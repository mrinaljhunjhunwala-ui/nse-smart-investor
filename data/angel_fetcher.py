"""
data/angel_fetcher.py
Angel One SmartAPI — Tier 0 data source for NSE/BSE historical + live data.

Why Angel One over Yahoo Finance / Stooq:
  ✓ No rate limiting whatsoever
  ✓ Real-time live quotes (during market hours)
  ✓ 5 years OHLCV history, all intervals
  ✓ Official NSE/BSE exchange data — never stale or missing
  ✓ Works reliably from Streamlit Cloud and all cloud IPs

Authentication flow (one-time per hour):
  1. Login: client_id + password + TOTP → JWT token
  2. All subsequent calls use: Authorization: Bearer <jwt>

Credentials — stored in Streamlit secrets (NEVER in code/git):
  .streamlit/secrets.toml (locally) OR Streamlit Cloud > App Settings > Secrets:
  ─────────────────────────────────────────────────
  [angel_one]
  api_key      = "C58Sb2tl..."          # My Smart API → API Key
  client_id    = "AABM038127"           # Your Angel One login ID
  password     = "yourpassword"         # Angel One login password
  totp_secret  = "BASE32SEEDHERE"       # Base32 seed from authenticator setup
  ─────────────────────────────────────────────────

How to get totp_secret:
  Angel One → Profile → Security Settings → Two-Factor Authentication
  → Re-setup → Copy the text key shown before you scan the QR code.
  It looks like: JBSWY3DPEHPK3PXP  (base32, ~16-32 chars)
"""

from __future__ import annotations

import json
import os
import time
import datetime
import urllib.request
from typing import Dict, List, Optional, Tuple

import pandas as pd

# ── In-process caches ─────────────────────────────────────────────────────────
_SESSION:      Dict = {"jwt": None, "feed_token": None, "api_key": "", "ts": 0.0}
_TOKEN_CACHE:  Dict[str, Optional[str]] = {}   # "RELIANCE" → "2885"

_BASE = "https://apiconnect.angelbroking.com"

# ── Interval strings expected by Angel One ────────────────────────────────────
_INTERVAL_MAP: Dict[str, str] = {
    "1d":  "ONE_DAY",
    "1wk": "ONE_WEEK",
    "1mo": "ONE_MONTH",
    "5m":  "FIVE_MINUTE",
    "15m": "FIFTEEN_MINUTE",
    "30m": "THIRTY_MINUTE",
    "60m": "ONE_HOUR",
    "1h":  "ONE_HOUR",
}

# ── Period → calendar days (mirrors data/fetcher.py) ─────────────────────────
_PERIOD_DAYS: Dict[str, int] = {
    "1d": 10, "5d": 18, "1m": 35, "6m": 185,
    "1y": 370, "2y": 740, "max": 1830,
}


# ─────────────────────────────────────────────────────────────────────────────
# Credentials + session
# ─────────────────────────────────────────────────────────────────────────────

def _get_credentials() -> Dict[str, str]:
    """Read Angel One credentials from Streamlit secrets or environment."""
    creds: Dict[str, str] = {}

    # 1. Streamlit secrets (cloud deploy)
    try:
        import streamlit as st
        ao = st.secrets.get("angel_one", {})
        creds = {
            "api_key":     str(ao.get("api_key",     "")),
            "client_id":   str(ao.get("client_id",   "")),
            "password":    str(ao.get("password",    "")),
            "totp_secret": str(ao.get("totp_secret", "")),
        }
    except Exception:
        pass

    # 2. Environment variables (fallback / local dev)
    for key, env in (
        ("api_key",     "ANGEL_API_KEY"),
        ("client_id",   "ANGEL_CLIENT_ID"),
        ("password",    "ANGEL_PASSWORD"),
        ("totp_secret", "ANGEL_TOTP_SECRET"),
    ):
        if not creds.get(key):
            creds[key] = os.environ.get(env, "")

    return creds


def is_configured() -> bool:
    """Return True if all four Angel One credentials are present."""
    c = _get_credentials()
    return bool(c["api_key"] and c["client_id"] and c["password"] and c["totp_secret"])


def _auth_headers(jwt: str, api_key: str) -> Dict[str, str]:
    return {
        "Authorization":    f"Bearer {jwt}",
        "Content-Type":     "application/json",
        "Accept":           "application/json",
        "X-UserType":       "USER",
        "X-SourceID":       "WEB",
        "X-ClientLocalIP":  "127.0.0.1",
        "X-ClientPublicIP": "127.0.0.1",
        "X-MACAddress":     "00:00:00:00:00:00",
        "X-PrivateKey":     api_key,
    }


