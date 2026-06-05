"""analysis/thesis/thesis_rules.py — deterministic reasoning rules.

Phase A1. NO AI. Pure functions over a `ThesisInputs` snapshot. Each rule either fires
(appending one fully-traceable `Factor`: text + source + evidence) or does not. Given the
same inputs the output is byte-identical — which is what makes the engine testable and
auditable.

Thresholds are intentionally explicit and documented inline so the reasoning is legible.
"""
from __future__ import annotations

from typing import List, Tuple

from .thesis_models import (
    Factor, ThesisInputs,
    BULL, BEAR, RISK,
    SRC_FUNDAMENTALS, SRC_TECHNICAL, SRC_MOMENTUM, SRC_DEEP, SRC_BETA,
    SRC_SENTIMENT, SRC_COMPOSITE, VERDICT_BY_SCORE,
)

# ── Thresholds (single source of truth) ─────────────────────────────────────────
ROE_STRONG = 15.0          # %  — high return on equity
ROE_WEAK = 8.0             # %  — weak return on equity
CAGR_STRONG = 15.0         # %  — strong compounding
CAGR_STEADY = 8.0          # %  — steady growth
DE_LOW = 0.5               # x  — conservative balance sheet (bull)
DE_ELEVATED = 1.0          # x  — elevated leverage (risk)
DE_HIGH = 1.5              # x  — high leverage (stronger risk)

TECH_STRONG = 30.0         # /40
TECH_WEAK = 15.0           # /40
MOM_STRONG = 18.0          # /25
MOM_WEAK = 8.0             # /25   (bear-grade weakness)
MOM_RISK = 10.0            # /25   (risk-grade weakness)
VOL_STRONG = 10.0          # /15
PAT_BULL = 5.0             # /10
SENT_WEAK = 3.0            # /10   (unfavourable market backdrop)

BETA_HIGH = 1.2            # x  — amplifies market moves
SIGNAL_AGREE = 0.70        # fraction of deep-confirmation checks bullish
EARNINGS_SOON = 7          # days — event/gap risk window
COMPOSITE_STRONG = 70.0    # /100
COMPOSITE_WEAK = 40.0      # /100


def _pct(x: float) -> str:
    return f"{x:.1f}%"


# ──────────────────────────────── BULL FACTORS ──────────────────────────────────
def bull_factors(inp: ThesisInputs) -> List[Factor]:
    out: List[Factor] = []

    # Fundamentals
    if inp.revenue_cagr is not None:
        if inp.revenue_cagr >= CAGR_STRONG:
            out.append(Factor("Revenue is compounding strongly", SRC_FUNDAMENTALS,
                              f"Revenue CAGR = {_pct(inp.revenue_cagr)}", BULL))
        elif inp.revenue_cagr >= CAGR_STEADY:
            out.append(Factor("Revenue is growing steadily", SRC_FUNDAMENTALS,
                              f"Revenue CAGR = {_pct(inp.revenue_cagr)}", BULL))
    if inp.eps_cagr is not None and inp.eps_cagr >= CAGR_STRONG:
        out.append(Factor("Earnings are compounding strongly", SRC_FUNDAMENTALS,
                          f"EPS CAGR = {_pct(inp.eps_cagr)}", BULL))
    if inp.roe is not None and inp.roe >= ROE_STRONG:
        out.append(Factor("High return on equity", SRC_FUNDAMENTALS,
                          f"ROE = {_pct(inp.roe)}", BULL))
    if inp.debt_to_equity is not None and inp.debt_to_equity < DE_LOW:
        out.append(Factor("Conservative balance sheet (low debt)", SRC_FUNDAMENTALS,
                          f"D/E = {inp.debt_to_equity:.2f}x", BULL))

    # Technical / momentum
    if inp.technical_score is not None and inp.technical_score >= TECH_STRONG:
        out.append(Factor("Strong technical trend", SRC_TECHNICAL,
                          f"Technical score {inp.technical_score:.0f}/40", BULL))
    if inp.momentum_score is not None and inp.momentum_score >= MOM_STRONG:
        out.append(Factor("Strong price momentum", SRC_MOMENTUM,
                          f"Momentum score {inp.momentum_score:.0f}/25", BULL))
    if inp.volume_score is not None and inp.volume_score >= VOL_STRONG:
        out.append(Factor("Above-average volume support", SRC_TECHNICAL,
                          f"Volume score {inp.volume_score:.0f}/15", BULL))
    if inp.pattern_score is not None and inp.pattern_score >= PAT_BULL:
        out.append(Factor("Bullish chart pattern present", SRC_TECHNICAL,
                          f"Pattern score {inp.pattern_score:.0f}/10", BULL))

    # Deep confirmation
    if inp.weekly_trend == "uptrend":
        out.append(Factor("Higher-timeframe (weekly) uptrend confirmed", SRC_DEEP,
                          "Weekly trend: uptrend", BULL))
    if inp.rel_strength == "outperforming":
        ev = (f"Relative strength {inp.rs_pct:+.1f}% vs Nifty"
              if inp.rs_pct is not None else "Outperforming Nifty")
        out.append(Factor("Outperforming the Nifty (relative strength)", SRC_DEEP, ev, BULL))
    if inp.signal_total and inp.signal_bull is not None \
            and inp.signal_bull / inp.signal_total >= SIGNAL_AGREE:
        out.append(Factor("Multi-signal confirmation", SRC_DEEP,
                          f"{inp.signal_bull}/{inp.signal_total} checks bullish", BULL))

    # Composite
    if inp.composite_score is not None and inp.composite_score >= COMPOSITE_STRONG:
        out.append(Factor("Composite model score is strongly positive", SRC_COMPOSITE,
                          f"Score {inp.composite_score:.0f}/100", BULL))

    # News
    if inp.news_sentiment == "positive":
        out.append(Factor("Positive recent news flow", SRC_SENTIMENT,
                          "News sentiment: positive", BULL))
    return out


