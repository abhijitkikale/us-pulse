import numpy as np
import pandas as pd
import pytest

from pipeline import fetch_prices as fp

DATES = pd.bdate_range("2026-01-01", periods=5)


def make_frame(symbols, nan_cols=(), base=100.0):
    """yfinance-style frame; MultiIndex columns for 2+ symbols, plain for one."""
    close = pd.DataFrame({s: base + np.arange(5.0) for s in symbols}, index=DATES)
    vol = pd.DataFrame({s: 1000.0 + np.arange(5.0) for s in symbols}, index=DATES)
    for c in nan_cols:
        close[c] = np.nan
        vol[c] = np.nan
    if len(symbols) == 1:
        out = pd.DataFrame({"Close": close.iloc[:, 0], "Volume": vol.iloc[:, 0]})
        return out
    return pd.concat({"Close": close, "Volume": vol}, axis=1)


class Fake:
    def __init__(self, fn=None):
        self.calls = []
        self.fn = fn or (lambda batch: make_frame(batch))

    def __call__(self, batch, **kw):
        self.calls.append((list(batch), kw))
        return self.fn(batch)


def test_batches_of_100():
    syms = [f"S{i}" for i in range(250)]
    d = Fake()
    close, volume, status = fp.download_prices(syms, downloader=d, sleep=lambda s: None)
    assert [len(c[0]) for c in d.calls] == [100, 100, 50]
    assert d.calls[0][1] == dict(period="5y", interval="1d", auto_adjust=True, progress=False, threads=True)
    assert close.shape[1] == 250 and volume.shape[1] == 250
    assert status == "ok"


def test_retries_then_succeeds():
    n = {"i": 0}

    def fn(batch):
        n["i"] += 1
        if n["i"] < 3:
            raise RuntimeError("boom")
        return make_frame(batch)

    waits = []
    close, volume, status = fp.download_prices(["A", "B"], downloader=Fake(fn), sleep=waits.append)
    assert n["i"] == 3
    assert waits == [2, 4]
    assert list(close.columns) == ["A", "B"]
    assert status == "ok"


def test_gives_up_after_retries():
    def fn(batch):
        raise RuntimeError("down")

    close, volume, status = fp.download_prices(["A", "B"], downloader=Fake(fn), sleep=lambda s: None)
    assert close.empty and volume.empty
    assert status.startswith("failed")


def test_all_nan_columns_dropped():
    d = Fake(lambda b: make_frame(b, nan_cols=["B"]))
    close, volume, status = fp.download_prices(["A", "B", "C"], downloader=d, sleep=lambda s: None)
    assert list(close.columns) == ["A", "C"]
    assert list(volume.columns) == ["A", "C"]
    assert status.startswith("partial")


def test_single_symbol_plain_columns():
    d = Fake()
    close, volume, status = fp.download_prices(["A"], downloader=d, sleep=lambda s: None)
    assert list(close.columns) == ["A"] and list(volume.columns) == ["A"]
    assert close["A"].iloc[-1] == 104.0
    assert status == "ok"


def test_merge_prices_new_wins_and_unions():
    old = pd.DataFrame({"A": [1.0, 2.0], "B": [5.0, 6.0]}, index=pd.to_datetime(["2026-01-01", "2026-01-02"]))
    new = pd.DataFrame({"A": [20.0, 30.0], "C": [7.0, 8.0]}, index=pd.to_datetime(["2026-01-02", "2026-01-05"]))
    m = fp.merge_prices(old, new)
    assert list(m.index) == list(pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-05"]))
    assert set(m.columns) == {"A", "B", "C"}
    assert m.loc["2026-01-02", "A"] == 20.0      # new wins
    assert m.loc["2026-01-01", "A"] == 1.0       # old kept
    assert m.loc["2026-01-02", "B"] == 6.0
    assert fp.merge_prices(None, new).equals(new)


def _cache_of(n, tmp_path):
    syms = [f"S{i}" for i in range(n)]
    f = make_frame(syms)
    path = tmp_path / "px.pkl"
    fp.save_cache(path, f["Close"], f["Volume"])
    return syms, path


def test_refresh_keeps_cache_when_download_collapses(tmp_path):
    syms, path = _cache_of(100, tmp_path)
    before = path.read_bytes()
    d = Fake(lambda b: make_frame(b[:10], base=500.0))
    close, volume, status = fp.refresh(syms, path, downloader=d, sleep=lambda s: None)
    assert close.shape[1] == 100 and volume.shape[1] == 100
    assert status.startswith("stale:")
    assert path.read_bytes() == before            # cache not overwritten
    assert close["S0"].iloc[-1] == 104.0          # old values, not the 500-based ones


def test_refresh_stale_check_ignores_cached_symbols_no_longer_requested(tmp_path):
    syms, path = _cache_of(100, tmp_path)          # cache holds S0..S99; 40 of them since delisted
    wanted = syms[:60]
    d = Fake(lambda b: make_frame(b, base=300.0))
    close, volume, status = fp.refresh(wanted, path, downloader=d, sleep=lambda s: None)
    assert status == "ok"                          # 60 of 60 requested, not 60 of 100 cached
    assert close["S0"].iloc[-1] == 304.0


def test_refresh_stale_check_counts_requested_cached_symbols(tmp_path):
    syms, path = _cache_of(100, tmp_path)
    wanted = syms[:50]
    d = Fake(lambda b: make_frame(b[:30], base=300.0))   # 30 of 50 requested -> under 80%
    close, volume, status = fp.refresh(wanted, path, downloader=d, sleep=lambda s: None)
    assert status.startswith("stale:") and "30 of 50" in status


def test_refresh_keeps_cache_when_download_empty(tmp_path):
    syms, path = _cache_of(20, tmp_path)
    before = path.read_bytes()
    close, volume, status = fp.refresh(syms, path, downloader=Fake(lambda b: pd.DataFrame()),
                                       sleep=lambda s: None)
    assert close.shape[1] == 20 and status.startswith("stale:")
    assert path.read_bytes() == before


def test_refresh_saves_cache_on_success(tmp_path):
    syms, path = _cache_of(10, tmp_path)
    d = Fake(lambda b: make_frame(b, base=200.0))
    close, volume, status = fp.refresh(syms + ["NEW"], path, downloader=d, sleep=lambda s: None)
    assert status == "ok"
    assert close.shape[1] == 11
    c2, v2 = fp.load_cache(path)
    assert c2.shape[1] == 11 and v2.shape[1] == 11
    assert c2["S0"].iloc[-1] == 204.0


def test_refresh_first_run_no_cache(tmp_path):
    path = tmp_path / "sub" / "px.pkl"
    close, volume, status = fp.refresh(["A", "B"], path, downloader=Fake(), sleep=lambda s: None)
    assert status == "ok" and close.shape[1] == 2
    assert path.exists()


def test_refresh_failed_without_cache(tmp_path):
    path = tmp_path / "px.pkl"
    close, volume, status = fp.refresh(["A"], path, downloader=Fake(lambda b: pd.DataFrame()),
                                       sleep=lambda s: None)
    assert close.empty and status.startswith("failed")
    assert not path.exists()


def test_load_cache_missing(tmp_path):
    assert fp.load_cache(tmp_path / "nope.pkl") == (None, None)
