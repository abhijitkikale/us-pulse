import json

import numpy as np
import pandas as pd

from pipeline.compute_activity import build_activity


def _frames(n_days, cols, close_fn, vol_fn):
    idx = pd.bdate_range("2025-01-01", periods=n_days)
    close = pd.DataFrame({c: [close_fn(c, i) for i in range(n_days)] for c in cols}, index=idx, dtype=float)
    vol = pd.DataFrame({c: [vol_fn(c, i) for i in range(n_days)] for c in cols}, index=idx, dtype=float)
    return close, vol


def test_breadth_counts_adv_dec_unch():
    def close(c, i):
        return {"UP": 10 + i, "DN": 10 - i * 0.1, "FLAT": 10}[c]
    c, v = _frames(5, ["UP", "DN", "FLAT"], close, lambda c, i: 1000)
    out = build_activity(c, v)
    assert out["n_stocks"] == 3
    assert (out["breadth"]["adv"][-1], out["breadth"]["dec"][-1], out["breadth"]["unch"][-1]) == (1, 1, 1)
    assert out["asof"] == c.index[-1].strftime("%Y-%m-%d")


def test_spike_requires_ratio_and_dollar_volume():
    def vol(c, i):
        last = i == 24
        return {"BIG": 2_000_000 if last else 100_000,      # 20x, $20M+ -> spike
                "CHEAP": 2_000 if last else 100,            # 20x but tiny dollar volume
                "STEADY": 1_000_000}[c]
    c, v = _frames(25, ["BIG", "CHEAP", "STEADY"], lambda c, i: 10 + i * 0.01, vol)
    out = build_activity(c, v)
    assert [r["s"] for r in out["spikes"]] == ["BIG"]
    r = out["spikes"][0]
    assert r["x"] == 20.0 and r["dp"] is None and r["tcr"] > 5
    assert out["params"] == {"spike_x": 2.0, "min_dollar_vol": 5_000_000, "avg_days": 20}
    assert [x["s"] for x in out["leaders"]["turnover"]][0] == "BIG"
    assert set(out["leaders"]["volume"][0]) == {"s", "p", "chg", "vol", "avg", "x", "tcr", "dp"}


def test_empty_input_returns_none():
    assert build_activity(None, None) is None
    e = pd.DataFrame()
    assert build_activity(e, e) is None


def test_breadth_history_length_capped():
    c, v = _frames(300, ["A", "B"], lambda c, i: 10 + i, lambda c, i: 1000)
    b = build_activity(c, v)["breadth"]
    assert len(b["d"]) == len(b["adv"]) == len(b["dec"]) == len(b["unch"]) == len(b["turn"]) == 260
    assert len(build_activity(c, v, tail_days=50)["breadth"]["d"]) == 50
    c2, v2 = _frames(30, ["A"], lambda c, i: 10 + i, lambda c, i: 1000)
    assert len(build_activity(c2, v2)["breadth"]["d"]) == 29     # first day has no previous close


def test_result_is_strict_json():
    c, v = _frames(30, ["A", "B"], lambda c, i: 10 + i, lambda c, i: 1000)
    c.iloc[5, 0] = np.nan
    v.iloc[3, 1] = np.nan
    json.dumps(build_activity(c, v), allow_nan=False)


def test_nan_last_close_excluded_from_today():
    c, v = _frames(25, ["A", "B", "C"], lambda c, i: 10 + i, lambda c, i: 1000)
    c.iloc[-1, 0] = np.nan
    out = build_activity(c, v)
    assert out["n_stocks"] == 2
    assert out["breadth"]["adv"][-1] == 2
    assert "A" not in [r["s"] for r in out["leaders"]["turnover"]]
    json.dumps(out, allow_nan=False)
