"""
data/fetcher.py
Fetches OHLCV data for NSE/BSE stocks using yfinance.
Appends .NS (NSE) or .BO (BSE) suffixes automatically.

Includes:
  - In-memory cache so each (ticker, period, interval) is only fetched once
    per process — avoids duplicate network calls during sector rotation.
  - Rate limiting (0.25 s between calls) to avoid Yahoo Finance DNS blocks.
"""

import time
import yfinance as yf
import pandas as pd
from typing import List, Optional

# ── In-process cache  {(ticker, period, interval): DataFrame} ────────────────
_FETCH_CACHE: dict = {}
_LAST_FETCH:  float = 0.0
_MIN_GAP:     float = 0.25   # seconds between yfinance calls


def _rate_limit():
    """Sleep if the last yfinance call was too recent."""
    global _LAST_FETCH
    gap = time.time() - _LAST_FETCH
    if gap < _MIN_GAP:
        time.sleep(_MIN_GAP - gap)
    _LAST_FETCH = time.time()

# ── NIFTY 50 constituents (updated 2026) ────────────────────────────────────
# Nifty 50 as of 2026 using Yahoo Finance working symbols:
#   TATAMOTORS → TMPV.NS  (Tata Motors PV, post-demerger Yahoo symbol)
#   ZOMATO     → ETERNAL.NS  (Zomato renamed to Eternal Ltd 2025)
#   UPL / LTIM removed; SHRIRAMFIN added
NIFTY50_TICKERS = [
    "RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "ICICIBANK.NS", "BHARTIARTL.NS",
    "INFY.NS", "SBIN.NS", "HINDUNILVR.NS", "ITC.NS", "LT.NS",
    "BAJFINANCE.NS", "HCLTECH.NS", "MARUTI.NS", "SUNPHARMA.NS", "ADANIENT.NS",
    "KOTAKBANK.NS", "TITAN.NS", "ONGC.NS", "NTPC.NS", "AXISBANK.NS",
    "WIPRO.NS", "ULTRACEMCO.NS", "ASIANPAINT.NS", "BAJAJFINSV.NS", "POWERGRID.NS",
    "M&M.NS", "NESTLEIND.NS", "JSWSTEEL.NS", "TMPV.NS", "TATASTEEL.NS",
    "TECHM.NS", "GRASIM.NS", "BPCL.NS", "ADANIPORTS.NS", "CIPLA.NS",
    "BRITANNIA.NS", "EICHERMOT.NS", "DRREDDY.NS", "HINDALCO.NS", "COALINDIA.NS",
    "DIVISLAB.NS", "TATACONSUM.NS", "SBILIFE.NS", "APOLLOHOSP.NS", "HDFCLIFE.NS",
    "INDUSINDBK.NS", "HEROMOTOCO.NS", "BAJAJ-AUTO.NS", "ETERNAL.NS", "SHRIRAMFIN.NS",
]

# Display name overrides for renamed / split tickers
TICKER_DISPLAY_NAMES = {
    "TMPV.NS":    "Tata Motors (PV)",
    "ETERNAL.NS": "Eternal Ltd (Zomato)",
}

# ── BANKNIFTY constituents ───────────────────────────────────────────────────
BANKNIFTY_TICKERS = [
    "HDFCBANK.NS", "ICICIBANK.NS", "SBIN.NS", "KOTAKBANK.NS", "AXISBANK.NS",
    "INDUSINDBK.NS", "BANDHANBNK.NS", "IDFCFIRSTB.NS", "AUBANK.NS", "FEDERALBNK.NS",
    "PNB.NS", "BANKBARODA.NS",
]


def fetch_data(
    tickers: List[str],
    period: str = "2y",
    interval: str = "1d",
    auto_adjust: bool = True,
    dropna: bool = True,
) -> pd.DataFrame:
    """
    Download historical OHLCV data for given tickers.

    Args:
        tickers:     List of ticker symbols (e.g. ['RELIANCE.NS', 'TCS.NS'])
        period:      yfinance period string: '1mo','3mo','6mo','1y','2y','5y','10y','max'
        interval:    '1d','1wk','1mo'  (intraday needs Kite/Upstox API)
        auto_adjust: Adjust for splits/dividends
        dropna:      Drop rows with any NaN values

    Returns:
        MultiIndex DataFrame with (OHLCV) x Ticker columns.
        Single ticker → flat DataFrame with Open, High, Low, Close, Volume columns.
    """
    print(f"  Fetching {len(tickers)} ticker(s) | period={period} | interval={interval}")
    data = yf.download(
        tickers=tickers,
        period=period,
        interval=interval,
        auto_adjust=auto_adjust,
        progress=False,
        threads=True,
    )

    if data.empty:
        raise ValueError(f"No data returned for tickers: {tickers}")

    if dropna:
        data.dropna(how="all", inplace=True)

    print(f"  OK Fetched {len(data)} rows from {data.index[0].date()} to {data.index[-1].date()}")
    return data


def fetch_single(ticker: str, period: str = "2y", interval: str = "1d") -> pd.DataFrame:
    """Fetch data for a single ticker and return a flat OHLCV DataFrame.

    Results are cached in-process — repeated calls for the same
    (ticker, period, interval) return the cached copy instantly.
    """
    cache_key = (ticker, period, interval)
    if cache_key in _FETCH_CACHE:
        return _FETCH_CACHE[cache_key].copy()

    _rate_limit()
    df = yf.download(ticker, period=period, interval=interval,
                     auto_adjust=True, progress=False)
    if df.empty:
        raise ValueError(f"No data for {ticker}")
    # yfinance >=0.2.31 returns MultiIndex columns (Price, Ticker) even for single tickers
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df.dropna(inplace=True)
    _FETCH_CACHE[cache_key] = df
    print(f"  OK {ticker}: {len(df)} rows ({df.index[0].date()} to {df.index[-1].date()})")
    return df.copy()


def fetch_index(index: str = "^NSEI", period: str = "2y") -> pd.DataFrame:
    """
    Fetch index data.
    Common Indian indices:
        ^NSEI   = NIFTY 50
        ^BSESN  = SENSEX
        ^NSEBANK = BANKNIFTY
    """
    return fetch_single(index, period=period)


def get_sector_tickers(sector: str) -> List[str]:
    """Return a predefined list of NSE tickers for a given sector."""
    sectors = {
        "it":      ["TCS.NS", "INFY.NS", "WIPRO.NS", "HCLTECH.NS", "TECHM.NS", "LTIM.NS"],
        "banking": BANKNIFTY_TICKERS,
        "pharma":  ["SUNPHARMA.NS", "DRREDDY.NS", "CIPLA.NS", "DIVISLAB.NS", "APOLLOHOSP.NS"],
        "auto":    ["MARUTI.NS", "TATAMOTORS.NS", "M&M.NS", "BAJAJ-AUTO.NS", "EICHERMOT.NS", "HEROMOTOCO.NS"],
        "fmcg":    ["HINDUNILVR.NS", "ITC.NS", "NESTLEIND.NS", "BRITANNIA.NS", "TATACONSUM.NS"],
        "energy":  ["RELIANCE.NS", "ONGC.NS", "BPCL.NS", "NTPC.NS", "POWERGRID.NS"],
        "metal":   ["TATASTEEL.NS", "JSWSTEEL.NS", "HINDALCO.NS"],
    }
    key = sector.lower()
    if key not in sectors:
        raise ValueError(f"Unknown sector '{sector}'. Available: {list(sectors.keys())}")
    return sectors[key]
