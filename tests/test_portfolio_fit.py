"""tests/test_portfolio_fit.py — deterministic tests for Phase B Portfolio Fit.

NO AI. All tests build a PortfolioFitInputs by hand and assert on the structured output —
no network, fully reproducible. Covers fit rating, each impact dimension, position-size
guidance, traceability and the empty-book edge case.
"""
from __future__ import annotations

from analysis.thesis import (
    PortfolioFitInputs, assess_fit, build_fit_inputs, FIT_RATINGS, POSITIVE, NEGATIVE,
)
from analysis.thesis.portfolio_fit import (
    SRC_CORRELATION, SRC_SECTOR, SRC_BETA, SRC_CONCENTRATION, SRC_THESIS,
)


# ── helpers / fixtures ───────────────────────────────────────────────────────────
def _diversified_book(**over):
    """A balanced 5-name book; candidate is a low-correlation new sector, good thesis."""
    base = dict(
        candidate_ticker="NEWCO", candidate_sector="Pharma",
        candidate_beta=0.85, candidate_vol_pct=22.0,
        candidate_verdict="Positive", candidate_verdict_score=1,
        avg_correlation=0.22, max_correlation=0.35, most_correlated_with="TCS",
        n_holdings=5, portfolio_beta=1.05,
        sector_weights={"IT": 30.0, "Banks": 25.0, "Auto": 20.0, "FMCG": 15.0, "Energy": 10.0},
        top_sector="IT", top_sector_pct=30.0, concentration_risk="MEDIUM",
    )
    base.update(over)
    return PortfolioFitInputs(**base)


def _concentrated_conflict(**over):
    """Candidate piles into an already-dominant sector, redundant, weak thesis."""
    base = dict(
        candidate_ticker="HDFCBANK", candidate_sector="Banks",
        candidate_beta=1.4, candidate_vol_pct=44.0,
        candidate_verdict="Negative", candidate_verdict_score=-1,
        avg_correlation=0.86, max_correlation=0.92, most_correlated_with="ICICIBANK",
        n_holdings=4, portfolio_beta=1.15,
        sector_weights={"Banks": 55.0, "IT": 25.0, "Auto": 20.0},
        top_sector="Banks", top_sector_pct=55.0, concentration_risk="HIGH",
    )
    base.update(over)
    return PortfolioFitInputs(**base)


def _pos_texts(res):
    return [f.text for f in res.positive_effects]


def _neg_texts(res):
    return [f.text for f in res.negative_effects]


# ── FIT RATING ───────────────────────────────────────────────────────────────────
def test_strong_fit_for_diversifying_good_stock():
    res = assess_fit(_diversified_book())
    assert res.fit_rating == "Strong Fit"
    assert res.fit_score >= 3


def test_strong_conflict_for_concentrated_redundant_weak():
    res = assess_fit(_concentrated_conflict(candidate_verdict="Strong Negative",
                                            candidate_verdict_score=-2))
    assert res.fit_rating == "Strong Conflict"
    assert res.fit_score == -3


def test_neutral_when_signals_cancel():
    # Candidate in a held (non-top) sector: improves balance (+1 concentration) but is
    # highly correlated (-1 redundant); beta/thesis neutral → nets to 0 → Neutral.
    inp = PortfolioFitInputs(
        candidate_ticker="X", candidate_sector="Auto", candidate_beta=1.0,
        candidate_verdict="Neutral", candidate_verdict_score=0,
        avg_correlation=0.85, max_correlation=0.88, most_correlated_with="M&M",
        n_holdings=5, portfolio_beta=1.0,
        sector_weights={"IT": 30.0, "Auto": 25.0, "Banks": 20.0, "FMCG": 15.0, "Energy": 10.0},
        top_sector="IT", top_sector_pct=30.0, concentration_risk="MEDIUM",
    )
    res = assess_fit(inp)
    assert res.fit_rating in FIT_RATINGS
    assert res.fit_rating == "Neutral"
    assert res.fit_score == 0


def test_fit_rating_always_valid_label():
    for vs in (-2, -1, 0, 1, 2):
        for ac in (0.1, 0.5, 0.9):
            res = assess_fit(_diversified_book(candidate_verdict_score=vs, avg_correlation=ac))
            assert res.fit_rating in FIT_RATINGS


