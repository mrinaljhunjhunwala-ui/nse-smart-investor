"""tests/test_valuation_decision.py — deterministic tests for Phase E1-v2.

NO AI, no network. Covers every matrix cell, every guard, every refusal path, the four
headline stress-test failures, the confidence model, and the descriptive-vocabulary
guarantee. All inputs hand-built via ValuationInputs.
"""
from __future__ import annotations

from analysis.sector_classification import classify_sector
from analysis.fundamentals.valuation_decision import (
    assess, ValuationInputs,
    SUPPORTED_BY_GROWTH_AND_QUALITY, SUPPORTED_BY_GROWTH, SUPPORTED_BY_QUALITY,
    SUPPORTED_BY_ROE, REASONABLE, DEMANDING_VS_GROWTH, DEMANDING_VS_RETURNS,
    DEMANDING_VS_ROE, INSUFFICIENT_EVIDENCE, PHRASES,
)

_FORBIDDEN = ["buy", "sell", "fair value", "intrinsic", "cheap", "expensive",
              "undervalued", "overvalued", "target price"]


def mk(label, **kw):
    p = classify_sector(label)
    base = dict(sector_group=p.group, is_financial=p.is_financial,
                fcf_capex_caveat=p.fcf_capex_caveat)
    base.update(kw)
    return ValuationInputs(**base)


def _nonfin(**kw):
    """A healthy non-financial scaffold (IT) with overridable fields."""
    base = dict(pe=20, roce=18, eps_cagr=15, revenue_cagr=14, fcf=1000,
                net_income=1000, operating_cash_flow=1100, total_equity=5000,
                eps_cagr_span_years=4, eps_cagr_points=4, eps_cagr_start_value=300)
    base.update(kw)
    return mk("IT", **base)


# ── NON-FINANCIAL MATRIX — every cell ────────────────────────────────────────────
def test_cell_lowpeg_high_quality():
    # PEG<1 (pe18/eps20=0.9), ROCE High → supported by growth & quality
    r = assess(_nonfin(pe=18, eps_cagr=20, roce=25))
    assert r.posture == SUPPORTED_BY_GROWTH_AND_QUALITY


def test_cell_lowpeg_moderate_quality():
    r = assess(_nonfin(pe=18, eps_cagr=20, roce=15))
    assert r.posture == SUPPORTED_BY_GROWTH


def test_cell_lowpeg_low_quality_is_gated():
    # G2: low ROCE blocks 'Supported' even at PEG<1
    r = assess(_nonfin(pe=18, eps_cagr=20, roce=9))
    assert r.posture == REASONABLE
    assert any("low returns" in c.lower() or "gate" in " ".join(r.reasons).lower()
               for c in r.caveats + r.reasons)


def test_cell_midpeg_high_quality():
    r = assess(_nonfin(pe=22, eps_cagr=15, roce=25))   # PEG ~1.47
    assert r.posture == SUPPORTED_BY_QUALITY


def test_cell_midpeg_moderate_quality():
    r = assess(_nonfin(pe=22, eps_cagr=15, roce=15))
    assert r.posture == REASONABLE


def test_cell_midpeg_low_quality():
    r = assess(_nonfin(pe=22, eps_cagr=15, roce=9))
    assert r.posture == DEMANDING_VS_RETURNS


def test_cell_highpeg_high_quality():
    r = assess(_nonfin(pe=40, eps_cagr=12, roce=40))   # PEG 3.3
    assert r.posture == DEMANDING_VS_GROWTH
    assert any("returns on capital" in c.lower() for c in r.caveats)


def test_cell_highpeg_moderate_quality():
    r = assess(_nonfin(pe=40, eps_cagr=12, roce=15))
    assert r.posture == DEMANDING_VS_GROWTH


def test_cell_highpeg_low_quality():
    r = assess(_nonfin(pe=40, eps_cagr=12, roce=9))
    assert r.posture == DEMANDING_VS_RETURNS


def test_quality_unknown_cannot_be_supported():
    r = assess(_nonfin(pe=18, eps_cagr=20, roce=None))
    assert r.posture not in (SUPPORTED_BY_GROWTH, SUPPORTED_BY_GROWTH_AND_QUALITY,
                             SUPPORTED_BY_QUALITY)


# ── FINANCIAL MATRIX — every cell ────────────────────────────────────────────────
def _fin(**kw):
    base = dict(pb=2.0, roe=14, total_equity=10000, roe_averaged=True)
    base.update(kw)
    return mk("Banking", **base)


def test_fin_high_roe_low_pb():
    assert assess(_fin(roe=18, pb=1.2)).posture == SUPPORTED_BY_ROE


def test_fin_high_roe_high_pb_premium_matched():
    assert assess(_fin(roe=18, pb=3.5)).posture == REASONABLE


