# US Pulse

A public, data-only dashboard for US markets (S&P 500 sectors, breadth, movers, ETFs and activity), published with GitHub Pages.
It is a port of the India dashboard. It reads market data and renders it. It never connects to a broker and never places orders.

Published page: `https://<owner>.github.io/<repo>/` (fill in after the first deploy).

## Layout

- `pipeline/` data-building code
- `tests/` automated tests
- `tools/` helper scripts, including `scan_repo.py` (secret and broker-code scanner) and `should_run.py` (workflow guard)
- `data/` committed small outputs only (`sectors.csv`, `membership.csv`, `last_count.txt`)
- `docs/` project documents
- `.github/workflows/` the scheduled refresh job

## Run locally

    pip install -r requirements.txt
    python pipeline/run.py --fill-sectors   # first time only: fetches every missing sector label (slow)
    python pipeline/run.py                  # normal build, writes dashboard.html
    python pipeline/run.py --cached         # rebuild from data/prices.pkl and data/sectors.csv, no downloads

    python -m pytest tests -q
    python tools/scan_repo.py

`run.py` exits with status 1 (after writing the page) when a source is stale, failed or partial.

## Nightly schedule

The workflow "Refresh US Pulse" runs on weekdays after the US close (17:35 New York time; two UTC cron entries cover both
daylight-saving states, plus a few retry slots because GitHub's scheduler is best-effort). A guard step builds only on a
trading day once the market has been closed for 20 minutes (16:00, or 13:00 on early-close days). The job runs the tests and
the repo scanner, builds the page, commits the three small data files, and deploys to Pages. If the build fails, the deploy
is skipped and the previously published page stays up. You can also start it by hand with "Run workflow".

## Data sources

Yahoo Finance (prices, via yfinance) and State Street SPDR (sector ETF holdings). Only derived numbers are published; raw
source data is not redistributed. For personal and friends' use.

## Disclaimer

Educational use only. This is not investment advice.

## Known limits

- Current index constituents only (no historical membership, so survivorship bias applies).
- No put/call ratio.
- No forward P/E.
- The valuation and risk tabs show placeholder cards for now.

## Security checklist for the owner

This repository is public, so everything committed is visible to everyone.

- [ ] Turn on 2-factor sign-in on your GitHub account.
- [ ] Settings -> Actions -> General: restrict Actions to selected actions, and set workflow permissions to read.
- [ ] Protect the `main` branch (require pull requests and passing checks).
- [ ] Never commit raw or private data (pickles, caches, `.env`, tokens). Only reviewed CSV outputs belong in `data/`.
- [ ] Remember: the repo is public, so nothing secret, personal, or account-related may ever be committed.