def test_poor_fit_for_redundant_but_decent_thesis():
    res = assess_fit(_concentrated_conflict(candidate_verdict="Positive",
                                            candidate_verdict_score=1,
                                            concentration_risk="HIGH"))
    assert res.fit_rating in ("Poor Fit", "Strong Conflict")
    assert res.fit_score < 0


# ── DIVERSIFICATION (correlation) ────────────────────────────────────────────────
def test_low_correlation_is_positive_diversifier():
    res = assess_fit(_diversified_book(avg_correlation=0.15))
    assert any("diversif" in t.lower() for t in _pos_texts(res))
    assert "0.15" in res.diversification_impact


def test_high_correlation_is_negative_redundant():
    res = assess_fit(_diversified_book(avg_correlation=0.88))
    neg = [f for f in res.negative_effects if f.source == SRC_CORRELATION]
    assert neg and "redundant" in neg[0].text.lower()
    assert "0.88" in neg[0].evidence


def test_correlation_evidence_names_most_correlated():
    res = assess_fit(_diversified_book(avg_correlation=0.9, max_correlation=0.95,
                                       most_correlated_with="INFY"))
    neg = [f for f in res.negative_effects if f.source == SRC_CORRELATION]
    assert neg and "INFY" in neg[0].evidence


# ── SECTOR impact ────────────────────────────────────────────────────────────────
def test_sector_impact_reports_before_after():
    # candidate in IT (currently 30%), added equal-weight to a 5-name book → ~42%
    res = assess_fit(_diversified_book(candidate_sector="IT"))
    assert "IT" in res.sector_impact and "%" in res.sector_impact
    assert "→" in res.sector_impact or "to" in res.sector_impact


def test_sector_overconcentration_is_negative():
    res = assess_fit(_concentrated_conflict(candidate_sector="Banks"))
    neg = [f for f in res.negative_effects if f.source == SRC_SECTOR]
    assert neg
    assert any("Banks" in f.evidence for f in neg)


def test_new_sector_is_positive_broadening():
    res = assess_fit(_diversified_book(candidate_sector="Pharma"))   # not in the book
    assert any(f.source == SRC_SECTOR and f.polarity == POSITIVE for f in res.positive_effects)
    assert "new sector" in res.sector_impact.lower()


# ── BETA impact ──────────────────────────────────────────────────────────────────
def test_beta_reduction_is_positive():
    res = assess_fit(_diversified_book(candidate_beta=0.5, portfolio_beta=1.10))
    beta_pos = [f for f in res.positive_effects if f.source == SRC_BETA]
    assert beta_pos and "lower" in beta_pos[0].text.lower()
    assert "→" in beta_pos[0].evidence


def test_beta_increase_above_threshold_is_negative():
    # high candidate beta on a small book pushes portfolio beta over 1.2
    res = assess_fit(_diversified_book(candidate_beta=2.2, portfolio_beta=1.15, n_holdings=2))
    beta_neg = [f for f in res.negative_effects if f.source == SRC_BETA]
    assert beta_neg


def test_beta_impact_string_present():
    res = assess_fit(_diversified_book())
    assert "beta" in res.beta_impact.lower()


# ── CONCENTRATION impact ─────────────────────────────────────────────────────────
def test_concentration_worsens_when_adding_to_high_top_sector():
    res = assess_fit(_concentrated_conflict(candidate_sector="Banks"))
    neg = [f for f in res.negative_effects if f.source == SRC_CONCENTRATION]
    assert neg
    assert "largest" in res.concentration_impact.lower() or "Banks" in res.concentration_impact


def test_concentration_improves_when_outside_top_sector():
    res = assess_fit(_diversified_book(candidate_sector="Pharma"))
    pos = [f for f in res.positive_effects if f.source == SRC_CONCENTRATION]
    assert pos and "balance" in res.concentration_impact.lower()


# ── POSITION SIZE guidance ───────────────────────────────────────────────────────
def test_position_large_when_no_pressures():
    res = assess_fit(_diversified_book())
    assert res.position_size_guidance == "Large"
    assert "no" in res.position_size_reason.lower()


def test_position_small_with_multiple_pressures():
    # high corr + high beta + high vol + sector concentration, good thesis (so not gated)
    res = assess_fit(_concentrated_conflict(candidate_verdict="Positive",
                                            candidate_verdict_score=1))
    assert res.position_size_guidance == "Small"
    assert ";" in res.position_size_reason or "pressures" in res.position_size_reason.lower()


