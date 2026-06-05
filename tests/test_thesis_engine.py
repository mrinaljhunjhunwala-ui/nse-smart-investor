"""tests/test_thesis_engine.py — deterministic tests for the Structured Thesis Engine.

Phase A1. NO AI. All tests build a `ThesisInputs` by hand and assert on the structured
output — no network, no subsystem calls, fully reproducible. Covers bull/bear/risk/
verdict generation + traceability metadata.
"""
from __future__ import annotations

import pytest

from analysis.thesis import (
    ThesisInputs, generate_thesis, build_inputs, VERDICTS, BULL, BEAR, RISK,
)
from analysis.thesis import thesis_rules as rules
from analysis.thesis.thesis_models import (
    SRC_FUNDAMENTALS, SRC_TECHNICAL, SRC_MOMENTUM, SRC_DEEP, SRC_BETA, SRC_SENTIMENT,
    SRC_COMPOSITE,
)


# ── helpers ──────────────────────────────────────────────────────────────────────
def _texts(factors):
    return [f.text for f in factors]


def _has_evidence(factors, substr):
    return any(substr.lower() in f.evidence.lower() for f in factors)


def _strong_bull_inputs():
    return ThesisInputs(
        ticker="TESTBULL", composite_score=82, action="STRONG BUY", grade="A",
        technical_score=34, momentum_score=21, volume_score=12, pattern_score=7,
        sentiment_score=7, weekly_trend="uptrend", rel_strength="outperforming",
        rs_pct=6.2, earnings_days=40, signal_bull=8, signal_total=9,
        revenue_cagr=18.4, eps_cagr=22.0, roe=21.0, debt_to_equity=0.30,
        beta=0.95, sector="IT",
    )


def _strong_bear_inputs():
    return ThesisInputs(
        ticker="TESTBEAR", composite_score=22, action="EXIT", grade="F",
        technical_score=8, momentum_score=5, volume_score=3, pattern_score=0,
        sentiment_score=2, weekly_trend="downtrend", rel_strength="underperforming",
        rs_pct=-9.0, earnings_days=3, signal_bull=1, signal_total=9,
        revenue_cagr=-6.0, eps_cagr=-12.0, roe=4.0, debt_to_equity=2.4,
        beta=1.6, sector="Realty", news_sentiment="negative",
    )


# ── BULL factor generation ───────────────────────────────────────────────────────
def test_bull_revenue_cagr_factor():
    inp = ThesisInputs(ticker="X", revenue_cagr=18.4)
    bull = rules.bull_factors(inp)
    assert any("Revenue" in t and "compounding" in t for t in _texts(bull))
    assert _has_evidence(bull, "Revenue CAGR = 18.4%")
    assert all(f.polarity == BULL for f in bull)


def test_bull_roe_factor_source_and_evidence():
    inp = ThesisInputs(ticker="X", roe=21.0)
    bull = rules.bull_factors(inp)
    roe_f = [f for f in bull if "return on equity" in f.text.lower()]
    assert roe_f and roe_f[0].source == SRC_FUNDAMENTALS
    assert "ROE = 21.0%" in roe_f[0].evidence


def test_bull_technical_and_momentum():
    inp = ThesisInputs(ticker="X", technical_score=34, momentum_score=21)
    bull = rules.bull_factors(inp)
    assert any("technical trend" in t.lower() for t in _texts(bull))
    assert any("momentum" in t.lower() for t in _texts(bull))


def test_bull_weekly_uptrend_and_relative_strength():
    inp = ThesisInputs(ticker="X", weekly_trend="uptrend",
                       rel_strength="outperforming", rs_pct=6.2)
    bull = rules.bull_factors(inp)
    assert any("weekly" in t.lower() for t in _texts(bull))
    rs = [f for f in bull if "relative strength" in f.text.lower()]
    assert rs and rs[0].source == SRC_DEEP and "+6.2%" in rs[0].evidence


def test_bull_multi_signal_agreement():
    inp = ThesisInputs(ticker="X", signal_bull=8, signal_total=9)
    bull = rules.bull_factors(inp)
    sig = [f for f in bull if "multi-signal" in f.text.lower()]
    assert sig and "8/9" in sig[0].evidence


