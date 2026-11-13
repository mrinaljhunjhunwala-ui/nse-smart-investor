"""
utils/vix.py — standalone India VIX fetcher, tiered and fail-closed.

Deliberately has NO module-level imports from this project so it can never be
caught in a stale sys.modules chain. Project helpers (the NSE session, the
Yahoo crumb) are imported lazily inside the tier functions. Both
analysis.score and analysis.portfolio_manager import from here, and
trading.signals delegates here.

Tier order (first that answers wins; ``source`` records which one):
  1. NSE ``/api/allIndices`` — the "INDIA VIX" row. Uses the nseindia.com
     session + homepage cookie warm-up from ``data/nse_corp_info.py``.
  2. Yahoo ``^INDIAVIX`` v8 chart (cookie + crumb from ``data.fetcher``).
  Angel One is NOT a tier: its token map holds NSE equity (-EQ) tokens only
  and ``data.fetcher`` skips Angel for every ``^`` index symbol on purpose
  (#322; HANDOFF "Verified closed"), so there is no index quote path to use.

Fail closed: when every tier fails the result is regime "unknown",
``allow_buy=False`` and ``reason="VIX unavailable from NSE / Yahoo"`` — an
outage must not silently remove the fear filter. Consumers show
``unavailable_caption(info)`` instead of passing silently.
"""

from __future__ import annotations

import logging
import math
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

_log = logging.getLogger("vix")
_VIX_CACHE: Optional[Dict] = None
_VIX_CACHE_TTL = 600        # 10 minutes — VIX can spike intraday
_VIX_FAIL_TTL = 120         # retry an outage sooner than a good reading

NSE_ALL_INDICES_URL = "https://www.nseindia.com/api/allIndices"
_NSE_HOME = "https://www.nseindia.com/"
_NSE_VIX_ROW = "INDIA VIX"
SOURCES = ("NSE", "Yahoo")
UNAVAILABLE_REASON = "VIX unavailable from NSE / Yahoo"

# FIX DIAG-VIX (Task 2.3 follow-up C): last-diagnostic getter for
# dashboard/shared/data_health.py. Written on every fetch attempt.
_last_diagnostic: Dict[str, Any] = {}


def get_last_diagnostic() -> Dict[str, Any]:
    """Diagnostic of the most recent VIX fetch attempt.

    Shape: {"ok": bool, "at": iso, "reason": str, "warnings": int,
    "source": str | None, "attempts": [{"source", "ok", "reason"}]}.
    Empty dict if no fetch has been attempted yet this process.
    """
    return dict(_last_diagnostic)


def classify(vix: float) -> str:
    """Regime bucket for a VIX level (thresholds unchanged)."""
    if vix < 12:
        return "complacency"
    if vix < 16:
        return "normal"
    if vix < 22:
        return "elevated"
    if vix < 28:
        return "fear"
    return "panic"


def _num(v: Any) -> Optional[float]:
    """Finite float from a number or a numeric string ("1,234.5"), else None."""
    if isinstance(v, bool) or v is None:
        return None
    try:
        f = float(v.replace(",", "").strip()) if isinstance(v, str) else float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _plausible(v: Optional[float]) -> bool:
    return v is not None and 0 < v < 200


# ── Tier 1: NSE allIndices ──────────────────────────────────────────────────

def _nse_all_indices_payload(timeout: float = 10) -> Any:
    """GET /api/allIndices on the shared nseindia.com session (network)."""
    from data.nse_corp_info import _ensure_session
    session = _ensure_session()
    try:
        session.get(_NSE_HOME, timeout=timeout)          # cookie warm-up
    except Exception as e:
        _log.debug("VIX/NSE: homepage prime failed (ignoring): %s", e)
    resp = session.get(NSE_ALL_INDICES_URL, timeout=timeout)
    status = getattr(resp, "status_code", None)
    if status != 200:
        raise ValueError(f"NSE allIndices HTTP {status}")
    return resp.json()


