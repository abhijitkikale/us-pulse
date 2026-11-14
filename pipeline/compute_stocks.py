"""Per-stock facts + membership labels (port of the India dashboard's build_stocks, US universe)."""
import math

import pandas as pd

from compute_core import _num, period_returns, risk_stats, trend_flags
from us_config import AVG_DAYS, MIN_AVG_DAYS, MIN_DOLLAR_VOL, MIN_PRICE, SECTOR_ETFS

# universe code -> index membership label
INDEX_LABELS = {"SP500": "S&P 500", "SP400": "S&P 400", "SP600": "S&P 600"}


def _text(v):
    """A clean string or None (pandas may hand us NaN for missing text)."""
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    v = str(v).strip()
    return v or None


def _sector(v):
    v = _text(v)
    return v if v in SECTOR_ETFS else None


def _dollar_vol(c: pd.Series, volume: pd.DataFrame, ticker: str):
    """Mean close*volume over the stock's last AVG_DAYS price observations; None if too few valid days."""
    if ticker not in volume.columns:
        return None
    last = c.tail(AVG_DAYS)
    dv = (last * volume[ticker].reindex(last.index)).dropna()
    if len(dv) < MIN_AVG_DAYS:
        return None
    m = float(dv.mean())
    return None if math.isnan(m) or math.isinf(m) else m


def build_stocks(universe: pd.DataFrame, close: pd.DataFrame, volume: pd.DataFrame,
                 labels: pd.DataFrame, bench: pd.Series | None = None):
    """Returns (stocks, members, dates). Universe = S&P 500 + S&P 400 + S&P 600."""
    uni = universe.drop_duplicates("ticker").set_index("ticker")
    lab = labels.drop_duplicates("ticker", keep="last").set_index("ticker") if len(labels) else None
    close = close.sort_index()
    asof = close.index.max()
    dates = list(close.index[-260:])
    stocks, member_of = {}, {}
    for sym, row in uni.iterrows():
        if sym not in close.columns:
            continue
        c = close[sym].dropna()
        if len(c) < 20 or (asof - c.index[-1]).days > 7:
            continue
        lrow = lab.loc[sym] if lab is not None and sym in lab.index else None
        index_label = INDEX_LABELS.get(row["universe"])
        sector = _sector(row["sector"]) if row["universe"] == "SP500" else (
            _sector(lrow["sector"]) if lrow is not None else None)
        mcap = lrow["mcap"] if lrow is not None else None
        mc = (_num(float(mcap) / 1e6, 0) or None) if mcap is not None and not pd.isna(mcap) else None
        if mc is not None and mc < 0:
            mc = None
        flags = trend_flags(c) or {}
        hi, lo = c.tail(252).max(), c.tail(252).min()
        dv = _dollar_vol(c, volume, sym)
        price = float(c.iloc[-1])
        stocks[sym] = {
            "s": sym, "n": _text(row["name"]) or sym, "i": _text(lrow["industry"]) if lrow is not None else None,
            "p": _num(price), "d1": _num((c.iloc[-1] / c.iloc[-2] - 1) * 100), "r": period_returns(c, asof),
            **flags, **risk_stats(c, bench),
            "pos": _num((c.iloc[-1] - lo) / (hi - lo) * 100, 0) if hi > lo else None,
            "hi": _num(hi), "lo": _num(lo),
            "mc": mc,                                                          # $ millions
            "mck": "yahoo" if mc is not None else None,
            "ser": [_num(v) for v in c.reindex(dates).values],
            "s50": [_num(v) for v in c.rolling(50).mean().reindex(dates).values],
            "s200": [_num(v) for v in c.rolling(200).mean().reindex(dates).values],
            "liq": bool(price > MIN_PRICE and dv is not None and dv > MIN_DOLLAR_VOL),
            "dv": _num(dv, 0),
        }
        member_of[sym] = [lbl for lbl in (sector, index_label) if lbl]
    ranked = sorted(stocks.values(), key=lambda s: (s["mc"] is None, -(s["mc"] or 0),
                                                    s["dv"] is None, -(s["dv"] or 0)))
    for i, s in enumerate(ranked, 1):
        s["rk"] = i
    members = {label: [] for label in (*SECTOR_ETFS, *INDEX_LABELS.values())}
    for sym, st in stocks.items():
        st["x"] = member_of[sym]
        for label in st["x"]:
            members[label].append(sym)
    return list(stocks.values()), members, [d.strftime("%Y-%m-%d") for d in dates]
