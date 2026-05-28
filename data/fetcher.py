"""
data/fetcher.py
Fetches OHLCV data for NSE/BSE stocks.

Primary source  : Stooq  (stooq.com) — free, no API key, no rate limits,
                  works from any cloud IP including Streamlit Community Cloud.
Fallback source : yfinance — used only if Stooq returns no data (e.g. for
                  index tickers like ^NSEI or very small-cap stocks).

In-memory cache: each (ticker, period) is fetched only once per process.
"""

import io
import time
import datetime
import urllib.request
import pandas as pd
from typing import List, Optional

# ── In-process cache  {(ticker, period, interval): DataFrame} ────────────────
_FETCH_CACHE: dict = {}

# ── Period → calendar days mapping ───────────────────────────────────────────
_PERIOD_DAYS = {
    # UI-style labels (1D / 5D / 1M / 6M / YTD / Max)
    "1d":  10,  "5d":  18,  "1m":  35,  "6m": 185,
    # yfinance-style labels (legacy internal use)
    "1mo": 35,  "2mo": 65,  "3mo": 95,  "6mo": 185,
    "1y":  370, "2y":  740, "3y": 1100, "5y": 1830,
    "max": 1830,
}

# ── UI label → internal period key used for fetching ─────────────────────────
UI_PERIOD_MAP = {
    "1D":  "1d",
    "5D":  "5d",
    "1M":  "1m",
    "6M":  "6m",
    "YTD": "ytd",
    "Max": "max",
}


def _period_to_dates(period: str):
    """Convert period string to (start_str, end_str) for Stooq.
    Handles UI labels (1d/5d/1m/6m/ytd/max) and legacy yfinance strings.
    """
    end = datetime.date.today()
    if period.lower() == "ytd":
        start = datetime.date(end.year, 1, 1)
    elif period.lower() == "max":
        start = end - datetime.timedelta(days=1830)
    else:
        days  = _PERIOD_DAYS.get(period.lower(), _PERIOD_DAYS.get(period, 370))
        start = end - datetime.timedelta(days=days)
    return start.strftime("%Y%m%d"), end.strftime("%Y%m%d")


def _fetch_stooq(ticker: str, period: str = "1y") -> pd.DataFrame:
    """
    Fetch daily OHLCV from Stooq — zero rate limits, works from cloud IPs.
    Ticker format: 'RELIANCE.NS' → stooq uses 'reliance.ns' (lowercase).
    Returns flat DataFrame with Open, High, Low, Close, Volume index=Date.
    """
    sym = ticker.lower()
    # Stooq uses ^nsei for Nifty 50 index — map common index names
    _INDEX_MAP = {"^nsei": "^nsei", "^bsesn": "^bsesn", "^nsebank": "^nsebank"}
    if sym in _INDEX_MAP:
        sym = _INDEX_MAP[sym]

    d1, d2 = _period_to_dates(period)
    url = f"https://stooq.com/q/d/l/?s={sym}&d1={d1}&d2={d2}&i=d"

    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=12) as r:
        raw = r.read().decode("utf-8", errors="replace")

    if not raw.strip() or "No data" in raw or len(raw) < 60:
        raise ValueError(f"Stooq returned no data for {ticker}")

    # Stooq sometimes returns an HTML page instead of CSV (maintenance / geo-block)
    if raw.lstrip().startswith("<") or "<!DOCTYPE" in raw[:200] or "<html" in raw[:200].lower():
        raise ValueError(f"Stooq returned HTML (not CSV) for {ticker}")

    df = pd.read_csv(io.StringIO(raw))
    df.columns = [c.strip().title() for c in df.columns]
    if "Date" not in df.columns:
        raise ValueError(f"Stooq unexpected format for {ticker}: {df.columns.tolist()}")

    df["Date"] = pd.to_datetime(df["Date"])
    df.set_index("Date", inplace=True)
    df.sort_index(inplace=True)
    df = df[["Open", "High", "Low", "Close", "Volume"]].dropna()
    df = df[df["Close"] > 0]
    return df


def _fetch_yfinance(ticker: str, period: str = "1y", interval: str = "1d") -> pd.DataFrame:
    """
    Fallback: yfinance download with a hard 20-second timeout via ThreadPoolExecutor.
    Returns flat DataFrame with Open, High, Low, Close, Volume.
    """
    import yfinance as yf
    from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout

    def _dl():
        df = yf.download(ticker, period=period, interval=interval,
                         auto_adjust=True, progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        return df

    with ThreadPoolExecutor(max_workers=1) as pool:
        fut = pool.submit(_dl)
        try:
            df = fut.result(timeout=20)
        except FuturesTimeout:
            raise ValueError(f"yfinance timed out for {ticker}")

    if df is None or df.empty:
        raise ValueError(f"yfinance returned no data for {ticker}")
    df.dropna(inplace=True)
    return df


def _rate_limit():
    """No-op — kept for backward compatibility with any callers."""
    pass

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
    Download OHLCV for multiple tickers (backtesting / batch use).
    Uses yfinance batch download which is more efficient for many tickers at once.
    For single-ticker analysis prefer fetch_single() which uses Stooq first.
    """
    import yfinance as yf
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

    print(f"  OK Fetched {len(data)} rows")
    return data


def fetch_single(ticker: str, period: str = "2y", interval: str = "1d") -> pd.DataFrame:
    """
    Fetch OHLCV for one ticker.  Stooq first → yfinance fallback.
    Results are cached in-process — repeated calls return the cached copy.

    Why Stooq first:
      - No rate limits, no API key, works from Streamlit Cloud US IPs
      - yfinance gets HTTP 429 (rate-limited) from datacenter IPs frequently
    """
    cache_key = (ticker, period, interval)
    if cache_key in _FETCH_CACHE:
        return _FETCH_CACHE[cache_key].copy()

    df = None
    last_err = ""

    # ── 1. Try Stooq (daily only) ─────────────────────────────────────────────
    if interval == "1d":
        try:
            df = _fetch_stooq(ticker, period=period)
            print(f"  [Stooq] {ticker}: {len(df)} rows")
        except Exception as e:
            last_err = str(e)
            print(f"  [Stooq] {ticker} failed: {e} — trying yfinance…")

    # ── 2. Fallback: yfinance (with 20 s timeout) ─────────────────────────────
    if df is None or df.empty:
        try:
            df = _fetch_yfinance(ticker, period=period, interval=interval)
            print(f"  [yfinance] {ticker}: {len(df)} rows")
        except Exception as e:
            last_err = str(e)

    if df is None or df.empty:
        raise ValueError(f"No data for {ticker}. Stooq + yfinance both failed: {last_err}")

    _FETCH_CACHE[cache_key] = df
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
