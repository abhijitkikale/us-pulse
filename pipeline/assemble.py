"""Payload contract: assemble the computed pieces into the one JSON object the page reads, plus the
staleness rule (vs the NYSE calendar) and a NaN/Inf scrubber so the JSON can be written strictly."""
import math

import numpy as np
import pandas as pd

import us_calendar
from us_config import PERIODS

TZ = "America/New_York"


def _day(ts):
    return None if ts is None or pd.isna(ts) else pd.Timestamp(ts).strftime("%d %b %Y")


def expected_session(today: pd.Timestamp):
    """The most recent trading day strictly before `today` (its close must be in the data)."""
    return us_calendar.prev_trading_day(pd.Timestamp(today).date())


def is_stale(price_asof, today) -> bool:
    """True when the latest price date is earlier than the last NYSE session before `today`.
    Weekends and exchange holidays are skipped via us_calendar, so Monday with Friday's close is fresh."""
    if price_asof is None or pd.isna(price_asof):
        return True
    return pd.Timestamp(price_asof).date() < expected_session(today)


def sanitize(obj):
    """Recursively replace NaN/Inf floats (incl. numpy scalars) with None; numpy ints/bools become Python ones."""
    if isinstance(obj, dict):
        return {k: sanitize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [sanitize(v) for v in obj]
    if isinstance(obj, (bool, np.bool_)):
        return bool(obj)
    if isinstance(obj, (int, np.integer)):
        return int(obj)
    if isinstance(obj, (float, np.floating)):
        f = float(obj)
        return None if math.isnan(f) or math.isinf(f) else f
    return obj


def today_ny() -> pd.Timestamp:
    """Today's date in New York (tz-naive midnight)."""
    return pd.Timestamp(pd.Timestamp.now(tz=TZ).date())


def assemble(indices, asof, members, stocks, dates, global_rows, activity, etfs, etf_categories, status,
             price_asof, today=None) -> dict:
    today = today_ny() if today is None else pd.Timestamp(today)
    stale = is_stale(price_asof, today)
    note = ""
    if stale:
        note = (f"Prices end {_day(price_asof) or 'unknown'}; the {_day(pd.Timestamp(expected_session(today)))} "
                f"close is missing")
    return {
        "built": pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%dT%H:%M:%SZ"),
        "asof": _day(asof), "stock_asof": _day(price_asof),
        "periods": list(PERIODS),
        "indices": list(indices.values()) if isinstance(indices, dict) else list(indices),
        "members": members, "stocks": stocks, "dates": dates,
        "global": global_rows, "activity": activity,
        "etfs": etfs, "etf_categories": etf_categories,
        "status": status, "stale": bool(stale), "stale_note": note,
        "universe_note": f"current constituents; {len(stocks):,} stocks",
        "mcap_note": "Market cap from Yahoo (total shares x price)",
        # India keys the shared template reads; not part of US v1
        "flows": [], "credit": None, "options": None,
    }
