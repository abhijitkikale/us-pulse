import json
import re

import numpy as np
import pandas as pd
import pytest

import build
import run

MINI = "<!doctype html><title>US Pulse</title><script>/*__PLOTLY__*/</script><script>const D = /*__DATA__*/null;</script>"


@pytest.fixture
def tpl(tmp_path):
    p = tmp_path / "template.html"
    p.write_text(MINI, encoding="utf-8")
    return p


def _embedded(html):
    m = re.search(r"const D = (.*?);</script>", html, re.S)
    return json.loads(m.group(1))


def test_render_valid_json_with_nan_replaced(tmp_path, tpl):
    out = build.render({"a": float("nan"), "b": [np.float64("inf"), 1.5]}, tmp_path / "o.html",
                       template_path=tpl, plotly_js="var P=1;")
    html = out.read_text(encoding="utf-8")
    assert "NaN" not in html and "Infinity" not in html
    assert _embedded(html) == {"a": None, "b": [None, 1.5]}
    assert "var P=1;" in html


def test_render_escapes_script_close_and_angle_brackets(tmp_path, tpl):
    name = "A</script><b>&\"'  <!--"
    out = build.render({"stocks": [{"n": name}]}, tmp_path / "o.html", template_path=tpl,
                       plotly_js="x='</script>';")
    html = out.read_text(encoding="utf-8")
    assert "A</script>" not in html and "<b>" not in html and "<!--" not in html
    assert " " not in html and " " not in html
    assert html.count("</script>") == 2                      # only the template's own two closing tags
    assert _embedded(html)["stocks"][0]["n"] == name


def test_render_requires_markers(tmp_path):
    bad = tmp_path / "t.html"
    bad.write_text("<html></html>", encoding="utf-8")
    with pytest.raises(ValueError):
        build.render({}, tmp_path / "o.html", template_path=bad, plotly_js="")
    assert not (tmp_path / "o.html").exists()


def test_render_inlines_installed_plotly_by_default(tmp_path, tpl):
    html = build.render({}, tmp_path / "o.html", template_path=tpl).read_text(encoding="utf-8")
    assert len(html) > 1_000_000 and "plotly" in html.lower()


# ---------- run.main, offline ----------

END = pd.Timestamp("2026-11-13")


def _fake_world(monkeypatch, tmp_path, tpl, n=30, price_status="ok", today="2026-11-16", weekend_fx=False):
    tickers = [f"T{i:02d}" for i in range(n)]
    uni = pd.DataFrame({"ticker": tickers, "name": [f"Co {t}" for t in tickers], "universe": "SP500",
                        "sector": "Technology"})
    idx = pd.bdate_range(end=END, periods=300)
    rng = np.random.default_rng(0)
    cols = tickers + ["^GSPC", "XLK", "SPY"]
    close = pd.DataFrame(100 * np.exp(np.cumsum(rng.normal(0, 0.01, (300, len(cols))), axis=0)),
                         index=idx, columns=cols)
    volume = pd.DataFrame(1e6, index=idx, columns=cols)
    if weekend_fx:                       # Yahoo returns a Saturday row for some FX pairs (seen live for CAD=X)
        close["CAD=X"] = 1.4
        close.loc[END + pd.Timedelta(days=1)] = np.nan
        close.loc[END + pd.Timedelta(days=1), "CAD=X"] = 1.41
        volume = volume.reindex(close.index)
    seen = {}

    def fake_refresh(symbols, cache_path, **kw):
        seen["symbols"] = list(symbols)
        return close, volume, price_status

    labels = pd.DataFrame(columns=["ticker", "sector", "industry", "mcap", "asof"])
    monkeypatch.setattr(run.fetch_membership, "fetch_membership", lambda: (uni, "ok (30 names)"))
    monkeypatch.setattr(run.fetch_prices, "refresh", fake_refresh)
    monkeypatch.setattr(run.fetch_sectors, "load_sectors", lambda t, c, **kw: (labels, "sectors: fetched 0"))
    monkeypatch.setattr(run.fetch_sectors, "fill_all", lambda t, c, **kw: (labels, "sectors: fetched 0"))
    monkeypatch.setattr(run, "DATA", tmp_path)
    monkeypatch.setattr(run, "OUT", tmp_path / "dashboard.html")
    monkeypatch.setattr(run, "TEMPLATE", tpl)
    monkeypatch.setattr(run, "PLOTLY_JS", "")
    monkeypatch.setattr(run, "_today", lambda: pd.Timestamp(today))
    return seen


