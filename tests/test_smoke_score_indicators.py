"""
Smoke tests for the scoring engine (analysis/score.py) and technical indicators
(utils/indicators.py).

These are intentionally lightweight behavioural checks — they feed known synthetic
OHLCV (a clean uptrend and a clean downtrend) and assert that:
  * indicators stay in their valid ranges (RSI 0-100, MACD sign tracks trend),
  * the composite score is well-formed (0-100, graded, component caps respected),
  * the engine ranks an uptrend higher than a downtrend.

They exist to catch gross regressions when the dashboard refactor merges and when
score/indicator internals change later. Run with:  py -m pytest tests/ -q
"""
import os
import sys

import numpy as np
import pandas as pd
import pytest

# ── make the project root importable regardless of where pytest is invoked ──
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from utils.indicators import (  # noqa: E402
    add_all_indicators, add_rsi, add_macd,
)
from analysis.score import score_dataframe  # noqa: E402


def _ohlcv(direction: str, n: int = 300, seed: int = 7) -> pd.DataFrame:
    """Synthetic daily OHLCV with a clear drift. `direction` = 'up' or 'down'.
    Drift dominates noise so the trend is unambiguous, but noise guarantees some
    down-days (needed so RSI's avg_loss is non-zero and the value is finite)."""
    rng = np.random.default_rng(seed)
    drift = 0.6 if direction == "up" else -0.6
    steps = rng.normal(drift, 0.8, n)
    close = 100 + np.cumsum(steps)
    close = np.maximum(close, 5.0)          # keep prices positive
    openp = np.concatenate([[close[0]], close[:-1]])
    high = np.maximum(openp, close) * (1 + rng.uniform(0.0, 0.01, n))
    low = np.minimum(openp, close) * (1 - rng.uniform(0.0, 0.01, n))
    vol = rng.integers(500_000, 2_000_000, n).astype(float)
    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    return pd.DataFrame(
        {"Open": openp, "High": high, "Low": low, "Close": close, "Volume": vol},
        index=idx,
    )


# ─────────────────────────── indicators.py ───────────────────────────

def test_rsi_in_range_and_tracks_trend():
    rsi_up = add_rsi(_ohlcv("up"))["RSI"].dropna()
    rsi_dn = add_rsi(_ohlcv("down"))["RSI"].dropna()
    assert len(rsi_up) and len(rsi_dn)
    # always bounded 0-100
    assert rsi_up.between(0, 100).all()
    assert rsi_dn.between(0, 100).all()
    # an uptrend should read momentum-strong, a downtrend momentum-weak
    assert rsi_up.iloc[-1] > 50 > rsi_dn.iloc[-1]


def test_macd_sign_tracks_trend():
    up = add_macd(_ohlcv("up"))
    dn = add_macd(_ohlcv("down"))
    for col in ("MACD", "MACD_Signal", "MACD_Hist"):
        assert col in up.columns
    # fast EMA above slow EMA in an uptrend (MACD > 0), below in a downtrend
    assert up["MACD"].iloc[-1] > 0 > dn["MACD"].iloc[-1]


def test_add_all_indicators_runs_and_populates():
    df = add_all_indicators(_ohlcv("up"))
    for col in ("SMA_20", "RSI", "MACD", "ATR", "BB_Upper"):
        assert col in df.columns, f"missing indicator column {col}"
    # last row should have finite core indicators (enough history for warm-up)
    last = df.iloc[-1]
    assert np.isfinite(last["RSI"]) and np.isfinite(last["MACD"])


# ─────────────────────────── score.py ───────────────────────────

def _score(direction: str):
    df = add_all_indicators(_ohlcv(direction))
    return score_dataframe(df, ticker="TEST.NS", sector="Other")


def test_score_is_well_formed():
    cs = _score("up")
    assert 0 <= cs.score <= 100
    assert isinstance(cs.grade, str) and cs.grade
    assert isinstance(cs.action, str) and cs.action
    # component scores respect their documented caps
    assert 0 <= cs.technical_score <= 40
    assert 0 <= cs.momentum_score <= 25
    assert 0 <= cs.volume_score <= 15
    assert 0 <= cs.pattern_score <= 10
    assert 0 <= cs.sentiment_score <= 10


def test_score_entry_levels_sane():
    cs = _score("up")
    assert cs.entry > 0 and cs.stop_loss > 0 and cs.target > 0
    assert cs.risk_reward > 0


def test_uptrend_scores_higher_than_downtrend():
    up = _score("up").score
    dn = _score("down").score
    assert up > dn, f"expected uptrend ({up}) to outscore downtrend ({dn})"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