def _get_session() -> Optional[Dict]:
    """
    Login and return session dict (jwt, feed_token, api_key).
    Cached for 50 minutes (JWT valid for 1 hour).
    Returns None if not configured or login fails.
    """
    global _SESSION
    now = time.time()

    # Return cached session if still valid
    if _SESSION["jwt"] and now - _SESSION["ts"] < 3000:
        return _SESSION

    creds = _get_credentials()
    if not all(creds.values()):
        return None

    try:
        import pyotp
        totp_code = pyotp.TOTP(creds["totp_secret"]).now()

        payload = json.dumps({
            "clientcode": creds["client_id"],
            "password":   creds["password"],
            "totp":       totp_code,
        }).encode()

        req = urllib.request.Request(
            f"{_BASE}/rest/auth/angelbroking/user/v1/loginByPassword",
            data=payload,
            headers={
                "Content-Type":     "application/json",
                "Accept":           "application/json",
                "X-UserType":       "USER",
                "X-SourceID":       "WEB",
                "X-ClientLocalIP":  "127.0.0.1",
                "X-ClientPublicIP": "127.0.0.1",
                "X-MACAddress":     "00:00:00:00:00:00",
                "X-PrivateKey":     creds["api_key"],
            },
        )
        with urllib.request.urlopen(req, timeout=15) as r:
            resp = json.loads(r.read())

        if not resp.get("status"):
            return None

        _SESSION.update({
            "jwt":        resp["data"]["jwtToken"],
            "feed_token": resp["data"]["feedToken"],
            "api_key":    creds["api_key"],
            "ts":         now,
        })
        return _SESSION

    except Exception:
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Symbol token lookup
# ─────────────────────────────────────────────────────────────────────────────

def _get_token(symbol_base: str, session: Dict) -> Optional[str]:
    """
    Get Angel One numeric token for a base NSE symbol (no .NS suffix).
    Calls searchScrip API once per symbol, then caches in _TOKEN_CACHE.
    """
    # Angel One stores M&M as "M&M" but JSON payload needs a clean search term;
    # some brokers also index it as "MM" — try both if needed
    key = symbol_base.upper()
    # Normalise tickers that contain special chars for the search call
    _search_key = key.replace("&", "%26") if "&" in key else key
    if key in _TOKEN_CACHE:
        return _TOKEN_CACHE[key]

    try:
        # Use the normalised search key for the API call
        payload = json.dumps({"exchange": "NSE", "searchscrip": _search_key}).encode()
        req = urllib.request.Request(
            f"{_BASE}/rest/secure/angelbroking/order/v1/searchScrip",
            data=payload,
            headers=_auth_headers(session["jwt"], session["api_key"]),
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())

        scrips: List[Dict] = data.get("data") or []
        token: Optional[str] = None

        # Prefer exact EQ match — compare against both original key and search key
        for s in scrips:
            sym   = s.get("tradingsymbol", "").upper()
            itype = s.get("instrumenttype", "").upper()
            if sym in (key, _search_key) and itype in ("", "EQ", "-EQ"):
                token = str(s["symboltoken"])
                break
        # Fallback: first result
        if token is None and scrips:
            token = str(scrips[0]["symboltoken"])

        _TOKEN_CACHE[key] = token
        return token

    except Exception:
        _TOKEN_CACHE[key] = None
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Date helpers
# ─────────────────────────────────────────────────────────────────────────────

