"""tests/test_quality_watch_scoring.py — regression coverage for the Quality
Watch score (FIX QW1 rescaling of missing ratios).

The formula moved from dashboard/pages/19_quality_watch.py into the pure
analysis/quality_watch.py (audit 2026-09-24), so it is imported directly —
no AST extraction from the Streamlit page needed any more.
"""
import pytest


@pytest.fixture(scope="module")
def compute_quality_score():
    from analysis.quality_watch import compute_quality_score as fn
    return fn


def test_full_data_unaffected(compute_quality_score):
    """All 3 ratio metrics present — behavior must be unchanged (no
    rescaling needed since weight_used already equals the max weight)."""
    score, breakdown = compute_quality_score(
        "REASONABLE", "high", 0, 0, roe=0.20, roce=0.20, debt_to_equity=0.3
    )
    assert breakdown["quality_ratios"] == 20
    assert score == 100


def test_single_strong_metric_not_diluted(compute_quality_score):
    """FIX QW1 — only ROE available (strong), ROCE and D/E missing. Before
    the fix this scored quality_ratios=7/20 (only ROE's raw point value,
    with no credit for the two unavailable metrics). It should now be
    rescaled to the full 20/20, since the one signal available is strongly
    positive and shouldn't be diluted just because peers are missing."""
    score, breakdown = compute_quality_score(
        "REASONABLE", "high", 0, 0, roe=0.20, roce=None, debt_to_equity=None
    )
    assert breakdown["quality_ratios"] == 20
    assert score == 100


def test_weak_single_metric_scales_down_too(compute_quality_score):
    """A weak single metric should rescale down proportionally, not get
    an inflated score just because it's the only one available."""
    score, breakdown = compute_quality_score(
        "REASONABLE", "high", 0, 0, roe=0.05, roce=None, debt_to_equity=None
    )
    # roe=0.05 -> raw 1 pt out of a possible 7 for that metric -> rescaled
    # to 20 * (1/7) ≈ 3, not 20.
    assert breakdown["quality_ratios"] == round(20 * 1 / 7)


def test_no_ratio_data_is_neutral_not_zero(compute_quality_score):
    """FIX QW1 — when none of ROE/ROCE/D-E are available, the component
    must be a neutral-low default (10/20), matching this same function's
    own INSUFFICIENT_EVIDENCE=10 treatment for `posture` ("unknown isn't
    bad"), not the previous 0/20 (the worst possible reading)."""
    score, breakdown = compute_quality_score(
        "INSUFFICIENT_EVIDENCE", "none", 0, 0, roe=None, roce=None, debt_to_equity=None
    )
    assert breakdown["quality_ratios"] == 10
    assert breakdown["quality_ratios"] != 0


def test_never_exceeds_20_points(compute_quality_score):
    """Rescaling must still respect the component's max weight even with
    all-strong partial inputs."""
    score, breakdown = compute_quality_score(
        "REASONABLE", "high", 0, 0, roe=0.30, roce=0.30, debt_to_equity=None
    )
    assert breakdown["quality_ratios"] <= 20


def test_governance_and_posture_unaffected_by_fix(compute_quality_score):
    """The fix only touches quality_ratios — governance_safety and
    valuation_posture scoring must be untouched."""
    score, breakdown = compute_quality_score(
        "DEMANDING_VS_ROE", "medium", red_flags=1, amber_flags=2,
        roe=None, roce=None, debt_to_equity=None,
    )
    assert breakdown["valuation_posture"] == 15
    assert breakdown["confidence"] == 10
    assert breakdown["governance_safety"] == 25 - 8 - 6  # 25 - 1*8 - 2*3
