"""analysis/thesis/portfolio_fit.py — Portfolio Fit Assessment (Phase B).

Answers: "Is this stock a good addition to my CURRENT portfolio?" — by computing the
MARGINAL impact of adding a candidate to the existing book. Uses existing systems only
(thesis verdict, beta, sector, portfolio risk, correlation, concentration). NO AI.

Same two-layer design as Phase A1:
  * `assess_fit(inputs)` — PURE, deterministic; the tests target this. No network.
  * `build_fit_inputs(candidate, holdings, ...)` — integration seam that assembles the
    inputs from the live subsystems (portfolio beta, sector weights, candidate vs holdings
    correlation, candidate beta/vol, thesis verdict). Each piece optional + wrapped.

The candidate is assumed to be added at an equal-weight slice (1/(n+1) of the new book)
unless an explicit `assumed_weight_pct` is supplied — this gives concrete before→after
numbers (e.g. "Increases Financials exposure from 28% to 41%").
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional

# ── Fit ratings (ordered most-negative → most-positive by score) ─────────────────
FIT_RATINGS = ["Strong Conflict", "Poor Fit", "Neutral", "Fit", "Strong Fit"]
RATING_BY_SCORE = {-3: "Strong Conflict", -2: "Poor Fit", -1: "Poor Fit",
                   0: "Neutral", 1: "Fit", 2: "Fit", 3: "Strong Fit"}

POSITIVE = "positive"
NEGATIVE = "negative"

# Source subsystem labels
SRC_CORRELATION = "Correlation"
SRC_SECTOR = "Sector Exposure"
SRC_BETA = "Portfolio Beta"
SRC_CONCENTRATION = "Concentration"
SRC_THESIS = "Thesis"
SRC_VOL = "Volatility"

# ── Thresholds (single source of truth) ─────────────────────────────────────────
CORR_DIVERSIFY = 0.30      # avg corr below → strong diversifier
CORR_MODERATE = 0.60       # below → still helpful
CORR_REDUNDANT = 0.80      # above → redundant risk
SECTOR_HIGH = 40.0         # % post-add sector weight → over-concentration
SECTOR_VHIGH = 45.0        # % → strong over-concentration
BETA_RAISE_RISK = 1.20     # post-add beta above → market-risk negative
BETA_MOVE_MIN = 0.02       # ignore trivial beta moves
VOL_HIGH = 40.0            # candidate annualised vol % → sizing pressure
BETA_HIGH = 1.30           # candidate beta → sizing pressure


@dataclass
class FitFactor:
    """A single traceable fit effect: text + source + evidence + polarity."""
    text: str
    source: str
    evidence: str
    polarity: str           # POSITIVE | NEGATIVE

    def to_dict(self) -> dict:
        return {"text": self.text, "source": self.source,
                "evidence": self.evidence, "polarity": self.polarity}


@dataclass
class PortfolioFitInputs:
    """Normalized snapshot for the fit rules. Portfolio-relative fields may be None
    (e.g. empty book), in which case relative rules simply don't fire."""
    candidate_ticker: str

    # Candidate
    candidate_sector: Optional[str] = None
    candidate_beta: Optional[float] = None
    candidate_vol_pct: Optional[float] = None        # annualised %
    candidate_verdict: Optional[str] = None          # thesis verdict label
    candidate_verdict_score: Optional[int] = None    # -2 … +2

    # Candidate vs current holdings
    avg_correlation: Optional[float] = None          # mean corr to existing holdings
    max_correlation: Optional[float] = None
    most_correlated_with: Optional[str] = None

    # Current portfolio
    n_holdings: int = 0
    portfolio_beta: Optional[float] = None
    sector_weights: Dict[str, float] = field(default_factory=dict)   # sector → % (current)
    top_sector: Optional[str] = None
    top_sector_pct: Optional[float] = None
    concentration_risk: Optional[str] = None         # LOW/MEDIUM/HIGH/VERY HIGH

    # Sizing assumption
    assumed_weight_pct: Optional[float] = None        # candidate post-add weight %