def test_position_moderate_with_one_pressure():
    res = assess_fit(_diversified_book(candidate_beta=1.5, candidate_vol_pct=20.0,
                                       avg_correlation=0.2))
    assert res.position_size_guidance == "Moderate"


def test_weak_thesis_forces_small_size():
    res = assess_fit(_diversified_book(candidate_verdict="Negative", candidate_verdict_score=-1))
    assert res.position_size_guidance == "Small"
    assert "thesis" in res.position_size_reason.lower()


# ── TRACEABILITY ─────────────────────────────────────────────────────────────────
def test_every_effect_is_traceable():
    res = assess_fit(_diversified_book())
    allf = res.positive_effects + res.negative_effects
    assert allf
    for f in allf:
        assert f.text and f.source and f.evidence
        assert f.polarity in (POSITIVE, NEGATIVE)


def test_supporting_evidence_is_union_of_effects():
    res = assess_fit(_concentrated_conflict())
    assert len(res.supporting_evidence) == len(res.positive_effects) + len(res.negative_effects)


def test_inputs_present_lists_subsystems():
    res = assess_fit(_diversified_book())
    assert SRC_CORRELATION in res.inputs_present
    assert SRC_BETA in res.inputs_present
    assert SRC_THESIS in res.inputs_present


def test_to_dict_serialisable():
    d = assess_fit(_diversified_book()).to_dict()
    assert d["fit_rating"] in FIT_RATINGS
    assert isinstance(d["positive_effects"], list)
    assert d["positive_effects"][0]["source"]


def test_determinism_same_inputs_same_output():
    a = assess_fit(_diversified_book()).to_dict()
    b = assess_fit(_diversified_book()).to_dict()
    assert a == b


# ── EDGE: empty portfolio ────────────────────────────────────────────────────────
def test_empty_portfolio_is_neutral_first_position():
    inp = PortfolioFitInputs(candidate_ticker="FIRST", candidate_sector="IT",
                             candidate_beta=1.0, candidate_verdict="Positive",
                             candidate_verdict_score=1, n_holdings=0)
    res = assess_fit(inp)
    assert "first position" in res.diversification_impact.lower()
    assert res.fit_rating in FIT_RATINGS
    # no portfolio-relative negatives possible
    assert all(f.source not in (SRC_CORRELATION, SRC_CONCENTRATION) for f in res.negative_effects)


def test_assumed_weight_overrides_equalweight():
    big = assess_fit(_diversified_book(candidate_sector="IT", assumed_weight_pct=50.0))
    small = assess_fit(_diversified_book(candidate_sector="IT", assumed_weight_pct=5.0))
    # a 50% slug pushes IT far higher than a 5% slug
    assert "to " in big.sector_impact or "→" in big.sector_impact
    assert big.fit_score <= small.fit_score


# ── build_fit_inputs integration seam (injected loader, no network) ──────────────
def test_build_fit_inputs_with_injected_loader():
    import pandas as pd
    import numpy as np

    rng = np.random.default_rng(0)
    idx = pd.bdate_range("2024-01-01", periods=120)

    def _series(drift):
        return pd.Series(100 + np.cumsum(rng.normal(drift, 1.0, len(idx))), index=idx)

    prices = {"AAA.NS": _series(0.05), "BBB.NS": _series(0.04), "CAND.NS": _series(0.03)}

    def loader(tkr, period="1y"):
        return pd.DataFrame({"Close": prices[tkr]})

    holdings = [{"ticker": "AAA.NS", "quantity": 10}, {"ticker": "BBB.NS", "quantity": 5}]
    inp = build_fit_inputs("CAND.NS", holdings, price_loader=loader,
                           candidate_thesis=type("T", (), {"verdict": "Positive",
                                                           "verdict_score": 1})(),
                           candidate_beta=0.9, candidate_sector="Pharma")
    assert inp.n_holdings == 2
    assert inp.candidate_vol_pct is not None         # computed from candidate returns
    assert inp.avg_correlation is not None            # candidate vs holdings
    assert inp.sector_weights                          # built from holdings
    res = assess_fit(inp)
    assert res.fit_rating in FIT_RATINGS
