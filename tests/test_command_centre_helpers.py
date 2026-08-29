"""tests/test_command_centre_helpers.py — pin the Top Picks freshness helper.

The Command Centre page's `_reanchor_levels()` function turns a scored
(entry, sl, tp) triangle + a live price into a re-anchored triangle plus
gross/net-of-cost R:R. This is the fix for the "SL sits above live price
because scored yesterday, priced today" bug.
"""
from __future__ import annotations

import importlib.util
import os
import sys
import types

import pytest


_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

# The Command Centre page is a top-level Streamlit script — importing it
# outright would run the whole page. Extract just the helper we need via
# a temp module that imports the source string. Kept crude on purpose;
# the helper is pure and doesn't touch Streamlit.
# FIX CC-FRESH → the helper moved into dashboard/shared/pick_freshness so
# both Command Centre and My Watchlist can consume the same impl. Import
# directly instead of scraping the CC page source.
from dashboard.shared.pick_freshness import (  # noqa: E402
    COST_ROUNDTRIP_PCT as _COST,
    reanchor_levels as _reanchor_levels,
)


# ─────────────── Basic contract ───────────────

def test_zero_entry_returns_zeros_gracefully():
    r = _reanchor_levels(0.0, 0.0, 0.0, 100.0)
    assert r["entry"] == 0.0
    assert r["reanchored"] is False


def test_no_live_price_returns_scored_triangle_with_cost_adjusted_rr():
    r = _reanchor_levels(entry=100.0, sl=98.0, tp=106.0, live_price=None)
    assert r["entry"] == 100.0 and r["sl"] == 98.0 and r["tp"] == 106.0
    assert r["reanchored"] is False
    # Gross R:R = 6 / 2 = 3.0
    assert r["rr"] == pytest.approx(3.0, abs=0.01)
    # Net = (6 − 0.30) / (2 + 0.30) ≈ 5.7 / 2.3 ≈ 2.48
    assert r["rr_net"] < r["rr"], "net R:R must be strictly worse than gross"
    assert r["rr_net"] == pytest.approx(2.48, abs=0.05)


# ─────────────── Drift threshold ───────────────

def test_drift_below_threshold_keeps_original_entry():
    """A 0.3 % drift is below the 0.5 % threshold — don't shift the levels."""
    r = _reanchor_levels(entry=100.0, sl=98.0, tp=106.0, live_price=100.3)
    assert r["entry"] == 100.0
    assert r["sl"]    == 98.0
    assert r["tp"]    == 106.0
    assert r["reanchored"] is False
    assert r["drift_pct"] == pytest.approx(0.3, abs=0.01)


def test_drift_above_threshold_reanchors_preserving_distances():
    """Live price 103 vs scored entry 100. Risk was 2, reward was 6.
    Re-anchored entry = 103, SL = 101, TP = 109. Distances preserved."""
    r = _reanchor_levels(entry=100.0, sl=98.0, tp=106.0, live_price=103.0)
    assert r["reanchored"] is True
    assert r["entry"] == pytest.approx(103.0, abs=0.01)
    assert r["sl"]    == pytest.approx(101.0, abs=0.01)
    assert r["tp"]    == pytest.approx(109.0, abs=0.01)
    # Same R:R (3.0 gross) — distances unchanged
    assert r["rr"]    == pytest.approx(3.0, abs=0.05)
    assert r["drift_pct"] == pytest.approx(3.0, abs=0.05)


def test_drift_downward_reanchors_too():
    """The classic "SL now above live price" case — scored at 100 with
    SL 98; live has dropped to 96. Re-anchor to keep the ATR-based risk."""
    r = _reanchor_levels(entry=100.0, sl=98.0, tp=106.0, live_price=96.0)
    assert r["reanchored"] is True
    assert r["entry"] == 96.0
    assert r["sl"]    == 94.0
    assert r["tp"]    == 102.0
    # SL must be BELOW live entry (the original bug produced SL > entry after drift)
    assert r["sl"] < r["entry"]


# ─────────────── Cost-adjusted R:R ───────────────

def test_cost_floor_matches_efficacy_study_constant():
    """The cost floor must stay in sync with research.score_efficacy so the
    honest-hit-rate work and the UI card R:R agree on what "net" means."""
    from research.score_efficacy import COST_ROUNDTRIP_PCT as EFF_COST
    assert _COST == EFF_COST, (
        f"CC-FRESH cost constant ({_COST}) drifted from efficacy study "
        f"constant ({EFF_COST}) — must stay in sync"
    )


def test_net_rr_lower_than_gross_rr():
    """Sanity: net R:R must never exceed gross for any positive cost floor."""
    for e, s, t, lp in [
        (100, 98, 106, None),
        (100, 98, 106, 100.3),
        (100, 98, 106, 103.0),
        (500, 490, 530, 505.0),
    ]:
        r = _reanchor_levels(e, s, t, lp)
        assert r["rr_net"] <= r["rr"], (
            f"net R:R > gross for (e={e}, sl={s}, tp={t}, lp={lp}): "
            f"gross={r['rr']}, net={r['rr_net']}"
        )


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
