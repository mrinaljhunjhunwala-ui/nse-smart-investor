"""
tests/test_sh2_evidence_gating.py — SH2 score-honesty regressions.

Locks the display contract for evidence-gated candlestick patterns and the
regime-aware oversold caveat. Pure imports only — no Streamlit runtime.
"""
from __future__ import annotations

import pytest

from dashboard.shared.disclosures import (
    evidence_gated_pattern_label,
    oversold_reliability_suffix,
)
from dashboard.shared.picks_ui import pick_pointers


# ── evidence_gated_pattern_label ────────────────────────────────────────────

def test_pattern_label_returns_none_on_empty():
    assert evidence_gated_pattern_label(None, 1.0) is None
    assert evidence_gated_pattern_label([], 1.0) is None
    assert evidence_gated_pattern_label(["", None], 1.0) is None


def test_pattern_label_never_says_signal_in_headline():
    """SH2 core: the headline must not read as a trading signal."""
    head, _ = evidence_gated_pattern_label(["BullEngulfing"], 1.8)
    assert "signal" not in head.lower()
    assert "informational" in head.lower()


def test_pattern_label_volume_confirms_when_ratio_high():
    _, caveat = evidence_gated_pattern_label(["Hammer"], 2.0)
    assert "volume" in caveat.lower()
    assert "confirm" in caveat.lower() or "support" in caveat.lower()


def test_pattern_label_flags_unconfirmed_when_volume_low():
    _, caveat = evidence_gated_pattern_label(["Hammer"], 0.9)
    assert "unconfirmed" in caveat.lower()
    assert "not a trading signal" in caveat.lower()


def test_pattern_label_handles_missing_volume():
    _, caveat = evidence_gated_pattern_label(["Doji"], None)
    assert "unavailable" in caveat.lower()
    assert "not a trading signal" in caveat.lower()


def test_pattern_label_joins_multiple_patterns():
    head, _ = evidence_gated_pattern_label(["Hammer", "BullEngulfing"], 1.5)
    assert "Hammer" in head and "BullEngulfing" in head


# ── oversold_reliability_suffix ─────────────────────────────────────────────

@pytest.mark.parametrize("regime", ["elevated", "fear", "panic",
                                    "FEAR", "Panic ", " Elevated"])
def test_oversold_suffix_present_in_fear_regimes(regime):
    suf = oversold_reliability_suffix(regime)
    assert suf
    assert "reliability" in suf.lower()


@pytest.mark.parametrize("regime", [None, "", "normal", "complacency",
                                    "unknown", "calm"])
def test_oversold_suffix_empty_outside_fear_regimes(regime):
    """Complacent / normal / unknown regimes get no caveat — no noise where
    the study shows the ranking works or is inconclusive."""
    assert oversold_reliability_suffix(regime) == ""


# ── picks_ui: dead candlestick bullet is gone ───────────────────────────────

def test_pick_pointers_never_mentions_candlestick_confirmation():
    """SH2: the "Bullish candlestick confirmation" bullet was dead code (the
    pattern field is always 0 post-PATTERN_REMOVAL_MIGRATION) and its wording
    read as a signal. It must not fire under any pattern value."""
    for pattern_val in (0, 5, 10, 999, None):
        pick = {"technical": 32, "momentum": 22, "volume": 12,
                "pattern": pattern_val, "entry": 100, "sl": 95,
                "tp": 110, "rr": 2.0}
        bullets = pick_pointers(pick)
        blob = " ".join(text for _, text in bullets).lower()
        assert "candlestick" not in blob
        assert "confirmation signal" not in blob
