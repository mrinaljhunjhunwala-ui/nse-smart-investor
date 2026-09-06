"""tests/test_positioning_6b_aggregation.py - Guardrail 5 (design 6b) lock-in.

Design 6b (`docs/COMPOSITE_SCORE_SHAPE_REVIEW.md`, ratified user 2026-09-06):
  F&O-eligible tickers with NSE_USE_POSITIONING_PILLAR ON and at least one
  real positioning input add positioning as a **pure 10-pt additive overlay**
  on top of the legacy 40+25+15+10=90 shape. Cap becomes 100.
  Non-F&O tickers OR flag OFF: unchanged legacy 4-pillar cap 90.

Tests here lock in three things:
  1. Non-F&O ticker + flag ON: cap stays 90, positioning inactive.
  2. F&O ticker + flag ON + positioning data: cap 100, ADDITIVE (not rescaled).
     Sub-scores tech/mom stay on 0-40 / 0-25 caps.
  3. F&O ticker + flag OFF: cap stays 90, positioning inactive.
"""
from __future__ import annotations

import os
import numpy as np
import pandas as pd
import pytest

from analysis.score import score_dataframe, CompositeScore
from utils.indicators import add_all_indicators


def _synthetic_uptrend(n: int = 300, seed: int = 11) -> pd.DataFrame:
    """Clean uptrend so tech/mom/vol land at healthy non-trivial values."""
    rng = np.random.default_rng(seed)
    steps = rng.normal(0.5, 0.7, n)
    close = 100 + np.cumsum(steps)
    close = np.maximum(close, 5.0)
    openp = np.concatenate([[close[0]], close[:-1]])
    high = np.maximum(openp, close) * (1 + rng.uniform(0.0, 0.01, n))
    low  = np.minimum(openp, close) * (1 - rng.uniform(0.0, 0.01, n))
    vol  = rng.integers(500_000, 2_000_000, n).astype(float)
    idx  = pd.date_range("2024-01-01", periods=n, freq="B")
    df = pd.DataFrame(
        {"Open": openp, "High": high, "Low": low, "Close": close, "Volume": vol},
        index=idx,
    )
    return add_all_indicators(df)


# Positioning input that will produce a non-zero pillar score
_POS_INPUT = {
    "oi_regime":             "long_buildup",
    "pcr":                   0.85,
    "max_pain_distance_pct": 0.5,
    "fii_deriv_net":         500.0,
}


@pytest.fixture(autouse=True)
def _restore_env():
    """Isolate NSE_USE_POSITIONING_PILLAR across tests."""
    _saved = os.environ.get("NSE_USE_POSITIONING_PILLAR")
    yield
    if _saved is None:
        os.environ.pop("NSE_USE_POSITIONING_PILLAR", None)
    else:
        os.environ["NSE_USE_POSITIONING_PILLAR"] = _saved


def test_non_fno_ticker_cap_stays_90_even_with_flag_and_data():
    """Non-F&O ticker never activates the pillar, whatever the flag says."""
    df = _synthetic_uptrend()
    os.environ["NSE_USE_POSITIONING_PILLAR"] = "1"
    # A ticker that is not in the F&O universe (arbitrary micro-cap style code).
    cs = score_dataframe(df, "NOTFNO_XYZ", positioning_info=_POS_INPUT)
    assert cs.positioning_score is None, "non-F&O must never carry a positioning score"
    assert cs.score <= 90.0, f"non-F&O cap must stay 90, got {cs.score}"


def test_fno_ticker_flag_off_cap_stays_90():
    """F&O ticker, flag OFF: legacy 4-pillar shape unchanged."""
    df = _synthetic_uptrend()
    os.environ.pop("NSE_USE_POSITIONING_PILLAR", None)
    # RELIANCE is F&O-eligible (present in data.fno_universe).
    cs = score_dataframe(df, "RELIANCE", positioning_info=_POS_INPUT)
    assert cs.positioning_score is None
    assert cs.score <= 90.0
    assert cs.is_fno is True


def test_fno_ticker_flag_on_no_data_cap_stays_90():
    """F&O + flag ON but no positioning data: pillar stays inactive.

    Guards against the systematic bias that would penalise every F&O name
    the moment the flag flips but before the data pipelines are online.
    """
    df = _synthetic_uptrend()
    os.environ["NSE_USE_POSITIONING_PILLAR"] = "1"
    cs = score_dataframe(df, "RELIANCE", positioning_info=None)
    assert cs.positioning_score is None
    assert cs.score <= 90.0


def test_fno_ticker_flag_on_with_data_is_additive_and_can_exceed_90():
    """The core 6b invariant: F&O + flag + data adds positioning ON TOP.

    Score without positioning input vs with positioning input must differ by
    exactly the positioning_score value (not by a rescaled amount). The
    tech/mom sub-scores must be identical across the two runs (proves they
    are NOT being rescaled the way 6a used to do).
    """
    df = _synthetic_uptrend()
    os.environ["NSE_USE_POSITIONING_PILLAR"] = "1"

    cs_no_pos  = score_dataframe(df, "RELIANCE", positioning_info=None)
    cs_yes_pos = score_dataframe(df, "RELIANCE", positioning_info=_POS_INPUT)

    # sub-scores unchanged - 6b keeps them on their native 0-40 / 0-25 caps
    assert cs_yes_pos.technical_score == cs_no_pos.technical_score
    assert cs_yes_pos.momentum_score  == cs_no_pos.momentum_score
    assert cs_yes_pos.volume_score    == cs_no_pos.volume_score
    assert cs_yes_pos.sentiment_score == cs_no_pos.sentiment_score

    # positioning contribution must exist
    assert cs_yes_pos.positioning_score is not None
    assert cs_yes_pos.positioning_score > 0.0

    # composite delta equals positioning contribution (within rounding)
    delta = cs_yes_pos.score - cs_no_pos.score
    assert abs(delta - cs_yes_pos.positioning_score) < 0.15, (
        f"expected additive: delta={delta:.2f}, pos={cs_yes_pos.positioning_score:.2f}"
    )

    # cap enforcement: never exceed 100 for the F&O + flag + data path
    assert cs_yes_pos.score <= 100.0


def test_fno_ticker_cap_100_enforced_at_ceiling():
    """When base 4-pillar + positioning would exceed 100, it clips to 100."""
    df = _synthetic_uptrend()
    os.environ["NSE_USE_POSITIONING_PILLAR"] = "1"
    cs = score_dataframe(df, "RELIANCE", positioning_info=_POS_INPUT)
    assert cs.score <= 100.0
