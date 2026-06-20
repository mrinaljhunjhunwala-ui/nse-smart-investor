"""
analysis/macro.py
Macro overlay — commodity and currency signals mapped to NSE sector tilts.

How it works
────────────
    1. Fetch 4 macro instruments from yfinance (all EOD daily bars):
           Gold (GC=F), Brent Crude (BZ=F), DXY (DX-Y.NYB), USD/INR (USDINR=X)
    2. Compute 20-day momentum (%) for each instrument
    3. Map momentum direction to a sector tilt signal (+1 overweight / -1 underweight / 0 neutral)
    4. Aggregate into a final MacroSignal dict

Sector tilt logic (NSE context)
────────────────────────────────
    Crude RISING  → ++ Energy, -- Aviation/FMCG (cost pressure)
    Crude FALLING → -- Energy, ++ FMCG/Auto (lower input cost)
    Gold  RISING  → ++ Jewellery / safe-haven sentiment, caution on growth
    DXY   RISING  → -- IT Exports ($/Rs margin compression), -- Metal
    DXY   FALLING → ++ IT Exports, ++ Metal (commodity USD-priced)
    USDINR RISING → ++ IT Exports, -- Oil importers (BPCL, IOC), -- FMCG imports
    USDINR FALLING→ -- IT Exports, ++ Energy importers

Key Functions
─────────────
    fetch_macro_data(period)            → Dict[str, pd.DataFrame]
    compute_macro_signals(period)       → Dict  (momentum + tilt per instrument)
    get_sector_tilts(period)            → Dict[sector, tilt_score]
    macro_report(period)                → full report dict (for dashboard use)
"""

from __future__ import annotations

import datetime
import json
import logging
import urllib.request
import warnings
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

_log = logging.getLogger("analysis.macro")


# ─────────────────────────────────────────────────────────────────────────────
# Macro instruments
# ─────────────────────────────────────────────────────────────────────────────

MACRO_SYMBOLS: Dict[str, str] = {
    "Gold":    "GC=F",
    "Crude":   "BZ=F",
    "DXY":     "DX-Y.NYB",
    "USDINR":  "USDINR=X",
}

# Momentum threshold: > +threshold% → RISING, < -threshold% → FALLING
_MOM_THRESHOLD = 2.0   # % over 20 days


# ─────────────────────────────────────────────────────────────────────────────
# Sector tilt rules
# Format: (instrument, direction) → {sector: tilt}
#   tilt = +1 (overweight), -1 (underweight), 0 (neutral)
# ─────────────────────────────────────────────────────────────────────────────

_TILT_RULES: List[Tuple[str, str, Dict[str, int]]] = [
    ("Crude",  "RISING",  {"Energy": +2, "Auto": -1, "FMCG": -1, "IT": 0, "Banking": -1, "Metal": 0, "Pharma": 0}),
    ("Crude",  "FALLING", {"Energy": -2, "Auto": +1, "FMCG": +1, "IT": 0, "Banking": +1, "Metal": 0, "Pharma": 0}),
    ("Gold",   "RISING",  {"Energy":  0, "Auto":  0, "FMCG":  0, "IT": 0, "Banking": -1, "Metal": +1, "Pharma": 0}),
    ("Gold",   "FALLING", {"Energy":  0, "Auto":  0, "FMCG":  0, "IT": 0, "Banking":  0, "Metal": -1, "Pharma": 0}),
    ("DXY",    "RISING",  {"Energy":  0, "Auto":  0, "FMCG":  0, "IT": -1, "Banking": 0, "Metal": -1, "Pharma": 0}),
    ("DXY",    "FALLING", {"Energy":  0, "Auto":  0, "FMCG":  0, "IT": +1, "Banking": 0, "Metal": +1, "Pharma": 0}),
    ("USDINR", "RISING",  {"Energy": -1, "Auto":  0, "FMCG": -1, "IT": +2, "Banking": 0, "Metal": 0, "Pharma": +1}),
    ("USDINR", "FALLING", {"Energy": +1, "Auto":  0, "FMCG": +1, "IT": -2, "Banking": 0, "Metal": 0, "Pharma": -1}),
]


# ─────────────────────────────────────────────────────────────────────────────
# Fetch macro data
# ─────────────────────────────────────────────────────────────────────────────

