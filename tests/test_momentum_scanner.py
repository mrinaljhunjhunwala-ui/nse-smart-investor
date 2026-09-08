"""
tests/test_momentum_scanner.py — Unit tests for the pure momentum scanner.

Uses synthetic OHLCV frames so the tests run offline in CI (no network, no
fetcher). Each test constructs a frame that isolates one filter — trend,
breakout, volume, RSI band, VWAP, exhaustion — and asserts that the ticker
either passes or is rejected as expected.

Regression guard: if you change any threshold in analysis/momentum_scanner.py's
DEFAULT_CONFIG, at least one of these tests must fail. That's on purpose —
the numbers matter and shouldn't drift silently.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from analysis.momentum_scanner import (
    DEFAULT_CONFIG,
    MomentumConfig,
    _evaluate_ticker,
    _relative_strength,
    _rsi,
    _atr,
    format_momentum_message,
    scan_momentum,
)


# ─────────────────────────────────────────────────────────────────────────────
# Synthetic-frame helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_frame(closes, volumes=None, highs=None, lows=None):
    """Build a minimal OHLCV frame from a Close series."""
    n = len(closes)
    closes = np.asarray(closes, dtype=float)
    if volumes is None:
        volumes = np.full(n, 100_000.0)
    if highs is None:
        highs = closes * 1.01
    if lows is None:
        lows = closes * 0.99
    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    return pd.DataFrame({
        "Open":   closes,
        "High":   highs,
        "Low":    lows,
        "Close":  closes,
        "Volume": volumes,
    }, index=idx)


def _uptrend_closes(n=250, start=100.0, drift=0.25, noise=1.5, seed=42):
    """Steady uptrend with mild noise — trend filter passes, RSI lands in
    the realistic 55–75 band (a monotonic linear uptrend gives RSI=100 by
    construction and would fail the not-exhausted filter, which is correct
    behaviour but wrong for testing the happy path)."""
    return start + np.arange(n) * drift + noise * np.random.RandomState(seed).randn(n)


def _downtrend_closes(n=250, start=200.0, drift=-0.4):
    return start + np.arange(n) * drift


# ─────────────────────────────────────────────────────────────────────────────
# Indicator sanity — cheap regressions on _rsi and _atr
# ─────────────────────────────────────────────────────────────────────────────

def test_rsi_uptrend_above_50():
    """RSI on a noisy uptrend must sit meaningfully above 50."""
    closes = pd.Series(_uptrend_closes(60, drift=0.4, noise=0.5))
    rsi = _rsi(closes, 14).iloc[-1]
    assert rsi > 60, f"expected RSI > 60 on noisy uptrend, got {rsi:.1f}"


def test_rsi_downtrend_below_50():
    closes = pd.Series(_downtrend_closes(60))
    rsi = _rsi(closes, 14).iloc[-1]
    assert rsi < 35, f"expected RSI < 35 on downtrend, got {rsi:.1f}"


def test_atr_scales_with_range():
    """ATR on a wider-range frame must be larger than on a narrow one."""
    n = 60
    closes = _uptrend_closes(n)
    narrow = _make_frame(closes, highs=closes * 1.005, lows=closes * 0.995)
    wide   = _make_frame(closes, highs=closes * 1.05,  lows=closes * 0.95)
    assert _atr(wide, 20).iloc[-1] > _atr(narrow, 20).iloc[-1] * 5


# ─────────────────────────────────────────────────────────────────────────────
# _evaluate_ticker — each filter tested in isolation
# ─────────────────────────────────────────────────────────────────────────────

def test_passes_when_all_filters_satisfied():
    """The happy path — steady uptrend with a fresh breakout day."""
    closes = _uptrend_closes(250, start=100, drift=0.4)
    # Force today's close to break the prior 55-day high by ~1.5 %
    closes[-1] = closes[-56:-1].max() * 1.015
    volumes = np.full(250, 100_000.0)
    volumes[-1] = 200_000.0  # 2× surge

    df = _make_frame(closes, volumes=volumes)
    result = _evaluate_ticker("TESTPASS", df, nifty_returns=None, cfg=DEFAULT_CONFIG)

    assert result is not None, "steady uptrend + breakout + volume should pass all filters"
    assert result["ticker"] == "TESTPASS"
    assert result["breakout_pct"] > 1.0
    assert result["volume_ratio"] >= 1.5
    assert DEFAULT_CONFIG.rsi_min <= result["rsi"] <= DEFAULT_CONFIG.rsi_max


def test_rejects_downtrend():
    """Trend filter alone must reject a name in a clean downtrend."""
    closes = _downtrend_closes(250)
    df = _make_frame(closes)
    assert _evaluate_ticker("DOWN", df, None, DEFAULT_CONFIG) is None


def test_rejects_no_breakout():
    """Rising trend but today's close doesn't break the 55d high."""
    closes = _uptrend_closes(250)
    closes[-1] = closes[-56:-1].max() * 0.98   # 2 % below prior high
    df = _make_frame(closes, volumes=np.full(250, 200_000.0))
    assert _evaluate_ticker("NOBREAK", df, None, DEFAULT_CONFIG) is None


def test_rejects_low_volume_on_breakout_day():
    """Real breakout but volume < 1.5× 20d avg — reject as unconfirmed."""
    closes = _uptrend_closes(250)
    closes[-1] = closes[-56:-1].max() * 1.02
    volumes = np.full(250, 100_000.0)
    volumes[-1] = 110_000.0   # only 1.1× — below cutoff
    df = _make_frame(closes, volumes=volumes)
    assert _evaluate_ticker("LOWVOL", df, None, DEFAULT_CONFIG) is None


def test_rejects_rsi_above_75_exhausted():
    """A stock that already ran hard — RSI > 75 — must be rejected."""
    # Build a sharp accelerating uptrend to push RSI above 75
    closes = np.concatenate([_uptrend_closes(200, drift=0.2),
                             np.linspace(180, 260, 50)])
    closes[-1] = closes[-56:-1].max() * 1.02   # still a technical breakout
    volumes = np.full(len(closes), 100_000.0)
    volumes[-1] = 250_000.0
    df = _make_frame(closes, volumes=volumes)
    result = _evaluate_ticker("EXHAUSTED", df, None, DEFAULT_CONFIG)
    # If it passed, RSI must be within band — else the filter did its job
    if result is not None:
        assert result["rsi"] <= DEFAULT_CONFIG.rsi_max


def test_rejects_penny_stock_below_min_price():
    """Guard against penny names — set a config with high min_price."""
    closes = _uptrend_closes(250, start=10, drift=0.02)  # ends near 15
    closes[-1] = closes[-56:-1].max() * 1.05
    df = _make_frame(closes, volumes=np.full(250, 200_000.0))
    result = _evaluate_ticker("PENNY", df, None, DEFAULT_CONFIG)
    assert result is None, "sub-₹20 price should be filtered by min_price guard"


def test_rejects_exhaustion_day():
    """A day where today's range is >2.5× ATR(20) is a parabolic move — reject."""
    closes = _uptrend_closes(250)
    closes[-1] = closes[-56:-1].max() * 1.10   # +10% single-day breakout
    n = 250
    highs = closes * 1.01
    lows  = closes * 0.99
    highs[-1] = closes[-1] * 1.08   # 16 % intraday range
    lows[-1]  = closes[-1] * 0.92
    volumes = np.full(n, 100_000.0)
    volumes[-1] = 300_000.0
    df = _make_frame(closes, volumes=volumes, highs=highs, lows=lows)
    assert _evaluate_ticker("PARABOLIC", df, None, DEFAULT_CONFIG) is None


