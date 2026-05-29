"""
data/fetcher.py
Fetches OHLCV data for NSE/BSE stocks — no yfinance library anywhere.

Source priority (fastest / most reliable first):
  Tier 0 : Angel One SmartAPI   — real-time, no rate limits, official exchange data.
            Only active when [angel_one] credentials are set in Streamlit secrets.
  Tier 1 : Stooq CSV            — free, no API key, cloud-safe (daily bars only).
  Tier 2 : Yahoo Finance v8 API — direct urllib + cookie+crumb auth (since mid-2024).

In-memory cache: each (ticker, period, interval) fetched only once per process.
"""

import http.cookiejar
import io
import time
import datetime
import urllib.parse
import urllib.request
import pandas as pd
from typing import List, Optional

# ── In-process cache  {(ticker, period, interval): DataFrame} ────────────────
_FETCH_CACHE: dict = {}

# ── Yahoo Finance session cache (cookie jar + crumb token) ───────────────────
_YF_SESSION: dict = {"opener": None, "crumb": "", "ts": 0.0}


def _get_yf_crumb():
    """
    Obtain a Yahoo Finance cookie-aware opener and a crumb token.

    Yahoo's v8 chart endpoint started requiring authentication in mid-2024:
      1. A session cookie is issued by  https://fc.yahoo.com/
      2. A crumb token is retrieved from /v1/test/getcrumb
      3. The crumb is appended as ?crumb=<token> to every chart API call.

    The session is cached for 30 minutes; a fresh crumb is fetched on expiry.
    Returns: (opener: urllib.request.OpenerDirector, crumb: str)
    """
    global _YF_SESSION
    now = time.time()
    if _YF_SESSION["opener"] is not None and now - _YF_SESSION["ts"] < 1800:
        return _YF_SESSION["opener"], _YF_SESSION["crumb"]

    cj     = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    _hdrs  = [
        ("User-Agent",      "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"),
        ("Accept",          "application/json, */*"),
        ("Accept-Language", "en-US,en;q=0.9"),
    ]
    opener.addheaders = _hdrs

    # Step 1 — consent gate (sets B / GUC cookies required for crumb)
    for _gate in ("https://fc.yahoo.com/", "https://finance.yahoo.com/"):
        try:
            opener.open(urllib.request.Request(
                _gate, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
            ), timeout=10)
            break
        except Exception:
            continue

    # Step 2 — crumb endpoint (short alpha-numeric token, ≤ 20 chars)
    crumb = ""
    for _cu in (
        "https://query2.finance.yahoo.com/v1/test/getcrumb",
        "https://query1.finance.yahoo.com/v1/test/getcrumb",
    ):
        try:
            with opener.open(urllib.request.Request(
                _cu, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
            ), timeout=10) as _r:
                _raw = _r.read().decode("utf-8").strip()
                if _raw and len(_raw) <= 25 and not _raw.startswith("<"):
                    crumb = _raw
                    break
        except Exception:
            continue

    _YF_SESSION.update({"opener": opener, "crumb": crumb, "ts": now})
    return opener, crumb

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

    try:
        df = pd.read_csv(io.StringIO(raw))
    except Exception:
        # Fallback: python engine is more lenient with malformed CSV rows
        df = pd.read_csv(io.StringIO(raw), engine="python", on_bad_lines="skip")
    df.columns = [c.strip().title() for c in df.columns]
    if "Date" not in df.columns:
        raise ValueError(f"Stooq unexpected format for {ticker}: {df.columns.tolist()}")

    df["Date"] = pd.to_datetime(df["Date"])
    df.set_index("Date", inplace=True)
    df.sort_index(inplace=True)
    df = df[["Open", "High", "Low", "Close", "Volume"]].dropna()
    df = df[df["Close"] > 0]
    return df


