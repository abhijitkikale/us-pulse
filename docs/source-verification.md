# Source verification report

Generated 2026-11-14 19:38 by `tools/verify_sources.py` (keyless; Russell not checked).

## Decision gate

- (a) State Street holdings: PASS
- (b) Yahoo per-ticker fundamentals: PASS
- (c) CBOE total put/call: FAIL
- (d) Yahoo index valuation / index history: PASS

Recommended actions:
- (a) holdings source works; use it for S&P 400/600 membership.
- (b) fields coverage is adequate and no rate limiting seen.
- (c) FAIL (unreachable or stale; the CSV may have stopped updating): Risk tab ships without put/call.
- (d) ETF PE and index history available.

## (a) State Street holdings (SPMD, SPSM)

Result: **PASS**

| Fund | Rows | Holdings as of | Bytes | Fetch note |
|---|---|---|---|---|
| SPMD | 403 | 12-Nov-2026 | 47064 | requests ok |
| SPSM | 611 | 12-Nov-2026 | 61498 | requests ok |

## (b) yfinance Ticker.info on sampled S&P 400/600 names

Result: **PASS**

- Tickers sampled: 60
- sector: 60/60 (100.0%)
- industry: 60/60 (100.0%)
- marketCap: 60/60 (100.0%)
- Elapsed: 22.6 s
- Rate limited: no
- Errors: 0

## (c) CBOE total put/call CSV

Result: **FAIL**

- URL: https://cdn.cboe.com/resources/options/volume_and_call_put_ratios/totalpc.csv
- Rows: 3256; last line: `10/04/2019, 2175006, 2289715, 4464721, 1.05`
- Last data date: 2019-10-04 (age 2598 days; stale if over 14)
- Fetch note: requests ok

## (d) Yahoo index valuation and index history

Result: **PASS**

- SPY trailingPE: 23.999777; forwardPE: None
- ^SP400 daily history (1y): 251 rows, last 2026-11-13
- ^SP600 daily history (1y): 251 rows, last 2026-11-13
