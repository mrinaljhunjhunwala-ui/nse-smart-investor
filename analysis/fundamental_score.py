"""
analysis/fundamental_score.py — a 0–100 Fundamental score built from published tests.

Replaces the crude ROE/ROCE/CAGR ``compute_quality_score`` on Analyze Stock only
(Quality Watch / portfolio pages keep that score). Three blocks, no other weights:

=====================  ======  =================================================
Block                  Points  Rule
=====================  ======  =================================================
Piotroski F-score       60     9 tests (Piotroski 2000), latest vs prior annual.
                               Points = 60 × passed / tests that ran.
Growth recency          20     revenue and net income, latest vs prior annual:
                               both up > 10% → 20 · both up → 14 · one up → 8 ·
                               both down → 0 · revenue down caps the block at 4.
Valuation sanity        20     non-lenders: PEG ≤ 1.5 → 20 · PE ≤ 25 → 14 ·
                               PE ≤ 40 → 8 · else 2. Lenders: P/B ≤ 1.5 with
                               ROE ≥ 12% → 20 · P/B ≤ 3 with ROE ≥ 12% → 14 ·
                               ROE ≥ 10% → 8 · else 2.
=====================  ======  =================================================

A block whose inputs are missing is excluded from the denominator (never scored
as 0). Final score = round(100 × earned / available); ``None`` when fewer than
60 points are available or fewer than two thirds of the applicable F-tests ran
(6 of 9 for operating companies, 4 of 6 for lenders).

Altman Z (non-lenders only) uses the ORIGINAL 1968 manufacturing-era
coefficients, untuned: Z = 1.2·WC/TA + 1.4·RE/TA + 3.3·EBIT/TA + 0.6·MVE/TL +
1.0·Sales/TA, zones < 1.8 distress · 1.8–3.0 grey · > 3.0 safe. A distress zone
caps the final score at 35. Market value of equity is the caller's
``market_cap``, else ``ratios.market_cap``, else P/E × latest net income (a
stated proxy). Total liabilities fall back to total assets − equity.

Lenders (``SectorProfile.is_financial`` from analysis.sector_classification)
skip Altman Z and the three F-tests that read deposits as debt or need a gross
margin / current ratio (LT debt/assets, current ratio, gross margin).

Implementation notes: ROA uses year-end total assets for both years (only two
balance sheets are needed); "no new shares" reads ``IncomeStatement.shares_diluted``
(up > 1% fails); LT debt falls back to total debt when LT debt is not reported.

Every reason is a fact ("OCF < net income", "PE 48 — above 40"), never advice.
Pure: no Streamlit, no network, no session state.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

F_POINTS = 60.0
GROWTH_POINTS = 20.0
VALUATION_POINTS = 20.0
MIN_POINTS_AVAILABLE = 60.0
DISTRESS_CAP = 35

Z_DISTRESS_BELOW = 1.8
Z_SAFE_ABOVE = 3.0

# Test names, in Piotroski's order.
T_ROA = "ROA > 0"
T_OCF = "Operating cash flow > 0"
T_DROA = "ROA up vs prior year"
T_ACCRUAL = "OCF > net income"
T_LEVER = "LT debt / assets down"
T_LIQUID = "Current ratio up"
T_SHARES = "No new shares issued"
T_MARGIN = "Gross margin up"
T_TURN = "Asset turnover up"
F_TESTS = (T_ROA, T_OCF, T_DROA, T_ACCRUAL, T_LEVER, T_LIQUID, T_SHARES, T_MARGIN, T_TURN)
LENDER_SKIPPED = (T_LEVER, T_LIQUID, T_MARGIN)

FCheck = Tuple[str, Optional[bool], str]


@dataclass
class FundamentalScore:
    score: Optional[int] = None
    f_score: Optional[int] = None                 # tests passed
    f_checks: List[FCheck] = field(default_factory=list)   # (name, passed|None, detail)
    growth_pts: Optional[float] = None
    valuation_pts: Optional[float] = None
    z_score: Optional[float] = None
    z_zone: Optional[str] = None                  # distress / grey / safe / n/a (...)
    lender: bool = False
    missing: List[str] = field(default_factory=list)
    as_of: Optional[date] = None                  # latest annual period_end
    reasons: List[str] = field(default_factory=list)
    f_tests_run: int = 0
    f_tests_applicable: int = 9

    @property
    def f_label(self) -> str:
        """'F-score 6/8 (1 test no data)' — the denominator is the tests that ran."""
        if self.f_score is None:
            return "F-score n/a"
        nodata = self.f_tests_applicable - self.f_tests_run
        bits = []
        if nodata:
            bits.append(f"{nodata} test{'s' if nodata > 1 else ''} no data")
        if self.lender:
            bits.append(f"{9 - self.f_tests_applicable} not applicable to lenders")
        tail = f" ({', '.join(bits)})" if bits else ""
        return f"F-score {self.f_score}/{self.f_tests_run}{tail}"

    @property
    def z_label(self) -> str:
        if self.z_zone is None:
            return "Z n/a"
        return f"Z {self.z_zone}"

    @property
    def summary(self) -> str:
        """'Fundamentals 72/100 · F-score 7/9 · Z safe' (or the not-enough-data line)."""
        if self.score is None:
            return "Fundamentals: not enough data (needs two annual statements)"
        return f"Fundamentals {self.score}/100 · {self.f_label} · {self.z_label}"

    def as_dict(self) -> Dict[str, Any]:
        return {"score": self.score, "f_score": self.f_score,
                "f_checks": [list(c) for c in self.f_checks],
                "growth_pts": self.growth_pts, "valuation_pts": self.valuation_pts,
                "z_score": self.z_score, "z_zone": self.z_zone, "lender": self.lender,
                "missing": list(self.missing),
                "as_of": str(self.as_of) if self.as_of else None,
                "reasons": list(self.reasons), "f_tests_run": self.f_tests_run,
                "f_tests_applicable": self.f_tests_applicable}


# ── helpers ────────────────────────────────────────────────────────────────────
def _num(x) -> Optional[float]:
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _div(a: Optional[float], b: Optional[float]) -> Optional[float]:
    if a is None or b is None or b == 0:
        return None
    return a / b


def _pend(row) -> Optional[date]:
    per = getattr(row, "period", None)
    return getattr(per, "period_end", None) if per is not None else None


def _annual(rows) -> List[Any]:
    out = [r for r in (rows or [])
           if _pend(r) is not None
           and getattr(getattr(r, "period", None), "period_type", "annual") == "annual"]
    return sorted(out, key=_pend, reverse=True)


def _match(rows: List[Any], d: Optional[date], tol_days: int = 45):
    """The row whose period_end is d (or the nearest within tol_days of it)."""
    if d is None:
        return None
    best, gap = None, None
    for r in rows:
        g = abs((_pend(r) - d).days)
        if g <= tol_days and (gap is None or g < gap):
            best, gap = r, g
    return best


def _g(row, attr) -> Optional[float]:
    return _num(getattr(row, attr, None)) if row is not None else None


def _pct(x: float) -> str:
    return f"{x * 100:.1f}%"


def _cr(x: float) -> str:
    cr = x / 1e7
    return f"{'-' if cr < 0 else ''}₹{abs(cr):,.0f} cr"


def _analytic(analytics: Optional[Dict], key: str, cf) -> Optional[float]:
    r = (analytics or {}).get(key)
    if r is None and cf is not None:
        try:
            from analysis.fundamentals import analytics as _fa
            r = getattr(_fa, key)(cf)
        except Exception:
            r = None
    if r is not None and getattr(r, "available", False):
        return _num(getattr(r, "value", None))
    return None


def _extract(inc, bal, cfl) -> Dict[str, Optional[float]]:
    return {
        "rev": _g(inc, "revenue"), "cogs": _g(inc, "cost_of_revenue"),
        "gp": _g(inc, "gross_profit"), "ni": _g(inc, "net_income"),
        "ebit": _g(inc, "operating_income"), "sh": _g(inc, "shares_diluted"),
        "ta": _g(bal, "total_assets"), "ca": _g(bal, "current_assets"),
        "cl": _g(bal, "current_liabilities"), "tl": _g(bal, "total_liabilities"),
        "ltd": _g(bal, "long_term_debt"), "td": _g(bal, "total_debt"),
        "eq": _g(bal, "total_equity"), "re": _g(bal, "retained_earnings"),
        "ocf": _g(cfl, "operating_cash_flow"),
    }


# ── blocks ─────────────────────────────────────────────────────────────────────
def _f_checks(cur: Dict[str, Optional[float]], pri: Dict[str, Optional[float]],
              lender: bool) -> List[FCheck]:
    checks: List[FCheck] = []

    def add(name, passed, detail):
        if lender and name in LENDER_SKIPPED:
            return
        checks.append((name, passed, detail))

    roa_t = _div(cur["ni"], cur["ta"])
    roa_p = _div(pri["ni"], pri["ta"])
    add(T_ROA, None if roa_t is None else roa_t > 0,
        "no data: net income / total assets" if roa_t is None else f"ROA {_pct(roa_t)}")
    ocf = cur["ocf"]
    add(T_OCF, None if ocf is None else ocf > 0,
        "no data: operating cash flow" if ocf is None else f"OCF {_cr(ocf)}")
    both_roa = roa_t is not None and roa_p is not None
    add(T_DROA, roa_t > roa_p if both_roa else None,
        f"ROA {_pct(roa_t)} vs {_pct(roa_p)}" if both_roa else "no data: prior-year ROA")
    both_acc = ocf is not None and cur["ni"] is not None
    add(T_ACCRUAL, ocf > cur["ni"] if both_acc else None,
        f"OCF {_cr(ocf)} vs net income {_cr(cur['ni'])}" if both_acc
        else "no data: OCF or net income")

    lt_t, lt_p, lt_note = cur["ltd"], pri["ltd"], ""
    if lt_t is None or lt_p is None:
        lt_t, lt_p, lt_note = cur["td"], pri["td"], " (total debt; LT debt not reported)"
    lv_t, lv_p = _div(lt_t, cur["ta"]), _div(lt_p, pri["ta"])
    if lv_t is None or lv_p is None:
        add(T_LEVER, None, "no data: long-term debt / total assets")
    else:
        add(T_LEVER, lv_t < lv_p or (lv_t == 0 and lv_p == 0),
            f"{_pct(lv_t)} vs {_pct(lv_p)}{lt_note}")

    cr_t, cr_p = _div(cur["ca"], cur["cl"]), _div(pri["ca"], pri["cl"])
    both_cr = cr_t is not None and cr_p is not None
    add(T_LIQUID, cr_t > cr_p if both_cr else None,
        f"{cr_t:.2f}× vs {cr_p:.2f}×" if both_cr
        else "no data: current assets / current liabilities")

    sh_t, sh_p = cur["sh"], pri["sh"]
    if sh_t is None or sh_p is None or sh_p <= 0:
        add(T_SHARES, None, "no data: diluted shares")
    else:
        add(T_SHARES, sh_t <= sh_p * 1.01, f"diluted shares {(sh_t / sh_p - 1) * 100:+.1f}%")

    def gm(d):
        gp = d["gp"]
        if gp is None and d["rev"] is not None and d["cogs"] is not None:
            gp = d["rev"] - d["cogs"]
        return _div(gp, d["rev"])
    gm_t, gm_p = gm(cur), gm(pri)
    both_gm = gm_t is not None and gm_p is not None
    add(T_MARGIN, gm_t > gm_p if both_gm else None,
        f"{_pct(gm_t)} vs {_pct(gm_p)}" if both_gm else "no data: gross profit / revenue")

    at_t, at_p = _div(cur["rev"], cur["ta"]), _div(pri["rev"], pri["ta"])
    both_at = at_t is not None and at_p is not None
    add(T_TURN, at_t > at_p if both_at else None,
        f"{at_t:.2f}× vs {at_p:.2f}×" if both_at else "no data: revenue / total assets")
    return checks


_FAIL_FACT = {
    T_ROA: "ROA not positive",
    T_OCF: "operating cash flow not positive",
    T_DROA: "ROA lower than prior year",
    T_ACCRUAL: "OCF < net income",
    T_LEVER: "LT debt / assets up",
    T_LIQUID: "current ratio down",
    T_SHARES: "diluted shares up more than 1%",
    T_MARGIN: "gross margin down",
    T_TURN: "asset turnover down",
}


def _growth(cur, pri, reasons: List[str]) -> Optional[float]:
    r_t, r_p, n_t, n_p = cur["rev"], pri["rev"], cur["ni"], pri["ni"]
    if None in (r_t, r_p, n_t, n_p):
        return None

    def chg(t, p):
        return (t / p - 1.0) if p > 0 else None
    rg, ng = chg(r_t, r_p), chg(n_t, n_p)
    r_up, n_up = r_t > r_p, n_t > n_p
    if r_up and n_up and rg is not None and ng is not None and rg > 0.10 and ng > 0.10:
        pts = 20.0
    elif r_up and n_up:
        pts = 14.0
    elif r_up or n_up:
        pts = 8.0
    else:
        pts = 0.0
    if r_t < r_p:
        pts = min(pts, 4.0)
    r_txt = (f"revenue {rg * 100:+.1f}%" if rg is not None
             else ("revenue up" if r_up else "revenue not up"))
    n_txt = (f"net income {ng * 100:+.1f}%" if ng is not None
             else ("net income up from a loss" if n_up else "net income not up"))
    reasons.append(f"{r_txt}, {n_txt} (latest vs prior annual)")
    return pts


def _valuation(cf, analytics, lender: bool, reasons: List[str],
               missing: List[str]) -> Optional[float]:
    ratios = getattr(cf, "ratios", None)
    if lender:
        pb = _num(getattr(ratios, "pb", None))
        pb = pb if pb is not None and pb > 0 else None
        roe = _analytic(analytics, "roe", cf)
        if pb is None or roe is None:
            missing.append("P/B and ROE (lender valuation)")
            return None
        if pb <= 1.5 and roe >= 12:
            pts = 20.0
        elif pb <= 3 and roe >= 12:
            pts = 14.0
        elif roe >= 10:
            pts = 8.0
        else:
            pts = 2.0
        reasons.append(f"P/B {pb:.1f}, ROE {roe:.1f}%")
        return pts
    pe = _num(getattr(ratios, "pe", None))
    if pe is None or pe <= 0:
        missing.append("P/E (positive)")
        return None
    eps_g = _analytic(analytics, "eps_cagr", cf)
    peg = pe / eps_g if eps_g is not None and eps_g > 0 else None
    if peg is not None and peg <= 1.5:
        reasons.append(f"PEG {peg:.2f} (PE {pe:.0f} ÷ EPS CAGR {eps_g:.0f}%) — at or below 1.5")
        return 20.0
    peg_txt = f", PEG {peg:.2f}" if peg is not None else ""
    if pe <= 25:
        reasons.append(f"PE {pe:.0f} — at or below 25{peg_txt}")
        return 14.0
    if pe <= 40:
        reasons.append(f"PE {pe:.0f} — 25 to 40{peg_txt}")
        return 8.0
    reasons.append(f"PE {pe:.0f} — above 40{peg_txt}")
    return 2.0


def _altman(cf, cur, market_cap: Optional[float]) -> Tuple[Optional[float], str, List[str]]:
    ta = cur["ta"]
    wc = (cur["ca"] - cur["cl"]) if cur["ca"] is not None and cur["cl"] is not None else None
    tl = cur["tl"]
    if tl is None and ta is not None and cur["eq"] is not None:
        tl = ta - cur["eq"]
    ratios = getattr(cf, "ratios", None)
    mve = _num(market_cap)
    if mve is None:
        mve = _num(getattr(ratios, "market_cap", None))
    if mve is None:
        pe = _num(getattr(ratios, "pe", None))
        if pe is not None and pe > 0 and cur["ni"] is not None and cur["ni"] > 0:
            mve = pe * cur["ni"]
    need = {"total assets": ta, "working capital": wc, "retained earnings": cur["re"],
            "EBIT": cur["ebit"], "market value of equity": mve, "total liabilities": tl,
            "revenue": cur["rev"]}
    absent = [k for k, v in need.items() if v is None]
    if not absent and (not ta or not tl):
        absent = ["non-zero total assets / liabilities"]
    if absent:
        return None, "n/a (no data: " + ", ".join(absent) + ")", absent
    z = (1.2 * wc / ta + 1.4 * cur["re"] / ta + 3.3 * cur["ebit"] / ta
         + 0.6 * mve / tl + 1.0 * cur["rev"] / ta)
    zone = "distress" if z < Z_DISTRESS_BELOW else ("safe" if z > Z_SAFE_ABOVE else "grey")
    return round(z, 2), zone, []


# ── public API ─────────────────────────────────────────────────────────────────
def compute_fundamental_score(cf: Any, sector_profile: Any = None,
                              analytics: Optional[Dict] = None,
                              market_cap: Optional[float] = None) -> FundamentalScore:
    """Score a ``CompanyFundamentals`` (annual statements, newest-first).

    ``sector_profile`` is a ``sector_classification.SectorProfile`` (lender routing via
    ``is_financial``); ``analytics`` is ``fundamentals.analytics.compute_all(cf)`` when
    the caller already has it (ROE / EPS CAGR are recomputed from ``cf`` otherwise).
    """
    lender = bool(getattr(sector_profile, "is_financial", False))
    applicable = 9 - (len(LENDER_SKIPPED) if lender else 0)
    out = FundamentalScore(lender=lender, f_tests_applicable=applicable)
    if lender:
        out.z_zone = "n/a (lender)"

    incs = _annual(getattr(cf, "income_statements", None)) if cf is not None else []
    if not incs:
        out.missing.append("annual income statements")
        out.reasons.append("no annual statements found")
        return out
    d_t = _pend(incs[0])
    out.as_of = d_t
    bals = _annual(getattr(cf, "balance_sheets", None))
    cfls = _annual(getattr(cf, "cash_flows", None))
    cur = _extract(incs[0], _match(bals, d_t), _match(cfls, d_t))
    prior = [r for r in incs[1:] if 270 <= (d_t - _pend(r)).days <= 460]
    if not prior:
        out.missing.append("prior annual statement (needs two annual statements)")
        out.reasons.append("only one annual statement found")
        if not lender:
            out.z_score, out.z_zone, _ = _altman(cf, cur, market_cap)
        return out
    d_p = _pend(prior[0])
    pri = _extract(prior[0], _match(bals, d_p), _match(cfls, d_p))

    # 1 · Piotroski
    out.f_checks = _f_checks(cur, pri, lender)
    ran = [c for c in out.f_checks if c[1] is not None]
    out.f_tests_run = len(ran)
    out.missing.extend(f"{n} — {d}" for n, p, d in out.f_checks if p is None)
    need = math.ceil(applicable * 2 / 3)
    if not lender:
        out.z_score, out.z_zone, z_absent = _altman(cf, cur, market_cap)
    else:
        z_absent = []
    if len(ran) < need:
        out.reasons.append(f"only {len(ran)} of {applicable} F-score tests had data "
                           f"(needs {need})")
        return out
    passed = sum(1 for c in ran if c[1])
    out.f_score = passed
    earned, available = F_POINTS * passed / len(ran), F_POINTS
    reasons: List[str] = [f"F-score {passed}/{len(ran)}"]
    reasons.extend(_FAIL_FACT[n] for n, p, _ in out.f_checks if p is False)

    # 2 · growth
    out.growth_pts = _growth(cur, pri, reasons)
    if out.growth_pts is None:
        out.missing.append("revenue / net income for both years (growth)")
    else:
        earned += out.growth_pts
        available += GROWTH_POINTS

    # 3 · valuation
    out.valuation_pts = _valuation(cf, analytics, lender, reasons, out.missing)
    if out.valuation_pts is not None:
        earned += out.valuation_pts
        available += VALUATION_POINTS

    # 4 · Altman Z
    if z_absent:
        out.missing.append("Altman Z inputs: " + ", ".join(z_absent))

    if available < MIN_POINTS_AVAILABLE:
        out.reasons = reasons
        return out
    score = round(100.0 * earned / available)
    if out.z_zone == "distress":
        capped = score > DISTRESS_CAP
        score = min(score, DISTRESS_CAP)
        reasons.insert(0, f"Altman Z {out.z_score:.2f} — distress zone"
                          + (f" (score capped at {DISTRESS_CAP})" if capped else ""))
    elif out.z_score is not None:
        reasons.append(f"Altman Z {out.z_score:.2f} — {out.z_zone} zone")
    out.score = int(score)
    out.reasons = reasons
    return out


def f_check_rows(fs: FundamentalScore) -> List[Dict[str, str]]:
    """Table rows for the page: the F-checks, then growth and valuation."""
    mark = {True: "pass", False: "fail", None: "no data"}
    rows = [{"Test": n, "Result": mark[p], "Detail": d} for n, p, d in fs.f_checks]
    if fs.lender:
        rows += [{"Test": n, "Result": "not applicable",
                  "Detail": "lender (deposits are not debt)"} for n in LENDER_SKIPPED]
    rows.append({"Test": "Growth recency (20 pts)",
                 "Result": "no data" if fs.growth_pts is None else f"{fs.growth_pts:.0f} pts",
                 "Detail": "revenue & net income, latest vs prior annual"})
    rows.append({"Test": "Valuation sanity (20 pts)",
                 "Result": "no data" if fs.valuation_pts is None else f"{fs.valuation_pts:.0f} pts",
                 "Detail": "P/B × ROE (lender)" if fs.lender else "PEG / P/E bands"})
    return rows
