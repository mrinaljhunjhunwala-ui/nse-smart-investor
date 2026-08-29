"""tests/test_final_verdict.py — regression cover for the seven-scores aggregator.

These tests pin the decision-tree guarantees that separate this from a
plain weighted average. Specifically:

  * A red qualitative flag VETOES a BUY, no matter how good the technical is
    (the "fraud with great momentum" failure mode we don't want).
  * A Strong-Negative thesis verdict also vetoes.
  * DEMANDING valuation DOWNGRADES rather than vetoing (real winners are
    allowed to be expensive).
  * Weak TQS damps but doesn't veto (oversold-bounce is a valid trade).
  * Confidence tracks how many gates yielded a firm read.
  * Everything missing (all Nones) returns a defensible HOLD, not a crash.
"""
from __future__ import annotations

import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from analysis.final_verdict import (  # noqa: E402
    CONFIDENCE, VERDICTS,
    combine,
)


# ─────────────── Structural guarantees ───────────────

def test_verdicts_are_exactly_the_labels_the_ui_expects():
    assert VERDICTS == ["AVOID", "HOLD", "WATCH", "BUY", "STRONG BUY"]


def test_all_none_returns_defensible_hold_not_crash():
    v = combine()
    assert v.verdict in VERDICTS
    assert v.confidence == "low"
    # A verdict on zero information must NOT be BUY / STRONG BUY
    assert v.verdict not in ("BUY", "STRONG BUY")


# ─────────────── Quality veto (the fraud-with-momentum guard) ───────────────

def test_red_flag_vetoes_a_strong_buy_technical():
    v = combine(
        composite_score=85, composite_action="STRONG BUY",
        tqs=80,
        quality_flags={"severity": "red", "top_flag": "Promoter pledge > 50 %"},
    )
    assert v.verdict == "AVOID"
    assert v.limiting_gate == "quality"
    assert "pledge" in v.primary_reason.lower() or "red" in v.primary_reason.lower()


def test_amber_flag_damps_but_does_not_veto():
    v_amber = combine(
        composite_score=80, composite_action="BUY",
        tqs=70,
        quality_flags={"severity": "amber", "top_flag": "Recent SEBI notice"},
    )
    v_clean = combine(
        composite_score=80, composite_action="BUY",
        tqs=70,
    )
    assert v_amber.verdict != "AVOID"
    # Damping should reduce conviction relative to a clean-flag identical case
    assert v_amber.conviction < v_clean.conviction


def test_low_quality_score_vetoes_below_floor():
    v = combine(
        composite_score=85, composite_action="STRONG BUY",
        quality_score=15.0,   # below the 30 floor
    )
    assert v.verdict == "AVOID"
    assert v.limiting_gate == "quality"


# ─────────────── Thesis veto ───────────────

def test_strong_negative_thesis_vetoes_a_buy():
    v = combine(
        composite_score=80, composite_action="BUY",
        thesis_verdict="Strong Negative", thesis_score=-2,
    )
    assert v.verdict == "AVOID"
    assert v.limiting_gate == "thesis"


def test_negative_thesis_damps_without_vetoing():
    v_neg = combine(
        composite_score=80, composite_action="BUY",
        thesis_verdict="Negative", thesis_score=-1,
    )
    v_pos = combine(
        composite_score=80, composite_action="BUY",
        thesis_verdict="Positive", thesis_score=1,
    )
    assert v_neg.verdict != "AVOID"
    assert v_neg.conviction < v_pos.conviction


# ─────────────── Valuation damper (NOT veto) ───────────────

def test_demanding_valuation_damps_but_does_not_veto():
    v_dem = combine(
        composite_score=85, composite_action="STRONG BUY",
        valuation_posture="DEMANDING_VS_GROWTH",
    )
    v_ok = combine(
        composite_score=85, composite_action="STRONG BUY",
        valuation_posture="REASONABLE",
    )
    # A DEMANDING valuation on a real trending winner is a valid trade —
    # position-sizing discipline, not a veto.
    assert v_dem.verdict != "AVOID"
    assert v_dem.conviction < v_ok.conviction


def test_supported_valuation_amplifies():
    v_sup = combine(
        composite_score=70, composite_action="BUY",
        valuation_posture="SUPPORTED_BY_GROWTH_AND_QUALITY",
    )
    v_ok = combine(
        composite_score=70, composite_action="BUY",
        valuation_posture="REASONABLE",
    )
    assert v_sup.conviction > v_ok.conviction


# ─────────────── Technical veto (the "don't enter here" gate) ───────────────

def test_technical_exit_vetoes_regardless_of_fundamentals():
    """A technical EXIT signal must veto — you're not entering a name the
    trading model says to leave, no matter how good the story."""
    v = combine(
        composite_score=15, composite_action="EXIT",
        quality_score=95,
        valuation_posture="SUPPORTED_BY_GROWTH_AND_QUALITY",
        thesis_verdict="Strong Positive", thesis_score=2,
    )
    assert v.verdict == "AVOID"


# ─────────────── Trend quality damper ───────────────

def test_weak_tqs_damps_but_does_not_veto_oversold_bounces():
    """A trend-quality reading is a damper only; sub-30 TQS trades happen
    on oversold-bounce entries and can be valid."""
    v_weak = combine(composite_score=70, composite_action="BUY", tqs=15)
    v_ok   = combine(composite_score=70, composite_action="BUY", tqs=45)
    assert v_weak.verdict != "AVOID"
    assert v_weak.conviction < v_ok.conviction


def test_strong_trend_amplifies_conviction():
    v_str = combine(composite_score=70, composite_action="BUY", tqs=80)
    v_ok  = combine(composite_score=70, composite_action="BUY", tqs=45)
    assert v_str.conviction > v_ok.conviction


# ─────────────── Confidence tracking ───────────────

def test_high_confidence_needs_at_least_4_firm_gates():
    v_full = combine(
        composite_score=70, composite_action="BUY",
        tqs=60,
        quality_score=70,
        valuation_posture="REASONABLE",
        thesis_verdict="Positive", thesis_score=1,
    )
    assert v_full.confidence == "high"

    v_thin = combine(composite_score=70, composite_action="BUY")
    assert v_thin.confidence == "low"


def test_medium_confidence_at_three_firm_gates():
    v = combine(
        composite_score=70, composite_action="BUY",
        tqs=60,
        valuation_posture="REASONABLE",
    )
    assert v.confidence == "medium"


# ─────────────── Subsystem drilldown preservation ───────────────

def test_subsystem_labels_preserve_every_input_for_ui_drilldown():
    v = combine(
        composite_score=70, composite_action="BUY",
        tqs=55, quality_score=68,
        valuation_posture="REASONABLE",
        thesis_verdict="Positive", thesis_score=1,
        quality_flags={"severity": "amber"},
    )
    assert v.subsystem_labels["composite"] == "BUY"
    assert "tqs"       in v.subsystem_labels
    assert "quality"   in v.subsystem_labels
    assert "valuation" in v.subsystem_labels
    assert "thesis"    in v.subsystem_labels
    assert "flags"     in v.subsystem_labels


def test_as_dict_shape_is_stable_for_ui_consumption():
    v = combine(composite_score=70, composite_action="BUY", tqs=55)
    d = v.as_dict()
    for k in ("verdict", "confidence", "conviction",
              "primary_reason", "limiting_gate", "gates", "subsystem_labels"):
        assert k in d, f"missing key {k}"
    assert isinstance(d["gates"], list)
    for g in d["gates"]:
        for k in ("name", "passed", "message", "effect"):
            assert k in g


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
