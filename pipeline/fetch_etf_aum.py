"""ETF assets under management (AUM) from Yahoo, cached in a committed CSV (aum in raw dollars).

Only missing or stale tickers are fetched, at most `max_new` per call. A failed fetch keeps the old row and never
raises. The status never starts with stale / failed / partial: AUM is a nice-to-have and must never turn the nightly
build red."""
import datetime as dt
import math
import time
from pathlib import Path

import pandas as pd

COLUMNS = ["ticker", "aum", "asof"]
FETCH_DELAY = 0.4  # seconds between Yahoo calls


def _clean(v):
    """A positive finite number of dollars, else None."""
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) and v > 0 else None


def default_fetcher(ticker):
    """Yahoo `totalAssets` (falls back to `netAssets`) in dollars; None on any failure or when neither is given."""
    try:
        import yfinance as yf
        info = yf.Ticker(ticker).info or {}
        return _clean(info.get("totalAssets")) or _clean(info.get("netAssets"))
    except Exception:
        return None


def _read_cache(cache_csv):
    p = Path(cache_csv)
    if not p.exists():
        return pd.DataFrame(columns=COLUMNS)
    try:
        df = pd.read_csv(p, dtype={"ticker": str, "asof": str}).reindex(columns=COLUMNS)
        df["aum"] = [_clean(v) for v in df["aum"]]
        return df.dropna(subset=["ticker"]).drop_duplicates("ticker", keep="last").reset_index(drop=True)
    except Exception:
        return pd.DataFrame(columns=COLUMNS)


def _needs_fetch(tickers, cache, today, max_age_days):
    known = {t: (a, v) for t, a, v in zip(cache["ticker"], cache["asof"], cache["aum"])}
    out = []
    for t in dict.fromkeys(tickers):
        a, v = known.get(t, (None, None))
        try:
            age = (today - dt.date.fromisoformat(str(a))).days if a else None
        except ValueError:
            age = None
        if _clean(v) is None or age is None or age > max_age_days:
            out.append(t)
    return out


def _write(cache, cache_csv):
    p = Path(cache_csv)
    p.parent.mkdir(parents=True, exist_ok=True)
    out = cache.copy()
    # whole dollars, written as integers: no decimals in the committed file
    out["aum"] = pd.array([None if _clean(v) is None else int(round(v)) for v in out["aum"]], dtype="Int64")
    out.sort_values("ticker").to_csv(p, index=False)


def fetch_etf_aum(tickers, cache_csv, fetcher=None, max_age_days=30, max_new=300, today=None,
                  sleep=time.sleep) -> tuple[pd.DataFrame, str]:
    """Returns (frame with columns ticker, aum, asof for the requested tickers that have a row, status)."""
    tickers = [t for t in dict.fromkeys(tickers) if isinstance(t, str) and t]
    try:
        fetcher = fetcher or default_fetcher
        today = today or dt.date.today()
        cache = _read_cache(cache_csv)
        todo = _needs_fetch(tickers, cache, today, max_age_days)
        attempt, remaining = todo[:max(0, max_new)], max(0, len(todo) - max(0, max_new))
        new_rows, failed = [], 0
        for i, t in enumerate(attempt):
            if i:
                sleep(FETCH_DELAY)
            try:
                v = _clean(fetcher(t))
            except Exception:
                v = None
            if v is None:
                failed += 1                          # the old row (if any) is kept as it is
                continue
            new_rows.append({"ticker": t, "aum": v, "asof": today.isoformat()})
        if new_rows:
            got = {r["ticker"] for r in new_rows}
            fresh = pd.DataFrame(new_rows, columns=COLUMNS)
            kept = cache[~cache["ticker"].isin(got)]
            cache = fresh if kept.empty else pd.concat([kept, fresh], ignore_index=True)
            _write(cache, cache_csv)
        df = cache[cache["ticker"].isin(set(tickers))].reset_index(drop=True)
        have = sum(_clean(v) is not None for v in df["aum"])
        if not have:
            return df, f"unavailable (no AUM for any of {len(tickers)} ETFs; fetched {len(new_rows)}, failed {failed})"
        status = f"ok ({have} of {len(tickers)} have AUM)"
        if attempt:
            status += f"; fetched {len(new_rows)}, failed {failed}, {remaining} remaining"
        return df, status
    except Exception as e:                           # AUM is optional: never break the build
        return pd.DataFrame(columns=COLUMNS), f"unavailable ({type(e).__name__})"


if __name__ == "__main__":                           # one-off seed: python pipeline/fetch_etf_aum.py
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import compute_etf
    import us_config
    uni = compute_etf.load_universe()
    df, st = fetch_etf_aum(list(uni["ticker"]), us_config.DATA / "etf_aum.csv")
    print(st)
    have = set(df.dropna(subset=["aum"])["ticker"])
    print("without AUM:", ", ".join(t for t in uni["ticker"] if t not in have) or "none")
