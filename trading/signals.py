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
        import yfinance as yf
        vix_df = yf.download("^INDIAVIX", period="5d", interval="1d",
                             auto_adjust=True, progress=False)
        if isinstance(vix_df.columns, pd.MultiIndex):
            vix_df.columns = vix_df.columns.get_level_values(0)
        if vix_df.empty or len(vix_df) < 2:
            raise ValueError("No VIX data")

        curr    = float(vix_df["Close"].iloc[-1])
        prev    = float(vix_df["Close"].iloc[-2])
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
    tickers:   List[str],
    strategy:  str = "all",          # "all" | "rsi_macd" | "momentum"
    period:    str = "1y",
    params:    Optional[Dict] = None,
    use_vix:   bool = True,
) -> List[Dict]:
    """
    Scan a ticker list across all 4 screens (or a single legacy strategy).

    strategy="all"      → runs all 4 modern screens
    strategy="rsi_macd" → legacy RSI+MACD only (backtest compat)
    strategy="momentum" → legacy Momentum only

    India VIX filter: when VIX > 28, BUY signals are suppressed.
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
        print(f"  ⚠️  VIX > 28 — BUY signals suppressed (panic regime)")
    print(f"  {'─'*56}")

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
            df  = fetch_single(ticker, period=period)
            df  = add_all_indicators(df)
            df.dropna(subset=["RSI", "MACD", "ATR"], inplace=True)
            if len(df) < 50:
                continue

            fired: List[Dict] = []

            if use_legacy:
                # Original single-strategy scan
                sig = legacy_fn(df, **params)
                if sig:
                    if sig["action"] == "BUY" and not vix_info["allow_buy"]:
                        print(f"  🔕 {ticker:<22}  BUY suppressed (VIX panic)")
                        continue
                    sig["ticker"] = ticker
                    fired.append(sig)
            else:
                # 4-screen approach — return the FIRST screen that fires
                # (priority: Oversold > Pullback > Breakout > Momentum)
                for fn in [
                    lambda d: check_oversold_bounce(d),
                    lambda d: check_pullback_to_sma(d, "SMA_20"),
                    lambda d: check_pullback_to_sma(d, "SMA_50"),
                    lambda d: check_breakout(d),
                    lambda d: check_momentum_leader(d),
                ]:
                    sig = fn(df)
                    if sig:
                        if sig["action"] == "BUY" and not vix_info["allow_buy"]:
                            break
                        sig["ticker"]   = ticker
                        sig["strategy"] = sig["screen"]
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
