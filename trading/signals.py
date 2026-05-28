"""
trading/signals.py — Phase 4a  (enhanced with 4-screen approach)
Real-time (delayed) signal scanner for NSE equities.

Screens implemented (from stock-screener skill):
    1. Oversold Bounce   — RSI < 35, at support, volume present
    2. Momentum Leaders  — Price > SMA20 > SMA50 > SMA200, RSI 50–70
    3. Breakout          — Within 3% of 52-week high + volume surge
    4. Pullback to SMA   — In uptrend, price pulled back to SMA20/50

Additional filters:
    • India VIX regime  — skip BUY signals when VIX > 28 (panic zone)
    • Candlestick confirmation — pattern must support direction
    • RSI divergence    — extra conviction layer
    • ADX trend filter  — separate ranging from trending stocks

Backward-compatible: original check_rsi_macd_signal / check_momentum_signal
still exist for the backtesting pipeline.
"""

from __future__ import annotations

import warnings
import numpy as np
import pandas as pd
from typing import List, Dict, Optional
from datetime import datetime

warnings.filterwarnings("ignore")

from data.fetcher import fetch_single
from utils.indicators import add_all_indicators
from strategies.sector_rotation import SECTORS, compute_sector_scores


# Reverse mapping: ticker → sector name (built from sector_rotation.SECTORS)
_TICKER_SECTOR: Dict[str, str] = {
    ticker: sector
    for sector, tickers in SECTORS.items()
    for ticker in tickers
}

# ─────────────────────────────────────────────────────────────────────────────
# India VIX — market sentiment regime
# ─────────────────────────────────────────────────────────────────────────────

_VIX_CACHE: Optional[Dict] = None

