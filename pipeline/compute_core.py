"""Core return / trend / risk functions (ported from the India dashboard's compute.py, unchanged)."""
import math
import pandas as pd
from us_config import PERIODS

OFFSETS = {"1W": pd.DateOffset(days=7), "1M": pd.DateOffset(months=1), "3M": pd.DateOffset(months=3),
           "6M": pd.DateOffset(months=6), "1Y": pd.DateOffset(years=1), "3Y": pd.DateOffset(years=3),
           "5Y": pd.DateOffset(years=5)}
YEARS = {"3Y": 3, "5Y": 5}


def _num(x, nd=2):
    if x is None:
        return None
    x = float(x)
    return None if math.isnan(x) or math.isinf(x) else round(x, nd)


def period_returns(s: pd.Series, asof=None, tolerance_days=6):
    """% return per period from a date-indexed close series. 3Y/5Y are annualised. None if history is too short."""
    s = s.dropna()
    out = {p: None for p in PERIODS}
    if s.empty:
        return out
    asof = asof or s.index[-1]
    s = s[s.index <= asof]
    if s.empty:
        return out
    last = s.iloc[-1]
    if len(s) >= 2:                      # 1D = change vs the previous trading day's close
        out["1D"] = _num((last / s.iloc[-2] - 1) * 100)
    for p, off in OFFSETS.items():
        target = asof - off
        if s.index[0] > target + pd.Timedelta(days=tolerance_days):
            continue
        before = s[s.index <= target]
        base = before.iloc[-1] if len(before) else s.iloc[0]
        r = last / base
        if p in YEARS:
            r = r ** (1 / YEARS[p])
        out[p] = _num((r - 1) * 100)
    return out


def trend_flags(close: pd.Series):
    """SMA-based flags used by the strength/weakness and breadth panels."""
    c = close.dropna()
    if len(c) < 50:
        return None
    p = c.iloc[-1]
    s25, s50 = c.rolling(25).mean().iloc[-1], c.rolling(50).mean().iloc[-1]
    s200 = c.rolling(200).mean().iloc[-1] if len(c) >= 200 else float("nan")
    ok200 = not math.isnan(s200)
    return {
        "sma50": _num(s50), "sma200": _num(s200) if ok200 else None,
        "a50": bool(p > s50), "a200": bool(p > s200) if ok200 else None,
        "gc": bool(s50 > s200) if ok200 else None,                       # golden cross state (50 > 200)
        "bs": bool(p > s25 > s50 > s200) if ok200 else None,             # brutal strength
        "bw": bool(p < s25 < s50 < s200) if ok200 else None,             # brutal weakness
    }


def risk_stats(c, bench, min_obs=120):
    """Beta, correlation, annualised volatility and max drawdown over ~1 year; daily returns on the benchmark's own trading days."""
    out = {"beta": None, "corr": None, "vol": None, "mdd": None}
    c = c.dropna()
    yr = c.tail(252)
    if len(yr) >= 60:
        out["mdd"] = _num(((yr / yr.cummax()) - 1).min() * 100, 1)
    if bench is not None:
        df = pd.concat([c.rename("s"), bench.rename("b")], axis=1).dropna().tail(253)
        r = df.pct_change().dropna()
        if len(r) >= min_obs and r["b"].var() > 0:
            out["beta"] = _num(r["s"].cov(r["b"]) / r["b"].var(), 2)
            out["corr"] = _num(r["s"].corr(r["b"]), 2)
            out["vol"] = _num(r["s"].std() * (252 ** 0.5) * 100, 1)
    return out
