"""Market-activity payload: whole-market breadth history, dollar-volume leaders and volume spikes (from daily close/volume)."""
import math

import pandas as pd

from pipeline.us_config import AVG_DAYS, MIN_AVG_DAYS, MIN_DOLLAR_VOL, SPIKE_X


def _n(x, nd=2):
    if x is None:
        return None
    x = float(x)
    return None if math.isnan(x) or math.isinf(x) else round(x, nd)


def _rows(df):
    return [{"s": r.s, "p": _n(r.p), "chg": _n(r.chg), "vol": int(r.vol), "avg": None if pd.isna(r.avg20) else int(r.avg20),
             "x": _n(r.ratio, 1), "tcr": _n(r.dvol / 1e6, 1), "dp": None} for r in df.itertuples()]


def build_activity(close, volume, top_n=25, spike_n=30, spike_x=SPIKE_X, min_dollar_vol=MIN_DOLLAR_VOL, tail_days=260):
    if close is None or volume is None or close.empty or volume.empty:
        return None
    close = close.apply(pd.to_numeric, errors="coerce").where(lambda d: d > 0).sort_index()
    volume = volume.apply(pd.to_numeric, errors="coerce").reindex(index=close.index, columns=close.columns)
    chg = close.pct_change(fill_method=None) * 100          # NaN when either day is missing
    chg = chg.iloc[1:]
    if chg.empty:
        return None
    adv, dec = (chg > 0).sum(axis=1), (chg < 0).sum(axis=1)
    n = chg.notna().sum(axis=1)
    turn = (close * volume).sum(axis=1, min_count=1).reindex(chg.index) / 1e6
    br = pd.DataFrame({"adv": adv, "dec": dec, "turn": turn}).assign(unch=n - adv - dec).tail(tail_days)
    last = chg.index[-1]
    prior = volume[volume.index < last].tail(AVG_DAYS)
    avg = prior.mean().where(prior.count() >= MIN_AVG_DAYS)
    today = pd.DataFrame({"p": close.loc[last], "chg": chg.loc[last], "vol": volume.loc[last]})
    today = today[today["chg"].notna() & today["vol"].notna()].rename_axis("s").reset_index()
    n_stocks = int(chg.loc[last].notna().sum())
    today["avg20"] = today["s"].map(avg)
    today["ratio"] = today["vol"] / today["avg20"]
    today["dvol"] = today["p"] * today["vol"]
    spikes = today[(today["ratio"] >= spike_x) & (today["dvol"] >= min_dollar_vol)].sort_values("ratio", ascending=False).head(spike_n)
    return {
        "asof": last.strftime("%Y-%m-%d"), "n_stocks": n_stocks,
        "params": {"spike_x": spike_x, "min_dollar_vol": min_dollar_vol, "avg_days": AVG_DAYS},
        "breadth": {"d": [d.strftime("%Y-%m-%d") for d in br.index], "adv": [int(v) for v in br["adv"]], "dec": [int(v) for v in br["dec"]],
                    "unch": [int(v) for v in br["unch"]], "turn": [_n(v, 1) for v in br["turn"]]},
        "leaders": {"turnover": _rows(today.sort_values("dvol", ascending=False).head(top_n)),
                    "volume": _rows(today.sort_values("vol", ascending=False).head(top_n))},
        "spikes": _rows(spikes),
    }