def test_run_refuses_collapsed_universe(monkeypatch, tmp_path, tpl):
    _fake_world(monkeypatch, tmp_path, tpl, n=30)
    (tmp_path / "last_count.txt").write_text("100", encoding="utf-8")
    with pytest.raises(SystemExit) as e:
        run.main()
    assert e.value.code not in (0, None)
    assert "30" in str(e.value.code) and "100" in str(e.value.code)
    assert not (tmp_path / "dashboard.html").exists()
    assert (tmp_path / "last_count.txt").read_text(encoding="utf-8") == "100"


def test_run_exits_1_after_writing_page_when_a_fetch_is_stale(monkeypatch, tmp_path, tpl):
    _fake_world(monkeypatch, tmp_path, tpl, price_status="stale: download returned 3 of 40 cached symbols")
    with pytest.raises(SystemExit) as e:
        run.main()
    assert e.value.code == 1
    html = (tmp_path / "dashboard.html").read_text(encoding="utf-8")
    assert _embedded(html)["status"]["prices"].startswith("stale:")
    assert (tmp_path / "last_count.txt").read_text(encoding="utf-8") == "30"


def test_run_ok_writes_page_and_count(monkeypatch, tmp_path, tpl):
    seen = _fake_world(monkeypatch, tmp_path, tpl, n=30)
    (tmp_path / "last_count.txt").write_text("40", encoding="utf-8")     # 30 >= 0.6 * 40
    run.main()                                                            # no SystemExit
    d = _embedded((tmp_path / "dashboard.html").read_text(encoding="utf-8"))
    assert len(d["stocks"]) == 30 and d["stale"] is False
    assert d["universe_note"] == "current constituents; 30 stocks"
    assert set(d["status"]) >= {"membership", "prices", "sectors"}
    assert (tmp_path / "last_count.txt").read_text(encoding="utf-8") == "30"
    syms = set(seen["symbols"])
    assert {"T00", "^GSPC", "^VIX", "XLK", "SMH", "^FTSE", "GBPUSD=X", "JPY=X", "SPY"} <= syms
    assert len(seen["symbols"]) == len(syms)                              # de-duplicated


def test_run_ignores_non_trading_day_rows_for_us_data(monkeypatch, tmp_path, tpl):
    _fake_world(monkeypatch, tmp_path, tpl, weekend_fx=True)
    run.main()
    d = _embedded((tmp_path / "dashboard.html").read_text(encoding="utf-8"))
    assert d["asof"] == "13 Nov 2026" and d["stock_asof"] == "13 Nov 2026"
    assert d["dates"][-1] == "2026-11-13"
    assert d["activity"]["asof"] == "2026-11-13" and d["activity"]["n_stocks"] == 30
    assert d["stocks"][0]["ser"][-1] is not None


def test_run_exits_1_when_prices_are_behind_the_calendar(monkeypatch, tmp_path, tpl):
    _fake_world(monkeypatch, tmp_path, tpl, today="2026-11-18")           # Mon 16 + Tue 17 missing
    with pytest.raises(SystemExit) as e:
        run.main()
    assert e.value.code == 1
    d = _embedded((tmp_path / "dashboard.html").read_text(encoding="utf-8"))
    assert d["stale"] is True and d["status"]["freshness"].startswith("stale:")


# ---------- membership: partial fetches never publish silently ----------

def _members(tickers, universe, sector=None):
    return pd.DataFrame({"ticker": tickers, "name": [f"Co {t}" for t in tickers], "universe": universe,
                         "sector": sector})