def _fetch_yahoo_direct(ticker: str, period: str = "1y", interval: str = "1d") -> pd.DataFrame:
    """
    Fallback: direct Yahoo Finance v8 chart API — no yfinance library, no rate limiting.
    Uses the same underlying endpoint as the yfinance library but via raw urllib,
    which avoids the HTTP 429 rate-limiting that hits the library from cloud IPs.
    Returns flat DataFrame with Open, High, Low, Close, Volume index=Date.
    """
    import json, datetime

    # Map internal period strings → Yahoo Finance API range parameter
    _RANGE_MAP = {
        "1d":  "5d",   "5d":  "5d",   "1m":  "1mo",  "6m":  "6mo",
        "ytd": "ytd",  "max": "max",
        "1mo": "1mo",  "2mo": "3mo",  "3mo": "3mo",  "6mo": "6mo",
        "1y":  "1y",   "2y":  "2y",   "3y":  "5y",   "5y":  "5y",
        # Intraday period keys (used by fetch_intraday)
        "7d":  "5d",   "15d": "1mo",  "30d": "1mo",   "60d": "60d",
    }
    yf_range = _RANGE_MAP.get(period.lower(), "1y")
    # Allow intraday intervals — Yahoo supports 5m, 15m, 30m, 60m, 1h
    _VALID_INTERVALS = {"1d", "1wk", "1mo", "5m", "15m", "30m", "60m", "1h"}
    yf_interval = interval if interval in _VALID_INTERVALS else "1d"

    # Use cookie-aware opener + crumb (required by Yahoo Finance since mid-2024)
    _opener, _crumb = _get_yf_crumb()
    _crumb_qs = f"&crumb={urllib.parse.quote(_crumb)}" if _crumb else ""

    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
           f"?interval={yf_interval}&range={yf_range}&includePrePost=false{_crumb_qs}")
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Accept":     "application/json",
    })
    try:
        with _opener.open(req, timeout=15) as r:
            data = json.loads(r.read())
    except Exception:
        # Session may have expired — reset cache and retry once with query2
        _YF_SESSION["opener"] = None
        url2 = (f"https://query2.finance.yahoo.com/v8/finance/chart/{ticker}"
                f"?interval={yf_interval}&range={yf_range}&includePrePost=false")
        req2 = urllib.request.Request(url2, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "Accept":     "application/json",
        })
        with urllib.request.urlopen(req2, timeout=15) as r:
            data = json.loads(r.read())

    result = data.get("chart", {}).get("result")
    if not result:
        err = data.get("chart", {}).get("error", {})
        raise ValueError(f"Yahoo chart API error for {ticker}: {err}")

    r0         = result[0]
    timestamps = r0.get("timestamp", [])
    quote      = r0["indicators"]["quote"][0]

    if not timestamps:
        raise ValueError(f"Yahoo chart API returned no timestamps for {ticker}")

    # Prefer adjclose when available (same as auto_adjust=True in yfinance)
    adjclose_list = (r0["indicators"].get("adjclose") or [{}])[0].get("adjclose")
    close_list    = adjclose_list if adjclose_list else quote.get("close", [])

    # For intraday intervals keep full datetime; for daily use date-only
    _intraday = yf_interval not in ("1d", "1wk", "1mo")
    if _intraday:
        # Convert UTC unix seconds → IST (UTC+5:30) datetime
        _ist_offset = datetime.timedelta(hours=5, minutes=30)
        dates = [
            datetime.datetime.utcfromtimestamp(ts) + _ist_offset
            for ts in timestamps
        ]
        idx = pd.DatetimeIndex(dates, name="Datetime")
    else:
        dates = [datetime.datetime.utcfromtimestamp(ts).date() for ts in timestamps]
        idx   = pd.DatetimeIndex(dates, name="Date")

    df = pd.DataFrame({
        "Open":   quote.get("open",   [None] * len(dates)),
        "High":   quote.get("high",   [None] * len(dates)),
        "Low":    quote.get("low",    [None] * len(dates)),
        "Close":  close_list,
        "Volume": quote.get("volume", [None] * len(dates)),
    }, index=idx)

    df = df.dropna(subset=["Close"])
    df = df[df["Close"] > 0]
    df.sort_index(inplace=True)
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
    Uses parallel fetch_single() calls — Stooq first, direct Yahoo fallback.
    No yfinance library; avoids rate-limiting from cloud IPs.
    Returns a MultiIndex DataFrame compatible with yfinance batch output.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    print(f"  Fetching {len(tickers)} ticker(s) | period={period} | interval={interval}")

    results: dict = {}

    def _one(t):
        return t, fetch_single(t, period=period, interval=interval)

    with ThreadPoolExecutor(max_workers=8) as pool:
        futs = {pool.submit(_one, t): t for t in tickers}
        for fut in as_completed(futs, timeout=60):
            try:
                t, df = fut.result(timeout=0)
                if df is not None and not df.empty:
                    results[t] = df
            except Exception:
                pass

    if not results:
        raise ValueError(f"No data returned for tickers: {tickers}")

    # Build MultiIndex DataFrame (Price × Ticker) to match yfinance batch format
    frames = []
    for t, df in results.items():
        for col in ("Open", "High", "Low", "Close", "Volume"):
            frames.append(df[[col]].rename(columns={col: (col, t)}))

    combined = pd.concat(frames, axis=1)
    combined.columns = pd.MultiIndex.from_tuples(combined.columns)
    if dropna:
        combined.dropna(how="all", inplace=True)

    print(f"  OK Fetched {len(combined)} rows × {len(results)} tickers")
    return combined