def test_fin_moderate_roe_moderate_pb():
    assert assess(_fin(roe=12, pb=2.0)).posture == REASONABLE


def test_fin_moderate_roe_high_pb():
    assert assess(_fin(roe=12, pb=3.5)).posture == DEMANDING_VS_ROE


def test_fin_low_roe_low_pb_caveat():
    r = assess(_fin(roe=8, pb=1.2))
    assert r.posture == REASONABLE and any("low roe" in c.lower() for c in r.caveats)


def test_fin_low_roe_high_pb():
    assert assess(_fin(roe=8, pb=3.5)).posture == DEMANDING_VS_ROE


def test_fin_elevated_roe_g6_downgrade():
    # ROE>=20 + high P/B → 'premium matched' downgraded to Demanding vs ROE (G6)
    r = assess(_fin(roe=22, pb=3.5))
    assert r.posture == DEMANDING_VS_ROE
    assert any("cyclically elevated" in c.lower() for c in r.caveats)
    assert r.confidence in ("medium", "low")


def test_fin_single_period_roe_caps_confidence():
    r = assess(_fin(roe=18, pb=1.2, roe_averaged=False))
    assert r.confidence in ("medium", "low")


def test_financial_services_bucket_capped_medium():
    r = assess(mk("Finance", pb=1.2, roe=18, total_equity=5000, roe_averaged=True))
    assert r.confidence in ("medium", "low")


# ── GUARDS / REFUSALS ────────────────────────────────────────────────────────────
def test_guard_insurance_always_refuses():
    r = assess(mk("Insurance", pb=2, roe=15, total_equity=5000))
    assert r.posture == INSUFFICIENT_EVIDENCE and r.triggered_guard == "H4-insurance"


def test_guard_negative_equity():
    r = assess(_nonfin(total_equity=-100))
    assert r.posture == INSUFFICIENT_EVIDENCE and r.triggered_guard == "H2-negative-equity"


def test_guard_negative_earnings():
    r = assess(_nonfin(net_income=-50))
    assert r.triggered_guard == "H1-negative-earnings"


def test_guard_missing_pe_nonfinancial():
    r = assess(_nonfin(pe=None))
    assert r.triggered_guard == "H3-missing-metric"


def test_guard_financial_missing_metric():
    r = assess(mk("Banking", pb=None, roe=15, total_equity=5000))
    assert r.triggered_guard == "H3-missing-metric"


def test_guard_implausible_pe():
    r = assess(_nonfin(pe=250))
    assert r.triggered_guard == "H6-implausible"


def test_guard_newly_listed():
    r = assess(_nonfin(eps_cagr_points=1, eps_cagr_span_years=1))
    assert r.triggered_guard == "H5-newly-listed"


def test_guard_cyclical_peak_G1():
    r = assess(mk("Metal", pe=8, roce=24, eps_cagr=45, revenue_cagr=10,
                  net_income=1000, total_equity=5000))
    assert r.posture == INSUFFICIENT_EVIDENCE and r.triggered_guard == "G1-cyclical-peak"


def test_guard_cyclical_trough_negative_growth():
    r = assess(mk("Metal", pe=40, roce=6, eps_cagr=-5, revenue_cagr=-3,
                  net_income=200, total_equity=5000))
    assert r.triggered_guard == "TR-cyclical-trough"


def test_guard_cyclical_trough_highpe_lowroce():
    r = assess(mk("Chemicals", pe=45, roce=7, eps_cagr=8, revenue_cagr=6,
                  net_income=200, total_equity=5000,
                  eps_cagr_points=4, eps_cagr_span_years=4, eps_cagr_start_value=100))
    assert r.triggered_guard == "TR-cyclical-trough"


def test_guard_base_effect_growth_over_cap():
    r = assess(_nonfin(eps_cagr=80))   # > 60% cap → growth lens off
    # not necessarily refusal (quality high enough → Reasonable), but no growth posture
    assert r.posture in (REASONABLE, INSUFFICIENT_EVIDENCE)
    assert all("supported by growth" not in PHRASES[r.posture].lower() for _ in [0])


def test_guard_turnaround_start_nonpositive():
    r = assess(_nonfin(eps_cagr=30, eps_cagr_start_value=-5, roce=8))
    # growth off + low quality → insufficient
    assert r.posture in (REASONABLE, INSUFFICIENT_EVIDENCE)


# ── G3 PEG band / no-growth path ─────────────────────────────────────────────────
def test_lowgrowth_disables_peg_quality_led():
    r = assess(_nonfin(pe=45, eps_cagr=2, roce=35))
    assert r.posture == REASONABLE and r.confidence == "low"
    assert any("not assessed against growth" in c.lower() or "growth not assess" in c.lower()
               for c in r.caveats)


def test_lowgrowth_low_quality_insufficient():
    r = assess(_nonfin(pe=20, eps_cagr=2, roce=9))
    assert r.posture == INSUFFICIENT_EVIDENCE