def test_partial_membership_fills_missing_universe_from_last_good(monkeypatch, tmp_path, tpl):
    _fake_world(monkeypatch, tmp_path, tpl, n=30)
    fresh = pd.concat([_members([f"T{i:02d}" for i in range(15)], "SP500", "Technology"),
                       _members([f"T{i:02d}" for i in range(15, 20)], "SP400")], ignore_index=True)
    cached = pd.concat([fresh, _members([f"T{i:02d}" for i in range(20, 30)], "SP600")], ignore_index=True)
    cache = tmp_path / "membership.csv"
    cached.to_csv(cache, index=False)
    before = cache.read_bytes()
    monkeypatch.setattr(run.fetch_membership, "fetch_membership",
                        lambda: (fresh, "partial: failed SPSM (HTTPError)"))
    with pytest.raises(SystemExit) as e:
        run.main()
    assert e.value.code == 1
    d = _embedded((tmp_path / "dashboard.html").read_text(encoding="utf-8"))
    st = d["status"]["membership"]
    assert st.startswith("stale: partial membership, using last good list for SP600"), st
    assert len(d["stocks"]) == 30
    assert sorted(d["members"]["S&P 600"]) == [f"T{i:02d}" for i in range(20, 30)]
    assert cache.read_bytes() == before                                   # last-good list not overwritten


def test_partial_membership_without_cached_universe_is_failed(monkeypatch, tmp_path):
    monkeypatch.setattr(run, "DATA", tmp_path)
    fresh = pd.concat([_members(["A", "B"], "SP500", "Energy"), _members(["C"], "SP400")], ignore_index=True)
    _members(["A", "B"], "SP500", "Energy").to_csv(tmp_path / "membership.csv", index=False)   # no SP600 rows
    monkeypatch.setattr(run.fetch_membership, "fetch_membership",
                        lambda: (fresh, "partial: failed SPSM (HTTPError)"))
    uni, status = run._membership(False)
    assert status.startswith("failed: "), status
    assert "SP600" in status
    assert sorted(uni["ticker"]) == ["A", "B", "C"]                       # run continues with what exists


def test_partial_sp500_sector_filled_from_last_good(monkeypatch, tmp_path):
    monkeypatch.setattr(run, "DATA", tmp_path)
    fresh = pd.concat([_members(["A"], "SP500", "Energy"), _members(["C"], "SP400"), _members(["D"], "SP600")],
                      ignore_index=True)
    cached = pd.concat([fresh, _members(["X"], "SP500", "Utilities")], ignore_index=True)
    cached.to_csv(tmp_path / "membership.csv", index=False)
    monkeypatch.setattr(run.fetch_membership, "fetch_membership",
                        lambda: (fresh, "partial: failed XLU (HTTPError)"))
    uni, status = run._membership(False)
    assert status.startswith("stale: partial membership, using last good list for SP500 (Utilities)"), status
    assert sorted(uni["ticker"]) == ["A", "C", "D", "X"]


def test_full_membership_fetch_overwrites_last_good(monkeypatch, tmp_path, tpl):
    _fake_world(monkeypatch, tmp_path, tpl, n=30)
    _members(["OLD"], "SP600").to_csv(tmp_path / "membership.csv", index=False)
    run.main()                                                            # exits 0
    saved = pd.read_csv(tmp_path / "membership.csv", dtype=str)
    assert sorted(saved["ticker"]) == [f"T{i:02d}" for i in range(30)]


def test_bad_statuses_include_partial():
    assert all(s.startswith(run.BAD) for s in ("stale: x", "failed: x", "partial: x"))
    assert not "ok (30 names)".startswith(run.BAD)


def test_run_out_option_writes_to_given_path(monkeypatch, tmp_path, tpl):
    _fake_world(monkeypatch, tmp_path, tpl, n=30)
    target = tmp_path / "elsewhere" / "page.html"
    run.main(out=target)
    assert target.exists()
    assert not (tmp_path / "dashboard.html").exists()
    assert len(_embedded(target.read_text(encoding="utf-8"))["stocks"]) == 30


def test_cli_out_flag_parsing():
    assert run._cli_out(["run.py", "--out", "X/y.html"]) == run.Path("X/y.html")
    assert run._cli_out(["run.py", "--cached"]) is None
