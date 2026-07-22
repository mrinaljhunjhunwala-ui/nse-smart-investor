"""tests/test_signals_breakout.py — regression coverage for
trading/signals.py's check_breakout().

FIX BRK-ADX: check_breakout() fetched `adx` from the dataframe but never
used it anywhere — not in a threshold check, not in the returned dict, not
in the reason string. A breakout near its 52-week high with no real trend
strength behind it (low ADX) is a much likelier fakeout than a confirmed
move, and the sibling screen check_momentum_leader() already correctly
gates on this (adx < 20). check_breakout() now does the same.

This module had no dedicated test file before this one.
"""
import numpy as np
import pandas as pd
import pytest

from trading.signals import check_breakout


def _make_df(adx=30.0, rsi=65.0, vol_ratio=2.0, n=60):
    """Synthetic breakout setup: price at its 52-week high, healthy volume,
    RSI comfortably below the overbought cutoff. `adx` is the only knob
    the FIX BRK-ADX tests vary."""
    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    close = np.linspace(100, 150, n)  # steadily rising -> last bar is the high
    df = pd.DataFrame({
        "Close":         close,
        "High":          close,
        "RSI":           [rsi] * n,
        "Volume_Ratio":  [vol_ratio] * n,
        "ADX":           [adx] * n,
        "ATR":           [2.0] * n,
    }, index=idx)
    return df


def test_strong_trend_confirms_breakout():
    """ADX well above the 20 cutoff — breakout should fire as before."""
    result = check_breakout(_make_df(adx=30.0))
    assert result is not None
    assert result["screen"] == "Breakout"


def test_weak_trend_now_blocks_breakout():
    """FIX BRK-ADX — ADX below 20 (weak/no trend) must now block the
    signal. Before the fix, adx was fetched but never checked, so this
    would have incorrectly fired a BUY."""
    result = check_breakout(_make_df(adx=15.0))
    assert result is None


def test_adx_exactly_at_threshold_is_not_blocked():
    """adx == 20 should NOT be blocked — the gate is strictly '< 20'."""
    result = check_breakout(_make_df(adx=20.0))
    assert result is not None


def test_missing_adx_does_not_block():
    """NaN ADX (e.g. insufficient history to compute it) must not itself
    block a signal — same graceful-degradation convention as the other
    NaN-tolerant checks in this function (vol_ratio, etc.)."""
    df = _make_df(adx=30.0)
    df["ADX"] = np.nan
    result = check_breakout(df)
    assert result is not None
    assert result["adx"] is None


def test_adx_surfaced_in_result_and_reason():
    """The adx value should now be visible in the output, not silently
    computed and discarded."""
    result = check_breakout(_make_df(adx=27.5))
    assert result is not None
    assert result["adx"] == 27.5
    assert "ADX=27.5" in result["reason"]


def test_still_blocks_on_existing_conditions():
    """Sanity check the fix didn't loosen or bypass the pre-existing gates
    (overbought RSI should still block, independent of ADX)."""
    result = check_breakout(_make_df(adx=30.0, rsi=85.0))
    assert result is None