def parse_nse_all_indices(payload: Any) -> Tuple[float, Optional[float]]:
    """(vix, pct_change) from an allIndices payload. Named ValueError on drift:
    no ``data`` list, no "INDIA VIX" row, or a non-numeric / implausible last."""
    rows = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        raise ValueError("NSE allIndices schema drift: 'data' list missing")
    row = next((r for r in rows if isinstance(r, dict)
                and str(r.get("index") or r.get("indexSymbol") or "").strip().upper() == _NSE_VIX_ROW),
               None)
    if row is None:
        raise ValueError("NSE allIndices schema drift: no 'INDIA VIX' row")
    last = _num(row.get("last"))
    if not _plausible(last):
        raise ValueError(f"NSE allIndices: INDIA VIX 'last' not a plausible number ({row.get('last')!r})")
    pct = _num(row.get("percentChange"))
    if pct is None:
        prev = _num(row.get("previousClose"))
        pct = (last / prev - 1) * 100 if _plausible(prev) else None
    return float(last), pct


def _fetch_nse() -> Tuple[float, Optional[float]]:
    return parse_nse_all_indices(_nse_all_indices_payload())


# ── Tier 2: Yahoo ^INDIAVIX ─────────────────────────────────────────────────

def _yahoo_chart_payload(timeout: float = 10) -> Any:
    """GET the ^INDIAVIX v8 chart, reusing data.fetcher's crumb (network)."""
    import json
    import urllib.parse
    import urllib.request

    # FIX YF-SESSION — reuse data.fetcher's cached cookie+crumb session; fall
    # back to an unauthenticated request if it is unavailable.
    try:
        from data.fetcher import _get_yf_crumb
        opener, crumb = _get_yf_crumb()
    except Exception as e:
        _log.debug("VIX: shared YF session unavailable, going unauthenticated: %s", e)
        opener, crumb = urllib.request.build_opener(), ""
    cqs = f"&crumb={urllib.parse.quote(crumb)}" if crumb else ""
    url = ("https://query1.finance.yahoo.com/v8/finance/chart/%5EINDIAVIX"
           f"?interval=1d&range=5d&includePrePost=false{cqs}")
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Accept": "application/json",
    })
    with opener.open(req, timeout=timeout) as r:
        return json.loads(r.read())


def parse_yahoo_chart(data: Any) -> Tuple[float, Optional[float]]:
    """(vix, pct_change) from a Yahoo v8 chart payload; named ValueError on drift."""
    chart = (data or {}).get("chart") or {}
    results = chart.get("result") or []
    if not results:
        raise ValueError(f"India VIX schema drift: chart.result missing/empty "
                         f"(chart.error={chart.get('error')!r})")
    quotes = ((results[0] or {}).get("indicators") or {}).get("quote") or []
    if not quotes:
        raise ValueError("India VIX schema drift: indicators.quote missing "
                         "(provider may have renamed the field)")
    closes = list((quotes[0] or {}).get("close") or [])
    # Yahoo leaves the latest close null for hours after the close; the price
    # is only in meta. Use it only when meta's trade time is on the last bar's
    # own IST date (same rule as data/fetcher._fill_last_daily_close).
    meta = (results[0] or {}).get("meta") or {}
    tss = (results[0] or {}).get("timestamp") or []
    if closes and closes[-1] is None and meta.get("regularMarketPrice") and tss:
        try:
            import datetime as _dt
            ist = _dt.timedelta(hours=5, minutes=30)

            def _day(ts):
                return (_dt.datetime.fromtimestamp(int(ts), tz=_dt.timezone.utc) + ist).date()
            if _day(meta.get("regularMarketTime")) == _day(tss[-1]):
                closes[-1] = float(meta["regularMarketPrice"])
        except (TypeError, ValueError, OverflowError):
            pass
    valid = [v for v in closes if v is not None]
    if len(valid) < 2:
        raise ValueError("insufficient VIX data")
    curr, prev = float(valid[-1]), float(valid[-2])
    if not _plausible(curr):
        raise ValueError(f"Yahoo ^INDIAVIX close not plausible ({curr!r})")
    return curr, ((curr / prev - 1) * 100 if prev else None)


