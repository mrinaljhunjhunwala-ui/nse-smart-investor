"""analysis/thesis — Structured Thesis Engine (Phase A1).

Transforms existing platform signals (composite score, deep-confirmation, fundamentals
analytics, beta, sector) into structured, fully-traceable investment reasoning:
Bull factors, Bear factors, Key risks, and a single Verdict.

NO AI. NO LLM. NO narrative generation — explainable rules only.
"""
from .thesis_models import (
    Factor, ThesisInputs, ThesisResult, VERDICTS,
    BULL, BEAR, RISK,
)
from .thesis_engine import generate_thesis, build_inputs, thesis_for_ticker
from . import thesis_rules
from .portfolio_fit import (
    FitFactor, PortfolioFitInputs, PortfolioFitResult, FIT_RATINGS,
    POSITIVE, NEGATIVE, assess_fit, build_fit_inputs, fit_for_candidate,
)

__all__ = [
    "Factor", "ThesisInputs", "ThesisResult", "VERDICTS",
    "BULL", "BEAR", "RISK",
    "generate_thesis", "build_inputs", "thesis_for_ticker",
    "thesis_rules",
    # Phase B — Portfolio Fit
    "FitFactor", "PortfolioFitInputs", "PortfolioFitResult", "FIT_RATINGS",
    "POSITIVE", "NEGATIVE", "assess_fit", "build_fit_inputs", "fit_for_candidate",
]
