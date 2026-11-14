import json
import math

import pandas as pd

from compute_indices import SECTOR_ETFS
from compute_stocks import INDEX_LABELS, build_stocks

END = "2026-10-01"


def idx(n, end=END):
    return pd.bdate_range(end=end, periods=n)


def series(n, start=100.0, step=0.1, end=END):
    return pd.Series([start + step * i for i in range(n)], index=idx(n, end))


def make(specs, n=300, labels=None, bench=True):
    """specs: list of dicts with ticker, universe, sector, name and optional close/vol Series."""
    uni = pd.DataFrame([{"ticker": s["ticker"], "name": s.get("name", s["ticker"] + " Inc"),
                         "universe": s["universe"], "sector": s.get("sector")} for s in specs])
    base = idx(n)
    cl, vo = {}, {}
    for s in specs:
        if s.get("missing"):
            continue
        c = s.get("close", series(n))
        cl[s["ticker"]] = c
        vo[s["ticker"]] = s.get("vol", pd.Series(1_000_000.0, index=c.index))
    close = pd.DataFrame(cl)
    volume = pd.DataFrame(vo)
    if labels is None:
        labels = pd.DataFrame(columns=["ticker", "sector", "industry", "mcap", "asof"])
    b = pd.Series([1000 + i + (i % 7) for i in range(n)], index=base) if bench else None
    return build_stocks(uni, close, volume, labels, b)


def by_ticker(stocks):
    return {s["s"]: s for s in stocks}


def lab(rows):
    return pd.DataFrame(rows, columns=["ticker", "sector", "industry", "mcap", "asof"])


def test_output_has_india_keys_plus_liq_dv():
    stocks, members, dates = make([{"ticker": "AAPL", "universe": "SP500", "sector": "Technology"}])
    s = stocks[0]
    for k in ("s", "n", "i", "p", "d1", "r", "sma50", "sma200", "a50", "a200", "gc", "bs", "bw", "beta", "corr",
              "vol", "mdd", "pos", "hi", "lo", "mc", "mck", "rk", "ser", "s50", "s200", "x", "liq", "dv"):
        assert k in s, k
    assert len(dates) == 260 and dates[-1] == END
    assert len(s["ser"]) == len(s["s50"]) == len(s["s200"]) == 260


def test_sector_from_spdr_for_sp500_and_yahoo_for_others():
    labels = lab([
        ("AAPL", "Energy", "Consumer Electronics", 3.5e12, "2026-10-01"),   # SP500: labels.sector ignored
        ("MID", "Industrials", "Machinery", 8e9, "2026-10-01"),
        ("SML", None, "Banks", None, "2026-10-01"),
    ])
    stocks, members, _ = make([
        {"ticker": "AAPL", "universe": "SP500", "sector": "Technology"},
        {"ticker": "MID", "universe": "SP400", "sector": None},
        {"ticker": "SML", "universe": "SP600", "sector": None},
    ], labels=labels)
    st = by_ticker(stocks)
    assert st["AAPL"]["x"] == ["Technology", "S&P 500"]
    assert st["MID"]["x"] == ["Industrials", "S&P 400"]
    assert st["SML"]["x"] == ["S&P 600"]           # no sector -> no sector label, still present
    assert st["AAPL"]["i"] == "Consumer Electronics"
    assert st["AAPL"]["mc"] == 3_500_000 and st["AAPL"]["mck"] == "yahoo"
    assert st["MID"]["mc"] == 8000
    assert st["SML"]["mc"] is None and st["SML"]["mck"] is None
    assert "AAPL" not in members["Energy"] and "AAPL" in members["Technology"]


def test_liquidity_flag_uses_price_and_dollar_volume():
    n = 300
    stocks, _, _ = make([
        {"ticker": "CHEAP", "universe": "SP600", "close": pd.Series(4.99, index=idx(n)),
         "vol": pd.Series(10_000_000.0, index=idx(n))},
        {"ticker": "THIN", "universe": "SP600", "close": pd.Series(50.0, index=idx(n)),
         "vol": pd.Series(1_000.0, index=idx(n))},
        {"ticker": "OK", "universe": "SP600", "close": pd.Series(50.0, index=idx(n)),
         "vol": pd.Series(200_000.0, index=idx(n))},
    ])
    st = by_ticker(stocks)
    assert st["CHEAP"]["liq"] is False
    assert st["THIN"]["liq"] is False
    assert st["OK"]["liq"] is True
    assert st["OK"]["dv"] == 10_000_000
    assert st["THIN"]["dv"] == 50_000


def test_dv_none_when_no_volume_and_liq_false():
    n = 300
    stocks, _, _ = make([{"ticker": "NOVOL", "universe": "SP500", "sector": "Energy",
                          "vol": pd.Series(float("nan"), index=idx(n))}])
    assert stocks[0]["dv"] is None and stocks[0]["liq"] is False


def test_short_history_stock_kept_with_none_long_returns():
    stocks, _, _ = make([
        {"ticker": "IPO", "universe": "SP400", "close": series(200)},
        {"ticker": "OLD", "universe": "SP500", "sector": "Utilities"},
    ])
    st = by_ticker(stocks)
    assert "IPO" in st
    assert st["IPO"]["r"]["5Y"] is None and st["IPO"]["r"]["3Y"] is None and st["IPO"]["r"]["1Y"] is None
    assert st["IPO"]["r"]["1M"] is not None
    assert st["IPO"]["ser"][0] is None and st["IPO"]["ser"][-1] is not None


