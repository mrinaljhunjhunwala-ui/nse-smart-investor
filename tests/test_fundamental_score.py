"""Pure tests for analysis/fundamental_score.py (no Streamlit, no network)."""
from __future__ import annotations

import re
from datetime import date

import pytest

from analysis.fundamental_score import (
    DISTRESS_CAP, LENDER_SKIPPED, T_LIQUID, T_SHARES, T_TURN, compute_fundamental_score,
    f_check_rows,
)
from analysis.fundamentals.models import (
    BalanceSheet, CashFlow, CompanyFundamentals, FiscalPeriod, IncomeStatement, RatioSnapshot,
)
from analysis.sector_classification import classify_sector

CR = 1e7
T, P = date(2026, 3, 31), date(2025, 3, 31)
IT = classify_sector("IT")
BANK = classify_sector("Banking")


def _cf(years, ratios=None):
    """years: list of (period_end, income kw, balance kw, cash kw), newest first. Values in ₹ cr."""
    def s(d):
        return {k: (v * CR if isinstance(v, (int, float)) and k not in ("eps_diluted",) else v)
                for k, v in d.items()}
    inc, bal, cfl = [], [], []
    for d, i, b, c in years:
        per = FiscalPeriod(period_end=d, fiscal_year=d.year)
        inc.append(IncomeStatement(period=per, **s(i)))
        bal.append(BalanceSheet(period=per, **s(b)))
        cfl.append(CashFlow(period=per, **s(c)))
    return CompanyFundamentals(symbol="TEST", provider_name="fixture",
                               income_statements=inc, balance_sheets=bal, cash_flows=cfl,
                               ratios=ratios)


STRONG = [
    (T, dict(revenue=1200, cost_of_revenue=700, net_income=130, operating_income=180,
             shares_diluted=100, eps_diluted=13.0),
     dict(total_assets=1050, current_assets=450, current_liabilities=200, long_term_debt=150,
          total_liabilities=450, total_equity=600, retained_earnings=500),
     dict(operating_cash_flow=160)),
    (P, dict(revenue=1000, cost_of_revenue=600, net_income=100, operating_income=150,
             shares_diluted=100, eps_diluted=10.0),
     dict(total_assets=1000, current_assets=400, current_liabilities=200, long_term_debt=200,
          total_liabilities=450, total_equity=550, retained_earnings=400),
     dict(operating_cash_flow=120)),
]
STRONG_RATIOS = RatioSnapshot(pe=20.0, pb=5.0, market_cap=3000 * CR)

WEAK = [
    (T, dict(revenue=900, cost_of_revenue=650, net_income=-40, operating_income=-20,
             shares_diluted=120),
     dict(total_assets=1000, current_assets=300, current_liabilities=400, long_term_debt=300,
          total_liabilities=900, total_equity=100, retained_earnings=-200),
     dict(operating_cash_flow=10)),
    (P, dict(revenue=1000, cost_of_revenue=600, net_income=50, operating_income=80,
             shares_diluted=100),
     dict(total_assets=1000, current_assets=400, current_liabilities=300, long_term_debt=200,
          total_liabilities=800, total_equity=200, retained_earnings=-150),
     dict(operating_cash_flow=60)),
]
WEAK_RATIOS = RatioSnapshot(pe=None, pb=2.0, market_cap=200 * CR)

LENDER = [
    (T, dict(revenue=500, net_income=150, shares_diluted=100),
     dict(total_assets=10000, total_equity=1000), dict(operating_cash_flow=300)),
    (P, dict(revenue=450, net_income=120, shares_diluted=100),
     dict(total_assets=9000, total_equity=900), dict(operating_cash_flow=200)),
]


def _drop(years, which, **fields):
    """Copy of `years` with the named balance/income fields set to None in BOTH years."""
    out = []
    for d, i, b, c in years:
        i, b = dict(i), dict(b)
        for k in fields.get("inc", ()):
            i.pop(k, None)
        for k in fields.get("bal", ()):
            b.pop(k, None)
        out.append((d, i, b, c))
    return out


def test_strong_non_lender_scores_9_of_9_and_100():
    fs = compute_fundamental_score(_cf(STRONG, STRONG_RATIOS), sector_profile=IT)
    assert fs.f_score == 9 and fs.f_tests_run == 9
    assert all(p is True for _, p, _ in fs.f_checks)
    assert fs.growth_pts == 20 and fs.valuation_pts == 20
    assert fs.z_zone == "safe" and fs.z_score > 3
    assert fs.score == 100
    assert fs.as_of == T and not fs.lender
    assert fs.summary == "Fundamentals 100/100 · F-score 9/9 · Z safe"


def test_weak_non_lender_f2_distress_capped():
    fs = compute_fundamental_score(_cf(WEAK, WEAK_RATIOS), sector_profile=IT)
    assert fs.f_score == 2 and fs.f_tests_run == 9
    assert fs.growth_pts == 0
    assert fs.valuation_pts is None            # loss-making: no positive P/E → block excluded
    assert fs.z_zone == "distress" and fs.z_score < 1.8
    assert fs.score is not None and fs.score <= DISTRESS_CAP
    assert any("distress zone" in r for r in fs.reasons)
    assert "OCF < net income" not in fs.reasons     # OCF 10 > NI -40 passes
    assert "ROA not positive" in fs.reasons


