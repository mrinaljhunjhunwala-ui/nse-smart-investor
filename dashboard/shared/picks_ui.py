"""dashboard/shared/picks_ui.py — reason pointers + a Deep Dive panel for each NSE
pick on the Command Centre.

Everything here is offline and driven by the scoring engine's own output:
  • pick_pointers()        — bullet "why" derived from the component-score breakdown
  • render_pick_analysis() — pointers + a Deep Dive expander (plain-English narrative,
                             per-component score bars, and an Open-full-analysis button)
"""
from __future__ import annotations
import html
import streamlit as st


def pick_pointers(pick: dict) -> list[tuple[str, str]]:
    """Turn the component-score breakdown into human-readable (emoji, text) bullets."""
    t = pick.get("technical", 0); m = pick.get("momentum", 0)
    v = pick.get("volume", 0); p = pick.get("pattern", 0)
    pts: list[tuple[str, str]] = []

    if t >= 30:
        pts.append(("✅", "Strong trend — price above its key moving averages"))
    elif t >= 18:
        pts.append(("🟡", "Mixed trend — only partial moving-average support"))
    else:
        pts.append(("⚠️", "Weak trend — trading below its long-term average"))

    if m >= 20:
        pts.append(("✅", "Strong momentum — RSI healthy and rising"))
    elif m >= 12:
        pts.append(("🟡", "Moderate momentum"))
    else:
        pts.append(("⚠️", "Weak momentum — limited buying thrust"))

    if v >= 10:
        pts.append(("✅", "Above-average volume — real buyer participation"))
    elif v < 6:
        pts.append(("⚠️", "Below-average volume — move needs confirmation"))

    if p >= 5:
        pts.append(("✅", "Bullish candlestick confirmation on the chart"))

    if pick.get("entry"):
        pts.append(("🎯", f"Risk:Reward {pick.get('rr', 0):.1f}:1 — entry ₹{pick['entry']:,.0f}, "
                          f"stop ₹{pick['sl']:,.0f}, target ₹{pick['tp']:,.0f}"))
    return pts


def render_pick_analysis(pick: dict, key_prefix: str):
    """Render reason pointers (always visible) + a Deep Dive expander (narrative +
    score bars + full-analysis button) for one pick."""
    tkr = pick["ticker"].replace(".NS", "")

    pts_html = "".join(
        f'<div style="font-size:11.5px;color:#cfd6e6;margin:1px 0">{e}&nbsp;{txt}</div>'
        for e, txt in pick_pointers(pick))
    st.markdown(f'<div style="margin:-2px 0 4px 2px">{pts_html}</div>', unsafe_allow_html=True)

    with st.expander(f"🔍 Deep Dive — why {tkr}?", expanded=False):
        narr = pick.get("narrative") or "No detailed narrative available for this pick."
        st.markdown(
            f'<div style="display:flex;gap:8px;background:#0c1830;border:1px solid #1d2c48;'
            f'border-radius:10px;padding:10px 12px;margin-bottom:8px">'
            f'<span style="font-size:18px">🧭</span>'
            f'<div style="font-size:12.5px;color:#dce6ff;line-height:1.5">'
            f'<b>Why {tkr} scored {pick.get("score", 0):.0f}/100:</b><br>{html.escape(narr)}</div></div>',
            unsafe_allow_html=True)

        st.caption("How the score was built")
        for label, cap in (("Technical", 40), ("Momentum", 25), ("Volume", 15),
                           ("Pattern", 10), ("Sentiment", 10)):
            val = float(pick.get(label.lower(), 0) or 0)
            st.markdown(f'<span style="font-size:11px;color:#8899bb">{label} '
                        f'<b style="color:#e0e0e0">{val:.0f}/{cap}</b></span>',
                        unsafe_allow_html=True)
            st.progress(min(1.0, val / cap if cap else 0.0))

        if st.button(f"📊 Open full analysis for {tkr}", key=f"{key_prefix}_full",
                     use_container_width=True):
            st.session_state["analyze_ticker"] = pick["ticker"]
            st.session_state["_goto_page"] = "🔍 Analyze Stock"
            st.rerun()
