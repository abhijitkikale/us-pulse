"""Static and (optional) browser checks of pipeline/template.html against the payload the pipeline builds."""
import json
import re
import shutil
import subprocess
from html.parser import HTMLParser
from pathlib import Path

import pandas as pd
import pytest

import build
from assemble import assemble

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "pipeline" / "template.html"
FIXTURE = ROOT / "tests" / "fixtures" / "payload_small.json"
TABS = ["overview", "sectors", "breadth", "activity", "valuation", "risk", "momentum", "etfs"]
TAB_NAMES = ["Overview", "Sectors", "Breadth & Trend", "Market Activity", "Valuation", "Risk Monitor",
             "Momentum Stocks", "ETFs"]
# JS names reached through `D.` that are not payload keys (none expected; kept explicit for future Date use)
NOT_KEYS = {"length"}


def _html():
    return TEMPLATE.read_text(encoding="utf-8")


def _inline_scripts(html):
    return [m.group(1) for m in re.finditer(r"<script>(.*?)</script>", html, re.S)]


def _app_script(html):
    return "\n".join(s for s in _inline_scripts(html) if "/*__PLOTLY__*/" not in s)


def _payload_keys():
    p = assemble(indices={}, asof=pd.Timestamp("2026-11-13"), members={}, stocks=[], dates=[], global_rows=[],
                 activity=None, etfs=[], etf_categories=[], status={}, price_asof=pd.Timestamp("2026-11-13"),
                 today=pd.Timestamp("2026-11-16"))
    return set(p)