# ──────────────────────────────── BEAR FACTORS ──────────────────────────────────
def bear_factors(inp: ThesisInputs) -> List[Factor]:
    out: List[Factor] = []

    # Fundamentals
    if inp.revenue_cagr is not None and inp.revenue_cagr < 0:
        out.append(Factor("Revenue is declining", SRC_FUNDAMENTALS,
                          f"Revenue CAGR = {_pct(inp.revenue_cagr)}", BEAR))
    if inp.eps_cagr is not None and inp.eps_cagr < 0:
        out.append(Factor("Earnings are shrinking", SRC_FUNDAMENTALS,
                          f"EPS CAGR = {_pct(inp.eps_cagr)}", BEAR))
    if inp.roe is not None and inp.roe < ROE_WEAK:
        out.append(Factor("Weak return on equity", SRC_FUNDAMENTALS,
                          f"ROE = {_pct(inp.roe)}", BEAR))

    # Technical / momentum
    if inp.technical_score is not None and inp.technical_score < TECH_WEAK:
        out.append(Factor("Weak / broken technical trend", SRC_TECHNICAL,
                          f"Technical score {inp.technical_score:.0f}/40", BEAR))
    if inp.momentum_score is not None and inp.momentum_score < MOM_WEAK:
        out.append(Factor("Weak price momentum", SRC_MOMENTUM,
                          f"Momentum score {inp.momentum_score:.0f}/25", BEAR))

    # Deep confirmation
    if inp.weekly_trend == "downtrend":
        out.append(Factor("Higher-timeframe (weekly) downtrend", SRC_DEEP,
                          "Weekly trend: downtrend", BEAR))
    if inp.rel_strength == "underperforming":
        ev = (f"Relative strength {inp.rs_pct:+.1f}% vs Nifty"
              if inp.rs_pct is not None else "Underperforming Nifty")
        out.append(Factor("Underperforming the Nifty (relative weakness)", SRC_DEEP, ev, BEAR))

    # Composite
    if inp.composite_score is not None and inp.composite_score < COMPOSITE_WEAK:
        out.append(Factor("Composite model score is negative", SRC_COMPOSITE,
                          f"Score {inp.composite_score:.0f}/100", BEAR))

    # News
    if inp.news_sentiment == "negative":
        out.append(Factor("Negative recent news flow", SRC_SENTIMENT,
                          "News sentiment: negative", BEAR))
    return out


