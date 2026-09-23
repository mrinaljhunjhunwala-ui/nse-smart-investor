"""Tests for chart_helpers.diverging_colors / PLOT_COLORS (P2 diverging rule)."""
from dashboard.shared.chart_helpers import PLOT_COLORS, diverging_colors


def test_hue_by_sign_opacity_by_magnitude():
    c = diverging_colors([10, -10, 5, 0])
    assert c[0] == "rgba(22,199,132,1.00)"
    assert c[1] == "rgba(255,77,77,1.00)"
    assert c[2].endswith("0.68)")          # 0.35 + 0.65 * 0.5 (rounded)
    assert c[3].startswith("rgba(22,199,132")


def test_nan_none_and_all_zero_safe():
    assert len(diverging_colors([None, float("nan")])) == 2
    assert diverging_colors([0, 0]) == ["rgba(22,199,132,0.35)"] * 2


def test_full_at_caps():
    assert diverging_colors([1000], full_at=10)[0].endswith("1.00)")


def test_tokens_present():
    assert {"bull", "bear", "accent", "azure", "faint"} <= set(PLOT_COLORS)
