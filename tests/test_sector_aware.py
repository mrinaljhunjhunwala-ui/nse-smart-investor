"""tests/test_sector_aware.py — deterministic tests for Phase D1 (sector-aware fundamentals).

NO AI, no network. Covers sector routing, the financials guard (banks/NBFCs/insurance),
ROCE + FCF calculations and edge cases, and missing-data handling. All inputs hand-built.
"""
from __future__ import annotations

from analysis.sector_classification import (
    classify_sector, SectorProfile, BANKS, NBFC, INSURANCE, FINANCIAL_SERVICES,
    IT_SERVICES, CONSUMER, CAPITAL_GOODS, ENERGY_POWER, OTHER,
)
from analysis.fundamentals.analytics import roce, free_cash_flow
from analysis.fundamentals.models import (
    CompanyFundamentals, RatioSnapshot, IncomeStatement, BalanceSheet, CashFlow, FiscalPeriod,
)
from analysis.fundamentals.valuation import build_valuation_context
from analysis.thesis import generate_thesis, ThesisInputs


# ── helpers ──────────────────────────────────────────────────────────────────────
def _texts(factors):
    return [f.text for f in factors]


def _cf_for_roce(ebit, total_assets, current_liabilities):
    inc = IncomeStatement(period=FiscalPeriod(), operating_income=ebit)
    bal = BalanceSheet(period=FiscalPeriod(), total_assets=total_assets,
                       current_liabilities=current_liabilities)
    return CompanyFundamentals(symbol="X", income_statements=[inc], balance_sheets=[bal])


def _cf_for_fcf(fcf_value):
    cfs = CashFlow(period=FiscalPeriod(), free_cash_flow=fcf_value)
    return CompanyFundamentals(symbol="X", cash_flows=[cfs])


# ── SECTOR ROUTING ───────────────────────────────────────────────────────────────
def test_route_banks():
    assert classify_sector("Banking").group == BANKS
    assert classify_sector("HDFC Bank").group == BANKS


def test_route_finance_bucket_is_financial():
    p = classify_sector("Finance")
    assert p.group == FINANCIAL_SERVICES and p.is_financial


def test_route_insurance_by_name_hint():
    p = classify_sector("Finance", name="ICICI Prudential Life Insurance")
    assert p.group == INSURANCE and p.is_financial


def test_route_nbfc_keyword():
    assert classify_sector("Housing Finance company").group in (NBFC, FINANCIAL_SERVICES)


def test_route_it_and_consumer():
    assert classify_sector("IT").group == IT_SERVICES
    assert classify_sector("Technology").group == IT_SERVICES
    assert classify_sector("FMCG").group == CONSUMER


def test_route_capital_goods_and_power_are_capex():
    assert classify_sector("CapitalGoods").is_capital_intensive
    assert classify_sector("CapitalGoods").fcf_capex_caveat
    assert classify_sector("Energy").fcf_capex_caveat


def test_route_unknown_is_neutral_other():
    p = classify_sector("Nonsense Sector 42")
    assert p.group == OTHER and not p.is_financial
    assert p.leverage_warning_applies and p.roce_meaningful and p.fcf_meaningful


def test_route_none_is_other_not_financial():
    p = classify_sector(None)
    assert p.group == OTHER and not p.is_financial


def test_financial_profiles_suppress_industrial_metrics():
    for label in ("Banking", "Finance", "Insurance"):
        p = classify_sector(label)
        assert p.is_financial
        assert not p.leverage_warning_applies
        assert not p.ev_ebitda_meaningful
        assert not p.roce_meaningful
        assert not p.fcf_meaningful
        assert p.note            # explanatory context present


# ── FINANCIALS GUARD in the thesis ───────────────────────────────────────────────
def test_bank_high_de_produces_no_leverage_risk():
    bank = classify_sector("Banking")
    res = generate_thesis(ThesisInputs(ticker="HDFCBANK", composite_score=72, roe=17.0,
                                       debt_to_equity=9.0, sector_profile=bank))
    assert not any("leverage" in t.lower() for t in _texts(res.key_risks))
    assert any("deposit" in n.lower() for n in res.notes)        # explanatory context instead


def test_nbfc_high_de_no_leverage_risk():
    nbfc = classify_sector("Finance", name="Bajaj Finance NBFC")
    res = generate_thesis(ThesisInputs(ticker="BAJFINANCE", composite_score=70,
                                       debt_to_equity=4.0, sector_profile=nbfc))
    assert not any("leverage" in t.lower() for t in _texts(res.key_risks))


def test_insurance_marked_financial_and_noted():
    ins = classify_sector("Finance", name="SBI Life Insurance")
    res = generate_thesis(ThesisInputs(ticker="SBILIFE", composite_score=65,
                                       debt_to_equity=3.0, sector_profile=ins))
    assert not any("leverage" in t.lower() for t in _texts(res.key_risks))
    assert res.notes


def test_non_financial_same_de_DOES_warn():
    mfg = classify_sector("CapitalGoods")
    res = generate_thesis(ThesisInputs(ticker="LT", composite_score=60,
                                       debt_to_equity=2.0, sector_profile=mfg))
    assert any("leverage" in t.lower() for t in _texts(res.key_risks))


def test_no_profile_preserves_legacy_leverage_warning():
    # backward-compat: with no sector profile, the leverage rule still fires
    res = generate_thesis(ThesisInputs(ticker="X", composite_score=55, debt_to_equity=2.0))
    assert any("leverage" in t.lower() for t in _texts(res.key_risks))


