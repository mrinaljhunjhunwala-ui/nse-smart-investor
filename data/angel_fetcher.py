"""
data/angel_fetcher.py
Angel One SmartAPI — Tier 0 data source for NSE/BSE historical + live data.

Fixes applied vs previous version:
  - requests.Session with retry replaces urllib (connection pooling + auto-retry)
  - _SESSION_LOCK + double-check locking eliminates login race condition
  - _TOKEN_CACHE now stores (token, timestamp) with 6-hour TTL
  - get_live_quote delegates to get_full_quote (no more duplicate code)
  - modify_order accepts `product` param (was hardcoded "DELIVERY")
  - _log.warning used for real failures (was _log.debug — invisible in prod)
  - get_batch_quotes applies rate limiting (same as fetch_historical)

FIX AO1 — _get_token() (searchScrip) had NO rate limiting, unlike
fetch_historical()'s getCandleData call right next to it. Every other
function in this file (fetch_historical, get_full_quote, get_batch_quotes,
get_market_depth, place_order, modify_order, place_gtt, cancel_gtt) calls
_get_token() first, so a full-universe scan (e.g. NIFTY 500) fired ~500
unthrottled searchScrip calls in a few seconds — blowing through Angel
One's documented combined limit of 1 request/second/client. Angel's API
appears to respond to this by returning empty/non-JSON bodies rather than
clean error objects, producing "Expecting value: line 1 column 1" on
every single ticker once the limit is breached — i.e. total Tier-0
outage even though login/credentials are perfectly valid.

  - _angel_rate_limit() (renamed from _hist_rate_limit, same shared
    module-level limiter) is now called inside _get_token() itself, so
    every caller is protected automatically without touching each one.
  - A circuit breaker trips after 5 consecutive _get_token() failures
    and pauses ALL Angel One attempts for 5 minutes, instead of paying a
    throttled-but-doomed round trip on every remaining ticker in the scan.
  - Failed token lookups are now cached for only 5 minutes (_TOKEN_FAIL_TTL),
    separate from the 6-hour TTL for real successes — so once Angel
    recovers, previously-poisoned tickers retry promptly instead of being
    stuck returning None for up to 6 hours.

FIX AO2 — _get_session() (loginByPassword) had the exact same gap as FIX AO1
did for _get_token(): no circuit breaker. Every other function in this file
calls _get_session() first, so broken credentials (rotated/expired
ANGEL_TOTP_SECRET, clock drift breaking the TOTP code, wrong password, or a
transient Angel outage) mean a full-universe scan fires ~500 unthrottled
loginByPassword POSTs in a row — not even covered by _angel_rate_limit().
Repeated failed logins against a broker's auth endpoint risk a temporary
account lock, a much costlier failure mode than the rate-limit issue FIX
AO1 addressed, so this breaker is deliberately stricter: it trips after
fewer consecutive failures and stays tripped longer than the token breaker.

  - A separate _LOGIN_BREAKER_* state (own lock/counters — failures here
    are unrelated to searchScrip failures and shouldn't share a counter)
    mirrors _breaker_tripped()/_record_failure()/_record_success() via
    _login_breaker_tripped()/_login_breaker_record_failure()/_success().
  - _get_session()'s slow path checks _login_breaker_tripped() right
    before attempting login (after the credentials-configured check,
    which is a separate "not set up at all" case) and returns None
    immediately without hitting the network if it's tripped.
  - A failed login (resp.get("status") falsy, or any exception) records a
    breaker failure; a successful login resets it.
"""

from __future__ import annotations

import logging
import os
import time
import threading
import datetime
from typing import Dict, List, Optional, Tuple

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

_log = logging.getLogger("angel_fetcher")

# ── HTTP session with retry adapter ───────────────────────────────────────────
# Replaces per-call urllib.request — gives connection pooling + auto-retry
# on transient server errors (500/502/503/504).
_http = requests.Session()
_http.mount("https://", HTTPAdapter(
    max_retries=Retry(
        total=3,
        backoff_factor=0.5,
        status_forcelist=[500, 502, 503, 504],
        allowed_methods=["GET", "POST"],
    )
))

