"""Source verification gate: probes the free data sources the dashboard depends on.

Keyless. Writes docs/source-verification.md. Run from a normal PC with internet:
    python tools/verify_sources.py
"""
import datetime as dt
import io
import pathlib
import random
import sys
import time
import urllib.request

import requests

SSGA_BASE = ("https://www.ssga.com/us/en/intermediary/etfs/library-content/"
             "products/fund-data/etfs/us/holdings-daily-us-en-{t}.xlsx")
CBOE_URL = "https://cdn.cboe.com/resources/options/volume_and_call_put_ratios/totalpc.csv"
UA = {"User-Agent": "Mozilla/5.0 (compatible; us-pulse-verify/1.0)"}
SAMPLE_SIZE = 60
OUT = pathlib.Path(__file__).resolve().parent.parent / "docs" / "source-verification.md"


def fetch(url: str, timeout: int = 60):
    """Return (bytes|None, note). Tries requests, then urllib. Never disables cert checks."""
    notes = []
    try:
        r = requests.get(url, headers=UA, timeout=timeout)
        if r.status_code == 200:
            return r.content, "requests ok"
        notes.append(f"requests HTTP {r.status_code}")
    except Exception as e:  # noqa: BLE001
        notes.append(f"requests {type(e).__name__}: {str(e)[:160]}")
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read(), "; ".join(notes) + "; urllib ok"
    except Exception as e:  # noqa: BLE001
        notes.append(f"urllib {type(e).__name__}: {str(e)[:160]}")
    return None, "; ".join(notes)


def parse_holdings(content: bytes):
    """Return (as_of_text, DataFrame of holdings rows with a ticker)."""
    import pandas as pd
    raw = pd.read_excel(io.BytesIO(content), header=None)
    as_of = ""
    hdr = None
    for i, row in raw.iterrows():
        cells = [str(c) for c in row.tolist() if str(c) != "nan"]
        if cells and cells[0].startswith("Holdings") and len(cells) > 1 and "As of" in cells[1]:
            as_of = cells[1].replace("As of", "").strip()
        if hdr is None and "Ticker" in cells and "Name" in cells:
            hdr = i
            break
    if hdr is None:
        return as_of, None
    df = raw.iloc[hdr + 1:].copy()
    df.columns = [str(c) for c in raw.iloc[hdr].tolist()]
    df = df[df["Ticker"].notna()]
    df = df[df["Ticker"].astype(str).str.strip().ne("")]
    # drop footer/disclaimer rows (no weight)
    df = df[df["Weight"].notna()]
    return as_of, df


def check_a():
    res = {"pass": True, "funds": {}, "tickers": {}}
    for t in ("SPMD", "SPSM"):
        content, note = fetch(SSGA_BASE.format(t=t.lower()))
        info = {"note": note, "rows": 0, "as_of": "", "bytes": len(content or b"")}
        if content is None:
            res["pass"] = False
        else:
            try:
                as_of, df = parse_holdings(content)
                info["as_of"] = as_of
                if df is None:
                    res["pass"] = False
                    info["note"] += "; header not found"
                else:
                    tick = [str(x).strip() for x in df["Ticker"]]
                    tick = [x for x in tick if x and x != "-" and " " not in x]
                    info["rows"] = len(df)
                    res["tickers"][t] = tick
                    lo, hi = {"SPMD": (350, 450), "SPSM": (550, 700)}[t]
                    if not (lo <= len(df) <= hi):
                        res["pass"] = False
            except Exception as e:  # noqa: BLE001
                res["pass"] = False
                info["note"] += f"; parse error {type(e).__name__}: {e}"
        res["funds"][t] = info
    return res


def sample_tickers(tickers: dict):
    rng = random.Random(42)
    half = SAMPLE_SIZE // 2
    out = []
    for t in ("SPMD", "SPSM"):
        pool = sorted(set(tickers.get(t, [])))
        out += rng.sample(pool, min(half, len(pool)))
    return out


def check_b(sample):
    import yfinance as yf
    got = {"sector": 0, "industry": 0, "marketCap": 0}
    errors, rate_limited, n = [], False, 0
    t0 = time.time()
    for sym in sample:
        n += 1
        try:
            info = yf.Ticker(sym).info or {}
            for k in got:
                if info.get(k):
                    got[k] += 1
        except Exception as e:  # noqa: BLE001
            msg = f"{type(e).__name__}: {str(e)[:100]}"
            errors.append(f"{sym}: {msg}")
            low = msg.lower()
            if "429" in low or "too many" in low or "ratelimit" in low or "rate limit" in low:
                rate_limited = True
    secs = time.time() - t0
    pct = {k: (100.0 * v / n if n else 0.0) for k, v in got.items()}
    ok = n > 0 and min(pct.values()) >= 80.0 and not rate_limited
    return {"pass": ok, "n": n, "got": got, "pct": pct, "secs": secs,
            "rate_limited": rate_limited, "errors": errors}


def check_c():
    content, note = fetch(CBOE_URL, timeout=30)
    res = {"pass": False, "note": note, "rows": 0, "last": ""}
    if content:
        lines = [l for l in content.decode("utf-8", "replace").splitlines() if l.strip()]
        res["rows"] = len(lines)
        res["last"] = lines[-1][:120] if lines else ""
        res["pass"] = len(lines) > 100
        # staleness: find the last parseable date in the file
        res["last_date"] = ""
        for l in reversed(lines):
            try:
                d0 = dt.datetime.strptime(l.split(",")[0].strip(), "%m/%d/%Y").date()
                res["last_date"] = d0.isoformat()
                res["stale_days"] = (dt.date.today() - d0).days
                if res["stale_days"] > 14:
                    res["pass"] = False
                break
            except ValueError:
                continue
    return res


