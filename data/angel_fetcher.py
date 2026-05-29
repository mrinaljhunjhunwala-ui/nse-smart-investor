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
    key = symbol_base.upper()
    if key in _TOKEN_CACHE:
        return _TOKEN_CACHE[key]

    try:
        payload = json.dumps({"exchange": "NSE", "searchscrip": key}).encode()
        req = urllib.request.Request(
            f"{_BASE}/rest/secure/angelbroking/order/v1/searchScrip",
            data=payload,
            headers=_auth_headers(session["jwt"], session["api_key"]),
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())

        scrips: List[Dict] = data.get("data") or []
        token: Optional[str] = None

        # Prefer exact EQ match (equity), not derivatives/ETFs
        for s in scrips:
            sym  = s.get("tradingsymbol", "").upper()
            itype = s.get("instrumenttype", "").upper()
            if sym == key and itype in ("", "EQ", "-EQ"):
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