def _period_to_dates(period: str) -> Tuple[str, str]:
    """Return (fromdate, todate) strings in Angel One format 'YYYY-MM-DD HH:MM'."""
    today = datetime.date.today()

    if period == "ytd":
        start = datetime.date(today.year, 1, 1)
    else:
        days  = _PERIOD_DAYS.get(period, 370)
        start = today - datetime.timedelta(days=days)

    _fmt = "%Y-%m-%d %H:%M"
    fromdate = datetime.datetime.combine(start,  datetime.time(9, 15)).strftime(_fmt)
    todate   = datetime.datetime.combine(today,  datetime.time(15, 30)).strftime(_fmt)
    return fromdate, todate


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def fetch_historical(
    ticker:   str,
    period:   str = "1y",
    interval: str = "1d",
) -> Optional[pd.DataFrame]:
    """
    Fetch OHLCV candle data from Angel One SmartAPI.

    Args:
        ticker  : NSE ticker — 'RELIANCE.NS' or plain 'RELIANCE'
        period  : '1d','5d','1m','6m','1y','2y','ytd','max'
        interval: '1d','1wk','5m','15m','30m','60m'

    Returns:
        pd.DataFrame with DatetimeIndex, columns Open/High/Low/Close/Volume
        or None on failure (caller falls through to Stooq / Yahoo).
    """
    session = _get_session()
    if session is None:
        return None

    symbol = ticker.replace(".NS", "").replace(".BO", "").upper()
    token  = _get_token(symbol, session)
    if token is None:
        return None

    ao_interval = _INTERVAL_MAP.get(interval, "ONE_DAY")
    fromdate, todate = _period_to_dates(period)

    try:
        payload = json.dumps({
            "exchange":    "NSE",
            "symboltoken": token,
            "interval":    ao_interval,
            "fromdate":    fromdate,
            "todate":      todate,
        }).encode()

        req = urllib.request.Request(
            f"{_BASE}/rest/secure/angelbroking/historical/v1/getCandleData",
            data=payload,
            headers=_auth_headers(session["jwt"], session["api_key"]),
        )
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.loads(r.read())

        candles = data.get("data") or []
        if not candles:
            return None

        # Response: [[timestamp, open, high, low, close, volume], ...]
        df = pd.DataFrame(
            candles, columns=["Date", "Open", "High", "Low", "Close", "Volume"]
        )
        df["Date"] = pd.to_datetime(df["Date"])
        df = df.set_index("Date").sort_index()
        df = df.apply(pd.to_numeric, errors="coerce")
        df.dropna(subset=["Close"], inplace=True)

        return df if not df.empty else None

    except Exception:
        # JWT may have expired — force refresh on next call
        _SESSION["jwt"] = None
        return None


def get_live_quote(ticker: str) -> Optional[Dict]:
    """
    Get live market quote from Angel One.

    Returns:
        {"price": float, "prev_close": float, "chg_pct": float}
        or None on failure / not configured.
    """
    session = _get_session()
    if session is None:
        return None

    symbol = ticker.replace(".NS", "").replace(".BO", "").upper()
    token  = _get_token(symbol, session)
    if token is None:
        return None

    try:
        payload = json.dumps({
            "mode": "FULL",
            "exchangeTokens": {"NSE": [token]},
        }).encode()

        req = urllib.request.Request(
            f"{_BASE}/rest/secure/angelbroking/market/v1/quote/",
            data=payload,
            headers=_auth_headers(session["jwt"], session["api_key"]),
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())

        fetched = (data.get("data", {}).get("fetched") or [])
        if not fetched:
            return None

        q = fetched[0]
        price      = float(q.get("ltp",   0))
        prev_close = float(q.get("close", price))

        if price <= 0:
            return None

        return {
            "price":      price,
            "prev_close": prev_close,
            "chg_pct":    (price / prev_close - 1) * 100 if prev_close > 0 else 0.0,
        }

    except Exception:
        return None


def clear_session() -> None:
    """Force a fresh login on the next call (useful after credential update)."""
    global _SESSION
    _SESSION["jwt"] = None


# ─────────────────────────────────────────────────────────────────────────────
# Extended Market Data
# ─────────────────────────────────────────────────────────────────────────────

def get_full_quote(ticker: str) -> Optional[Dict]:
    """
    Full market data for one ticker — live LTP, today's OHLC, volume,
    52-week high/low, upper/lower circuits, OI.

    Returns dict with all available fields, or None on failure.
    """
    session = _get_session()
    if session is None:
        return None

    symbol = ticker.replace(".NS", "").replace(".BO", "").upper()
    token  = _get_token(symbol, session)
    if token is None:
        return None

    try:
        payload = json.dumps({
            "mode": "FULL",
            "exchangeTokens": {"NSE": [token]},
        }).encode()

        req = urllib.request.Request(
            f"{_BASE}/rest/secure/angelbroking/market/v1/quote/",
            data=payload,
            headers=_auth_headers(session["jwt"], session["api_key"]),
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())

        fetched = (data.get("data", {}).get("fetched") or [])
        if not fetched:
            return None

        q = fetched[0]
        price      = float(q.get("ltp", 0))
        prev_close = float(q.get("close", price))
        if price <= 0:
            return None

        return {
            "ticker":          symbol,
            "price":           price,
            "prev_close":      prev_close,
            "chg_pct":         (price / prev_close - 1) * 100 if prev_close > 0 else 0.0,
            "open":            float(q.get("open",  0)),
            "high":            float(q.get("high",  0)),
            "low":             float(q.get("low",   0)),
            "volume":          int(q.get("totaltradedvolume", 0) or 0),
            "avg_price":       float(q.get("averagetradedprice", 0) or 0),
            "upper_circuit":   float(q.get("uppercircuit", 0) or 0),
            "lower_circuit":   float(q.get("lowercircuit", 0) or 0),
            "week_52_high":    float(q.get("52weekhigh", 0) or 0),
            "week_52_low":     float(q.get("52weeklow",  0) or 0),
            "oi":              int(q.get("opentrades", 0) or 0),
            "bid":             float((q.get("depth", {}).get("buy",  [{}])[0] or {}).get("price", 0)),
            "ask":             float((q.get("depth", {}).get("sell", [{}])[0] or {}).get("price", 0)),
            "bid_qty":         int((q.get("depth", {}).get("buy",  [{}])[0] or {}).get("quantity", 0)),
            "ask_qty":         int((q.get("depth", {}).get("sell", [{}])[0] or {}).get("quantity", 0)),
            "net_chg":         price - prev_close,
        }

    except Exception:
        return None


