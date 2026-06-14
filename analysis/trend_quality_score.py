"""
trend_quality_score.py
======================
Trend Quality Score (TQS) — max 90 points across 4 equally-weighted pillars.

Merges:
  - Gemini's vectorized np.where scoring (fast, production-grade)
  - pandas_ta for indicator calculation (reliable, battle-tested)
  - This codebase's TQSResult dataclass + scan_universe() + print_report()

Install:
    pip install yfinance pandas-ta numpy pandas

Usage:
    python trend_quality_score.py
    from trend_quality_score import score_ticker, scan_universe
"""

from __future__ import annotations
import warnings
warnings.filterwarnings("ignore")

import os
import sys

# ── Ensure project root is on sys.path so data.fetcher resolves correctly ────
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import numpy as np
import pandas as pd
import pandas_ta as ta
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

pd.options.mode.chained_assignment = None


# ─────────────────────────────────────────────────────────────────────────────
# Data fetching — uses existing tiered fetcher (Angel One → Stooq → Yahoo)
# ─────────────────────────────────────────────────────────────────────────────

def fetch_data(ticker: str, period: str = "5y") -> pd.DataFrame:
    """
    Use the repo's tiered data fetcher so TQS benefits from Angel One
    live data automatically when credentials are configured.
    Falls back to Stooq → Yahoo if Angel One is unavailable.
    """
    try:
        from data.fetcher import fetch_single
        df = fetch_single(ticker, period=period)
    except Exception:
        # Hard fallback to yfinance if fetcher itself is unavailable
        import yfinance as yf
        df = yf.download(ticker, period=period, auto_adjust=True, progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [c[0] for c in df.columns]

    if df is None or df.empty:
        raise ValueError(f"{ticker}: no data returned")
    if len(df) < 252:
        raise ValueError(f"{ticker}: need ≥252 rows, got {len(df)}")

    return df[["Open", "High", "Low", "Close", "Volume"]].dropna()


# ─────────────────────────────────────────────────────────────────────────────
# Indicator engine  (pandas_ta for reliability + fast vectorized extras)
# ─────────────────────────────────────────────────────────────────────────────

def _fast_slope(series: pd.Series, window: int) -> pd.Series:
    """Vectorized rolling OLS slope — ~10x faster than polyfit inside apply."""
    x = np.arange(window, dtype=float)
    x -= x.mean()
    x_ss = (x ** 2).sum()
    return series.rolling(window).apply(
        lambda y: float(np.dot(x, y - y.mean()) / x_ss), raw=True
    )


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    # ── P1: Trend Strength ────────────────────────────────────────────────────
    df["SMA20"]  = ta.sma(df["Close"], length=20)
    df["SMA50"]  = ta.sma(df["Close"], length=50)
    df["SMA200"] = ta.sma(df["Close"], length=200)
    df["SMA200_Slope"] = (df["SMA200"].pct_change(5) / 5) * 100

    adx_df = ta.adx(df["High"], df["Low"], df["Close"], length=14)
    df["ADX"] = adx_df["ADX_14"] if adx_df is not None else np.nan

    # ── P2: Trend Persistence (rolling Sharpe, annualised, clipped) ───────────
    ret = df["Close"].pct_change()

    def rolling_sharpe(returns: pd.Series, window: int) -> pd.Series:
        mu    = returns.rolling(window).mean()
        sigma = returns.rolling(window).std(ddof=1).replace(0, np.nan)
        return (mu / sigma * np.sqrt(252)).clip(-3.0, 3.0)

    df["Sharpe_5"]  = rolling_sharpe(ret, 5)
    df["Sharpe_20"] = rolling_sharpe(ret, 20)
    df["Sharpe_60"] = rolling_sharpe(ret, 60)

    # ── P3: Momentum Quality ──────────────────────────────────────────────────
    df["RSI"] = ta.rsi(df["Close"], length=14)

    macd_df = ta.macd(df["Close"], fast=12, slow=26, signal=9)
    if macd_df is not None:
        df["MACD"]           = macd_df["MACD_12_26_9"]
        df["MACD_Sig"]       = macd_df["MACDs_12_26_9"]
        df["MACD_Hist"]      = macd_df["MACDh_12_26_9"]
    else:
        df[["MACD", "MACD_Sig", "MACD_Hist"]] = np.nan

    df["MACD_Hist_Delta"] = df["MACD_Hist"].diff()   # histogram day-over-day change

    # ── P4: Technical Confirmation ────────────────────────────────────────────
    df["OBV"] = ta.obv(df["Close"], df["Volume"])

    obv_mu    = df["OBV"].rolling(20).mean()
    obv_sigma = df["OBV"].rolling(20).std(ddof=1).replace(0, np.nan)
    df["OBV_Z"] = ((df["OBV"] - obv_mu) / obv_sigma).clip(-3.0, 3.0)

    # Vectorized slope — avoids slow polyfit-inside-apply loop
    df["OBV_Slope_20"]      = _fast_slope(df["OBV"], 20)
    df["OBV_Slope_PctRank"] = df["OBV_Slope_20"].rolling(252).rank(pct=True)

    up_vol   = ret.gt(0) * df["Volume"]
    down_vol = ret.lt(0) * df["Volume"]
    df["Vol_Ratio"] = (
        up_vol.rolling(20).sum() / down_vol.rolling(20).sum().replace(0, np.nan)
    ).fillna(1.0).clip(upper=3.0)

    df.dropna(inplace=True)
    return df


# ─────────────────────────────────────────────────────────────────────────────
# Vectorized pillar scoring  (Gemini-style np.where chains — fast)
# ─────────────────────────────────────────────────────────────────────────────

def _score_all_pillars(df: pd.DataFrame) -> pd.DataFrame:
    """Compute all 4 pillar scores for every row in one vectorized pass."""
    c = df  # alias for brevity

    # ── P1: Trend Strength (max 22.5) ─────────────────────────────────────────
    p1_align = np.where(
        (c["Close"] > c["SMA20"]) & (c["SMA20"] > c["SMA50"]) & (c["SMA50"] > c["SMA200"]), 12.0,
        np.where((c["Close"] > c["SMA50"]) & (c["SMA50"] > c["SMA200"]), 8.0,
        np.where(c["Close"] > c["SMA200"], 4.0, 0.0)))

    p1_adx = np.where(c["ADX"] > 40, 6.0,
             np.where(c["ADX"] > 30, 4.5,
             np.where(c["ADX"] > 25, 3.0,
             np.where(c["ADX"] >= 20, 1.5, 0.0))))

    p1_slope = np.where(c["SMA200_Slope"] > 0.05, 4.5,
               np.where(c["SMA200_Slope"] > 0.01, 2.5,
               np.where(c["SMA200_Slope"] >= 0.0, 1.0, 0.0)))

    p1 = p1_align + p1_adx + p1_slope

    # ── P2: Trend Persistence (max 22.5) ──────────────────────────────────────
    p2_s5 = np.where(c["Sharpe_5"] > 2.0, 5.0,
            np.where(c["Sharpe_5"] >= 1.0, 3.75,
            np.where(c["Sharpe_5"] >= 0.0, 2.5,
            np.where(c["Sharpe_5"] >= -1.0, 1.25, 0.0))))

    p2_s20 = np.where(c["Sharpe_20"] > 2.0, 10.0,
             np.where(c["Sharpe_20"] >= 1.5, 8.0,
             np.where(c["Sharpe_20"] >= 1.0, 6.0,
             np.where(c["Sharpe_20"] >= 0.0, 3.0,
             np.where(c["Sharpe_20"] >= -1.0, 1.0, 0.0)))))

    p2_s60 = np.where(c["Sharpe_60"] > 2.0, 7.5,
             np.where(c["Sharpe_60"] >= 1.5, 6.0,
             np.where(c["Sharpe_60"] >= 1.0, 4.5,
             np.where(c["Sharpe_60"] >= 0.0, 2.25,
             np.where(c["Sharpe_60"] >= -1.0, 0.75, 0.0)))))

    p2 = p2_s5 + p2_s20 + p2_s60

    # ── P3: Momentum Quality (max 22.5) ───────────────────────────────────────
    p3_rsi = np.where((c["RSI"] >= 55) & (c["RSI"] <= 70), 13.5,
             np.where((c["RSI"] >= 45) & (c["RSI"] < 55), 9.0,
             np.where((c["RSI"] > 70) & (c["RSI"] <= 80), 6.75,
             np.where((c["RSI"] >= 30) & (c["RSI"] < 45), 4.5,
             np.where(c["RSI"] > 80, 2.25, 0.0)))))

    is_bull     = c["MACD"] > c["MACD_Sig"]
    hist_pos    = c["MACD_Hist"] > 0
    hist_rising = c["MACD_Hist_Delta"] > 0
    # "approaching cross": histogram near zero relative to its own recent noise
    hist_std5   = c["MACD_Hist"].rolling(5).std().fillna(0)
    near_cross  = (c["MACD_Hist"].abs() < hist_std5) & (hist_std5 > 0)

    p3_macd = np.where(is_bull & hist_pos & hist_rising, 9.0,
              np.where(is_bull & hist_pos, 6.75,
              np.where(is_bull, 4.5,
              np.where(near_cross, 2.25, 0.0))))

    p3 = p3_rsi + p3_macd

    # ── P4: Technical Confirmation (max 22.5) ─────────────────────────────────
    p4_z = np.where(c["OBV_Z"] >= 2.0, 13.5,
           np.where(c["OBV_Z"] >= 1.0, 10.125,
           np.where(c["OBV_Z"] >= 0.0, 6.75,
           np.where(c["OBV_Z"] >= -1.0, 3.375, 0.0))))

    p4_slope = np.where(c["OBV_Slope_PctRank"] >= 0.75, 5.625,
               np.where(c["OBV_Slope_PctRank"] >= 0.50, 3.75,
               np.where(c["OBV_Slope_PctRank"] >= 0.25, 1.875, 0.0)))

    p4_ratio = np.where(c["Vol_Ratio"] > 1.5, 3.375,
               np.where(c["Vol_Ratio"] > 1.2, 2.25,
               np.where(c["Vol_Ratio"] >= 1.0, 1.125, 0.0)))

    p4 = p4_z + p4_slope + p4_ratio

    out = df[["Close"]].copy()
    out["P1_Strength"]     = p1.round(3)
    out["P2_Persistence"]  = p2.round(3)
    out["P3_Momentum"]     = p3.round(3)
    out["P4_Confirmation"] = p4.round(3)
    out["TQS"]             = (p1 + p2 + p3 + p4).round(2)
    out["RSI"]             = df["RSI"].round(2)
    out["ADX"]             = df["ADX"].round(2)
    out["Sharpe_20"]       = df["Sharpe_20"].round(3)
    out["OBV_Z"]           = df["OBV_Z"].round(3)
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Result dataclass
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class TQSResult:
    ticker:     str
    date:       str
    close:      float
    tqs:        float
    p1:         float
    p2:         float
    p3:         float
    p4:         float
    rsi:        float
    adx:        float
    sharpe_20:  float
    obv_z:      float

    def grade(self) -> str:
        for thresh, g in [(80,"A+"), (70,"A"), (55,"B"), (40,"C"), (25,"D")]:
            if self.tqs >= thresh: return g
        return "F"

    def signal(self) -> str:
        if self.tqs >= 75: return "STRONG TREND"
        if self.tqs >= 60: return "TRENDING"
        if self.tqs >= 45: return "NEUTRAL"
        if self.tqs >= 30: return "WEAK"
        return "AVOID"

    def as_dict(self) -> Dict:
        return {
            "ticker": self.ticker, "date": self.date, "close": self.close,
            "tqs": self.tqs, "grade": self.grade(), "signal": self.signal(),
            "p1_strength": self.p1, "p2_persistence": self.p2,
            "p3_momentum": self.p3, "p4_confirmation": self.p4,
            "rsi": self.rsi, "adx": self.adx,
            "sharpe_20": self.sharpe_20, "obv_z": self.obv_z,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def score_ticker(
    ticker: str,
    period: str = "2y",
    last_n: int = 1,
) -> "TQSResult | List[TQSResult]":
    """Score one ticker. Returns TQSResult or list of last_n results."""
    df_raw = fetch_data(ticker, period=period)
    df_ind = add_indicators(df_raw)
    df_tqs = _score_all_pillars(df_ind)

    results = []
    for idx, row in df_tqs.tail(last_n).iterrows():
        results.append(TQSResult(
            ticker=ticker, date=str(idx.date()),
            close=float(row["Close"]), tqs=float(row["TQS"]),
            p1=float(row["P1_Strength"]), p2=float(row["P2_Persistence"]),
            p3=float(row["P3_Momentum"]), p4=float(row["P4_Confirmation"]),
            rsi=float(row["RSI"]), adx=float(row["ADX"]),
            sharpe_20=float(row["Sharpe_20"]), obv_z=float(row["OBV_Z"]),
        ))
    return results[0] if last_n == 1 else results


def scan_universe(tickers: List[str], period: str = "1y") -> pd.DataFrame:
    """Score all tickers, return DataFrame sorted by TQS descending."""
    rows = []
    for t in tickers:
        try:
            r = score_ticker(t, period=period)
            rows.append(r.as_dict())
            print(f"  ✓ {t:20s}  TQS={r.tqs:5.1f}  [{r.grade()}]  {r.signal()}")
        except Exception as e:
            print(f"  ✗ {t:20s}  skipped: {e}")
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values("tqs", ascending=False).reset_index(drop=True)


def print_report(r: TQSResult) -> None:
    bar = lambda v, mx: "█" * int(v / mx * 20) + "░" * (20 - int(v / mx * 20))
    print(f"\n{'━'*56}")
    print(f"  TQS Report — {r.ticker}  [{r.date}]")
    print(f"{'━'*56}")
    print(f"  Close:    ₹{r.close:>10,.2f}")
    print(f"  Grade:    {r.grade():<4}  Signal: {r.signal()}")
    print(f"\n  TQS Total   {r.tqs:5.1f}/90   {bar(r.tqs, 90)}")
    print(f"  P1 Strength {r.p1:5.1f}/22.5 {bar(r.p1, 22.5)}")
    print(f"  P2 Persist  {r.p2:5.1f}/22.5 {bar(r.p2, 22.5)}")
    print(f"  P3 Momentum {r.p3:5.1f}/22.5 {bar(r.p3, 22.5)}")
    print(f"  P4 Volume   {r.p4:5.1f}/22.5 {bar(r.p4, 22.5)}")
    print(f"\n  RSI:      {r.rsi:5.1f}    ADX:      {r.adx:5.1f}")
    print(f"  Sharpe20: {r.sharpe_20:5.2f}    OBV Z:    {r.obv_z:5.2f}")
    print(f"{'━'*56}\n")


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    TICKER = "RELIANCE.NS"
    print(f"Scoring {TICKER}...")
    result = score_ticker(TICKER, period="2y")
    print_report(result)

    # Last 5 days (useful for backtesting)
    history = score_ticker(TICKER, period="2y", last_n=5)
    print("Last 5 sessions:")
    for h in history:
        print(f"  {h.date}  TQS={h.tqs:5.1f}  P1={h.p1:.1f} "
              f"P2={h.p2:.1f} P3={h.p3:.1f} P4={h.p4:.1f}  {h.signal()}")

    # Universe scan
    NIFTY_SAMPLE = [
        "RELIANCE.NS", "TCS.NS",       "HDFCBANK.NS",  "INFY.NS",
        "ICICIBANK.NS","HINDUNILVR.NS", "ITC.NS",       "SBIN.NS",
        "BHARTIARTL.NS","KOTAKBANK.NS", "AXISBANK.NS",  "WIPRO.NS",
    ]
    print(f"\nScanning {len(NIFTY_SAMPLE)} stocks...\n")
    scan_df = scan_universe(NIFTY_SAMPLE, period="1y")
    print("\n" + "─" * 90)
    print(scan_df[[
        "ticker","close","tqs","grade","signal",
        "p1_strength","p2_persistence","p3_momentum","p4_confirmation",
        "rsi","sharpe_20","obv_z"
    ]].to_string(index=False))
