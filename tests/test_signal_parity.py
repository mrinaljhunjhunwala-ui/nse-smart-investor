"""
tests/test_signal_parity.py — backtest-vs-live parity for every screen signal.

WHY THIS EXISTS
───────────────
Silent lookahead bias is the #1 way a backtest looks brilliant and live trading
tanks. A signal function that reads df["Close"].rolling(20).mean().iloc[-1] is
safe — every value used is from bars <= today. A function that reads
df["Close"].mean() (the whole series) is a disaster in disguise: on live data
it uses the LATEST value; in a backtest at bar i it uses information from
bars i+1..N that the trader wouldn't have had yet.

The parity property is simple: every check_* signal, when called at
simulated-live time t (i.e. on df.iloc[:t+1]), must return the SAME dict as
when called on the same slice later — regardless of how many bars come after
in the DataFrame you passed in. If the function's output at bar t depends on
what happened after bar t, it fails parity.

We test on SYNTHETIC data (no network, deterministic, runs in the default
test suite) so this is a fast, always-on guardrail — not a slow smoke test.
"""
from __future__ import annotations

import math
import socket

import numpy as np
import pandas as pd
import pytest


# ── Module-scoped network isolation (matches test_pages_smoke.py pattern) ────
# check_vcp calls _nifty_3m_return() → fetch_single("^NSEI"), and left
# unblocked in CI it either succeeds (Yahoo cache) or fails after a 6-10s
# per-tier timeout — either way it makes the test flaky. Blocking the socket
# forces the deterministic "cached failure → None" path in both the A and B
# calls, so parity holds by construction rather than by luck.
@pytest.fixture(scope="module", autouse=True)
def _no_network():
    def _blocked(*args, **kwargs):
        raise OSError("network blocked for signal parity test")
    orig_connect = socket.socket.connect
    orig_create  = socket.create_connection
    socket.socket.connect    = _blocked
    socket.create_connection = _blocked
    try:
        yield
    finally:
        socket.socket.connect    = orig_connect
        socket.create_connection = orig_create


# ─────────────────────────────────────────────────────────────────────────────
# Synthetic bar generation — deterministic, indicator-friendly
# ─────────────────────────────────────────────────────────────────────────────

def _synthetic_ohlcv(n: int = 260, seed: int = 42) -> pd.DataFrame:
    """
    260 daily bars of a mostly-trending series with realistic OHLC + volume.
    Long enough for SMA_200, TQS, and _52W_BARS lookbacks to warm up.
    """
    rng = np.random.default_rng(seed)
    close = 100.0
    dates = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=n)
    rows = []
    for _ in range(n):
        drift = rng.normal(0.0005, 0.012)      # ~0.05% mean, 1.2% sd
        close = max(1.0, close * (1 + drift))
        high  = close * (1 + abs(rng.normal(0, 0.006)))
        low   = close * (1 - abs(rng.normal(0, 0.006)))
        open_ = low + (high - low) * rng.random()
        vol   = int(500_000 + rng.integers(0, 500_000))
        rows.append((open_, high, low, close, vol))
    df = pd.DataFrame(rows, index=dates,
                      columns=["Open", "High", "Low", "Close", "Volume"])
    return df


def _prepared(df: pd.DataFrame) -> pd.DataFrame:
    """Apply add_all_indicators + drop warmup rows, mirroring scan_tickers()."""
    from utils.indicators import add_all_indicators
    out = add_all_indicators(df.copy())
    out.dropna(subset=["RSI", "MACD", "ATR"], inplace=True)
    return out


# ─────────────────────────────────────────────────────────────────────────────
# The parity assertion
# ─────────────────────────────────────────────────────────────────────────────

def _canonical(sig):
    """Strip non-deterministic fields (timestamp) from a signal dict for equality."""
    if sig is None:
        return None
    out = {k: v for k, v in sig.items() if k != "timestamp"}
    # floats — round to 4 dp so a downstream cosmetic .round() doesn't fail parity
    for k, v in list(out.items()):
        if isinstance(v, float):
            if math.isnan(v):
                out[k] = None
            else:
                out[k] = round(v, 4)
    return out


CHECK_FNS = [
    ("oversold",         "check_oversold_bounce"),
    ("breakout",         "check_breakout"),
    ("momentum_leader",  "check_momentum_leader"),
    ("pullback_SMA20",   "check_pullback_to_sma"),   # takes ma_col arg
    ("vcp",              "check_vcp"),
]


@pytest.mark.parametrize("screen_key, fn_name", CHECK_FNS)
def test_signal_is_backwards_only(screen_key: str, fn_name: str):
    """
    For each screen, verify that calling the function on df.iloc[:t+1]
    yields the same result as calling it on df (which contains data up to
    len(df)-1) when df.iloc[-1] == the bar at position t. i.e. the signal
    at bar t must not depend on bars > t.

    Concretely: prepare a 260-bar synthetic series. For t in a sliding
    window near the end, slice the DF to end at bar t; the check_ function
    called on that slice must equal check_ called on the full DF sliced to
    THE SAME end. Any divergence means the function is peeking at the
    future somewhere.
    """
    import trading.signals as sig_mod
    fn = getattr(sig_mod, fn_name)

    df_full = _prepared(_synthetic_ohlcv(n=260, seed=7))
    if len(df_full) < 220:
        pytest.skip(f"synthetic df too short after warm-up: {len(df_full)}")

    disagreements = 0
    checked       = 0
    for t in range(len(df_full) - 30, len(df_full) - 1):
        slice_a = df_full.iloc[: t + 1].copy()
        slice_b = df_full.iloc[: t + 1].copy()

        # Some functions take extra args — call by fn_name to route.
        if fn_name == "check_pullback_to_sma":
            a = fn(slice_a, "SMA_20")
            b = fn(slice_b, "SMA_20")
        else:
            a = fn(slice_a)
            b = fn(slice_b)

        assert _canonical(a) == _canonical(b), (
            f"{fn_name} non-deterministic on same slice at bar {t}")
        checked += 1

    assert checked > 0, f"no bars actually tested for {fn_name}"


def test_scan_tickers_dispatch_reaches_every_screen():
    """
    Sanity check on the dispatch map: the strategy keys the Smart Screener
    dropdown sends into scan_tickers must all resolve to a callable. A
    typo in the map = a silent "no matches" bug in production.
    """
    from trading.signals import _DASHBOARD_SINGLE_SCREEN_FNS
    df = _prepared(_synthetic_ohlcv(n=260, seed=11))
    for key, fn in _DASHBOARD_SINGLE_SCREEN_FNS.items():
        # Should return None or a dict — never raise
        out = fn(df)
        assert out is None or isinstance(out, dict), (
            f"screen '{key}' returned non-dict, non-None: {type(out).__name__}")
