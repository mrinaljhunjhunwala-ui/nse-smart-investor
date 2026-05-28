"""
utils/live_price.py — Real-time NSE equity prices.

Tier hierarchy (fastest → most reliable fallback):
  1. Yahoo Finance JSON API  — direct HTTP, no library, works from cloud IPs,
                               returns live price during market hours
  2. NSE India official API  — real-time but needs cookie, may fail on cloud
  3. Stooq EOD              — yesterday's close, never fails

Why not yfinance?
  yfinance.download() is rate-limited from Streamlit Cloud / datacenter IPs.
  The direct Yahoo JSON endpoint (query1.finance.yahoo.com) is a lighter path
  that avoids the rate-limiting applied to the Python library's batch calls.
"""

from __future__ import annotations

import json
import math
import time
import urllib.request
from typing import Dict, List, Optional


# ─── Yahoo Finance direct quote API ─────────────────────────────────────────

def _yahoo_json_quote(ticker_ns: str) -> Optional[dict]:
    """
    Fetch live quote from Yahoo Finance JSON endpoint.
    Works from cloud IPs (Streamlit Community Cloud, Heroku, etc.)
    Returns dict with 'price', 'prev_close', or None on failure.
    """
    try:
        url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker_ns}"
               "?interval=1m&range=1d&includePrePost=false")
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                "Accept": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=8) as r:
            data = json.loads(r.read())

        meta = data["chart"]["result"][0]["meta"]
        price      = meta.get("regularMarketPrice")
        prev_close = meta.get("previousClose") or meta.get("chartPreviousClose")

        if price and float(price) > 0 and not math.isnan(float(price)):
            return {
                "price":      float(price),
                "prev_close": float(prev_close) if prev_close else float(price),
            }
    except Exception:
        pass
    return None


# ─── NSE India session (cookie-based, real-time) ────────────────────────────

_nse_session = None
_nse_session_ts: float = 0.0
_NSE_SESSION_TTL = 300


def _get_nse_session():
    global _nse_session, _nse_session_ts
    if _nse_session is None or (time.time() - _nse_session_ts) > _NSE_SESSION_TTL:
        import requests
        s = requests.Session()
        s.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36"
            ),
            "Referer": "https://www.nseindia.com/",
        })
        try:
            s.get("https://www.nseindia.com/", timeout=6)
        except Exception:
            pass
        _nse_session = s
        _nse_session_ts = time.time()
    return _nse_session


def _nse_live_price(symbol: str) -> Optional[dict]:
    """NSE India official API — real-time, needs fresh session cookies."""
    try:
        session = _get_nse_session()
        url = f"https://www.nseindia.com/api/quote-equity?symbol={symbol.upper()}"
        resp = session.get(url, timeout=6)
        if resp.status_code != 200:
            return None
        data = resp.json()
        pi = data.get("priceInfo", {})
        price = pi.get("lastPrice") or pi.get("close")
        prev  = pi.get("previousClose") or pi.get("close")
        if price:
            return {"price": float(price), "prev_close": float(prev or price)}
    except Exception:
        pass
    return None


# ─── Stooq EOD fallback ──────────────────────────────────────────────────────

def _stooq_eod_price(ticker_ns: str) -> Optional[dict]:
    """Last EOD close from Stooq — never rate-limited, works everywhere."""
    try:
        import io, datetime, pandas as pd
        sym = ticker_ns.lower()
        end   = datetime.date.today()
        start = end - datetime.timedelta(days=7)
        url = (f"https://stooq.com/q/d/l/?s={sym}"
               f"&d1={start.strftime('%Y%m%d')}&d2={end.strftime('%Y%m%d')}&i=d")
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as r:
            raw = r.read().decode()
        if len(raw) < 60 or "No data" in raw:
            return None
        df = pd.read_csv(io.StringIO(raw))
        df.columns = [c.strip().title() for c in df.columns]
        df = df.dropna(subset=["Close"])
        if df.empty:
            return None
        df = df.sort_values("Date")
        price = float(df["Close"].iloc[-1])
        prev  = float(df["Close"].iloc[-2]) if len(df) > 1 else price
        return {"price": price, "prev_close": prev}
    except Exception:
        return None


# ─── Public interface ────────────────────────────────────────────────────────

def get_live_price(symbol: str) -> Optional[float]:
    """
    Get current price for a single NSE symbol.
    Returns float or None.
    """
    clean_ns = (symbol if symbol.endswith(".NS") else f"{symbol}.NS")
    clean    = symbol.replace(".NS", "").upper()

    # Tier 1: Yahoo direct JSON (live during market hours, works from cloud)
    q = _yahoo_json_quote(clean_ns)
    if q:
        return q["price"]

    # Tier 2: NSE India API (real-time, may fail on cloud due to Cloudflare)
    q = _nse_live_price(clean)
    if q:
        return q["price"]

    # Tier 3: Stooq EOD (yesterday's close — always works)
    q = _stooq_eod_price(clean_ns)
    return q["price"] if q else None


def get_live_quote(symbol: str) -> Optional[dict]:
    """
    Get price + prev_close dict for one NSE symbol.
    Returns {"price": float, "prev_close": float, "chg_pct": float} or None.
    """
    clean_ns = (symbol if symbol.endswith(".NS") else f"{symbol}.NS")
    clean    = symbol.replace(".NS", "").upper()

    for fetch_fn, arg in [
        (_yahoo_json_quote, clean_ns),
        (_nse_live_price,   clean),
        (_stooq_eod_price,  clean_ns),
    ]:
        q = fetch_fn(arg)
        if q:
            p  = q["price"]
            pc = q["prev_close"]
            return {
                "price":      p,
                "prev_close": pc,
                "chg_pct":    (p / pc - 1) * 100 if pc > 0 else 0.0,
            }
    return None


def get_live_prices_batch(symbols: List[str], max_workers: int = 8) -> Dict[str, Optional[dict]]:
    """
    Fetch live quotes for multiple symbols in parallel.
    Returns {symbol: {"price", "prev_close", "chg_pct"} or None}
    """
    from concurrent.futures import ThreadPoolExecutor, wait as _wait

    results: Dict[str, Optional[dict]] = {}
    pool = ThreadPoolExecutor(max_workers=max_workers)
    try:
        futs = {pool.submit(get_live_quote, sym): sym for sym in symbols}
        done, _ = _wait(list(futs.keys()), timeout=20)
        for fut in done:
            sym = futs[fut]
            try:
                val = fut.result(timeout=0)
                # Ensure we only store proper dicts — never raw exceptions or other types
                results[sym] = val if isinstance(val, dict) else None
            except Exception:
                results[sym] = None
    finally:
        pool.shutdown(wait=False)

    for sym in symbols:
        if sym not in results:
            results[sym] = None
    return results
