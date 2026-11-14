import json
import re

import pandas as pd

from compute_etf import CATEGORIES, UNIVERSE_CSV, build_etf
from us_config import SECTOR_ETFS, THEMES

END = "2026-10-01"
BANNED = re.compile(r"2X|3X|Ultra|Short|Inverse|Bear|Bull", re.I)


def universe():
    return pd.read_csv(UNIVERSE_CSV)


def series(n, start=100.0, step=0.1):
    return pd.Series([start + step * i for i in range(n)], index=pd.bdate_range(end=END, periods=n))


def make(specs, n=300, bench=None):
    """specs: list of (ticker, category, close Series | None for missing)."""
    uni = pd.DataFrame([{"ticker": t, "name": t + " Fund", "category": c} for t, c, _ in specs])
    cl = {t: s for t, _, s in specs if s is not None}
    close = pd.DataFrame(cl)
    volume = pd.DataFrame({t: pd.Series(1_000_000.0, index=s.index) for t, s in cl.items()})
    return build_etf(uni, close, volume, bench)


# ---- universe file ----

def test_universe_size_between_200_and_300():
    assert 200 <= len(universe()) <= 300


def test_no_leveraged_or_inverse_names():
    u = universe()
    bad = [n for n in u["name"] if BANNED.search(n)]
    assert not bad, bad
    assert not u["name"].str.contains("VIX|Volatility Index", case=False).any()


def test_tickers_unique_and_categories_valid():
    u = universe()
    assert list(u.columns) == ["ticker", "name", "category"]
    assert u["ticker"].is_unique
    assert set(u["category"]) == set(CATEGORIES)
    assert len(CATEGORIES) == 11
    assert u["name"].notna().all() and u["ticker"].str.fullmatch(r"[A-Z]{1,5}").all()
    cat = dict(zip(u["ticker"], u["category"]))
    for t in SECTOR_ETFS.values():
        assert cat.get(t) == "US Sector", t
    for t in THEMES.values():
        assert cat.get(t) == "Theme", t
    for t in ("SPY", "QQQ", "DIA", "IWM", "IJR"):
        assert cat.get(t) == "Size", t


def test_every_category_has_at_least_5():
    counts = universe()["category"].value_counts()
    for c in CATEGORIES:
        assert counts.get(c, 0) >= 5, c


# ---- builder ----

def test_build_etf_drops_short_history():
    etfs, cats = make([("AAA", "Bonds", series(300)), ("BBB", "Theme", series(19)),
                       ("CCC", "Size", series(20)), ("DDD", "Theme", None)])
    assert [e["t"] for e in etfs] == ["AAA", "CCC"]
    assert cats == ["Bonds", "Size"]
    short = etfs[1]                                       # 20 obs: kept, trend keys present but None
    for k in ("a50", "a200", "gc", "bs", "bw", "vol", "mdd"):
        assert k in short and short[k] is None, k
    assert short["dv"] is not None


def test_build_etf_returns_periods_and_flags():
    bench = pd.Series([1000 + i + (i % 7) for i in range(300)], index=pd.bdate_range(end=END, periods=300))
    zig = series(300) * pd.Series([1 + 0.01 * ((i % 5) - 2) for i in range(300)],
                                  index=pd.bdate_range(end=END, periods=300))
    etfs, cats = make([("UP", "Commodities", zig)], bench=bench)
    e = etfs[0]
    for k in ("t", "n", "c", "p", "d1", "r", "a50", "a200", "gc", "bs", "bw", "vol", "mdd", "dv", "ser"):
        assert k in e, k
    assert e["t"] == "UP" and e["n"] == "UP Fund" and e["c"] == "Commodities"
    assert set(e["r"]) >= {"1D", "1W", "1M", "3M", "6M", "1Y", "3Y", "5Y"}
    assert e["r"]["1M"] is not None and e["r"]["3Y"] is None
    assert e["p"] == round(float(zig.iloc[-1]), 2)
    assert e["d1"] == round((zig.iloc[-1] / zig.iloc[-2] - 1) * 100, 2)
    assert e["a50"] is True and e["a200"] is True and e["gc"] is True
    assert isinstance(e["vol"], float) and e["vol"] > 0
    assert e["mdd"] <= 0
    assert len(e["ser"]) == 260 and e["ser"][-1] == e["p"]
    assert e["dv"] == round(float((zig.tail(20) * 1_000_000).mean()), 0)
    assert cats == ["Commodities"]


def test_build_etf_without_bench_has_no_vol():
    etfs, _ = make([("AAA", "Bonds", series(300))])
    assert etfs[0]["vol"] is None and etfs[0]["mdd"] is not None


def test_build_etf_output_is_strict_json():
    s = series(300)
    s.iloc[100:110] = float("nan")
    etfs, cats = make([("AAA", "Bonds", s), ("BBB", "Theme", series(30))])
    json.dumps({"etfs": etfs, "cats": cats}, allow_nan=False)