# ── In-process caches ─────────────────────────────────────────────────────────
_SESSION:      Dict = {"jwt": None, "feed_token": None, "api_key": "", "ts": 0.0}
_SESSION_LOCK  = threading.Lock()                           # guards login race condition
_TOKEN_CACHE:  Dict[str, Tuple[Optional[str], float]] = {} # symbol → (token, timestamp)
_TOKEN_TTL      = 3600 * 6  # 6 hours for a real resolved token — handles delistings
_TOKEN_FAIL_TTL = 300       # FIX AO1: only 5 min for a FAILED lookup — a failure during
                            # a rate-limit/breaker event shouldn't poison a ticker for 6h

# ── Shared rate limiter for ALL Angel One data-read calls ────────────────────
# FIX AO1: was "_hist_rate_limit", used only by fetch_historical(). Angel One's
# combined rate limit applies across endpoints, not per-endpoint, and the
# heaviest call volume by far is _get_token()'s searchScrip lookup (once per
# ticker, called by every other function below). Renamed + now called from
# _get_token() itself so every caller is protected without separate changes.
_HIST_LOCK         = threading.Lock()
_HIST_LAST         = [0.0]
_HIST_MIN_INTERVAL = 1.0   # 1 req/s — matches Angel's documented combined limit

def _angel_rate_limit() -> None:
    with _HIST_LOCK:
        elapsed = time.time() - _HIST_LAST[0]
        if elapsed < _HIST_MIN_INTERVAL:
            time.sleep(_HIST_MIN_INTERVAL - elapsed)
        _HIST_LAST[0] = time.time()

_hist_rate_limit = _angel_rate_limit  # back-compat alias, same function


# ── Circuit breaker for Angel One outages ─────────────────────────────────────
# FIX AO1: when Angel starts failing repeatedly (rate-limit ban, transient
# upstream outage), stop attempting calls for a cooldown period rather than
# paying a throttled-but-doomed round trip on every remaining ticker in a
# full-universe scan. Trips after 5 consecutive _get_token() failures; resets
# on the next success after cooldown expires.
_BREAKER_LOCK       = threading.Lock()
_BREAKER_FAILS      = [0]
_BREAKER_TRIPPED_AT = [0.0]
_BREAKER_THRESHOLD  = 5
_BREAKER_COOLDOWN   = 300  # 5 minutes


def _breaker_tripped() -> bool:
    with _BREAKER_LOCK:
        if _BREAKER_TRIPPED_AT[0]:
            if time.time() - _BREAKER_TRIPPED_AT[0] < _BREAKER_COOLDOWN:
                return True
            # cooldown expired — give Angel another chance
            _BREAKER_TRIPPED_AT[0] = 0.0
            _BREAKER_FAILS[0] = 0
        return False


def _breaker_record_failure() -> None:
    with _BREAKER_LOCK:
        _BREAKER_FAILS[0] += 1
        if _BREAKER_FAILS[0] >= _BREAKER_THRESHOLD and not _BREAKER_TRIPPED_AT[0]:
            _BREAKER_TRIPPED_AT[0] = time.time()
            _log.warning(
                "angel_fetcher: circuit breaker TRIPPED after %d consecutive "
                "_get_token() failures — pausing Angel One calls for %ds",
                _BREAKER_FAILS[0], _BREAKER_COOLDOWN,
            )


def _breaker_record_success() -> None:
    with _BREAKER_LOCK:
        _BREAKER_FAILS[0] = 0
        _BREAKER_TRIPPED_AT[0] = 0.0


# ── Circuit breaker for Angel One LOGIN failures ──────────────────────────────
# FIX AO2: separate from the _BREAKER_* state above — _get_token() failures
# (rate-limit/searchScrip) and login failures are different problems with
# different blast radii and shouldn't share a counter. Deliberately stricter
# than the token breaker: trips faster (3 vs 5) and stays tripped longer
# (10 min vs 5 min), because repeated failed loginByPassword attempts risk
# a temporary account lock from Angel — a costlier failure mode than being
# rate-limited on a read endpoint.
_LOGIN_BREAKER_LOCK       = threading.Lock()
_LOGIN_BREAKER_FAILS      = [0]
_LOGIN_BREAKER_TRIPPED_AT = [0.0]
_LOGIN_BREAKER_THRESHOLD  = 3
_LOGIN_BREAKER_COOLDOWN   = 600  # 10 minutes


def _login_breaker_tripped() -> bool:
    with _LOGIN_BREAKER_LOCK:
        if _LOGIN_BREAKER_TRIPPED_AT[0]:
            if time.time() - _LOGIN_BREAKER_TRIPPED_AT[0] < _LOGIN_BREAKER_COOLDOWN:
                return True
            # cooldown expired — give login another chance
            _LOGIN_BREAKER_TRIPPED_AT[0] = 0.0
            _LOGIN_BREAKER_FAILS[0] = 0
        return False