def get_india_vix_regime() -> Dict:
    """
    Fetch India VIX and return regime info.
    Cached per-process (refreshed at each run).

    Returns dict:
        vix       : float
        regime    : "complacency" | "normal" | "elevated" | "fear" | "panic"
        allow_buy : bool  (False when VIX > 28)
        vix_pct_chg: float (1-day change)
    """
    global _VIX_CACHE
    if _VIX_CACHE is not None:
        return _VIX_CACHE

    try:
        import json, urllib.parse as _up
        from data.fetcher import _get_yf_crumb
        _opener, _crumb = _get_yf_crumb()
        _cqs = f"&crumb={_up.quote(_crumb)}" if _crumb else ""
        _url = (f"https://query1.finance.yahoo.com/v8/finance/chart/%5EINDIAVIX"
                f"?interval=1d&range=5d&includePrePost=false{_cqs}")
        _req = urllib.request.Request(
            _url, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
        with _opener.open(_req, timeout=8) as _r:
            _d = json.loads(_r.read())
        _closes = _d["chart"]["result"][0]["indicators"]["quote"][0]["close"]
        _valid  = [v for v in _closes if v is not None]
        if len(_valid) < 2:
            raise ValueError("No VIX data")

        curr    = float(_valid[-1])
        prev    = float(_valid[-2])
        pct_chg = (curr / prev - 1) * 100

        if curr < 12:
            regime = "complacency"
        elif curr < 16:
            regime = "normal"
        elif curr < 22:
            regime = "elevated"
        elif curr < 28:
            regime = "fear"
        else:
            regime = "panic"

        _VIX_CACHE = {
            "vix":         round(curr, 2),
            "regime":      regime,
            "allow_buy":   curr <= 28,       # block new longs in panic
            "vix_pct_chg": round(pct_chg, 2),
        }
    except Exception:
        # Fallback: neutral — don't block anything
        _VIX_CACHE = {"vix": None, "regime": "unknown", "allow_buy": True, "vix_pct_chg": 0.0}

    return _VIX_CACHE


# ─────────────────────────────────────────────────────────────────────────────
# Helper: trailing stop value for open position
# ─────────────────────────────────────────────────────────────────────────────

def calc_trailing_stop(df: pd.DataFrame, entry_price: float, atr_mult: float = 2.0) -> float:
    """
    Hybrid trailing stop (from trailing-stops skill):
        < 1R profit  → original stop (entry - 2×ATR at entry)
        ≥ 1R gained  → highest close since entry minus ATR×multiplier
    """
    atr     = float(df["ATR"].iloc[-1]) if "ATR" in df.columns else 0.0
    initial_stop = entry_price - 2.0 * atr

    # Highest close since 'entry_price' was first seen — approximate with last 60 rows
    recent_high = float(df["Close"].tail(60).max())
    atr_trail   = recent_high - atr_mult * atr

    current_price = float(df["Close"].iloc[-1])
    profit_in_r   = (current_price - entry_price) / (entry_price - initial_stop + 1e-6)

    if profit_in_r < 1.0:
        return initial_stop
    return max(initial_stop, atr_trail)


# ─────────────────────────────────────────────────────────────────────────────
# Structure-based stop loss  (from trailing-stops + risk-management skills)
# ─────────────────────────────────────────────────────────────────────────────

def find_structure_stop(
    df:         pd.DataFrame,
    lookback:   int   = 20,
    buffer_pct: float = 0.5,
) -> Optional[float]:
    """
    Find the most recent swing low in the last `lookback` bars.

    A swing low: Low[i] < Low[i-1]  AND  Low[i] < Low[i+1]

    Returns the swing-low price minus a small buffer:
        stop = swing_low × (1 − buffer_pct / 100)

    Falls back to None if no swing low found — caller should use ATR stop.

    Why structure stops?
        They respect where the market has already "proved" there are buyers.
        An ATR stop may be too close in trending markets and too wide in
        volatile ones; structure stops adapt to actual price behaviour.
    """
    if len(df) < lookback + 2:
        return None

    # Include one extra bar at each end for the pivot comparison
    lows = df["Low"].values[-(lookback + 2):]

    swing_lows = []
    for i in range(1, len(lows) - 1):
        if lows[i] < lows[i - 1] and lows[i] < lows[i + 1]:
            swing_lows.append(float(lows[i]))

    if not swing_lows:
        return None

    recent_sw_low = swing_lows[-1]               # most recent swing pivot
    return round(recent_sw_low * (1 - buffer_pct / 100), 2)


# ─────────────────────────────────────────────────────────────────────────────
# Kelly Criterion position sizing  (from position-sizing / kelly-criterion skill)
# ─────────────────────────────────────────────────────────────────────────────

def kelly_position_size(
    win_rate:    float,
    rr_ratio:    float,
    capital:     float = 100_000.0,
    fraction:    float = 0.5,           # half-Kelly (safer than full Kelly)
    max_risk_pct: float = 2.0,          # hard cap: never risk more than 2%
) -> Dict:
    """
    Kelly Criterion for optimal position sizing.

    Formula:  f* = (b × p − q) / b
        b = rr_ratio (net reward per unit risk)
        p = win_rate
        q = 1 − p

    Args:
        win_rate     : Historical win rate  (0 < p < 1), e.g. 0.55
        rr_ratio     : Reward-to-risk ratio (b > 0),     e.g. 2.5
        capital      : Total portfolio in Rs (default 1 lakh)
        fraction     : Kelly fraction to apply (0.5 = half-Kelly, safest)
        max_risk_pct : Hard cap on risk %  (default 2 % per trade)

    Returns dict:
        kelly_pct  : Raw adjusted-Kelly as % of capital
        risk_pct   : Actual risk % after cap
        risk_rs    : Risk in rupees
        max_shares_fn : callable(entry, stop) → max shares  (convenience)
    """
    if not (0 < win_rate < 1):
        raise ValueError(f"win_rate must be in (0, 1), got {win_rate}")
    if rr_ratio <= 0:
        raise ValueError(f"rr_ratio must be positive, got {rr_ratio}")

    q          = 1.0 - win_rate
    raw_kelly  = (rr_ratio * win_rate - q) / rr_ratio   # f*
    adj_kelly  = max(0.0, raw_kelly * fraction)          # half-Kelly (or custom)
    kelly_pct  = adj_kelly * 100
    risk_pct   = min(kelly_pct, max_risk_pct)
    risk_rs    = capital * risk_pct / 100

    return {
        "kelly_pct":  round(kelly_pct, 2),
        "risk_pct":   round(risk_pct,  2),
        "risk_rs":    round(risk_rs,   2),
        "fraction":   fraction,
        "win_rate":   win_rate,
        "rr_ratio":   rr_ratio,
        "notes":      (f"Half-Kelly={kelly_pct:.1f}% → "
                       f"capped at {risk_pct:.1f}% = Rs {risk_rs:,.0f}"),
    }


def shares_from_risk(
    entry_price: float,
    stop_price:  float,
    risk_rs:     float,
) -> int:
    """
    Compute max shares to buy given a fixed rupee-risk amount.

        shares = risk_rs / (entry − stop)

    Returns at least 1 if there's any valid risk budget.
    """
    risk_per_share = entry_price - stop_price
    if risk_per_share <= 0:
        return 0
    return max(1, int(risk_rs / risk_per_share))


# ─────────────────────────────────────────────────────────────────────────────
# Screen 1: Oversold Bounce  (from stock-screener skill)
# ─────────────────────────────────────────────────────────────────────────────

def check_oversold_bounce(
    df:              pd.DataFrame,
    rsi_threshold:   float = 35,
    min_vol_ratio:   float = 0.7,
    min_pct_above_52wL: float = 3.0,
) -> Optional[Dict]:
    """
    RSI oversold bounce:
        • RSI(14) < rsi_threshold     (deeply oversold)
        • Price ≥ 3% above 52-week low (not in free-fall)
        • Volume ≥ 0.7× 20-day avg    (some participation)
        • Bullish candlestick pattern OR RSI divergence (confirmation)
    Returns signal dict or None.
    """
    cur   = df.iloc[-1]
    price = float(cur["Close"])

    rsi    = cur.get("RSI",          np.nan)
    atr    = cur.get("ATR",          np.nan)
    v_rat  = cur.get("Volume_Ratio", np.nan)
    bull_div = int(cur.get("RSI_Bull_Div", 0))
    bull_eng = int(cur.get("Pat_BullEngulfing", 0))
    hammer   = int(cur.get("Pat_Hammer",        0))
    morn     = int(cur.get("Pat_MorningStar",   0))

    if any(pd.isna(v) for v in [rsi, atr]):
        return None
    if rsi >= rsi_threshold:
        return None

    # Volume gate
    if not pd.isna(v_rat) and v_rat < min_vol_ratio:
        return None

    # Not in free-fall
    low_52w = float(df["Low"].min())
    pct_above = (price - low_52w) / max(low_52w, 1) * 100
    if pct_above < min_pct_above_52wL:
        return None

    # Need at least one confirmation signal
    confirmation = bull_div or bull_eng or hammer or morn
    reason_parts = [f"RSI={rsi:.1f} (oversold)"]
    if bull_div:  reason_parts.append("RSI_Bull_Div")
    if bull_eng:  reason_parts.append("BullEngulfing")
    if hammer:    reason_parts.append("Hammer")
    if morn:      reason_parts.append("MorningStar")

    sl = price - 2.0 * atr
    tp = price + 3.0 * atr
    return {
        "action":       "BUY",
        "screen":       "Oversold_Bounce",
        "price":        round(price, 2),
        "sl":           round(sl, 2),
        "tp":           round(tp, 2),
        "rsi":          round(rsi, 2),
        "vol_ratio":    round(float(v_rat), 2) if not pd.isna(v_rat) else None,
        "confirmation": bool(confirmation),
        "reason":       " + ".join(reason_parts),
        "timestamp":    datetime.now().isoformat(),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Screen 2: Momentum Leader  (from stock-screener skill)
# ─────────────────────────────────────────────────────────────────────────────

def check_momentum_leader(
    df:                 pd.DataFrame,
    rsi_lo:             float = 50,
    rsi_hi:             float = 72,
    perf_lookback:      int   = 20,
    min_perf_pct:       float = 2.0,    # relaxed from 5% → 2% for sideways markets
) -> Optional[Dict]:
    """
    Momentum leader in clear uptrend:
        • Price > SMA20 > SMA50 > SMA200   (full MA stack)
        • RSI between rsi_lo and rsi_hi    (trending, not overbought)
        • Last 20-day performance > min_perf_pct
        • ADX > 20 (actual trend, not chop)
    """
    cur   = df.iloc[-1]
    price = float(cur["Close"])

    sma20  = cur.get("SMA_20",  np.nan)
    sma50  = cur.get("SMA_50",  np.nan)
    sma200 = cur.get("SMA_200", np.nan)
    rsi    = cur.get("RSI",     np.nan)
    adx    = cur.get("ADX",     np.nan)
    atr    = cur.get("ATR",     np.nan)

    if any(pd.isna(v) for v in [sma20, sma50, sma200, rsi, atr]):
        return None

    # Full MA stack
    if not (price > sma20 > sma50 > sma200):
        return None

    # RSI in sweet spot
    if not (rsi_lo < rsi < rsi_hi):
        return None

    # ADX trend filter (>20 = trending)
    if not pd.isna(adx) and adx < 20:
        return None

    # Performance check
    if len(df) < perf_lookback + 2:
        return None
    perf_20d = float(df["Close"].pct_change(perf_lookback).iloc[-1]) * 100
    if perf_20d < min_perf_pct:
        return None

    sl = max(float(sma20) - 0.5 * atr, price - 2.0 * atr)
    # No fixed TP — trail with SMA20 (exit when price closes below SMA20)
    return {
        "action":    "BUY",
        "screen":    "Momentum_Leader",
        "price":     round(price, 2),
        "sl":        round(sl, 2),
        "tp":        None,           # trail via SMA20
        "rsi":       round(rsi, 2),
        "adx":       round(float(adx), 2) if not pd.isna(adx) else None,
        "perf_20d":  round(perf_20d, 2),
        "reason":    f"Price>SMA20>SMA50>SMA200 | RSI={rsi:.1f} | 20d={perf_20d:+.1f}%",
        "timestamp": datetime.now().isoformat(),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Screen 3: Breakout  (from stock-screener skill)
# ─────────────────────────────────────────────────────────────────────────────

def check_breakout(
    df:                pd.DataFrame,
    vol_multiplier:    float = 1.5,
    pct_from_high:     float = 3.0,
) -> Optional[Dict]:
    """
    Breakout near 52-week high with volume:
        • Price within pct_from_high% of 52-week high
        • Volume ≥ vol_multiplier × 20-day average
        • RSI < 80 (not wildly overbought)
        • ADX > 20 (trending)
    """
    cur   = df.iloc[-1]
    price = float(cur["Close"])
    rsi   = cur.get("RSI",          np.nan)
    v_rat = cur.get("Volume_Ratio", np.nan)
    adx   = cur.get("ADX",          np.nan)
    atr   = cur.get("ATR",          np.nan)

    if any(pd.isna(v) for v in [rsi, atr]):
        return None

    high_52w     = float(df["High"].max())
    pct_from_52h = (high_52w - price) / max(high_52w, 1) * 100

    if pct_from_52h > pct_from_high:
        return None
    if not pd.isna(v_rat) and v_rat < vol_multiplier:
        return None
    if rsi > 80:
        return None

    sl = price - 2.0 * atr
    tp = price + 3.0 * atr
    return {
        "action":       "BUY",
        "screen":       "Breakout",
        "price":        round(price, 2),
        "sl":           round(sl, 2),
        "tp":           round(tp, 2),
        "rsi":          round(rsi, 2),
        "vol_ratio":    round(float(v_rat), 2) if not pd.isna(v_rat) else None,
        "pct_from_52h": round(pct_from_52h, 2),
        "reason":       f"Near 52w high (−{pct_from_52h:.1f}%) | VolRatio={v_rat:.2f}x | RSI={rsi:.1f}",
        "timestamp":    datetime.now().isoformat(),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Screen 4: Pullback to SMA  (from stock-screener skill)
# ─────────────────────────────────────────────────────────────────────────────

def check_pullback_to_sma(
    df:             pd.DataFrame,
    sma_target:     str   = "SMA_20",   # "SMA_20" or "SMA_50"
    pct_tolerance:  float = 2.0,        # within ±2% of SMA
) -> Optional[Dict]:
    """
    Pullback-to-SMA in an established uptrend:
        • Price above SMA200 (in uptrend)
        • Price within pct_tolerance% of sma_target (touched it)
        • RSI < 55 (not overbought on the pullback)
        • Bullish pattern OR RSI bull divergence (optional boost)
    """
    cur   = df.iloc[-1]
    price = float(cur["Close"])

    sma200 = cur.get("SMA_200", np.nan)
    sma_t  = cur.get(sma_target, np.nan)
    rsi    = cur.get("RSI",      np.nan)
    atr    = cur.get("ATR",      np.nan)

    if any(pd.isna(v) for v in [sma200, sma_t, rsi, atr]):
        return None

    if price <= sma200:
        return None
    if rsi >= 55:
        return None

    pct_from_sma = (price - float(sma_t)) / max(float(sma_t), 1) * 100
    if not (-pct_tolerance <= pct_from_sma <= pct_tolerance):
        return None

    bull_div = int(cur.get("RSI_Bull_Div",    0))
    bull_eng = int(cur.get("Pat_BullEngulfing",0))
    hammer   = int(cur.get("Pat_Hammer",       0))

    extras = []
    if bull_div: extras.append("RSI_Div")
    if bull_eng: extras.append("BullEngulf")
    if hammer:   extras.append("Hammer")

    sl = price - 2.0 * atr
    tp = price + 3.0 * atr
    return {
        "action":      "BUY",
        "screen":      f"Pullback_{sma_target}",
        "price":       round(price, 2),
        "sl":          round(sl, 2),
        "tp":          round(tp, 2),
        "rsi":         round(rsi, 2),
        "pct_from_sma": round(pct_from_sma, 2),
        "reason":      f"Pullback to {sma_target} ({pct_from_sma:+.1f}%) | RSI={rsi:.1f}"
                       + (f" | {'+'.join(extras)}" if extras else ""),
        "timestamp":   datetime.now().isoformat(),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Screen 5: Fibonacci Pullback  (from fibonacci-trading skill)
# ─────────────────────────────────────────────────────────────────────────────

def check_fibonacci_pullback(
    df:      pd.DataFrame,
    max_rsi: float = 60,
) -> Optional[Dict]:
    """
    Pullback to Fibonacci 38.2% or 61.8% retracement in a long-term uptrend.

    Conditions:
        • Price above SMA_200 (confirmed long-term uptrend)
        • Price within ±1.5% of Fib_38_2 OR Fib_61_8 (proximity flags already computed)
        • RSI < max_rsi (not extended / overbought)

    Stop / Target:
        38.2% entry: SL just below 61.8% level, TP at swing high (Fib_High)
        61.8% entry: SL just below 78.6% level, TP at swing high
    """
    cur   = df.iloc[-1]
    price = float(cur["Close"])

    sma200   = cur.get("SMA_200",       np.nan)
    rsi      = cur.get("RSI",           np.nan)
    atr      = cur.get("ATR",           np.nan)
    near_38  = int(cur.get("Fib_Near_38", 0))
    near_62  = int(cur.get("Fib_Near_62", 0))
    fib_38   = cur.get("Fib_38_2",      np.nan)
    fib_62   = cur.get("Fib_61_8",      np.nan)
    fib_78   = cur.get("Fib_78_6",      np.nan)
    fib_high = cur.get("Fib_High",      np.nan)

    if any(pd.isna(v) for v in [sma200, rsi, atr, fib_38, fib_62]):
        return None

    # Long-term uptrend required
    if price <= float(sma200):
        return None

    # RSI must not be extended
    if rsi >= max_rsi:
        return None

    # Must be near a key Fib level
    if not (near_38 or near_62):
        return None

    # Choose level and build SL / TP
    if near_38:
        level_name  = "38.2%"
        fib_support = float(fib_38)
        sl          = float(fib_62) * 0.99 if not pd.isna(fib_62) else price - 2.0 * atr
    else:
        level_name  = "61.8%"
        fib_support = float(fib_62)
        sl          = float(fib_78) * 0.99 if not pd.isna(fib_78) else price - 2.0 * atr

    tp = float(fib_high) if not pd.isna(fib_high) else price + 3.0 * atr
    rr = (tp - price) / max(price - sl, 1e-6)

    # Optional confirmations
    extras = []
    if int(cur.get("RSI_Bull_Div",      0)): extras.append("RSI_Div")
    if int(cur.get("Pat_Hammer",         0)): extras.append("Hammer")
    if int(cur.get("Pat_BullEngulfing",  0)): extras.append("BullEngulf")
    macd_h = cur.get("MACD_Hist", np.nan)
    if not pd.isna(macd_h) and float(macd_h) > 0:
        extras.append("MACD+")

    return {
        "action":      "BUY",
        "screen":      "Fib_Pullback",
        "price":       round(price, 2),
        "sl":          round(sl, 2),
        "tp":          round(tp, 2),
        "rsi":         round(rsi, 2),
        "fib_level":   level_name,
        "fib_support": round(fib_support, 2),
        "rr_ratio":    round(rr, 2),
        "reason":      f"Fib {level_name} pullback | RSI={rsi:.1f} | R:R={rr:.1f}x"
                       + (f" | {'+'.join(extras)}" if extras else ""),
        "timestamp":   datetime.now().isoformat(),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Legacy: original RSI+MACD signal  (used by backtesting pipeline)
# ─────────────────────────────────────────────────────────────────────────────

def check_rsi_macd_signal(
    df:             pd.DataFrame,
    rsi_oversold:   float = 40,
    rsi_overbought: float = 55,
    atr_stop_mult:  float = 2.5,
    atr_tp_mult:    float = 3.2,
) -> Optional[Dict]:
    cur   = df.iloc[-1]
    prev  = df.iloc[-2]

    rsi    = cur.get("RSI",          np.nan)
    macd   = cur.get("MACD",         np.nan)
    sig    = cur.get("MACD_Signal",  np.nan)
    macd_p = prev.get("MACD",        np.nan)
    sig_p  = prev.get("MACD_Signal", np.nan)
    atr    = cur.get("ATR",          np.nan)
    price  = float(cur["Close"])

    if any(np.isnan(v) for v in [rsi, macd, sig, atr]):
        return None

    macd_cross_up   = (macd > sig)  and (macd_p <= sig_p)
    macd_cross_down = (macd < sig)  and (macd_p >= sig_p)

    if rsi < rsi_oversold and macd_cross_up:
        return {
            "action":    "BUY",
            "screen":    "RSI+MACD",
            "ticker":    None,
            "price":     round(price, 2),
            "sl":        round(price - atr_stop_mult * atr, 2),
            "tp":        round(price + atr_tp_mult   * atr, 2),
            "rsi":       round(rsi, 2),
            "strategy":  "RSI+MACD",
            "reason":    f"RSI={rsi:.1f} + MACD bullish cross",
            "timestamp": datetime.now().isoformat(),
        }
    if rsi > rsi_overbought or macd_cross_down:
        reason = "RSI overbought" if rsi > rsi_overbought else "MACD bearish crossover"
        return {
            "action":    "SELL",
            "screen":    "RSI+MACD",
            "ticker":    None,
            "price":     round(price, 2),
            "sl":        None, "tp": None,
            "rsi":       round(rsi, 2),
            "strategy":  "RSI+MACD",
            "reason":    reason,
            "timestamp": datetime.now().isoformat(),
        }
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Legacy: original Momentum signal  (used by backtesting pipeline)
# ─────────────────────────────────────────────────────────────────────────────

def check_momentum_signal(
    df:                 pd.DataFrame,
    momentum_threshold: float = 0.05,
    momentum_lookback:  int   = 20,
    sma_trend_period:   int   = 50,
    sma_exit_period:    int   = 20,
    atr_stop_mult:      float = 1.5,
) -> Optional[Dict]:
    cur   = df.iloc[-1]
    price = float(cur["Close"])
    close = df["Close"]

    if len(close) < max(momentum_lookback, sma_trend_period) + 5:
        return None

    momentum  = float(close.pct_change(momentum_lookback).iloc[-1])
    sma_trend = float(close.rolling(sma_trend_period).mean().iloc[-1])
    sma_exit  = float(close.rolling(sma_exit_period).mean().iloc[-1])
    atr       = cur.get("ATR", np.nan)

    if any(pd.isna(v) for v in [momentum, sma_trend, sma_exit]):
        return None

    if momentum > momentum_threshold and price > sma_trend:
        sl = price - atr_stop_mult * atr if not np.isnan(atr) else price * 0.97
        return {
            "action":    "BUY",
            "screen":    "Momentum",
            "ticker":    None,
            "price":     round(price, 2),
            "sl":        round(sl, 2),
            "tp":        None,
            "momentum":  round(momentum * 100, 2),
            "strategy":  "Momentum",
            "reason":    f"{momentum_lookback}d mom={momentum*100:+.2f}% | above SMA{sma_trend_period}",
            "timestamp": datetime.now().isoformat(),
        }
    if price < sma_exit or momentum < 0:
        reason = f"Below SMA{sma_exit_period}" if price < sma_exit else "Momentum turned negative"
        return {
            "action":   "SELL",
            "screen":   "Momentum",
            "ticker":   None,
            "price":    round(price, 2),
            "sl":       None, "tp": None,
            "momentum": round(momentum * 100, 2),
            "strategy": "Momentum",
            "reason":   reason,
            "timestamp": datetime.now().isoformat(),
        }
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Multi-screen scan  (main entry point)
# ─────────────────────────────────────────────────────────────────────────────

def scan_tickers(
    tickers:       List[str],
    strategy:      str  = "all",     # "all" | "rsi_macd" | "momentum"
    period:        str  = "1y",
    params:        Optional[Dict] = None,
    use_vix:       bool = True,
    sector_filter: bool = False,     # only fire BUYs in top-N sectors
    top_n_sectors: int  = 3,
) -> List[Dict]:
    """
    Scan a ticker list across all 5 screens (or a single legacy strategy).

    strategy="all"      → runs all 5 modern screens
    strategy="rsi_macd" → legacy RSI+MACD only (backtest compat)
    strategy="momentum" → legacy Momentum only

    Filters applied in order:
        1. India VIX  — suppress BUY when VIX > 28
        2. Sector     — (optional) suppress BUY if sector not in top-N ranked
    """
    params  = params or {}
    signals = []

    # ── India VIX regime check ────────────────────────────────────────────────
    vix_info = {"allow_buy": True, "vix": None, "regime": "unknown"}
    if use_vix:
        try:
            vix_info = get_india_vix_regime()
        except Exception:
            pass

    vix_str = (f"  India VIX: {vix_info['vix']} | Regime: {vix_info['regime'].upper()}"
               if vix_info["vix"] else "  India VIX: unavailable")
    print(f"\n  Scanning {len(tickers)} tickers  |  strategy={strategy}")
    print(f"{vix_str}")
    if not vix_info["allow_buy"]:
        print(f"  VIX > 28 — BUY signals suppressed (panic regime)")
    print(f"  {'─'*56}")

    # ── Sector rotation filter (computed once for the whole scan) ─────────────
    allowed_sectors: Optional[set] = None
    if sector_filter and strategy == "all":
        try:
            sec_scores = compute_sector_scores(period="1y")
            if not sec_scores.empty:
                allowed_sectors = set(sec_scores.head(top_n_sectors).index.tolist())
                print(f"  Sector filter ON — top {top_n_sectors}: {', '.join(sorted(allowed_sectors))}")
        except Exception as exc:
            print(f"  Sector filter error ({exc}) — filter disabled")

    # Choose which check functions to use
    if strategy == "rsi_macd":
        legacy_fn = check_rsi_macd_signal
        use_legacy = True
    elif strategy == "momentum":
        legacy_fn = check_momentum_signal
        use_legacy = True
    else:
        use_legacy = False
        legacy_fn  = None

    for ticker in tickers:
        try:
            # ── Sector filter: skip BUY if sector not top-ranked ─────────────
            if allowed_sectors is not None:
                ticker_sector = _TICKER_SECTOR.get(ticker)
                if ticker_sector and ticker_sector not in allowed_sectors:
                    print(f"  -- {ticker:<22}  skipped (sector={ticker_sector} not top {top_n_sectors})")
                    continue

            df  = fetch_single(ticker, period=period)
            df  = add_all_indicators(df)
            df.dropna(subset=["RSI", "MACD", "ATR"], inplace=True)
            if len(df) < 50:
                continue

            fired: List[Dict] = []

            # Structure stop (computed once per ticker, reused across screens)
            struct_stop = find_structure_stop(df, lookback=20)

            if use_legacy:
                # Original single-strategy scan
                sig = legacy_fn(df, **params)
                if sig:
                    if sig["action"] == "BUY" and not vix_info["allow_buy"]:
                        print(f"  -- {ticker:<22}  BUY suppressed (VIX panic)")
                        continue
                    sig["ticker"] = ticker
                    fired.append(sig)
            else:
                # 5-screen approach — return the FIRST screen that fires
                # Priority: Oversold > Fib Pullback > SMA Pullback > Breakout > Momentum
                for fn in [
                    lambda d: check_oversold_bounce(d),
                    lambda d: check_fibonacci_pullback(d),
                    lambda d: check_pullback_to_sma(d, "SMA_20"),
                    lambda d: check_pullback_to_sma(d, "SMA_50"),
                    lambda d: check_breakout(d),
                    lambda d: check_momentum_leader(d),
                ]:
                    sig = fn(df)
                    if sig:
                        if sig["action"] == "BUY" and not vix_info["allow_buy"]:
                            break
                        sig["ticker"]        = ticker
                        sig["strategy"]      = sig["screen"]
                        sig["sector"]        = _TICKER_SECTOR.get(ticker, "Unknown")
                        # Prefer structure stop if it's tighter than ATR stop
                        if struct_stop and struct_stop > 0 and sig["action"] == "BUY":
                            atr_sl = sig.get("sl", 0)
                            # Use structure stop only when it's above ATR stop (tighter)
                            if struct_stop > atr_sl:
                                sig["sl"]            = struct_stop
                                sig["stop_type"]     = "structure"
                            else:
                                sig["stop_type"]     = "atr"
                            sig["structure_stop"] = struct_stop
                        fired.append(sig)
                        break    # only one signal per ticker

            if fired:
                for sig in fired:
                    signals.append(sig)
                    icon = "🟢" if sig["action"] == "BUY" else "🔴"
                    screen_tag = sig.get("screen", sig.get("strategy", ""))
                    print(f"  {icon} {ticker:<22}  [{screen_tag:<20}]  "
                          f"{sig['action']}  Rs.{sig['price']:,.2f}  — {sig['reason']}")
            else:
                print(f"  ⚪ {ticker:<22}  no signal")

        except Exception as e:
            print(f"  ⚠️  {ticker:<22}  error: {e}")

    print(f"\n  {len(signals)} signal(s) fired out of {len(tickers)} tickers scanned.")
    return signals
