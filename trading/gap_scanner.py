"""
trading/gap_scanner.py
Overnight gap-up / gap-down scanner for NSE equities.

A "gap" is when today's open is significantly different from yesterday's close.
This is the single most important pre-market tool for intraday traders.

Functions
─────────
    scan_gaps(tickers, min_gap_pct)    → pd.DataFrame
    get_nifty50_gaps()                 → pd.DataFrame (pre-configured Nifty 50)
    classify_gap(gap_pct)             → str (category + emoji)
    gap_trade_plan(ticker, gap_info)   → dict (intraday plan for gap traders)

Gap Categories (from India intraday conventions):
    ≥ +3%   : Strong Gap Up    — watch for breakout continuation or fade
    +1.5 to +3% : Moderate Gap Up   — wait for 15-min candle, then entry
    +0.5 to +1.5%: Small Gap Up     — minor, trade normally
    −0.5 to +0.5%: Flat             — no gap trade
    −1.5 to −0.5%: Small Gap Down   — minor, trade normally
    −3 to −1.5%  : Moderate Gap Down — watch for bounce or continuation
    ≤ −3%   : Strong Gap Down  — high-risk, wait for stability

Data: uses EOD daily bars only (no intraday needed — open/close from daily bars).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Optional

from data.fetcher import fetch_single, NIFTY50_TICKERS


# ─────────────────────────────────────────────────────────────────────────────
# Gap classification
# ─────────────────────────────────────────────────────────────────────────────

def classify_gap(gap_pct: float) -> Dict:
    """
    Classify a gap percentage into a category with intraday trade bias.

    Returns dict:
        category    : str
        emoji       : str
        bias        : 'bullish' | 'bearish' | 'neutral'
        strategy    : brief intraday strategy note
    """
    if gap_pct >= 3.0:
        return {"category": "Strong Gap Up",   "emoji": "🚀",
                "bias": "bullish",
                "strategy": "Wait for 15-min candle close above VWAP — continuation or fade above prev high"}
    elif gap_pct >= 1.5:
        return {"category": "Moderate Gap Up",  "emoji": "⬆️",
                "bias": "bullish",
                "strategy": "ORB setup: buy if 15-min high breaks with volume; SL below open"}
    elif gap_pct >= 0.5:
        return {"category": "Small Gap Up",     "emoji": "↗️",
                "bias": "neutral",
                "strategy": "Minor gap — treat as normal day, rely on chart setup"}
    elif gap_pct > -0.5:
        return {"category": "Flat Open",        "emoji": "➡️",
                "bias": "neutral",
                "strategy": "No gap trade. Look for first 15-min ORB breakout"}
    elif gap_pct > -1.5:
        return {"category": "Small Gap Down",   "emoji": "↘️",
                "bias": "neutral",
                "strategy": "Minor gap down — treat as normal day, wait for trend confirmation"}
    elif gap_pct > -3.0:
        return {"category": "Moderate Gap Down","emoji": "⬇️",
                "bias": "bearish",
                "strategy": "ORB setup: short if 15-min low breaks; wait for 30-min before long"}
    else:
        return {"category": "Strong Gap Down",  "emoji": "💥",
                "bias": "bearish",
                "strategy": "High gap risk — wait 30-45 min for stability; short only with momentum confirmation"}


# ─────────────────────────────────────────────────────────────────────────────
# Single ticker gap
# ─────────────────────────────────────────────────────────────────────────────

def _single_gap(ticker: str) -> Optional[Dict]:
    """Fetch last 2 bars and compute gap. Returns dict or None on error."""
    try:
        df = fetch_single(ticker, period="5d")
        if len(df) < 2:
            return None
        prev_close = float(df["Close"].iloc[-2])
        today_open = float(df["Open"].iloc[-1])
        today_close= float(df["Close"].iloc[-1])

        if prev_close <= 0:
            return None

        gap_pct    = (today_open  - prev_close) / prev_close * 100
        change_pct = (today_close - prev_close) / prev_close * 100

        # Volume surge vs 5-day average
        vol_today  = float(df["Volume"].iloc[-1])
        vol_avg    = float(df["Volume"].iloc[:-1].mean())
        vol_ratio  = vol_today / max(vol_avg, 1)

        info = classify_gap(gap_pct)
        return {
            "ticker":       ticker,
            "prev_close":   round(prev_close, 2),
            "today_open":   round(today_open, 2),
            "today_close":  round(today_close, 2),
            "gap_pct":      round(gap_pct, 2),
            "change_pct":   round(change_pct, 2),
            "vol_ratio":    round(vol_ratio, 2),
            "category":     info["category"],
            "emoji":        info["emoji"],
            "bias":         info["bias"],
            "strategy":     info["strategy"],
        }
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Main scanner
# ─────────────────────────────────────────────────────────────────────────────

def scan_gaps(
    tickers:     List[str],
    min_gap_pct: float = 0.5,
    max_workers: int   = 12,
) -> pd.DataFrame:
    """
    Scan a ticker list for overnight gaps.

    Args:
        tickers     : list of yfinance symbols (e.g. NIFTY50_TICKERS)
        min_gap_pct : only include tickers with abs(gap) >= this % (default 0.5%)
        max_workers : parallel fetch threads

    Returns:
        DataFrame sorted by gap_pct descending (gap-ups first) with columns:
            ticker, prev_close, today_open, today_close, gap_pct, change_pct,
            vol_ratio, category, emoji, bias, strategy
    """
    rows = []
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futs = {pool.submit(_single_gap, t): t for t in tickers}
        for fut in as_completed(futs, timeout=45):
            try:
                result = fut.result(timeout=0)
                if result and abs(result["gap_pct"]) >= min_gap_pct:
                    rows.append(result)
            except Exception:
                pass

    if not rows:
        return pd.DataFrame(columns=[
            "ticker", "prev_close", "today_open", "today_close",
            "gap_pct", "change_pct", "vol_ratio", "category", "emoji", "bias", "strategy"
        ])

    df = pd.DataFrame(rows).sort_values("gap_pct", ascending=False).reset_index(drop=True)
    return df


# ─────────────────────────────────────────────────────────────────────────────
# Convenience: scan Nifty 50
# ─────────────────────────────────────────────────────────────────────────────

def get_nifty50_gaps(min_gap_pct: float = 0.5) -> pd.DataFrame:
    """Scan all Nifty 50 stocks for gaps. Top-level convenience function."""
    return scan_gaps(NIFTY50_TICKERS, min_gap_pct=min_gap_pct)


# ─────────────────────────────────────────────────────────────────────────────
# Gap trade plan generator
# ─────────────────────────────────────────────────────────────────────────────

def gap_trade_plan(gap_row: Dict) -> Dict:
    """
    Generate an intraday trade plan for a gapped stock.

    Strategy:
        Gap Up  → ORB long above 15-min high, SL = 15-min low, TP = 2× range
        Gap Down → ORB short below 15-min low, SL = 15-min high, TP = 2× range

    Note: 15-min levels must be observed live — this returns the framework.
    """
    ticker   = gap_row.get("ticker", "")
    gap_pct  = gap_row.get("gap_pct", 0)
    open_    = gap_row.get("today_open", 0)
    bias     = gap_row.get("bias", "neutral")

    # Approximate ORB levels using gap context
    # True ORB requires real-time 9:15–9:30 data; these are directional guides
    est_range = open_ * 0.005   # estimate 0.5% initial range from open

    if bias == "bullish":
        est_entry = round(open_ + est_range, 2)
        est_sl    = round(open_ - est_range, 2)
        est_tp    = round(est_entry + 2 * (est_entry - est_sl), 2)
        action    = "BUY above 15-min high"
    elif bias == "bearish":
        est_entry = round(open_ - est_range, 2)
        est_sl    = round(open_ + est_range, 2)
        est_tp    = round(est_entry - 2 * (est_sl - est_entry), 2)
        action    = "SHORT below 15-min low"
    else:
        return {
            "ticker": ticker, "action": "WAIT",
            "note": "Flat/small gap — wait for 15-min ORB setup to form.",
            "gap_pct": gap_pct,
        }

    rr = abs(est_tp - est_entry) / max(abs(est_entry - est_sl), 0.01)
    return {
        "ticker":       ticker,
        "action":       action,
        "gap_pct":      round(gap_pct, 2),
        "open":         open_,
        "est_entry":    est_entry,
        "est_sl":       est_sl,
        "est_tp":       est_tp,
        "rr_ratio":     round(rr, 2),
        "note":         (f"ORB plan (15-min based). "
                         f"Wait for 9:15-9:30 candle to form before entry. "
                         f"Confirm with volume > 1.5× avg."),
    }