def _login_breaker_record_failure() -> None:
    with _LOGIN_BREAKER_LOCK:
        _LOGIN_BREAKER_FAILS[0] += 1
        if _LOGIN_BREAKER_FAILS[0] >= _LOGIN_BREAKER_THRESHOLD and not _LOGIN_BREAKER_TRIPPED_AT[0]:
            _LOGIN_BREAKER_TRIPPED_AT[0] = time.time()
            _log.warning(
                "angel_fetcher: LOGIN circuit breaker TRIPPED after %d consecutive "
                "_get_session() failures — pausing login attempts for %ds",
                _LOGIN_BREAKER_FAILS[0], _LOGIN_BREAKER_COOLDOWN,
            )


def _login_breaker_record_success() -> None:
    with _LOGIN_BREAKER_LOCK:
        _LOGIN_BREAKER_FAILS[0] = 0
        _LOGIN_BREAKER_TRIPPED_AT[0] = 0.0

_BASE = "https://apiconnect.angelbroking.com"

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
    Cached for 50 minutes. Thread-safe via double-check locking —
    prevents two concurrent threads from both logging in simultaneously.

    FIX AO2: gated by a circuit breaker — if login has failed 3+ times in
    a row recently, skip the network call entirely instead of risking a
    temporary account lock from repeated bad-credential attempts.
    """
    global _SESSION
    # Fast path: no lock needed if session is valid
    if _SESSION["jwt"] and time.time() - _SESSION["ts"] < 3000:
        return _SESSION

    # Slow path: acquire lock, double-check, then login
    with _SESSION_LOCK:
        if _SESSION["jwt"] and time.time() - _SESSION["ts"] < 3000:
            return _SESSION  # another thread already refreshed it

        creds = _get_credentials()
        if not all(creds.values()):
            return None

        if _login_breaker_tripped():
            return None  # Angel login is in a known-bad state — don't pile on

        try:
            import pyotp
            totp_code = pyotp.TOTP(creds["totp_secret"]).now()
            resp = _http.post(
                f"{_BASE}/rest/auth/angelbroking/user/v1/loginByPassword",
                json={
                    "clientcode": creds["client_id"],
                    "password":   creds["password"],
                    "totp":       totp_code,
                },
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
                timeout=15,
            ).json()

            if not resp.get("status"):
                _log.warning("angel_fetcher: login failed — %s", resp.get("message", "unknown"))
                _login_breaker_record_failure()
                return None

            _SESSION.update({
                "jwt":        resp["data"]["jwtToken"],
                "feed_token": resp["data"]["feedToken"],
                "api_key":    creds["api_key"],
                "ts":         time.time(),
            })
            _login_breaker_record_success()
            return _SESSION

        except Exception as e:
            _log.warning("angel_fetcher._get_session failed: %s", e)
            _login_breaker_record_failure()
            return None


# ─────────────────────────────────────────────────────────────────────────────
# Symbol token lookup
# ─────────────────────────────────────────────────────────────────────────────

def _get_token(symbol_base: str, session: Dict) -> Optional[str]:
    """
    Get Angel One numeric token for a base NSE symbol (no .NS suffix).
    Cached per symbol — 6h TTL for a real token, 5min TTL for a failed
    lookup (FIX AO1, see _TOKEN_FAIL_TTL).

    FIX AO1: now rate-limited (was the one unthrottled call in this file)
    and gated by the circuit breaker — if Angel has failed 5+ times in a
    row recently, skip the network call entirely instead of adding to the
    pile-up that's keeping it rate-limited.
    """
    key        = symbol_base.upper()
    _search_key = key.replace("&", "%26") if "&" in key else key

    # Check cache — different TTL depending on whether it was a hit or a miss
    if key in _TOKEN_CACHE:
        token, ts = _TOKEN_CACHE[key]
        ttl = _TOKEN_TTL if token is not None else _TOKEN_FAIL_TTL
        if time.time() - ts < ttl:
            return token

    if _breaker_tripped():
        return None  # Angel is in a known-bad state — don't pile on

    try:
        _angel_rate_limit()
        resp = _http.post(
            f"{_BASE}/rest/secure/angelbroking/order/v1/searchScrip",
            json={"exchange": "NSE", "searchscrip": _search_key},
            headers=_auth_headers(session["jwt"], session["api_key"]),
            timeout=10,
        ).json()

        scrips: List[Dict] = resp.get("data") or []
        token: Optional[str] = None

        for s in scrips:
            sym   = s.get("tradingsymbol", "").upper()
            itype = s.get("instrumenttype", "").upper()
            if sym in (key, _search_key) and itype in ("", "EQ", "-EQ"):
                token = str(s["symboltoken"])
                break
        if token is None and scrips:
            token = str(scrips[0]["symboltoken"])

        _TOKEN_CACHE[key] = (token, time.time())
        _breaker_record_success()
        return token

    except Exception as e:
        _log.warning("angel_fetcher._get_token(%s) failed: %s", key, e)
        _TOKEN_CACHE[key] = (None, time.time())
        _breaker_record_failure()
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Date helpers
# ─────────────────────────────────────────────────────────────────────────────

def _period_to_dates(period: str) -> Tuple[str, str]:
    today = datetime.date.today()
    if period == "ytd":
        start = datetime.date(today.year, 1, 1)
    else:
        days  = _PERIOD_DAYS.get(period, 370)
        start = today - datetime.timedelta(days=days)
    _fmt     = "%Y-%m-%d %H:%M"
    fromdate = datetime.datetime.combine(start, datetime.time(9, 15)).strftime(_fmt)
    todate   = datetime.datetime.combine(today, datetime.time(15, 30)).strftime(_fmt)
    return fromdate, todate


# ─────────────────────────────────────────────────────────────────────────────
# Public API — Historical data
# ─────────────────────────────────────────────────────────────────────────────

def fetch_historical(
    ticker:   str,
    period:   str = "1y",
    interval: str = "1d",
) -> Optional[pd.DataFrame]:
    """
    Fetch OHLCV candle data from Angel One SmartAPI.
    Returns DataFrame with DatetimeIndex and Open/High/Low/Close/Volume,
    or None on failure (caller falls through to Stooq / Yahoo).
    """
    session = _get_session()
    if session is None:
        return None

    symbol = ticker.replace(".NS", "").replace(".BO", "").upper()
    token  = _get_token(symbol, session)
    if token is None:
        return None

    ao_interval      = _INTERVAL_MAP.get(interval, "ONE_DAY")
    fromdate, todate = _period_to_dates(period)

    try:
        _hist_rate_limit()
        resp = _http.post(
            f"{_BASE}/rest/secure/angelbroking/historical/v1/getCandleData",
            json={
                "exchange":    "NSE",
                "symboltoken": token,
                "interval":    ao_interval,
                "fromdate":    fromdate,
                "todate":      todate,
            },
            headers=_auth_headers(session["jwt"], session["api_key"]),
            timeout=20,
        ).json()

        candles = resp.get("data") or []
        if not candles:
            return None

        df = pd.DataFrame(candles, columns=["Date", "Open", "High", "Low", "Close", "Volume"])
        df["Date"] = pd.to_datetime(df["Date"])
        df = df.set_index("Date").sort_index()
        df = df.apply(pd.to_numeric, errors="coerce")
        df.dropna(subset=["Close"], inplace=True)
        return df if not df.empty else None

    except Exception as e:
        _log.warning("angel_fetcher.fetch_historical(%s) failed: %s", symbol, e)
        _SESSION["jwt"] = None  # force refresh on next call
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Public API — Live quotes
# ─────────────────────────────────────────────────────────────────────────────

def get_full_quote(ticker: str) -> Optional[Dict]:
    """
    Full market data: live LTP, today's OHLC, volume, 52w high/low,
    upper/lower circuits, bid/ask depth, OI.
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
        resp = _http.post(
            f"{_BASE}/rest/secure/angelbroking/market/v1/quote/",
            json={"mode": "FULL", "exchangeTokens": {"NSE": [token]}},
            headers=_auth_headers(session["jwt"], session["api_key"]),
            timeout=10,
        ).json()

        fetched = (resp.get("data", {}).get("fetched") or [])
        if not fetched:
            return None

        q          = fetched[0]
        price      = float(q.get("ltp",   0))
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
            "bid":             float((q.get("depth", {}).get("buy",  [{}])[0] or {}).get("price",    0)),
            "ask":             float((q.get("depth", {}).get("sell", [{}])[0] or {}).get("price",    0)),
            "bid_qty":         int((q.get("depth",   {}).get("buy",  [{}])[0] or {}).get("quantity", 0)),
            "ask_qty":         int((q.get("depth",   {}).get("sell", [{}])[0] or {}).get("quantity", 0)),
            "net_chg":         price - prev_close,
        }

    except Exception as e:
        _log.warning("angel_fetcher.get_full_quote(%s) failed: %s", symbol, e)
        return None


