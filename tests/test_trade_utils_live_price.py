"""tests/test_trade_utils_live_price.py — _fetch_single_live_price /
_portfolio_live_prices bounded-wait behavior.

FIX TU-WAIT1 regression coverage: _fetch_single_live_price() was the one
caller of utils.live_price.get_live_prices_batch() in the app that didn't
pass max_wait_seconds, so with Angel One unavailable it could block up to
30s per ticker (and _portfolio_live_prices() looped this sequentially per
holding — up to 30s × N holdings). These tests assert the bound is actually
threaded through, not just present in a docstring.

No live network — utils.live_price.get_live_prices_batch is always
monkeypatched, matching this repo's "no live network in the default test
suite" convention.
"""
from __future__ import annotations

import pytest

from dashboard.shared import trade_utils as tu
import utils.live_price as lp


@pytest.fixture(autouse=True)
def _clear_price_caches():
    """_fetch_single_live_price / _portfolio_live_prices are @st.cache_data
    — clear before each test so one test's cached result can't leak into
    the next (they'd otherwise share a process-wide cache across tests)."""
    tu._fetch_single_live_price.clear()
    tu._portfolio_live_prices.clear()
    yield
    tu._fetch_single_live_price.clear()
    tu._portfolio_live_prices.clear()


def test_fetch_single_live_price_passes_default_max_wait(monkeypatch):
    calls = []

    def _fake_batch(symbols, max_workers=8, max_wait_seconds=None):
        calls.append((tuple(symbols), max_wait_seconds))
        return {symbols[0]: {"price": 100.0, "prev_close": 99.0, "chg_pct": 1.01}}

    monkeypatch.setattr(lp, "get_live_prices_batch", _fake_batch)

    result = tu._fetch_single_live_price("RELIANCE")
    assert result["price"] == 100.0
    assert len(calls) == 1
    assert calls[0][1] == 10, (
        "_fetch_single_live_price must bound get_live_prices_batch's wait — "
        f"got max_wait_seconds={calls[0][1]!r}, expected 10 (matching nav.py's "
        "own precedent for single/few-ticker interactive lookups)"
    )


def test_fetch_single_live_price_accepts_explicit_override(monkeypatch):
    calls = []

    def _fake_batch(symbols, max_workers=8, max_wait_seconds=None):
        calls.append(max_wait_seconds)
        return {symbols[0]: {"price": 50.0, "prev_close": 49.0, "chg_pct": 2.0}}

    monkeypatch.setattr(lp, "get_live_prices_batch", _fake_batch)

    tu._fetch_single_live_price("TCS", max_wait_seconds=3)
    assert calls == [3]


def test_portfolio_live_prices_uses_tighter_bound_per_ticker(monkeypatch):
    """Sequential across holdings — must use a tighter bound than the
    single-ticker default so a multi-holding portfolio doesn't multiply the
    10s default into a minutes-long page load."""
    calls = []

    def _fake_batch(symbols, max_workers=8, max_wait_seconds=None):
        calls.append((tuple(symbols), max_wait_seconds))
        return {symbols[0]: {"price": 10.0, "prev_close": 9.5, "chg_pct": 5.0}}

    monkeypatch.setattr(lp, "get_live_prices_batch", _fake_batch)

    result = tu._portfolio_live_prices(("RELIANCE", "TCS", "INFY"))
    assert set(result.keys()) == {"RELIANCE", "TCS", "INFY"}
    assert len(calls) == 3
    assert all(c[1] == 6 for c in calls), (
        f"expected max_wait_seconds=6 for every holding, got {calls}"
    )


def test_portfolio_live_prices_one_bad_ticker_does_not_poison_others(monkeypatch):
    def _fake_batch(symbols, max_workers=8, max_wait_seconds=None):
        sym = symbols[0]
        if sym == "BADTICKER":
            return {sym: None}
        return {sym: {"price": 10.0, "prev_close": 9.5, "chg_pct": 5.0}}

    monkeypatch.setattr(lp, "get_live_prices_batch", _fake_batch)

    result = tu._portfolio_live_prices(("RELIANCE", "BADTICKER", "TCS"))
    assert set(result.keys()) == {"RELIANCE", "TCS"}
    assert "BADTICKER" not in result
