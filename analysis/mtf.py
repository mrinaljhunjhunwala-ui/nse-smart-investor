"""
analysis/mtf.py
Multi-Timeframe (MTF) alignment analysis.

Confirms trade direction across daily, weekly, and monthly bars so that
entries only fire when all meaningful timeframes agree.  Uses only daily
yfinance data (resampled) — no intraday data required.

Key Functions
─────────────
    resample_weekly(df)              → weekly OHLCV from daily bars
    resample_monthly(df)             → monthly OHLCV from daily bars
    get_trend_direction(df)          → 'bullish' | 'bearish' | 'neutral'
    check_daily_weekly_alignment(df, weekly_df=None) → dict with alignment details
    check_all_timeframes(ticker)     → full 3-TF alignment dict
    mtf_score(ticker)                → 0-3 bullish TF count (quick integer)
"""

import numpy as np
import pandas as pd

from data.fetcher import fetch_single


# ─────────────────────────────────────────────────────────────────────────────
# Resamplers
# ─────────────────────────────────────────────────────────────────────────────

def resample_weekly(df: pd.DataFrame) -> pd.DataFrame:
    """
    Resample a daily OHLCV DataFrame to weekly bars (week ending Friday).

    Required columns: Open, High, Low, Close, Volume
    """
    ohlcv = {
        "Open":   "first",
        "High":   "max",
        "Low":    "min",
        "Close":  "last",
        "Volume": "sum",
    }
    weekly = df.resample("W-FRI").agg(ohlcv).dropna(subset=["Close"])
    return weekly


def resample_monthly(df: pd.DataFrame) -> pd.DataFrame:
    """
    Resample a daily OHLCV DataFrame to monthly bars (calendar month end).

    Required columns: Open, High, Low, Close, Volume
    """
    ohlcv = {
        "Open":   "first",
        "High":   "max",
        "Low":    "min",
        "Close":  "last",
        "Volume": "sum",
    }
    monthly = df.resample("ME").agg(ohlcv).dropna(subset=["Close"])
    return monthly


# ─────────────────────────────────────────────────────────────────────────────
# Trend Direction on a Single Timeframe
# ─────────────────────────────────────────────────────────────────────────────

