"""
dashboard/shared/ui_components.py — shared visual building blocks.

Sprint B: the app renders very similar UI on 6+ pages (Command Centre Top
Picks, My Watchlist, Analyze Stock hero, Deep Dive, Tomorrow's Watchlist,
etc.) but each page hand-rolled its own HTML with subtly-different colors,
font sizes, and inconsistent inclusion of freshness / confidence / cost
context. This module is the single place all of them can pull from so the
same concept LOOKS the same everywhere without a mega-component refactor.

Every function returns a self-contained HTML string. Callers stamp it into
st.markdown(..., unsafe_allow_html=True). Nothing here touches Streamlit —
these are pure string builders, testable in isolation.
"""
from __future__ import annotations

from typing import Optional


# ─────────────────────────────────────────────────────────────────────────────
# Single source of truth for verdict / action / regime colors
# ─────────────────────────────────────────────────────────────────────────────
# The previous code had slightly-different green / amber / red per page; users
# saw the same STRONG BUY as one shade of green on Top Picks and a different
# shade on Watchlist. These constants are the palette every page should pull
# from. Colors chosen for AA-contrast against a dark background (#0d1526).

COLORS = {
    "STRONG BUY": "#26a69a",   # teal-green — strongest bull
    "BUY":        "#4CAF50",   # solid green
    "WATCH":      "#2196F3",   # blue (was WATCHLIST in some places)
    "WATCHLIST":  "#2196F3",
    "HOLD":       "#9E9E9E",   # neutral grey
    "CAUTION":    "#FF9800",   # amber
    "EXIT":       "#ef5350",   # solid red
    "AVOID":      "#B71C1C",   # deeper red (final-verdict veto)
    "UNAVAILABLE": "#555555",
}

REGIME_COLORS = {
    "trend_up":   "#26a69a",
    "trend_down": "#ef5350",
    "range":      "#FFC107",
    "risk_off":   "#B71C1C",
    "unknown":    "#666666",
}

REGIME_EMOJI = {
    "trend_up": "📈", "trend_down": "📉", "range": "⇄",
    "risk_off": "🚨", "unknown": "❓",
}

REGIME_NOTES = {
    "trend_up":
        "Trending up — momentum-heavy signals have historically hit ~60%",
    "trend_down":
        "Trending down — contrarian BUYs have outperformed, momentum signals have not",
    "range":
        "Range-bound — historical BUY hit rate here is ~46% vs 55%+ in trending regimes. "
        "Halve size or wait",
    "risk_off":
        "Risk-off (VIX ≥ 22) — historically all BUYs paid 5-12% but you have to buy the fear",
    "unknown":
        "Regime undetermined — data unavailable",
}


def action_color(action_or_verdict: str) -> str:
    """Look up the canonical color for a verdict / action label."""
    return COLORS.get((action_or_verdict or "").upper(), COLORS["HOLD"])


# ─────────────────────────────────────────────────────────────────────────────
# Verdict pill (used on Top Picks cards, Analyze Stock banner, Watchlist rows)
# ─────────────────────────────────────────────────────────────────────────────

def verdict_pill(verdict: str, horizon: str = "medium",
                 confidence: str = "medium",
                 conviction: Optional[int] = None,
                 primary_reason: str = "",
                 compact: bool = True) -> str:
    """
    A colored pill showing "VERDICT: BUY" (or STRONG BUY / WATCH / HOLD /
    AVOID) with a hover tooltip carrying horizon, confidence, conviction
    and primary reason. `compact=True` returns the small inline pill used
    on cards; False returns a fuller banner for page hero areas.
    """
    c = action_color(verdict)
    tip_bits = [f"{horizon}-term lens", f"{confidence} confidence"]
    if conviction is not None:
        tip_bits.append(f"conviction {conviction}/100")
    tip = " · ".join(tip_bits)
    if primary_reason:
        tip = f"{tip}. {primary_reason}"
    if compact:
        return (
            f'<span style="background:{c}22;color:{c};border:1px solid {c};'
            f'border-radius:5px;padding:1px 7px;font-size:10px;font-weight:700;'
            f'margin-left:6px" title="{tip}">'
            f'VERDICT: {verdict}</span>'
        )
    return (
        f'<div style="display:inline-block;background:{c}22;color:{c};'
        f'border:1px solid {c};border-radius:6px;padding:4px 10px;'
        f'font-size:13px;font-weight:700" title="{tip}">'
        f'{verdict}</div>'
    )


# ─────────────────────────────────────────────────────────────────────────────
# Freshness stamp (single "scored HH:MM · live price as of now" line)
# ─────────────────────────────────────────────────────────────────────────────

def freshness_stamp(scored_at: str = "",
                    live_ok: bool = True) -> str:
    """
    Small footer line showing when the numbers on the card were computed
    and whether live-price data is available. Kept intentionally quiet
    (small font, low-contrast color) so it's readable without competing
    with the primary card content.
    """
    scored_txt = scored_at or "unknown"
    live_txt = "live price as of now" if live_ok else "live price unavailable — showing last close"
    return (
        f'<div style="font-size:10px;color:#555;margin-top:3px">'
        f'📊 Scored at {scored_txt} · 💹 {live_txt}'
        f'</div>'
    )


# ─────────────────────────────────────────────────────────────────────────────
# Risk-reward line with gross + cost-adjusted variants
# ─────────────────────────────────────────────────────────────────────────────

def rr_line(rr_gross: float, rr_net: float,
            cost_pct: float = 0.30) -> str:
    """
    The "R:R X.X:1 gross, Y.Y:1 net of ~Z% costs" line every card should
    carry so gross ratios don't overstate expected edge.
    """
    return (
        f'<div style="font-size:11px;color:#888;margin-top:2px">'
        f'R:R <span style="color:#fff">{rr_gross:.1f}:1</span> gross, '
        f'<span style="color:#ffb300">{rr_net:.1f}:1 net of ~{cost_pct:.2f}% costs</span>'
        f'</div>'
    )


# ─────────────────────────────────────────────────────────────────────────────
# Regime badge — use the SAME visual on every page that needs the context
# ─────────────────────────────────────────────────────────────────────────────

def regime_badge(label: str = "unknown",
                 confidence: str = "low",
                 compact: bool = False) -> str:
    """
    Standardized market-regime badge. `compact=True` returns a small inline
    pill (good for page-title rows). False returns the full-width banner
    used on Command Centre.
    """
    c = REGIME_COLORS.get(label, REGIME_COLORS["unknown"])
    e = REGIME_EMOJI.get(label, REGIME_EMOJI["unknown"])
    note = REGIME_NOTES.get(label, REGIME_NOTES["unknown"])
    pretty = label.replace("_", " ").title()

    if compact:
        return (
            f'<span style="background:{c}15;color:{c};border:1px solid {c};'
            f'border-radius:5px;padding:2px 8px;font-size:11px;font-weight:700" '
            f'title="{note}">{e} {pretty} · {confidence}</span>'
        )
    return (
        f'<div style="background:linear-gradient(90deg,{c}15,{c}05);'
        f'border-left:4px solid {c};border-radius:8px;padding:9px 14px;'
        f'margin:6px 0 12px 0;display:flex;justify-content:space-between;'
        f'align-items:center;flex-wrap:wrap">'
        f'<span><span style="font-size:15px">{e} '
        f'<b style="color:{c}">{pretty}</b></span> '
        f'<span style="font-size:11px;color:#888;margin-left:8px">'
        f'{confidence.title()} confidence</span></span>'
        f'<span style="font-size:12px;color:#bbb">{note}</span>'
        f'</div>'
    )