def test_bull_steady_vs_strong_revenue_threshold():
    steady = rules.bull_factors(ThesisInputs(ticker="X", revenue_cagr=10.0))
    assert any("steadily" in t for t in _texts(steady))
    strong = rules.bull_factors(ThesisInputs(ticker="X", revenue_cagr=20.0))
    assert any("strongly" in t for t in _texts(strong))


def test_no_bull_factors_when_weak():
    assert rules.bull_factors(_strong_bear_inputs()) == []


# ── BEAR factor generation ───────────────────────────────────────────────────────
def test_bear_revenue_decline():
    inp = ThesisInputs(ticker="X", revenue_cagr=-6.0)
    bear = rules.bear_factors(inp)
    assert any("declining" in t.lower() for t in _texts(bear))
    assert _has_evidence(bear, "-6.0%")
    assert all(f.polarity == BEAR for f in bear)


def test_bear_weak_technical_and_momentum():
    inp = ThesisInputs(ticker="X", technical_score=8, momentum_score=5)
    bear = rules.bear_factors(inp)
    assert any("technical" in t.lower() for t in _texts(bear))
    assert any("momentum" in t.lower() for t in _texts(bear))


def test_bear_downtrend_and_underperformance():
    inp = ThesisInputs(ticker="X", weekly_trend="downtrend",
                       rel_strength="underperforming", rs_pct=-9.0)
    bear = rules.bear_factors(inp)
    assert any("downtrend" in t.lower() for t in _texts(bear))
    under = [f for f in bear if "underperforming" in f.text.lower()]
    assert under and "-9.0%" in under[0].evidence


def test_bear_composite_negative():
    inp = ThesisInputs(ticker="X", composite_score=22)
    bear = rules.bear_factors(inp)
    assert any("negative" in t.lower() for t in _texts(bear))


def test_no_bear_factors_when_strong():
    assert rules.bear_factors(_strong_bull_inputs()) == []


# ── RISK generation (the required set) ───────────────────────────────────────────
def test_risk_high_beta():
    inp = ThesisInputs(ticker="X", beta=1.6)
    risks = rules.key_risks(inp)
    r = [f for f in risks if f.source == SRC_BETA]
    assert r and "Beta = 1.60" in r[0].evidence and r[0].polarity == RISK


def test_risk_high_debt_equity():
    inp = ThesisInputs(ticker="X", debt_to_equity=2.4)
    risks = rules.key_risks(inp)
    r = [f for f in risks if "leverage" in f.text.lower()]
    assert r and "D/E = 2.40x" in r[0].evidence


def test_risk_weak_momentum():
    inp = ThesisInputs(ticker="X", momentum_score=5)
    risks = rules.key_risks(inp)
    assert any("momentum" in t.lower() for t in _texts(risks))


def test_risk_earnings_proximity():
    inp = ThesisInputs(ticker="X", earnings_days=3)
    risks = rules.key_risks(inp)
    r = [f for f in risks if "earnings" in f.text.lower()]
    assert r and "3" in r[0].evidence
    # outside the window → no earnings risk
    assert not any("earnings" in t.lower()
                   for t in _texts(rules.key_risks(ThesisInputs(ticker="X", earnings_days=40))))


def test_risk_negative_sentiment():
    inp = ThesisInputs(ticker="X", news_sentiment="negative")
    risks = rules.key_risks(inp)
    assert any(f.source == SRC_SENTIMENT for f in risks)


def test_risk_technical_weakness():
    inp = ThesisInputs(ticker="X", technical_score=8)
    risks = rules.key_risks(inp)
    assert any("technical" in t.lower() for t in _texts(risks))


def test_risk_partial_fundamentals_flag():
    inp = ThesisInputs(ticker="X", fundamentals_partial=True)
    risks = rules.key_risks(inp)
    assert any("partial" in t.lower() for t in _texts(risks))


def test_no_risks_for_clean_strong_stock():
    # strong bull: low beta, low D/E, strong momentum, far earnings, good sentiment
    assert rules.key_risks(_strong_bull_inputs()) == []


# ── VERDICT generation ───────────────────────────────────────────────────────────
def test_verdict_strong_positive():
    res = generate_thesis(_strong_bull_inputs())
    assert res.verdict == "Strong Positive"
    assert res.verdict_score == 2


def test_verdict_strong_negative():
    res = generate_thesis(_strong_bear_inputs())
    assert res.verdict == "Strong Negative"
    assert res.verdict_score == -2


