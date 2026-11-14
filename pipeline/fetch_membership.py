"""Index membership (S&P 500 / 400 / 600) from State Street SPDR daily holdings files."""
import io
import re

import pandas as pd
import requests

from pipeline.us_config import SECTOR_ETFS

BASE = ("https://www.ssga.com/us/en/intermediary/etfs/library-content/products/"
        "fund-data/etfs/us/holdings-daily-us-en-{t}.xlsx")  # ticker must be lowercase
COLUMNS = ["ticker", "name", "universe", "sector"]
TIMEOUT = 30
# Real equity tickers: letters with an optional share-class suffix, checked after dot->dash.
# Drops futures (IXTZ6), numeric ids (2602335D), CASH-like and blank rows.
_TICKER_RE = re.compile(r"^[A-Z]{1,5}(-[A-Z]{1,2})?$")
_NON_HOLDINGS = {"CASH", "USD"}


def yahoo_ticker(t: str) -> str:
    return t.replace(".", "-")


def parse_ssga_xlsx(content: bytes) -> pd.DataFrame:
    """Parse a holdings workbook into ticker, name, weight; cash/footer rows dropped."""
    raw = pd.read_excel(io.BytesIO(content), header=None, dtype=object)
    hdr = None
    for i in range(len(raw)):
        if any(str(c).strip() == "Ticker" for c in raw.iloc[i]):
            hdr = i
            break
    if hdr is None:
        raise ValueError("holdings header row not found")
    cols = [str(c).strip() for c in raw.iloc[hdr]]
    body = raw.iloc[hdr + 1:].copy()
    body.columns = cols
    out = pd.DataFrame({
        "ticker": body["Ticker"].map(lambda v: "" if pd.isna(v) else str(v).strip().upper()),
        "name": body["Name"].map(lambda v: "" if pd.isna(v) else str(v).strip()) if "Name" in cols else "",
        "weight": pd.to_numeric(body["Weight"], errors="coerce") if "Weight" in cols else float("nan"),
    })
    keep = out["ticker"].map(lambda t: bool(_TICKER_RE.match(yahoo_ticker(t))) and t not in _NON_HOLDINGS)
    return out[keep].reset_index(drop=True)


def _empty() -> pd.DataFrame:
    return pd.DataFrame(columns=COLUMNS)


def _load(get, etf: str) -> pd.DataFrame:
    r = get(BASE.format(t=etf.lower()), timeout=TIMEOUT)
    r.raise_for_status()
    return parse_ssga_xlsx(r.content)


def fetch_membership(get=requests.get) -> tuple[pd.DataFrame, str]:
    """Never raises. Returns (ticker[yahoo form], name, universe, sector) and a status string."""
    try:
        return _fetch(get)
    except Exception as e:  # defensive: contract is never to raise
        return _empty(), f"failed: {type(e).__name__}: {e}"


def _fetch(get) -> tuple[pd.DataFrame, str]:
    frames, failed = [], []

    def grab(etf, universe, sector):
        try:
            df = _load(get, etf)
        except Exception as e:
            failed.append(f"{etf} ({type(e).__name__})")
            return None
        df = df.assign(ticker=df["ticker"].map(yahoo_ticker), universe=universe, sector=sector)
        frames.append(df[COLUMNS])
        return df

    sp500_ok = 0
    for sector, etf in SECTOR_ETFS.items():
        if grab(etf, "SP500", sector) is not None:
            sp500_ok += 1
    grab("SPMD", "SP400", None)
    grab("SPSM", "SP600", None)

    notes = []
    if not frames:
        return _empty(), "failed: no holdings files could be fetched (" + ", ".join(failed) + ")"
    allm = pd.concat(frames, ignore_index=True)
    rank = {"SP500": 0, "SP400": 1, "SP600": 2}
    allm = (allm.assign(_r=allm["universe"].map(rank)).sort_values("_r", kind="stable")
            .drop_duplicates("ticker", keep="first").drop(columns="_r").reset_index(drop=True))
    allm["sector"] = allm["sector"].astype(object).where(allm["sector"].notna(), None)

    n500 = int((allm["universe"] == "SP500").sum())
    if sp500_ok == len(SECTOR_ETFS) and not 490 <= n500 <= 510:
        # SPY is only a sanity check on the union size
        try:
            spy = len(_load(get, "SPY"))
            notes.append(f"SP500 union has {n500} names (SPY lists {spy}); outside 490-510")
        except Exception as e:
            notes.append(f"SP500 union has {n500} names; outside 490-510 (SPY check failed: {type(e).__name__})")
    if failed:
        return allm, "partial: failed " + ", ".join(failed) + ("; " + "; ".join(notes) if notes else "")
    return allm, "ok" + ("; " + "; ".join(notes) if notes else "") + f" ({len(allm)} names)"