class _Text(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts, self._skip, self.tabs = [], 0, []

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip += 1
        a = dict(attrs)
        if tag == "button" and "data-tab" in a:
            self.tabs.append(a["data-tab"])
        for k in ("title", "alt", "placeholder"):
            if a.get(k):
                self.parts.append(a[k])

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def _parsed():
    p = _Text()
    p.feed(_html())
    return p


def test_template_node_syntax_ok(tmp_path):
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    scripts = [s for s in _inline_scripts(_html()) if "/*__PLOTLY__*/" not in s]
    assert scripts
    for i, s in enumerate(scripts):
        f = tmp_path / f"s{i}.js"
        f.write_text(s.replace("/*__DATA__*/null", "null"), encoding="utf-8")
        r = subprocess.run([node, "--check", str(f)], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr


def test_template_reads_only_known_payload_keys():
    keys = set(re.findall(r"\bD\.([A-Za-z_]\w*)", _app_script(_html()))) - NOT_KEYS
    assert keys, "the script reads no payload keys"
    assert keys <= _payload_keys(), sorted(keys - _payload_keys())


FORBIDDEN = [r"Nifty", r"\bNSE\b", "₹", r"(?i)crore", r"Fyers", r"BharatPulse", r"SEBI", r"\bIST\b",
             r"India VIX", r"\bFII\b", r"\bDII\b", r"(?i)bharat", r"Kolkata", r"lakh", r"en-IN"]


@pytest.mark.parametrize("pattern", FORBIDDEN)
def test_no_india_strings(pattern):
    text = " ".join(_parsed().parts) + "\n" + _app_script(_html())
    hits = sorted({m.group(0) for m in re.finditer(pattern, text)})
    assert not hits, hits


def test_disclaimer_present():
    text = " ".join(" ".join(_parsed().parts).split())
    assert "not investment advice" in text
    assert "current constituents" in text


def test_no_image_assets_or_external_resources():
    html = _html()
    assert "<img" not in html and "__LOGO__" not in html and "__FAVICON__" not in html
    assert not re.search(r"""(src|href)\s*=\s*["']https?://""", html)
    assert "raw.githubusercontent" not in html and "fetch(" not in _app_script(html)


def test_stale_banner_markup_present():
    assert re.search(r"""id=["']stale-banner["']""", _html())


def test_stale_banner_logic_present():
    js = _app_script(_html())
    assert "D.stale" in js and "D.stock_asof" in js and "D.stale_note" in js
    assert re.search(r"STALE_DAYS\s*=\s*4\b", js)
    assert re.search(r"/\s*864e5\s*\)?\s*>\s*STALE_DAYS", js)
    assert "data as of" in js


def test_tabs_in_order():
    p = _parsed()
    assert p.tabs == TABS
    html = _html()
    names = re.findall(r"<button data-tab=\"\w+\"[^>]*>(.*?)</button>", html)
    assert [n.replace("&amp;", "&") for n in names] == TAB_NAMES
    for t in TABS:
        assert f'id="tab-{t}"' in html


def test_removed_tabs_are_gone():
    html = _html()
    for gone in ("tab-options", "tab-vprofile", "tab-surface3d", "tab-flows", "renderOptions", "renderVProfile",
                 "renderSurface3D", "renderFlows", "pollLive", "D.flows", "D.options", "D.credit"):
        assert gone not in html, gone


def test_breadth_segments_are_us_indices():
    assert "const SEGS=['S&P 500','S&P 400','S&P 600'];" in _html()


def test_fixture_is_a_pipeline_payload():
    d = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert set(d) == _payload_keys()
    groups = [i["group"] for i in d["indices"]]
    assert groups.count("sector") == 11 and "theme" in groups
    assert len(d["etfs"]) >= 4 and any(str(v).startswith("stale") for v in d["status"].values())
    assert FIXTURE.stat().st_size < 300_000


# ---------- Task 14: sectors, themes, momentum defaults ----------

def _page_text():
    return " ".join(_parsed().parts) + "\n" + _app_script(_html())


def test_momentum_defaults_are_half_half():
    js = _app_script(_html())
    assert re.search(r"const MOM=\{ws:0\.5,wt:0\.5", js)
    assert "ws:0.6" not in js and "wt:0.4" not in js


def test_reset_button_restores_half_half():
    js = _app_script(_html())
    m = re.search(r"\$\('#mom-reset'\)\.onclick=.*", js)
    assert m, "no reset handler"
    line = m.group(0)
    assert "MOM.ws=0.5" in line and "MOM.wt=0.5" in line
    assert "0.6" not in line and "0.4" not in line
    assert 'title="Back to 0.5 / 0.5"' in _html()


def test_momentum_weights_keep_usp_prefix():
    js = _app_script(_html())
    keys = set(re.findall(r"localStorage\.(?:get|set)Item\('([^']+)'", js))
    assert keys and all(k.startswith("usp_") for k in keys), keys


def test_template_mentions_equal_weight_and_relative_strength():
    text = _page_text()
    assert "Equal-weight" in text and "vs S&P 500" in text and "Cap-weighted (ETF)" in text


def test_themes_table_exists():
    html = _html()
    assert re.search(r"""<table[^>]*id=["']tb-themes["']""", html)
    assert "Themes" in " ".join(_parsed().parts)


def test_illiquid_checkbox_exists():
    html = _html()
    assert re.search(r"""<input type="checkbox" id="mom-illiq"[^>]*>\s*include illiquid""", html)
    assert "MOM.illiq" in _app_script(html)
    text = " ".join(" ".join(_parsed().parts).split())
    assert ("Rankings use current index constituents (S&P 500, 400, 600); stocks under $5 or with under $5M "
            "average daily dollar volume are hidden unless you include illiquid.") in text


def test_themes_not_used_for_stock_assignment():
    js = _app_script(_html())
    assert re.search(r"const SECT = D\.indices\.filter\(i=>i\.group==='sector'\);", js)
    assert re.search(r"const THEME = D\.indices\.filter\(i\s*=>\s*i\.group\s*===\s*'theme'\);", js)
    body = re.search(r"function momRows\(H\)\{(.*?)\n\}", js, re.S).group(1)
    assert "THEME" not in body and "'theme'" not in body
    assert "sectSet=new Set(SECT.map(" in body
    sc = re.search(r"function sectComposite\(H\)\{(.*?)\n\}", js, re.S).group(1)
    assert "SECT.map(" in sc and "THEME" not in sc


def test_drawer_title_uses_label():
    js = _app_script(_html())
    assert "title=`${ix.label} (${ix.nse})`" in js
    assert "title=ix.nse" not in js
    assert "a.download=(fname.replace(" in js


def test_status_fetched_is_ok():
    js = _app_script(_html())
    m = re.search(r"const okStatus=.*", js)
    assert m and "fetched" in m.group(0) and "cached" in m.group(0)
    assert "okStatus(v)" in re.search(r"\$\('#status'\)\.innerHTML=.*", js).group(0)


def test_et_clock_uses_format_to_parts():
    js = _app_script(_html())
    assert "formatToParts" in js and "America/New_York" in js
    assert "new Date(new Date().toLocaleString(" not in js


def test_banner_skips_freshness_status():
    js = _app_script(_html())
    line = re.search(r"const bad=Object\.entries\(D\.status.*", js).group(0)
    assert "'freshness'" in line


def test_csv_doubles_embedded_quotes():
    js = _app_script(_html())
    assert "const csvq=" in js
    row = re.search(r"rows\.map\(s=>\[(.*?)\]\.map", js).group(1)
    assert "csvq(s.n)" in row and "csvq(s.i)" in row and "'\"'+s.i+'\"'" not in row


def test_sma_comparison_is_all_tracked_stocks():
    html = _html()
    assert "All tracked stocks" in _app_script(html)
    assert "Grey bar = S&amp;P 500" not in html and "Grey bar = all tracked stocks" in html


# ---------- Task 15: ETF tab ----------

def test_etf_tab_markup_present():
    html = _html()
    for i in ("tab-etfs", "tb-etf", "etf-cat"):
        assert re.search(rf"""id=["']{i}["']""", html), i
    assert re.search(r"""<table[^>]*id=["']tb-etf["']""", html)
    assert re.search(r"""<select[^>]*id=["']etf-cat["']""", html)


def test_etf_overall_rank_note_present():
    text = " ".join(" ".join(_parsed().parts).split()) + "\n" + _app_script(_html())
    assert "mixes unlike funds" in text
    assert "uses the method and weights set on the Momentum Stocks tab" in text


def test_render_tab_map_includes_etfs():
    js = _app_script(_html())
    m = re.search(r"function renderTab\(\)\{\(\{(.*?)\}\)\[S\.tab\]\(\)\}", js)
    assert m, "renderTab map not found"
    entries = dict(kv.split(":", 1) for kv in m.group(1).split(","))
    fn = entries["etfs"].strip()
    assert fn != "placeholder" and re.fullmatch(r"[A-Za-z_]\w*", fn), fn
    assert re.search(rf"function {fn}\(", js), fn


def test_etf_categories_in_canonical_order():
    js = _app_script(_html())
    order = ["US Sector", "Theme", "Size", "Style & Factor", "International Country", "International Region",
             "Bonds", "Commodities", "Dividend & Income", "Real Estate", "Currency & Other"]
    m = re.search(r"const ETF_CAT_ORDER=\[(.*?)\];", js)
    assert m and re.findall(r"'([^']+)'", m.group(1)) == order


# ---------- optional: load the rendered fixture in headless Chromium ----------

def _render_fixture(tmp_path, payload=None):
    payload = payload or json.loads(FIXTURE.read_text(encoding="utf-8"))
    return build.render(payload, tmp_path / "dashboard.html")


def _browser():
    sync = pytest.importorskip("playwright.sync_api")
    pw = sync.sync_playwright().start()
    try:
        b = pw.chromium.launch()
    except Exception as e:                                  # browser binary missing
        pw.stop()
        pytest.skip(f"chromium unavailable: {e}")
    return pw, b


def _open(b, out):
    page = b.new_page()
    errors = []
    page.on("console", lambda m: errors.append(f"console.{m.type}: {m.text}") if m.type == "error" else None)
    page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
    page.goto(out.as_uri())
    page.wait_for_function("window.__ready === true", timeout=20000)
    return page, errors


def test_page_loads_without_console_errors(tmp_path):
    out = _render_fixture(tmp_path)
    pw, b = _browser()
    try:
        page, errors = _open(b, out)
        per_tab = {}
        for t in TABS:
            before = len(errors)
            page.click(f'nav button[data-tab="{t}"]')
            page.wait_for_timeout(250)
            assert page.is_visible(f"#tab-{t}"), t
            per_tab[t] = errors[before:]
        page.click('nav button[data-tab="overview"]')
        page.evaluate("$('#ch-bench').emit('plotly_click',{points:[{customdata:'S&P 500'}]})")   # a bar click
        page.wait_for_timeout(250)
        assert page.is_visible("#drawer.open")
        page.evaluate("closeDrawer()")
        page.click("#tb-globrank tr.click")                 # a US row of the global rank table
        page.wait_for_timeout(250)
        assert page.inner_text("#dtitle") in ("S&P 500 (^GSPC)", "Dow Jones (^DJI)", "Nasdaq 100 (^NDX)",
                                              "S&P 400 (^SP400)", "S&P 600 (^SP600)")
        page.evaluate("closeDrawer()")
        page.evaluate("openIndex('Technology',true)")       # a sector drawer
        page.wait_for_timeout(250)
        assert page.is_visible("#drawer.open")
        page.click("#d-tbl tbody tr.click")                 # a stock inside it
        page.wait_for_timeout(250)
        assert errors == [], (errors, per_tab)
        assert "US Pulse" in page.title()
        assert "data as of 13 Nov 2026" in page.inner_text("header")
        banner = page.inner_text("#stale-banner")           # the fixture's status has one stale source ('etf')
        assert page.is_visible("#stale-banner") and "etf" in banner
    finally:
        b.close()
        pw.stop()


def test_sectors_themes_and_momentum_render(tmp_path):
    d = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert any(s["liq"] is False for s in d["stocks"]), "fixture needs an illiquid stock"
    n_themes = sum(i["group"] == "theme" for i in d["indices"])
    for ix in d["indices"]:                                  # the small fixture has too few stocks per sector for ew
        if ix["label"] == "Technology":
            ix["ew"]["1M"] = 1.234
    out = _render_fixture(tmp_path, d)
    pw, b = _browser()
    try:
        page, errors = _open(b, out)
        page.evaluate("try{localStorage.clear()}catch(e){}")
        per_tab = {}
        for t in TABS:
            before = len(errors)
            page.click(f'nav button[data-tab="{t}"]')
            page.wait_for_timeout(200)
            per_tab[t] = errors[before:]
        assert all(v == [] for v in per_tab.values()), per_tab
        page.click('nav button[data-tab="sectors"]')
        page.click('.pseg[data-k="secTbl"] button[data-p="1M"]')
        assert page.locator("#tb-secrank tbody tr").count() == 11
        assert page.locator("#tb-themes tbody tr").count() == n_themes
        head = page.inner_text("#tb-secrank thead")
        assert "Cap-weighted (ETF)" in head and "Equal-weight" in head and "vs S&P 500" in head
        assert "vs S&P 500" in page.inner_text("#tb-themes thead")
        tech = page.locator('#tb-secrank tr[data-l="Technology"] td').all_inner_texts()
        assert tech[2] == "+1.2%" and tech[3].endswith(" pts"), tech
        for tbl in ("#tb-secrank", "#tb-themes"):
            cells = page.locator(f"{tbl} td.rs").all_inner_texts()
            assert cells and all(c.strip() not in ("", "–") for c in cells), (tbl, cells)
        page.click("#tb-themes tbody tr.click >> nth=0")
        page.wait_for_timeout(250)
        assert page.is_visible("#drawer.open")
        assert re.fullmatch(r".+ \([A-Z]+\)", page.inner_text("#dtitle"))
        page.evaluate("closeDrawer()")
        page.evaluate("openIndex('Technology',true)")
        page.wait_for_timeout(250)
        assert page.inner_text("#dtitle") == "Technology (XLK)"
        with page.expect_download() as dl:
            page.click("#csv")
        assert dl.value.suggested_filename == "Technology.csv"
        page.evaluate("closeDrawer()")
        page.click('nav button[data-tab="momentum"]')
        page.wait_for_timeout(200)
        assert page.input_value("#mom-ws") == "0.5" and page.input_value("#mom-wt") == "0.5"
        assert not page.is_checked("#mom-illiq")
        n_off = page.locator("#tb-mom tbody tr").count()
        page.check("#mom-illiq")
        page.wait_for_timeout(200)
        n_on = page.locator("#tb-mom tbody tr").count()
        assert 0 < n_off < n_on, (n_off, n_on)
        page.fill("#mom-ws", "0.8")
        page.click("#mom-reset")
        assert page.input_value("#mom-ws") == "0.5" and page.input_value("#mom-wt") == "0.5"
        row = page.locator("#status tr", has_text="sectors").inner_text()
        assert "⚠" not in row and "✓" in row
        assert errors == [], errors
    finally:
        b.close()
        pw.stop()


MOM_BY_SECTOR = """() => { const out = {}; momRows(S.momH).rows.forEach(r => (out[r.sec] ??= []).push([r.s.s, r.tRank, r.nIn]));
  return out; }"""


def test_momentum_ranks_liquid_stocks_only(tmp_path):
    d = json.loads(FIXTURE.read_text(encoding="utf-8"))
    ill = [s["s"] for s in d["stocks"] if s["liq"] is False]
    assert ill == ["TK20"], ill
    out = _render_fixture(tmp_path, d)
    pw, b = _browser()
    try:
        page, errors = _open(b, out)
        page.click('nav button[data-tab="momentum"]')
        page.wait_for_timeout(200)
        assert not page.is_checked("#mom-illiq")
        off = page.evaluate(MOM_BY_SECTOR)
        for sec, rows in off.items():               # every sector's listed stocks are ranked among themselves only
            assert all(s not in ill for s, _, _ in rows), (sec, rows)
            assert sorted(r for _, r, _ in rows)[0] == 1, (sec, rows)
            assert all(n == len(rows) for _, _, n in rows), (sec, rows)
        cells = page.locator("#tb-mom tbody tr").evaluate_all(
            "trs => trs.map(t => [t.dataset.s, t.cells[2].innerText, t.cells[5].innerText])")
        by_sec = {}
        for sym, sec, rank in cells:
            by_sec.setdefault(sec, []).append(int(rank.split("/")[0]))
        assert by_sec and all(min(v) == 1 for v in by_sec.values()), by_sec
        assert "1 illiquid hidden" in page.inner_text("#mom-sub")
        page.check("#mom-illiq")
        page.wait_for_timeout(200)
        on = page.evaluate(MOM_BY_SECTOR)
        sec = next(k for k, rows in on.items() if any(s == "TK20" for s, _, _ in rows))
        assert dict((s, r) for s, r, _ in on[sec])["TK20"] == 1, on[sec]   # the illiquid stock would have led its sector
        assert all(r > 1 for s, r, _ in on[sec] if s != "TK20")
        row = page.locator('#tb-mom tr[data-s="TK20"]')
        assert row.count() == 1 and row.locator("td").nth(5).inner_text().startswith("1/")
        assert "illiquid hidden" not in page.inner_text("#mom-sub")
        assert errors == [], errors
    finally:
        b.close()
        pw.stop()


def test_stale_banner_hidden_for_fresh_ok_payload(tmp_path):
    d = json.loads(FIXTURE.read_text(encoding="utf-8"))
    d["stock_asof"] = pd.Timestamp.now().strftime("%d %b %Y")
    d["status"] = {k: "ok" for k in d["status"]}
    d["stale"], d["stale_note"] = False, ""
    out = _render_fixture(tmp_path, d)
    pw, b = _browser()
    try:
        page, errors = _open(b, out)
        assert not page.is_visible("#stale-banner")
        d["stale"], d["stale_note"] = True, "Prices end 12 Nov 2026; the 13 Nov 2026 close is missing"
        page, errors2 = _open(b, _render_fixture(tmp_path / "s", d))
        assert page.is_visible("#stale-banner")
        assert "close is missing" in page.inner_text("#stale-banner")
        d["stale"], d["stale_note"] = False, ""             # build said fresh, but the data is 6 days old in the browser
        d["stock_asof"] = (pd.Timestamp.now() - pd.Timedelta(days=6)).strftime("%d %b %Y")
        page, errors3 = _open(b, _render_fixture(tmp_path / "o", d))
        assert page.is_visible("#stale-banner")
        assert "more than 4 days ago" in page.inner_text("#stale-banner")
        d["stock_asof"] = (pd.Timestamp.now() - pd.Timedelta(days=3)).strftime("%d %b %Y")   # a long weekend is fine
        page, errors4 = _open(b, _render_fixture(tmp_path / "w", d))
        assert not page.is_visible("#stale-banner")
        assert errors == errors2 == errors3 == errors4 == []
    finally:
        b.close()
        pw.stop()


# ---------- every payload string is escaped before it reaches HTML ----------

HOSTILE = "\"><img src=x onerror=window.__xss=1>&'\""


def _hostile_payload():
    d = json.loads(FIXTURE.read_text(encoding="utf-8"))
    st = d["stocks"][0]
    old, new = st["s"], "TK" + HOSTILE
    st["s"], st["n"], st["i"] = new, "Name " + HOSTILE, "Industry " + HOSTILE
    for k, syms in d["members"].items():
        d["members"][k] = [new if s == old else s for s in syms]
    for rows in (d["activity"]["leaders"]["turnover"], d["activity"]["leaders"]["volume"], d["activity"]["spikes"]):
        for r in rows:
            if r["s"] == old:
                r["s"] = new
    sec_old, sec_new = "Technology", "Tech " + HOSTILE
    for ix in d["indices"]:
        if ix["label"] == sec_old:
            ix["label"], ix["nse"] = sec_new, "XLK" + HOSTILE
    d["members"][sec_new] = d["members"].pop(sec_old)
    for s in d["stocks"]:
        s["x"] = [sec_new if x == sec_old else x for x in s["x"]]
    for ix in d["indices"]:
        if ix["group"] == "theme":
            ix["label"], ix["nse"] = "Theme " + HOSTILE, "SMH" + HOSTILE
            break
    d["status"]["src " + HOSTILE] = "stale: " + HOSTILE
    d["asof"] = d["stock_asof"] = "13 Nov 2026" + HOSTILE
    d["stale"], d["stale_note"] = True, "note " + HOSTILE
    d["activity"]["asof"] = "2026-11-13" + HOSTILE
    d["global"][0]["name"] = "Index " + HOSTILE + " (USA)"
    d["etfs"][0]["t"], d["etfs"][0]["n"], d["etfs"][0]["c"] = "ET" + HOSTILE, "ETF " + HOSTILE, "Cat " + HOSTILE
    d["etf_categories"] = sorted({e["c"] for e in d["etfs"]})
    d["universe_note"] = d["mcap_note"] = "note " + HOSTILE
    return d, new, sec_new


def test_esc_escapes_quotes_too():
    js = _app_script(_html())
    m = re.search(r"const esc = .*", js)
    assert m and "&quot;" in m.group(0) and "&#39;" in m.group(0)


def test_hostile_strings_never_appear_raw_in_rendered_html(tmp_path):
    d, _, _ = _hostile_payload()
    html = build.render(d, tmp_path / "dashboard.html", plotly_js="").read_text(encoding="utf-8")
    assert "<img src=x onerror" not in html and "onerror=window.__xss=1>" not in html


def test_hostile_payload_does_not_execute(tmp_path):
    d, sym, sec = _hostile_payload()
    out = _render_fixture(tmp_path, d)
    pw, b = _browser()
    try:
        page, errors = _open(b, out)
        for t in TABS:
            page.click(f'nav button[data-tab="{t}"]')
            page.wait_for_timeout(200)
            for q in ("1Y", "1D"):                               # every period control of the tab (no page-wide bar)
                for btn in page.locator(f'#tab-{t} .pseg button[data-p="{q}"]').all():
                    btn.click()
            for sel in ("#secH", "#thH", "#mom-h", "#etf-h"):
                if page.is_visible(sel):
                    page.select_option(sel, "1Y")
        page.click('nav button[data-tab="sectors"]')
        assert sec in page.inner_text("#tb-secrank")             # shown as literal text
        page.click(f'#tb-secrank tr[data-l="{sec.replace(chr(34), chr(92) + chr(34))}"]')
        page.wait_for_timeout(250)
        assert page.is_visible("#drawer.open")
        assert sec in page.inner_text("#dtitle")
        page.evaluate("closeDrawer()")
        theme = "Theme " + HOSTILE
        assert theme in page.inner_text("#tb-themes")
        page.click(f'#tb-themes tr[data-l="{theme.replace(chr(34), chr(92) + chr(34))}"]')
        page.wait_for_timeout(250)
        assert page.is_visible("#drawer.open") and theme in page.inner_text("#dtitle")
        page.evaluate("closeDrawer()")
        page.click('nav button[data-tab="momentum"]')
        page.check("#mom-illiq")
        page.select_option("#mom-h", "6M")                      # the 1Y set above leaves no stock with enough history
        page.wait_for_timeout(200)
        opts = page.locator("#mom-sec option").all_inner_texts()
        assert sec in opts, opts                                  # the hostile sector is a literal option label
        page.select_option("#mom-sec", sec)
        page.fill("#mom-mcap", "300")
        page.fill("#mom-cap", "1")
        page.click('#mom-mcap-q button[data-mcap="2000"]')
        page.click('#mom-mcap-q button[data-mcap=""]')
        page.fill("#mom-cap", "")
        page.select_option("#mom-sec", "")
        page.click('nav button[data-tab="sectors"]')
        page.evaluate("s=>openStock(s,true)", sym)
        page.wait_for_timeout(250)
        assert sym in page.inner_text("#dtitle")
        page.evaluate("closeDrawer()")
        page.click('nav button[data-tab="activity"]')
        page.click(f'#act-l tr[data-s="{sym.replace(chr(34), chr(92) + chr(34))}"]')
        page.wait_for_timeout(250)
        assert sym in page.inner_text("#dtitle")
        assert "src " + HOSTILE in page.inner_text("#status")
        page.evaluate("closeDrawer()")
        page.click('nav button[data-tab="etfs"]')
        assert "Cat " + HOSTILE in page.locator("#etf-cat option").all_inner_texts()
        page.select_option("#etf-h", "3M")
        page.click('#etf-aum-q button[data-aum="500"]')
        page.click('#etf-aum-q button[data-aum=""]')
        page.select_option("#etf-cat", "Cat " + HOSTILE)
        page.wait_for_timeout(150)
        assert page.locator("#tb-etf tbody tr").count() == 1
        assert "ETF " + HOSTILE in page.inner_text("#tb-etf") and "Cat " + HOSTILE in page.inner_text("#tb-etf")
        page.click("#tb-etf tbody tr")
        page.wait_for_timeout(250)
        assert page.inner_text("#dtitle") == "ETF " + HOSTILE + " (ET" + HOSTILE + ")"
        page.evaluate("closeDrawer()")
        assert page.evaluate("window.__xss") is None
        assert page.locator("img").count() == 0
        assert errors == [], errors
    finally:
        b.close()
        pw.stop()


# ---------- Task 15: the ETF tab in a browser ----------

def _expected_category_order(etfs, horizon="6M"):
    """Hand calculation of the page's default composite (method 'slice', skip the latest week, weights 1)."""
    order = ["1W", "1M", "3M", "6M", "1Y", "3Y", "5Y"]
    inc = [q for q in order[: order.index(horizon) + 1] if q != "1W"]
    prev = {"1M": "1W", "3M": "1M", "6M": "3M", "1Y": "6M", "3Y": "1Y", "5Y": "3Y"}
    yrs = {"3Y": 3, "5Y": 5}

    def tot(r, q):
        return (1 + r / 100) ** yrs.get(q, 1)

    def sliced(e, q):          # this period's own slice of time: growth over q divided by growth over the period before
        a, b = e["r"].get(q), e["r"].get(prev[q])
        return None if a is None or b is None else (tot(a, q) / tot(b, prev[q]) - 1) * 100

    rank = {}
    for q in inc:
        vals = sorted(((sliced(e, q), e["t"]) for e in etfs if sliced(e, q) is not None), key=lambda x: -x[0])
        for k, (_, t) in enumerate(vals):
            rank.setdefault(t, {})[q] = k + 1
    ok = [e["t"] for e in etfs if all(q in rank.get(e["t"], {}) for q in inc)]
    bad = sorted(e["t"] for e in etfs if e["t"] not in ok)
    ok.sort(key=lambda t: (sum(rank[t][q] for q in inc), [rank[t][q] for q in inc]))
    return ok, bad


def test_etf_tab_renders_ranks_and_drawer(tmp_path):
    d = json.loads(FIXTURE.read_text(encoding="utf-8"))
    by_cat = {}
    for e in d["etfs"]:
        by_cat.setdefault(e["c"], []).append(e)
    big = sorted(c for c, v in by_cat.items() if len(v) >= 4)
    assert len(big) >= 2, by_cat.keys()
    short = [e["t"] for e in d["etfs"] if e["r"]["6M"] is None]
    assert short, "fixture needs an ETF with a short history"
    out = _render_fixture(tmp_path, d)
    pw, b = _browser()
    try:
        page, errors = _open(b, out)
        page.evaluate("try{localStorage.clear()}catch(e){}")
        per_tab = {}
        for t in TABS:
            before = len(errors)
            page.click(f'nav button[data-tab="{t}"]')
            page.wait_for_timeout(200)
            per_tab[t] = errors[before:]
        assert all(v == [] for v in per_tab.values()), per_tab
        page.click('nav button[data-tab="etfs"]')
        assert page.input_value("#etf-cat") == "All"
        opts = page.locator("#etf-cat option").all_inner_texts()
        assert opts == ["All", "US Sector", "Size", "Bonds", "Commodities"], opts
        assert page.locator("#tb-etf tbody tr").count() == len(d["etfs"])
        assert "mixes unlike funds" in page.inner_text("#tb-etf thead")
        assert "uses the method and weights set on the Momentum Stocks tab" in page.inner_text("#tab-etfs")
        all_rows = page.locator("#tb-etf tbody tr").evaluate_all("trs => trs.map(t => t.dataset.t)")
        exp_all, bad_all = _expected_category_order(d["etfs"])
        assert all_rows == exp_all + bad_all, (all_rows, exp_all, bad_all)
        seen = set()
        for cat in big:
            page.select_option("#etf-cat", cat)
            page.wait_for_timeout(150)
            rows = page.locator("#tb-etf tbody tr").evaluate_all(
                "trs => trs.map(t => [t.dataset.t, t.cells[3].innerText])")
            exp, bad = _expected_category_order(by_cat[cat])
            assert [r[0] for r in rows] == exp + bad, (cat, rows, exp, bad)
            n = len(exp)
            assert [r[1] for r in rows] == [f"{k + 1}/{n}" for k in range(n)] + ["n/a"] * len(bad), rows
            seen.add(tuple(r[0] for r in rows))
        assert len(seen) == len(big)                         # switching category changes the rows
        cat = next(c for c in big if any(e["t"] in short for e in by_cat[c]))
        page.select_option("#etf-cat", cat)
        page.wait_for_timeout(150)
        last = page.locator("#tb-etf tbody tr").last
        assert last.get_attribute("data-t") in short and "n/a" in last.inner_text()
        page.click(f'#tb-etf tr[data-t="{short[0]}"]')       # a drawer for the short-history ETF
        page.wait_for_timeout(250)
        assert page.is_visible("#drawer.open")
        e = next(x for x in d["etfs"] if x["t"] == short[0])
        assert page.inner_text("#dtitle") == f'{e["n"]} ({e["t"]})'
        npts = page.evaluate("$('#d-px').data[0].x.length")
        assert npts == len(e["ser"]) and page.evaluate("$('#d-px').data.length") == 1   # no SMA lines for ETFs
        assert page.evaluate("$('#d-px').data[0].x.at(-1)") == d["dates"][-1]
        page.evaluate("closeDrawer()")
        page.evaluate("""() => { const e = D.etfs[1]; e.ser = Array(D.dates.length + 7).fill(10); openEtf(e.t, true); }""")
        page.wait_for_timeout(250)                           # a ser longer than the dates axis is cut from the left
        assert page.evaluate("$('#d-px').data[0].x.length") == len(d["dates"])
        assert page.evaluate("$('#d-px').data[0].y.length") == len(d["dates"])
        page.evaluate("closeDrawer()")
        page.select_option("#etf-cat", "All")
        page.click("#tb-etf tbody tr >> nth=0")
        page.wait_for_timeout(250)
        assert page.is_visible("#drawer.open")
        page.evaluate("closeDrawer()")
        page.evaluate("""() => { const e = D.etfs[0]; delete e.ser; renderETFs(); openEtf(e.t, true); }""")   # no ser at all
        page.wait_for_timeout(250)
        assert page.is_visible("#drawer.open")
        page.evaluate("closeDrawer()")
        page.click('nav button[data-tab="momentum"]')        # a method change re-ranks the ETFs
        page.select_option("#mm-method", "cum")
        page.wait_for_timeout(150)
        page.click('nav button[data-tab="etfs"]')
        assert "cumulative" in page.inner_text("#etf-note")
        assert errors == [], errors
    finally:
        b.close()
        pw.stop()


# ---------- fixes batch 2: per-table periods, momentum filters, ETF AUM / horizon, Russell 2000 ----------

def test_no_page_wide_period_bar():
    html = _html()
    assert 'id="periods"' not in html and "#periods" not in html and "All charts" not in html
    js = _app_script(html)
    for k in ("globTbl", "secTbl", "thTbl"):
        assert f'data-k="{k}"' in html and f"S.pp.{k}" in js, k
    for sel, key in (("secH", "S.secH"), ("thH", "S.thH"), ("mom-h", "S.momH"), ("etf-h", "S.etfH")):
        assert re.search(rf'<select[^>]*id="{sel}"', html), sel
        assert f"{key}=$('#{sel}').value" in js, (sel, key)
    assert re.search(r"function renderETFs\(\)\{\s*const H=S\.etfH", js)
    assert "S.secH" not in re.search(r"function renderMomentum\(\)\{(.*?)\n\}", js, re.S).group(1)


def test_new_filter_controls_present_and_persisted():
    html, js = _html(), _app_script(_html())
    for i in ("mom-cap", "mom-mcap", "etf-aum", "etf-h", "mom-why"):
        assert re.search(rf'id="{i}"', html), i
    assert "Min market cap ($M)" in html and "Min AUM ($M)" in html and "Max stocks per sector" in html
    assert [b for b in re.findall(r'data-mcap="(\d*)"', html)] == ["300", "2000", "10000", ""]
    assert [b for b in re.findall(r'data-aum="(\d*)"', html)] == ["500", "1000", "5000", ""]
    keys = set(re.findall(r"localStorage\.(?:get|set)Item\('([^']+)'", js))
    assert {"usp_mom_mcap", "usp_etf_aum", "usp_mom_cap"} <= keys


SNAPSHOT = """() => { renderOverview(); renderSectors(); renderBreadth(); renderMomentum(); renderETFs();
  const t = id => document.getElementById(id).innerHTML;
  const c = id => JSON.stringify((document.getElementById(id).data || []).map(d => [d.x, d.y]));
  const out = {};
  for (const id of ['tb-globrank', 'tb-secrank', 'tb-themes', 'tb-mom', 'mom-sub', 'tb-etf', 'etf-note', 'tb-bands', 'tb-strength']) out[id] = t(id);
  for (const id of ['ch-bench', 'ch-glob', 'ch-sec', 'ch-sma', 'ch-ad']) out[id] = c(id);
  return out; }"""


def test_each_table_and_chart_has_its_own_period(tmp_path):
    out = _render_fixture(tmp_path)
    pw, b = _browser()
    try:
        page, errors = _open(b, out)
        assert page.locator("#periods").count() == 0
        steps = [  # (tab, action, control, value, keys that must change)
            ("overview", "seg", "bench", "1Y", {"ch-bench"}),
            ("overview", "seg", "glob", "6M", {"ch-glob"}),
            ("overview", "seg", "globTbl", "1Y", {"tb-globrank"}),
            ("sectors", "seg", "sec", "3M", {"ch-sec"}),
            ("sectors", "seg", "secTbl", "1Y", {"tb-secrank"}),
            ("sectors", "seg", "thTbl", "6M", {"tb-themes"}),
            ("sectors", "sel", "#secH", "3M", {"tb-secrank"}),
            ("sectors", "sel", "#thH", "1Y", {"tb-themes"}),
            ("breadth", "seg", "ad", "1Y", {"ch-ad"}),
            ("momentum", "sel", "#mom-h", "3M", {"tb-mom", "mom-sub"}),
            ("etfs", "sel", "#etf-h", "3M", {"tb-etf", "etf-note"}),
        ]
        for tab, kind, ctl, val, expect in steps:
            page.click(f'nav button[data-tab="{tab}"]')
            page.wait_for_timeout(100)
            before = page.evaluate(SNAPSHOT)
            if kind == "seg":
                page.click(f'.pseg[data-k="{ctl}"] button[data-p="{val}"]')
                assert page.locator(f'.pseg[data-k="{ctl}"] button.on').inner_text() == val
            else:
                page.select_option(ctl, val)
            page.wait_for_timeout(100)
            after = page.evaluate(SNAPSHOT)
            changed = {k for k in before if before[k] != after[k]}
            assert changed == expect, (ctl, val, changed, expect)
        assert page.evaluate("[S.secH, S.thH, S.momH, S.etfH]") == ["3M", "1Y", "3M", "3M"]
        assert page.inner_text("#tb-secrank thead th.sel >> nth=-1") == "1Y"         # its own period column
        assert page.inner_text("#tb-themes thead th.sel >> nth=-1") == "6M"
        assert page.inner_text("#tb-mom thead th.sel") == "3M"
        assert page.inner_text("#tb-etf thead th.sel") == "3M"
        assert errors == [], errors
    finally:
        b.close()
        pw.stop()


def _mom_dom(page):
    return page.locator("#tb-mom tbody tr").evaluate_all(
        "trs => trs.map(t => [t.dataset.s, t.cells[2].innerText, +t.cells[0].innerText, t.cells[5].innerText])")


def test_momentum_weights_line_and_linked_inputs(tmp_path):
    out = _render_fixture(tmp_path)
    pw, b = _browser()
    try:
        page, errors = _open(b, out)
        page.click('nav button[data-tab="momentum"]')
        for ws in ("0.2", "0.5", "0.8", "1"):
            page.fill("#mom-ws", ws)
            page.wait_for_timeout(100)
            assert float(page.input_value("#mom-wt")) == pytest.approx(1 - float(ws))   # the other box follows
            rows = _mom_dom(page)
            top = rows[0][1]
            k = next((r[2] for r in rows if r[1] != top), None)
            why = page.inner_text("#mom-why")
            assert f"Sector weight {float(ws):g} + stock weight" in why, why
            assert (f"first stock outside {top} appears at rank {k} " in why) if k else (f"Every listed stock is in {top}" in why), why
        page.fill("#mom-wt", "0.3")
        page.wait_for_timeout(100)
        assert page.input_value("#mom-ws") == "0.7"
        assert "Weighted score = 0.7 × sector score + 0.3 × stock score" in page.inner_text("#mom-sub")
        assert errors == [], errors
    finally:
        b.close()
        pw.stop()


def test_momentum_max_per_sector_cap(tmp_path):
    out = _render_fixture(tmp_path)
    pw, b = _browser()
    try:
        page, errors = _open(b, out)
        page.click('nav button[data-tab="momentum"]')
        page.fill("#mom-ws", "1")                            # one sector fills the top
        page.wait_for_timeout(100)
        full = _mom_dom(page)
        page.fill("#mom-cap", "1")
        page.wait_for_timeout(100)
        capped = _mom_dom(page)
        secs = [r[1] for r in capped]
        assert len(secs) == len(set(secs)) == len({r[1] for r in full})        # one stock per sector, every sector
        best = {}
        for r in full:
            best.setdefault(r[1], r)
        assert capped == sorted(best.values(), key=lambda r: r[2])              # each sector's best, ranks unchanged
        assert "max 1 per sector" in page.inner_text("#mom-sub")
        assert page.evaluate("localStorage.getItem('usp_mom_cap')") == "1"
        page.fill("#mom-cap", "2")
        page.wait_for_timeout(100)
        assert all(sum(1 for r in _mom_dom(page) if r[1] == s) <= 2 for s in secs)
        page.fill("#mom-cap", "")
        page.wait_for_timeout(100)
        assert _mom_dom(page) == full
        assert errors == [], errors
    finally:
        b.close()
        pw.stop()


def test_momentum_min_market_cap_filter(tmp_path):
    d = json.loads(FIXTURE.read_text(encoding="utf-8"))
    sectors = {i["label"] for i in d["indices"] if i["group"] == "sector"}
    pool = [s for s in d["stocks"] if s["liq"] is not False and set(s["x"]) & sectors]
    out = _render_fixture(tmp_path, d)
    pw, b = _browser()
    try:
        page, errors = _open(b, out)
        page.click('nav button[data-tab="momentum"]')
        n0 = page.locator("#tb-mom tbody tr").count()
        assert "below market cap" not in page.inner_text("#mom-sub")
        for how, val in (("fill", "2000"), ("click", "10000"), ("click", "300")):
            if how == "fill":
                page.fill("#mom-mcap", val)
            else:
                page.click(f'#mom-mcap-q button[data-mcap="{val}"]')
            page.wait_for_timeout(100)
            assert page.input_value("#mom-mcap") == val
            low = [s["s"] for s in pool if s["mc"] is None or s["mc"] < float(val)]
            assert low and any(s["mc"] is None for s in pool)
            rows = page.evaluate(MOM_BY_SECTOR)
            listed = [x for v in rows.values() for x in v]
            assert all(sym not in low for sym, _, _ in listed), val
            for sec, rs in rows.items():                     # ranks are among the remaining stocks only
                assert sorted(r for _, r, _ in rs) == list(range(1, len(rs) + 1)), (sec, rs)
                assert all(n == len(rs) for _, _, n in rs), (sec, rs)
            assert page.locator("#tb-mom tbody tr").count() == len(listed) < n0
            assert f"{len(low)} below market cap hidden" in page.inner_text("#mom-sub")
            assert page.evaluate("localStorage.getItem('usp_mom_mcap')") == val
        page.click('#mom-mcap-q button[data-mcap=""]')
        page.wait_for_timeout(100)
        assert page.input_value("#mom-mcap") == "" and page.locator("#tb-mom tbody tr").count() == n0
        assert page.evaluate("localStorage.getItem('usp_mom_mcap')") == "null"
        assert errors == [], errors
    finally:
        b.close()
        pw.stop()


def test_etf_min_aum_filter_reranks_the_rest(tmp_path):
    d = json.loads(FIXTURE.read_text(encoding="utf-8"))
    aum = {e["t"]: e["aum"] for e in d["etfs"]}
    assert None in aum.values() and any(v is not None and v < 1 for v in aum.values())
    out = _render_fixture(tmp_path, d)
    pw, b = _browser()
    try:
        page, errors = _open(b, out)
        page.click('nav button[data-tab="etfs"]')
        cells = dict(page.locator("#tb-etf tbody tr").evaluate_all(
            "trs => trs.map(t => [t.dataset.t, t.cells[12].innerText])"))
        assert "AUM" in page.inner_text("#tb-etf thead")
        assert cells["IWM"] == "–" and cells["IEF"] == "$0.4M" and cells["SPY"] == "$630.00B" and cells["XLB"] == "$800M"
        page.click('#etf-aum-q button[data-aum="1000"]')
        page.wait_for_timeout(100)
        keep = [e for e in d["etfs"] if e["aum"] is not None and e["aum"] >= 1000]
        hidden = len(d["etfs"]) - len(keep)
        assert hidden == 3
        rows = page.locator("#tb-etf tbody tr").evaluate_all("trs => trs.map(t => t.dataset.t)")
        exp, bad = _expected_category_order(keep)
        assert rows == exp + bad
        assert f"{hidden} below AUM hidden" in page.inner_text("#etf-note")
        page.select_option("#etf-cat", "US Sector")             # the category filter works with the AUM filter
        page.wait_for_timeout(100)
        sec = [e for e in keep if e["c"] == "US Sector"]
        rows = page.locator("#tb-etf tbody tr").evaluate_all("trs => trs.map(t => [t.dataset.t, t.cells[3].innerText])")
        exp, bad = _expected_category_order(sec)
        assert [r[0] for r in rows] == exp + bad and "XLB" not in [r[0] for r in rows]
        assert [r[1] for r in rows] == [f"{k + 1}/{len(exp)}" for k in range(len(exp))] + ["n/a"] * len(bad)
        page.click('nav button[data-tab="momentum"]')           # the filters survive a tab switch
        page.click('nav button[data-tab="etfs"]')
        assert page.input_value("#etf-cat") == "US Sector" and page.input_value("#etf-aum") == "1000"
        assert page.locator("#tb-etf tbody tr").count() == len(sec)
        page.evaluate("() => { const s = $('#etf-cat'); s.value = 'Size'; s.dispatchEvent(new Event('input', {bubbles: true})); }")
        page.wait_for_timeout(100)
        size = [e["t"] for e in keep if e["c"] == "Size"]
        assert sorted(page.locator("#tb-etf tbody tr").evaluate_all("trs => trs.map(t => t.dataset.t)")) == sorted(size)
        page.fill("#etf-aum", "999999999")
        page.wait_for_timeout(100)
        assert "No ETFs match" in page.inner_text("#tb-etf")
        assert page.evaluate("localStorage.getItem('usp_etf_aum')") == "999999999"
        page.fill("#etf-aum", "")
        page.wait_for_timeout(100)
        assert page.locator("#tb-etf tbody tr").count() == sum(e["c"] == "Size" for e in d["etfs"]) > len(size)
        assert errors == [], errors
    finally:
        b.close()
        pw.stop()


def test_etf_horizon_changes_order_like_hand_calculation(tmp_path):
    d = json.loads(FIXTURE.read_text(encoding="utf-8"))
    out = _render_fixture(tmp_path, d)
    pw, b = _browser()
    try:
        page, errors = _open(b, out)
        page.click('nav button[data-tab="etfs"]')
        assert page.input_value("#etf-h") == "6M"
        orders = set()
        for h in ("1M", "3M", "6M", "1Y"):
            page.select_option("#etf-h", h)
            page.wait_for_timeout(100)
            rows = page.locator("#tb-etf tbody tr").evaluate_all("trs => trs.map(t => t.dataset.t)")
            exp, bad = _expected_category_order(d["etfs"], h)
            assert rows == exp + bad, (h, rows, exp, bad)
            assert page.inner_text("#tb-etf thead th.sel") == h
            orders.add(tuple(rows))
        assert len(orders) > 1
        page.click('nav button[data-tab="sectors"]')            # the sector horizon does not move the ETF table
        page.select_option("#secH", "1M")
        page.click('nav button[data-tab="etfs"]')
        assert page.input_value("#etf-h") == "1Y"
        assert errors == [], errors
    finally:
        b.close()
        pw.stop()


def test_russell_2000_on_overview_index_only(tmp_path):
    d = json.loads(FIXTURE.read_text(encoding="utf-8"))
    rut = next(i for i in d["indices"] if i["label"] == "Russell 2000")
    assert rut["group"] == "benchmark" and rut["nse"] == "^RUT" and "Russell 2000" not in d["members"]
    assert all("Russell" not in g["name"] for g in d["global"])
    out = _render_fixture(tmp_path, d)
    pw, b = _browser()
    try:
        page, errors = _open(b, out)
        bars = page.evaluate("$('#ch-bench').data[0].x")
        assert len(bars) == 6 and "Russell 2000" in bars and "VIX" not in bars
        page.evaluate("$('#ch-bench').emit('plotly_click',{points:[{customdata:'Russell 2000'}]})")
        page.wait_for_timeout(250)
        assert page.is_visible("#drawer.open")
        assert page.inner_text("#dtitle") == "Russell 2000 (^RUT)"
        assert page.locator("#d-tbl").count() == 0 and page.locator("#csv").count() == 0
        assert "Constituent stocks are not tracked for this index" in page.inner_text("#dbody")
        assert page.evaluate("$('#d-idx').data[0].y.length") == len(rut["wk"]["c"])
        page.click('#dbody .pseg button[data-p="1Y"]')         # the drawer's own period still works
        page.wait_for_timeout(150)
        assert page.locator('#dbody .pseg button.on').inner_text() == "1Y"
        page.evaluate("closeDrawer()")
        page.click('nav button[data-tab="breadth"]')
        assert "Russell" not in page.inner_text("#tab-breadth")
        assert errors == [], errors
    finally:
        b.close()
        pw.stop()
