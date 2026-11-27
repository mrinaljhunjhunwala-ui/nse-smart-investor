"""Upstox market data (quotes + historical candles) via a read-only Analytics Token.

Completely inactive until a token is configured: ``is_configured()`` is False, no
function makes a network call and nothing is logged above DEBUG.

Token (never hard-coded, never logged):
  * Streamlit secrets ``[upstox] analytics_token = "..."``, or
  * env var ``UPSTOX_ANALYTICS_TOKEN`` (GitHub secret of the same name).
  An empty value means "not configured".

Endpoints (https://upstox.com/developer/api-documentation/):
  * Full market quote  GET https://api.upstox.com/v2/market-quote/quotes?instrument_key=k1,k2
    (max 500 keys per call)  .../get-full-market-quote/
  * Historical candles GET https://api.upstox.com/v3/historical-candle/{key}/{unit}/{interval}/{to}/{from}
    .../v3/get-historical-candle-data/
  * Instruments file   https://assets.upstox.com/market-quote/instruments/exchange/NSE.json.gz
    .../instruments/
  Auth: ``Authorization: Bearer <analytics token>``; see .../analytics-token/.

401 / 403 trip a 30-minute circuit breaker at once (an analytics token has been
reported to get 403 on some quote endpoints); five other consecutive failures trip a
5-minute one; 429 backs off 60 s. While open, every call returns None / {} at once
so callers fall through to the next tier.
"""
from __future__ import annotations

import datetime
import gzip
import json
import logging
import os
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import quote as _urlquote

import pandas as pd
import requests

_log = logging.getLogger(__name__)

SOURCE = "upstox"
_API = "https://api.upstox.com"
QUOTE_URL = f"{_API}/v2/market-quote/quotes"
CANDLE_URL = f"{_API}/v3/historical-candle"
INSTRUMENTS_URL = "https://assets.upstox.com/market-quote/instruments/exchange/NSE.json.gz"
QUOTE_BATCH = 500                      # documented max keys per quote call

_CACHE_DIR = Path(os.environ.get("UPSTOX_CACHE_DIR")
                  or Path(__file__).resolve().parent / "cache")
_INSTR_FILE = "upstox_instruments_nse.json"
_INSTR_MAX_AGE_S = 24 * 3600

# Index tickers used across the app -> Upstox index keys.
INDEX_KEYS: Dict[str, str] = {
    "^NSEI": "NSE_INDEX|Nifty 50",
    "NIFTY": "NSE_INDEX|Nifty 50",
    "NIFTY50": "NSE_INDEX|Nifty 50",
    "^NSEBANK": "NSE_INDEX|Nifty Bank",
    "BANKNIFTY": "NSE_INDEX|Nifty Bank",
    "^INDIAVIX": "NSE_INDEX|India VIX",
    "INDIAVIX": "NSE_INDEX|India VIX",
}


# ─── token ──────────────────────────────────────────────────────────────────

def _secrets_section() -> Any:
    """The [upstox] table from st.secrets: the single read point (tests blank it)."""
    import streamlit as st
    return st.secrets.get("upstox", {})


def _token() -> str:
    tok = ""
    try:
        tok = str((_secrets_section() or {}).get("analytics_token", "") or "")
    except Exception as e:         # no streamlit / no secrets file
        _log.debug("upstox: st.secrets unavailable (%s), using env", type(e).__name__)
    if not tok.strip():
        tok = os.environ.get("UPSTOX_ANALYTICS_TOKEN", "")
    return tok.strip()


def is_configured() -> bool:
    return bool(_token())


def _scrub(text: Any) -> str:
    """str(text) with the token (if any) masked, for logs and exceptions."""
    s = str(text)
    tok = _token()
    return s.replace(tok, "***") if tok else s


def _headers() -> Dict[str, str]:
    return {"Authorization": f"Bearer {_token()}", "Accept": "application/json"}


# ─── breaker + rate limit ───────────────────────────────────────────────────

_LOCK = threading.Lock()
_STATE: Dict[str, Any] = {"fails": 0, "open_until": 0.0, "reason": ""}
_FAIL_THRESHOLD = 5
_FAIL_COOLDOWN_S = 300.0
_AUTH_COOLDOWN_S = 1800.0
_RATE_COOLDOWN_S = 60.0
_MIN_GAP_S = 0.12                      # <= ~8 req/s (Upstox allows 50/s)
_PER_MIN = 250                         # Upstox allows 500/min
_CALLS: deque = deque()
_LAST_ERROR: Dict[str, str] = {"where": "", "reason": ""}


def breaker_open() -> bool:
    with _LOCK:
        if _STATE["open_until"] and time.time() < _STATE["open_until"]:
            return True
        if _STATE["open_until"]:
            _STATE.update(open_until=0.0, fails=0, reason="")
        return False