def get_batch_quotes(tickers: List[str]) -> Dict[str, Optional[Dict]]:
    """
    Fetch live quotes for multiple tickers in batched calls (max 50 per request).

    Args:
        tickers : list of NSE tickers (e.g. ['RELIANCE.NS', 'TCS.NS'])

    Returns:
        Dict keyed by original ticker, value = full_quote dict or None.
    """
    if not tickers:
        return {}

    session = _get_session()
    if session is None:
        return {t: None for t in tickers}

    # Resolve all tokens first
    symbols   = [t.replace(".NS", "").replace(".BO", "").upper() for t in tickers]
    token_map = {}  # token → original_ticker
    valid_tokens: List[str] = []

    for orig, sym in zip(tickers, symbols):
        token = _get_token(sym, session)
        if token:
            token_map[token] = orig
            valid_tokens.append(token)

    if not valid_tokens:
        return {t: None for t in tickers}

    results: Dict[str, Optional[Dict]] = {t: None for t in tickers}
    BATCH = 50

    for i in range(0, len(valid_tokens), BATCH):
        batch = valid_tokens[i: i + BATCH]
        try:
            payload = json.dumps({
                "mode": "FULL",
                "exchangeTokens": {"NSE": batch},
            }).encode()

            req = urllib.request.Request(
                f"{_BASE}/rest/secure/angelbroking/market/v1/quote/",
                data=payload,
                headers=_auth_headers(session["jwt"], session["api_key"]),
            )
            with urllib.request.urlopen(req, timeout=15) as r:
                data = json.loads(r.read())

            fetched = (data.get("data", {}).get("fetched") or [])
            for q in fetched:
                tok  = str(q.get("symbolToken", ""))
                orig = token_map.get(tok)
                if orig is None:
                    continue
                price      = float(q.get("ltp", 0))
                prev_close = float(q.get("close", price))
                if price <= 0:
                    continue
                results[orig] = {
                    "ticker":          orig,
                    "price":           price,
                    "prev_close":      prev_close,
                    "chg_pct":         (price / prev_close - 1) * 100 if prev_close > 0 else 0.0,
                    "open":            float(q.get("open", 0)),
                    "high":            float(q.get("high", 0)),
                    "low":             float(q.get("low",  0)),
                    "volume":          int(q.get("totaltradedvolume", 0) or 0),
                    "upper_circuit":   float(q.get("uppercircuit", 0) or 0),
                    "lower_circuit":   float(q.get("lowercircuit", 0) or 0),
                    "week_52_high":    float(q.get("52weekhigh", 0) or 0),
                    "week_52_low":     float(q.get("52weeklow",  0) or 0),
                    "net_chg":         price - prev_close,
                }
        except Exception:
            continue

    return results