def fetch_single(ticker: str, period: str = "2y", interval: str = "1d") -> pd.DataFrame:
    """
    Fetch OHLCV for one ticker.
    Priority: Angel One (Tier 0) → Stooq (Tier 1) → Yahoo Finance (Tier 2).
    Results are cached in-process — repeated calls return the cached copy.
    """
    cache_key = (ticker, period, interval)
    if cache_key in _FETCH_CACHE:
        return _FETCH_CACHE[cache_key].copy()

    df = None
    last_err = ""

    # ── Tier 0: Angel One SmartAPI (only if credentials configured) ───────────
    try:
        from data.angel_fetcher import fetch_historical as _ao_fetch, is_configured as _ao_ok
        if _ao_ok():
            df = _ao_fetch(ticker, period=period, interval=interval)
            if df is not None and not df.empty:
                print(f"  [AngelOne] {ticker}: {len(df)} rows")
    except Exception as _e:
        last_err = str(_e)

    # ── Tier 1: Stooq CSV (daily bars only — no intraday support) ────────────
    if (df is None or df.empty) and interval == "1d":
        try:
            df = _fetch_stooq(ticker, period=period)
            print(f"  [Stooq] {ticker}: {len(df)} rows")
        except Exception as e:
            last_err = str(e)
            print(f"  [Stooq] {ticker} failed: {e} — trying Yahoo…")
    elif df is None or df.empty:
        print(f"  [intraday {interval}] {ticker} — skipping Stooq (daily-only)")

    # ── Tier 2: Yahoo Finance v8 chart API (cookie+crumb auth) ───────────────
    if df is None or df.empty:
        try:
            df = _fetch_yahoo_direct(ticker, period=period, interval=interval)
            print(f"  [Yahoo] {ticker}: {len(df)} rows")
        except Exception as e:
            last_err = str(e)
            print(f"  [Yahoo] {ticker} failed: {e}")

    if df is None or df.empty:
        raise ValueError(f"No data for {ticker}. All sources failed: {last_err}")

    _FETCH_CACHE[cache_key] = df
    return df.copy()


def fetch_intraday(
    ticker:   str,
    interval: str = "5m",
    days:     int = 5,
) -> pd.DataFrame:
    """
    Fetch intraday OHLCV bars for a single NSE ticker.

    Yahoo Finance intraday limits (free API):
        5m  bars → last 5  trading days max
        15m bars → last 60 trading days max
        30m bars → last 60 trading days max
        60m bars → last 730 trading days max

    Args:
        ticker   : yfinance symbol (e.g. 'RELIANCE.NS')
        interval : '5m' | '15m' | '30m' | '60m'  (default '5m')
        days     : how many trading days of data to request

    Returns:
        DataFrame with IST datetime index, columns: Open, High, Low, Close, Volume
        Only market hours rows (09:15–15:30 IST) are returned.

    Raises:
        ValueError if no data returned.
    """
    _MAX_DAYS = {"5m": 5, "15m": 60, "30m": 60, "60m": 730, "1h": 730}
    if interval not in _MAX_DAYS:
        raise ValueError(f"interval must be one of {list(_MAX_DAYS)} — got '{interval}'")

    # Cap days to Yahoo's limit for the chosen interval
    cap = _MAX_DAYS[interval]
    days = min(days, cap)

    # Map days → period string understood by _fetch_yahoo_direct / _RANGE_MAP
    if days <= 5:
        period = "5d"
    elif days <= 15:
        period = "7d"
    elif days <= 30:
        period = "15d"
    else:
        period = "60d"

    df = fetch_single(ticker, period=period, interval=interval)

    # Filter to NSE market hours 09:15 – 15:30 IST
    try:
        times = df.index.time
        import datetime as _dt
        mkt_open  = _dt.time(9, 15)
        mkt_close = _dt.time(15, 30)
        df = df[(times >= mkt_open) & (times <= mkt_close)]
    except Exception:
        pass   # index may already be date-only on fallback

    return df


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
