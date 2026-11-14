"""Per-ETF facts for the ETF explorer: returns, trend flags, risk and liquidity over a curated universe."""
from pathlib import Path

import pandas as pd

from compute_core import _num, period_returns, risk_stats, trend_flags
from compute_stocks import _dollar_vol, _text

UNIVERSE_CSV = Path(__file__).resolve().parent / "etf_universe.csv"
CATEGORIES = ["US Sector", "Theme", "Size", "Style & Factor", "International Country", "International Region",
              "Bonds", "Commodities", "Dividend & Income", "Real Estate", "Currency & Other"]
FLAG_KEYS = ("a50", "a200", "gc", "bs", "bw")
MIN_OBS = 20
SER_LEN = 260


def load_universe(path=UNIVERSE_CSV) -> pd.DataFrame:
    return pd.read_csv(path)


def build_etf(universe: pd.DataFrame, close: pd.DataFrame, volume: pd.DataFrame,
              bench: pd.Series | None = None):
    """Returns (etfs, categories present, sorted). ETFs missing from `close` or with < 20 closes are skipped."""
    close = close.sort_index()
    asof = close.index.max() if len(close) else None
    etfs = []
    for row in universe.drop_duplicates("ticker").itertuples(index=False):
        sym = row.ticker
        if sym not in close.columns:
            continue
        c = close[sym].dropna()
        if len(c) < MIN_OBS:
            continue
        flags = trend_flags(c) or {}                       # <50 obs: keys kept, all None
        risk = risk_stats(c, bench)
        etfs.append({
            "t": sym, "n": _text(row.name) or sym, "c": row.category,
            "p": _num(c.iloc[-1]), "d1": _num((c.iloc[-1] / c.iloc[-2] - 1) * 100),
            "r": period_returns(c, asof),
            **{k: flags.get(k) for k in FLAG_KEYS},
            "vol": risk["vol"], "mdd": risk["mdd"],
            "dv": _num(_dollar_vol(c, volume, sym), 0),
            "ser": [_num(v) for v in c.tail(SER_LEN).values],
        })
    return etfs, sorted({e["c"] for e in etfs})
