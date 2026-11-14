"""Index / sector / theme builders, equal-weight sector returns, relative strength and global rows."""
import pandas as pd
from compute_core import _num, period_returns
from us_config import BENCHMARKS, GLOBAL, PERIODS, SECTOR_ETFS, THEMES

MIN_EW_MEMBERS = 5
SPX = "S&P 500"
_EMPTY_PES = lambda: {"d": [], "pe": [], "pb": [], "dy": []}


def build_indices(close: pd.DataFrame):
    """Return (indices_by_label, asof, pivot) from a date-indexed frame of closes keyed by symbol."""
    symbols = [s for t in (BENCHMARKS, SECTOR_ETFS, THEMES) for s in t.values()]
    piv = close[[c for c in close.columns if c in symbols]].sort_index()
    asof = piv.index.max()
    out = {}
    for group, table in (("benchmark", BENCHMARKS), ("sector", SECTOR_ETFS), ("theme", THEMES)):
        for label, sym in table.items():
            if sym not in piv.columns:
                continue
            s = piv[sym].dropna()
            if s.empty:
                continue
            wk = s.resample("W-FRI").last().dropna().tail(262)
            out[label] = {
                "label": label, "group": group, "nse": sym, "csv": None,
                "close": _num(s.iloc[-1]),
                "chg": _num((s.iloc[-1] / s.iloc[-2] - 1) * 100) if len(s) > 1 else None,
                "ret": period_returns(s, asof), "pe": None, "pb": None, "dy": None,
                "wk": {"d": [d.strftime("%Y-%m-%d") for d in wk.index], "c": [_num(v) for v in wk.values]},
                "pes": _EMPTY_PES(),
            }
    spx = out.get(SPX, {}).get("ret")
    for e in out.values():
        if e["group"] in ("sector", "theme"):
            e["rs"] = {p: (None if spx is None or e["ret"][p] is None or spx[p] is None
                           else _num(e["ret"][p] - spx[p]))
                       for p in PERIODS}
    return out, asof, piv


def add_equal_weight(indices: dict, members: dict, close: pd.DataFrame) -> None:
    """Set indices[sector]['ew'] = equal-weighted mean return of the sector's S&P 500 members (in place)."""
    spx = set(members.get(SPX, []))
    for label, e in indices.items():
        if e.get("group") != "sector":
            continue
        tickers = [t for t in members.get(label, []) if t in spx and t in close.columns]
        rets = [period_returns(close[t]) for t in tickers]
        ew = {}
        for p in PERIODS:
            vals = [r[p] for r in rets if r[p] is not None]
            ew[p] = _num(sum(vals) / len(vals)) if len(vals) >= MIN_EW_MEMBERS else None
        e["ew"] = ew


def build_global(close: pd.DataFrame) -> list:
    """Rows {name, local, usd}: each index in local terms and converted to USD via its FX series."""
    def usd_per(sym, kind):   # USD per 1 local unit
        return close[sym] if kind == "usd_per" else 1 / close[sym]

    series = {}
    for label, (sym, fx) in GLOBAL.items():
        if sym not in close.columns:
            continue
        rate = usd_per(*fx) if fx and fx[0] in close.columns else None
        if fx and rate is None:
            continue
        series[label] = (close[sym], rate)
    covered = {sym for sym, _ in GLOBAL.values()}
    for label, sym in BENCHMARKS.items():
        if label == "VIX" or sym in covered or sym not in close.columns:
            continue
        series[label] = (close[sym], None)
    out = []
    for label, (local, rate) in series.items():
        loc = period_returns(local)
        usd = period_returns(local * rate.reindex(local.index, method="ffill")) if rate is not None else loc
        out.append({"name": label, "local": loc, "usd": usd})
    return out