def _trip(seconds: float, reason: str) -> None:
    with _LOCK:
        _STATE["open_until"] = time.time() + seconds
        _STATE["reason"] = reason
    _log.warning("upstox: breaker OPEN for %ds: %s; falling back to the next tier",
                 int(seconds), reason)


def _record_failure(where: str, reason: str) -> None:
    _LAST_ERROR.update(where=where, reason=reason)
    _log.warning("upstox: %s failed: %s", where, reason)
    with _LOCK:
        _STATE["fails"] += 1
        n = _STATE["fails"]
    if n >= _FAIL_THRESHOLD:
        _trip(_FAIL_COOLDOWN_S, f"{n} consecutive failures (last: {where}: {reason})")


def _record_success() -> None:
    with _LOCK:
        _STATE["fails"] = 0


def last_error() -> Dict[str, str]:
    return dict(_LAST_ERROR)


def _reset_state() -> None:
    """Tests: close the breaker and clear the rate window and instrument map."""
    with _LOCK:
        _STATE.update(fails=0, open_until=0.0, reason="")
        _CALLS.clear()
    _LAST_ERROR.update(where="", reason="")
    _MAP.clear()
    _MAP_AT[0] = 0.0


def _rate_slot() -> bool:
    """Wait the per-call gap; False when the per-minute budget is spent."""
    with _LOCK:
        now = time.time()
        while _CALLS and now - _CALLS[0] > 60:
            _CALLS.popleft()
        if len(_CALLS) >= _PER_MIN:
            return False
        wait = (_CALLS[-1] + _MIN_GAP_S - now) if _CALLS else 0.0
        _CALLS.append(now + max(wait, 0.0))
    if wait > 0:
        time.sleep(wait)
    return True


def _get_json(url: str, where: str, params: Optional[dict] = None,
              timeout: float = 10) -> Optional[dict]:
    """GET with auth; None on any failure (logged, breaker updated). Never raises."""
    if not is_configured() or breaker_open():
        return None
    if not _rate_slot():
        _log.debug("upstox: per-minute budget spent, skipping %s", where)
        return None
    try:
        resp = requests.get(url, params=params, headers=_headers(), timeout=timeout)
    except Exception as e:
        _record_failure(where, f"{type(e).__name__}: {_scrub(e)[:200]}")
        return None
    status = getattr(resp, "status_code", 0) or 0
    if status in (401, 403):
        body = _scrub(getattr(resp, "text", "") or "")[:200]
        _LAST_ERROR.update(where=where, reason=f"HTTP {status}")
        _trip(_AUTH_COOLDOWN_S, f"{where} HTTP {status} (token rejected / not permitted for this "
                                f"endpoint): {body}")
        return None
    if status == 429:
        _LAST_ERROR.update(where=where, reason="HTTP 429")
        _trip(_RATE_COOLDOWN_S, f"{where} HTTP 429 rate limited")
        return None
    if status >= 400:
        _record_failure(where, f"HTTP {status}: {_scrub(getattr(resp, 'text', ''))[:200]}")
        return None
    try:
        data = resp.json()
    except Exception as e:
        _record_failure(where, f"bad JSON ({type(e).__name__})")
        return None
    if not isinstance(data, dict) or data.get("status") not in (None, "success"):
        _record_failure(where, f"status={_scrub(data.get('status') if isinstance(data, dict) else data)}")
        return None
    _record_success()
    return data


# ─── instruments: NSE symbol -> instrument key ──────────────────────────────

_MAP: Dict[str, str] = {}
_MAP_AT = [0.0]
_MAP_LOCK = threading.Lock()


def build_symbol_map(rows: List[dict]) -> Dict[str, str]:
    """{TRADING_SYMBOL: instrument_key} for NSE equities plus {NAME: key} for NSE indices."""
    out: Dict[str, str] = {}
    for r in rows or []:
        if not isinstance(r, dict):
            continue
        seg, key = r.get("segment"), r.get("instrument_key")
        if not key:
            continue
        if seg == "NSE_EQ":
            sym = str(r.get("trading_symbol") or "").upper()
            # EQ series wins over BE/SM etc. when a symbol appears twice
            if sym and (sym not in out or r.get("instrument_type") == "EQ"):
                out[sym] = key
        elif seg == "NSE_INDEX":
            for k in (r.get("trading_symbol"), r.get("name")):
                if k:
                    out.setdefault(f"IDX:{str(k).upper()}", key)
    return out