def get_live_quote(ticker: str) -> Optional[Dict]:
    """
    Get live price, prev_close, and change%.
    Delegates to get_full_quote — no duplicate API call.
    Returns {"price", "prev_close", "chg_pct"} or None.
    """
    full = get_full_quote(ticker)
    if full is None:
        return None
    return {
        "price":      full["price"],
        "prev_close": full["prev_close"],
        "chg_pct":    full["chg_pct"],
    }


def clear_session() -> None:
    """Force a fresh login on the next call (useful after credential update)."""
    global _SESSION
    _SESSION["jwt"] = None


def get_batch_quotes(tickers: List[str]) -> Dict[str, Optional[Dict]]:
    """
    Fetch live quotes for multiple tickers in batched calls (max 50 per request).
    Rate-limited same as fetch_historical to avoid 429s under concurrent load.
    """
    if not tickers:
        return {}

    session = _get_session()
    if session is None:
        return {t: None for t in tickers}

    symbols   = [t.replace(".NS", "").replace(".BO", "").upper() for t in tickers]
    token_map = {}
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
            _hist_rate_limit()  # rate-limit batch calls same as candle calls
            resp = _http.post(
                f"{_BASE}/rest/secure/angelbroking/market/v1/quote/",
                json={"mode": "FULL", "exchangeTokens": {"NSE": batch}},
                headers=_auth_headers(session["jwt"], session["api_key"]),
                timeout=15,
            ).json()

            fetched = (resp.get("data", {}).get("fetched") or [])
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
                    "ticker":        orig,
                    "price":         price,
                    "prev_close":    prev_close,
                    "chg_pct":       (price / prev_close - 1) * 100 if prev_close > 0 else 0.0,
                    "open":          float(q.get("open", 0)),
                    "high":          float(q.get("high", 0)),
                    "low":           float(q.get("low",  0)),
                    "volume":        int(q.get("totaltradedvolume", 0) or 0),
                    "upper_circuit": float(q.get("uppercircuit", 0) or 0),
                    "lower_circuit": float(q.get("lowercircuit", 0) or 0),
                    "week_52_high":  float(q.get("52weekhigh", 0) or 0),
                    "week_52_low":   float(q.get("52weeklow",  0) or 0),
                    "net_chg":       price - prev_close,
                }
        except Exception as e:
            _log.warning("angel_fetcher.get_batch_quotes batch %d failed: %s", i // BATCH, e)
            continue

    return results


def get_market_depth(ticker: str) -> Optional[Dict]:
    """
    Get top-5 bid/ask market depth for a single ticker.
    Returns buy/sell levels + LTP + total qty + buy/sell ratio, or None.
    """
    session = _get_session()
    if session is None:
        return None

    symbol = ticker.replace(".NS", "").replace(".BO", "").upper()
    token  = _get_token(symbol, session)
    if token is None:
        return None

    try:
        resp = _http.post(
            f"{_BASE}/rest/secure/angelbroking/market/v1/quote/",
            json={"mode": "FULL", "exchangeTokens": {"NSE": [token]}},
            headers=_auth_headers(session["jwt"], session["api_key"]),
            timeout=10,
        ).json()

        fetched = (resp.get("data", {}).get("fetched") or [])
        if not fetched:
            return None

        q     = fetched[0]
        depth = q.get("depth", {})
        buys  = depth.get("buy",  []) or []
        sells = depth.get("sell", []) or []

        def _parse_levels(levels: list) -> List[Dict]:
            return [
                {
                    "price":  float(lv.get("price",    0)),
                    "qty":    int(lv.get("quantity",   0)),
                    "orders": int(lv.get("orders",     0)),
                }
                for lv in levels[:5]
            ]

        parsed_buys  = _parse_levels(buys)
        parsed_sells = _parse_levels(sells)
        total_buy    = sum(lv["qty"] for lv in parsed_buys)
        total_sell   = sum(lv["qty"] for lv in parsed_sells)

        return {
            "buys":           parsed_buys,
            "sells":          parsed_sells,
            "ltp":            float(q.get("ltp", 0)),
            "total_buy_qty":  total_buy,
            "total_sell_qty": total_sell,
            "buy_sell_ratio": (total_buy / total_sell if total_sell > 0 else None),
        }

    except Exception as e:
        _log.warning("angel_fetcher.get_market_depth(%s) failed: %s", symbol, e)
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Portfolio & Account
# ─────────────────────────────────────────────────────────────────────────────

def get_holdings() -> Optional[List[Dict]]:
    """Fetch all equity holdings in the Angel One demat account."""
    session = _get_session()
    if session is None:
        return None

    try:
        resp = _http.get(
            f"{_BASE}/rest/secure/angelbroking/portfolio/v1/getHolding",
            headers=_auth_headers(session["jwt"], session["api_key"]),
            timeout=15,
        ).json()

        raw = resp.get("data") or []
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
                "symbol":    h.get("tradingsymbol", "").replace("-EQ", ""),
                "exchange":  h.get("exchange", "NSE"),
                "isin":      h.get("isin", ""),
                "qty":       qty,
                "t1_qty":    int(h.get("t1qty", 0) or 0),
                "avg_price": round(avg, 2),
                "ltp":       round(ltp, 2),
                "pnl":       round(pnl, 2),
                "pnl_pct":   round(pnl_p, 2),
                "value_rs":  round(ltp * qty, 2),
            })

        return sorted(holdings, key=lambda x: x["value_rs"], reverse=True)

    except Exception as e:
        _log.warning("angel_fetcher.get_holdings failed: %s", e)
        return None


