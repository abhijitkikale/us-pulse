"""Sector / industry / market-cap labels from Yahoo, cached in a committed CSV (mcap in raw dollars)."""
import datetime as dt
import time
from pathlib import Path

import pandas as pd

from pipeline import us_config

COLUMNS = ["ticker", "sector", "industry", "mcap", "asof"]
FETCH_DELAY = 0.4  # seconds between Yahoo calls


_TARGETS = frozenset(us_config.YAHOO_SECTOR_MAP.values())


def normalize_sector(raw):
    if raw is None:
        return None
    if raw in _TARGETS:
        return raw
    return us_config.YAHOO_SECTOR_MAP.get(raw)


def default_fetcher(ticker):
    """Keep only sector, industry, marketCap; {} on any failure."""
    try:
        import yfinance as yf
        info = yf.Ticker(ticker).info or {}
        return {k: info.get(k) for k in ("sector", "industry", "marketCap") if info.get(k) is not None}
    except Exception:
        return {}


def _read_cache(cache_csv):
    p = Path(cache_csv)
    if not p.exists():
        return pd.DataFrame(columns=COLUMNS)
    try:
        df = pd.read_csv(p, dtype={"ticker": str, "asof": str})
        df = df.reindex(columns=COLUMNS)
        df["sector"] = [normalize_sector(x) if isinstance(x, str) else None for x in df["sector"]]
        return df
    except Exception:
        return pd.DataFrame(columns=COLUMNS)


def _needs_fetch(tickers, cache, today, max_age_days):
    asof = dict(zip(cache["ticker"], cache["asof"]))
    out = []
    for t in dict.fromkeys(tickers):
        a = asof.get(t)
        try:
            age = (today - dt.date.fromisoformat(str(a))).days if a else None
        except ValueError:
            age = None
        if age is None or age > max_age_days:
            out.append(t)
    return out


def load_sectors(tickers, cache_csv, fetcher=None, max_age_days=30, max_new=300, today=None, sleep=time.sleep):
    df, status, _ = _load(tickers, cache_csv, fetcher, max_age_days, max_new, today, sleep)
    return df, status


def _load(tickers, cache_csv, fetcher, max_age_days, max_new, today, sleep):
    """Returns (frame, status, counts) where counts = dict(fetched, failed, remaining)."""
    fetcher = fetcher or default_fetcher
    today = today or dt.date.today()
    cache = _read_cache(cache_csv)
    todo = _needs_fetch(tickers, cache, today, max_age_days)
    attempt, remaining = todo[:max_new], max(0, len(todo) - max_new)
    new_rows, failed = [], 0
    for i, t in enumerate(attempt):
        if i:
            sleep(FETCH_DELAY)
        try:
            info = fetcher(t) or {}
        except Exception:
            info = {}
        if not info:
            failed += 1
            continue
        new_rows.append({"ticker": t, "sector": normalize_sector(info.get("sector")), "industry": info.get("industry"),
                         "mcap": info.get("marketCap"), "asof": today.isoformat()})
    if new_rows:
        got = {r["ticker"] for r in new_rows}
        fresh = pd.DataFrame(new_rows, columns=COLUMNS)
        kept = cache[~cache["ticker"].isin(got)]
        cache = fresh if kept.empty else pd.concat([kept, fresh], ignore_index=True)
    p = Path(cache_csv)
    p.parent.mkdir(parents=True, exist_ok=True)
    cache.to_csv(p, index=False)
    wanted = set(tickers)
    df = cache[cache.ticker.isin(wanted)].reset_index(drop=True)
    status = (f"sectors: fetched {len(new_rows)}, cached {len(df) - len(new_rows)}, "
              f"failed {failed}, {remaining} remaining")
    return df, status, {"fetched": len(new_rows), "failed": failed, "remaining": remaining}


def fill_all(tickers, cache_csv, fetcher=None, max_age_days=30, batch=300, sleep=time.sleep, pause=5, today=None):
    """Call load_sectors repeatedly until nothing is missing/stale or a round makes no progress."""
    today = today or dt.date.today()
    rounds = []
    while True:
        df, status, counts = _load(tickers, cache_csv, fetcher, max_age_days, batch, today, sleep)
        rounds.append(status)
        pending = _needs_fetch(tickers, _read_cache(cache_csv), today, max_age_days)
        if not pending:
            break
        if counts["fetched"] == 0:  # no progress: every attempted fetch failed
            break
        sleep(pause)
    return df, f"{status} (rounds: {len(rounds)})"
