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
                           "mcap": [float(5e9 + 3e9 * (30 - i)) for i in range(30)], "asof": "2026-11-01"})
    etf_uni = compute_etf.load_universe()
    etf_uni = etf_uni[etf_uni["ticker"].isin(ETFS)]

    syms = (list(uni["ticker"]) + list(us_config.BENCHMARKS.values()) + list(us_config.SECTOR_ETFS.values())
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
    volume = pd.DataFrame(np.round(rng.uniform(4e5, 6e6, (N_DAYS, len(syms)))), index=idx, columns=syms)
    volume.iloc[-1, :6] *= 4                       # a few volume spikes on the last day

    status = {"membership": "ok (30 names)", "prices": "ok", "sectors": "sectors: fetched 0",
              "etf": "stale: 1 ETF missing from the last download"}
    payload = run.build_payload(uni, etf_uni, close, volume, labels, status, today=pd.Timestamp("2026-11-16"))
    text = json.dumps(payload, separators=(",", ":"), allow_nan=False)
    bad = re.search(r"\b7497\b|\bU\d{7}\b", text)
    if bad:
        raise SystemExit(f"fixture contains a scanner-flagged literal: {bad.group(0)}; change the seed")
    OUT.write_text(text, encoding="utf-8")
    print(f"wrote {OUT} ({len(text) / 1e3:.0f} KB, {len(payload['stocks'])} stocks, {len(payload['etfs'])} ETFs)")


if __name__ == "__main__":
    main()
