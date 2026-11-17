"""analysis/calls_scorecard.py — end-of-day check of the day's BUY calls.

Owner, 17 Nov: "at EOD all the new buy calls, how they performed, like the delivery digest
and intraday watchlist, would be a good way of analysing the app and its verdicts." This
grades each call on the day it was made: price at the call → close, the day's high / low,
whether the stop or target was touched, and the move against the Nifty. The 5- and
20-session grading stays where it is (verdict ledger / calibration report); day 1 is only
the first look, so the summary says so.

Pure: no Streamlit, no network, no DB. Callers pass plain numbers in.
"""
from __future__ import annotations

import math
from typing import Any, Dict, Iterable, List, Mapping, Optional


def _num(x: Any) -> Optional[float]:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) and v > 0 else None


def grade_call(*, entry: Any, close: Any, high: Any = None, low: Any = None,
               stop: Any = None, target: Any = None, nifty_pct: Any = None) -> Dict[str, Any]:
    """One BUY call's day: % move from the call price to the close, vs the Nifty, and whether
    the day's range touched the stop or target. A missing price leaves its field None."""
    e, c, h, lo = _num(entry), _num(close), _num(high), _num(low)
    sl, tp = _num(stop), _num(target)
    out: Dict[str, Any] = {"entry": e, "close": c, "high": h, "low": lo, "stop": sl, "target": tp,
                           "pct": None, "vs_nifty": None, "best_pct": None, "worst_pct": None,
                           "stop_hit": False, "target_hit": False}
    if e and c:
        out["pct"] = (c / e - 1) * 100
        try:
            n = float(nifty_pct)
            if math.isfinite(n):
                out["vs_nifty"] = out["pct"] - n
        except (TypeError, ValueError):
            pass
    if e and h:
        out["best_pct"] = (h / e - 1) * 100
    if e and lo:
        out["worst_pct"] = (lo / e - 1) * 100
    lo_seen = lo if lo is not None else c
    hi_seen = h if h is not None else c
    out["stop_hit"] = bool(sl and lo_seen and lo_seen <= sl)
    out["target_hit"] = bool(tp and hi_seen and hi_seen >= tp)
    return out


def grade_levels(levels: Mapping[str, Any], *, close: Any, high: Any = None,
                 low: Any = None) -> Dict[str, Any]:
    """Intraday watchlist: did the day break its upside / downside level, reach the next level
    above, and where did it close against them."""
    up, down, nxt = _num(levels.get("up")), _num(levels.get("down")), _num(levels.get("next_up"))
    c, h, lo = _num(close), _num(high), _num(low)
    hi_seen = h if h is not None else c
    lo_seen = lo if lo is not None else c
    out = {"up": up, "down": down, "next_up": nxt, "close": c,
           "broke_up": bool(up and hi_seen and hi_seen >= up),
           "reached_next": bool(nxt and hi_seen and hi_seen >= nxt),
           "broke_down": bool(down and lo_seen and lo_seen <= down),
           "closed": None}
    if c and up and down:
        out["closed"] = "above ▲" if c >= up else ("below ▼" if c <= down else "inside")
    return out


def summarize(graded: Iterable[Mapping[str, Any]], nifty_pct: Any = None) -> Dict[str, Any]:
    """Counts and averages over graded calls that have a move."""
    rows = [g for g in graded if g.get("pct") is not None]
    n = len(rows)
    out: Dict[str, Any] = {"n": n, "up": sum(1 for g in rows if g["pct"] > 0),
                           "avg_pct": None, "avg_vs_nifty": None, "beat_nifty": None,
                           "stops_hit": sum(1 for g in rows if g.get("stop_hit")),
                           "targets_hit": sum(1 for g in rows if g.get("target_hit")),
                           "nifty_pct": None}
    try:
        nf = float(nifty_pct)
        out["nifty_pct"] = nf if math.isfinite(nf) else None
    except (TypeError, ValueError):
        pass
    if n:
        out["avg_pct"] = sum(g["pct"] for g in rows) / n
        vs = [g["vs_nifty"] for g in rows if g.get("vs_nifty") is not None]
        if vs:
            out["avg_vs_nifty"] = sum(vs) / len(vs)
            out["beat_nifty"] = sum(1 for v in vs if v > 0)
    return out


def _pct(v: Optional[float]) -> str:
    return "n/a" if v is None else f"{v:+.1f}%"


def call_line(sym: str, g: Mapping[str, Any], *, when: str = "") -> str:
    """'SGMART 08:43 ₹983.40 → ₹1,013.35 +3.0% (vs Nifty +2.6) · range -0.7% / +3.9% · TARGET HIT'"""
    if g.get("entry") is None or g.get("close") is None:
        return f"{sym} — no closing price"
    s = f"{sym}{' ' + when if when else ''} ₹{g['entry']:,.2f} → ₹{g['close']:,.2f} {_pct(g['pct'])}"
    if g.get("vs_nifty") is not None:
        s += f" (vs Nifty {g['vs_nifty']:+.1f})"
    if g.get("worst_pct") is not None and g.get("best_pct") is not None:
        s += f" · day range {g['worst_pct']:+.1f}% / {g['best_pct']:+.1f}%"
    flags = [f for f, k in (("STOP HIT", "stop_hit"), ("TARGET HIT", "target_hit")) if g.get(k)]
    if flags:
        s += " · " + " · ".join(flags)
    return s


def levels_line(sym: str, g: Mapping[str, Any]) -> str:
    """'DHANBANK broke ▲ ₹43.65 · closed inside · ▼ ₹41.35 held'"""
    if g.get("close") is None:
        return f"{sym} — no closing price"
    bits = []
    if g.get("up"):
        bits.append(("reached the next level ₹{:,.2f}".format(g["next_up"]) if g.get("reached_next")
                     else f"broke ▲ ₹{g['up']:,.2f}") if g.get("broke_up") else f"▲ ₹{g['up']:,.2f} not reached")
    if g.get("down"):
        bits.append(f"broke ▼ ₹{g['down']:,.2f}" if g.get("broke_down") else f"▼ ₹{g['down']:,.2f} held")
    bits.append(f"closed {g['closed']} at ₹{g['close']:,.2f}" if g.get("closed") else f"closed ₹{g['close']:,.2f}")
    return f"{sym} " + " · ".join(bits)


def summary_line(s: Mapping[str, Any]) -> str:
    if not s.get("n"):
        return "No call had a closing price."
    bits = [f"{s['n']} call{'s' if s['n'] != 1 else ''} · {s['up']} up / {s['n'] - s['up']} down or flat",
            f"average {_pct(s['avg_pct'])}"]
    if s.get("nifty_pct") is not None:
        bits.append(f"Nifty {_pct(s['nifty_pct'])}")
    if s.get("avg_vs_nifty") is not None:
        bits.append(f"average vs Nifty {s['avg_vs_nifty']:+.1f} pts ({s['beat_nifty']} beat it)")
    bits.append(f"stops hit {s['stops_hit']} · targets hit {s['targets_hit']}")
    return " · ".join(bits)


def scorecard_rows(calls: List[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """Flatten graded calls for KV storage / a dataframe (Today page, later analysis)."""
    keep = ("symbol", "group", "when", "verdict", "score", "entry", "close", "pct", "vs_nifty",
            "best_pct", "worst_pct", "stop", "target", "stop_hit", "target_hit")
    return [{k: c.get(k) for k in keep} for c in calls]
