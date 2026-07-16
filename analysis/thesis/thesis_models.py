"""analysis/thesis/thesis_models.py — data contracts for the structured thesis engine.

Phase A1. NO AI, NO narrative generation. These dataclasses are the typed boundary
between the platform's existing signals (composite score, deep-confirmation,
fundamentals analytics, beta, sector) and the deterministic rules in `thesis_rules.py`.

Design rules:
  * `ThesisInputs` is a flat, normalized bundle — every field Optional so the engine
    degrades gracefully when a subsystem is unavailable (a rule that needs a missing
    field simply does not fire).
  * Every `Factor` is fully traceable: text + source subsystem + supporting evidence.
  * `ThesisResult.verdict` is one of exactly five labels.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional

# The five permitted verdicts (ordered most-negative → most-positive by score).
VERDICTS = ["Strong Negative", "Negative", "Neutral", "Positive", "Strong Positive"]
VERDICT_BY_SCORE = {-2: "Strong Negative", -1: "Negative", 0: "Neutral",
                    1: "Positive", 2: "Strong Positive"}

# Polarity tags for a Factor.
BULL = "bull"
BEAR = "bear"
RISK = "risk"

# Source subsystem labels (the provenance of a factor).
SRC_FUNDAMENTALS = "Fundamentals"
SRC_TECHNICAL = "Technical"
SRC_MOMENTUM = "Momentum"
SRC_DEEP = "DeepConfirmation"
SRC_BETA = "Beta"
SRC_SENTIMENT = "Sentiment"
SRC_COMPOSITE = "Composite"
SRC_LIQUIDITY = "Liquidity"


@dataclass
class Factor:
    """One traceable reasoning point.

    text     — the human-readable claim, e.g. "Revenue compounding strongly".
    source   — which subsystem produced it (one of the SRC_* labels).
    evidence — the supporting metric, e.g. "Revenue CAGR = 18.4%".
    polarity — BULL | BEAR | RISK.
    """
    text: str
    source: str
    evidence: str
    polarity: str

    def to_dict(self) -> dict:
        return {"text": self.text, "source": self.source,
                "evidence": self.evidence, "polarity": self.polarity}


@dataclass
class ThesisInputs:
    """Normalized snapshot of existing signals consumed by the rules. All Optional."""
    ticker: str

    # ── Composite score + component scores (analysis.score.CompositeScore) ──
    composite_score: Optional[float] = None      # 0–100
    action: Optional[str] = None
    grade: Optional[str] = None
    technical_score: Optional[float] = None       # /40
    momentum_score: Optional[float] = None        # /25
    volume_score: Optional[float] = None          # /15
    sentiment_score: Optional[float] = None       # /10
    risk_reward: Optional[float] = None

    # ── Deep-confirmation signals (dashboard.shared.cache._deep_confirmation) ──
    weekly_trend: Optional[str] = None            # "uptrend" | "downtrend" | "sideways"
    rel_strength: Optional[str] = None            # "outperforming" | "underperforming"
    rs_pct: Optional[float] = None                # % vs Nifty
    earnings_days: Optional[int] = None           # days to next earnings (None if unknown)
    signal_bull: Optional[int] = None             # bullish checks passed
    signal_total: Optional[int] = None            # total checks

    # ── Fundamentals analytics (analysis.fundamentals.analytics) ──
    revenue_cagr: Optional[float] = None          # %
    eps_cagr: Optional[float] = None              # %
    roe: Optional[float] = None                   # %
    debt_to_equity: Optional[float] = None        # x
    roce: Optional[float] = None                  # % (Phase D1)
    fcf: Optional[float] = None                   # ₹ cr (Phase D1)
    fundamentals_partial: bool = False

    # ── Sector awareness (Phase D1) ──
    sector_profile: Optional[object] = None       # analysis.sector_classification.SectorProfile

    # ── Market risk ──
    beta: Optional[float] = None

    # ── Context ──
    sector: Optional[str] = None
    news_sentiment: Optional[str] = None          # "positive" | "negative" | "neutral"

    # ── Liquidity (Phase C1 — from existing OHLCV) ──
    liquidity_tier: Optional[str] = None          # "High" | "Medium" | "Low" | "Illiquid"
    avg_daily_turnover: Optional[float] = None    # ₹ (30d)


@dataclass
class ThesisResult:
    """The structured output: lists + a single verdict, all traceable."""
    ticker: str
    verdict: str                                  # one of VERDICTS
    verdict_score: int                            # -2 … +2
    verdict_rationale: str
    bull_factors: List[Factor] = field(default_factory=list)
    bear_factors: List[Factor] = field(default_factory=list)
    key_risks: List[Factor] = field(default_factory=list)
    inputs_present: List[str] = field(default_factory=list)   # subsystems that contributed
    notes: List[str] = field(default_factory=list)            # explanatory context (Phase D1)
    generated_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict:
        return {
            "ticker": self.ticker,
            "verdict": self.verdict,
            "verdict_score": self.verdict_score,
            "verdict_rationale": self.verdict_rationale,
            "bull_factors": [f.to_dict() for f in self.bull_factors],
            "bear_factors": [f.to_dict() for f in self.bear_factors],
            "key_risks": [f.to_dict() for f in self.key_risks],
            "inputs_present": list(self.inputs_present),
            "notes": list(self.notes),
            "generated_at": self.generated_at.isoformat(),
        }
