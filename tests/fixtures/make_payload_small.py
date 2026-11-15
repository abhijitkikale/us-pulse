"""One-off generator for tests/fixtures/payload_small.json: a small, deterministic payload built by the real
pipeline (run.build_payload) from synthetic prices. Re-run from the repo root after a payload change:

    python tests/fixtures/make_payload_small.py
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for p in (str(ROOT), str(ROOT / "pipeline")):
    if p not in sys.path:
        sys.path.insert(0, p)

import numpy as np                      # noqa: E402
import pandas as pd                     # noqa: E402

import compute_etf                      # noqa: E402
import run                              # noqa: E402
import us_config                        # noqa: E402

OUT = Path(__file__).resolve().parent / "payload_small.json"
END = pd.Timestamp("2026-11-13")
N_DAYS = 280
SECTORS = list(us_config.SECTOR_ETFS)
THEMES = ["Semiconductors", "Regional Banks", "Biotech", "Software"]
ETFS = ["XLK", "XLF", "SPY", "QQQ", "TLT", "GLD"]
# extra ETFs for the ETF tab (Task 15): 'US Sector' gets 5 funds (XLV, XLI and XLB reuse the sector ETF series
# already priced above) and 'Size' 4. IWM, IJH and IEF are priced from their own generator with distinct daily
# drifts, so the series above stay unchanged. IJH has only 90 closes: its 6M / 1Y returns are null and it must
# rank "n/a" (last) in its category.
SECTOR_EXTRA = ["XLV", "XLI", "XLB"]
EXTRA_ETFS = {"IWM": 0.0020, "IJH": 0.0012, "IEF": 0.0002}
SHORT_ETF, SHORT_LEN = "IJH", 90
# market caps ($) chosen around the momentum quick picks (300 / 2,000 / 10,000 $M); TK05 has no market cap at all.
# The other stocks keep 5e9 + 3e9 * (30 - i), so most are above 10,000 $M.
MCAP_OVERRIDE = {2: 250e6, 9: 250e6, 16: 250e6, 3: 1.2e9, 10: 1.2e9, 17: 1.2e9, 24: 1.2e9, 4: 6e9, 11: 6e9, 18: 6e9,
                 5: float("nan")}
# ETF assets under management in raw dollars: a null (IWM) and a tiny fund (IEF, $0.4M), and values around the
# ETF quick picks (500 / 1,000 / 5,000 $M)
AUM = {"XLK": 7.2e10, "XLF": 5.1e10, "SPY": 6.3e11, "QQQ": 3.4e11, "TLT": 4.8e10, "GLD": 1.0e11, "XLV": 3.9e10,
       "XLI": 2.2e9, "XLB": 8.0e8, "IWM": None, "IJH": 3.0e9, "IEF": 4.0e5}
RUSSELL_SYM = "^RUT"                    # priced from its own generator so every other series stays unchanged


def main():
    rng = np.random.default_rng(13)
    idx = pd.bdate_range(end=END, periods=N_DAYS)
    rows = []
    for i in range(30):                 # 22 S&P 500 (2 per sector), 4 S&P 400, 4 S&P 600
        uni = "SP500" if i < 22 else "SP400" if i < 26 else "SP600"
        sector = SECTORS[i % len(SECTORS)]
        rows.append({"ticker": f"TK{i:02d}", "name": f"Sample {sector} Co {i:02d}", "universe": uni,
                     "sector": sector if uni == "SP500" else None})
    uni = pd.DataFrame(rows)
    labels = pd.DataFrame({"ticker": uni["ticker"], "sector": [r["sector"] or SECTORS[(i + 3) % 11]
                                                               for i, r in enumerate(rows)],
                           "industry": [f"Industry {i % 7}" for i in range(30)],
                           "mcap": [MCAP_OVERRIDE.get(i, float(5e9 + 3e9 * (30 - i))) for i in range(30)],
                           "asof": "2026-11-01"})
    etf_uni = compute_etf.load_universe()
    etf_uni = etf_uni[etf_uni["ticker"].isin(ETFS + SECTOR_EXTRA + list(EXTRA_ETFS))]

    syms = (list(uni["ticker"]) + [b for b in us_config.BENCHMARKS.values() if b != RUSSELL_SYM]
            + list(us_config.SECTOR_ETFS.values())
            + [us_config.THEMES[t] for t in THEMES] + ETFS)
    for sym, fx in us_config.GLOBAL.values():
        syms.append(sym)
        if fx:
            syms.append(fx[0])
    syms = list(dict.fromkeys(syms))
    drift = rng.normal(0.0004, 0.0006, len(syms))
    steps = rng.normal(drift, 0.012, (N_DAYS, len(syms)))
    base = rng.uniform(20, 400, len(syms))
    close = pd.DataFrame(np.round(base * np.exp(np.cumsum(steps, axis=0)), 2), index=idx, columns=syms)
    for i, t in enumerate(uni["ticker"]):          # stock histories between 60 and 260 sessions
        close.iloc[: N_DAYS - (60 + (i * 7) % 201), close.columns.get_loc(t)] = np.nan
    ill = close.columns.get_loc("TK20")          # one illiquid S&P 500 stock: trades under $5, on a steady climb so that
    up = 3.2 * np.exp(0.005 * (np.arange(N_DAYS) - (N_DAYS - 1)))   # it would rank first in its sector if it were counted
    close.iloc[:, ill] = np.where(close.iloc[:, ill].isna(), np.nan, np.round(up, 2))
    volume = pd.DataFrame(np.round(rng.uniform(4e5, 6e6, (N_DAYS, len(syms)))), index=idx, columns=syms)
    volume.iloc[-1, :6] *= 4                       # a few volume spikes on the last day
    erng = np.random.default_rng(1315)
    ex = list(EXTRA_ETFS)
    esteps = erng.normal(np.array(list(EXTRA_ETFS.values())), 0.009, (N_DAYS, len(ex)))
    eclose = pd.DataFrame(np.round(erng.uniform(30, 300, len(ex)) * np.exp(np.cumsum(esteps, axis=0)), 2),
                          index=idx, columns=ex)
    eclose.iloc[: N_DAYS - SHORT_LEN, ex.index(SHORT_ETF)] = np.nan
    evol = pd.DataFrame(np.round(erng.uniform(4e5, 6e6, (N_DAYS, len(ex)))), index=idx, columns=ex)
    close, volume = pd.concat([close, eclose], axis=1), pd.concat([volume, evol], axis=1)
    rrng = np.random.default_rng(2000)
    close[RUSSELL_SYM] = np.round(2300 * np.exp(np.cumsum(rrng.normal(0.0003, 0.013, N_DAYS))), 2)
    volume[RUSSELL_SYM] = 0.0

    status = {"membership": "ok (30 names)", "prices": "ok", "sectors": "sectors: fetched 0, cached 30, failed 0, 0 remaining (rounds: 1)",
              "etf": "stale: 1 ETF missing from the last download"}
    status["etf_aum"] = "ok (11 of 12 have AUM)"
    aum = pd.DataFrame({"ticker": list(AUM), "aum": [np.nan if v is None else v for v in AUM.values()],
                        "asof": "2026-11-01"})
    payload = run.build_payload(uni, etf_uni, close, volume, labels, status, today=pd.Timestamp("2026-11-16"), aum=aum)
    text = json.dumps(payload, separators=(",", ":"), allow_nan=False)
    bad = re.search(r"\b7497\b|\bU\d{7}\b", text)
    if bad:
        raise SystemExit(f"fixture contains a scanner-flagged literal: {bad.group(0)}; change the seed")
    OUT.write_text(text, encoding="utf-8")
    print(f"wrote {OUT} ({len(text) / 1e3:.0f} KB, {len(payload['stocks'])} stocks, {len(payload['etfs'])} ETFs)")


if __name__ == "__main__":
    main()