def get_positions() -> Optional[Dict]:
    """Fetch today's open positions (CNC day-trade and MIS intraday)."""
    session = _get_session()
    if session is None:
        return None

    try:
        resp = _http.get(
            f"{_BASE}/rest/secure/angelbroking/order/v1/getPosition",
            headers=_auth_headers(session["jwt"], session["api_key"]),
            timeout=12,
        ).json()

        raw = resp.get("data") or {}
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

    except Exception as e:
        _log.warning("angel_fetcher.get_positions failed: %s", e)
        return None


def get_funds() -> Optional[Dict]:
    """Fetch available funds and margin utilisation."""
    session = _get_session()
    if session is None:
        return None

    try:
        resp = _http.get(
            f"{_BASE}/rest/secure/angelbroking/user/v1/getRMS",
            headers=_auth_headers(session["jwt"], session["api_key"]),
            timeout=10,
        ).json()

        d = resp.get("data") or {}
        return {
            "available_cash": float(d.get("availablecash",      0) or 0),
            "used_margin":    float(d.get("utiliseddebits",      0) or 0),
            "total_margin":   float(d.get("net",                 0) or 0),
            "collateral":     float(d.get("collateral",          0) or 0),
            "m2m":            float(d.get("m2munrealisedprofit", 0) or 0),
        }

    except Exception as e:
        _log.warning("angel_fetcher.get_funds failed: %s", e)
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Order Book & Trade Book
# ─────────────────────────────────────────────────────────────────────────────