def get_market_depth(ticker: str) -> Optional[Dict]:
    """
    Get top-5 bid/ask market depth for a single ticker.

    Returns:
        {
            "buys":  [{"price": float, "qty": int, "orders": int}, ...],  # 5 levels
            "sells": [{"price": float, "qty": int, "orders": int}, ...],  # 5 levels
            "ltp":   float,
            "total_buy_qty": int,
            "total_sell_qty": int,
        }
        or None on failure.
    """
    session = _get_session()
    if session is None:
        return None

    symbol = ticker.replace(".NS", "").replace(".BO", "").upper()
    token  = _get_token(symbol, session)
    if token is None:
        return None

    try:
        payload = json.dumps({
            "mode": "FULL",
            "exchangeTokens": {"NSE": [token]},
        }).encode()

        req = urllib.request.Request(
            f"{_BASE}/rest/secure/angelbroking/market/v1/quote/",
            data=payload,
            headers=_auth_headers(session["jwt"], session["api_key"]),
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())

        fetched = (data.get("data", {}).get("fetched") or [])
        if not fetched:
            return None

        q     = fetched[0]
        depth = q.get("depth", {})
        buys  = depth.get("buy",  []) or []
        sells = depth.get("sell", []) or []

        def _parse_levels(levels: list) -> List[Dict]:
            out = []
            for lv in levels[:5]:
                out.append({
                    "price":  float(lv.get("price", 0)),
                    "qty":    int(lv.get("quantity", 0)),
                    "orders": int(lv.get("orders", 0)),
                })
            return out

        parsed_buys  = _parse_levels(buys)
        parsed_sells = _parse_levels(sells)

        total_buy_qty  = sum(lv["qty"] for lv in parsed_buys)
        total_sell_qty = sum(lv["qty"] for lv in parsed_sells)

        return {
            "buys":          parsed_buys,
            "sells":         parsed_sells,
            "ltp":           float(q.get("ltp", 0)),
            "total_buy_qty": total_buy_qty,
            "total_sell_qty":total_sell_qty,
            "buy_sell_ratio": (total_buy_qty / total_sell_qty
                               if total_sell_qty > 0 else None),
        }

    except Exception:
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Portfolio & Account
# ─────────────────────────────────────────────────────────────────────────────

def get_holdings() -> Optional[List[Dict]]:
    """
    Fetch all equity holdings in the Angel One demat account.

    Returns list of dicts:
        {
            "symbol", "exchange", "isin", "qty", "t1_qty",
            "avg_price", "ltp", "pnl", "pnl_pct", "value_rs"
        }
    or None on failure / not configured.
    """
    session = _get_session()
    if session is None:
        return None

    try:
        req = urllib.request.Request(
            f"{_BASE}/rest/secure/angelbroking/portfolio/v1/getHolding",
            headers=_auth_headers(session["jwt"], session["api_key"]),
        )
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read())

        raw = data.get("data") or []
        if not raw:
            return []

        holdings = []
        for h in raw:
            qty = int(h.get("quantity", 0) or 0)
            if qty <= 0:
                continue
            avg   = float(h.get("averageprice", 0) or 0)
            ltp   = float(h.get("ltp", avg) or avg)
            pnl   = (ltp - avg) * qty
            pnl_p = ((ltp / avg) - 1) * 100 if avg > 0 else 0.0

            holdings.append({
                "symbol":   h.get("tradingsymbol", "").replace("-EQ", ""),
                "exchange": h.get("exchange", "NSE"),
                "isin":     h.get("isin", ""),
                "qty":      qty,
                "t1_qty":   int(h.get("t1qty", 0) or 0),
                "avg_price": round(avg, 2),
                "ltp":       round(ltp, 2),
                "pnl":       round(pnl, 2),
                "pnl_pct":   round(pnl_p, 2),
                "value_rs":  round(ltp * qty, 2),
            })

        return sorted(holdings, key=lambda x: x["value_rs"], reverse=True)

    except Exception:
        return None


def get_positions() -> Optional[Dict]:
    """
    Fetch today's open positions (both CNC day-trade and MIS intraday).

    Returns:
        {
            "day": [{"symbol", "qty", "avg_price", "ltp", "pnl", "product"}, ...],
            "net": [...],  # net positions across all products
        }
    or None on failure.
    """
    session = _get_session()
    if session is None:
        return None

    try:
        req = urllib.request.Request(
            f"{_BASE}/rest/secure/angelbroking/order/v1/getPosition",
            headers=_auth_headers(session["jwt"], session["api_key"]),
        )
        with urllib.request.urlopen(req, timeout=12) as r:
            data = json.loads(r.read())

        raw = data.get("data") or {}
        if not raw:
            return {"day": [], "net": []}

        def _parse_positions(items: list) -> List[Dict]:
            out = []
            for p in (items or []):
                qty = int(p.get("netqty", 0) or 0)
                if qty == 0:
                    continue
                avg = float(p.get("netavgprice", 0) or 0)
                ltp = float(p.get("ltp", avg) or avg)
                out.append({
                    "symbol":    p.get("tradingsymbol", "").replace("-EQ", ""),
                    "qty":       qty,
                    "avg_price": round(avg, 2),
                    "ltp":       round(ltp, 2),
                    "pnl":       round((ltp - avg) * qty, 2),
                    "product":   p.get("producttype", ""),
                    "side":      "LONG" if qty > 0 else "SHORT",
                })
            return out

        return {
            "day": _parse_positions(raw.get("day") or []),
            "net": _parse_positions(raw.get("net") or []),
        }

    except Exception:
        return None