def _download_instruments() -> Optional[List[dict]]:
    try:
        resp = requests.get(INSTRUMENTS_URL, timeout=30)
        resp.raise_for_status()
        raw = resp.content
        try:
            raw = gzip.decompress(raw)
        except OSError:
            pass                                  # served already-decompressed
        rows = json.loads(raw.decode("utf-8"))
        return rows if isinstance(rows, list) else None
    except Exception as e:
        _LAST_ERROR.update(where="instruments", reason=type(e).__name__)
        _log.warning("upstox: instruments download failed: %s: %s", type(e).__name__, _scrub(e)[:200])
        return None


def _load_map() -> Dict[str, str]:
    """Symbol map, from memory, then the on-disk cache (< 1 day old), then a download."""
    now = time.time()
    if _MAP and now - _MAP_AT[0] < _INSTR_MAX_AGE_S:
        return _MAP
    with _MAP_LOCK:
        if _MAP and now - _MAP_AT[0] < _INSTR_MAX_AGE_S:
            return _MAP
        path = _CACHE_DIR / _INSTR_FILE
        cached: Dict[str, str] = {}
        try:
            if path.exists():
                cached = json.loads(path.read_text(encoding="utf-8"))
                if now - path.stat().st_mtime < _INSTR_MAX_AGE_S and cached:
                    _MAP.clear()
                    _MAP.update(cached)
                    _MAP_AT[0] = path.stat().st_mtime
                    return _MAP
        except Exception as e:
            _log.debug("upstox: instrument cache unreadable: %s", e)
        rows = _download_instruments()
        fresh = build_symbol_map(rows) if rows else {}
        if fresh:
            try:
                _CACHE_DIR.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(fresh), encoding="utf-8")
            except Exception as e:
                _log.debug("upstox: could not write instrument cache: %s", e)
            _MAP.clear()
            _MAP.update(fresh)
            _MAP_AT[0] = now
        elif cached:                              # stale cache beats nothing
            _MAP.clear()
            _MAP.update(cached)
            _MAP_AT[0] = now - _INSTR_MAX_AGE_S + 3600   # retry download in an hour
        return _MAP


def instrument_key(symbol: str) -> Optional[str]:
    """'RELIANCE' / 'RELIANCE.NS' / '^NSEI' -> Upstox instrument key, or None.
    BSE (.BO) symbols are not served."""
    s = str(symbol or "").strip().upper()
    if not s or s.endswith(".BO"):
        return None
    if s in INDEX_KEYS:
        return INDEX_KEYS[s]
    if s.startswith("^"):
        return _load_map().get(f"IDX:{s[1:]}")
    return _load_map().get(s[:-3] if s.endswith(".NS") else s)


# ─── quotes ─────────────────────────────────────────────────────────────────

_IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30))


def _as_of(v: Any) -> Optional[str]:
    """Upstox time (epoch ms number/string or ISO string) -> IST ISO string."""
    if v in (None, ""):
        return None
    try:
        ms = float(v)
        return datetime.datetime.fromtimestamp(ms / 1000, _IST).isoformat(timespec="seconds")
    except (TypeError, ValueError):
        pass
    try:
        ts = pd.Timestamp(str(v))
        ts = ts.tz_localize(_IST) if ts.tzinfo is None else ts.tz_convert(_IST)
        return ts.isoformat()
    except Exception:
        return None


def parse_quote(q: dict) -> Optional[dict]:
    """One entry of the full-quote 'data' map -> the app's quote dict, or None."""
    try:
        price = float(q.get("last_price"))
    except (TypeError, ValueError):
        return None
    if not price > 0:
        return None
    prev = None
    try:
        if q.get("net_change") is not None:
            prev = price - float(q["net_change"])
    except (TypeError, ValueError):
        prev = None
    if not prev or prev <= 0:
        try:
            prev = float((q.get("ohlc") or {}).get("close") or price)
        except (TypeError, ValueError):
            prev = price
    out = {
        "price": price,
        "prev_close": prev,
        "chg_pct": (price / prev - 1) * 100 if prev > 0 else 0.0,
        "source": SOURCE,
    }
    try:
        if q.get("volume"):
            out["volume"] = int(float(q["volume"]))
    except (TypeError, ValueError):
        pass
    ohlc = q.get("ohlc") or {}
    for k in ("high", "low"):
        try:
            if ohlc.get(k):
                out[k] = float(ohlc[k])
        except (TypeError, ValueError):
            pass
    try:
        if q.get("average_price"):
            out["vwap"] = float(q["average_price"])
    except (TypeError, ValueError):
        pass
    as_of = _as_of(q.get("last_trade_time") or q.get("timestamp"))
    if as_of:
        out["as_of"] = as_of
    return out