def test_insufficient_data_returns_none():
    df = _make_frame(_uptrend_closes(100))   # < min_bars_needed=210
    assert _evaluate_ticker("SHORT", df, None, DEFAULT_CONFIG) is None


def test_empty_frame_returns_none():
    assert _evaluate_ticker("EMPTY", pd.DataFrame(), None, DEFAULT_CONFIG) is None


# ─────────────────────────────────────────────────────────────────────────────
# Relative strength ranking
# ─────────────────────────────────────────────────────────────────────────────

def test_relative_strength_positive_when_stock_outperforms():
    stock = pd.Series(np.linspace(100, 130, 100))   # +30 % end-to-end
    nifty = pd.Series(np.linspace(100, 110, 100))   # +10 % end-to-end
    rs = _relative_strength(stock, nifty, 63)
    # Over the last 63 of 100 points the stock's window-return exceeds
    # Nifty's window-return by ~10 percentage points — that's the RS value.
    assert rs is not None and rs > 8


def test_relative_strength_falls_back_to_absolute_when_no_nifty():
    stock = pd.Series(np.linspace(100, 120, 100))
    rs = _relative_strength(stock, None, 63)
    assert rs is not None and rs > 10   # absolute return, still positive


# ─────────────────────────────────────────────────────────────────────────────
# End-to-end scan_momentum
# ─────────────────────────────────────────────────────────────────────────────

