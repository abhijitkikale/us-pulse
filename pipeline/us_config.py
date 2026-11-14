"""Static configuration: benchmarks, sector ETFs, themes and global peers the dashboard tracks."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

PERIODS = ["1D", "1W", "1M", "3M", "6M", "1Y", "3Y", "5Y"]

# label -> Yahoo symbol
BENCHMARKS = {
    "S&P 500": "^GSPC",
    "Nasdaq 100": "^NDX",
    "Dow Jones": "^DJI",
    "S&P 400": "^SP400",
    "S&P 600": "^SP600",
    "VIX": "^VIX",
}

# label -> Select Sector SPDR ticker
SECTOR_ETFS = {
    "Technology": "XLK",
    "Financials": "XLF",
    "Health Care": "XLV",
    "Energy": "XLE",
    "Consumer Discretionary": "XLY",
    "Consumer Staples": "XLP",
    "Industrials": "XLI",
    "Materials": "XLB",
    "Utilities": "XLU",
    "Real Estate": "XLRE",
    "Communication Services": "XLC",
}

# label -> thematic ETF ticker
THEMES = {
    "Semiconductors": "SMH",
    "Defence": "ITA",
    "Regional Banks": "KRE",
    "Biotech": "XBI",
    "Software": "IGV",
    "Homebuilders": "XHB",
    "Retail": "XRT",
    "Transportation": "IYT",
    "Oil & Gas E&P": "XOP",
    "Gold Miners": "GDX",
    "Clean Energy": "ICLN",
    "Cybersecurity": "CIBR",
    "Uranium": "URA",
    "Internet": "FDN",
    "Aerospace & Defense": "XAR",
}

# label -> (yahoo symbol, (fx symbol to convert local->USD, 'per_usd' = local per USD | 'usd_per') or None)
# Copied from the India dashboard minus Russell 2000 (excluded) and Indian rows; S&P 400/600 live in BENCHMARKS.
GLOBAL = {
    "S&P 500 (USA)": ("^GSPC", None),
    "Dow Jones (USA)": ("^DJI", None),
    "NASDAQ (USA)": ("^IXIC", None),
    "S&P/TSX Composite (Canada)": ("^GSPTSE", ("CAD=X", "per_usd")),
    "Bovespa (Brazil)": ("^BVSP", ("BRL=X", "per_usd")),
    "FTSE 100 (UK)": ("^FTSE", ("GBPUSD=X", "usd_per")),
    "DAX (Germany)": ("^GDAXI", ("EURUSD=X", "usd_per")),
    "EURO STOXX 50 (Europe)": ("^STOXX50E", ("EURUSD=X", "usd_per")),
    "CAC 40 (France)": ("^FCHI", ("EURUSD=X", "usd_per")),
    "Nikkei 225 (Japan)": ("^N225", ("JPY=X", "per_usd")),
    "Hang Seng (China)": ("^HSI", ("HKD=X", "per_usd")),
    "ASX 200 (Australia)": ("^AXJO", ("AUDUSD=X", "usd_per")),
    "KOSPI (S.Korea)": ("^KS11", ("KRW=X", "per_usd")),
}

# Yahoo sector name -> SECTOR_ETFS label
YAHOO_SECTOR_MAP = {
    "Technology": "Technology",
    "Financial Services": "Financials",
    "Healthcare": "Health Care",
    "Energy": "Energy",
    "Consumer Cyclical": "Consumer Discretionary",
    "Consumer Defensive": "Consumer Staples",
    "Industrials": "Industrials",
    "Basic Materials": "Materials",
    "Utilities": "Utilities",
    "Real Estate": "Real Estate",
    "Communication Services": "Communication Services",
}

# Momentum liquidity floor and volume-spike settings
MIN_PRICE = 5.0
MIN_DOLLAR_VOL = 5_000_000
SPIKE_X = 2.0
AVG_DAYS = 20
MIN_AVG_DAYS = 10