def _fetch_yahoo_macro(symbol: str, period: str = "3mo") -> pd.DataFrame:
    """
    Fetch OHLCV for a macro instrument directly from Yahoo Finance v8 chart API.
    Cloud-safe: pure urllib, no yfinance library.
    Handles futures-style symbols with '=' (e.g., GC=F, BZ=F, USDINR=X).
    """
    _RANGE_MAP = {
        "1mo": "1mo", "3mo": "3mo", "6mo": "6mo",
        "1y": "1y",   "2y": "2y",   "3y": "5y",
    }
    yf_range = _RANGE_MAP.get(period.lower(), "3mo")
    # Use cookie+crumb auth — required by Yahoo Finance since mid-2024
    try:
        from data.fetcher import _get_yf_crumb
        import urllib.parse as _up
        _opener, _crumb = _get_yf_crumb()
        _cqs = f"&crumb={_up.quote(_crumb)}" if _crumb else ""
    except Exception as e:
        _opener, _cqs = None, ""
        _log.debug("Yahoo crumb auth unavailable for %s, falling back to unauthenticated request: %s",
                   symbol, e)
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
           f"?interval=1d&range={yf_range}&includePrePost=false{_cqs}")
    req = urllib.request.Request(
        url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                      "Accept": "application/json"})
    _open_fn = _opener.open if _opener else urllib.request.urlopen
    with _open_fn(req, timeout=12) as r:
        data = json.loads(r.read())

    result = data.get("chart", {}).get("result")
    if not result:
        raise ValueError(f"Yahoo chart API error for {symbol}: {data.get('chart',{}).get('error')}")

    r0         = result[0]
    timestamps = r0.get("timestamp", [])
    quote      = r0["indicators"]["quote"][0]

    dates = [datetime.datetime.utcfromtimestamp(ts).date() for ts in timestamps]
    df = pd.DataFrame({
        "Open":   quote.get("open",   [None] * len(dates)),
        "High":   quote.get("high",   [None] * len(dates)),
        "Low":    quote.get("low",    [None] * len(dates)),
        "Close":  quote.get("close",  [None] * len(dates)),
        "Volume": quote.get("volume", [None] * len(dates)),
    }, index=pd.DatetimeIndex(dates, name="Date"))

    df = df.dropna(subset=["Close"])
    df = df[df["Close"] > 0]
    df.sort_index(inplace=True)
    return df


def fetch_macro_data(period: str = "3mo") -> Dict[str, pd.DataFrame]:
    """
    Fetch OHLCV data for all 4 macro instruments.
    Uses Yahoo Finance v8 chart API directly (no yfinance library, cloud-safe).

    Returns dict: {instrument_name: DataFrame}
    """
    result: Dict[str, pd.DataFrame] = {}
    for name, sym in MACRO_SYMBOLS.items():
        try:
            df = _fetch_yahoo_macro(sym, period=period)
            if not df.empty and len(df) >= 5:
                result[name] = df
            else:
                _log.warning("macro fetch for %s (%s) returned insufficient data (%d rows)",
                            name, sym, len(df))
        except Exception as e:
            _log.warning("macro fetch failed for %s (%s): %s: %s",
                        name, sym, type(e).__name__, e)
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Compute macro signals
# ─────────────────────────────────────────────────────────────────────────────

def compute_macro_signals(
    period:   str   = "3mo",
    mom_days: int   = 20,
    data:     Optional[Dict[str, pd.DataFrame]] = None,
) -> Dict[str, Dict]:
    """
    Compute 20-day momentum for each macro instrument and classify direction.

    Args:
        period   : yfinance period string (fetches data if `data` not supplied)
        mom_days : lookback for momentum calculation (default 20 trading days)
        data     : pre-fetched data dict (skip fetch if provided)

    Returns dict per instrument:
    {
        "Gold": {
            "price":     float,   # latest close
            "mom_pct":   float,   # 20-day momentum %
            "direction": str,     # "RISING" | "FALLING" | "FLAT"
            "chg_1d":    float,   # 1-day change %
            "chg_5d":    float,   # 5-day change %
        },
        ...
    }
    """
    if data is None:
        data = fetch_macro_data(period=period)

    signals: Dict[str, Dict] = {}

    for name, df in data.items():
        if df.empty or len(df) < mom_days + 1:
            signals[name] = {
                "price": np.nan, "mom_pct": np.nan,
                "direction": "UNKNOWN", "chg_1d": np.nan, "chg_5d": np.nan,
            }
            continue

        close = df["Close"]
        price    = float(close.iloc[-1])
        mom_pct  = float((close.iloc[-1] / close.iloc[-(mom_days + 1)] - 1) * 100)
        chg_1d   = float((close.iloc[-1] / close.iloc[-2]  - 1) * 100) if len(close) >= 2  else 0.0
        chg_5d   = float((close.iloc[-1] / close.iloc[-6]  - 1) * 100) if len(close) >= 6  else 0.0

        if mom_pct > _MOM_THRESHOLD:
            direction = "RISING"
        elif mom_pct < -_MOM_THRESHOLD:
            direction = "FALLING"
        else:
            direction = "FLAT"

        signals[name] = {
            "price":     round(price, 4) if price < 1 else round(price, 2),
            "mom_pct":   round(mom_pct, 2),
            "direction": direction,
            "chg_1d":    round(chg_1d, 2),
            "chg_5d":    round(chg_5d, 2),
        }

    return signals