def get_trend_direction(df: pd.DataFrame, fast: int = 20, slow: int = 50) -> dict:
    """
    Classify trend direction for an OHLCV DataFrame at its native timeframe.

    Method
    ──────
    1. Fast MA (default 20-period) vs Slow MA (50-period) relationship
    2. Slope of Fast MA over last 5 bars (rising / falling)
    3. Price position relative to both MAs
    4. ADX proxy: (recent high − recent low) / low as trend strength

    Returns
    ───────
    {
        "direction"  : "bullish" | "bearish" | "neutral",
        "strength"   : "strong" | "moderate" | "weak",
        "fast_ma"    : float,          # most-recent fast MA value
        "slow_ma"    : float,          # most-recent slow MA value
        "price"      : float,          # most-recent close
        "ma_spread"  : float,          # (fast - slow) / slow × 100  (%)
        "slope_rising": bool,          # fast MA rising last 5 bars?
    }
    """
    if len(df) < slow + 5:
        return {"direction": "neutral", "strength": "weak",
                "fast_ma": np.nan, "slow_ma": np.nan,
                "price": np.nan, "ma_spread": np.nan, "slope_rising": False}

    close    = df["Close"]
    fast_ma  = close.ewm(span=fast, adjust=False).mean()
    slow_ma  = close.ewm(span=slow, adjust=False).mean()

    f_now  = fast_ma.iloc[-1]
    s_now  = slow_ma.iloc[-1]
    p_now  = close.iloc[-1]

    spread_pct   = (f_now - s_now) / s_now * 100         # + = bullish
    slope_rising = fast_ma.iloc[-1] > fast_ma.iloc[-5]   # 5-bar slope

    # Price above / below MAs
    above_fast = p_now > f_now
    above_slow = p_now > s_now

    # Direction classification
    if spread_pct > 0 and slope_rising and above_slow:
        direction = "bullish"
    elif spread_pct < 0 and (not slope_rising) and (not above_slow):
        direction = "bearish"
    else:
        direction = "neutral"

    # Strength via spread magnitude
    abs_spread = abs(spread_pct)
    if abs_spread >= 3.0:
        strength = "strong"
    elif abs_spread >= 1.0:
        strength = "moderate"
    else:
        strength = "weak"

    return {
        "direction":   direction,
        "strength":    strength,
        "fast_ma":     round(f_now, 2),
        "slow_ma":     round(s_now, 2),
        "price":       round(p_now, 2),
        "ma_spread":   round(spread_pct, 2),
        "slope_rising": bool(slope_rising),
        "above_fast":  bool(above_fast),
        "above_slow":  bool(above_slow),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Daily / Weekly Alignment Check
# ─────────────────────────────────────────────────────────────────────────────

def check_daily_weekly_alignment(df: pd.DataFrame, weekly_df: pd.DataFrame = None) -> dict:
    """
    Compare daily vs weekly trend to confirm or contradict a signal.

    Parameters
    ──────────
    df : daily OHLCV DataFrame (already fetched, needs ≥ 252 rows for reliability)
    weekly_df : optional, already-fetched weekly OHLCV DataFrame. Pass this when
        the caller has real exchange-reported weekly bars available (e.g. fetched
        with interval="1wk") rather than a daily->weekly resample, which is a
        weaker proxy — Yahoo/NSE's actual weekly bars can differ from a naive
        resample near week boundaries and holidays. When omitted, falls back to
        resample_weekly(df) as before, so existing single-argument callers are
        unaffected.

    Returns
    ───────
    {
        "aligned"      : bool,       # True when both TFs agree
        "alignment"    : str,        # 'bullish' | 'bearish' | 'mixed'
        "daily"        : dict,       # get_trend_direction result on daily
        "weekly"       : dict,       # get_trend_direction result on weekly
        "confirmation" : str,        # human-readable summary
    }
    """
    daily_trend  = get_trend_direction(df)
    weekly_df    = weekly_df if weekly_df is not None and not weekly_df.empty else resample_weekly(df)
    weekly_trend = get_trend_direction(weekly_df)

    d_dir = daily_trend["direction"]
    w_dir = weekly_trend["direction"]

    if d_dir == "bullish" and w_dir == "bullish":
        alignment    = "bullish"
        aligned      = True
        confirmation = "Both daily and weekly bullish — high-conviction long setup."
    elif d_dir == "bearish" and w_dir == "bearish":
        alignment    = "bearish"
        aligned      = True
        confirmation = "Both daily and weekly bearish — avoid longs / consider shorts."
    elif d_dir == "bullish" and w_dir == "neutral":
        alignment    = "mixed"
        aligned      = False
        confirmation = "Daily bullish but weekly neutral — wait for weekly confirmation."
    elif d_dir == "bullish" and w_dir == "bearish":
        alignment    = "mixed"
        aligned      = False
        confirmation = "Daily bullish but weekly bearish — counter-trend risk, skip."
    elif d_dir == "bearish" and w_dir == "bullish":
        alignment    = "mixed"
        aligned      = False
        confirmation = "Daily pullback in weekly uptrend — possible buy-the-dip opportunity."
    else:
        alignment    = "mixed"
        aligned      = False
        confirmation = f"Timeframes mixed (daily={d_dir}, weekly={w_dir}) — no clear edge."

    return {
        "aligned":      aligned,
        "alignment":    alignment,
        "daily":        daily_trend,
        "weekly":       weekly_trend,
        "confirmation": confirmation,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Full Three-Timeframe Check (daily + weekly + monthly)
# ─────────────────────────────────────────────────────────────────────────────

def check_all_timeframes(ticker: str, period: str = "2y") -> dict:
    """
    Fetch data and check daily, weekly, and monthly trend alignment.

    Parameters
    ──────────
    ticker : yfinance symbol (e.g. 'RELIANCE.NS')
    period : yfinance period string (default '2y' for monthly context)

    Returns
    ───────
    {
        "ticker"        : str,
        "aligned"       : bool,      # all 3 TFs agree
        "bullish_count" : int,        # 0-3 bullish timeframes
        "alignment"     : str,        # 'bullish' | 'bearish' | 'mixed'
        "daily"         : dict,
        "weekly"        : dict,
        "monthly"       : dict,
        "summary"       : str,
    }
    """
    try:
        df = fetch_single(ticker, period=period)
        df = df.dropna(subset=["Close"])
        if len(df) < 60:
            return _empty_mtf(ticker, "Insufficient data")
    except Exception as exc:
        return _empty_mtf(ticker, str(exc))

    daily_trend   = get_trend_direction(df)
    weekly_trend  = get_trend_direction(resample_weekly(df))
    monthly_trend = get_trend_direction(resample_monthly(df))

    dirs         = [daily_trend["direction"], weekly_trend["direction"], monthly_trend["direction"]]
    bullish_count = dirs.count("bullish")
    bearish_count = dirs.count("bearish")

    if bullish_count == 3:
        alignment = "bullish"
        aligned   = True
        summary   = f"{ticker}: All 3 timeframes bullish — maximum conviction long."
    elif bearish_count == 3:
        alignment = "bearish"
        aligned   = True
        summary   = f"{ticker}: All 3 timeframes bearish — avoid / short."
    elif bullish_count >= 2:
        alignment = "bullish"
        aligned   = False
        summary   = f"{ticker}: {bullish_count}/3 TFs bullish — moderate conviction."
    elif bearish_count >= 2:
        alignment = "bearish"
        aligned   = False
        summary   = f"{ticker}: {bearish_count}/3 TFs bearish — lean short."
    else:
        alignment = "mixed"
        aligned   = False
        summary   = f"{ticker}: Timeframes conflict — wait for alignment."

    return {
        "ticker":        ticker,
        "aligned":       aligned,
        "bullish_count": bullish_count,
        "alignment":     alignment,
        "daily":         daily_trend,
        "weekly":        weekly_trend,
        "monthly":       monthly_trend,
        "summary":       summary,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Quick Integer Score (0–3)
# ─────────────────────────────────────────────────────────────────────────────

def mtf_score(ticker: str, period: str = "2y") -> int:
    """
    Return an integer 0–3: the count of bullish timeframes (daily/weekly/monthly).

    Designed for fast in-scanner use:
        3 → all timeframes bullish  (take entry)
        2 → 2 of 3 bullish          (reduced size)
        1 → only 1 TF bullish       (skip or paper-trade only)
        0 → no bullish TF           (skip)
    """
    result = check_all_timeframes(ticker, period=period)
    return result.get("bullish_count", 0)


# ─────────────────────────────────────────────────────────────────────────────
# Helper
# ─────────────────────────────────────────────────────────────────────────────

def _empty_mtf(ticker: str, reason: str) -> dict:
    empty = {"direction": "neutral", "strength": "weak",
             "fast_ma": np.nan, "slow_ma": np.nan,
             "price": np.nan, "ma_spread": np.nan,
             "slope_rising": False, "above_fast": False, "above_slow": False}
    return {
        "ticker":        ticker,
        "aligned":       False,
        "bullish_count": 0,
        "alignment":     "mixed",
        "daily":         empty,
        "weekly":        empty,
        "monthly":       empty,
        "summary":       f"{ticker}: MTF error — {reason}",
    }
