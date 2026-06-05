"""
utils/vix.py — standalone India VIX fetcher.

Deliberately has NO imports from this project so it can never be caught
in a stale sys.modules chain.  Both analysis.score and
analysis.portfolio_manager import from here instead of trading.signals.

Uses direct urllib + Yahoo Finance cookie+crumb auth (required since mid-2024).
No yfinance dependency — safe on Streamlit Cloud.
"""

from __future__ import annotations
import logging
import time
from typing import Dict, Optional

_log = logging.getLogger("vix")
_VIX_CACHE: Optional[Dict] = None
_VIX_CACHE_TTL = 600   # 10 minutes — VIX can spike intraday


def get_india_vix_regime() -> Dict:
    """
    Fetch India VIX and classify regime.
    Cached for 10 minutes — refreshes intraday so panic spikes are caught.

    Returns:
        vix        : float | None
        regime     : "complacency" | "normal" | "elevated" | "fear" | "panic" | "unknown"
        allow_buy  : bool   (False when VIX > 28)
        vix_pct_chg: float  (1-day % change)
    """
    global _VIX_CACHE
    if _VIX_CACHE is not None and time.time() - _VIX_CACHE.get("_ts", 0) < _VIX_CACHE_TTL:
        return {k: v for k, v in _VIX_CACHE.items() if k != "_ts"}

    try:
        import http.cookiejar
        import json
        import urllib.parse
        import urllib.request

        # ── Step 1: build cookie-aware opener (Yahoo requires GUC/B cookies) ──
        cj     = http.cookiejar.CookieJar()
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
        _ua    = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
        opener.addheaders = [("User-Agent", _ua), ("Accept", "application/json, */*")]

        for _gate in ("https://fc.yahoo.com/", "https://finance.yahoo.com/"):
            try:
                opener.open(urllib.request.Request(
                    _gate, headers={"User-Agent": _ua}
                ), timeout=8)
                break
            except Exception as e:
                _log.debug("VIX gateway %s failed: %s", _gate, e)  # try next gateway
                continue

        # ── Step 2: get crumb token ───────────────────────────────────────────
        crumb = ""
        for _cu in (
            "https://query2.finance.yahoo.com/v1/test/getcrumb",
            "https://query1.finance.yahoo.com/v1/test/getcrumb",
        ):
            try:
                with opener.open(
                    urllib.request.Request(_cu, headers={"User-Agent": _ua}),
                    timeout=8,
                ) as _r:
                    _raw = _r.read().decode("utf-8").strip()
                    if _raw and len(_raw) <= 25 and not _raw.startswith("<"):
                        crumb = _raw
                        break
            except Exception as e:
                _log.debug("VIX crumb %s failed: %s", _cu, e)  # try next crumb endpoint
                continue

        # ── Step 3: fetch India VIX (^INDIAVIX) ──────────────────────────────
        _cqs = f"&crumb={urllib.parse.quote(crumb)}" if crumb else ""
        url  = (
            "https://query1.finance.yahoo.com/v8/finance/chart/%5EINDIAVIX"
            f"?interval=1d&range=5d&includePrePost=false{_cqs}"
        )
        req = urllib.request.Request(url, headers={
            "User-Agent": _ua,
            "Accept":     "application/json",
        })
        with opener.open(req, timeout=10) as r:
            data = json.loads(r.read())

        closes = data["chart"]["result"][0]["indicators"]["quote"][0]["close"]
        valid  = [v for v in closes if v is not None]
        if len(valid) < 2:
            raise ValueError("insufficient VIX data")

        curr    = float(valid[-1])
        prev    = float(valid[-2])
        pct_chg = (curr / prev - 1) * 100

        if   curr < 12: regime = "complacency"
        elif curr < 16: regime = "normal"
        elif curr < 22: regime = "elevated"
        elif curr < 28: regime = "fear"
        else:           regime = "panic"

        _VIX_CACHE = {
            "vix":         round(curr, 2),
            "regime":      regime,
            "allow_buy":   curr <= 28,
            "vix_pct_chg": round(pct_chg, 2),
            "_ts":         time.time(),
        }

    except Exception:
        _VIX_CACHE = {
            "vix": None, "regime": "unknown",
            "allow_buy": True, "vix_pct_chg": 0.0,
            "_ts": time.time(),
        }

    return {k: v for k, v in _VIX_CACHE.items() if k != "_ts"}


def clear_vix_cache() -> None:
    """Force next call to re-fetch from network."""
    global _VIX_CACHE
    _VIX_CACHE = None
