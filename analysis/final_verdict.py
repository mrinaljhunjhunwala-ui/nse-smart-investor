"""
analysis/final_verdict.py — the ONE answer.

Problem this solves
───────────────────
The app currently produces up to seven partial verdicts for a single ticker:

  1. Composite score       (analysis/score.py)              — trade now?
  2. TQS                   (analysis/trend_quality_score)   — trend healthy?
  3. Qualitative flags     (analysis/qualitative_flags)     — governance?
  4. Thesis verdict        (analysis/thesis/thesis_engine)  — story holds?
  5. Valuation posture     (analysis/fundamentals/          — overpaying?
                             valuation_decision)
  6. Fundamental quality   (research/fundamental_quality)   — good business?
  7. Portfolio fit         (analysis/thesis/portfolio_fit)  — fits book?

Each answers a different question, and users have been asked to synthesise
seven partial answers themselves. That was the "seven-scores problem"
flagged in the assessment. This module produces ONE coherent verdict that
composes them, without hiding what each subsystem said.

Design principle
────────────────
Not a weighted sum. A DECISION TREE. Quality and governance are GATES
(they can veto a BUY no matter how good the technical setup looks).
Valuation is a DAMPER (a "STRONG BUY" on an overpriced name gets
downgraded, not vetoed). Technical setup is what turns a "watch-worthy"
name into an "act today" call — it's the LAST filter, not the first.

This is the Buffett/Munger circle-of-competence structure: rule out on
quality first, price second, timing third. Any single-number aggregator
that ignores this ordering will happily flash STRONG BUY on a fraud with
great momentum, which is the exact failure mode we want to prevent.

Inputs are all OPTIONAL. Callers pass whatever they've computed; missing
inputs are treated as unknown, not as bad. The verdict records confidence
based on how many gates were actually evaluable — a verdict with 5/5 gates
firm is HIGH confidence; with only 2/5 available is LOW.

Nothing here fetches data. Callers (dashboard pages / research scripts)
are the appropriate place to decide what to compute.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

_log = logging.getLogger("analysis.final_verdict")


# ─────────────────────────────────────────────────────────────────────────────
# Verdict vocabulary
# ─────────────────────────────────────────────────────────────────────────────

# One label a user actually acts on. Ordered by strength.
VERDICTS = ["AVOID", "HOLD", "WATCH", "BUY", "STRONG BUY"]

CONFIDENCE = ("low", "medium", "high")


@dataclass
class GateEvaluation:
    """One gate's outcome. name is 'quality' | 'valuation' | ..."""
    name:    str
    passed:  Optional[bool]           # None = insufficient data
    message: str                      # one-line human-readable
    effect:  str                      # "veto" | "damp" | "amplify" | "none"