def test_very_short_history_dropped():
    stocks, _, _ = make([{"ticker": "NEW", "universe": "SP600", "close": series(19)},
                         {"ticker": "OLD", "universe": "SP500", "sector": "Utilities"}])
    assert "NEW" not in by_ticker(stocks)


def test_stale_stock_dropped():
    stocks, members, _ = make([
        {"ticker": "STALE", "universe": "SP500", "sector": "Energy", "close": series(280, end="2026-09-15")},
        {"ticker": "FRESH", "universe": "SP500", "sector": "Energy"},
    ])
    st = by_ticker(stocks)
    assert "STALE" not in st and "FRESH" in st
    assert "STALE" not in members["Energy"] and "STALE" not in members["S&P 500"]


def test_ticker_missing_from_prices_skipped():
    stocks, members, _ = make([{"ticker": "GONE", "universe": "SP500", "sector": "Energy", "missing": True},
                               {"ticker": "HERE", "universe": "SP500", "sector": "Energy"}])
    assert [s["s"] for s in stocks] == ["HERE"]
    assert members["Energy"] == ["HERE"]


def test_members_contain_sector_and_index_labels():
    labels = lab([("MID", "Financials", "Banks", 5e9, "2026-10-01")])
    stocks, members, _ = make([
        {"ticker": "JPM", "universe": "SP500", "sector": "Financials"},
        {"ticker": "MID", "universe": "SP400"},
        {"ticker": "SML", "universe": "SP600"},
    ], labels=labels)
    assert set(members) == set(SECTOR_ETFS) | set(INDEX_LABELS.values())
    assert set(INDEX_LABELS.values()) == {"S&P 500", "S&P 400", "S&P 600"}
    assert members["Financials"] == ["JPM", "MID"]
    assert members["S&P 500"] == ["JPM"] and members["S&P 400"] == ["MID"] and members["S&P 600"] == ["SML"]
    assert members["Technology"] == []
    present = {s["s"] for s in stocks}
    for label, ticks in members.items():
        assert set(ticks) <= present
        for t in ticks:
            assert label in by_ticker(stocks)[t]["x"]


def test_goog_and_googl_both_present_single_sector():
    stocks, members, _ = make([
        {"ticker": "GOOGL", "universe": "SP500", "sector": "Communication Services"},
        {"ticker": "GOOG", "universe": "SP500", "sector": "Communication Services"},
        {"ticker": "BRK-B", "universe": "SP500", "sector": "Financials"},
        {"ticker": "GOOG", "universe": "SP500", "sector": "Communication Services"},   # duplicate universe row
    ])
    st = by_ticker(stocks)
    assert len(stocks) == 3
    assert {"GOOG", "GOOGL", "BRK-B"} == set(st)
    assert st["BRK-B"]["x"] == ["Financials", "S&P 500"]
    assert sorted(members["Communication Services"]) == ["GOOG", "GOOGL"]
    for label, ticks in members.items():
        assert len(ticks) == len(set(ticks)), label
    assert st["GOOG"]["x"] == ["Communication Services", "S&P 500"]


def test_company_name_with_angle_bracket_is_preserved_unescaped():
    stocks, _, _ = make([{"ticker": "ODD", "universe": "SP500", "sector": "Energy",
                          "name": 'A<B> & "Q" Corp\'s'}])
    assert stocks[0]["n"] == 'A<B> & "Q" Corp\'s'


def test_rank_by_mcap_then_dollar_volume():
    n = 300
    labels = lab([("BIG", None, None, 2e12, "x"), ("SMALL", None, None, 1e9, "x")])
    stocks, _, _ = make([
        {"ticker": "SMALL", "universe": "SP600"},
        {"ticker": "BIG", "universe": "SP500", "sector": "Technology"},
        {"ticker": "LOWDV", "universe": "SP600", "vol": pd.Series(10.0, index=idx(n))},
        {"ticker": "HIDV", "universe": "SP600", "vol": pd.Series(9e6, index=idx(n))},
        {"ticker": "NODV", "universe": "SP600", "vol": pd.Series(float("nan"), index=idx(n))},
    ], labels=labels)
    st = by_ticker(stocks)
    assert [st[t]["rk"] for t in ("BIG", "SMALL", "HIDV", "LOWDV", "NODV")] == [1, 2, 3, 4, 5]


def test_payload_serialises_without_nan():
    n = 300
    c = series(n)
    c.iloc[100:110] = float("nan")
    flat = pd.Series(10.0, index=idx(n))                       # hi == lo -> pos None
    infv = pd.Series(float("inf"), index=idx(n))
    stocks, members, dates = make([
        {"ticker": "GAP", "universe": "SP500", "sector": "Energy", "close": c},
        {"ticker": "FLAT", "universe": "SP600", "close": flat},
        {"ticker": "INFV", "universe": "SP400", "vol": infv},
        {"ticker": "IPO", "universe": "SP400", "close": series(30)},
    ], bench=False)
    json.dumps({"stocks": stocks, "members": members, "dates": dates}, allow_nan=False)

    def walk(v):
        if isinstance(v, float):
            assert not math.isnan(v) and not math.isinf(v)
        elif isinstance(v, dict):
            for x in v.values():
                walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)
    walk(stocks)
    st = by_ticker(stocks)
    assert st["FLAT"]["pos"] is None
    assert st["INFV"]["dv"] is None
