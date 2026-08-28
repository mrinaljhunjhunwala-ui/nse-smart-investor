"""tests/test_mtf_alignment.py — regression test for check_daily_weekly_alignment.

NO AI, no network. Deterministic synthetic OHLCV frames only.

Covers the real bug found in a repo audit: analysis/mtf.py's
check_daily_weekly_alignment(df) took exactly one argument, but
dashboard/pages/13_swing_checklist.py called it with two
(check_daily_weekly_alignment(_sc_df_daily, _sc_df_weekly)) — a leftover from a
fix that started fetching real weekly bars but never updated the function to
accept them. The call was wrapped in a try/except, so it never crashed the
page, but it silently failed the MTF checklist item on every single run.

Fix: check_daily_weekly_alignment gained an optional weekly_df parameter.
When provided, it's used directly (real exchange-reported weekly bars, not a
daily->weekly resample); when omitted, behaviour is unchanged from before.

These tests would have caught the original bug (test_two_positional_args_matches_swing_checklist_call_pattern
reproduces the exact call shape that used to raise TypeError) and guard
against a regression where the passed-in weekly_df is silently ignored.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from analysis.mtf import check_daily_weekly_alignment, resample_weekly


def _trending_ohlc(n: int, start: float = 100.0, drift: float = 0.5,
                   freq: str = "B") -> pd.DataFrame:
    """n bars of a clean straight-line trend (positive drift = bullish,
    negative = bearish) — enough bars and a strong enough slope to clear
    get_trend_direction's minimum-length guard and MA-spread thresholds."""
    dates = pd.date_range("2022-01-03", periods=n, freq=freq)
    closes = start + np.arange(n) * drift
    return pd.DataFrame({
        "Open": closes, "High": closes + abs(drift), "Low": closes - abs(drift),
        "Close": closes, "Volume": 1_000_000,
    }, index=dates)


class TestBackwardCompatibility:
    """Single-argument calls (every pre-existing caller) must behave exactly
    as before the fix — weekly_df defaults to a resample of df."""

    def test_single_arg_still_works(self):
        daily = _trending_ohlc(300, drift=0.5)   # clean uptrend, > 1y of daily bars
        result = check_daily_weekly_alignment(daily)
        assert result["alignment"] == "bullish"
        assert result["aligned"] is True

    def test_single_arg_matches_explicit_resample(self):
        """Omitting weekly_df must produce the identical result to passing
        resample_weekly(df) explicitly — the default path and the explicit
        path should be one and the same code path, not two implementations."""
        daily = _trending_ohlc(300, drift=0.5)
        implicit = check_daily_weekly_alignment(daily)
        explicit = check_daily_weekly_alignment(daily, resample_weekly(daily))
        assert implicit["alignment"] == explicit["alignment"]
        assert implicit["confirmation"] == explicit["confirmation"]


class TestExplicitWeeklyDfIsActuallyUsed:
    """The whole point of the fix: a passed-in weekly_df must be used as-is,
    not silently discarded in favour of resampling df."""

    def test_explicit_bearish_weekly_overrides_resampled_bullish(self):
        daily_bullish = _trending_ohlc(300, drift=0.5)          # daily: uptrend
        weekly_bearish = _trending_ohlc(80, start=500.0, drift=-4.0, freq="W")  # weekly: downtrend

        result = check_daily_weekly_alignment(daily_bullish, weekly_bearish)

        # If the bug regressed (weekly_df silently ignored, falling back to
        # resample_weekly(daily_bullish)), this would come back "bullish"/aligned
        # instead — that's exactly the wrong-signal failure mode the fix closes.
        assert result["daily"]["direction"] == "bullish"
        assert result["weekly"]["direction"] == "bearish"
        assert result["alignment"] == "mixed"
        assert result["aligned"] is False
        assert "counter-trend" in result["confirmation"].lower()

    def test_empty_weekly_df_falls_back_to_resample(self):
        """An empty (but non-None) weekly_df — e.g. a failed fetch that
        returned an empty frame rather than None — must fall back safely
        instead of feeding get_trend_direction an empty frame."""
        daily = _trending_ohlc(300, drift=0.5)
        result = check_daily_weekly_alignment(daily, pd.DataFrame())
        assert result["alignment"] == "bullish"   # same as the no-arg case


class TestSwingChecklistCallPattern:
    """Reproduces the exact call shape from dashboard/pages/13_swing_checklist.py
    that used to raise TypeError: check_daily_weekly_alignment() takes 1
    positional argument but 2 were given."""

    def test_two_positional_args_matches_swing_checklist_call_pattern(self):
        sc_df_daily = _trending_ohlc(300, drift=0.5)
        sc_df_weekly = _trending_ohlc(80, start=500.0, drift=1.0, freq="W")

        # This is the literal call from 13_swing_checklist.py line ~152.
        # Before the fix, this line raised TypeError on every checklist run.
        mtf = check_daily_weekly_alignment(sc_df_daily, sc_df_weekly)

        assert isinstance(mtf, dict)
        assert set(mtf.keys()) == {"aligned", "alignment", "daily", "weekly", "confirmation"}
        assert mtf["alignment"] in ("bullish", "bearish", "mixed")