def get_funds() -> Optional[Dict]:
    """
    Fetch available funds and margin utilisation from Angel One.

    Returns:
        {
            "available_cash":  float,
            "used_margin":     float,
            "total_margin":    float,
            "collateral":      float,
            "m2m":             float,
        }
    or None on failure.
    """
    session = _get_session()
    if session is None:
        return None

    try:
        req = urllib.request.Request(
            f"{_BASE}/rest/secure/angelbroking/user/v1/getRMS",
            headers=_auth_headers(session["jwt"], session["api_key"]),
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())

        d = data.get("data") or {}
        return {
            "available_cash":  float(d.get("availablecash",          0) or 0),
            "used_margin":     float(d.get("utiliseddebits",          0) or 0),
            "total_margin":    float(d.get("net",                     0) or 0),
            "collateral":      float(d.get("collateral",              0) or 0),
            "m2m":             float(d.get("m2munrealisedprofit",     0) or 0),
        }

    except Exception:
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Order Book & Trade Book
# ─────────────────────────────────────────────────────────────────────────────

def get_order_book() -> Optional[List[Dict]]:
    """
    Fetch all orders placed today (open, executed, cancelled, rejected).

    Returns list of order dicts or None on failure.
    """
    session = _get_session()
    if session is None:
        return None

    try:
        req = urllib.request.Request(
            f"{_BASE}/rest/secure/angelbroking/order/v1/list",
            headers=_auth_headers(session["jwt"], session["api_key"]),
        )
        with urllib.request.urlopen(req, timeout=12) as r:
            data = json.loads(r.read())

        raw = data.get("data") or []
        orders = []
        for o in raw:
            orders.append({
                "order_id":    o.get("orderid", ""),
                "symbol":      o.get("tradingsymbol", "").replace("-EQ", ""),
                "side":        o.get("transactiontype", ""),
                "qty":         int(o.get("quantity", 0) or 0),
                "filled_qty":  int(o.get("filledshares", 0) or 0),
                "price":       float(o.get("price", 0) or 0),
                "avg_price":   float(o.get("averageprice", 0) or 0),
                "order_type":  o.get("ordertype", ""),
                "status":      o.get("status", ""),
                "product":     o.get("producttype", ""),
                "time":        o.get("updatetime", ""),
                "variety":     o.get("variety", "NORMAL"),
            })
        return orders

    except Exception:
        return None


def get_trade_book() -> Optional[List[Dict]]:
    """
    Fetch all executed trades today.

    Returns list of trade dicts or None on failure.
    """
    session = _get_session()
    if session is None:
        return None

    try:
        req = urllib.request.Request(
            f"{_BASE}/rest/secure/angelbroking/order/v1/getTradeBook",
            headers=_auth_headers(session["jwt"], session["api_key"]),
        )
        with urllib.request.urlopen(req, timeout=12) as r:
            data = json.loads(r.read())

        raw = data.get("data") or []
        trades = []
        for t in raw:
            trades.append({
                "order_id":   t.get("orderid", ""),
                "trade_id":   t.get("tradeid", ""),
                "symbol":     t.get("tradingsymbol", "").replace("-EQ", ""),
                "side":       t.get("transactiontype", ""),
                "qty":        int(t.get("fillsize", 0) or 0),
                "price":      float(t.get("fillprice", 0) or 0),
                "product":    t.get("producttype", ""),
                "exchange":   t.get("exchange", ""),
                "time":       t.get("filltime", ""),
            })
        return trades

    except Exception:
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Order Placement
# ─────────────────────────────────────────────────────────────────────────────