def get_order_book() -> Optional[List[Dict]]:
    """Fetch all orders placed today (open, executed, cancelled, rejected)."""
    session = _get_session()
    if session is None:
        return None

    try:
        resp = _http.get(
            f"{_BASE}/rest/secure/angelbroking/order/v1/list",
            headers=_auth_headers(session["jwt"], session["api_key"]),
            timeout=12,
        ).json()

        return [
            {
                "order_id":   o.get("orderid", ""),
                "symbol":     o.get("tradingsymbol", "").replace("-EQ", ""),
                "side":       o.get("transactiontype", ""),
                "qty":        int(o.get("quantity",    0) or 0),
                "filled_qty": int(o.get("filledshares", 0) or 0),
                "price":      float(o.get("price",        0) or 0),
                "avg_price":  float(o.get("averageprice", 0) or 0),
                "order_type": o.get("ordertype",   ""),
                "status":     o.get("status",      ""),
                "product":    o.get("producttype", ""),
                "time":       o.get("updatetime",  ""),
                "variety":    o.get("variety",     "NORMAL"),
            }
            for o in (resp.get("data") or [])
        ]

    except Exception as e:
        _log.warning("angel_fetcher.get_order_book failed: %s", e)
        return None


def get_trade_book() -> Optional[List[Dict]]:
    """Fetch all executed trades today."""
    session = _get_session()
    if session is None:
        return None

    try:
        resp = _http.get(
            f"{_BASE}/rest/secure/angelbroking/order/v1/getTradeBook",
            headers=_auth_headers(session["jwt"], session["api_key"]),
            timeout=12,
        ).json()

        return [
            {
                "order_id": t.get("orderid",  ""),
                "trade_id": t.get("tradeid",  ""),
                "symbol":   t.get("tradingsymbol", "").replace("-EQ", ""),
                "side":     t.get("transactiontype", ""),
                "qty":      int(t.get("fillsize",  0) or 0),
                "price":    float(t.get("fillprice", 0) or 0),
                "product":  t.get("producttype", ""),
                "exchange": t.get("exchange",    ""),
                "time":     t.get("filltime",    ""),
            }
            for t in (resp.get("data") or [])
        ]

    except Exception as e:
        _log.warning("angel_fetcher.get_trade_book failed: %s", e)
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Order Placement
# ─────────────────────────────────────────────────────────────────────────────

