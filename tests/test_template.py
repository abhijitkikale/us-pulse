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
        page.click('#periods button[data-p="1M"]')
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
    d["etfs"][0]["n"], d["etfs"][0]["c"] = "ETF " + HOSTILE, "Cat " + HOSTILE
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
            for sel in ('#periods button[data-p="1Y"]', '#periods button[data-p="1D"]'):
                page.click(sel)
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
        page.wait_for_timeout(200)
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
        assert page.evaluate("window.__xss") is None
        assert page.locator("img").count() == 0
        assert errors == [], errors
    finally:
        b.close()
        pw.stop()
