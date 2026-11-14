import json
import math
import re
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import us_config
from assemble import assemble, is_stale, sanitize

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "pipeline" / "template.html"


@pytest.mark.parametrize("today, data, stale", [
    ("2026-11-16", "2026-11-13", False),   # Monday, Friday's close present
    ("2026-11-17", "2026-11-13", True),    # Tuesday, Monday's close missing
    ("2026-11-14", "2026-11-13", False),   # Saturday, Friday's close present
    ("2026-11-15", "2026-11-12", True),    # Sunday, Friday's close missing
    ("2026-11-27", "2026-11-25", False),   # day after Thanksgiving (Thu 26 Nov closed): Wed is the previous session
    ("2026-11-30", "2026-11-25", True),    # Monday after: the Friday 27 Nov early-close session is missing
    ("2026-11-30", "2026-11-27", False),
    ("2026-11-17", "2026-11-17", False),   # same-day data is never stale
])
def test_is_stale_uses_previous_trading_day(today, data, stale):
    assert is_stale(pd.Timestamp(data), pd.Timestamp(today)) is stale


def test_is_stale_missing_price_date_is_stale():
    assert is_stale(None, pd.Timestamp("2026-11-16")) is True


def test_sanitize_replaces_nan_inf():
    p = {"a": float("nan"), "b": [1.0, float("inf"), -float("inf"), np.float64("nan"), np.float32(2.5)],
         "c": {"d": (np.int64(3), np.bool_(True), None, "x")}, "e": 1}
    out = sanitize(p)
    assert out == {"a": None, "b": [1.0, None, None, None, 2.5], "c": {"d": [3, True, None, "x"]}, "e": 1}
    assert type(out["c"]["d"][0]) is int and type(out["c"]["d"][1]) is bool and type(out["b"][4]) is float
    json.dumps(out, allow_nan=False)


def _args(n_stocks=3, price_asof="2026-11-13"):
    ix = {"S&P 500": {"label": "S&P 500", "group": "benchmark", "close": 6000.0, "chg": float("nan")}}
    stocks = [{"s": f"T{i}", "n": f"Name {i}", "p": 10.0 + i} for i in range(n_stocks)]
    return dict(indices=ix, asof=pd.Timestamp("2026-11-13"), members={"S&P 500": ["T0"]}, stocks=stocks,
                dates=["2026-11-13"], global_rows=[{"name": "DAX (Germany)", "local": {}, "usd": {}}],
                activity={"asof": "2026-11-13"}, etfs=[{"t": "XLK"}], etf_categories=["US Sector"],
                status={"prices": "ok"}, price_asof=pd.Timestamp(price_asof))


def test_assemble_payload_shape():
    p = assemble(**_args(1432), today=pd.Timestamp("2026-11-16"))
    assert p["asof"] == "13 Nov 2026" and p["stock_asof"] == "13 Nov 2026"
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", p["built"])
    assert p["periods"] == us_config.PERIODS
    assert isinstance(p["indices"], list) and p["indices"][0]["label"] == "S&P 500"
    assert p["global"][0]["name"] == "DAX (Germany)"
    assert p["universe_note"] == "current constituents; 1,432 stocks"
    assert p["stale"] is False and p["stale_note"] == ""
    assert p["flows"] == [] and p["credit"] is None and p["options"] is None
    for k in ("members", "stocks", "dates", "activity", "etfs", "etf_categories", "status"):
        assert k in p


def test_assemble_flags_stale_prices():
    p = assemble(**_args(price_asof="2026-11-12"), today=pd.Timestamp("2026-11-17"))
    assert p["stale"] is True
    assert "12 Nov 2026" in p["stale_note"] and "16 Nov 2026" in p["stale_note"]


def test_assemble_payload_serialises_strict():
    p = sanitize(assemble(**_args(), today=pd.Timestamp("2026-11-16")))
    s = json.dumps(p, allow_nan=False)
    assert json.loads(s)["indices"][0]["chg"] is None


# JS names reached through `D.` that are not payload keys (Date methods etc. in the template)
_NOT_KEYS = {"length", "map", "on", "at", "getFullYear", "setFullYear", "toISOString", "toLocaleDateString",
             "removeAllListeners"}


def test_assemble_has_every_key_the_template_reads():
    keys = set(re.findall(r"\bD\.([A-Za-z_]\w*)", TEMPLATE.read_text(encoding="utf-8"))) - _NOT_KEYS
    p = assemble(**_args(), today=pd.Timestamp("2026-11-16"))
    assert keys <= set(p), sorted(keys - set(p))
