"""analysis/fundamentals/valuation_decision.py — Valuation Decision Layer (Phase E1-v2).

Implements docs/VALUATION_DECISION_E1_V2_SPEC.md exactly: a sector-aware, growth- and
quality-adjusted *descriptive* valuation posture, with all stress-test guardrails
(G1 peak, G2 quality gate, G3 PEG band, G4 cash-conversion veto, G5–G10) applied as an
ORDERED pipeline — guards run BEFORE the reasoning matrices.

Descriptive philosophy (hard rule): the engine NEVER says Buy/Sell/Fair value/Intrinsic
value/Cheap/Expensive/Under-/Over-valued. It only relates a multiple to growth (PEG) and
quality (ROE/ROCE), and on any ambiguity defaults to Reasonable / Insufficient — never
Supported.

Pure & deterministic: `assess(ValuationInputs)` touches no network. `assess_valuation(...)`
is the integration seam that extracts inputs from existing objects (ValuationContext,
analytics dict, SectorProfile, CompanyFundamentals). No new data, no provider.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from analysis.sector_classification import (
    METALS, CHEMICALS, AUTO, MANUFACTURING, ENERGY_POWER, INFRASTRUCTURE,
    FINANCIAL_SERVICES, INSURANCE,
)

# Sectors where peak/trough cyclicality guards are active (commodity/cyclical earnings).
# Commodity-cyclical sectors — earnings swing with commodity/price cycles, so the
# cyclical peak (G1) and trough guards apply. (Energy & Power is included because most of
# it is commodity oil/gas/refining; regulated utilities within it are excluded below.)
COMMODITY_CYCLICAL = {METALS, CHEMICALS, AUTO, MANUFACTURING, ENERGY_POWER}

# Regulated utilities — stable, regulated-ROE earnings (power transmission/distribution,
# grid infra, regulated generation). The cyclical peak/trough guards must NOT fire on these:
# their earnings are regulated, not commodity-cyclical (V1 finding: POWERGRID was wrongly
# trough-refused). Identified by ticker symbol or company-name keyword, since the sector
# classifier groups them under "Energy & Power" alongside commodity-energy.
REGULATED_UTILITY = {"POWERGRID", "NTPC", "NHPC", "SJVN", "NLCINDIA", "PGCIL"}
_REG_UTIL_NAME_KW = ("power grid", "grid corporation", "transmission",
                     "national thermal", "hydroelectric", "hydro power")

# Back-compat alias (was the single combined set before the V1 utilities/commodity split).
CYCLICAL_GROUPS = COMMODITY_CYCLICAL


def is_regulated_utility(symbol=None, name=None) -> bool:
    """True for regulated power utilities (trough/peak guards do not apply)."""
    sym = (symbol or "").replace(".NS", "").replace(".BO", "").strip().upper()
    if sym in REGULATED_UTILITY:
        return True
    nm = (name or "").lower()
    return any(k in nm for k in _REG_UTIL_NAME_KW)

# ── Posture constants (the ONLY permitted conclusions) ───────────────────────────
SUPPORTED_BY_GROWTH_AND_QUALITY = "SUPPORTED_BY_GROWTH_AND_QUALITY"
SUPPORTED_BY_GROWTH = "SUPPORTED_BY_GROWTH"
SUPPORTED_BY_QUALITY = "SUPPORTED_BY_QUALITY"
SUPPORTED_BY_ROE = "SUPPORTED_BY_ROE"
REASONABLE = "REASONABLE"
DEMANDING_VS_GROWTH = "DEMANDING_VS_GROWTH"
DEMANDING_VS_RETURNS = "DEMANDING_VS_RETURNS"
DEMANDING_VS_ROE = "DEMANDING_VS_ROE"
INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"

_SUPPORTED = {SUPPORTED_BY_GROWTH_AND_QUALITY, SUPPORTED_BY_GROWTH,
              SUPPORTED_BY_QUALITY, SUPPORTED_BY_ROE}
_DIRECTIONAL = _SUPPORTED | {DEMANDING_VS_GROWTH, DEMANDING_VS_RETURNS, DEMANDING_VS_ROE}

PHRASES = {
    SUPPORTED_BY_GROWTH_AND_QUALITY: "Valuation appears supported by both growth and quality.",
    SUPPORTED_BY_GROWTH: "Valuation appears supported by growth.",
    SUPPORTED_BY_QUALITY: "Valuation appears supported by quality (high returns on capital).",
    SUPPORTED_BY_ROE: "Valuation appears supported by ROE.",
    REASONABLE: "Valuation appears reasonable relative to growth and returns.",
    DEMANDING_VS_GROWTH: "Valuation appears demanding relative to growth.",
    DEMANDING_VS_RETURNS: "Valuation appears demanding relative to returns on capital.",
    DEMANDING_VS_ROE: "Valuation appears demanding relative to ROE.",
    INSUFFICIENT_EVIDENCE: "Insufficient evidence to assess valuation.",
}

# ── Thresholds (single source of truth; from the spec) ───────────────────────────
ROCE_HIGH = 20.0
ROCE_FLOOR = 12.0          # G2 quality gate
ROE_HIGH = 16.0
ROE_MOD = 10.0
ROE_ELEVATED = 20.0        # G6
PB_LOW = 1.5
PB_HIGH = 3.0
PEG_LOW = 1.0
PEG_HIGH = 2.0
GROWTH_MIN = 5.0           # G3 band floor
GROWTH_MAX = 60.0          # G3 band cap
PE_IMPLAUSIBLE = 200.0
PEAK_PE = 12.0             # G1
PEAK_ROCE = 18.0
PEAK_EPS_CAGR = 30.0
MARGIN_DIVERGENCE = 15.0   # EPS-CAGR − Rev-CAGR (pp)
TROUGH_PE = 35.0
TROUGH_ROCE = 10.0
CONV_MIN = 0.6             # OCF/NI floor (G4)
SPAN_HIGH = 3.0            # G8
SPAN_MIN = 2.0


@dataclass
class ValuationInputs:
    sector_group: str
    is_financial: bool
    fcf_capex_caveat: bool
    # multiples
    pe: Optional[float] = None
    pb: Optional[float] = None
    # quality
    roce: Optional[float] = None        # %
    roe: Optional[float] = None         # %
    roe_averaged: bool = False          # True if ROE is a multi-period average
    # growth
    eps_cagr: Optional[float] = None    # %
    revenue_cagr: Optional[float] = None  # %
    eps_cagr_span_years: Optional[float] = None
    eps_cagr_points: Optional[int] = None
    eps_cagr_start_value: Optional[float] = None
    # earnings / equity / cash
    net_income: Optional[float] = None
    total_equity: Optional[float] = None
    operating_cash_flow: Optional[float] = None
    fcf: Optional[float] = None         # ₹ cr (sign meaningful)
    # flags
    is_psu: bool = False
    is_regulated_utility: bool = False   # regulated power utility → cyclical guards OFF

    @property
    def is_cyclical(self) -> bool:
        # Commodity-cyclical sectors fire the peak/trough guards — EXCEPT regulated
        # utilities, whose earnings are regulated, not commodity-cyclical (V1 fix).
        return (self.sector_group in COMMODITY_CYCLICAL) and not self.is_regulated_utility

    @property
    def is_insurance(self) -> bool:
        return self.sector_group == INSURANCE


@dataclass
class ValuationAssessment:
    posture: str
    phrase: str
    justification: str
    confidence: str                     # high | medium | low | none
    confidence_factors: List[str] = field(default_factory=list)
    reasons: List[str] = field(default_factory=list)      # what produced the posture
    caveats: List[str] = field(default_factory=list)
    triggered_guard: Optional[str] = None                  # set on refusal
    inputs_used: List[str] = field(default_factory=list)
    sector_branch: str = ""

    def to_dict(self) -> dict:
        return {"posture": self.posture, "phrase": self.phrase,
                "justification": self.justification, "confidence": self.confidence,
                "confidence_factors": list(self.confidence_factors),
                "reasons": list(self.reasons), "caveats": list(self.caveats),
                "triggered_guard": self.triggered_guard,
                "inputs_used": list(self.inputs_used), "sector_branch": self.sector_branch}


# ── helpers ──────────────────────────────────────────────────────────────────────
def _branch(inp: ValuationInputs) -> str:
    if inp.is_insurance:
        return "insurance"
    return "financial" if inp.is_financial else "non-financial"


def _refuse(guard: str, reason: str, branch: str, inputs_used: List[str]) -> ValuationAssessment:
    return ValuationAssessment(
        posture=INSUFFICIENT_EVIDENCE, phrase=PHRASES[INSUFFICIENT_EVIDENCE],
        justification=reason, confidence="none", confidence_factors=[],
        reasons=[reason], caveats=[], triggered_guard=guard,
        inputs_used=inputs_used, sector_branch=branch)


def _fmt(x, suffix="%"):
    return f"{x:.1f}{suffix}" if x is not None else "n/a"


def _quality_tier(roce: Optional[float]) -> Optional[str]:
    if roce is None:
        return None
    if roce >= ROCE_HIGH:
        return "High"
    if roce >= ROCE_FLOOR:
        return "Moderate"
    return "Low"


def _roe_tier(roe: Optional[float]) -> Optional[str]:
    if roe is None:
        return None
    if roe >= ROE_HIGH:
        return "High"
    if roe >= ROE_MOD:
        return "Moderate"
    return "Low"


def _pb_tier(pb: Optional[float]) -> Optional[str]:
    if pb is None:
        return None
    if pb < PB_LOW:
        return "Low"
    if pb <= PB_HIGH:
        return "Moderate"
    return "High"


def _peg_tier(peg: float) -> str:
    if peg < PEG_LOW:
        return "low"
    if peg <= PEG_HIGH:
        return "mid"
    return "high"


_LEVEL = {3: "high", 2: "medium", 1: "low"}


# ── the pipeline ─────────────────────────────────────────────────────────────────
def assess(inp: ValuationInputs) -> ValuationAssessment:
    branch = _branch(inp)
    used: List[str] = []

    # ── Step 1 — HARD guards (refuse before any reasoning) ──────────────────────
    if inp.is_insurance:
        return _refuse("H4-insurance",
                       "Insurers are valued on embedded value (P/EV), which is not available.",
                       branch, used)
    if inp.total_equity is not None and inp.total_equity <= 0:
        return _refuse("H2-negative-equity",
                       "Negative shareholders' equity — P/B and ROE are not meaningful.",
                       branch, used)
    if inp.is_financial:
        if inp.pb is None or inp.roe is None:
            return _refuse("H3-missing-metric",
                           "Financial branch needs both P/B and ROE; one is unavailable.",
                           branch, used)
    else:
        if inp.net_income is not None and inp.net_income <= 0:
            return _refuse("H1-negative-earnings",
                           "Earnings are negative or zero — no earnings-based valuation possible.",
                           branch, used)
        if inp.pe is None:
            return _refuse("H3-missing-metric",
                           "No usable earnings multiple (P/E) to assess against growth.",
                           branch, used)
        if inp.pe > PE_IMPLAUSIBLE:
            return _refuse("H6-implausible",
                           f"P/E {inp.pe:.0f}× is implausibly high — likely an earnings distortion.",
                           branch, used)
        if inp.eps_cagr_points is not None and inp.eps_cagr_points < 2:
            return _refuse("H5-newly-listed",
                           "Under two years of earnings history — too new to assess valuation.",
                           branch, used)

    # ── Financial branch (P/B × ROE) ────────────────────────────────────────────
    if inp.is_financial:
        return _assess_financial(inp, branch)

    # ── Step 2 — base-effect / turnaround (G7) ──────────────────────────────────
    growth_off_reason: Optional[str] = None
    if inp.eps_cagr is not None and inp.eps_cagr > GROWTH_MAX:
        growth_off_reason = (f"EPS CAGR {inp.eps_cagr:.0f}% exceeds the {GROWTH_MAX:.0f}% cap — "
                             "likely a low-base/turnaround effect; growth lens disabled.")
    if (inp.eps_cagr_start_value is not None and inp.net_income is not None
            and inp.eps_cagr_start_value <= 0):
        growth_off_reason = ("Earnings recently crossed zero (turnaround) — growth lens disabled.")

    # ── Step 3 — cyclical PEAK guard (G1) ───────────────────────────────────────
    if inp.is_cyclical and inp.pe is not None and inp.roce is not None and inp.eps_cagr is not None:
        margin_div = (inp.revenue_cagr is not None
                      and (inp.eps_cagr - inp.revenue_cagr) > MARGIN_DIVERGENCE)
        if (inp.pe < PEAK_PE and inp.roce > PEAK_ROCE and inp.eps_cagr > PEAK_EPS_CAGR
                and margin_div):
            return _refuse(
                "G1-cyclical-peak",
                (f"Possible cyclical peak: low P/E {inp.pe:.0f}× with high ROCE {inp.roce:.0f}% "
                 f"and margin-led EPS CAGR {inp.eps_cagr:.0f}% (vs revenue {inp.revenue_cagr:.0f}%) "
                 "— earnings may be near a cyclical top."),
                branch, used)

    # ── Step 4 — cyclical TROUGH guard (broadened) ──────────────────────────────
    if inp.is_cyclical:
        trough = ((inp.eps_cagr is not None and inp.eps_cagr < 0)
                  or (inp.pe is not None and inp.pe > TROUGH_PE
                      and inp.roce is not None and inp.roce < TROUGH_ROCE))
        if trough:
            return _refuse(
                "TR-cyclical-trough",
                ("Possible cyclical trough: depressed earnings distort the multiple "
                 "(high P/E with low ROCE, or negative earnings growth)."),
                branch, used)

    return _assess_non_financial(inp, branch, growth_off_reason)


# ── financial reasoning (§5) ─────────────────────────────────────────────────────
def _assess_financial(inp: ValuationInputs, branch: str) -> ValuationAssessment:
    used = ["P/B", "ROE"]
    rt, pbt = _roe_tier(inp.roe), _pb_tier(inp.pb)
    reasons, caveats, conf_factors = [], [], []
    reasons.append(f"ROE {self_pct(inp.roe)} ({rt}) vs P/B {inp.pb:.2f}× ({pbt}).")

    if rt == "High":
        posture = SUPPORTED_BY_ROE if pbt in ("Low", "Moderate") else REASONABLE
        if pbt == "High":
            reasons.append("High P/B but matched by a high ROE.")
    elif rt == "Moderate":
        posture = REASONABLE if pbt in ("Low", "Moderate") else DEMANDING_VS_ROE
    else:  # Low ROE
        posture = REASONABLE if pbt == "Low" else DEMANDING_VS_ROE
        if pbt == "Low":
            caveats.append("Low ROE — a low P/B may reflect weak returns rather than value.")

    # G6 — elevated-ROE caution
    cap_medium = False
    if inp.roe is not None and inp.roe >= ROE_ELEVATED and pbt == "High":
        posture = DEMANDING_VS_ROE
        caveats.append("ROE may be cyclically elevated (benign credit cycle); the premium "
                       "assumes it persists.")
        cap_medium = True
    if not inp.roe_averaged:
        caveats.append("ROE is a single-period figure; a multi-year average would be steadier.")
        cap_medium = True
    if inp.sector_group == FINANCIAL_SERVICES:
        cap_medium = True
        conf_factors.append("applicability: heterogeneous Financial-Services bucket → capped medium")
    if inp.is_psu:
        cap_medium = True
        caveats.append("PSU — returns may reflect government priorities or one-offs.")

    # confidence
    avail = 3 if inp.roe_averaged else 2
    applic = 2 if inp.sector_group == FINANCIAL_SERVICES else 3
    level = min(avail, applic)
    if cap_medium:
        level = min(level, 2)
    conf_factors.append(f"data availability: {'averaged' if inp.roe_averaged else 'single-period'} ROE")
    confidence = _LEVEL[level]

    just = f"P/B {inp.pb:.2f}× against ROE {self_pct(inp.roe)}"
    return ValuationAssessment(posture=posture, phrase=PHRASES[posture], justification=just,
                               confidence=confidence, confidence_factors=conf_factors,
                               reasons=reasons, caveats=caveats, inputs_used=used,
                               sector_branch=branch)


def self_pct(x):
    return f"{x:.1f}%" if x is not None else "n/a"


# ── non-financial reasoning (§4) ─────────────────────────────────────────────────
def _assess_non_financial(inp: ValuationInputs, branch: str,
                          growth_off_reason: Optional[str]) -> ValuationAssessment:
    reasons, caveats, conf_factors = [], [], []
    used = ["P/E"]

    qtier = _quality_tier(inp.roce)
    if inp.roce is not None:
        used.append("ROCE")

    # Growth lens validity (G3 band + base-effect)
    growth_valid = (growth_off_reason is None and inp.eps_cagr is not None
                    and GROWTH_MIN <= inp.eps_cagr <= GROWTH_MAX and inp.pe is not None)
    if growth_off_reason:
        caveats.append(growth_off_reason)
    elif inp.eps_cagr is not None and inp.eps_cagr < GROWTH_MIN:
        caveats.append(f"EPS CAGR {inp.eps_cagr:.1f}% is below the {GROWTH_MIN:.0f}% floor — "
                       "PEG is unstable, so growth is not assessed.")

    peak_caution = (inp.is_cyclical and inp.pe is not None and inp.pe < PEAK_PE
                    and inp.roce is not None and inp.roce > PEAK_ROCE)
    if peak_caution:
        caveats.append("Cyclical sector with a low multiple on high returns — watch for a "
                       "cyclical-earnings peak.")

    # ── growth lens OFF → quality-led / insufficient ──
    if not growth_valid:
        if qtier == "High":
            reasons.append(f"ROCE {self_pct(inp.roce)} is high but growth is unmeasurable/too low.")
            return ValuationAssessment(
                posture=REASONABLE, phrase=PHRASES[REASONABLE],
                justification=(f"ROCE {self_pct(inp.roce)} with minimal/unmeasurable growth — "
                               "valuation not assessed against growth."),
                confidence="low",
                confidence_factors=["data availability: growth lens unavailable → low"],
                reasons=reasons,
                caveats=caveats + ["High returns on capital but growth not assessable."],
                inputs_used=used + ["ROCE"], sector_branch=branch)
        # Regulated utilities are stable, low-growth BY DESIGN — "growth too low to assess"
        # is an expected characteristic, not a data deficiency, so a regulated utility
        # resolves to Reasonable (low confidence) rather than a refusal. (Part 1 / V1 fix:
        # the same over-refusal that hit POWERGRID via the trough guard also reaches it here.)
        if inp.is_regulated_utility:
            reasons.append("Regulated utility — stable, low-growth regulated earnings.")
            return ValuationAssessment(
                posture=REASONABLE, phrase=PHRASES[REASONABLE],
                justification="Regulated utility with stable, low-growth earnings — "
                              "valuation not assessed against growth.",
                confidence="low",
                confidence_factors=["regulated utility: growth lens not applicable → low"],
                reasons=reasons,
                caveats=caveats + ["Regulated earnings; growth not the right lens."],
                inputs_used=used + (["ROCE"] if inp.roce is not None else []),
                sector_branch=branch)
        return _refuse("growth-lens-off",
                       "Growth cannot be assessed and quality is not exceptional — "
                       "insufficient basis for a valuation posture.", branch, used)

    # ── growth lens valid → PEG × quality matrix (with G2 gate) ──
    used.append("EPS CAGR")
    peg = inp.pe / inp.eps_cagr
    pegt = _peg_tier(peg)
    reasons.append(f"P/E {inp.pe:.0f}× ÷ EPS CAGR {inp.eps_cagr:.0f}% → PEG {peg:.2f} ({pegt}).")

    posture = _matrix_non_financial(pegt, qtier, reasons)

    # G5 — capex-phase ROCE softening
    capex_soft = False
    if inp.fcf_capex_caveat and posture == DEMANDING_VS_RETURNS:
        posture = REASONABLE
        capex_soft = True
        caveats.append("Returns on capital may be temporarily depressed by an ongoing capex cycle.")

    # quality note on demanding-vs-growth with high ROCE
    if posture == DEMANDING_VS_GROWTH and qtier == "High":
        caveats.append("The premium is partly supported by high returns on capital.")

    # ── G4 — cash-conversion veto (non-capex only) ──
    ocf_ni = None
    if inp.operating_cash_flow is not None and inp.net_income and inp.net_income > 0:
        ocf_ni = inp.operating_cash_flow / inp.net_income
    poor_conversion = (not inp.fcf_capex_caveat) and (
        (inp.fcf is not None and inp.fcf < 0) or (ocf_ni is not None and ocf_ni < CONV_MIN))
    if poor_conversion and posture in _SUPPORTED:
        posture = REASONABLE
        caveats.append("Earnings are not converting to cash (weak free cash flow) — growth "
                       "quality is unproven.")
        reasons.append("Cash-conversion veto applied (G4): supportive posture downgraded.")

    # ── confidence (§8) ──
    confidence, conf_factors, consist_level = _confidence_non_financial(
        inp, growth_valid, qtier, peg, pegt, capex_soft, peak_caution)

    # consistency override: only a SUPPORTED posture on incoherent evidence → Reasonable
    # (demanding postures are already conservative and are left to stand).
    if consist_level == 1 and posture in _SUPPORTED:
        reasons.append("Evidence is incoherent (margin-led growth with weak cash) → "
                       "downgraded to Reasonable.")
        posture = REASONABLE

    just = (f"P/E {inp.pe:.0f}× against EPS CAGR {inp.eps_cagr:.0f}% "
            f"and ROCE {self_pct(inp.roce)}")
    return ValuationAssessment(posture=posture, phrase=PHRASES[posture], justification=just,
                               confidence=confidence, confidence_factors=conf_factors,
                               reasons=reasons, caveats=caveats, inputs_used=used,
                               sector_branch=branch)


def _matrix_non_financial(pegt: str, qtier: Optional[str], reasons: List[str]) -> str:
    """The gated PEG × quality matrix. Low-quality column can never be 'Supported' (G2)."""
    if qtier is None:                       # quality unknown → no 'Supported' possible
        reasons.append("Quality (ROCE) unavailable — cannot issue a quality-gated 'Supported'.")
        return {"low": REASONABLE, "mid": REASONABLE, "high": DEMANDING_VS_GROWTH}[pegt]
    table = {
        ("low", "High"): SUPPORTED_BY_GROWTH_AND_QUALITY,
        ("low", "Moderate"): SUPPORTED_BY_GROWTH,
        ("low", "Low"): REASONABLE,          # G2 gate: 'growth on low returns (unproven)'
        ("mid", "High"): SUPPORTED_BY_QUALITY,
        ("mid", "Moderate"): REASONABLE,
        ("mid", "Low"): DEMANDING_VS_RETURNS,
        ("high", "High"): DEMANDING_VS_GROWTH,
        ("high", "Moderate"): DEMANDING_VS_GROWTH,
        ("high", "Low"): DEMANDING_VS_RETURNS,
    }
    posture = table[(pegt, qtier)]
    if pegt == "low" and qtier == "Low":
        reasons.append("Quality gate (G2): low ROCE blocks a 'Supported' posture → Reasonable "
                       "(growth on low returns, unproven).")
    return posture


def _confidence_non_financial(inp, growth_valid, qtier, peg, pegt, capex_soft, peak_caution):
    factors: List[str] = []
    # availability
    span = inp.eps_cagr_span_years
    if growth_valid and qtier is not None:
        if span is not None and span >= SPAN_HIGH:
            avail = 3
        elif span is not None and span >= SPAN_MIN:
            avail = 2
        else:
            avail = 2 if span is None else 1
    else:
        avail = 1
    factors.append(f"data availability: growth span "
                   f"{('%.0fy' % span) if span is not None else 'unknown'} → {_LEVEL[avail]}")
    # applicability
    applic = 2 if inp.sector_group in (INFRASTRUCTURE, ENERGY_POWER) else 3
    if applic == 2:
        factors.append("applicability: capital-intensive/regulated sector → capped medium")
    # consistency — only genuine incoherence lowers it (a rich multiple on high quality is
    # the legitimate 'demanding-vs-growth, quality-supported' cell, NOT a contradiction).
    margin_div = (inp.revenue_cagr is not None and inp.eps_cagr is not None
                  and (inp.eps_cagr - inp.revenue_cagr) > MARGIN_DIVERGENCE)
    fcf_neg = inp.fcf is not None and inp.fcf < 0 and not inp.fcf_capex_caveat
    if margin_div and fcf_neg:
        consist = 1
        factors.append("consistency: margin-led growth AND weak cash → low")
    elif margin_div:
        consist = 2
        factors.append("consistency: margin-led growth (EPS ≫ revenue) → capped medium")
    elif fcf_neg:
        consist = 2
        factors.append("consistency: negative free cash flow → capped medium")
    else:
        consist = 3
        factors.append("consistency: growth, quality and cash agree")

    level = min(avail, applic, consist)
    if capex_soft:
        level = min(level, 2); factors.append("capex-softened cell → capped medium")
    if peak_caution:
        level = min(level, 2); factors.append("cyclical peak-caution → capped medium")
    if inp.is_psu:
        level = min(level, 2); factors.append("PSU → capped medium")
    if qtier is None:
        level = min(level, 2); factors.append("single-lens (no quality) → capped medium")
    return _LEVEL[level], factors, consist


# ── integration seam ─────────────────────────────────────────────────────────────
def build_valuation_inputs(valuation_context, analytics: dict, sector_profile,
                           cf=None, is_psu: bool = False) -> ValuationInputs:
    """Build a ValuationInputs from existing objects (the live-data adapter). Exposed
    separately so the regression harness can capture the exact inputs for offline replay."""
    def _av(key):
        a = analytics.get(key) if analytics else None
        return a.value if (a is not None and getattr(a, "available", False)
                           and a.value is not None) else None

    eps_a = analytics.get("eps_cagr") if analytics else None
    detail = getattr(eps_a, "detail", {}) if eps_a is not None else {}

    inc = cf.latest_income() if (cf is not None and hasattr(cf, "latest_income")) else None
    bal = cf.latest_balance() if (cf is not None and hasattr(cf, "latest_balance")) else None
    cfs = cf.latest_cashflow() if (cf is not None and hasattr(cf, "latest_cashflow")) else None
    n_income = len(getattr(cf, "income_statements", []) or []) if cf is not None else None

    inp = ValuationInputs(
        sector_group=getattr(sector_profile, "group", "Other"),
        is_financial=getattr(sector_profile, "is_financial", False),
        fcf_capex_caveat=getattr(sector_profile, "fcf_capex_caveat", False),
        pe=getattr(valuation_context, "pe", None),
        pb=getattr(valuation_context, "pb", None),
        roce=_av("roce"), roe=_av("roe"),
        roe_averaged=("average" in str(
            (analytics.get("roe").detail.get("equity_basis", "")) if analytics
            and analytics.get("roe") is not None else "")),
        eps_cagr=_av("eps_cagr"), revenue_cagr=_av("revenue_cagr"),
        eps_cagr_span_years=detail.get("span_years"),
        eps_cagr_points=detail.get("points") if detail else n_income,
        eps_cagr_start_value=detail.get("start_value"),
        net_income=getattr(inc, "net_income", None) if inc else None,
        total_equity=getattr(bal, "total_equity", None) if bal else None,
        operating_cash_flow=getattr(cfs, "operating_cash_flow", None) if cfs else None,
        fcf=_av("fcf"), is_psu=is_psu,
        is_regulated_utility=is_regulated_utility(
            getattr(cf, "symbol", None) if cf is not None else None,
            getattr(cf, "company_name", None) if cf is not None else None),
    )
    return inp


def assess_valuation(valuation_context, analytics: dict, sector_profile,
                     cf=None, is_psu: bool = False) -> ValuationAssessment:
    """Build ValuationInputs from existing objects, then assess. Defensive/wrapped."""
    return assess(build_valuation_inputs(valuation_context, analytics, sector_profile,
                                         cf=cf, is_psu=is_psu))
