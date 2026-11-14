"""Daily entry point: fetch -> compute -> assemble -> render dashboard.html.

    python pipeline/run.py                 # full run (from the repo root or from pipeline/)
    python pipeline/run.py --cached        # rebuild from data/prices.pkl and data/sectors.csv only, no downloads
    python pipeline/run.py --fill-sectors  # fetch every missing/old sector label before building (slow, one-off)

Exits non-zero after writing the page when a source is stale or failed, and refuses to write the page at all
when the stock universe collapsed versus the previous run (data/last_count.txt)."""
import sys
import warnings
from pathlib import Path

HERE = Path(__file__).resolve().parent
for _p in (str(HERE.parent), str(HERE)):           # `pipeline.x` and bare `x` imports both resolve
    if _p not in sys.path:
        sys.path.insert(0, _p)

import pandas as pd                                    # noqa: E402

import assemble as asm                                 # noqa: E402
import build                                           # noqa: E402
import compute_activity                                # noqa: E402
import compute_etf                                     # noqa: E402
import compute_indices                                 # noqa: E402
import compute_stocks                                  # noqa: E402
import us_calendar                                     # noqa: E402
import us_config                                       # noqa: E402
from pipeline import fetch_membership, fetch_prices, fetch_sectors   # noqa: E402

warnings.filterwarnings("ignore")

DATA = us_config.DATA
OUT = us_config.ROOT / "dashboard.html"
TEMPLATE = None            # None = build.TEMPLATE (pipeline/template.html)
PLOTLY_JS = None           # None = the installed plotly package's plotly.min.js
MIN_KEEP = 0.6             # refuse to publish when the universe shrinks below this share of the last run
BAD = ("stale:", "failed")


def _today():
    return asm.today_ny()


def _membership(cached):
    """Fetch the S&P 500/400/600 lists; fall back to the last good copy when the fetch returns nothing."""
    cache = DATA / "membership.csv"
    if cached and cache.exists():
        return pd.read_csv(cache, dtype=str), "cached"
    uni, status = fetch_membership.fetch_membership()
    if len(uni):
        if status.startswith("ok"):
            DATA.mkdir(parents=True, exist_ok=True)
            uni.to_csv(cache, index=False)
        return uni, status
    if cache.exists():
        return pd.read_csv(cache, dtype=str), f"stale: using last good list ({status})"
    return uni, status


def symbol_list(uni, etf_uni):
    syms = list(uni["ticker"])
    for table in (us_config.BENCHMARKS, us_config.SECTOR_ETFS, us_config.THEMES):
        syms += list(table.values())
    for sym, fx in us_config.GLOBAL.values():
        syms.append(sym)
        if fx:
            syms.append(fx[0])
    syms += list(etf_uni["ticker"])
    return list(dict.fromkeys(s for s in syms if isinstance(s, str) and s))


def _previous_count():
    try:
        return int((DATA / "last_count.txt").read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def build_payload(uni, etf_uni, close, volume, labels, status, today=None) -> dict:
    """Compute every section and assemble the sanitized payload. Adds status['freshness'] when prices are behind."""
    # US instruments only trade on NYSE sessions; Yahoo adds weekend rows for some FX pairs (e.g. CAD=X on a
    # Saturday), which would otherwise become the "as of" date with no stock data. Global rows keep every date.
    us_close = close[[us_calendar.is_trading_day(d.date()) for d in close.index]]
    us_volume = volume.reindex(index=us_close.index) if volume is not None else pd.DataFrame(index=us_close.index)
    bench = us_close["^GSPC"] if "^GSPC" in us_close.columns else None
    indices, asof, _ = compute_indices.build_indices(us_close)
    stocks, members, dates = compute_stocks.build_stocks(uni, us_close, us_volume, labels, bench)
    compute_indices.add_equal_weight(indices, members, us_close)
    stock_cols = [t for t in dict.fromkeys(uni["ticker"]) if t in us_close.columns]
    activity = compute_activity.build_activity(us_close[stock_cols], us_volume.reindex(columns=stock_cols))
    etfs, etf_categories = compute_etf.build_etf(etf_uni, us_close, us_volume, bench)
    global_rows = compute_indices.build_global(close)
    price_asof = us_close[stock_cols].dropna(how="all").index.max() if stock_cols else None

    payload = asm.assemble(indices, asof, members, stocks, dates, global_rows, activity, etfs, etf_categories,
                           status, price_asof, today=today)
    if payload["stale"]:
        status["freshness"] = "stale: " + payload["stale_note"]   # same dict object as payload["status"]
    return asm.sanitize(payload)


def main(cached: bool = False, fill_sectors: bool = False):
    status = {}
    uni, status["membership"] = _membership(cached)
    etf_uni = compute_etf.load_universe()
    symbols = symbol_list(uni, etf_uni)

    cache = DATA / "prices.pkl"
    if cached:
        close, volume = fetch_prices.load_cache(cache)
        status["prices"] = "cached" if close is not None else f"failed: no price cache at {cache}"
    else:
        close, volume, status["prices"] = fetch_prices.refresh(symbols, cache)
    if close is None or close.empty:
        raise SystemExit(f"No price data ({status['prices']}); page not written")

    tickers = list(uni["ticker"])                    # Ruling R18: industry + mcap labels for the whole universe
    sectors_csv = DATA / "sectors.csv"
    if fill_sectors:
        labels, status["sectors"] = fetch_sectors.fill_all(tickers, sectors_csv)
    else:
        labels, status["sectors"] = fetch_sectors.load_sectors(tickers, sectors_csv, **({"max_new": 0} if cached else {}))

    payload = build_payload(uni, etf_uni, close, volume, labels, status, today=_today())
    stocks = payload["stocks"]

    prev = _previous_count()
    if not stocks or (prev and len(stocks) < MIN_KEEP * prev):
        raise SystemExit(f"Refusing to build: {len(stocks)} stocks vs {prev} last run "
                         f"(below {MIN_KEEP:.0%}); previous page kept. Status: {status}")

    out = build.render(payload, OUT, template_path=TEMPLATE, plotly_js=PLOTLY_JS)
    DATA.mkdir(parents=True, exist_ok=True)
    (DATA / "last_count.txt").write_text(str(len(stocks)), encoding="utf-8")
    print("Built", out, f"({out.stat().st_size / 1e6:.1f} MB, {len(stocks)} stocks, {len(payload['etfs'])} ETFs)")
    for k, v in status.items():
        print(f"  {k}: {v}")
    bad = [k for k, v in status.items() if str(v).startswith(BAD)]
    if bad:
        print("Stale or failed sources: " + ", ".join(bad))
        raise SystemExit(1)
    return out


if __name__ == "__main__":
    main(cached="--cached" in sys.argv, fill_sectors="--fill-sectors" in sys.argv)