def test_verdict_neutral_midband():
    inp = ThesisInputs(ticker="X", composite_score=52)   # 45–61 band, no factors
    res = generate_thesis(inp)
    assert res.verdict == "Neutral"
    assert res.verdict_score == 0


def test_verdict_is_always_a_valid_label():
    for score in (5, 25, 47, 55, 68, 78, 95):
        res = generate_thesis(ThesisInputs(ticker="X", composite_score=score))
        assert res.verdict in VERDICTS


def test_verdict_heavy_risk_tempers_positive():
    # mid-high score but a wall of risks should pull the verdict down by a notch
    base = ThesisInputs(ticker="X", composite_score=70)
    loaded = ThesisInputs(ticker="X", composite_score=70, beta=1.6,
                          debt_to_equity=2.0, momentum_score=5,
                          earnings_days=2, technical_score=8)
    v_base = generate_thesis(base).verdict_score
    v_loaded = generate_thesis(loaded).verdict_score
    assert v_loaded < v_base


# ── TRACEABILITY metadata ────────────────────────────────────────────────────────
def test_every_factor_is_traceable():
    res = generate_thesis(_strong_bull_inputs())
    allf = res.bull_factors + res.bear_factors + res.key_risks
    assert allf, "expected at least some factors"
    for f in allf:
        assert f.text and isinstance(f.text, str)
        assert f.source and isinstance(f.source, str)
        assert f.evidence and isinstance(f.evidence, str)
        assert f.polarity in (BULL, BEAR, RISK)


def test_verdict_rationale_and_inputs_present():
    res = generate_thesis(_strong_bull_inputs())
    assert "⇒" in res.verdict_rationale and "Composite" in res.verdict_rationale
    # provenance lists the subsystems that contributed
    assert SRC_COMPOSITE in res.inputs_present
    assert SRC_FUNDAMENTALS in res.inputs_present
    assert SRC_DEEP in res.inputs_present
    assert SRC_BETA in res.inputs_present


def test_result_to_dict_is_serialisable():
    res = generate_thesis(_strong_bull_inputs())
    d = res.to_dict()
    assert d["verdict"] in VERDICTS
    assert isinstance(d["bull_factors"], list)
    assert d["bull_factors"][0]["source"]   # each factor carries its source


def test_determinism_same_inputs_same_output():
    a = generate_thesis(_strong_bull_inputs()).to_dict()
    b = generate_thesis(_strong_bull_inputs()).to_dict()
    a.pop("generated_at"); b.pop("generated_at")
    assert a == b


# ── build_inputs (integration seam) with injected pieces, no network ─────────────
def test_build_inputs_uses_injected_pieces_without_network():
    class _CS:  # mimics CompositeScore duck-type
        score = 80; action = "BUY"; grade = "A"
        technical_score = 33; momentum_score = 20; volume_score = 11
        pattern_score = 6; sentiment_score = 7; risk_reward = 2.1; sector = "IT"
    deep = {"weekly": "uptrend", "rel_strength": "outperforming", "rs_pct": 5.0,
            "earnings_days": 30, "bull": 7, "total": 9}

    class _AR:  # mimics AnalyticResult
        def __init__(self, v): self.value = v; self.available = v is not None
    fundamentals = {"results": {"revenue_cagr": _AR(16.0), "eps_cagr": _AR(19.0),
                                "roe": _AR(20.0), "debt_to_equity": _AR(0.4)},
                    "partial": False}

    inp = build_inputs("ZZZ", composite=_CS(), deep=deep,
                       fundamentals=fundamentals, beta=0.9, sector="IT")
    assert inp.composite_score == 80 and inp.technical_score == 33
    assert inp.weekly_trend == "uptrend" and inp.rs_pct == 5.0
    assert inp.revenue_cagr == 16.0 and inp.debt_to_equity == 0.4
    assert inp.beta == 0.9
    res = generate_thesis(inp)
    assert res.verdict in VERDICTS
    assert res.bull_factors  # should produce bull factors from these strong inputs


def test_empty_inputs_degrade_to_neutral():
    res = generate_thesis(ThesisInputs(ticker="EMPTY"))
    assert res.verdict == "Neutral"
    assert res.bull_factors == [] and res.bear_factors == [] and res.key_risks == []
    assert res.inputs_present == []