def get_batch_quotes(symbols: List[str]) -> Dict[str, dict]:
    """{symbol: quote} for the symbols Upstox answered (missing ones are absent).
    {} when not configured or the breaker is open. Never raises."""
    if not symbols or not is_configured() or breaker_open():
        return {}
    try:
        key_to_syms: Dict[str, List[str]] = {}
        for s in symbols:
            k = instrument_key(s)
            if k:
                key_to_syms.setdefault(k, []).append(s)
        keys = list(key_to_syms)
        out: Dict[str, dict] = {}
        for i in range(0, len(keys), QUOTE_BATCH):
            chunk = keys[i:i + QUOTE_BATCH]
            data = _get_json(QUOTE_URL, "quotes", params={"instrument_key": ",".join(chunk)})
            if data is None:
                break                              # breaker / error: rest falls through
            for entry in (data.get("data") or {}).values():
                if not isinstance(entry, dict):
                    continue
                q = parse_quote(entry)
                for s in key_to_syms.get(entry.get("instrument_token") or "", []):
                    if q:
                        out[s] = dict(q)
        if keys and not out:
            _log.debug("upstox: no quotes for %d keys", len(keys))
        return out
    except Exception as e:
        _log.warning("upstox: get_batch_quotes failed: %s: %s", type(e).__name__, _scrub(e)[:200])
        return {}


def get_live_quote(symbol: str) -> Optional[dict]:
    return get_batch_quotes([symbol]).get(symbol)


# ─── historical candles ─────────────────────────────────────────────────────

_PERIOD_DAYS = {
    "1d": 10, "5d": 18, "1m": 35, "6m": 185,
    "1mo": 35, "2mo": 65, "3mo": 95, "6mo": 185,
    "1y": 370, "2y": 740, "3y": 1100, "5y": 1830, "10y": 3650, "max": 3650,
}
# interval -> (unit, n, max span days per request)
_INTERVALS = {
    "1d": ("days", 1, 3650), "1wk": ("weeks", 1, 3650), "1mo": ("months", 1, 3650),
    "1m": ("minutes", 1, 30), "2m": ("minutes", 2, 30), "5m": ("minutes", 5, 30),
    "15m": ("minutes", 15, 30), "30m": ("minutes", 30, 90),
    "60m": ("hours", 1, 90), "1h": ("hours", 1, 90), "90m": ("minutes", 90, 90),
}


def parse_candles(payload: dict, daily: bool = True) -> pd.DataFrame:
    """v3 historical-candle JSON -> OHLCV frame on a tz-naive IST index named 'Date'."""
    candles = ((payload or {}).get("data") or {}).get("candles") or []
    if not candles:
        return pd.DataFrame()
    df = pd.DataFrame([c[:6] for c in candles],
                      columns=["Date", "Open", "High", "Low", "Close", "Volume"])
    idx = pd.to_datetime(df["Date"], utc=True).dt.tz_convert("Asia/Kolkata").dt.tz_localize(None)
    if daily:
        idx = idx.dt.normalize()
    df["Date"] = idx
    df = df.set_index("Date").sort_index()
    df = df.apply(pd.to_numeric, errors="coerce").dropna(subset=["Close"])
    df = df[~df.index.duplicated(keep="last")]
    return df


def fetch_historical(ticker: str, period: str = "1y", interval: str = "1d") -> Optional[pd.DataFrame]:
    """Candles in the shape data.fetcher's tiers return, or None. Never raises."""
    if not is_configured() or breaker_open():
        return None
    spec = _INTERVALS.get(interval)
    if spec is None:
        return None
    try:
        key = instrument_key(ticker)
        if not key:
            return None
        unit, n, max_span = spec
        today = datetime.datetime.now(_IST).date()
        if period == "ytd":
            start = datetime.date(today.year, 1, 1)
        else:
            start = today - datetime.timedelta(days=_PERIOD_DAYS.get(period, 370))
        start = max(start, today - datetime.timedelta(days=max_span))
        url = (f"{CANDLE_URL}/{_urlquote(key, safe='')}/{unit}/{n}/"
               f"{today.isoformat()}/{start.isoformat()}")
        data = _get_json(url, f"candles {ticker} {interval}", timeout=20)
        if data is None:
            return None
        df = parse_candles(data, daily=(unit in ("days", "weeks", "months")))
        return df if not df.empty else None
    except Exception as e:
        _log.warning("upstox: fetch_historical(%s) failed: %s: %s", ticker, type(e).__name__,
                     _scrub(e)[:200])
        return None


def status() -> Dict[str, Any]:
    """Token-free state for diagnostics."""
    with _LOCK:
        left = max(0.0, _STATE["open_until"] - time.time()) if _STATE["open_until"] else 0.0
        return {"configured": is_configured(), "breaker_open": left > 0,
                "breaker_seconds_left": int(left), "breaker_reason": _STATE["reason"],
                "last_error": dict(_LAST_ERROR)}
