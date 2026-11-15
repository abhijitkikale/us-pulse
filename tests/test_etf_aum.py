import datetime as dt
import json

import pandas as pd
import pytest

import fetch_etf_aum as fa
from compute_etf import build_etf

TODAY = dt.date(2026, 11, 15)
BAD = ("stale", "failed", "partial")


def _cache(path, rows):
    pd.DataFrame(rows, columns=["ticker", "aum", "asof"]).to_csv(path, index=False)


class Fetcher:
    def __init__(self, values):
        self.values, self.calls = values, []

    def __call__(self, t):
        self.calls.append(t)
        v = self.values.get(t)
        if isinstance(v, Exception):
            raise v
        return v


def test_only_missing_or_stale_tickers_are_fetched(tmp_path):
    p = tmp_path / "aum.csv"
    _cache(p, [("AAA", 1e9, "2026-11-10"), ("BBB", 2e9, "2026-09-01"), ("CCC", None, "2026-11-10")])
    f = Fetcher({"BBB": 3e9, "CCC": 4e9, "DDD": 5e9})
    df, status = fa.fetch_etf_aum(["AAA", "BBB", "CCC", "DDD"], p, fetcher=f, today=TODAY, sleep=lambda s: None)
    assert f.calls == ["BBB", "CCC", "DDD"]                  # AAA is fresh; CCC had no value; DDD is new
    got = dict(zip(df["ticker"], df["aum"]))
    assert got == {"AAA": 1e9, "BBB": 3e9, "CCC": 4e9, "DDD": 5e9}
    assert status.startswith("ok (4 of 4 have AUM)"), status
    saved = pd.read_csv(p)
    assert set(saved["ticker"]) == {"AAA", "BBB", "CCC", "DDD"}
    assert dict(zip(saved["ticker"], saved["asof"]))["BBB"] == "2026-11-15"


def test_max_new_caps_fetches_and_pauses_between_calls(tmp_path):
    p = tmp_path / "aum.csv"
    f = Fetcher({t: 1e8 for t in "ABCDE"})
    pauses = []
    df, status = fa.fetch_etf_aum(list("ABCDE"), p, fetcher=f, max_new=2, today=TODAY, sleep=pauses.append)
    assert f.calls == ["A", "B"] and pauses == [fa.FETCH_DELAY]
    assert "3 remaining" in status and status.startswith("ok (2 of 5 have AUM)")
    df2, _ = fa.fetch_etf_aum(list("ABCDE"), p, fetcher=f, max_new=0, today=TODAY, sleep=pauses.append)
    assert f.calls == ["A", "B"] and len(df2) == 2           # max_new=0 (the --cached build) only reads


def test_failed_fetch_keeps_old_row_and_never_raises(tmp_path):
    p = tmp_path / "aum.csv"
    _cache(p, [("AAA", 7e9, "2026-01-01"), ("BBB", 1e9, "2026-01-01")])
    f = Fetcher({"AAA": RuntimeError("boom"), "BBB": None})
    df, status = fa.fetch_etf_aum(["AAA", "BBB", "CCC"], p, fetcher=f, today=TODAY, sleep=lambda s: None)
    assert dict(zip(df["ticker"], df["aum"])) == {"AAA": 7e9, "BBB": 1e9}
    assert "failed 3" in status and not status.startswith(BAD)
    assert pd.read_csv(p)["asof"].tolist() == ["2026-01-01", "2026-01-01"]


@pytest.mark.parametrize("setup", ["empty", "all_fail", "corrupt", "crash"])
def test_status_never_starts_with_a_bad_word(tmp_path, setup, monkeypatch):
    p = tmp_path / "aum.csv"
    fetcher = Fetcher({})
    if setup == "corrupt":
        p.write_bytes(b"\x00\xff garbage,,,\n\x01")
    if setup == "all_fail":
        fetcher = Fetcher({"A": RuntimeError("x"), "B": ValueError("y")})
    if setup == "crash":
        monkeypatch.setattr(fa, "_read_cache", lambda c: 1 / 0)
    df, status = fa.fetch_etf_aum(["A", "B"], p, fetcher=fetcher, today=TODAY, sleep=lambda s: None)
    assert status.startswith("unavailable ("), status
    assert not status.startswith(BAD)
    assert list(df.columns) == ["ticker", "aum", "asof"]


def test_default_fetcher_reads_total_assets_then_net_assets(monkeypatch):
    import sys
    import types

    infos = {"A": {"totalAssets": 1.5e9}, "B": {"netAssets": 2e8}, "C": {}, "D": None}

    class T:
        def __init__(self, t):
            if t == "E":
                raise RuntimeError("down")
            self.info = infos[t]

    monkeypatch.setitem(sys.modules, "yfinance", types.SimpleNamespace(Ticker=T))
    assert fa.default_fetcher("A") == 1.5e9 and fa.default_fetcher("B") == 2e8
    assert fa.default_fetcher("C") is None and fa.default_fetcher("D") is None and fa.default_fetcher("E") is None


def test_cache_is_written_in_whole_dollars(tmp_path):
    p = tmp_path / "aum.csv"
    fa.fetch_etf_aum(["A"], p, fetcher=lambda t: 123456789.75, today=TODAY, sleep=lambda s: None)
    assert p.read_text(encoding="utf-8").splitlines()[1] == "A,123456790,2026-11-15"


def test_committed_cache_shape():
    from us_config import DATA
    p = DATA / "etf_aum.csv"
    if not p.exists():
        pytest.skip("no committed AUM cache yet")
    df = pd.read_csv(p, dtype={"ticker": str, "asof": str})
    assert list(df.columns) == ["ticker", "aum", "asof"] and df["ticker"].is_unique
    assert (df["aum"].dropna() > 0).all()


# ---- build_etf with aum ----

def _etf_inputs():
    idx = pd.bdate_range(end="2026-10-01", periods=300)
    close = pd.DataFrame({t: pd.Series([100 + 0.1 * i for i in range(300)], index=idx) for t in ("AAA", "BBB", "CCC")})
    volume = pd.DataFrame({t: pd.Series(1e6, index=idx) for t in close})
    uni = pd.DataFrame([{"ticker": t, "name": t + " Fund", "category": "Bonds"} for t in close])
    return uni, close, volume


def test_build_etf_adds_aum_in_millions_and_strict_json():
    uni, close, volume = _etf_inputs()
    aum = pd.DataFrame({"ticker": ["AAA", "BBB", "ZZZ"], "aum": [12_345_000_000.0, float("nan"), 1e9],
                        "asof": ["2026-11-01"] * 3})
    etfs, _ = build_etf(uni, close, volume, aum=aum)
    got = {e["t"]: e["aum"] for e in etfs}
    assert got == {"AAA": 12345.0, "BBB": None, "CCC": None}
    json.dumps(etfs, allow_nan=False)                         # strict JSON
    etfs2, _ = build_etf(uni, close, volume, aum={"CCC": 400_000.0})
    assert {e["t"]: e["aum"] for e in etfs2} == {"AAA": None, "BBB": None, "CCC": 0.4}
    etfs3, _ = build_etf(uni, close, volume)
    assert all(e["aum"] is None for e in etfs3)
