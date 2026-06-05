"""tests/test_valuation_liquidity.py — deterministic tests for Phase C1.

NO AI, no network. Covers valuation mapping + missing values, liquidity tier logic,
turnover calculations, and thesis/portfolio-fit integration. All inputs hand-built.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from analysis.fundamentals.models import CompanyFundamentals, RatioSnapshot
from analysis.fundamentals.valuation import build_valuation_context, ValuationContext
from analysis.liquidity import (
    compute_liquidity, format_turnover, LiquidityContext,
    TIER_HIGH, TIER_MEDIUM, TIER_LOW, CR,
)
from analysis.thesis import generate_thesis, ThesisInputs, assess_fit, PortfolioFitInputs


# ── helpers ──────────────────────────────────────────────────────────────────────
def _frame(close, volume, n=120):
    idx = pd.bdate_range("2024-01-01", periods=n)
    return pd.DataFrame({"Close": np.full(n, float(close)),
                         "Volume": np.full(n, float(volume))}, index=idx)


def _cf(pe=None, pb=None, ev=None, provider="YahooFinance"):
    return CompanyFundamentals(symbol="X", provider_name=provider,
                               ratios=RatioSnapshot(pe=pe, pb=pb, ev_ebitda=ev))


# ── VALUATION mapping ────────────────────────────────────────────────────────────
def test_valuation_all_present_high_confidence():
    vc = build_valuation_context(_cf(pe=22.5, pb=3.1, ev=14.2))
    assert (vc.pe, vc.pb, vc.ev_ebitda) == (22.5, 3.1, 14.2)
    assert vc.confidence == "high"
    assert vc.missing_fields == []
    assert vc.source == "YahooFinance"


def test_valuation_two_present_medium():
    vc = build_valuation_context(_cf(pe=18.0, pb=2.0, ev=None))
    assert vc.confidence == "medium"
    assert vc.missing_fields == ["EV/EBITDA"]
    assert vc.available_count() == 2


def test_valuation_one_present_low():
    vc = build_valuation_context(_cf(pe=18.0))
    assert vc.confidence == "low"
    assert set(vc.missing_fields) == {"P/B", "EV/EBITDA"}


def test_valuation_none_present_confidence_none():
    vc = build_valuation_context(_cf())
    assert vc.confidence == "none"
    assert vc.pe is None and vc.pb is None and vc.ev_ebitda is None
    assert len(vc.missing_fields) == 3


def test_valuation_negative_pe_is_not_fabricated():
    # loss-making / non-positive multiple → reported as unavailable, never a number
    vc = build_valuation_context(_cf(pe=-12.0, pb=0.0, ev=15.0))
    assert vc.pe is None and vc.pb is None        # negative & zero rejected
    assert vc.ev_ebitda == 15.0
    assert "P/E" in vc.missing_fields and "P/B" in vc.missing_fields


def test_valuation_nan_and_inf_rejected():
    vc = build_valuation_context(_cf(pe=float("nan"), pb=float("inf"), ev=12.0))
    assert vc.pe is None and vc.pb is None and vc.ev_ebitda == 12.0


def test_valuation_handles_missing_cf_and_ratios():
    assert build_valuation_context(None).confidence == "none"
    assert build_valuation_context(CompanyFundamentals(symbol="Z")).confidence == "none"


def test_valuation_to_dict():
    d = build_valuation_context(_cf(pe=20.0, pb=2.5, ev=10.0)).to_dict()
    assert d["pe"] == 20.0 and d["confidence"] == "high" and d["missing_fields"] == []


# ── LIQUIDITY tier logic + turnover ──────────────────────────────────────────────
def test_turnover_calculation_exact():
    # 500 × 1,000,000 = ₹50 cr/day → High
    lq = compute_liquidity(_frame(500, 1_000_000))
    assert lq.avg_daily_turnover_30d == 500 * 1_000_000
    assert lq.avg_daily_volume_30d == 1_000_000
    assert lq.liquidity_tier == "High"


def test_tier_high_boundary():
    # turnover exactly at the High threshold
    lq = compute_liquidity(_frame(TIER_HIGH / 1_000, 1_000))
    assert lq.liquidity_tier == "High"


def test_tier_medium():
    lq = compute_liquidity(_frame(100, 100_000))   # ₹1 cr/day → Medium (≥5cr? no) ...
    # 100 × 100000 = ₹1cr < 5cr → Low actually; build an explicit Medium:
    lq = compute_liquidity(_frame(100, 1_000_000))  # ₹10 cr → Medium
    assert lq.liquidity_tier == "Medium"


def test_tier_low():
    lq = compute_liquidity(_frame(100, 100_000))    # ₹1 cr → between 50L and 5cr → Low
    assert lq.liquidity_tier == "Low"


def test_tier_illiquid():
    lq = compute_liquidity(_frame(50, 1_000))       # ₹50,000/day → Illiquid
    assert lq.liquidity_tier == "Illiquid"


def test_liquidity_insufficient_history_is_unknown():
    lq = compute_liquidity(_frame(100, 100_000, n=10))
    assert lq.liquidity_tier == "Unknown"
    assert lq.avg_daily_turnover_30d is None
    assert "need" in lq.reason


def test_liquidity_missing_columns():
    df = pd.DataFrame({"Close": [1, 2, 3]})
    lq = compute_liquidity(df)
    assert lq.liquidity_tier == "Unknown" and "Volume" in lq.reason


def test_liquidity_none_frame():
    assert compute_liquidity(None).liquidity_tier == "Unknown"


def test_volume_trend_rising():
    # last 30 days higher volume than the prior 60 → rising
    idx = pd.bdate_range("2024-01-01", periods=120)
    vol = np.concatenate([np.full(90, 100_000.0), np.full(30, 300_000.0)])
    df = pd.DataFrame({"Close": np.full(120, 100.0), "Volume": vol}, index=idx)
    lq = compute_liquidity(df)
    assert lq.volume_trend == "rising"
    assert lq.volume_trend_ratio > 1.2


def test_volume_trend_falling():
    idx = pd.bdate_range("2024-01-01", periods=120)
    vol = np.concatenate([np.full(90, 300_000.0), np.full(30, 100_000.0)])
    df = pd.DataFrame({"Close": np.full(120, 100.0), "Volume": vol}, index=idx)
    lq = compute_liquidity(df)
    assert lq.volume_trend == "falling"
    assert lq.volume_trend_ratio < 0.8


def test_volume_trend_none_when_short_history():
    lq = compute_liquidity(_frame(100, 100_000, n=45))   # ≥30 but <90 → no trend
    assert lq.liquidity_tier in ("High", "Medium", "Low", "Illiquid")
    assert lq.volume_trend is None and lq.volume_trend_ratio is None


def test_format_turnover():
    assert format_turnover(None) == "—"
    assert "cr" in format_turnover(42.3 * CR)
    assert "lakh" in format_turnover(85 * 1e5)


# ── THESIS integration ───────────────────────────────────────────────────────────
def test_thesis_high_liquidity_bull_factor():
    res = generate_thesis(ThesisInputs(ticker="H", composite_score=60,
                                       liquidity_tier="High", avg_daily_turnover=50 * CR))
    liq = [f for f in res.bull_factors if f.source == "Liquidity"]
    assert liq and "high liquidity" in liq[0].text.lower()
    assert "cr" in liq[0].evidence


def test_thesis_low_liquidity_risk_factor():
    res = generate_thesis(ThesisInputs(ticker="L", composite_score=60,
                                       liquidity_tier="Illiquid", avg_daily_turnover=200_000))
    liq = [f for f in res.key_risks if f.source == "Liquidity"]
    assert liq and "execution risk" in liq[0].text.lower()


def test_thesis_low_tier_also_triggers_risk():
    res = generate_thesis(ThesisInputs(ticker="L2", composite_score=60,
                                       liquidity_tier="Low", avg_daily_turnover=80 * 1e5))
    assert any(f.source == "Liquidity" for f in res.key_risks)


def test_thesis_medium_liquidity_no_factor():
    res = generate_thesis(ThesisInputs(ticker="M", composite_score=60,
                                       liquidity_tier="Medium", avg_daily_turnover=10 * CR))
    assert not any(f.source == "Liquidity" for f in res.bull_factors)
    assert not any(f.source == "Liquidity" for f in res.key_risks)


def test_thesis_liquidity_in_provenance():
    res = generate_thesis(ThesisInputs(ticker="H", composite_score=60, liquidity_tier="High"))
    assert "Liquidity" in res.inputs_present


# ── PORTFOLIO FIT integration ────────────────────────────────────────────────────
def _good_candidate(**over):
    base = dict(candidate_ticker="Z", candidate_sector="Pharma", candidate_beta=0.8,
                candidate_verdict="Strong Positive", candidate_verdict_score=2,
                avg_correlation=0.10, n_holdings=5, portfolio_beta=1.0,
                sector_weights={"IT": 30.0, "Banks": 25.0, "Auto": 25.0, "FMCG": 20.0},
                top_sector="IT", top_sector_pct=30.0, concentration_risk="MEDIUM")
    base.update(over)
    return PortfolioFitInputs(**base)


def test_fit_illiquid_caps_position_to_small():
    res = assess_fit(_good_candidate(candidate_liquidity_tier="Illiquid"))
    assert res.position_size_guidance == "Small"
    assert "illiquid" in res.position_size_reason.lower()


def test_fit_low_liquidity_is_a_pressure():
    # otherwise-clean candidate; low liquidity adds one pressure → Moderate
    res = assess_fit(_good_candidate(candidate_liquidity_tier="Low"))
    assert res.position_size_guidance == "Moderate"
    assert "liquidity" in res.position_size_reason.lower()


def test_fit_high_liquidity_no_penalty():
    res = assess_fit(_good_candidate(candidate_liquidity_tier="High"))
    assert res.position_size_guidance == "Large"
