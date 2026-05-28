"""
utils/vix.py — standalone India VIX fetcher.

Deliberately has NO imports from this project so it can never be caught
in a stale sys.modules chain.  Both analysis.score and
analysis.portfolio_manager import from here instead of trading.signals.
"""

from __future__ import annotations
from typing import Dict, Optional

_VIX_CACHE: Optional[Dict] = None


def get_india_vix_regime() -> Dict:
    """
    Fetch India VIX and classify regime.
    Cached in-process (refreshed on server restart).

    Returns:
        vix        : float | None
        regime     : "complacency" | "normal" | "elevated" | "fear" | "panic" | "unknown"
        allow_buy  : bool   (False when VIX > 28)
        vix_pct_chg: float  (1-day % change)
    """
    global _VIX_CACHE
    if _VIX_CACHE is not None:
        return _VIX_CACHE

    try:
        import yfinance as yf
        import pandas as pd

        df = yf.download("^INDIAVIX", period="5d", interval="1d",
                         auto_adjust=True, progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        if df.empty or len(df) < 2:
            raise ValueError("no VIX data")

        curr    = float(df["Close"].iloc[-1])
        prev    = float(df["Close"].iloc[-2])
        pct_chg = (curr / prev - 1) * 100

        if curr < 12:   regime = "complacency"
        elif curr < 16: regime = "normal"
        elif curr < 22: regime = "elevated"
        elif curr < 28: regime = "fear"
        else:           regime = "panic"

        _VIX_CACHE = {
            "vix":         round(curr, 2),
            "regime":      regime,
            "allow_buy":   curr <= 28,
            "vix_pct_chg": round(pct_chg, 2),
        }
    except Exception:
        _VIX_CACHE = {
            "vix": None, "regime": "unknown",
            "allow_buy": True, "vix_pct_chg": 0.0,
        }

    return _VIX_CACHE


def clear_vix_cache() -> None:
    """Force next call to re-fetch from network."""
    global _VIX_CACHE
    _VIX_CACHE = None