# ── G4 cash-conversion veto ──────────────────────────────────────────────────────
def test_g4_negative_fcf_vetoes_supported():
    # PEG<1, Moderate quality → would be Supported by growth, but FCF<0 non-capex → Reasonable
    r = assess(_nonfin(pe=18, eps_cagr=22, roce=15, fcf=-200))
    assert r.posture == REASONABLE
    assert any("converting to cash" in c.lower() for c in r.caveats)


def test_g4_poor_ocf_ni_vetoes():
    r = assess(_nonfin(pe=18, eps_cagr=22, roce=15, fcf=10,
                       net_income=1000, operating_cash_flow=300))   # OCF/NI=0.3
    assert r.posture == REASONABLE


def test_g4_does_not_apply_to_capex_sector():
    # capgoods negative FCF should NOT veto via G4 (capex caveat), supported can stand
    r = assess(mk("CapitalGoods", pe=18, roce=22, eps_cagr=22, revenue_cagr=20, fcf=-500,
                  net_income=800, operating_cash_flow=200, total_equity=4000,
                  eps_cagr_points=4, eps_cagr_span_years=4, eps_cagr_start_value=200))
    assert r.posture in (SUPPORTED_BY_GROWTH_AND_QUALITY, SUPPORTED_BY_GROWTH)


# ── G5 capex softening ───────────────────────────────────────────────────────────
def test_g5_capex_softens_demanding_vs_returns():
    r = assess(mk("CapitalGoods", pe=35, roce=10, eps_cagr=30, revenue_cagr=28, fcf=-1500,
                  net_income=800, total_equity=4000,
                  eps_cagr_points=4, eps_cagr_span_years=4, eps_cagr_start_value=200))
    assert r.posture == REASONABLE
    assert any("capex" in c.lower() for c in r.caveats)


# ── HEADLINE FAILURES (before/after intent) ──────────────────────────────────────
def test_headline_cyclical_peak_not_supported():
    r = assess(mk("Auto", pe=9, roce=22, eps_cagr=40, revenue_cagr=12,
                  net_income=1000, total_equity=6000))
    assert r.posture == INSUFFICIENT_EVIDENCE


def test_headline_low_quality_growth_not_supported():
    r = assess(_nonfin(pe=50, eps_cagr=55, roce=9))
    assert r.posture == REASONABLE


def test_headline_accrual_growth_not_supported():
    r = assess(_nonfin(pe=22, eps_cagr=25, roce=14, fcf=-200,
                       net_income=300, operating_cash_flow=100))
    assert r.posture == REASONABLE


def test_headline_lowgrowth_peg_not_demanding_noise():
    r = assess(_nonfin(pe=45, eps_cagr=2, roce=35))
    assert r.posture == REASONABLE   # not a noisy DEMANDING_VS_GROWTH from PEG=22


# ── CONFIDENCE / EXPLAINABILITY / VOCABULARY ─────────────────────────────────────
def test_confidence_high_for_clean_compounder():
    r = assess(_nonfin(pe=18, eps_cagr=20, roce=25, revenue_cagr=19))
    assert r.confidence == "high"
    assert r.confidence_factors


def test_short_history_caps_confidence():
    r = assess(_nonfin(pe=18, eps_cagr=20, roce=25, eps_cagr_span_years=2, eps_cagr_points=2))
    assert r.confidence in ("medium", "low")


def test_psu_caps_confidence():
    r = assess(_nonfin(pe=18, eps_cagr=20, roce=25, is_psu=True))
    assert r.confidence in ("medium", "low")


def test_every_posture_has_reasons_and_phrase():
    r = assess(_nonfin())
    assert r.phrase == PHRASES[r.posture]
    assert r.reasons and r.justification


def test_refusal_carries_guard_and_reason():
    r = assess(mk("Insurance", pb=2, roe=15, total_equity=5000))
    assert r.triggered_guard and r.reasons


def test_no_forbidden_vocabulary_anywhere():
    cases = [_nonfin(), _nonfin(pe=50, eps_cagr=55, roce=9), _fin(roe=18, pb=1.2),
             mk("Insurance", pb=2, roe=15, total_equity=5000),
             mk("Metal", pe=8, roce=24, eps_cagr=45, revenue_cagr=10,
                net_income=1000, total_equity=5000)]
    for inp in cases:
        r = assess(inp)
        blob = " ".join([r.phrase, r.justification] + r.reasons + r.caveats).lower()
        for word in _FORBIDDEN:
            assert word not in blob, f"forbidden word '{word}' in output"


def test_to_dict_serialisable():
    d = assess(_nonfin()).to_dict()
    assert d["posture"] and d["phrase"] and "confidence" in d


def test_determinism():
    a = assess(_nonfin()).to_dict()
    b = assess(_nonfin()).to_dict()
    assert a == b