def place_order(
    symbol:        str,
    qty:           int,
    side:          str,               # "BUY" or "SELL"
    order_type:    str   = "MARKET",  # "MARKET","LIMIT","SL","SL-M"
    price:         float = 0.0,
    trigger_price: float = 0.0,
    product:       str   = "INTRADAY",  # "INTRADAY" (MIS) or "DELIVERY" (CNC)
    exchange:      str   = "NSE",
    validity:      str   = "DAY",
    variety:       str   = "NORMAL",
) -> Optional[Dict]:
    """
    Place a new order via Angel One SmartAPI.
    Returns {"order_id": str, "status": "placed"} on success or error dict on failure.
    """
    session = _get_session()
    if session is None:
        return None

    sym   = symbol.replace(".NS", "").replace(".BO", "").upper()
    token = _get_token(sym, session)
    if token is None:
        return None

    try:
        resp = _http.post(
            f"{_BASE}/rest/secure/angelbroking/order/v1/placeOrder",
            json={
                "variety":         variety,
                "tradingsymbol":   sym + "-EQ",
                "symboltoken":     token,
                "transactiontype": side.upper(),
                "exchange":        exchange,
                "ordertype":       order_type,
                "producttype":     product,
                "duration":        validity,
                "price":           str(price) if price else "0",
                "squareoff":       "0",
                "stoploss":        str(trigger_price) if trigger_price else "0",
                "quantity":        str(qty),
            },
            headers=_auth_headers(session["jwt"], session["api_key"]),
            timeout=15,
        ).json()

        if resp.get("status"):
            return {"order_id": resp.get("data", {}).get("orderid", ""), "status": "placed"}
        return {"status": "failed", "message": resp.get("message", "Unknown error")}

    except Exception as e:
        _log.warning("angel_fetcher.place_order(%s) failed: %s", sym, e)
        return {"status": "error", "message": str(e)}


def modify_order(
    order_id:      str,
    symbol:        str,
    qty:           int,
    order_type:    str,
    price:         float = 0.0,
    trigger_price: float = 0.0,
    product:       str   = "DELIVERY",   # FIX: was hardcoded "DELIVERY" — now a param
    exchange:      str   = "NSE",
    validity:      str   = "DAY",
    variety:       str   = "NORMAL",
) -> Optional[Dict]:
    """
    Modify a pending order. `product` must match the original order's product type.
    Returns {"order_id": str, "status": "modified"} or error dict.
    """
    session = _get_session()
    if session is None:
        return None

    sym   = symbol.replace(".NS", "").replace(".BO", "").upper()
    token = _get_token(sym, session)
    if token is None:
        return None

    try:
        resp = _http.post(
            f"{_BASE}/rest/secure/angelbroking/order/v1/modifyOrder",
            json={
                "variety":       variety,
                "orderid":       order_id,
                "ordertype":     order_type,
                "producttype":   product,     # now correctly uses the caller's value
                "duration":      validity,
                "price":         str(price),
                "quantity":      str(qty),
                "tradingsymbol": sym + "-EQ",
                "symboltoken":   token,
                "exchange":      exchange,
                "stoploss":      str(trigger_price) if trigger_price else "0",
                "squareoff":     "0",
            },
            headers=_auth_headers(session["jwt"], session["api_key"]),
            timeout=12,
        ).json()

        if resp.get("status"):
            return {"order_id": resp.get("data", {}).get("orderid", order_id), "status": "modified"}
        return {"status": "failed", "message": resp.get("message", "")}

    except Exception as e:
        _log.warning("angel_fetcher.modify_order(%s) failed: %s", order_id, e)
        return {"status": "error", "message": str(e)}


