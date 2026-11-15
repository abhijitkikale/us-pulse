"""Membership fetch tests: xlsx fixtures built in-test, fake `get`, no network."""
import io

import openpyxl
import pytest

from pipeline.fetch_membership import fetch_membership, parse_ssga_xlsx, yahoo_ticker
from pipeline.us_config import SECTOR_ETFS


def make_xlsx(rows):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Fund Name:", "Test ETF"])
    ws.append(["Ticker Symbol:", "TST"])
    ws.append(["Holdings: As of", "01-Jan-2026"])
    ws.append([])
    ws.append(["Name", "Ticker", "Identifier", "SEDOL", "Weight"])
    for name, tick, w in rows:
        ws.append([name, tick, "X", "Y", w])
    ws.append(["US DOLLAR", "CASH", "-", "-", 0.1])
    ws.append(["The values shown are for information only; this is a disclaimer.", None, None, None, None])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


class Resp:
    def __init__(self, content, status=200):
        self.content = content
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def fake_get(files):
    """files: lowercase ticker -> list of rows (or None for a 404)."""
    def get(url, timeout=None, **kw):
        assert timeout is not None
        ua = kw.get("headers", {}).get("User-Agent", "")
        assert ua.startswith("Mozilla/5.0") and "python-requests" not in ua
        assert kw.get("verify", True) is True
        tick = url.rsplit("holdings-daily-us-en-", 1)[1].split(".")[0]
        assert tick == tick.lower()
        rows = files.get(tick)
        if rows is None:
            return Resp(b"", 404)
        return Resp(make_xlsx(rows))
    return get


def test_parse_ssga_xlsx_finds_header_and_drops_footer():
    df = parse_ssga_xlsx(make_xlsx([("Apple", "aapl", 5.0), ("Microsoft", "MSFT", 4.0), ("Nvidia", "NVDA", 3.0)]))
    assert list(df.columns) == ["ticker", "name", "weight"]
    assert list(df["ticker"]) == ["AAPL", "MSFT", "NVDA"]


def test_yahoo_ticker_maps_dots():
    assert yahoo_ticker("BRK.B") == "BRK-B"
    assert yahoo_ticker("BF.B") == "BF-B"


def _all_sectors(extra=None):
    files = {t.lower(): [] for t in SECTOR_ETFS.values()}
    files["xlk"] = [("Apple", "AAPL", 1.0)]
    files["spy"] = [("Apple", "AAPL", 1.0)]
    files["spmd"] = [("Mid", "MID", 1.0)]
    files["spsm"] = [("Small", "SML", 1.0)]
    files.update(extra or {})
    return files


def test_universe_priority_dedup():
    files = _all_sectors({"spmd": [("Apple", "AAPL", 1.0), ("Mid", "MID", 1.0)],
                          "spsm": [("Mid", "MID", 1.0), ("Small", "SML", 1.0)]})
    df, status = fetch_membership(get=fake_get(files))
    assert df["ticker"].is_unique
    u = dict(zip(df["ticker"], df["universe"]))
    assert u == {"AAPL": "SP500", "MID": "SP400", "SML": "SP600"}
    sec = dict(zip(df["ticker"], df["sector"]))
    assert sec["AAPL"] == "Technology" and sec["MID"] is None
    assert list(df.columns) == ["ticker", "name", "universe", "sector"]


def test_fetch_membership_reports_failure_not_raise():
    def boom(url, **kw):
        raise ConnectionError("down")
    df, status = fetch_membership(get=boom)
    assert df.empty and status.startswith("failed")
    assert list(df.columns) == ["ticker", "name", "universe", "sector"]


def test_partial_failure_reported():
    files = _all_sectors()
    del files["spsm"]
    df, status = fetch_membership(get=fake_get(files))
    assert "partial" in status and not df.empty


def test_share_classes_both_kept_once_each():
    files = _all_sectors({"xlc": [("Alphabet C", "GOOG", 1.0), ("Alphabet A", "GOOGL", 1.0)],
                          "xlf": [("Berkshire", "BRK.B", 1.0)]})
    df, _ = fetch_membership(get=fake_get(files))
    assert (df["ticker"] == "GOOG").sum() == 1 and (df["ticker"] == "GOOGL").sum() == 1
    assert "BRK-B" in set(df["ticker"])


JUNK = [("Fut", "IXTZ6", 0.1), ("Fut2", "FAZ6", 0.1), ("Swap", "2602335D", 0.1), ("Cash", "CASH", 0.1), ("Dollar", "USD", 0.1)]
REAL = [("Apple", "AAPL", 5.0), ("Berkshire", "BRK.B", 4.0), ("Brown", "BF.B", 3.0), ("Alphabet", "GOOG", 2.0)]


def test_non_equity_rows_dropped():
    df = parse_ssga_xlsx(make_xlsx(JUNK + REAL))
    assert set(df["ticker"]) == {"AAPL", "BRK.B", "BF.B", "GOOG"}


def test_fetch_drops_futures_and_keeps_share_classes():
    files = _all_sectors({"xlk": JUNK + REAL})
    df, _ = fetch_membership(get=fake_get(files))
    t = set(df["ticker"])
    assert {"AAPL", "BRK-B", "BF-B", "GOOG"} <= t
    assert not t & {"IXTZ6", "FAZ6", "2602335D", "CASH", "USD"}


def _names(n):
    import itertools, string
    gen = ("".join(c) for c in itertools.product(string.ascii_uppercase, repeat=3))
    return [(f"N{i}", next(gen), 1.0) for i in range(n)]


def test_count_note_only_when_out_of_range():
    in_range = _all_sectors({"xlk": _names(500), "spy": _names(500)})
    _, st = fetch_membership(get=fake_get(in_range))
    assert "outside 490-510" not in st
    out = _all_sectors({"xlk": _names(515), "spy": _names(504)})
    _, st = fetch_membership(get=fake_get(out))
    assert "outside 490-510" in st
