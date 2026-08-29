"""dashboard/shared/pick_freshness.py — shared helpers for pick-card freshness.

Extracted from dashboard/pages/02_command_centre.py so any page rendering a
pick card (Command Centre Top Picks, My Watchlist, Deep Dive live-snapshot,
Tomorrow's Watchlist, ...) uses the same re-anchoring + cost logic.

Two things live here:

  COST_ROUNDTRIP_PCT      cost floor for R:R adjustment. MUST stay in sync
                          with research.score_efficacy.COST_ROUNDTRIP_PCT
                          — a test in tests/test_command_centre_helpers.py
                          enforces that.

  reanchor_levels(...)    given a scored (entry, sl, tp) triangle and a
                          current live price, returns a dict with:
                              entry / sl / tp    re-anchored if drift > 0.5%
                              rr / rr_net        gross + cost-adjusted R:R
                              drift_pct          how far live has moved
                              reanchored         True if levels shifted
                          Purely deterministic — no I/O, no Streamlit
                          dependency, testable in isolation.

  compose_finalverdict_for_card(pick, tqs)   given a Top Picks / Watchlist
                          card dict (has "score", "action", optionally
                          "horizon_hint") and an optional TQS float,
                          returns a FinalVerdict configured for a horizon
                          derived from the card's own horizon_hint (short
                          for "Swing", medium otherwise). Used by the
                          card-render code to surface the ONE-verdict
                          answer alongside the composite score.
"""
from __future__ import annotations

from typing import Any, Dict, Optional


# Keep in sync with research.score_efficacy.COST_ROUNDTRIP_PCT
COST_ROUNDTRIP_PCT       = 0.30
LIVE_DRIFT_THRESHOLD_PCT = 0.5


def reanchor_levels(entry: float, sl: float, tp: float,
                    live_price: "float | None") -> Dict[str, Any]:
    """Re-anchor a scored (entry, sl, tp) triangle to the current live price.

    * If no live price is available, return the scored triangle unchanged
      and just add cost-adjusted R:R for honesty.
    * If live price is within LIVE_DRIFT_THRESHOLD_PCT of the scored entry,
      return the scored triangle unchanged (the drift isn't worth shifting
      levels for).
    * Otherwise, preserve the ATR-based RISK and REWARD distances (entry−sl,
      tp−entry) and re-anchor both to the live price — the same fix
      analysis/score.py already applies to the Analyze Stock page's live
      overlay ("entry/SL/TP staleness" fix).

    Returns a dict with entry / sl / tp / rr / rr_net / drift_pct /
    reanchored keys. Callers should paste it directly into the card render.
    """
    if not entry or entry <= 0:
        return {"entry": entry, "sl": sl, "tp": tp, "rr": 0.0, "rr_net": 0.0,
                "drift_pct": 0.0, "reanchored": False}

    if not live_price or live_price <= 0:
        risk = max(entry - sl, 0.01) if sl else 0.01
        reward = max(tp - entry, 0.0) if tp else 0.0
        rr = round(reward / risk, 2) if risk > 0 else 0.0
        cost_abs = entry * COST_ROUNDTRIP_PCT / 100
        rr_net = round(max(0.0, reward - cost_abs) / max(risk + cost_abs, 0.01), 2)
        return {"entry": entry, "sl": sl, "tp": tp, "rr": rr, "rr_net": rr_net,
                "drift_pct": 0.0, "reanchored": False}

    drift_pct = (live_price - entry) / entry * 100
    if abs(drift_pct) < LIVE_DRIFT_THRESHOLD_PCT:
        risk = max(entry - sl, 0.01) if sl else 0.01
        reward = max(tp - entry, 0.0) if tp else 0.0
        rr = round(reward / risk, 2) if risk > 0 else 0.0
        cost_abs = entry * COST_ROUNDTRIP_PCT / 100
        rr_net = round(max(0.0, reward - cost_abs) / max(risk + cost_abs, 0.01), 2)
        return {"entry": entry, "sl": sl, "tp": tp, "rr": rr, "rr_net": rr_net,
                "drift_pct": round(drift_pct, 2), "reanchored": False}

    risk_dist   = entry - sl if sl > 0 else 0
    reward_dist = tp - entry if tp > 0 else 0
    new_entry = round(live_price, 2)
    new_sl    = round(live_price - risk_dist, 2) if risk_dist > 0 else sl
    new_tp    = round(live_price + reward_dist, 2) if reward_dist > 0 else tp
    risk = max(new_entry - new_sl, 0.01) if new_sl else 0.01
    reward = max(new_tp - new_entry, 0.0) if new_tp else 0.0
    rr = round(reward / risk, 2) if risk > 0 else 0.0
    cost_abs = new_entry * COST_ROUNDTRIP_PCT / 100
    rr_net = round(max(0.0, reward - cost_abs) / max(risk + cost_abs, 0.01), 2)
    return {"entry": new_entry, "sl": new_sl, "tp": new_tp, "rr": rr, "rr_net": rr_net,
            "drift_pct": round(drift_pct, 2), "reanchored": True}


def _horizon_for_pick(pick: Dict[str, Any]) -> str:
    """
    Map a Top Picks / Watchlist card's `horizon` hint to a FinalVerdict
    horizon lens. Composite score labels these "Swing (3-10 trading days)"
    or "Positional (2-6 weeks)" today (see analysis/score._pick_horizon).
    A card without a horizon hint gets the default medium lens.
    """
    hint = str(pick.get("horizon", "") or "").lower()
    if "swing" in hint or "day" in hint:
        return "short"
    if "positional" in hint or "week" in hint:
        return "medium"
    if "invest" in hint or "long" in hint or "month" in hint:
        return "long"
    return "medium"


def compose_finalverdict_for_card(pick: Dict[str, Any],
                                  tqs: Optional[float] = None,
                                  *,
                                  log_source: Optional[str] = "shadow_auto"):
    """
    Build a FinalVerdict for one pick card, using its composite score /
    action + optional TQS. Horizon is inferred from the pick's own
    horizon hint so a "Swing (3-10 trading days)" pick is scored on the
    short lens (technical dominant) and a positional/investment pick on
    medium/long. Returns the FinalVerdict object.

    SHADOW LEDGER (Tier 1 #2) — every card compose call also silently
    persists the verdict to verdict_log with source=`log_source` (default
    "shadow_auto") so we later know which BUY/STRONG BUY signals the app
    surfaced whether or not the user paper-traded them. Pass log_source=None
    to opt a specific call out of logging (e.g. re-renders inside the same
    session). All failure paths are swallowed — logging never breaks a UI
    render.
    """
    from analysis.final_verdict import combine
    fv = combine(
        composite_score=pick.get("score"),
        composite_action=pick.get("action"),
        tqs=tqs,
        horizon=_horizon_for_pick(pick),
    )
    if log_source:
        try:
            from analysis.verdict_ledger import log_verdict as _vl_log
            _t = pick.get("ticker") or pick.get("symbol")
            _px = pick.get("entry") or pick.get("price") or pick.get("close")
            if _t:
                _t = str(_t).upper()
                if not _t.endswith(".NS") and not _t.endswith(".BO"):
                    _t = _t + ".NS"
                _score = pick.get("score")
                _vl_log(ticker=_t, final_verdict=fv,
                        entry_price=(float(_px) if _px else None),
                        composite_score=(float(_score) if _score is not None else None),
                        source=log_source,
                        horizon=_horizon_for_pick(pick))
        except Exception:
            # Ledger is a background concern — never break a card render
            pass
    return fv