# ─────────────────────────────────────────────────────────────────────────────
# Sector tilts from macro signals
# ─────────────────────────────────────────────────────────────────────────────

def get_sector_tilts(
    period: str = "3mo",
    signals: Optional[Dict[str, Dict]] = None,
) -> Dict[str, Dict]:
    """
    Compute aggregate sector tilt scores from all macro signals.

    Args:
        period  : yfinance period (used only if signals not supplied)
        signals : pre-computed macro signals dict

    Returns:
        {
            "Energy":  {"tilt": +2, "bias": "OVERWEIGHT",  "drivers": ["Crude RISING"]},
            "IT":      {"tilt": +1, "bias": "OVERWEIGHT",  "drivers": ["USDINR RISING"]},
            "Banking": {"tilt": -1, "bias": "UNDERWEIGHT", "drivers": ["Crude RISING"]},
            ...
        }
    """
    if signals is None:
        signals = compute_macro_signals(period=period)

    # Aggregate tilt scores per sector
    sector_scores: Dict[str, int]        = {}
    sector_drivers: Dict[str, List[str]] = {}

    for instrument, direction, tilts in _TILT_RULES:
        sig = signals.get(instrument, {})
        if sig.get("direction") != direction:
            continue
        for sector, tilt in tilts.items():
            if tilt == 0:
                continue
            sector_scores[sector]  = sector_scores.get(sector, 0) + tilt
            sector_drivers.setdefault(sector, [])
            sector_drivers[sector].append(f"{instrument} {direction}")

    # Build output
    result: Dict[str, Dict] = {}
    for sector, score in sector_scores.items():
        if score >= 2:
            bias = "STRONG OVERWEIGHT"
        elif score == 1:
            bias = "OVERWEIGHT"
        elif score == -1:
            bias = "UNDERWEIGHT"
        elif score <= -2:
            bias = "STRONG UNDERWEIGHT"
        else:
            bias = "NEUTRAL"
        result[sector] = {
            "tilt":    score,
            "bias":    bias,
            "drivers": sector_drivers.get(sector, []),
        }

    # Ensure all 7 sectors are represented
    for s in ["Energy", "IT", "Banking", "Auto", "FMCG", "Metal", "Pharma"]:
        if s not in result:
            result[s] = {"tilt": 0, "bias": "NEUTRAL", "drivers": []}

    return result


# ─────────────────────────────────────────────────────────────────────────────
# Full macro report
# ─────────────────────────────────────────────────────────────────────────────

def macro_report(period: str = "3mo") -> Dict:
    """
    Full macro overlay report — signals + sector tilts + summary narrative.

    Used by the dashboard Macro page and optionally by scan_tickers().

    Returns:
    {
        "signals"      : {instrument: signal_dict},
        "sector_tilts" : {sector: tilt_dict},
        "overweights"  : [str],    # sectors to overweight
        "underweights" : [str],    # sectors to underweight
        "narrative"    : str,      # plain-English summary
        "period"       : str,
    }
    """
    data    = fetch_macro_data(period=period)
    signals = compute_macro_signals(data=data)
    tilts   = get_sector_tilts(signals=signals)

    overweights  = sorted([s for s, t in tilts.items() if t["tilt"] > 0],
                          key=lambda s: -tilts[s]["tilt"])
    underweights = sorted([s for s, t in tilts.items() if t["tilt"] < 0],
                          key=lambda s:  tilts[s]["tilt"])

    # Build narrative
    lines = ["=== Macro Overlay Summary ==="]
    for name, sig in signals.items():
        dir_sym = ("↑" if sig["direction"] == "RISING"
                   else "↓" if sig["direction"] == "FALLING" else "→")
        lines.append(f"  {name:<8}: {dir_sym} {sig['mom_pct']:+.1f}% (20d) | "
                     f"Price: {sig['price']}")

    if overweights:
        lines.append(f"  Overweight  : {', '.join(overweights)}")
    if underweights:
        lines.append(f"  Underweight : {', '.join(underweights)}")
    if not overweights and not underweights:
        lines.append("  No strong macro tilts — maintain neutral sector weights.")

    return {
        "signals":      signals,
        "sector_tilts": tilts,
        "overweights":  overweights,
        "underweights": underweights,
        "narrative":    "\n".join(lines),
        "period":       period,
    }