@dataclass
class FinalVerdict:
    """The single answer. Everything else is drilldown."""
    verdict:          str                                   # one of VERDICTS
    confidence:       str                                   # low | medium | high
    conviction:       int                                   # 0-100 aggregated conviction score
    primary_reason:   str                                   # single sentence
    gates:            List[GateEvaluation] = field(default_factory=list)
    limiting_gate:    Optional[str] = None                  # gate that most reduced conviction
    subsystem_labels: Dict[str, str] = field(default_factory=dict)  # {"composite": "BUY", ...}

    def as_dict(self) -> Dict:
        return {
            "verdict":          self.verdict,
            "confidence":       self.confidence,
            "conviction":       self.conviction,
            "primary_reason":   self.primary_reason,
            "limiting_gate":    self.limiting_gate,
            "gates": [
                {"name": g.name, "passed": g.passed,
                 "message": g.message, "effect": g.effect}
                for g in self.gates
            ],
            "subsystem_labels": self.subsystem_labels,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Individual gate evaluators
# ─────────────────────────────────────────────────────────────────────────────

def _gate_quality(quality_score: Optional[float],
                  quality_flags: Optional[Dict]) -> GateEvaluation:
    """
    Governance + fundamental-quality gate.

    A RED qualitative flag (pledge breach, regulatory action, audit qualification)
    is a HARD VETO — no BUY signal survives one. An AMBER flag caps conviction
    but doesn't veto. Fundamental-quality score < 30 is a soft veto.
    """
    if quality_flags and quality_flags.get("severity") == "red":
        top = quality_flags.get("top_flag", "governance red flag")
        return GateEvaluation(
            name="quality", passed=False, effect="veto",
            message=f"Red governance flag: {top}. BUY suppressed.")

    if quality_score is not None and quality_score < 30:
        return GateEvaluation(
            name="quality", passed=False, effect="veto",
            message=f"Fundamental quality score {quality_score:.0f}/100 below "
                    f"the 30-point floor. BUY suppressed.")

    if quality_flags and quality_flags.get("severity") == "amber":
        top = quality_flags.get("top_flag", "flag")
        return GateEvaluation(
            name="quality", passed=True, effect="damp",
            message=f"Amber flag ({top}) — proceed with reduced size.")

    if quality_score is None and not quality_flags:
        return GateEvaluation(
            name="quality", passed=None, effect="none",
            message="Quality data unavailable.")

    return GateEvaluation(
        name="quality", passed=True, effect="none",
        message=f"Quality passes"
                + (f" (score {quality_score:.0f}/100)" if quality_score else ""))


def _gate_valuation(posture: Optional[str]) -> GateEvaluation:
    """
    Valuation posture gate — DAMPER not veto.

    "DEMANDING_*" postures reduce conviction; they never suppress a signal
    outright, because a demanding valuation on a real trending winner can
    still be a valid trade (the DAMP is your position-sizing discipline).
    """
    if not posture:
        return GateEvaluation(
            name="valuation", passed=None, effect="none",
            message="Valuation data unavailable.")

    if posture == "INSUFFICIENT_EVIDENCE":
        return GateEvaluation(
            name="valuation", passed=None, effect="none",
            message="Insufficient evidence for valuation posture.")

    if posture.startswith("DEMANDING"):
        return GateEvaluation(
            name="valuation", passed=True, effect="damp",
            message=f"Valuation posture: {posture.replace('_', ' ').lower()}. "
                    f"Consider halving size or waiting for a pullback.")

    if posture.startswith("SUPPORTED"):
        return GateEvaluation(
            name="valuation", passed=True, effect="amplify",
            message=f"Valuation posture: {posture.replace('_', ' ').lower()}.")

    # REASONABLE and everything else
    return GateEvaluation(
        name="valuation", passed=True, effect="none",
        message=f"Valuation posture: {posture.replace('_', ' ').lower()}.")


def _gate_thesis(verdict: Optional[str],
                 verdict_score: Optional[int]) -> GateEvaluation:
    """
    Thesis-engine gate.

    "Strong Negative" (score -2) is a veto — the story explicitly does not
    hold. "Negative" (-1) is a damper. "Positive" and "Strong Positive"
    are amplifiers. Neutral is a no-op.
    """
    if not verdict:
        return GateEvaluation(
            name="thesis", passed=None, effect="none",
            message="Thesis engine not run.")

    if verdict_score is not None and verdict_score <= -2:
        return GateEvaluation(
            name="thesis", passed=False, effect="veto",
            message=f"Thesis: {verdict}. BUY suppressed.")

    if verdict_score is not None and verdict_score == -1:
        return GateEvaluation(
            name="thesis", passed=True, effect="damp",
            message=f"Thesis: {verdict}. Reduce size.")

    if verdict_score is not None and verdict_score >= 1:
        return GateEvaluation(
            name="thesis", passed=True, effect="amplify",
            message=f"Thesis: {verdict}.")

    return GateEvaluation(
        name="thesis", passed=True, effect="none",
        message=f"Thesis: {verdict or 'Neutral'}.")


def _gate_trend_quality(tqs: Optional[float]) -> GateEvaluation:
    """
    Trend-quality (TQS) gate.

    TQS < 25 damps — the trend is weak enough that any BUY here is
    counter-trend by construction. Not a veto because oversold-bounce trades
    are legitimate; but conviction should reflect the trend backdrop.
    TQS > 60 amplifies (strong, persistent trend).
    """
    if tqs is None:
        return GateEvaluation(
            name="trend", passed=None, effect="none",
            message="TQS unavailable.")

    if tqs < 25:
        return GateEvaluation(
            name="trend", passed=True, effect="damp",
            message=f"TQS {tqs:.0f}/90 — trend weak. Counter-trend entry.")

    if tqs > 60:
        return GateEvaluation(
            name="trend", passed=True, effect="amplify",
            message=f"TQS {tqs:.0f}/90 — trend strong and persistent.")

    return GateEvaluation(
        name="trend", passed=True, effect="none",
        message=f"TQS {tqs:.0f}/90 — trend health neutral.")


def _gate_technical(composite_score: Optional[float],
                    composite_action: Optional[str]) -> GateEvaluation:
    """
    Technical-setup gate — the "act now?" question.

    The composite score's action label maps here without translation. This
    is the DRIVER of the final verdict; every other gate modifies its
    conviction. When no composite is available the entire final-verdict
    exercise defaults to HOLD (we can't decide without SOMETHING numeric
    to anchor).
    """
    if composite_score is None:
        return GateEvaluation(
            name="technical", passed=None, effect="none",
            message="No composite technical read available.")

    act = (composite_action or "").upper()
    if act in ("STRONG BUY", "BUY"):
        return GateEvaluation(
            name="technical", passed=True, effect="amplify",
            message=f"Technical setup: {act.title()} (composite score "
                    f"{composite_score:.0f}/90).")

    if act in ("EXIT", "CAUTION"):
        return GateEvaluation(
            name="technical", passed=False, effect="veto",
            message=f"Technical setup: {act.title()} (composite score "
                    f"{composite_score:.0f}/90). Do not enter here.")

    return GateEvaluation(
        name="technical", passed=True, effect="none",
        message=f"Technical setup: {act.title() if act else 'neutral'} "
                f"(composite score {composite_score:.0f}/90).")


# ─────────────────────────────────────────────────────────────────────────────
# The aggregator
# ─────────────────────────────────────────────────────────────────────────────

def _apply_effects(base_conviction: int,
                   gates: List[GateEvaluation]) -> Tuple[int, Optional[str]]:
    """
    Turn gate effects into a conviction score adjustment.

    Numeric interpretation:
      * veto      → cap to 0        (returned as the limiting gate)
      * damp      → −20 each
      * amplify   → +10 each
      * none      → no change

    Bounded 0..100. `limiting_gate` is the gate that most reduced conviction.
    """
    convict = base_conviction
    veto_gate: Optional[str] = None
    biggest_damp = 0
    biggest_damp_gate: Optional[str] = None

    for g in gates:
        if g.effect == "veto" and g.passed is False:
            veto_gate = g.name
            convict = 0
        elif g.effect == "damp":
            convict -= 20
            if 20 > biggest_damp:
                biggest_damp = 20
                biggest_damp_gate = g.name
        elif g.effect == "amplify":
            convict += 10

    limiting = veto_gate or biggest_damp_gate
    return max(0, min(100, convict)), limiting


def _label_from_conviction(conviction: int,
                           tech_gate: GateEvaluation) -> str:
    """Map final conviction number back to a verdict label."""
    if tech_gate.effect == "veto":
        return "AVOID"
    if conviction >= 85:  return "STRONG BUY"
    if conviction >= 65:  return "BUY"
    if conviction >= 45:  return "WATCH"
    if conviction >= 25:  return "HOLD"
    return "AVOID"


def _confidence_from_gate_coverage(gates: List[GateEvaluation]) -> str:
    """
    High = at least 4/5 gates yielded a firm passed/failed. Medium = 3/5.
    Low = fewer. Callers can't act with the same confidence on a partial
    read as on a full one.
    """
    firm = sum(1 for g in gates if g.passed is not None)
    if firm >= 4: return "high"
    if firm == 3: return "medium"
    return "low"


def combine(*,
            composite_score:   Optional[float] = None,
            composite_action:  Optional[str]   = None,
            tqs:               Optional[float] = None,
            quality_score:     Optional[float] = None,
            quality_flags:     Optional[Dict]  = None,
            valuation_posture: Optional[str]   = None,
            thesis_verdict:    Optional[str]   = None,
            thesis_score:      Optional[int]   = None,
            ) -> FinalVerdict:
    """
    Combine every subsystem's output into ONE verdict.

    Every argument is optional; a caller that only has half the pieces
    still gets a defensible answer, just with lower confidence. The
    subsystem outputs themselves are preserved in `subsystem_labels` for
    the UI to render as drilldown chips.
    """
    tech = _gate_technical(composite_score, composite_action)
    qual = _gate_quality(quality_score, quality_flags)
    valu = _gate_valuation(valuation_posture)
    thes = _gate_thesis(thesis_verdict, thesis_score)
    trnd = _gate_trend_quality(tqs)
    gates = [tech, qual, valu, thes, trnd]

    # Base conviction from the composite score (0-90 scaled to 0-100)
    if composite_score is not None:
        base = int(round(min(100, composite_score * (100 / 90))))
    else:
        base = 50  # neutral prior when even the composite is missing

    conviction, limiting = _apply_effects(base, gates)
    verdict = _label_from_conviction(conviction, tech)
    confidence = _confidence_from_gate_coverage(gates)

    # Primary reason: the strongest signal driving the verdict
    if tech.effect == "veto":
        primary = tech.message
    elif limiting:
        limiting_g = next((g for g in gates if g.name == limiting), None)
        if limiting_g:
            primary = limiting_g.message
        else:
            primary = tech.message
    else:
        primary = tech.message

    labels: Dict[str, str] = {}
    if composite_action:      labels["composite"] = composite_action
    if tqs is not None:       labels["tqs"] = f"{tqs:.0f}/90"
    if valuation_posture:     labels["valuation"] = valuation_posture
    if thesis_verdict:        labels["thesis"] = thesis_verdict
    if quality_score is not None:
        labels["quality"] = f"{quality_score:.0f}/100"
    if quality_flags and quality_flags.get("severity"):
        labels["flags"] = str(quality_flags.get("severity"))

    return FinalVerdict(
        verdict=verdict, confidence=confidence,
        conviction=conviction, primary_reason=primary,
        gates=gates, limiting_gate=limiting,
        subsystem_labels=labels,
    )
