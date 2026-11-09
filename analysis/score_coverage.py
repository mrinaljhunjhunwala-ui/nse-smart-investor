"""analysis/score_coverage.py — which composite-score parts were NOT measured.

The composite score never invents data: when an input is missing, the part it
feeds is held at its neutral midpoint (or, for RS vs Nifty, simply left out)
instead of being scored. This module turns that into a short plain-language
list the UI can show next to the score, so a user can tell a measured 45/90
from one where several parts sat at neutral for lack of data.

Pure: no Streamlit, no I/O. Works on a CompositeScore or any duck-typed object
with the same attributes (older cached scores without ``coverage`` fall back
to the plain fields and the narrative sentences).
"""
from __future__ import annotations

from typing import List

# Plain-language line per coverage key (shown when that input was missing).
_LINES = {
    "sma200": ("Long-term trend (200-day average): under 200 trading days of history, "
               "so this check is held at neutral"),
    "momentum_history": ("Momentum: fewer than 25 trading days of history, "
                         "so the whole momentum part is held at neutral (12.5/25)"),
    "r60d": ("3-month return: under 3 months of history, "
             "so this part of momentum is held at neutral"),
    "rs_vs_nifty": ("Relative strength vs Nifty: benchmark data not available, "
                    "so momentum uses absolute returns only"),
    "sector_rank": ("Sector strength: sector not in the current sector ranking, "
                    "so it is held at neutral"),
}

_ORDER = ("sma200", "momentum_history", "r60d", "rs_vs_nifty", "sector_rank")

_UNSCORED_ACTIONS = ("DATA_UNAVAILABLE", "UNAVAILABLE")


def is_unscored(cs) -> bool:
    """True when the score object is a refusal sentinel (no score was computed)."""
    return str(getattr(cs, "action", "") or "").upper() in _UNSCORED_ACTIONS


def _coverage_from_fields(cs) -> dict:
    """Best-effort coverage for score objects without a ``coverage`` dict."""
    narrative = str(getattr(cs, "narrative", "") or "")
    fallback = bool(getattr(cs, "momentum_fallback", False))
    return {
        "sma200": "200-day average is not yet available" not in narrative,
        "momentum_history": not fallback,
        "r60d": (not fallback
                 and "3-month momentum component is scored neutral" not in narrative),
        "rs_vs_nifty": getattr(cs, "rs_score", None) is not None,
        "sector_rank": getattr(cs, "sector_rank", None) is not None,
    }


def neutralised_parts(cs) -> List[str]:
    """Plain-language list of score parts held at neutral / not measured
    because data was missing. Empty list = every part was measured.
    A sentinel (unscored) object returns an empty list — there is no score
    to qualify; callers should show the "not scored" message instead."""
    if cs is None or is_unscored(cs):
        return []
    cov = getattr(cs, "coverage", None)
    if not isinstance(cov, dict) or not cov:
        cov = _coverage_from_fields(cs)
    out: List[str] = []
    for key in _ORDER:
        if key == "r60d" and cov.get("momentum_history") is False:
            continue  # already covered by the whole-momentum line
        if cov.get(key) is False:
            out.append(_LINES[key])
    return out


def coverage_note(cs) -> str:
    """One compact markdown string for the UI ('' for an unscored object)."""
    if cs is None or is_unscored(cs):
        return ""
    parts = neutralised_parts(cs)
    if not parts:
        return "Data coverage · all score parts measured from available data."
    return ("Data coverage · not measured, for lack of data (no score is invented): "
            + "; ".join(parts) + ".")
