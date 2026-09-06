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
        "Trending up. Momentum-heavy signals have historically hit ~60%",
    "trend_down":
        "Trending down. Score dispatches to mean-reversion when v2 is on "
        "(NSE_USE_REGIME_WEIGHTS=1); momentum-first signals underperform either way",
    "range":
        "Range-bound. Historical BUY hit rate here is ~46% vs ~60% in trend-up regimes. "
        "Halve size or wait",
    "risk_off":
        "Risk-off (VIX ≥ 22). Historically all BUYs paid 5-12% but you have to buy the fear",
    "unknown":
        "Regime undetermined. Data unavailable",
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

# ─────────────────────────────────────────────────────────────────────────────
# Sprint 1.3 — panel() and stat() shared components
# Replace the three parallel systems the audit flagged (design.py .card-*,
# inline glass-panel divs, _pto_cell helper). Both source colour from
# design.py CSS custom properties by name, not raw hex — Task 1.6 hook
# rejects hex in page files.
# ─────────────────────────────────────────────────────────────────────────────

_PANEL_TONE_ACCENT = {
    "neutral": "var(--hairline)",
    "info":    "var(--accent)",
    "bull":    "var(--bull)",
    "bear":    "var(--bear)",
    "amber":   "var(--amber)",
    "violet":  "var(--violet)",
}

_PANEL_KINDS = {
    "flat":   {"bg": "var(--surface)",  "radius": "var(--r-base)",
               "border": "1px solid var(--hairline)"},
    "glass":  {"bg": "var(--surface)",  "radius": "var(--r-soft)",
               "border": "1px solid var(--hairline)"},
    "sunken": {"bg": "var(--sunken)",   "radius": "var(--r-base)",
               "border": "1px solid var(--hairline-soft)"},
}


def panel(body_html: str,
          kind: str = "flat",
          tone: str = "neutral",
          title: str = "",
          margin: str = "6px 0") -> str:
    """Container for a card / hero / metric group.

    kind: 'flat' (default cards), 'glass' (hero panels), 'sunken' (secondary)
    tone: 'neutral' (default), 'info', 'bull', 'bear', 'amber', 'violet' —
          adds a 3-px semantic rail on the left when non-neutral.
    title: optional eyebrow label rendered in the mono utility face.

    Returns raw HTML — caller stamps via st.markdown(..., unsafe_allow_html=True).
    """
    style = _PANEL_KINDS.get(kind, _PANEL_KINDS["flat"])
    rail_color = _PANEL_TONE_ACCENT.get(tone, _PANEL_TONE_ACCENT["neutral"])
    rail_css = (f"border-left:3px solid {rail_color};"
                if tone != "neutral" else "")
    title_html = (
        f'<div style="font-family:var(--font-mono);font-size:10px;'
        f'letter-spacing:1.2px;text-transform:uppercase;color:var(--dim);'
        f'font-weight:600;margin-bottom:8px">{title}</div>'
        if title else ""
    )
    return (
        f'<div style="background:{style["bg"]};border:{style["border"]};'
        f'{rail_css}border-radius:{style["radius"]};'
        f'padding:14px 18px;margin:{margin}">'
        f'{title_html}{body_html}</div>'
    )


_STAT_TONE_COLOR = {
    "neutral": "var(--ink)",
    "bull":    "var(--bull)",
    "bear":    "var(--bear)",
    "amber":   "var(--amber)",
    "accent":  "var(--accent)",
    "dim":     "var(--dim)",
}


def stat(label: str, value: str,
         delta: str = "",
         delta_positive: Optional[bool] = None,
         sub: str = "",
         tone: str = "neutral",
         align: str = "left") -> str:
    """Single-value stat (label + big number + optional delta and sub-line).

    Replaces st.metric / .metric-box / _pto_cell / _glass_metric etc.
    Numeric value renders in the mono face for column-friendly alignment.

    tone: 'neutral' | 'bull' | 'bear' | 'amber' | 'accent' | 'dim'
    delta_positive: True → green arrow, False → red, None → grey (no arrow)
    """
    value_color = _STAT_TONE_COLOR.get(tone, _STAT_TONE_COLOR["neutral"])
    delta_html = ""
    if delta:
        if delta_positive is True:
            _c, _sym = "var(--bull)", "▲"
        elif delta_positive is False:
            _c, _sym = "var(--bear)", "▼"
        else:
            _c, _sym = "var(--dim)", "•"
        delta_html = (
            f'<div style="font-family:var(--font-mono);font-size:12px;'
            f'color:{_c};font-weight:600;margin-top:4px">'
            f'{_sym} {delta}</div>'
        )
    sub_html = (
        f'<div style="font-size:11px;color:var(--dim);margin-top:3px">{sub}</div>'
        if sub else ""
    )
    return (
        f'<div style="text-align:{align}">'
        f'<div style="font-family:var(--font-mono);font-size:10px;'
        f'letter-spacing:1.2px;text-transform:uppercase;color:var(--dim);'
        f'font-weight:600">{label}</div>'
        f'<div style="font-family:var(--font-mono);font-size:23px;'
        f'font-weight:700;color:{value_color};margin-top:4px;'
        f'letter-spacing:-.3px">{value}</div>'
        f'{delta_html}{sub_html}</div>'
    )


