"""
strategies/sector_rotation.py — Phase 3a
Sector momentum scoring and rotation for Indian equities.

Ranks 7 NSE sectors (IT, Banking, Pharma, Auto, FMCG, Energy, Metal)
by composite momentum score across 20 / 60 / 120-day windows.
Returns tickers from the top-N sectors for portfolio allocation.
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Tuple

from data.fetcher import fetch_single

# ── Sector definitions ────────────────────────────────────────────────────────
# Fix (v2): Tata Motors demerged Oct 2025 into two separately listed entities —
# TMCV.NS (commercial vehicles) and TMPV.NS (passenger vehicles/cars — the
# larger consumer-facing business). Only TMCV.NS was listed here, so Auto
# sector scoring was blind to the passenger-vehicle side entirely. Added
# TMPV.NS. Also thickened Metal, which had only 3 constituents (one outlier
# stock could swing the whole sector average) — added VEDL.NS and NMDC.NS.
SECTORS: Dict[str, List[str]] = {
    "IT":      ["TCS.NS", "INFY.NS", "WIPRO.NS", "HCLTECH.NS", "TECHM.NS"],
    "Banking": ["HDFCBANK.NS", "ICICIBANK.NS", "SBIN.NS", "KOTAKBANK.NS", "AXISBANK.NS"],
    "Pharma":  ["SUNPHARMA.NS", "DRREDDY.NS", "CIPLA.NS", "DIVISLAB.NS"],
    "Auto":    ["MARUTI.NS", "BAJAJ-AUTO.NS", "EICHERMOT.NS", "HEROMOTOCO.NS", "TMCV.NS", "TMPV.NS"],
    "FMCG":    ["HINDUNILVR.NS", "ITC.NS", "NESTLEIND.NS", "BRITANNIA.NS", "TATACONSUM.NS"],
    "Energy":  ["RELIANCE.NS", "ONGC.NS", "BPCL.NS", "NTPC.NS", "POWERGRID.NS"],
    "Metal":   ["TATASTEEL.NS", "JSWSTEEL.NS", "HINDALCO.NS", "VEDL.NS", "NMDC.NS"],
}

# Lookback windows (trading days) and their weights in composite score
LOOKBACKS: Dict[str, int]   = {"mom_20d": 20, "mom_60d": 60, "mom_120d": 120}
WEIGHTS:   Dict[str, float] = {"mom_20d": 0.25, "mom_60d": 0.50, "mom_120d": 0.25}


def compute_sector_scores(period: str = "2y") -> pd.DataFrame:
    """
    Fetch latest prices for all sector tickers and compute momentum scores.

    Score per sector:
        1. For each ticker: return = close[-1] / close[-N-1] − 1  (× 100)
        2. Average returns across all tickers in the sector
        3. Composite = weighted sum across lookback windows

    Returns:
        DataFrame indexed by sector name with columns:
        mom_20d, mom_60d, mom_120d, composite_score, Rank, n_tickers
    """
    print(f"\n{'='*60}")
    print(f"  PHASE 3a  —  SECTOR ROTATION ANALYSIS")
    print(f"  Scoring {len(SECTORS)} sectors  |  lookbacks: 20d / 60d / 120d")
    print(f"{'='*60}\n")
    print(f"  {'Sector':<12}  {'20d':>8}  {'60d':>8}  {'120d':>9}  {'Score':>8}")
    print(f"  {'─'*55}")

    rows = []
    failed_tickers: List[str] = []   # Fix (v2): surfaced via df.attrs so callers can warn users, not just the console

    for sector, tickers in SECTORS.items():
        ticker_returns: List[Dict] = []

        for ticker in tickers:
            try:
                df = fetch_single(ticker, period=period)
                close = df["Close"]
                entry: Dict = {}
                for key, n in LOOKBACKS.items():
                    if len(close) > n:
                        entry[key] = float((close.iloc[-1] / close.iloc[-n - 1] - 1) * 100)
                if entry:
                    ticker_returns.append(entry)
            except Exception as e:
                print(f"    ⚠ {ticker}: failed to compute returns, excluded from sector avg: {e}")
                failed_tickers.append(ticker)

        if not ticker_returns:
            continue

        row: Dict = {"Sector": sector, "n_tickers": len(ticker_returns)}
        for key in LOOKBACKS:
            vals = [r[key] for r in ticker_returns if key in r]
            row[key] = round(np.mean(vals), 2) if vals else 0.0

        row["composite_score"] = round(
            sum(WEIGHTS[k] * row.get(k, 0.0) for k in WEIGHTS), 2
        )
        rows.append(row)

        print(
            f"  {sector:<12}  {row['mom_20d']:>+7.2f}%  {row['mom_60d']:>+7.2f}%  "
            f"{row['mom_120d']:>+8.2f}%  {row['composite_score']:>+7.2f}"
        )

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows).set_index("Sector").sort_values("composite_score", ascending=False)
    df["Rank"] = range(1, len(df) + 1)

    if failed_tickers:
        print(f"\n  ⚠ {len(failed_tickers)} ticker(s) failed and were excluded: {', '.join(failed_tickers)}")
    df.attrs["failed_tickers"] = failed_tickers   # non-breaking: existing callers ignore .attrs by default

    return df


def get_top_sector_tickers(
    n_sectors: int = 3,
    period: str = "2y",
    scores_df: pd.DataFrame = None,
) -> Tuple[List[str], pd.DataFrame]:
    """
    Return the flat ticker list from the top-N sectors by momentum.

    Args:
        n_sectors:  How many sectors to select (default 3)
        period:     yfinance period for momentum calculation
        scores_df:  Pre-computed scores (skip re-fetching if supplied)

    Returns:
        (tickers, scores_df)
    """
    if scores_df is None or scores_df.empty:
        scores_df = compute_sector_scores(period=period)
    if scores_df.empty:
        return [], scores_df

    top = scores_df.head(n_sectors).index.tolist()
    seen: set = set()
    tickers: List[str] = []
    for s in top:
        for t in SECTORS.get(s, []):
            if t not in seen:
                seen.add(t)
                tickers.append(t)

    return tickers, scores_df