def check_d():
    import yfinance as yf
    res = {"info": {}, "hist": {}}
    try:
        info = yf.Ticker("SPY").info or {}
        for k in ("trailingPE", "forwardPE"):
            res["info"][k] = info.get(k)
    except Exception as e:  # noqa: BLE001
        res["info"]["error"] = f"{type(e).__name__}: {str(e)[:120]}"
    for sym in ("^SP400", "^SP600"):
        try:
            h = yf.Ticker(sym).history(period="1y", interval="1d")
            if h is None or h.empty:
                res["hist"][sym] = {"rows": 0, "last": ""}
            else:
                res["hist"][sym] = {"rows": len(h), "last": str(h.index[-1].date())}
        except Exception as e:  # noqa: BLE001
            res["hist"][sym] = {"rows": 0, "last": "", "error": f"{type(e).__name__}: {str(e)[:120]}"}
    res["pass_pe"] = any(res["info"].get(k) for k in ("trailingPE", "forwardPE"))
    res["pass_hist"] = all(v["rows"] > 200 for v in res["hist"].values())
    res["pass"] = res["pass_pe"] and res["pass_hist"]
    return res


def pf(ok):
    return "PASS" if ok else "FAIL"


def render(a, b, c, d, stamp):
    L = []
    L.append("# Source verification report\n")
    L.append(f"Generated {stamp} by `tools/verify_sources.py` (keyless; Russell not checked).\n")
    L.append("## Decision gate\n")
    L.append(f"- (a) State Street holdings: {pf(a['pass'])}")
    L.append(f"- (b) Yahoo per-ticker fundamentals: {pf(b['pass'])}")
    L.append(f"- (c) CBOE total put/call: {pf(c['pass'])}")
    L.append(f"- (d) Yahoo index valuation / index history: {pf(d['pass'])}\n")
    L.append("Recommended actions:")
    L.append("- (a) " + ("holdings source works; use it for S&P 400/600 membership."
             if a["pass"] else "FAIL: use the spec section 6 fallback (membership CSV committed, refreshed monthly)."))
    L.append("- (b) " + ("fields coverage is adequate and no rate limiting seen."
             if b["pass"] else "FAIL (under 80% fields or rate limited): Task 6 must use the per-night cap (`max_new=300`)."))
    L.append("- (c) " + ("put/call usable." if c["pass"] else
             "FAIL (unreachable or stale; the CSV may have stopped updating): Risk tab ships without put/call."))
    L.append("- (d) " + ("ETF PE and index history available." if d["pass"] else
             "Partial or FAIL: see details; do not rely on missing items."))
    L.append("\n## (a) State Street holdings (SPMD, SPSM)\n")
    L.append(f"Result: **{pf(a['pass'])}**\n")
    L.append("| Fund | Rows | Holdings as of | Bytes | Fetch note |\n|---|---|---|---|---|")
    for t, i in a["funds"].items():
        L.append(f"| {t} | {i['rows']} | {i['as_of'] or 'n/a'} | {i['bytes']} | {i['note']} |")
    L.append("\n## (b) yfinance Ticker.info on sampled S&P 400/600 names\n")
    L.append(f"Result: **{pf(b['pass'])}**\n")
    L.append(f"- Tickers sampled: {b['n']}")
    for k in ("sector", "industry", "marketCap"):
        L.append(f"- {k}: {b['got'][k]}/{b['n']} ({b['pct'][k]:.1f}%)")
    L.append(f"- Elapsed: {b['secs']:.1f} s")
    L.append(f"- Rate limited: {'yes' if b['rate_limited'] else 'no'}")
    L.append(f"- Errors: {len(b['errors'])}")
    for e in b["errors"][:10]:
        L.append(f"  - {e}")
    L.append("\n## (c) CBOE total put/call CSV\n")
    L.append(f"Result: **{pf(c['pass'])}**\n")
    L.append(f"- URL: {CBOE_URL}")
    L.append(f"- Rows: {c['rows']}; last line: `{c['last']}`")
    L.append(f"- Last data date: {c.get('last_date') or 'n/a'} (age {c.get('stale_days', 'n/a')} days; stale if over 14)")
    L.append(f"- Fetch note: {c['note']}")
    L.append("\n## (d) Yahoo index valuation and index history\n")
    L.append(f"Result: **{pf(d['pass'])}**\n")
    L.append(f"- SPY trailingPE: {d['info'].get('trailingPE')}; forwardPE: {d['info'].get('forwardPE')}"
             + (f" ({d['info']['error']})" if "error" in d["info"] else ""))
    for sym, v in d["hist"].items():
        L.append(f"- {sym} daily history (1y): {v['rows']} rows, last {v['last'] or 'n/a'}"
                 + (f" ({v['error']})" if "error" in v else ""))
    L.append("")
    return "\n".join(L)


def main():
    a = check_a()
    sample = sample_tickers(a["tickers"])
    b = check_b(sample)
    c = check_c()
    d = check_d()
    stamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(render(a, b, c, d, stamp), encoding="utf-8")
    print(f"wrote {OUT}")
    for name, r in (("a", a), ("b", b), ("c", c), ("d", d)):
        print(name, pf(r["pass"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