def place_order(
    symbol:        str,
    qty:           int,
    side:          str,           # "BUY" or "SELL"
    order_type:    str = "MARKET", # "MARKET","LIMIT","SL","SL-M"
    price:         float = 0.0,
    trigger_price: float = 0.0,
    product:       str = "INTRADAY",  # "INTRADAY" (MIS) or "DELIVERY" (CNC)
    exchange:      str = "NSE",
    validity:      str = "DAY",       # "DAY" or "IOC"
    variety:       str = "NORMAL",
) -> Optional[Dict]:
    """
    Place a new order via Angel One SmartAPI.

    Returns:
        {"order_id": str, "status": "placed"} on success
        or None on failure.
    """
    session = _get_session()
    if session is None:
        return None

    sym = symbol.replace(".NS", "").replace(".BO", "").upper()
    token = _get_token(sym, session)
    if token is None:
        return None

    try:
        payload = json.dumps({
            "variety":          variety,
            "tradingsymbol":    sym + "-EQ",
            "symboltoken":      token,
            "transactiontype":  side.upper(),
            "exchange":         exchange,
            "ordertype":        order_type,
            "producttype":      product,
            "duration":         validity,
            "price":            str(price) if price else "0",
            "squareoff":        "0",
            "stoploss":         str(trigger_price) if trigger_price else "0",
            "quantity":         str(qty),
        }).encode()

        req = urllib.request.Request(
            f"{_BASE}/rest/secure/angelbroking/order/v1/placeOrder",
            data=payload,
            headers=_auth_headers(session["jwt"], session["api_key"]),
        )
        with urllib.request.urlopen(req, timeout=15) as r:
            resp = json.loads(r.read())

        if resp.get("status"):
            return {
                "order_id": resp.get("data", {}).get("orderid", ""),
                "status":   "placed",
            }
        return {"status": "failed", "message": resp.get("message", "Unknown error")}

    except Exception as e:
        return {"status": "error", "message": str(e)}


def modify_order(
    order_id:      str,
    symbol:        str,
    qty:           int,
    order_type:    str,
    price:         float = 0.0,
    trigger_price: float = 0.0,
    exchange:      str = "NSE",
    validity:      str = "DAY",
    variety:       str = "NORMAL",
) -> Optional[Dict]:
    """
    Modify a pending order.

    Returns:
        {"order_id": str, "status": "modified"} on success or None.
    """
    session = _get_session()
    if session is None:
        return None

    sym   = symbol.replace(".NS", "").replace(".BO", "").upper()
    token = _get_token(sym, session)
    if token is None:
        return None

    try:
        payload = json.dumps({
            "variety":       variety,
            "orderid":       order_id,
            "ordertype":     order_type,
            "producttype":   "DELIVERY",
            "duration":      validity,
            "price":         str(price),
            "quantity":      str(qty),
            "tradingsymbol": sym + "-EQ",
            "symboltoken":   token,
            "exchange":      exchange,
            "stoploss":      str(trigger_price) if trigger_price else "0",
            "squareoff":     "0",
        }).encode()

        req = urllib.request.Request(
            f"{_BASE}/rest/secure/angelbroking/order/v1/modifyOrder",
            data=payload,
            headers=_auth_headers(session["jwt"], session["api_key"]),
        )
        with urllib.request.urlopen(req, timeout=12) as r:
            resp = json.loads(r.read())

        if resp.get("status"):
            return {
                "order_id": resp.get("data", {}).get("orderid", order_id),
                "status":   "modified",
            }
        return {"status": "failed", "message": resp.get("message", "")}

    except Exception as e:
        return {"status": "error", "message": str(e)}