# ───────────────────────────────── KEY RISKS ────────────────────────────────────
def key_risks(inp: ThesisInputs) -> List[Factor]:
    """Explicit risks from: high beta, high D/E, weak momentum, earnings proximity,
    negative sentiment, technical weakness (+ data-quality caveat)."""
    out: List[Factor] = []

    # High beta
    if inp.beta is not None and inp.beta > BETA_HIGH:
        out.append(Factor("High market sensitivity — amplifies market moves (and losses)",
                          SRC_BETA, f"Beta = {inp.beta:.2f}", RISK))

    # High debt / equity
    if inp.debt_to_equity is not None and inp.debt_to_equity > DE_ELEVATED:
        label = "High leverage" if inp.debt_to_equity > DE_HIGH else "Elevated leverage"
        out.append(Factor(f"{label} — sensitive to rates and earnings shocks",
                          SRC_FUNDAMENTALS, f"D/E = {inp.debt_to_equity:.2f}x", RISK))

    # Weak momentum
    if inp.momentum_score is not None and inp.momentum_score < MOM_RISK:
        out.append(Factor("Weak momentum — limited buying support right now",
                          SRC_MOMENTUM, f"Momentum score {inp.momentum_score:.0f}/25", RISK))

    # Earnings proximity
    if inp.earnings_days is not None and 0 <= inp.earnings_days <= EARNINGS_SOON:
        d = inp.earnings_days
        out.append(Factor(f"Earnings due in {d} day(s) — event/gap risk", SRC_DEEP,
                          f"Earnings in {d}d", RISK))

    # Negative sentiment (news, or an unfavourable volatility/market backdrop)
    if inp.news_sentiment == "negative":
        out.append(Factor("Negative news sentiment", SRC_SENTIMENT,
                          "News sentiment: negative", RISK))
    elif inp.sentiment_score is not None and inp.sentiment_score <= SENT_WEAK:
        out.append(Factor("Unfavourable market / volatility backdrop", SRC_SENTIMENT,
                          f"Sentiment score {inp.sentiment_score:.0f}/10", RISK))

    # Technical weakness
    if inp.technical_score is not None and inp.technical_score < TECH_WEAK:
        out.append(Factor("Technical weakness / trend breakdown", SRC_TECHNICAL,
                          f"Technical score {inp.technical_score:.0f}/40", RISK))

    # Data-quality caveat
    if inp.fundamentals_partial:
        out.append(Factor("Fundamental data is partial — some metrics unavailable",
                          SRC_FUNDAMENTALS, "Provider returned partial statements", RISK))
    return out


# ────────────────────────────────── VERDICT ─────────────────────────────────────
def _score_band(score) -> int:
    """Map the 0–100 composite score to a -2…+2 lean."""
    if score is None:
        return 0
    if score >= 75:
        return 2
    if score >= 62:
        return 1
    if score >= 45:
        return 0
    if score >= 30:
        return -1
    return -2


def compute_verdict(inp: ThesisInputs,
                    bull: List[Factor],
                    bear: List[Factor],
                    risks: List[Factor]) -> Tuple[str, int, str]:
    """Deterministic verdict from the composite-score band, nudged by the bull/bear
    balance and a heavy-risk penalty. Clamped to [-2, +2] → one of five labels.

    Returns (verdict_label, verdict_score, rationale).
    """
    band = _score_band(inp.composite_score)
    nb, nbe, nr = len(bull), len(bear), len(risks)

    nudge = 0
    if nb - nbe >= 3:
        nudge += 1
    elif nbe - nb >= 3:
        nudge -= 1
    if nr >= 4:                       # heavy risk load tempers an otherwise positive read
        nudge -= 1

    final = max(-2, min(2, band + nudge))
    verdict = VERDICT_BY_SCORE[final]

    if inp.composite_score is not None:
        rationale = (f"Composite {inp.composite_score:.0f}/100 → band {band:+d}; "
                     f"{nb} bull vs {nbe} bear, {nr} risk(s) → nudge {nudge:+d}; "
                     f"net {final:+d} ⇒ {verdict}.")
    else:
        rationale = (f"No composite score; {nb} bull / {nbe} bear / {nr} risk(s) "
                     f"→ nudge {nudge:+d}, net {final:+d} ⇒ {verdict}.")
    return verdict, final, rationale
