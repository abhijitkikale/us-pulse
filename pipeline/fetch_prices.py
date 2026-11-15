"""Batched Yahoo price download with a pickle cache and keep-last-good protection."""
import time
from pathlib import Path

import pandas as pd
import yfinance as yf

SOFT_MISSING_RATIO = 0.01  # up to this share of symbols may be missing and the status stays ok
STALE_RATIO = 0.8  # fresh download must return at least this share of the cached symbols


def _field(frame, name, symbols):
    """Extract one field (Close/Volume) as a symbol-columned frame; handles the one-symbol plain Index."""
    if frame is None or len(frame) == 0:
        return pd.DataFrame()
    if isinstance(frame.columns, pd.MultiIndex):
        if name not in frame.columns.get_level_values(0):
            return pd.DataFrame()
        return frame[name].copy()
    if name not in frame.columns or len(symbols) != 1:
        return pd.DataFrame()
    return frame[[name]].rename(columns={name: symbols[0]})


def download_prices(symbols, period="5y", batch=100, retries=3, downloader=yf.download, sleep=time.sleep):
    """Return (close, volume, status). Never raises; failed batches are skipped."""
    symbols = list(dict.fromkeys(symbols))
    closes, vols, failed_batches = [], [], 0
    for i in range(0, len(symbols), batch):
        chunk = symbols[i:i + batch]
        got = False
        for attempt in range(retries):
            try:
                d = downloader(chunk, period=period, interval="1d", auto_adjust=True,
                               progress=False, threads=True)
                c, v = _field(d, "Close", chunk), _field(d, "Volume", chunk)
                if c.empty:
                    raise ValueError("empty download")
                closes.append(c)
                vols.append(v)
                got = True
                break
            except Exception:
                if attempt < retries - 1:
                    sleep(2 * 2 ** attempt)          # 2, 4, 8 ...
        failed_batches += not got
    if not closes:
        return pd.DataFrame(), pd.DataFrame(), "failed: no price data"
    close = pd.concat(closes, axis=1).dropna(axis=1, how="all").sort_index()
    volume = pd.concat(vols, axis=1)
    volume = volume[[c for c in close.columns if c in volume.columns]].sort_index()
    close = close.loc[:, ~close.columns.duplicated()]
    volume = volume.loc[:, ~volume.columns.duplicated()]
    missing = len(symbols) - close.shape[1]
    if failed_batches or missing > SOFT_MISSING_RATIO * len(symbols):
        return close, volume, f"partial: {close.shape[1]}/{len(symbols)} symbols"
    if missing:
        names = [s for s in symbols if s not in close.columns]
        shown = ", ".join(names[:10]) + (", ..." if len(names) > 10 else "")
        return close, volume, f"ok ({missing} missing: {shown})"
    return close, volume, "ok"


def merge_prices(old, new):
    """Fresh rows win; cached cells Yahoo did not return are kept. Union of dates and columns, sorted."""
    if new is None or new.empty:
        return old
    if old is None or old.empty:
        return new
    return new.combine_first(old).sort_index()


def load_cache(path):
    path = Path(path)
    if not path.exists():
        return None, None
    try:
        close, volume = pd.read_pickle(path)
        return close, volume
    except Exception:
        return None, None


def save_cache(path, close, volume):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    pd.to_pickle((close, volume), tmp)
    tmp.replace(path)                                 # atomic: never leave a half-written cache


def refresh(symbols, cache_path, **kw):
    """Download, merge into the cache, save. If the download returned under 80% of the symbols the
    cache already holds (Yahoo outage / partial batch), keep the cache untouched and report 'stale:'.
    Only cached symbols that are still requested count, so delisted names left in the cache never trip it."""
    old_c, old_v = load_cache(cache_path)
    new_c, new_v, status = download_prices(symbols, **kw)
    if old_c is not None and not old_c.empty:
        wanted = set(symbols)
        held = sum(c in wanted for c in old_c.columns)
        got = sum(c in wanted for c in new_c.columns)
        if got < STALE_RATIO * held:
            return old_c, old_v, (f"stale: download returned {got} of "
                                  f"{held} cached symbols ({status}); cache kept")
    elif new_c.empty:
        return pd.DataFrame(), pd.DataFrame(), status
    close = merge_prices(old_c, new_c)
    volume = merge_prices(old_v, new_v)
    save_cache(cache_path, close, volume)
    return close, volume, status