def cancel_order(order_id: str, variety: str = "NORMAL") -> bool:
    """Cancel a pending order. Returns True on success."""
    session = _get_session()
    if session is None:
        return False

    try:
        resp = _http.post(
            f"{_BASE}/rest/secure/angelbroking/order/v1/cancelOrder",
            json={"variety": variety, "orderid": order_id},
            headers=_auth_headers(session["jwt"], session["api_key"]),
            timeout=10,
        ).json()
        return bool(resp.get("status"))

    except Exception as e:
        _log.warning("angel_fetcher.cancel_order(%s) failed: %s", order_id, e)
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
    side:          str = "BUY",
    exchange:      str = "NSE",
    product_type:  str = "DELIVERY",
) -> Optional[Dict]:
    """Place a Good Till Triggered (GTT) order."""
    session = _get_session()
    if session is None:
        return None

    sym   = symbol.replace(".NS", "").replace(".BO", "").upper()
    token = _get_token(sym, session)
    if token is None:
        return None

    try:
        resp = _http.post(
            f"{_BASE}/rest/secure/angelbroking/gtt/v1/createRule",
            json={
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
            },
            headers=_auth_headers(session["jwt"], session["api_key"]),
            timeout=12,
        ).json()

        if resp.get("status"):
            return {"rule_id": str(resp.get("data", {}).get("id", "")), "status": "placed"}
        return {"status": "failed", "message": resp.get("message", "")}

    except Exception as e:
        _log.warning("angel_fetcher.place_gtt(%s) failed: %s", sym, e)
        return {"status": "error", "message": str(e)}


def get_gtt_list() -> Optional[List[Dict]]:
    """Get all active GTT rules in the account."""
    session = _get_session()
    if session is None:
        return None

    try:
        resp = _http.get(
            f"{_BASE}/rest/secure/angelbroking/gtt/v1/ruleList",
            headers=_auth_headers(session["jwt"], session["api_key"]),
            timeout=10,
        ).json()

        return [
            {
                "rule_id":     str(g.get("id", "")),
                "symbol":      g.get("tradingsymbol", "").replace("-EQ", ""),
                "side":        g.get("transactiontype", ""),
                "qty":         int(g.get("qty", 0) or 0),
                "trigger":     float(g.get("triggerprice", 0) or 0),
                "limit_price": float(g.get("price",        0) or 0),
                "status":      g.get("status", ""),
            }
            for g in (resp.get("data") or [])
        ]

    except Exception as e:
        _log.warning("angel_fetcher.get_gtt_list failed: %s", e)
        return None


def cancel_gtt(rule_id: str, symbol: str, exchange: str = "NSE") -> bool:
    """Cancel/delete an active GTT rule. Returns True on success."""
    session = _get_session()
    if session is None:
        return False

    sym   = symbol.replace(".NS", "").replace(".BO", "").upper()
    token = _get_token(sym, session) or ""

    try:
        resp = _http.post(
            f"{_BASE}/rest/secure/angelbroking/gtt/v1/cancelRule",
            json={
                "id":            str(rule_id),
                "tradingsymbol": sym + "-EQ",
                "symboltoken":   token,
                "exchange":      exchange,
            },
            headers=_auth_headers(session["jwt"], session["api_key"]),
            timeout=10,
        ).json()
        return bool(resp.get("status"))

    except Exception as e:
        _log.warning("angel_fetcher.cancel_gtt(%s) failed: %s", rule_id, e)
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Account Profile
# ─────────────────────────────────────────────────────────────────────────────

def get_profile() -> Optional[Dict]:
    """Get Angel One account profile."""
    session = _get_session()
    if session is None:
        return None

    try:
        resp = _http.get(
            f"{_BASE}/rest/secure/angelbroking/user/v1/getProfile",
            headers=_auth_headers(session["jwt"], session["api_key"]),
            timeout=10,
        ).json()

        d = resp.get("data") or {}
        return {
            "name":      d.get("name",       ""),
            "client_id": d.get("clientcode", ""),
            "email":     d.get("email",      ""),
            "mobile":    d.get("mobileno",   ""),
            "exchanges": d.get("exchanges",  []),
            "products":  d.get("products",   []),
            "broker":    d.get("broker",     "Angel One"),
        }

    except Exception as e:
        _log.warning("angel_fetcher.get_profile failed: %s", e)
        return None
