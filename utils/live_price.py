"""
utils/live_price.py — real-time NSE equity prices.

Strategy (fastest to slowest, first success wins):
  1. NSE India official API  (real-time, ~0 delay)
  2. yfinance fast_info      (near real-time, ~15 min delay)
  3. yfinance download 2d    (EOD fallback)

Usage:
    from utils.live_price import get_live_price, get_live_prices_batch
    price = get_live_price("ONGC")          # returns float or None
    prices = get_live_prices_batch(["ONGC", "TCS", "INFY"])  # dict
"""

from __future__ import annotations
import time
from typing import Dict, List, Optional

# ─── NSE session (shared, keeps cookies alive) ────────────────────────────────
_nse_session = None
_nse_session_ts: float = 0.0
_NSE_SESSION_TTL = 300  # refresh session every 5 min


def _get_nse_session():
    """Return a requests.Session primed with NSE cookies."""
    global _nse_session, _nse_session_ts
    if _nse_session is None or (time.time() - _nse_session_ts) > _NSE_SESSION_TTL:
        import requests
        s = requests.Session()
        s.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Referer": "https://www.nseindia.com/",
        })
        try:
            # Hit homepage to get session cookies (required by NSE API)
            s.get("https://www.nseindia.com/", timeout=6)
        except Exception:
            pass
        _nse_session = s
        _nse_session_ts = time.time()
    return _nse_session


def _nse_live_price(symbol: str) -> Optional[float]:
    """
    Fetch live price from NSE India's official quote API.
    Returns lastPrice (real-time during market hours) or None on failure.
    """
    try:
        session = _get_nse_session()
        url = f"https://www.nseindia.com/api/quote-equity?symbol={symbol.upper()}"
        resp = session.get(url, timeout=6)
        if resp.status_code != 200:
            return None
        data = resp.json()
        # lastPrice is under priceInfo
        price_info = data.get("priceInfo", {})
        last = price_info.get("lastPrice") or price_info.get("close")
        return float(last) if last else None
    except Exception:
        return None


def _yfinance_fast_price(symbol: str) -> Optional[float]:
    """yfinance fast_info — usually within ~15 min of live price."""
    try:
        import yfinance as yf
        ticker_sym = symbol if symbol.endswith(".NS") else f"{symbol}.NS"
        t = yf.Ticker(ticker_sym)
        fi = t.fast_info
        import math
        price = fi.get("last_price") or fi.get("regularMarketPrice")
        if price is None:
            return None
        p = float(price)
        return p if (p > 0 and not math.isnan(p)) else None
    except Exception:
        return None


def _yfinance_eod_price(symbol: str) -> Optional[float]:
    """yfinance end-of-day fallback — yesterday's close."""
    try:
        import yfinance as yf
        import pandas as pd
        ticker_sym = symbol if symbol.endswith(".NS") else f"{symbol}.NS"
        df = yf.download(ticker_sym, period="2d", interval="1d",
                         auto_adjust=True, progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df.dropna(subset=["Close"])
        if df.empty:
            return None
        return float(df["Close"].iloc[-1])
    except Exception:
        return None


def get_live_price(symbol: str) -> Optional[float]:
    """
    Get the most current available price for a single NSE symbol.
    Tries NSE API → yfinance fast_info → yfinance EOD.
    """
    clean = symbol.replace(".NS", "").upper()

    # 1. NSE real-time
    price = _nse_live_price(clean)
    if price and price > 0:
        return price

    # 2. yfinance fast_info (~15 min delay)
    price = _yfinance_fast_price(clean)
    if price and price > 0:
        return price

    # 3. yfinance EOD (prior day close)
    return _yfinance_eod_price(clean)


def get_live_prices_batch(symbols: List[str], max_workers: int = 6) -> Dict[str, Optional[float]]:
    """
    Fetch live prices for multiple symbols in parallel.
    Returns dict  { "ONGC": 273.30, "TCS": 3850.0, ... }
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed, wait as _wait

    results: Dict[str, Optional[float]] = {}
    pool = ThreadPoolExecutor(max_workers=max_workers)
    try:
        futs = {pool.submit(get_live_price, sym): sym for sym in symbols}
        done, _ = _wait(list(futs.keys()), timeout=15)
        for fut in done:
            sym = futs[fut]
            try:
                results[sym] = fut.result(timeout=0)
            except Exception:
                results[sym] = None
    finally:
        pool.shutdown(wait=False)

    # fill any that timed out
    for sym in symbols:
        if sym not in results:
            results[sym] = None

    return results
