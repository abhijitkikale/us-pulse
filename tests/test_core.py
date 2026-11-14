import numpy as np
import pandas as pd

from compute_core import _num, period_returns, risk_stats, trend_flags


def series(n, f):
    idx = pd.bdate_range(end="2026-10-01", periods=n)
    return pd.Series([f(i) for i in range(n)], index=idx)


def test_simple_1m_return():
    s = pd.Series([100.0, 110.0], index=pd.to_datetime(["2026-09-01", "2026-10-01"]))
    assert period_returns(s)["1M"] == 10.0


def test_short_history_gives_none():
    r = period_returns(series(30, lambda i: 100 + i))
    assert r["1W"] is not None and r["1Y"] is None and r["5Y"] is None


def test_annualised_3y():
    idx = pd.to_datetime(["2023-10-01", "2026-10-01"])
    r = period_returns(pd.Series([100.0, 133.1], index=idx))
    assert abs(r["3Y"] - 10.0) < 0.05          # 1.1^3 = 1.331 -> 10% p.a.


def test_trend_up_is_brutal_strength():
    f = trend_flags(series(300, lambda i: 100 + i))
    assert f["bs"] and f["gc"] and f["a50"] and f["a200"] and not f["bw"]


def test_trend_down_is_brutal_weakness():
    f = trend_flags(series(300, lambda i: 500 - i))
    assert f["bw"] and not f["gc"] and not f["a50"] and not f["bs"]


def test_too_short_for_flags():
    assert trend_flags(series(20, lambda i: i + 1)) is None


def test_one_day_return_uses_previous_close():
    s = pd.Series([100.0, 105.0, 99.75], index=pd.to_datetime(["2026-09-29", "2026-09-30", "2026-10-01"]))
    assert period_returns(s)["1D"] == -5.0


def test_short_history_gives_none_for_long_periods():
    r = period_returns(series(200, lambda i: 100 + i))
    assert r["3Y"] is None and r["5Y"] is None
    assert isinstance(r["1M"], float)


def test_short_history_flags_and_risk_are_none_or_partial():
    assert trend_flags(series(49, lambda i: 100 + i)) is None
    f = trend_flags(series(100, lambda i: 100 + i))     # 50..199 obs: no 200-day flags
    assert f["sma200"] is None and f["a200"] is None and f["gc"] is None
    assert f["bs"] is None and f["bw"] is None and f["a50"] is True
    s = series(40, lambda i: 100 + i)
    assert risk_stats(s, s) == {"beta": None, "corr": None, "vol": None, "mdd": None}
    assert period_returns(pd.Series(dtype=float)) == {k: None for k in period_returns(series(3, lambda i: 1 + i))}


def test_risk_stats_beta_of_doubled_benchmark():
    rng = np.random.default_rng(0)
    b = pd.Series(100 * np.cumprod(1 + rng.normal(0, 0.01, 300)), index=pd.bdate_range(end="2026-10-01", periods=300))
    c = 100 * (b / b.iloc[0]) ** 2
    r = risk_stats(c, b)
    assert r["corr"] > 0.99 and r["beta"] > 1.5 and r["vol"] > 0 and r["mdd"] <= 0
    assert risk_stats(c, None)["beta"] is None and risk_stats(c, None)["mdd"] is not None


def test_nan_inf_become_none():
    assert _num(float("inf")) is None
    assert _num(float("nan")) is None
    assert _num(None) is None and _num(1.2345) == 1.23