@dataclass
class PortfolioFitResult:
    candidate_ticker: str
    fit_rating: str
    fit_score: int
    diversification_impact: str
    sector_impact: str
    beta_impact: str
    concentration_impact: str
    position_size_guidance: str        # Small | Moderate | Large
    position_size_reason: str
    positive_effects: List[FitFactor] = field(default_factory=list)
    negative_effects: List[FitFactor] = field(default_factory=list)
    supporting_evidence: List[FitFactor] = field(default_factory=list)
    inputs_present: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "candidate_ticker": self.candidate_ticker,
            "fit_rating": self.fit_rating, "fit_score": self.fit_score,
            "diversification_impact": self.diversification_impact,
            "sector_impact": self.sector_impact, "beta_impact": self.beta_impact,
            "concentration_impact": self.concentration_impact,
            "position_size_guidance": self.position_size_guidance,
            "position_size_reason": self.position_size_reason,
            "positive_effects": [f.to_dict() for f in self.positive_effects],
            "negative_effects": [f.to_dict() for f in self.negative_effects],
            "supporting_evidence": [f.to_dict() for f in self.supporting_evidence],
            "inputs_present": list(self.inputs_present),
            "notes": list(self.notes),
        }


# ─────────────────────────────── pure assessment ────────────────────────────────
def _candidate_weight(inp: PortfolioFitInputs) -> float:
    """Assumed post-add weight of the candidate, as a fraction (0–1)."""
    if inp.assumed_weight_pct is not None:
        return max(0.0, min(1.0, inp.assumed_weight_pct / 100.0))
    return 1.0 / (inp.n_holdings + 1)