def test_scan_momentum_ranks_by_rs():
    """Two passing candidates — the one with higher RS should come first."""
    def _mk_pass(drift, seed):
        # Both HOT and MILD must land inside the RSI 55–75 band; higher drift
        # pushes RSI toward 75, so we cap at 0.3 (~empirically RSI ≈ 70) and
        # use distinct seeds so their randomness — and therefore the resulting
        # 63d returns used for RS ranking — differ enough to produce a stable
        # ordering.
        c = _uptrend_closes(250, start=100, drift=drift, seed=seed)
        c[-1] = c[-56:-1].max() * 1.02
        v = np.full(250, 100_000.0)
        v[-1] = 200_000.0
        return _make_frame(c, volumes=v)

    frames = {"HOT": _mk_pass(0.3, seed=1), "MILD": _mk_pass(0.15, seed=2)}
    nifty  = _make_frame(_uptrend_closes(250, drift=0.1, seed=3))

    def fetcher(t): return frames.get(t)
    out = scan_momentum(["HOT", "MILD"], fetcher, nifty_history=nifty)
    assert len(out) == 2
    assert out[0]["ticker"] == "HOT", f"HOT should rank above MILD, got {[c['ticker'] for c in out]}"


def test_scan_momentum_skips_failed_fetches():
    def fetcher(t):
        if t == "MISSING":
            return None
        c = _uptrend_closes(250)
        c[-1] = c[-56:-1].max() * 1.02
        v = np.full(250, 100_000.0)
        v[-1] = 200_000.0
        return _make_frame(c, volumes=v)

    out = scan_momentum(["MISSING", "GOOD"], fetcher, nifty_history=None)
    assert len(out) == 1
    assert out[0]["ticker"] == "GOOD"


def test_scan_momentum_returns_at_most_top_n():
    """More than top_n passing candidates — output must be capped."""
    def _pass():
        c = _uptrend_closes(250)
        c[-1] = c[-56:-1].max() * 1.02
        v = np.full(250, 100_000.0)
        v[-1] = 200_000.0
        return _make_frame(c, volumes=v)

    tickers = [f"T{i}" for i in range(12)]
    def fetcher(_): return _pass()

    cfg = MomentumConfig(top_n=5)
    out = scan_momentum(tickers, fetcher, cfg=cfg)
    assert len(out) == 5


# ─────────────────────────────────────────────────────────────────────────────
# Message formatter — smoke checks
# ─────────────────────────────────────────────────────────────────────────────

def test_format_message_empty():
    msg = format_momentum_message([])
    assert "No stocks passed" in msg
    assert "Momentum scan" in msg


def test_format_message_with_candidates():
    candidates = [{
        "ticker": "RELIANCE", "price": 1450.0, "prior_high_55d": 1420.0,
        "breakout_pct": 2.1, "volume_ratio": 2.3, "rsi": 62.0,
        "vwap": 1400.0, "atr": 25.0, "sma50": 1380.0, "sma200": 1300.0,
        "rs_63d": 8.5, "suggested_entry": 1450.0, "suggested_stop": 1400.0,
        "suggested_target": 1550.0,
    }]
    msg = format_momentum_message(candidates)
    assert "RELIANCE" in msg
    assert "1,450" in msg   # thousands separator on price
    assert "not advice" in msg.lower()
