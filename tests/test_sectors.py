import datetime as dt

import pandas as pd

from pipeline import fetch_sectors as fs

TODAY = dt.date(2026, 11, 14)


def _info(sector="Technology", industry="Software", mcap=1e9):
    return {"sector": sector, "industry": industry, "marketCap": mcap}


def _seed(path, rows):
    pd.DataFrame(rows, columns=["ticker", "sector", "industry", "mcap", "asof"]).to_csv(path, index=False)


def test_normalize_sector_maps_yahoo_names():
    assert fs.normalize_sector("Financial Services") == "Financials"
    assert fs.normalize_sector("Healthcare") == "Health Care"
    assert fs.normalize_sector("Nonsense") is None
    assert fs.normalize_sector(None) is None


def test_only_missing_or_stale_fetched(tmp_path):
    csv = tmp_path / "s.csv"
    _seed(csv, [["A", "Technology", "X", 1e9, "2026-11-10"], ["B", "Energy", "Y", 2e9, "2026-01-01"]])
    calls = []

    def fetcher(t):
        calls.append(t)
        return _info()

    df, _ = fs.load_sectors(["A", "B", "C"], csv, fetcher=fetcher, today=TODAY, sleep=lambda s: None)
    assert sorted(calls) == ["B", "C"]
    assert list(df.columns) == ["ticker", "sector", "industry", "mcap", "asof"]
    assert set(df.ticker) == {"A", "B", "C"}
    assert df.set_index("ticker").loc["B", "asof"] == "2026-11-14"
    assert df.set_index("ticker").loc["C", "mcap"] == 1e9


def test_max_new_cap_respected_and_remainder_reported(tmp_path):
    csv = tmp_path / "s.csv"
    calls = []
    df, status = fs.load_sectors(list("ABCDE"), csv, fetcher=lambda t: calls.append(t) or _info(),
                                 max_new=2, today=TODAY, sleep=lambda s: None)
    assert len(calls) == 2 and len(df) == 2
    assert "3 remaining" in status


def test_failed_fetch_keeps_old_row_and_does_not_raise(tmp_path):
    csv = tmp_path / "s.csv"
    _seed(csv, [["B", "Energy", "Y", 2e9, "2026-01-01"]])
    df, status = fs.load_sectors(["B", "C"], csv, fetcher=lambda t: {}, today=TODAY, sleep=lambda s: None)
    assert list(df.ticker) == ["B"]
    assert df.iloc[0]["asof"] == "2026-01-01"
    assert "failed 2" in status
    assert pd.read_csv(csv).ticker.tolist() == ["B"]


def test_status_reports_counts(tmp_path):
    csv = tmp_path / "s.csv"
    _seed(csv, [["A", "Technology", "X", 1e9, "2026-11-10"]])
    _, status = fs.load_sectors(["A", "B"], csv, fetcher=lambda t: _info(), today=TODAY, sleep=lambda s: None)
    assert "fetched 1" in status and "cached 1" in status and "failed 0" in status


def test_fill_all_loops_until_complete(tmp_path):
    csv = tmp_path / "s.csv"
    sleeps = []
    df, status = fs.fill_all(list("ABCDE"), csv, fetcher=lambda t: _info(), batch=2, today=TODAY,
                             sleep=sleeps.append, pause=5)
    assert len(df) == 5
    assert 5 in sleeps  # paused between rounds


def test_fill_all_stops_when_no_progress(tmp_path):
    csv = tmp_path / "s.csv"
    n = []
    df, status = fs.fill_all(["A", "B"], csv, fetcher=lambda t: n.append(t) or {}, batch=2, today=TODAY,
                             sleep=lambda s: None)
    assert len(df) == 0
    assert len(n) == 2  # one round only