def assess_fit(inp: PortfolioFitInputs) -> PortfolioFitResult:
    """Deterministic marginal-fit assessment. No network, no subsystem calls."""
    pos: List[FitFactor] = []
    neg: List[FitFactor] = []
    score = 0
    notes: List[str] = []

    c = _candidate_weight(inp)
    has_book = inp.n_holdings > 0

    # ── Diversification (correlation) ─────────────────────────────────────────
    if inp.avg_correlation is not None and has_book:
        ac = inp.avg_correlation
        if ac < CORR_DIVERSIFY:
            div_txt = f"Low average correlation to your holdings ({ac:.2f}) — strong diversifier."
            pos.append(FitFactor("Strong diversification benefit", SRC_CORRELATION,
                                 f"Avg correlation {ac:.2f} to existing holdings", POSITIVE))
            score += 2
        elif ac < CORR_MODERATE:
            div_txt = f"Moderate average correlation to your holdings ({ac:.2f}) — some diversification."
            pos.append(FitFactor("Adds some diversification", SRC_CORRELATION,
                                 f"Avg correlation {ac:.2f} to existing holdings", POSITIVE))
            score += 1
        elif ac < CORR_REDUNDANT:
            div_txt = f"Fairly correlated to your holdings ({ac:.2f}) — limited diversification."
        else:
            div_txt = f"Highly correlated to your holdings ({ac:.2f}) — adds little diversification."
            ev = f"Avg correlation {ac:.2f}"
            if inp.most_correlated_with and inp.max_correlation is not None:
                ev += f" (most like {inp.most_correlated_with} at {inp.max_correlation:.2f})"
            neg.append(FitFactor("Redundant with existing holdings", SRC_CORRELATION, ev, NEGATIVE))
            score -= 1
    elif not has_book:
        div_txt = "First position — diversification not applicable yet."
    else:
        div_txt = "Correlation to your holdings unavailable."

    # ── Sector impact ─────────────────────────────────────────────────────────
    sector_impact = "Sector impact unavailable."
    new_sector_pct: Optional[float] = None
    if inp.candidate_sector and has_book:
        s_old = inp.sector_weights.get(inp.candidate_sector, 0.0) / 100.0   # fraction
        new_sector_pct = (s_old * (1 - c) + c) * 100.0
        held = inp.candidate_sector in inp.sector_weights
        if held:
            sector_impact = (f"Increases {inp.candidate_sector} exposure from "
                             f"{s_old*100:.0f}% to {new_sector_pct:.0f}%.")
        else:
            sector_impact = (f"Adds a new sector ({inp.candidate_sector}) at "
                             f"~{new_sector_pct:.0f}% — broadens the book.")
        if new_sector_pct >= SECTOR_VHIGH:
            neg.append(FitFactor(f"Heavily over-concentrates {inp.candidate_sector}",
                                 SRC_SECTOR,
                                 f"{inp.candidate_sector} {s_old*100:.0f}% → {new_sector_pct:.0f}%",
                                 NEGATIVE))
            score -= 2
        elif new_sector_pct >= SECTOR_HIGH:
            neg.append(FitFactor(f"Raises {inp.candidate_sector} above a prudent 40%",
                                 SRC_SECTOR,
                                 f"{inp.candidate_sector} {s_old*100:.0f}% → {new_sector_pct:.0f}%",
                                 NEGATIVE))
            score -= 1
        elif not held:
            pos.append(FitFactor(f"Broadens diversification into {inp.candidate_sector}",
                                 SRC_SECTOR,
                                 f"New sector at ~{new_sector_pct:.0f}% of the book", POSITIVE))
            score += 1
    elif not has_book and inp.candidate_sector:
        sector_impact = f"First position — establishes {inp.candidate_sector} exposure."

    # ── Beta impact ───────────────────────────────────────────────────────────
    beta_impact = "Beta impact unavailable."
    if inp.candidate_beta is not None and inp.portfolio_beta is not None and has_book:
        beta_after = (1 - c) * inp.portfolio_beta + c * inp.candidate_beta
        beta_impact = (f"Moves portfolio beta from {inp.portfolio_beta:.2f} to {beta_after:.2f}.")
        delta = beta_after - inp.portfolio_beta
        if delta <= -BETA_MOVE_MIN:
            pos.append(FitFactor("Lowers portfolio market sensitivity", SRC_BETA,
                                 f"Portfolio beta {inp.portfolio_beta:.2f} → {beta_after:.2f}",
                                 POSITIVE))
            score += 1
        elif delta >= BETA_MOVE_MIN and beta_after > BETA_RAISE_RISK:
            neg.append(FitFactor("Raises portfolio beta above 1.2 (more market risk)", SRC_BETA,
                                 f"Portfolio beta {inp.portfolio_beta:.2f} → {beta_after:.2f}",
                                 NEGATIVE))
            score -= 1
    elif not has_book and inp.candidate_beta is not None:
        beta_impact = f"First position — sets portfolio beta to ~{inp.candidate_beta:.2f}."

    # ── Concentration impact ──────────────────────────────────────────────────
    concentration_impact = "Concentration impact unavailable."
    if has_book and inp.candidate_sector:
        is_top = (inp.top_sector is not None and inp.candidate_sector == inp.top_sector)
        crisk = (inp.concentration_risk or "").upper()
        if is_top:
            concentration_impact = (f"Adds to your largest sector ({inp.top_sector}, "
                                    f"currently {inp.top_sector_pct:.0f}%).")
            if crisk in ("HIGH", "VERY HIGH"):
                neg.append(FitFactor("Worsens an already-high concentration", SRC_CONCENTRATION,
                                     f"Top sector {inp.top_sector} {inp.top_sector_pct:.0f}% "
                                     f"(risk {inp.concentration_risk})", NEGATIVE))
                score -= 2
            else:
                neg.append(FitFactor("Increases concentration in your largest sector",
                                     SRC_CONCENTRATION,
                                     f"Top sector {inp.top_sector} {inp.top_sector_pct:.0f}%",
                                     NEGATIVE))
                score -= 1
        else:
            concentration_impact = (f"Spreads weight outside your largest sector "
                                    f"({inp.top_sector or 'n/a'}) — improves balance.")
            pos.append(FitFactor("Improves portfolio balance (away from the top sector)",
                                 SRC_CONCENTRATION,
                                 f"Candidate sector {inp.candidate_sector} ≠ top "
                                 f"{inp.top_sector or 'n/a'}", POSITIVE))
            score += 1

    # ── Candidate thesis gate (don't add a weak stock, however it diversifies) ─
    if inp.candidate_verdict_score is not None:
        vs = inp.candidate_verdict_score
        vlabel = inp.candidate_verdict or str(vs)
        if vs >= 1:
            pos.append(FitFactor(f"Candidate's own thesis is favourable ({vlabel})", SRC_THESIS,
                                 f"Thesis verdict {vlabel} (score {vs:+d})", POSITIVE))
            score += 1
        elif vs <= -2:
            neg.append(FitFactor(f"Candidate's own thesis is poor ({vlabel})", SRC_THESIS,
                                 f"Thesis verdict {vlabel} (score {vs:+d})", NEGATIVE))
            score -= 3
        elif vs == -1:
            neg.append(FitFactor(f"Candidate's own thesis is weak ({vlabel})", SRC_THESIS,
                                 f"Thesis verdict {vlabel} (score {vs:+d})", NEGATIVE))
            score -= 2

    # ── Fit rating ────────────────────────────────────────────────────────────
    clamped = max(-3, min(3, score))
    fit_rating = RATING_BY_SCORE[clamped]

    # ── Position size guidance ────────────────────────────────────────────────
    pressures: List[str] = []
    if inp.avg_correlation is not None and inp.avg_correlation > 0.70 and has_book:
        pressures.append(f"high correlation ({inp.avg_correlation:.2f})")
    if inp.candidate_beta is not None and inp.candidate_beta > BETA_HIGH:
        pressures.append(f"high beta ({inp.candidate_beta:.2f})")
    if inp.candidate_vol_pct is not None and inp.candidate_vol_pct > VOL_HIGH:
        pressures.append(f"high volatility ({inp.candidate_vol_pct:.0f}%)")
    if new_sector_pct is not None and new_sector_pct >= SECTOR_HIGH:
        pressures.append(f"sector concentration ({new_sector_pct:.0f}%)")

    weak_thesis = inp.candidate_verdict_score is not None and inp.candidate_verdict_score <= -1
    if weak_thesis:
        guidance = "Small"
        size_reason = (f"Small — the candidate's own thesis is weak "
                       f"({inp.candidate_verdict or inp.candidate_verdict_score}); size conservatively.")
    elif len(pressures) >= 2:
        guidance = "Small"
        size_reason = "Small — multiple risk pressures: " + "; ".join(pressures) + "."
    elif len(pressures) == 1:
        guidance = "Moderate"
        size_reason = "Moderate — one risk pressure: " + pressures[0] + "."
    else:
        guidance = "Large"
        size_reason = ("Large — no concentration, beta, volatility or correlation pressures "
                       "detected against your current book.")

    # ── Provenance ────────────────────────────────────────────────────────────
    present = []
    if inp.avg_correlation is not None:
        present.append(SRC_CORRELATION)
    if inp.candidate_sector and inp.sector_weights:
        present.append(SRC_SECTOR)
    if inp.candidate_beta is not None and inp.portfolio_beta is not None:
        present.append(SRC_BETA)
    if inp.concentration_risk:
        present.append(SRC_CONCENTRATION)
    if inp.candidate_verdict_score is not None:
        present.append(SRC_THESIS)
    if inp.candidate_vol_pct is not None:
        present.append(SRC_VOL)

    if not has_book:
        notes.append("Portfolio is empty — fit is based on the candidate's own thesis and risk; "
                     "portfolio-relative effects are not applicable.")
    notes.append(f"Assumes the candidate is added at ~{c*100:.0f}% of the new book "
                 f"({'explicit' if inp.assumed_weight_pct is not None else 'equal-weight assumption'}).")

    return PortfolioFitResult(
        candidate_ticker=inp.candidate_ticker,
        fit_rating=fit_rating, fit_score=clamped,
        diversification_impact=div_txt, sector_impact=sector_impact,
        beta_impact=beta_impact, concentration_impact=concentration_impact,
        position_size_guidance=guidance, position_size_reason=size_reason,
        positive_effects=pos, negative_effects=neg,
        supporting_evidence=pos + neg, inputs_present=present, notes=notes,
    )