def cancel_order(order_id: str, variety: str = "NORMAL") -> bool:
    """
    Cancel a pending order.

    Returns True on success, False on failure.
    """
    session = _get_session()
    if session is None:
        return False

    try:
        payload = json.dumps({
            "variety": variety,
            "orderid": order_id,
        }).encode()

        req = urllib.request.Request(
            f"{_BASE}/rest/secure/angelbroking/order/v1/cancelOrder",
            data=payload,
            headers=_auth_headers(session["jwt"], session["api_key"]),
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            resp = json.loads(r.read())

        return bool(resp.get("status"))

    except Exception:
        return False


# ─────────────────────────────────────────────────────────────────────────────
# GTT (Good Till Triggered) Orders
# ─────────────────────────────────────────────────────────────────────────────

def place_gtt(
    symbol:        str,
    qty:           int,
    trigger_price: float,
    limit_price:   float,
    current_price: float,
    side:          str = "BUY",  # "BUY" or "SELL"
    exchange:      str = "NSE",
    product_type:  str = "DELIVERY",
) -> Optional[Dict]:
    """
    Place a Good Till Triggered (GTT) order.

    Common use: buy-on-breakout or sell-on-stop-loss with day's-end safety.

    Args:
        symbol        : NSE ticker (e.g. 'RELIANCE' or 'RELIANCE.NS')
        qty           : Number of shares
        trigger_price : Price at which the GTT fires
        limit_price   : Limit price for the triggered order
        current_price : Current market price (required by Angel One API)
        side          : 'BUY' or 'SELL'
        exchange      : 'NSE' or 'BSE'
        product_type  : 'DELIVERY' (CNC) or 'INTRADAY' (MIS)

    Returns:
        {"rule_id": str, "status": "placed"} on success or None.
    """
    session = _get_session()
    if session is None:
        return None

    sym   = symbol.replace(".NS", "").replace(".BO", "").upper()
    token = _get_token(sym, session)
    if token is None:
        return None

    try:
        payload = json.dumps({
            "tradingsymbol":   sym + "-EQ",
            "symboltoken":     token,
            "exchange":        exchange,
            "producttype":     product_type,
            "transactiontype": side.upper(),
            "price":           str(limit_price),
            "qty":             str(qty),
            "triggerprice":    str(trigger_price),
            "disclosedqty":    "0",
            "timeperiod":      "365",
        }).encode()

        req = urllib.request.Request(
            f"{_BASE}/rest/secure/angelbroking/gtt/v1/createRule",
            data=payload,
            headers=_auth_headers(session["jwt"], session["api_key"]),
        )
        with urllib.request.urlopen(req, timeout=12) as r:
            resp = json.loads(r.read())

        if resp.get("status"):
            return {
                "rule_id": str(resp.get("data", {}).get("id", "")),
                "status":  "placed",
            }
        return {"status": "failed", "message": resp.get("message", "")}

    except Exception as e:
        return {"status": "error", "message": str(e)}


def get_gtt_list() -> Optional[List[Dict]]:
    """
    Get all active GTT rules in the account.

    Returns list of GTT rule dicts or None on failure.
    """
    session = _get_session()
    if session is None:
        return None

    try:
        req = urllib.request.Request(
            f"{_BASE}/rest/secure/angelbroking/gtt/v1/ruleList",
            headers=_auth_headers(session["jwt"], session["api_key"]),
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())

        raw = data.get("data") or []
        gtts = []
        for g in raw:
            gtts.append({
                "rule_id":     str(g.get("id", "")),
                "symbol":      g.get("tradingsymbol", "").replace("-EQ", ""),
                "side":        g.get("transactiontype", ""),
                "qty":         int(g.get("qty", 0) or 0),
                "trigger":     float(g.get("triggerprice", 0) or 0),
                "limit_price": float(g.get("price", 0) or 0),
                "status":      g.get("status", ""),
            })
        return gtts

    except Exception:
        return None


def cancel_gtt(rule_id: str, symbol: str, exchange: str = "NSE") -> bool:
    """
    Cancel/delete an active GTT rule.

    Returns True on success.
    """
    session = _get_session()
    if session is None:
        return False

    sym   = symbol.replace(".NS", "").replace(".BO", "").upper()
    token = _get_token(sym, session) or ""

    try:
        payload = json.dumps({
            "id":            str(rule_id),
            "tradingsymbol": sym + "-EQ",
            "symboltoken":   token,
            "exchange":      exchange,
        }).encode()

        req = urllib.request.Request(
            f"{_BASE}/rest/secure/angelbroking/gtt/v1/cancelRule",
            data=payload,
            headers=_auth_headers(session["jwt"], session["api_key"]),
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            resp = json.loads(r.read())

        return bool(resp.get("status"))

    except Exception:
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Account Profile
# ─────────────────────────────────────────────────────────────────────────────

def get_profile() -> Optional[Dict]:
    """
    Get Angel One account profile.

    Returns:
        {"name": str, "client_id": str, "email": str, "mobile": str,
         "exchanges": list, "products": list}
    or None on failure.
    """
    session = _get_session()
    if session is None:
        return None

    try:
        req = urllib.request.Request(
            f"{_BASE}/rest/secure/angelbroking/user/v1/getProfile",
            headers=_auth_headers(session["jwt"], session["api_key"]),
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())

        d = data.get("data") or {}
        return {
            "name":      d.get("name",      ""),
            "client_id": d.get("clientcode",""),
            "email":     d.get("email",     ""),
            "mobile":    d.get("mobileno",  ""),
            "exchanges": d.get("exchanges", []),
            "products":  d.get("products",  []),
            "broker":    d.get("broker",    "Angel One"),
        }

    except Exception:
        return None
