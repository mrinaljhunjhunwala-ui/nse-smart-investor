"""
analysis/business_gate.py — a plain "is the business itself sound?" check.

Why this exists
───────────────
Analyze Stock's headline used to be an if-ladder on the 0–90 trend composite
alone, so a company with negative net worth and a clean chart read
"Constructive". This module answers the question the chart cannot: does the
latest fundamental / governance evidence show a broken business? The page
shows its result FIRST ("Business"), then the trend read ("Trend").

It is descriptive. Every reason is a fact ("negative net worth (latest
filing)", "quality score 22/100") — never an instruction. It does not fetch
anything; the page passes the inputs it already computed for the FinalVerdict
(``analysis.final_verdict.combine``), so the two reads cannot disagree on the
facts.

Statuses
────────
=================  ==========================================================
Status             Fires when (first matching group wins: FAIL > INSUFFICIENT
                   > CAUTION > PASS)
=================  ==========================================================
FAIL               quality score < 30 (0 counts) · total equity < 0 ·
                   valuation refused with guard
                   ``H2-negative-equity`` (method does not apply because net
                   worth is not positive)
INSUFFICIENT_DATA  ``fundamentals_missing`` (no statements from any source) ·
                   OR quality score is None AND valuation refused for a
                   *data-missing* guard (any refusal guard NOT in
                   ``final_verdict.NOT_APPLICABLE_GUARDS``, e.g. H3) ·
                   OR no fundamental check had any data at all
CAUTION            red or amber qualitative flag (keyword-matched news is a
                   prompt to read, not proof) · DEMANDING valuation posture ·
                   quality 30–50 ·
                   flags not yet checked · trailing net income < 0 with
                   positive equity · lenders (via sector_classification):
                   ROE < 0 · non-lenders where leverage applies: debt/equity
                   > 2× · non-lenders where cash flow applies: operating cash
                   flow < 0 while net income > 0
PASS               none of the above
=================  ==========================================================

Sector routing goes through ``analysis.sector_classification.SectorProfile``
(``is_financial``, ``leverage_warning_applies``, ``fcf_meaningful``) — banks,
NBFCs and insurers are never judged on debt/equity (deposits are not debt).

Pure: no Streamlit, no network, no session state.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Tuple

from analysis.final_verdict import NOT_APPLICABLE_GUARDS

PASS = "PASS"
CAUTION = "CAUTION"
FAIL = "FAIL"
INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
STATUSES = (PASS, CAUTION, FAIL, INSUFFICIENT_DATA)

# Flag severities the gate understands. "unchecked" = the flags were not looked
# up on this render (cold page: the live scrape runs later in the page).
FLAG_SEVERITIES = ("red", "amber", "green", "none", "unchecked")

QUALITY_FAIL_BELOW = 30.0
QUALITY_CAUTION_MAX = 50.0
DEBT_EQUITY_CAUTION = 2.0

INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


@dataclass
class BusinessGate:
    status: str                                   # one of STATUSES
    reasons: List[str] = field(default_factory=list)      # facts behind the status, worst first
    checked: List[str] = field(default_factory=list)      # checks that had data
    unavailable: List[str] = field(default_factory=list)  # checks that could not run

    @property
    def headline_reason(self) -> str:
        return self.reasons[0] if self.reasons else ""

    def as_dict(self) -> Dict[str, Any]:
        return {"status": self.status, "reasons": list(self.reasons),
                "checked": list(self.checked), "unavailable": list(self.unavailable)}


# ── helpers ────────────────────────────────────────────────────────────────────
def is_data_missing_guard(guard: Optional[str]) -> bool:
    """True when a valuation refusal means a needed figure was not found
    (H3-style), False when the data was found but the method does not apply."""
    return bool(guard) and guard not in NOT_APPLICABLE_GUARDS


def flag_severity(flag_dicts: Optional[Iterable[Dict[str, Any]]]) -> Tuple[str, str]:
    """Collapse QualitativeFlag dicts (``sentiment`` = red/amber/green) to one
    severity plus the headline of the worst flag. ``None`` → "unchecked";
    an empty list → "none". Legacy "negative"/"neutral" values are accepted."""
    if flag_dicts is None:
        return "unchecked", ""
    flags = list(flag_dicts)
    if not flags:
        return "none", ""
    rank = {"red": 3, "negative": 3, "amber": 2, "neutral": 2, "green": 1, "positive": 1}
    worst, worst_rank = None, 0
    for f in flags:
        r = rank.get(str(f.get("sentiment", "")).lower(), 0)
        if r > worst_rank:
            worst, worst_rank = f, r
    if worst is None:
        return "none", ""
    sev = {3: "red", 2: "amber", 1: "green"}[worst_rank]
    top = str(worst.get("headline") or worst.get("message") or "")[:80]
    return sev, top


def metrics_from_fundamentals(cf: Any = None, analytics: Optional[Dict] = None) -> Dict[str, float]:
    """Pull the raw figures the gate reads from objects the page already holds:
    a ``CompanyFundamentals`` (latest income / balance / cash-flow) and the
    ``analytics.compute_all`` dict. Duck-typed; missing pieces are skipped."""
    out: Dict[str, float] = {}

    def _put(key, val):
        if val is None:
            return
        try:
            out[key] = float(val)
        except (TypeError, ValueError):
            pass

    for getter, attr, key in (("latest_income", "net_income", "net_income"),
                              ("latest_balance", "total_equity", "total_equity"),
                              ("latest_cashflow", "operating_cash_flow", "operating_cash_flow")):
        fn = getattr(cf, getter, None) if cf is not None else None
        if callable(fn):
            try:
                stmt = fn()
            except Exception:
                stmt = None
            _put(key, getattr(stmt, attr, None) if stmt is not None else None)
    for src, key in (("debt_to_equity", "debt_to_equity"), ("roe", "roe")):
        a = analytics.get(src) if analytics else None
        if a is not None and getattr(a, "available", False):
            _put(key, getattr(a, "value", None))
    return out


def _inr_cr(x: float) -> str:
    cr = x / 1e7
    return f"{'-' if cr < 0 else ''}₹{abs(cr):,.0f} cr"


# ── the gate ───────────────────────────────────────────────────────────────────
def assess_business(*,
                    quality_score: Optional[float] = None,
                    valuation_posture: Optional[str] = None,
                    valuation_guard: Optional[str] = None,
                    flags_severity: Optional[str] = "unchecked",
                    fundamentals_missing: Optional[bool] = None,
                    sector_profile: Any = None,
                    metrics: Optional[Dict[str, float]] = None) -> BusinessGate:
    """Classify the business as PASS / CAUTION / FAIL / INSUFFICIENT_DATA.

    Inputs mirror what ``final_verdict.combine`` receives (quality score,
    valuation posture + guard, flag severity, fundamentals_missing) plus the
    sector profile and the raw metric dict from ``metrics_from_fundamentals``.
    """
    m = dict(metrics or {})
    fails: List[str] = []
    cautions: List[str] = []
    checked: List[str] = []
    unavailable: List[str] = []
    is_lender = bool(getattr(sector_profile, "is_financial", False))
    leverage_applies = (getattr(sector_profile, "leverage_warning_applies", True)
                        if sector_profile is not None else True)
    cash_applies = (getattr(sector_profile, "fcf_meaningful", True)
                    if sector_profile is not None else True)

    # Governance / news flags
    sev = (flags_severity or "unchecked").lower()
    flags_unchecked = sev == "unchecked"
    if flags_unchecked:
        unavailable.append("governance & news flags")
    else:
        checked.append("governance & news flags")
        # The flag's own headline is third-party text, so it stays on the
        # News & Flags tab; the reason names only the severity.
        # Red flags come from a short keyword match on NSE announcements /
        # news ("pledge", "resignation", "penalty" ...). That is a prompt to
        # read the item, not proof the business is broken, so it is CAUTION;
        # FAIL is reserved for hard balance-sheet facts.
        if sev == "red":
            cautions.insert(0, "red governance / news flag (see News & Flags)")
        elif sev == "amber":
            cautions.append("amber governance / news flag (see News & Flags)")

    # Fundamental quality score (0 is a real, worst-case score)
    if quality_score is None:
        unavailable.append("fundamental quality score")
    else:
        checked.append("fundamental quality score")
        q = float(quality_score)
        if q < QUALITY_FAIL_BELOW:
            fails.append(f"quality score {q:.0f}/100")
        elif q <= QUALITY_CAUTION_MAX:
            cautions.append(f"quality score {q:.0f}/100")

    # Net worth
    eq = m.get("total_equity")
    if eq is not None:
        checked.append("net worth")
        if eq < 0:
            fails.append(f"negative net worth (latest filing, {_inr_cr(eq)})")
    if valuation_guard == "H2-negative-equity" and not (eq is not None and eq < 0):
        fails.append("net worth not positive (latest filing)")
        if eq is None:
            checked.append("net worth")
    if eq is None and valuation_guard != "H2-negative-equity":
        unavailable.append("net worth")

    # Profitability
    ni = m.get("net_income")
    if ni is not None:
        checked.append("profitability")
        if ni < 0 and (eq is None or eq > 0):
            cautions.append(f"loss-making (latest net income {_inr_cr(ni)})")
    else:
        unavailable.append("profitability")

    # Balance-sheet quality, routed by sector profile
    if is_lender:
        roe = m.get("roe")
        if roe is not None:
            checked.append("return on equity")
            if roe < 0:
                cautions.append(f"return on equity negative ({roe:.1f}%)")
        else:
            unavailable.append("return on equity")
    else:
        de = m.get("debt_to_equity")
        if leverage_applies:
            if de is not None:
                checked.append("leverage")
                if de > DEBT_EQUITY_CAUTION and (eq is None or eq > 0):
                    cautions.append(f"debt/equity {de:.1f}×")
            else:
                unavailable.append("leverage")
        ocf = m.get("operating_cash_flow")
        if cash_applies:
            if ocf is not None:
                checked.append("cash flow")
                if ocf < 0 and ni is not None and ni > 0:
                    cautions.append("operating cash flow negative while reported profit is positive")
            else:
                unavailable.append("cash flow")

    # Valuation
    posture = valuation_posture or None
    if posture is None:
        unavailable.append("valuation")
    elif posture == INSUFFICIENT_EVIDENCE:
        unavailable.append("valuation")
    else:
        checked.append("valuation")
        if str(posture).upper().startswith("DEMANDING"):
            cautions.append("valuation reads demanding")

    # Listed last so a real finding leads the headline when there is one.
    if flags_unchecked:
        cautions.append("governance & news flags not yet checked on this load")

    # Status
    fundamental_checks = {"fundamental quality score", "net worth", "profitability",
                          "return on equity", "leverage", "cash flow", "valuation"}
    nothing_fundamental = not (fundamental_checks & set(checked))
    data_missing = bool(fundamentals_missing) or nothing_fundamental or (
        quality_score is None and posture == INSUFFICIENT_EVIDENCE
        and is_data_missing_guard(valuation_guard))
    if fails:
        return BusinessGate(FAIL, fails + cautions, checked, unavailable)
    if data_missing:
        if fundamentals_missing:
            why = "no company financials found in any source"
        elif nothing_fundamental:
            why = "no fundamental figures available on this load"
        else:
            why = "core fundamentals not found and no quality score"
        return BusinessGate(INSUFFICIENT_DATA, [why] + cautions, checked, unavailable)
    if cautions:
        return BusinessGate(CAUTION, cautions, checked, unavailable)
    return BusinessGate(PASS, ["no adverse finding in the checks that ran"], checked, unavailable)
