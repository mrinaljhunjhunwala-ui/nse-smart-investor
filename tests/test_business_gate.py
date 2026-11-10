"""Pure tests for analysis/business_gate.py (no Streamlit, no network)."""
from __future__ import annotations

import re
from types import SimpleNamespace

import pytest

from analysis.business_gate import (
    CAUTION, FAIL, INSUFFICIENT_DATA, PASS, assess_business, flag_severity,
    is_data_missing_guard, metrics_from_fundamentals,
)
from analysis.sector_classification import classify_sector

BANK = classify_sector("Banking")
IT = classify_sector("IT")
CR = 1e7  # one crore in rupees

# A healthy non-lender: every check has data and nothing is adverse.
GOOD = dict(
    quality_score=72.0, valuation_posture="REASONABLE", flags_severity="none",
    sector_profile=IT,
    metrics={"net_income": 500 * CR, "total_equity": 4000 * CR,
             "operating_cash_flow": 600 * CR, "debt_to_equity": 0.3},
)


def _with(**over):
    d = {**GOOD, **over}
    if "metrics" in over and over["metrics"] is not None:
        d["metrics"] = {**GOOD["metrics"], **over["metrics"]}
    return d


CASES = [
    ("healthy", {}, PASS, "no adverse finding"),
    ("red flag", {"flags_severity": "red"}, FAIL, "red governance"),
    ("quality zero", {"quality_score": 0.0}, FAIL, "quality score 0/100"),
    ("quality 22", {"quality_score": 22.0}, FAIL, "quality score 22/100"),
    ("negative equity", {"metrics": {"total_equity": -120 * CR}}, FAIL, "negative net worth"),
    ("H2 guard, equity unknown",
     {"valuation_posture": "INSUFFICIENT_EVIDENCE", "valuation_guard": "H2-negative-equity",
      "metrics": {"total_equity": None}}, FAIL, "net worth not positive"),
    ("demanding valuation", {"valuation_posture": "DEMANDING_VS_GROWTH"}, CAUTION, "demanding"),
    ("quality 40", {"quality_score": 40.0}, CAUTION, "quality score 40/100"),
    ("amber flag", {"flags_severity": "amber"}, CAUTION, "amber governance"),
    ("flags unchecked", {"flags_severity": "unchecked"}, CAUTION, "not yet checked"),
    ("loss-making, equity positive", {"metrics": {"net_income": -50 * CR}}, CAUTION, "loss-making"),
    ("high leverage", {"metrics": {"debt_to_equity": 3.1}}, CAUTION, "debt/equity 3.1"),
    ("negative OCF with profit", {"metrics": {"operating_cash_flow": -10 * CR}}, CAUTION,
     "operating cash flow negative"),
    ("fundamentals missing", {"fundamentals_missing": True, "quality_score": None, "metrics": None},
     INSUFFICIENT_DATA, "no company financials"),
    ("H3 refusal, no quality",
     {"quality_score": None, "valuation_posture": "INSUFFICIENT_EVIDENCE",
      "valuation_guard": "H3-missing-metric"}, INSUFFICIENT_DATA, "core fundamentals not found"),
    ("nothing fundamental at all",
     {"quality_score": None, "valuation_posture": None, "metrics": None},
     INSUFFICIENT_DATA, "no fundamental figures"),
    ("red flag beats missing data",
     {"fundamentals_missing": True, "quality_score": None, "flags_severity": "red"}, FAIL, "red"),
]


@pytest.mark.parametrize("name,over,status,reason_part", CASES, ids=[c[0] for c in CASES])
def test_status_table(name, over, status, reason_part):
    kw = _with(**over)
    if over.get("metrics", "x") is None:
        kw["metrics"] = None
    g = assess_business(**kw)
    assert g.status == status, g.reasons
    assert reason_part in g.headline_reason or any(reason_part in r for r in g.reasons)


def test_not_applicable_refusal_with_quality_is_not_insufficient():
    g = assess_business(**_with(valuation_posture="INSUFFICIENT_EVIDENCE",
                                valuation_guard="growth-lens-off"))
    assert g.status == PASS
    assert "valuation" in g.unavailable


def test_growth_lens_off_is_not_a_data_missing_guard():
    assert not is_data_missing_guard("growth-lens-off")
    assert not is_data_missing_guard("H1-negative-earnings")
    assert is_data_missing_guard("H3-missing-metric")
    assert not is_data_missing_guard(None)


def test_lender_is_not_judged_on_leverage_or_cash_flow():
    # A bank with D/E of 9 and negative OCF is normal (deposits are not debt).
    g = assess_business(quality_score=65.0, valuation_posture="REASONABLE",
                        flags_severity="none", sector_profile=BANK,
                        metrics={"net_income": 900 * CR, "total_equity": 9000 * CR,
                                 "operating_cash_flow": -300 * CR, "debt_to_equity": 9.0,
                                 "roe": 14.0})
    assert g.status == PASS, g.reasons
    assert "leverage" not in g.checked and "cash flow" not in g.checked
    assert "return on equity" in g.checked


def test_lender_negative_roe_is_caution():
    g = assess_business(quality_score=65.0, valuation_posture="REASONABLE",
                        flags_severity="none", sector_profile=BANK,
                        metrics={"net_income": 100 * CR, "total_equity": 9000 * CR, "roe": -2.5})
    assert g.status == CAUTION
    assert "return on equity negative" in g.headline_reason


def test_same_metrics_non_lender_flags_leverage():
    g = assess_business(quality_score=65.0, valuation_posture="REASONABLE",
                        flags_severity="none", sector_profile=IT,
                        metrics={"net_income": 900 * CR, "total_equity": 9000 * CR,
                                 "operating_cash_flow": 50 * CR, "debt_to_equity": 9.0})
    assert g.status == CAUTION
    assert any("debt/equity" in r for r in g.reasons)


def test_real_finding_leads_over_unchecked_flags():
    g = assess_business(**_with(flags_severity="unchecked", quality_score=45.0))
    assert g.headline_reason.startswith("quality score 45")


_ADVICE = re.compile(r"\b(buy|sell|hold|avoid|accumulate|exit)\b", re.I)


def test_no_advice_words_in_any_reason():
    for _, over, _, _ in CASES:
        kw = _with(**over)
        if over.get("metrics", "x") is None:
            kw["metrics"] = None
        for r in assess_business(**kw).reasons:
            assert not _ADVICE.search(r), r


def test_flag_severity_collapse():
    assert flag_severity(None) == ("unchecked", "")
    assert flag_severity([]) == ("none", "")
    sev, top = flag_severity([{"sentiment": "green", "headline": "g"},
                              {"sentiment": "amber", "headline": "a"},
                              {"sentiment": "red", "headline": "r"}])
    assert (sev, top) == ("red", "r")
    assert flag_severity([{"sentiment": "neutral"}])[0] == "amber"   # legacy spelling
    assert flag_severity([{"sentiment": "green"}])[0] == "green"


def test_metrics_from_fundamentals_duck_typed():
    cf = SimpleNamespace(
        latest_income=lambda: SimpleNamespace(net_income=-5.0),
        latest_balance=lambda: SimpleNamespace(total_equity=10.0),
        latest_cashflow=lambda: None,
    )
    an = {"debt_to_equity": SimpleNamespace(available=True, value=1.5),
          "roe": SimpleNamespace(available=False, value=None)}
    assert metrics_from_fundamentals(cf, an) == {"net_income": -5.0, "total_equity": 10.0,
                                                 "debt_to_equity": 1.5}
    assert metrics_from_fundamentals(None, None) == {}
