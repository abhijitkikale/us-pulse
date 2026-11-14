import pandas as pd
import pytest

from compute_indices import add_equal_weight, build_global, build_indices


def frame(cols, n=300):
    idx = pd.bdate_range(end="2026-10-01", periods=n)
    return pd.DataFrame({k: [f(i) for i in range(n)] for k, f in cols.items()}, index=idx)


def flat(v):
    return lambda i: v


def test_entry_has_india_keys():
    close = frame({"^GSPC": lambda i: 100 + i, "XLK": lambda i: 50 + i, "SMH": lambda i: 20 + i})
    idx, asof, piv = build_indices(close)
    assert asof == close.index.max()
    assert set(piv.columns) == {"^GSPC", "XLK", "SMH"}
    for label, group in (("S&P 500", "benchmark"), ("Technology", "sector"), ("Semiconductors", "theme")):
        e = idx[label]
        assert e["group"] == group
        for k in ("label", "group", "nse", "csv", "close", "chg", "ret", "pe", "pb", "dy", "wk", "pes"):
            assert k in e
        assert e["csv"] is None and e["pe"] is None and e["pb"] is None and e["dy"] is None
        assert e["pes"] == {"d": [], "pe": [], "pb": [], "dy": []}
        assert set(e["wk"]) == {"d", "c"} and len(e["wk"]["d"]) <= 262
    assert idx["Technology"]["nse"] == "XLK"


def test_relative_strength_is_difference_vs_spx():
    close = frame({"^GSPC": flat(100.0), "XLK": flat(100.0)})
    close.iloc[-1] = [102.0, 105.0]
    # 1M base: the whole history is flat at 100 so 1M return is last/100-1
    idx, _, _ = build_indices(close)
    assert idx["Technology"]["ret"]["1M"] == 5.0
    assert idx["Technology"]["rs"]["1M"] == pytest.approx(3.0)


def test_rs_none_when_either_side_none():
    close = frame({"^GSPC": flat(100.0), "XLK": flat(100.0)}, n=300)
    close.loc[close.index[:-10], "XLK"] = float("nan")
    idx, _, _ = build_indices(close)
    assert idx["Technology"]["ret"]["1Y"] is None
    assert idx["Technology"]["rs"]["1Y"] is None


def test_missing_symbol_is_skipped_not_raised():
    close = frame({"^GSPC": flat(100.0)})
    idx, _, _ = build_indices(close)
    assert list(idx) == ["S&P 500"]


def _members(rets, n=300):
    cols = {}
    for k, r in rets.items():
        cols[k] = flat(100.0)
    df = frame(cols, n)
    for k, r in rets.items():
        df.iloc[-1, df.columns.get_loc(k)] = 100.0 * (1 + r / 100)
    return df


def test_equal_weight_averages_members():
    close = _members({"A": 1, "B": 2, "C": 6, "D": 3, "E": 3})
    indices = {"Technology": {"group": "sector"}, "S&P 500": {"group": "benchmark"}}
    members = {"Technology": list("ABCDE"), "S&P 500": list("ABCDE")}
    add_equal_weight(indices, members, close)
    assert indices["Technology"]["ew"]["1M"] == pytest.approx(3.0)
    assert "ew" not in indices["S&P 500"]


def test_equal_weight_needs_five_members():
    close = _members({"A": 1, "B": 2, "C": 6, "D": 3})
    indices = {"Technology": {"group": "sector"}}
    members = {"Technology": list("ABCD"), "S&P 500": list("ABCD")}
    add_equal_weight(indices, members, close)
    assert indices["Technology"]["ew"]["1M"] is None


def test_equal_weight_uses_intersection_with_spx():
    close = _members({"A": 1, "B": 2, "C": 6, "D": 3, "E": 3, "F": 50})
    indices = {"Technology": {"group": "sector"}}
    members = {"Technology": list("ABCDEF"), "S&P 500": list("ABCDE")}
    add_equal_weight(indices, members, close)
    assert indices["Technology"]["ew"]["1M"] == pytest.approx(3.0)


def test_build_global_converts_with_fx():
    n = 300
    close = frame({
        "^N225": lambda i: 100.0 if i < n - 1 else 110.0,
        "JPY=X": lambda i: 100.0 if i < n - 1 else 100.0 / 0.95,   # yen loses 5% vs USD
        "^GSPC": flat(100.0),
    }, n)
    rows = {r["name"]: r for r in build_global(close)}
    j = rows["Nikkei 225 (Japan)"]
    assert j["local"]["1M"] == pytest.approx(10.0)
    assert j["usd"]["1M"] == pytest.approx(4.5, abs=0.01)
    assert "FTSE 100 (UK)" not in rows
    us = rows["S&P 500 (USA)"]
    assert us["local"] == us["usd"]