def test_distress_cap_bites_on_a_good_f_score():
    years = [(d, i, {**b, "retained_earnings": -2000}, c) for d, i, b, c in STRONG]
    ratios = RatioSnapshot(pe=20.0, market_cap=10 * CR)
    fs = compute_fundamental_score(_cf(years, ratios), sector_profile=IT)
    assert fs.f_score == 9 and fs.z_zone == "distress"
    assert fs.score == DISTRESS_CAP
    assert fs.reasons[0].endswith(f"(score capped at {DISTRESS_CAP})")


def test_lender_routed_via_sector_classification():
    assert BANK.is_financial
    ratios = RatioSnapshot(pb=2.0)
    fs = compute_fundamental_score(_cf(LENDER, ratios), sector_profile=BANK)
    assert fs.lender and fs.z_zone == "n/a (lender)" and fs.z_score is None
    names = [n for n, _, _ in fs.f_checks]
    assert not set(LENDER_SKIPPED) & set(names)
    assert fs.f_tests_applicable == 6 and fs.f_tests_run == 6
    # ROE = 150 / avg(1000, 900) = 15.8% ≥ 12 and P/B 2.0 ≤ 3 → 14
    assert fs.valuation_pts == 14
    assert "not applicable to lenders" in fs.f_label
    rows = f_check_rows(fs)
    assert sum(r["Result"] == "not applicable" for r in rows) == 3
    # a non-lender read of the same statements would run Z / debt tests
    assert compute_fundamental_score(_cf(LENDER, ratios), sector_profile=IT).f_tests_applicable == 9


def test_one_statement_is_none_with_missing():
    fs = compute_fundamental_score(_cf(STRONG[:1], STRONG_RATIOS), sector_profile=IT)
    assert fs.score is None and fs.f_score is None
    assert any("prior annual statement" in m for m in fs.missing)
    assert fs.summary == "Fundamentals: not enough data (needs two annual statements)"


def test_no_statements_and_none_cf():
    assert compute_fundamental_score(None).score is None
    fs = compute_fundamental_score(CompanyFundamentals(symbol="X"))
    assert fs.score is None and fs.missing == ["annual income statements"]


def test_partial_seven_of_nine_rescales():
    years = _drop(STRONG, None, inc=("shares_diluted",), bal=("current_assets",))
    # make asset turnover fall: latest revenue / assets below prior
    years[0] = (years[0][0], {**years[0][1], "revenue": 1040, "cost_of_revenue": 600}, years[0][2], years[0][3])
    fs = compute_fundamental_score(_cf(years, STRONG_RATIOS), sector_profile=IT)
    res = {n: p for n, p, _ in fs.f_checks}
    assert res[T_LIQUID] is None and res[T_SHARES] is None and res[T_TURN] is False
    assert fs.f_tests_run == 7 and fs.f_score == 6
    assert fs.f_label == "F-score 6/7 (2 tests no data)"
    # 60×6/7 + growth 20 (rev +4%, NI +30% → both up, not both >10% → 14) + valuation
    expected = round(100 * (60 * 6 / 7 + fs.growth_pts + fs.valuation_pts) / 100)
    assert fs.growth_pts == 14
    assert fs.score == expected
    assert fs.z_score is None and "working capital" in fs.z_zone


def test_too_few_tests_is_none():
    years = _drop(STRONG, None, inc=("shares_diluted", "cost_of_revenue", "revenue"),
                  bal=("current_assets", "long_term_debt"))
    fs = compute_fundamental_score(_cf(years, STRONG_RATIOS), sector_profile=IT)
    assert fs.f_tests_run < 6 and fs.score is None
    assert fs.missing


@pytest.mark.parametrize("pe,eps_now,pts", [
    (20.0, 13.0, 20),     # PEG 0.67
    (20.0, 10.5, 14),     # EPS +5% → PEG 4 → PE ≤ 25
    (35.0, 10.5, 8),
    (48.0, 10.5, 2),
])
def test_valuation_bands(pe, eps_now, pts):
    years = [(STRONG[0][0], {**STRONG[0][1], "eps_diluted": eps_now}, STRONG[0][2], STRONG[0][3]),
             STRONG[1]]
    fs = compute_fundamental_score(_cf(years, RatioSnapshot(pe=pe, market_cap=3000 * CR)),
                                   sector_profile=IT)
    assert fs.valuation_pts == pts
    if pts == 2:
        assert any(r.startswith("PE 48 — above 40") for r in fs.reasons)


def test_revenue_down_caps_growth_at_4():
    years = [(T, {**STRONG[0][1], "revenue": 950}, STRONG[0][2], STRONG[0][3]), STRONG[1]]
    fs = compute_fundamental_score(_cf(years, STRONG_RATIOS), sector_profile=IT)
    assert fs.growth_pts == 4


ADVICE = re.compile(r"\b(buy|sell|hold|accumulate|avoid|exit|should|recommend\w*|"
                    r"invest now|target price)\b", re.I)


@pytest.mark.parametrize("years,ratios,sp", [
    (STRONG, STRONG_RATIOS, IT), (WEAK, WEAK_RATIOS, IT),
    (LENDER, RatioSnapshot(pb=2.0), BANK), (STRONG[:1], STRONG_RATIOS, IT),
])
def test_no_advice_words(years, ratios, sp):
    fs = compute_fundamental_score(_cf(years, ratios), sector_profile=sp)
    text = " ".join(fs.reasons + fs.missing + [fs.summary] + [d for _, _, d in fs.f_checks]
                    + [r["Detail"] for r in f_check_rows(fs)])
    assert not ADVICE.search(text), text
