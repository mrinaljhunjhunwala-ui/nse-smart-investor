"""
backtest/sector_runner.py — Phase 3a
Sector rotation backtest pipeline.

1. Score all 7 sectors by composite momentum (20d / 60d / 120d)
2. Select the top-N sectors
3. Run equal-weight portfolio backtest on their constituent tickers
4. Compare vs. running on the bottom sectors (to validate the rotation signal)
"""

import pandas as pd
from typing import Type, Dict, Optional, List

from strategies.sector_rotation import (
    SECTORS, compute_sector_scores, get_top_sector_tickers
)
from backtest.portfolio import run_portfolio_backtest


def run_sector_rotation_backtest(
    strategy_cls: Type,
    period: str = "2y",
    total_cash: float = 1_000_000,
    n_sectors: int = 3,
    strategy_params: Optional[Dict] = None,
) -> pd.DataFrame:
    """
    Full sector rotation + backtest pipeline.

    Args:
        strategy_cls:    Trading strategy for the selected sector tickers
        period:          Data period (used for both scoring and backtesting)
        total_cash:      Total capital in INR
        n_sectors:       Number of top sectors to invest in
        strategy_params: Optimised strategy params from Phase 2a (optional)

    Returns:
        Portfolio results DataFrame for the top-sector tickers
    """
    # ── Step 1: Score and rank sectors ────────────────────────────────────────
    scores = compute_sector_scores(period=period)
    if scores.empty:
        print("  ERROR: Sector scoring failed.")
        return pd.DataFrame()

    # FIX BT3 — n_sectors is a free CLI int (main.py --n-sectors) with no
    # upper-bound check. If it's >= the total number of scored sectors,
    # scores.tail(len(scores) - n_sectors) evaluates to scores.tail(<=0),
    # and pandas' negative .tail(-k) means "all but the first k rows" —
    # NOT empty. That silently produced a "bottom_sectors" (Avoided) list
    # that overlapped with top_sectors, printing sectors as both invested-in
    # and avoided at once. Clamp so bottom_sectors is only ever the genuine
    # complement of top_sectors.
    n_sectors      = max(1, min(n_sectors, len(scores)))
    top_sectors    = scores.head(n_sectors).index.tolist()
    bottom_sectors = scores.tail(max(0, len(scores) - n_sectors)).index.tolist()

    # ── Step 2: Print ranking table ───────────────────────────────────────────
    print(f"\n  ── Sector Ranking  (top {n_sectors} selected for investment) ──────────────")
    print(f"  {'#':<4} {'Sector':<12} {'20d':>8} {'60d':>8} {'120d':>9} {'Score':>8}  Decision")
    print(f"  {'─'*65}")

    for _, row in scores.iterrows():
        sector   = row.name
        decision = "  ✅ INVEST" if sector in top_sectors else "  ⛔ skip"
        print(
            f"  {int(row['Rank']):<4} {sector:<12} "
            f"{row['mom_20d']:>+7.2f}%  "
            f"{row['mom_60d']:>+7.2f}%  "
            f"{row['mom_120d']:>+8.2f}%  "
            f"{row['composite_score']:>+7.2f}{decision}"
        )

    # ── Step 3: Collect tickers for top sectors ───────────────────────────────
    seen: set         = set()
    selected_tickers: List[str] = []
    for s in top_sectors:
        for t in SECTORS.get(s, []):
            if t not in seen:
                seen.add(t)
                selected_tickers.append(t)

    print(f"\n  Top sectors   : {', '.join(top_sectors)}")
    print(f"  Avoided       : {', '.join(bottom_sectors)}")
    print(f"  Total tickers : {len(selected_tickers)}  →  {', '.join(selected_tickers)}")

    # ── Step 4: Portfolio backtest on selected tickers ────────────────────────
    results = run_portfolio_backtest(
        tickers         = selected_tickers,
        strategy_cls    = strategy_cls,
        period          = period,
        total_cash      = total_cash,
        strategy_params = strategy_params,
        save_chart      = True,
    )

    return results
