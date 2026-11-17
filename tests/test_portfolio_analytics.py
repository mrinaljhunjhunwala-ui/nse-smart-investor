"""
tests/test_portfolio_analytics.py — coverage for the two previously untested
portfolio-analytics modules:

  • analysis/portfolio_concentration.py  (HHI / diversification)
  • analysis/portfolio_fundamentals.py    (quality score — thin wrapper)

Pure-function tests; no network. The alert tests inject mock Telegram/quoter
objects and monkeypatch the alerts CSV path, so nothing real is sent or read.
"""
from __future__ import annotations



from analysis.portfolio_concentration import (
    calculate_hhi,
    analyze_concentration,
    concentration_grade,
    ConcentrationResult,
)
from analysis.portfolio_fundamentals import compute_quality_score, quality_score_coverage


# ─────────────────────────────────────────────────────────────────────────────
# Section A — portfolio_concentration
# ─────────────────────────────────────────────────────────────────────────────

def test_hhi_equal_weights_ten_holdings():
    # 10 holdings at 10% each → Σ(10²) × 10 = 1000
    assert calculate_hhi([10.0] * 10) == 1000.0


def test_hhi_single_holding():
    assert calculate_hhi([100.0]) == 10000.0


def test_hhi_empty_list():
    assert calculate_hhi([]) == 0.0


def test_hhi_two_holdings_60_40():
    # 60² + 40² = 3600 + 1600 = 5200
    assert calculate_hhi([60.0, 40.0]) == 5200.0


def test_grade_a():
    assert concentration_grade(500) == "A"


def test_grade_b():
    assert concentration_grade(1200) == "B"


def test_grade_c():
    assert concentration_grade(1700) == "C"


def test_grade_d():
    assert concentration_grade(2200) == "D"


def test_grade_f():
    assert concentration_grade(3000) == "F"


def test_analyze_empty_portfolio():
    r = analyze_concentration([])
    assert isinstance(r, ConcentrationResult)
    assert r.total_holdings == 0
    assert r.hhi == 0
    assert r.hhi_category == "Unknown"


def test_analyze_single_holding():
    r = analyze_concentration([{"ticker": "RELIANCE", "weight_pct": 100.0}])
    assert r.hhi == 10000
    assert r.hhi_category == "High"
    assert r.risk_level == "HIGH"
    assert r.top_1_weight == 100.0


def test_analyze_equal_ten_holdings():
    holdings = [{"ticker": f"S{i}", "weight_pct": 10.0} for i in range(10)]
    r = analyze_concentration(holdings)
    assert r.hhi == 1000
    assert r.hhi_category == "Low"
    assert r.risk_level == "LOW"
    assert abs(r.top_5_weight - 50.0) < 0.01


# ─────────────────────────────────────────────────────────────────────────────
# Section B — compute_quality_score (inputs are already in PERCENT)
# ─────────────────────────────────────────────────────────────────────────────

def test_quality_empty_dict():
    assert compute_quality_score({}) == 0


def test_quality_only_roe_15():
    # 15% ROE → 15×2 = 30 (the cap); only metric present → 100% of its weight
    assert compute_quality_score({"roe": 15.0}) == 100


def test_quality_all_zero():
    assert compute_quality_score({
        "roe": 0.0, "roce": 0.0, "revenue_cagr_5y": 0.0, "eps_cagr_5y": 0.0,
    }) == 0


def test_quality_all_maxed():
    assert compute_quality_score({
        "roe": 15.0, "roce": 15.0, "revenue_cagr_5y": 20.0, "eps_cagr_5y": 20.0,
    }) == 100


def test_quality_partial_roe_only():
    # 7.5% ROE → 7.5×2 = 15 of 30 → 50/100 scaled
    assert compute_quality_score({"roe": 7.5}) == 50


def test_quality_negative_cagr_clamped_not_negative():
    # A negative CAGR must contribute 0, never drag the score below 0
    s = compute_quality_score({"eps_cagr_5y": -50.0})
    assert s == 0
    assert s >= 0


# ─────────────────────────────────────────────────────────────────────────────
# Section B2 — quality_score_coverage (additive; does not change
# compute_quality_score's return type, since the assertions above depend
# on it staying a plain int)
# ─────────────────────────────────────────────────────────────────────────────

def test_coverage_nothing_available():
    assert quality_score_coverage({}) == (0, 4)


def test_coverage_one_metric():
    assert quality_score_coverage({"roe": 15.0}) == (1, 4)


def test_coverage_all_four():
    assert quality_score_coverage({
        "roe": 15.0, "roce": 15.0, "revenue_cagr_5y": 20.0, "eps_cagr_5y": 20.0,
    }) == (4, 4)


def test_coverage_prefers_5y_falls_back_to_3y_without_double_counting():
    # Only the 3y variants present — should count as 1 metric each, not 0
    # (falling back) and not 2 (double-counting 5y+3y as separate signals).
    assert quality_score_coverage({
        "revenue_cagr_3y": 10.0, "eps_cagr_3y": 8.0,
    }) == (2, 4)