# ─────────────────────────────────────────────────────────────────────────────
# Sprint 1.4 — Verdict Card hero for Analyze Stock
# Audit's #1 finding: "So what should I do?" was never the loudest thing on
# the page. This is that one thing. Renders action, conviction score, size
# in rupees, R multiple, horizon, and (when armed) the F&O positioning
# regime — all in a single at-a-glance panel above every other on-page
# section. Pure string builder; caller composes portfolio_ctx if available.
# ─────────────────────────────────────────────────────────────────────────────

def verdict_card(cs, portfolio_ctx: Optional[dict] = None,
                 capital_per_trade: float = 100_000.0) -> str:
    """Build the top-of-page verdict card for Analyze Stock.

    cs is a CompositeScore instance. portfolio_ctx is optional — pass a dict
    like {'shares_held': 40, 'avg_price': 2500.0} to render a position line.
    capital_per_trade drives the suggested share count from risk-per-trade.

    Only reads fields that CompositeScore always populates + the four new
    fields shipped in Recs 1-6: rs_score, positioning_score, is_fno,
    momentum_fallback.
    """
    action    = getattr(cs, "action", "HOLD") or "HOLD"
    score     = float(getattr(cs, "score", 0.0) or 0.0)
    grade     = getattr(cs, "grade", "F") or "F"
    horizon   = getattr(cs, "horizon", "") or ""
    entry     = float(getattr(cs, "entry", 0.0) or 0.0)
    sl        = float(getattr(cs, "stop_loss", 0.0) or 0.0)
    tp        = float(getattr(cs, "target", 0.0) or 0.0)
    rr        = float(getattr(cs, "risk_reward", 0.0) or 0.0)
    rs_score  = getattr(cs, "rs_score", None)
    pos_score = getattr(cs, "positioning_score", None)
    is_fno    = bool(getattr(cs, "is_fno", False))
    ticker    = str(getattr(cs, "ticker", "")).replace(".NS", "") or "—"

    tone = "bull" if action in ("STRONG BUY", "BUY") else \
           "bear" if action in ("EXIT", "AVOID") else \
           "amber" if action in ("CAUTION",) else "info"
    action_color_ = action_color(action)

    # Risk-per-trade sizing: 1% of capital, at least 1 share, capped when
    # entry is unavailable.
    per_share_risk = max(entry - sl, 0.01) if entry > 0 else 0.0
    if per_share_risk > 0 and entry > 0:
        risk_budget = capital_per_trade * 0.01
        shares      = max(1, int(risk_budget / per_share_risk))
        position_rs = shares * entry
    else:
        shares      = 0
        position_rs = 0.0

    # Header: ticker + action pill + grade + horizon
    # NB: F&O chip is precomputed outside the f-string. Python 3.11 rejects
    # backslashes inside f-string expressions (PEP 701 relaxed this in 3.12);
    # CI runs on 3.11 so we keep the escape-free form.
    fno_chip = (
        ' · <span style="background:var(--tint-accent);color:var(--accent);'
        'border:1px solid var(--accent);border-radius:4px;padding:2px 6px;'
        'font-size:10px;font-weight:600;letter-spacing:.5px">F&amp;O</span>'
        if is_fno else ""
    )
    horizon_txt = horizon or "-"
    header = (
        f'<div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap;'
        f'margin-bottom:14px">'
        f'<span style="font-size:22px;font-weight:700;color:var(--ink);'
        f'letter-spacing:-.3px">{ticker}</span>'
        f'<span style="background:{action_color_}22;color:{action_color_};'
        f'border:1px solid {action_color_};border-radius:6px;padding:4px 12px;'
        f'font-size:13px;font-weight:700;letter-spacing:.5px">{action}</span>'
        f'<span style="color:var(--dim);font-family:var(--font-mono);'
        f'font-size:12px">Grade {grade} · {horizon_txt}</span>'
        f'{fno_chip}'
        f'</div>'
    )

    # Left cluster: conviction score (big) + score bar
    # FIX POS2-UI (Rec 6 design 6b): F&O ticker with the Positioning pillar
    # active scores against a 100-pt cap instead of 90 (the extra 10 comes
    # from the positioning overlay). Show the real ceiling so the fraction
    # reads honestly. Non-F&O or pillar-inactive tickers keep the 90 cap.
    _cap = 100.0 if pos_score is not None else 90.0
    score_pct = max(0.0, min(1.0, score / _cap))
    conviction = (
        f'<div style="text-align:left">'
        f'<div style="font-family:var(--font-mono);font-size:10px;'
        f'letter-spacing:1.2px;text-transform:uppercase;color:var(--dim);'
        f'font-weight:600">Conviction</div>'
        f'<div style="font-family:var(--font-mono);font-size:44px;'
        f'font-weight:700;color:{action_color_};line-height:1;letter-spacing:-1px;'
        f'margin-top:6px">{score:.0f}<span style="font-size:16px;color:var(--dim);'
        f'font-weight:500">/{int(_cap)}</span></div>'
        f'<div style="margin-top:8px;height:4px;background:var(--hairline);'
        f'border-radius:2px;overflow:hidden;width:140px">'
        f'<div style="height:100%;width:{score_pct*100:.1f}%;'
        f'background:{action_color_}"></div></div></div>'
    )

    # Right cluster: entry / stop / target / R:R / size — all as stat()
    def _fmt_rs(x: float) -> str:
        return f"Rs.{x:,.2f}"
    sl_pct = ((sl / entry - 1) * 100) if entry > 0 else 0.0
    tp_pct = ((tp / entry - 1) * 100) if entry > 0 else 0.0
    trade = (
        '<div style="display:grid;grid-template-columns:repeat(5, minmax(90px,1fr));'
        'gap:14px 22px;flex:1">'
        + stat("Entry",  _fmt_rs(entry), tone="neutral")
        + stat("Stop",   _fmt_rs(sl),
               sub=f"{sl_pct:+.1f}%", tone="bear")
        + stat("Target", _fmt_rs(tp),
               sub=f"{tp_pct:+.1f}%", tone="bull")
        + stat("R:R",    f"{rr:.1f}x", tone="accent")
        + stat("Suggested size", f"{shares} sh"
               if shares else "—",
               sub=(_fmt_rs(position_rs) if position_rs else "risk-budget 1%"),
               tone="neutral")
        + '</div>'
    )

    body = (
        f'{header}'
        f'<div style="display:flex;gap:28px;align-items:flex-start;flex-wrap:wrap">'
        f'{conviction}{trade}</div>'
    )

    # Optional secondary row: RS + positioning + portfolio position
    footer_bits = []
    if rs_score is not None:
        _rs_tone = "bull" if rs_score >= 70 else "amber" if rs_score >= 40 else "bear"
        footer_bits.append(stat("RS vs Nifty", f"{rs_score:.0f}",
                                sub="0-100 percentile", tone=_rs_tone))
    if pos_score is not None:
        _pos_tone = ("bull" if pos_score >= 7 else
                     "amber" if pos_score >= 4 else "bear")
        footer_bits.append(stat("Positioning", f"{pos_score:.1f}/10",
                                sub="OI · PCR · MP · FII", tone=_pos_tone))
    # FIX OVERLAY1 (Task 3.3) - TQS x valuation sidecar. Rendered as a footer
    # stat next to RS / Positioning, deliberately NOT next to the big 0-90
    # conviction number, so it reads as a secondary quality-x-value lens
    # rather than a competing headline. Never blended into cs.score.
    overlay_score = getattr(cs, "overlay_score", None)
    if overlay_score is not None:
        _ov_tone = ("bull"  if overlay_score >= 70 else
                    "amber" if overlay_score >= 45 else "bear")
        footer_bits.append(stat("Quality x Value", f"{overlay_score}/100",
                                sub="TQS x valuation posture", tone=_ov_tone))
    if portfolio_ctx:
        _q = int(portfolio_ctx.get("shares_held", 0) or 0)
        _a = float(portfolio_ctx.get("avg_price", 0) or 0.0)
        if _q:
            pnl = (entry - _a) * _q if entry > 0 else 0.0
            footer_bits.append(stat("Your position", f"{_q} sh @ Rs.{_a:,.2f}",
                                    sub=f"P/L Rs.{pnl:+,.0f}",
                                    tone="bull" if pnl >= 0 else "bear"))
    if footer_bits:
        body += (
            '<div style="margin-top:16px;padding-top:14px;'
            'border-top:1px solid var(--hairline-soft);'
            'display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));'
            'gap:14px 20px">'
            + "".join(footer_bits)
            + '</div>'
        )

    return panel(body, kind="glass", tone=tone, margin="12px 0")


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
