"""tests/test_overlay_score.py - Task 3.3 sidecar overlay unit tests.

Covers analysis.score.compute_overlay_score in isolation (pure, no I/O):
  * both inputs required (None on either -> None)
  * unrecognised posture -> None
  * non-finite TQS -> None
  * expected values across the posture bands
  * clipping at 0 and 100
  * CompositeScore field defaults to None when caller does not pass overlay
    inputs (Guardrail 5 acceptance: nothing changes for existing consumers)
"""
from __future__ import annotations

import math
import pytest

from analysis.score import compute_overlay_score, CompositeScore


# ── Absent inputs -> None ────────────────────────────────────────────────────

def test_none_tqs_returns_none():
    assert compute_overlay_score(None, "SUPPORTED_BY_QUALITY") is None


def test_none_posture_returns_none():
    assert compute_overlay_score(70.0, None) is None


def test_both_none_returns_none():
    assert compute_overlay_score(None, None) is None


def test_unrecognised_posture_returns_none():
    # Guards against silently mapping garbage posture strings to 1.0
    assert compute_overlay_score(70.0, "MYSTERY_POSTURE") is None


def test_non_finite_tqs_returns_none():
    assert compute_overlay_score(float("nan"), "REASONABLE") is None
    assert compute_overlay_score(float("inf"), "REASONABLE") is None


def test_non_numeric_tqs_returns_none():
    assert compute_overlay_score("high", "REASONABLE") is None


# ── Expected values across posture bands ─────────────────────────────────────
# TQS=90 normalises to 100, so posture modifier lands directly:
#   supported_growth_and_quality: 100 * 1.15 -> 115 -> clipped to 100
#   supported_*:                  100 * 1.10 -> 110 -> clipped to 100
#   reasonable:                   100 * 1.00 -> 100
#   demanding_*:                  100 * 0.75 ->  75
#   insufficient_evidence:        100 * 0.85 ->  85

def test_max_tqs_supported_both_clips_to_100():
    assert compute_overlay_score(90.0, "SUPPORTED_BY_GROWTH_AND_QUALITY") == 100


def test_max_tqs_reasonable_is_100():
    assert compute_overlay_score(90.0, "REASONABLE") == 100


def test_max_tqs_demanding_is_75():
    assert compute_overlay_score(90.0, "DEMANDING_VS_GROWTH") == 75
    assert compute_overlay_score(90.0, "DEMANDING_VS_RETURNS") == 75
    assert compute_overlay_score(90.0, "DEMANDING_VS_ROE") == 75


def test_max_tqs_insufficient_is_85():
    assert compute_overlay_score(90.0, "INSUFFICIENT_EVIDENCE") == 85


def test_supported_variants_all_get_same_modifier():
    for posture in ("SUPPORTED_BY_GROWTH", "SUPPORTED_BY_QUALITY", "SUPPORTED_BY_ROE"):
        assert compute_overlay_score(45.0, posture) == 55  # 45/90*100 = 50; *1.10 = 55


def test_zero_tqs_reasonable_is_zero():
    assert compute_overlay_score(0.0, "REASONABLE") == 0


def test_zero_tqs_demanding_is_zero():
    assert compute_overlay_score(0.0, "DEMANDING_VS_GROWTH") == 0


def test_zero_tqs_supported_is_zero():
    # 0 * 1.15 rounds to 0 (not below zero)
    assert compute_overlay_score(0.0, "SUPPORTED_BY_GROWTH_AND_QUALITY") == 0


# ── Clipping at the extremes ─────────────────────────────────────────────────

def test_negative_tqs_clips_to_zero_baseline():
    # A pathological negative TQS still yields a well-formed 0..100 int
    assert compute_overlay_score(-5.0, "REASONABLE") == 0


def test_overly_large_tqs_clips_to_100_baseline():
    # TQS above its 90-pt max clips before the modifier applies
    assert compute_overlay_score(120.0, "REASONABLE") == 100
    assert compute_overlay_score(120.0, "DEMANDING_VS_GROWTH") == 75


# ── Interior values sanity check ─────────────────────────────────────────────

def test_mid_tqs_reasonable_matches_direct_normalisation():
    # TQS=54 -> norm 60 -> reasonable *1.00 -> 60
    assert compute_overlay_score(54.0, "REASONABLE") == 60


def test_mid_tqs_supported_boosts_by_10pct():
    # TQS=54 -> norm 60 -> supported *1.10 -> 66
    assert compute_overlay_score(54.0, "SUPPORTED_BY_QUALITY") == 66


def test_mid_tqs_demanding_penalises_by_25pct():
    # TQS=54 -> norm 60 -> demanding *0.75 -> 45
    assert compute_overlay_score(54.0, "DEMANDING_VS_ROE") == 45


# ── CompositeScore field default (backwards compat) ──────────────────────────

def test_composite_score_overlay_defaults_to_none():
    cs = CompositeScore(
        ticker="TEST", price=100.0, score=50.0, grade="B", action="HOLD",
        technical_score=20.0, momentum_score=15.0, volume_score=10.0,
        sentiment_score=5.0, entry=100.0, stop_loss=95.0, target=110.0,
        risk_reward=2.0, headline="test", narrative="test",
        sector="Other", vix_regime="normal", sector_rank=7,
    )
    assert cs.overlay_score is None
    assert cs.as_dict()["overlay_score"] is None


def test_composite_score_overlay_serialises_when_set():
    cs = CompositeScore(
        ticker="TEST", price=100.0, score=50.0, grade="B", action="HOLD",
        technical_score=20.0, momentum_score=15.0, volume_score=10.0,
        sentiment_score=5.0, entry=100.0, stop_loss=95.0, target=110.0,
        risk_reward=2.0, headline="test", narrative="test",
        sector="Other", vix_regime="normal", sector_rank=7,
        overlay_score=73,
    )
    assert cs.overlay_score == 73
    assert cs.as_dict()["overlay_score"] == 73
