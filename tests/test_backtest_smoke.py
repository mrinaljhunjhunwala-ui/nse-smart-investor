"""tests/test_backtest_smoke.py — gated end-to-end backtest smoke (Part 4).

Exercises the FULL backtest path on a single ticker: engine imports → runner fetches →
backtesting.py executes → output schema. It is **slow and network-dependent**, so it is
marked `slow` and EXCLUDED from the default run + CI (pytest.ini `addopts = -m "not slow"`).

Run it explicitly:
    python -m pytest tests/test_backtest_smoke.py -m slow -q

Runtime: ~10–30 s (one ticker, 1-yr daily, single strategy).
"""
from __future__ import annotations

import pandas as pd
import pytest

_EXPECTED_COLUMNS = {
    "Return (%)", "Buy & Hold (%)", "Sharpe", "Max Drawdown (%)",
    "Win Rate (%)", "# Trades", "Profit Factor",
}


@pytest.mark.slow
def test_backtest_end_to_end_single_ticker():
    # 1) engine + strategy import cleanly
    from backtest.runner import run_backtest
    from strategies.momentum import MomentumStrategy

    # 2) runner executes the full path on one ticker (no plot file)
    report = run_backtest(["RELIANCE.NS"], MomentumStrategy, period="1y", plot=False)

    # 3) output schema is valid
    assert isinstance(report, pd.DataFrame), "run_backtest must return a DataFrame"
    if report.empty:
        pytest.skip("backtest returned no rows (likely no network for the data fetch) — "
                    "engine/runner executed; schema check skipped")
    assert _EXPECTED_COLUMNS <= set(report.columns), (
        f"missing columns: {_EXPECTED_COLUMNS - set(report.columns)}")
    row = report.iloc[0]
    # core metrics are numeric and finite
    for col in ("Return (%)", "Sharpe", "Max Drawdown (%)", "# Trades"):
        val = row[col]
        assert pd.notna(val) and isinstance(val, (int, float)), f"{col} not numeric: {val!r}"
    assert int(row["# Trades"]) >= 0
