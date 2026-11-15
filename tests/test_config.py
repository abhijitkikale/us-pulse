import us_config as c


def test_eleven_sectors_unique_tickers():
    assert len(c.SECTOR_ETFS) == 11
    assert len(set(c.SECTOR_ETFS.values())) == 11


def test_sector_names_match_yahoo_map_targets():
    assert set(c.YAHOO_SECTOR_MAP.values()) <= set(c.SECTOR_ETFS)
    assert set(c.YAHOO_SECTOR_MAP.values()) == set(c.SECTOR_ETFS)


def test_themes_count_is_15_and_do_not_overlap_sector_etfs():
    assert len(c.THEMES) == 15
    assert len(set(c.THEMES.values())) == 15
    assert not set(c.THEMES.values()) & set(c.SECTOR_ETFS.values())


def test_benchmarks_have_seven_entries_incl_russell_index():
    assert len(c.BENCHMARKS) == 7
    assert c.BENCHMARKS["S&P 400"] == "^SP400"
    assert c.BENCHMARKS[c.RUSSELL] == "^RUT" and c.RUSSELL == "Russell 2000"


def test_global_has_no_russell_or_india_and_fx_shape():
    assert not any("Russell" in k or "India" in k for k in c.GLOBAL)
    assert all(sym != "^RUT" for sym, _ in c.GLOBAL.values())
    for sym, fx in c.GLOBAL.values():
        assert fx is None or fx[1] in ("per_usd", "usd_per")


def test_paths_and_constants():
    assert c.DATA == c.ROOT / "data"
    assert (c.ROOT / "pipeline").is_dir()
    assert c.PERIODS == ["1D", "1W", "1M", "3M", "6M", "1Y", "3Y", "5Y"]
    assert (c.MIN_PRICE, c.MIN_DOLLAR_VOL, c.SPIKE_X, c.AVG_DAYS, c.MIN_AVG_DAYS) == (5.0, 5_000_000, 2.0, 20, 10)