def test_financial_suppresses_roce_and_fcf_factors():
    bank = classify_sector("Banking")
    res = generate_thesis(ThesisInputs(ticker="HDFCBANK", composite_score=70, roce=2.0,
                                       fcf=-50000.0, sector_profile=bank))
    assert not any("capital employed" in t.lower() for t in _texts(res.bear_factors))
    assert not any("free cash flow" in t.lower() for t in _texts(res.bear_factors))


# ── ROCE calculation ─────────────────────────────────────────────────────────────
def test_roce_basic():
    r = roce(_cf_for_roce(ebit=200.0, total_assets=1000.0, current_liabilities=200.0))
    assert r.available and r.value == 25.0          # 200 / (1000-200) = 25%
    assert r.detail["capital_employed"] == 800.0


def test_roce_missing_ebit():
    r = roce(_cf_for_roce(ebit=None, total_assets=1000.0, current_liabilities=200.0))
    assert not r.available and r.value is None and "EBIT" in r.reason


def test_roce_missing_balance_fields():
    r = roce(_cf_for_roce(ebit=200.0, total_assets=None, current_liabilities=200.0))
    assert not r.available and r.value is None


def test_roce_nonpositive_capital_employed():
    r = roce(_cf_for_roce(ebit=200.0, total_assets=300.0, current_liabilities=500.0))
    assert not r.available and "non-positive" in r.reason     # never fabricated


# ── FCF calculation ──────────────────────────────────────────────────────────────
def test_fcf_positive_in_crores():
    r = free_cash_flow(_cf_for_fcf(5_000_000_000.0))          # ₹500 cr
    assert r.available and r.value == 500.0 and r.unit == "₹cr"


def test_fcf_negative_preserved():
    r = free_cash_flow(_cf_for_fcf(-1_500_000_000.0))
    assert r.available and r.value == -150.0                   # sign kept, not zeroed


def test_fcf_missing_is_unavailable():
    r = free_cash_flow(CompanyFundamentals(symbol="X"))
    assert not r.available and r.value is None


# ── ROCE / FCF thesis integration (non-financial) ────────────────────────────────
def test_high_roce_is_bull_for_non_financial():
    it = classify_sector("IT")
    res = generate_thesis(ThesisInputs(ticker="TCS", composite_score=68, roce=45.0,
                                       sector_profile=it))
    assert any("capital employed" in t.lower() for t in _texts(res.bull_factors))


def test_low_roce_is_bear_for_non_financial():
    res = generate_thesis(ThesisInputs(ticker="X", composite_score=50, roce=4.0,
                                       sector_profile=classify_sector("Auto")))
    assert any("capital employed" in t.lower() for t in _texts(res.bear_factors))


def test_positive_fcf_bull():
    res = generate_thesis(ThesisInputs(ticker="HUL", composite_score=60, fcf=8000.0,
                                       sector_profile=classify_sector("FMCG")))
    assert any("free cash flow" in t.lower() for t in _texts(res.bull_factors))


def test_negative_fcf_capex_sector_is_note_not_bear():
    res = generate_thesis(ThesisInputs(ticker="NTPC", composite_score=58, fcf=-12000.0,
                                       sector_profile=classify_sector("Energy")))
    assert not any("free cash flow" in t.lower() for t in _texts(res.bear_factors))
    assert any("capex" in n.lower() for n in res.notes)


def test_negative_fcf_non_capex_is_bear():
    res = generate_thesis(ThesisInputs(ticker="X", composite_score=55, fcf=-500.0,
                                       sector_profile=classify_sector("IT")))
    assert any("free cash flow" in t.lower() for t in _texts(res.bear_factors))


# ── Valuation guard ──────────────────────────────────────────────────────────────
def test_valuation_suppresses_ev_ebitda_for_financials():
    bank = classify_sector("Banking")
    cf = CompanyFundamentals(symbol="HDFCBANK", provider_name="YahooFinance",
                             ratios=RatioSnapshot(pe=18.0, pb=2.8, ev_ebitda=12.0))
    vc = build_valuation_context(cf, sector_profile=bank)
    assert vc.ev_ebitda is None and not vc.ev_ebitda_applicable
    assert "EV/EBITDA" not in vc.missing_fields          # n/a, not "missing"
    assert vc.confidence == "high"                        # not penalised for the suppression
    assert vc.preferred_valuation == "P/B + ROE"
    assert vc.notes


def test_valuation_keeps_ev_ebitda_for_non_financial():
    it = classify_sector("IT")
    cf = CompanyFundamentals(symbol="TCS", ratios=RatioSnapshot(pe=28.0, pb=12.0, ev_ebitda=20.0))
    vc = build_valuation_context(cf, sector_profile=it)
    assert vc.ev_ebitda == 20.0 and vc.ev_ebitda_applicable


# ── missing-data handling ────────────────────────────────────────────────────────
def test_thesis_with_no_fundamentals_and_financial_profile_is_safe():
    res = generate_thesis(ThesisInputs(ticker="X", composite_score=50,
                                       sector_profile=classify_sector("Banking")))
    assert res.verdict in ("Neutral", "Positive", "Negative", "Strong Positive", "Strong Negative")
    assert res.bear_factors == [] or all("leverage" not in t.lower()
                                         for t in _texts(res.bear_factors))
