"""analysis/quality_watch.py — pure Quality Score (0-100) for page 19.

Moved out of dashboard/pages/19_quality_watch.py (audit 2026-09-24) so it is
unit-testable and so ratio selection routes through
analysis/sector_classification.py.

Components (unchanged weights):
  valuation posture   40   (POSTURE_POINTS)
  confidence          15
  governance safety   25   (25 - 8*red - 3*amber, floored at 0)
  quality ratios      20   (sector-aware; rescaled to available metrics)

FIX QW-POSTURE — the page's map lacked SUPPORTED_BY_GROWTH_AND_QUALITY /
SUPPORTED_BY_GROWTH / SUPPORTED_BY_QUALITY (emitted by
valuation_decision.py), so they fell to the default 10 — BELOW every
DEMANDING_* posture (15). Every posture the engine can emit is now mapped
and every SUPPORTED_* ranks above every DEMANDING_*.

FIX QW-SECTOR — banks/NBFCs/insurers are scored on ROE + P/B; ROCE and
debt/equity (deposits are not "debt") are excluded for financials.

Descriptive score only — not a recommendation.
"""
from __future__ import annotations

from typing import Dict, Optional, Tuple

from analysis.fundamentals import valuation_decision as _vd
from analysis.sector_classification import SectorProfile, quality_ratio_keys

POSTURE_POINTS: Dict[str, int] = {
    _vd.SUPPORTED_BY_GROWTH_AND_QUALITY: 40,
    _vd.REASONABLE: 40,
    _vd.SUPPORTED_BY_GROWTH: 35,
    _vd.SUPPORTED_BY_QUALITY: 35,
    _vd.SUPPORTED_BY_ROE: 35,
    _vd.DEMANDING_VS_ROE: 15,
    _vd.DEMANDING_VS_RETURNS: 15,
    _vd.DEMANDING_VS_GROWTH: 15,
    _vd.INSUFFICIENT_EVIDENCE: 10,  # unknown isn't "bad" — neutral-low, not zero
}
UNKNOWN_POSTURE_POINTS = 10
CONFIDENCE_POINTS: Dict[str, int] = {"high": 15, "medium": 10, "low": 5, "none": 0}

# Per-metric (max points, tier function) — tiers return points <= max.
_RATIO_RULES = {
    "roe": (7, lambda v: 7 if v > 0.15 else (4 if v > 0.10 else 1)),
    "roce": (7, lambda v: 7 if v > 0.15 else (4 if v > 0.10 else 1)),
    "debt_to_equity": (6, lambda v: 6 if v < 0.5 else (3 if v < 1.0 else 0)),
    # P/B for financials: lower multiple for the same ROE = better supported.
    "pb": (6, lambda v: 6 if v < 2.0 else (3 if v < 3.5 else 1)),
}


def compute_quality_score(posture: Optional[str], confidence: Optional[str],
                          red_flags: int, amber_flags: int, *,
                          roe: Optional[float] = None, roce: Optional[float] = None,
                          debt_to_equity: Optional[float] = None,
                          pb: Optional[float] = None,
                          sector_profile: Optional[SectorProfile] = None) -> Tuple[int, dict]:
    """Return (score_0_to_100, breakdown). Never raises.

    Missing ratios are rescaled out (FIX QW1): "unknown" reduces coverage,
    it is not scored as the worst reading. If no applicable ratio is
    available, quality_ratios is a neutral-low 10/20.
    breakdown["ratios_used"] lists the sector-applicable ratios that fed the
    score (not summed into the total).
    """
    breakdown: dict = {}
    breakdown["valuation_posture"] = POSTURE_POINTS.get(posture or "", UNKNOWN_POSTURE_POINTS)
    breakdown["confidence"] = CONFIDENCE_POINTS.get(confidence or "", 0)
    breakdown["governance_safety"] = max(0, 25 - int(red_flags or 0) * 8 - int(amber_flags or 0) * 3)

    values = {"roe": roe, "roce": roce, "debt_to_equity": debt_to_equity, "pb": pb}
    q = 0.0
    weight = 0.0
    used = []
    for key in quality_ratio_keys(sector_profile):
        v = values.get(key)
        if v is None:
            continue
        try:
            fv = float(v)
        except (TypeError, ValueError):
            continue
        if fv != fv:  # NaN
            continue
        mx, fn = _RATIO_RULES[key]
        q += fn(fv)
        weight += mx
        used.append(key)
    breakdown["quality_ratios"] = round(min(20.0, q * 20.0 / weight)) if weight > 0 else 10

    total = (breakdown["valuation_posture"] + breakdown["confidence"]
             + breakdown["governance_safety"] + breakdown["quality_ratios"])
    breakdown["ratios_used"] = used
    return round(total), breakdown