# ─────────────────────────── integration seam ───────────────────────────────────
def _pct_returns(series):
    return series.pct_change().dropna()


def build_fit_inputs(candidate_ticker: str,
                     holdings: List[Dict], *,
                     period: str = "1y",
                     candidate_thesis=None,
                     candidate_beta: Optional[float] = None,
                     candidate_sector: Optional[str] = None,
                     price_loader=None) -> PortfolioFitInputs:
    """Assemble PortfolioFitInputs from existing subsystems.

    holdings: list of {"ticker", "quantity"} (the current book). Everything is wrapped;
    a subsystem failure degrades that field to None rather than raising.
    """
    inp = PortfolioFitInputs(candidate_ticker=candidate_ticker)

    book = [(h.get("ticker"), float(h.get("quantity") or 0))
            for h in holdings if h.get("ticker") and float(h.get("quantity") or 0) > 0]
    inp.n_holdings = len(book)

    if price_loader is None:
        try:
            from data.fetcher import fetch_single as price_loader
        except Exception:
            price_loader = None

    # Candidate sector
    if candidate_sector is None:
        try:
            from data.universe import get_sector
            candidate_sector = get_sector(candidate_ticker)
        except Exception:
            candidate_sector = None
    inp.candidate_sector = candidate_sector

    # Candidate thesis verdict
    th = candidate_thesis
    if th is None:
        try:
            from .thesis_engine import thesis_for_ticker
            th = thesis_for_ticker(candidate_ticker)
        except Exception:
            th = None
    if th is not None:
        inp.candidate_verdict = getattr(th, "verdict", None)
        inp.candidate_verdict_score = getattr(th, "verdict_score", None)

    # Candidate beta
    if candidate_beta is None:
        try:
            from analysis.hedging import calculate_stock_beta
            b = calculate_stock_beta(candidate_ticker, period=period)
            candidate_beta = None if (b is None or (isinstance(b, float) and math.isnan(b))) else float(b)
        except Exception:
            candidate_beta = None
    inp.candidate_beta = candidate_beta

    # Sector weights + concentration (reuse portfolio_manager analyser if a CSV book,
    # else compute from holdings + get_sector + latest price)
    if book and price_loader is not None:
        import pandas as pd
        from analysis.portfolio_risk import TRADING_DAYS
        try:
            from data.universe import get_sector
        except Exception:
            get_sector = lambda t: "Unknown"   # noqa: E731

        closes, values, sector_val = {}, {}, {}
        for tkr, q in book:
            try:
                df = price_loader(tkr, period=period)
                s = df["Close"].dropna() if df is not None and not df.empty else None
            except Exception:
                s = None
            if s is None or len(s) < 30:
                continue
            closes[tkr] = s
            v = q * float(s.iloc[-1])
            values[tkr] = v
            sec = get_sector(tkr) or "Unknown"
            sector_val[sec] = sector_val.get(sec, 0.0) + v

        total = sum(values.values()) or 1.0
        inp.sector_weights = {s: round(v / total * 100, 1) for s, v in sector_val.items()}
        if inp.sector_weights:
            inp.top_sector = max(inp.sector_weights, key=inp.sector_weights.__getitem__)
            inp.top_sector_pct = inp.sector_weights[inp.top_sector]
            tp = inp.top_sector_pct
            inp.concentration_risk = ("VERY HIGH" if tp > 60 else "HIGH" if tp > 45
                                      else "MEDIUM" if (tp > 30 or len(inp.sector_weights) < 4)
                                      else "LOW")

        # Portfolio beta — reuse hedging engine
        try:
            from analysis.hedging import calculate_portfolio_beta
            bo = calculate_portfolio_beta(
                [{"ticker": t, "value_rs": values[t]} for t in closes], period=period)
            pb = bo.get("portfolio_beta")
            inp.portfolio_beta = None if (pb is None or (isinstance(pb, float) and math.isnan(pb))) else pb
        except Exception:
            inp.portfolio_beta = None

        # Candidate vs holdings correlation + candidate vol
        try:
            cdf = price_loader(candidate_ticker, period=period)
            cs = cdf["Close"].dropna() if cdf is not None and not cdf.empty else None
        except Exception:
            cs = None
        if cs is not None and len(cs) >= 30:
            cret = _pct_returns(cs)
            inp.candidate_vol_pct = round(float(cret.std()) * math.sqrt(TRADING_DAYS) * 100, 2)
            corrs = {}
            for tkr, s in closes.items():
                joined = pd.concat([cs, s], axis=1).dropna()
                if len(joined) >= 5:
                    r = joined.pct_change().dropna()
                    cval = r.iloc[:, 0].corr(r.iloc[:, 1])
                    if cval is not None and not math.isnan(cval):
                        corrs[tkr.replace(".NS", "")] = round(float(cval), 2)
            if corrs:
                inp.avg_correlation = round(sum(corrs.values()) / len(corrs), 2)
                inp.most_correlated_with = max(corrs, key=corrs.__getitem__)
                inp.max_correlation = corrs[inp.most_correlated_with]

    return inp


def fit_for_candidate(candidate_ticker: str, holdings: List[Dict], **pieces) -> PortfolioFitResult:
    """Convenience: build_fit_inputs(...) then assess_fit(...)."""
    return assess_fit(build_fit_inputs(candidate_ticker, holdings, **pieces))
