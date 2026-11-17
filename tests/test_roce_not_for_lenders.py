"""Owner, 17 Nov: ROCE is not applicable to banking stocks (CLAUDE.md rule 3)."""
from analysis.portfolio_fundamentals import compute_quality_score, quality_score_coverage


def test_bank_quality_ignores_roce():
    bank = {"ticker": "HDFCBANK.NS", "roe": 15.0, "roce": 2.0, "revenue_cagr_3y": 20.0, "eps_cagr_3y": 20.0}
    # ROCE 2% used to cost a strong bank 26 of 30 points; now it is left out and the rest rescaled
    assert compute_quality_score(bank) == 100
    assert quality_score_coverage(bank) == (3, 3)


def test_industrial_quality_still_uses_roce():
    co = {"ticker": "TCS.NS", "roe": 15.0, "roce": 2.0, "revenue_cagr_3y": 20.0, "eps_cagr_3y": 20.0}
    assert compute_quality_score(co) == 74 and quality_score_coverage(co) == (4, 4)


def test_explicit_flag_wins():
    assert quality_score_coverage({"ticker": "TCS.NS", "roe": 1, "is_financial": True}) == (1, 3)
