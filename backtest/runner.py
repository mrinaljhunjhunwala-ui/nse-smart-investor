"""
backtest/runner.py
Runs backtests across multiple tickers and generates a consolidated report.
Uses backtesting.py for execution, plus STT/brokerage cost modeling.

Optimizations applied:
  - Parallelizes per-ticker backtest loop with ThreadPoolExecutor (8 workers)
  - Preserves result ordering (collected by ticker, reassembled in input order)
  - Per-ticker error handling: one failure doesn't abort the batch
  - All failures logged at WARNING level (no silent drops)
"""

import pandas as pd
import numpy as np
from backtesting import Backtest
from typing import Type, List, Dict, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
import logging

from data.fetcher import fetch_single
from utils.indicators import add_all_indicators

_log = logging.getLogger("backtest.runner")

# ── Indian market cost constants ─────────────────────────────────────────────
STT_RATE       = 0.001   # 0.1% on sell side (equity delivery)
BROKERAGE_RATE = 0.0003  # 0.03% per leg (Zerodha flat ₹20 per order, approx)
EXCHANGE_FEES  = 0.00035 # NSE transaction charges + SEBI fees + GST (approx)
TOTAL_COST     = STT_RATE + 2 * BROKERAGE_RATE + 2 * EXCHANGE_FEES  # round-trip


def run_backtest(
    tickers: List[str],
    strategy_cls: Type,
    period: str = "2y",
    cash: float = 1_000_000,
    commission: float = TOTAL_COST,
    plot: bool = True,
    optimize: bool = False,
    strategy_params: dict = None,
) -> pd.DataFrame:
    """
    Run backtest for each ticker and print a consolidated performance table.
    Uses parallel execution (ThreadPoolExecutor, 8 workers) for per-ticker loops.
    One ticker's failure does not prevent other results from being collected.

    Args:
        tickers:         List of NSE/BSE ticker symbols
        strategy_cls:    Strategy class (from strategies/)
        period:          yfinance period string
        cash:            Starting capital in INR
        commission:      Round-trip commission rate (default: realistic Indian market costs)
        plot:            Show backtesting.py chart for the last ticker
        optimize:        Run parameter optimisation (slow — only for single ticker)
        strategy_params: Dict of parameter overrides from Phase 2a optimiser

    Returns:
        DataFrame with per-ticker performance metrics (input ticker order preserved)
    """
    results: Dict[str, Dict] = {}
    _MAX_WORKERS = 8
    _TICKER_TIMEOUT = 60  # per-ticker wall-clock timeout in backtest execution
    
    def _backtest_one(ticker: str) -> tuple[str, Optional[Dict]]:
        """
        Run a single ticker's backtest.
        Returns (ticker, result_dict or None on failure).
        """
        try:
            print(f"  Backtesting {ticker}...", end=" ", flush=True)
            df = fetch_single(ticker, period=period)
            df = add_all_indicators(df)
            # Only require OHLCV present — dropping rows with ANY indicator NaN can punch
            # mid-series gaps and distort bar timing. OHLCV is never NaN so bars stay
            # contiguous; the strategy handles its own indicator warm-up.
            df = df.dropna(subset=["Open", "High", "Low", "Close", "Volume"])

            if len(df) < 60:
                print(f"SKIP (only {len(df)} rows after indicator warmup)")
                return ticker, None

            bt = Backtest(
                df,
                strategy_cls,
                cash=cash,
                commission=commission,
                exclusive_orders=True,
            )

            if optimize and len(tickers) == 1:
                stats = bt.optimize(
                    rsi_oversold=range(25, 45, 5),
                    rsi_overbought=range(55, 75, 5),
                    maximize="Sharpe Ratio",
                    constraint=lambda p: p.rsi_oversold < p.rsi_overbought,
                )
            else:
                stats = bt.run(**(strategy_params or {}))

            result = {
                "Ticker":          ticker,
                "Return (%)":      round(stats["Return [%]"], 2),
                "Buy & Hold (%)":  round(stats["Buy & Hold Return [%]"], 2),
                "Sharpe":          round(stats["Sharpe Ratio"], 2),
                "Max Drawdown (%)":round(stats["Max. Drawdown [%]"], 2),
                "Win Rate (%)":    round(stats["Win Rate [%]"], 2),
                "# Trades":        int(stats["# Trades"]),
                "Profit Factor":   round(stats.get("Profit Factor", 0), 2),
            }
            print(f"✓  Return: {stats['Return [%]']:.1f}%  Sharpe: {stats['Sharpe Ratio']:.2f}")
            return ticker, result

        except Exception as e:
            _log.warning("backtest failed for ticker=%s: %s: %s",
                        ticker, type(e).__name__, e)
            print(f"ERROR — {e}")
            return ticker, None

    print(f"  Backtesting {len(tickers)} ticker(s) in parallel ({_MAX_WORKERS} workers)...")

    # Parallelize backtest execution per ticker (not within a single ticker)
    with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as pool:
        futs = {pool.submit(_backtest_one, t): t for t in tickers}
        for fut in as_completed(futs, timeout=_TICKER_TIMEOUT * len(tickers)):
            try:
                ticker, result = fut.result(timeout=_TICKER_TIMEOUT)
                if result is not None:
                    results[ticker] = result
            except Exception as e:
                ticker_name = futs.get(fut, "unknown")
                _log.warning("backtest future failed for ticker=%s: %s: %s",
                            ticker_name, type(e).__name__, e)

    if not results:
        print("\n  No results to display.")
        return pd.DataFrame()

    # Reassemble results in input ticker order (preserve user's ordering)
    ordered_results = []
    for ticker in tickers:
        if ticker in results:
            ordered_results.append(results[ticker])

    report = pd.DataFrame(ordered_results).set_index("Ticker")

    # ── Summary table ────────────────────────────────────────────────────────
    print(f"\n{'─'*80}")
    print("  BACKTEST SUMMARY")
    print(f"{'─'*80}")
    print(report.to_string())
    print(f"{'─'*80}")
    print(f"\n  Average Return:   {report['Return (%)'].mean():.2f}%")
    print(f"  Average Sharpe:   {report['Sharpe'].mean():.2f}")
    print(f"  Average Drawdown: {report['Max Drawdown (%)'].mean():.2f}%")
    print(f"  Average Win Rate: {report['Win Rate (%)'].mean():.2f}%")
    print(f"  Total Tickers:    {len(report)}")

    # ── Save to CSV ──────────────────────────────────────────────────────────
    out_path = "backtest_results.csv"
    report.to_csv(out_path)
    print(f"\n  Results saved to: {out_path}")

    return report