def _fetch_yahoo() -> Tuple[float, Optional[float]]:
    return parse_yahoo_chart(_yahoo_chart_payload())


# Looked up by name at call time so tests can monkeypatch one tier.
_TIERS = (("NSE", "_fetch_nse"), ("Yahoo", "_fetch_yahoo"))


def fetch_vix_tiered() -> Dict[str, Any]:
    """Try each tier in order; never raises. Uncached (the canary calls this).

    Returns vix, regime, allow_buy, vix_pct_chg, source, reason, attempts.
    """
    attempts: List[Dict[str, Any]] = []
    for name, fn_name in _TIERS:
        try:
            curr, pct = globals()[fn_name]()
        except Exception as e:
            attempts.append({"source": name, "ok": False, "reason": f"{type(e).__name__}: {e}"})
            _log.info("India VIX: %s tier failed: %s", name, e)
            continue
        attempts.append({"source": name, "ok": True, "reason": ""})
        return {
            "vix": round(curr, 2), "regime": classify(curr),
            "allow_buy": curr <= 28,
            "vix_pct_chg": round(pct, 2) if pct is not None else 0.0,
            "source": name, "reason": "", "attempts": attempts,
        }
    _log.warning("India VIX unavailable from every source — failing closed: %s",
                 "; ".join(f"{a['source']}: {a['reason']}" for a in attempts))
    return {
        "vix": None, "regime": "unknown", "allow_buy": False, "vix_pct_chg": 0.0,
        "source": None, "reason": UNAVAILABLE_REASON, "attempts": attempts,
    }


def get_india_vix_regime() -> Dict:
    """
    India VIX and its regime, cached 10 minutes (an outage for 2 minutes).

    Returns:
        vix        : float | None
        regime     : "complacency" | "normal" | "elevated" | "fear" | "panic" | "unknown"
        allow_buy  : bool   False when VIX > 28 OR when no source answered
        vix_pct_chg: float  (1-day % change)
        source     : "NSE" | "Yahoo" | None
        reason     : "" on success, else "VIX unavailable from NSE / Yahoo"
        attempts   : per-tier [{"source", "ok", "reason"}]
    """
    global _VIX_CACHE
    if _VIX_CACHE is not None:
        ttl = _VIX_CACHE_TTL if _VIX_CACHE.get("vix") is not None else _VIX_FAIL_TTL
        if time.time() - _VIX_CACHE.get("_ts", 0) < ttl:
            return {k: v for k, v in _VIX_CACHE.items() if k != "_ts"}

    info = fetch_vix_tiered()
    ok = info["vix"] is not None
    _VIX_CACHE = {**info, "_ts": time.time()}
    _last_diagnostic.update({
        "ok": ok, "at": datetime.now().isoformat(),
        "reason": "" if ok else "; ".join(f"{a['source']}: {a['reason']}" for a in info["attempts"]),
        "source": info["source"], "attempts": info["attempts"],
        "warnings": int(_last_diagnostic.get("warnings", 0)) + (0 if ok else 1),
    })
    return {k: v for k, v in _VIX_CACHE.items() if k != "_ts"}


def is_unavailable(info: Optional[Dict]) -> bool:
    """True when a VIX dict carries no reading (fail-closed or missing)."""
    if not isinstance(info, dict):
        return True
    return info.get("vix") is None or str(info.get("regime", "unknown")).lower() == "unknown"


def unavailable_caption(info: Optional[Dict]) -> str:
    """One descriptive line for a missing VIX reading ("" when a reading exists)."""
    if not is_unavailable(info):
        return ""
    reason = info.get("reason") if isinstance(info, dict) else None
    return (f"⚪ {reason or UNAVAILABLE_REASON} — the VIX fear filter is treated as "
            "closed until a reading returns.")


def clear_vix_cache() -> None:
    """Force next call to re-fetch from network."""
    global _VIX_CACHE
    _VIX_CACHE = None
