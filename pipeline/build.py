"""Render dashboard.html: inline Plotly + the embedded JSON payload into the template (plain-text title, no image assets)."""
import json
from pathlib import Path

from assemble import sanitize
from us_config import ROOT

TEMPLATE = ROOT / "pipeline" / "template.html"
OUT = ROOT / "dashboard.html"
PLOTLY_MARK = "/*__PLOTLY__*/"
DATA_MARK = "/*__DATA__*/null"


def plotly_source() -> str:
    import plotly
    return (Path(plotly.__file__).parent / "package_data" / "plotly.min.js").read_text(encoding="utf-8")


def to_script_json(payload) -> str:
    """Strict JSON safe inside a <script>: '<' (</script>, <!--), '>' and '&' as \\u escapes, and the JS line separators."""
    return (json.dumps(sanitize(payload), separators=(",", ":"), allow_nan=False)
            .replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
            .replace("\u2028", "\\u2028").replace("\u2029", "\\u2029"))


def render(payload, out=None, template_path=None, plotly_js=None) -> Path:
    out = Path(out or OUT)
    tpl = Path(template_path or TEMPLATE).read_text(encoding="utf-8")
    if PLOTLY_MARK not in tpl or DATA_MARK not in tpl:
        raise ValueError(f"template is missing {PLOTLY_MARK} or {DATA_MARK}")
    js = plotly_source() if plotly_js is None else plotly_js
    data = to_script_json(payload)
    # Plotly first, so a payload string that happens to contain the Plotly marker is never expanded.
    html = tpl.replace(PLOTLY_MARK, js.replace("</script", "<\\/script"), 1).replace(DATA_MARK, data, 1)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.name + ".tmp")
    tmp.write_text(html, encoding="utf-8")
    tmp.replace(out)                                   # never leave a half-written page
    return out
