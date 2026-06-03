"""dashboard/shared/picks_ui.py — reason pointers, Deep Dive panel, and an optional
"Ask AI" chat for each NSE pick on the Command Centre.

The pointers + Deep Dive narrative work fully offline (driven by the scoring engine's
own output). The interactive chat is optional: it activates only when an Anthropic API
key is present in Streamlit secrets / env, and degrades to a hint otherwise.
"""
from __future__ import annotations
import os
import html
import streamlit as st

# Plain-English assistant persona. Kept stable so it caches on models that support it.
_SYSTEM = (
    "You are a concise NSE / Indian-equity analysis assistant embedded in a trading "
    "dashboard. Explain the given stock setup in plain English a retail investor can "
    "understand. Use ONLY the data provided about this stock plus general market "
    "knowledge — never invent specific prices or numbers not given. Keep answers under "
    "~120 words. You are NOT a SEBI-registered adviser: if asked whether to buy/sell, "
    "explain the trade-offs and end with a one-line reminder that this is not "
    "personalised investment advice."
)


# ── secrets / config ─────────────────────────────────────────────────────────
def _secret(name: str):
    try:
        if name in st.secrets:
            return st.secrets[name]
    except Exception:
        pass
    return os.environ.get(name)


def _ai_key():
    return _secret("ANTHROPIC_API_KEY")


def _ai_model():
    return _secret("ANTHROPIC_MODEL") or "claude-haiku-4-5"   # fast + cheap


# ── reason pointers (offline) ─────────────────────────────────────────────────
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


# ── AI chat (optional) ─────────────────────────────────────────────────────────
def _stock_context(pick: dict) -> str:
    tkr = pick["ticker"].replace(".NS", "")
    return (
        f"Stock: {tkr} (sector: {pick.get('sector', '?')})\n"
        f"Composite score: {pick.get('score', 0)}/100 (grade {pick.get('grade', '?')}, "
        f"action {pick.get('action', '?')})\n"
        f"Component breakdown — Technical {pick.get('technical', 0):.0f}/40, "
        f"Momentum {pick.get('momentum', 0):.0f}/25, Volume {pick.get('volume', 0):.0f}/15, "
        f"Pattern {pick.get('pattern', 0):.0f}/10, Sentiment {pick.get('sentiment', 0):.0f}/10\n"
        f"Suggested levels — entry ₹{pick.get('entry', 0)}, stop-loss ₹{pick.get('sl', 0)}, "
        f"target ₹{pick.get('tp', 0)}, risk:reward {pick.get('rr', 0)}:1\n"
        f"Engine narrative: {pick.get('narrative', '') or 'n/a'}"
    )


def ask_ai(pick: dict, history: list[dict]) -> str:
    """Call Claude Haiku with the stock context as a (cacheable) system prompt."""
    import anthropic
    client = anthropic.Anthropic(api_key=_ai_key())
    system = [
        {"type": "text", "text": _SYSTEM},
        # stable per-stock context — cache_control is harmless if below the cache minimum
        {"type": "text", "text": _stock_context(pick), "cache_control": {"type": "ephemeral"}},
    ]
    resp = client.messages.create(
        model=_ai_model(), max_tokens=400, system=system, messages=history,
    )
    return "".join(b.text for b in resp.content if b.type == "text").strip() or "(no answer)"


def _bubble(role: str, text: str):
    if role == "user":
        st.markdown(
            f'<div style="text-align:right;margin:4px 0"><span style="background:#1c2b4a;'
            f'color:#e8eefc;padding:6px 10px;border-radius:10px 10px 2px 10px;display:inline-block;'
            f'font-size:12px;max-width:85%">{html.escape(text)}</span></div>',
            unsafe_allow_html=True)
    else:
        st.markdown(
            f'<div style="display:flex;gap:6px;margin:4px 0"><span>🤖</span>'
            f'<span style="background:#10233a;color:#d8e6ff;padding:6px 10px;'
            f'border-radius:10px 10px 10px 2px;font-size:12px;max-width:88%">'
            f'{html.escape(text)}</span></div>', unsafe_allow_html=True)


def _render_ask_ai(pick: dict, key_prefix: str):
    st.markdown("---")
    if not _ai_key():
        st.caption("💡 **Ask AI** (interactive follow-up Q&A) turns on once an "
                   "`ANTHROPIC_API_KEY` is added to Streamlit secrets. The explanation "
                   "above already works without it.")
        return

    st.markdown("**🤖 Ask AI about this pick**")
    hist_key = f"_chat_{key_prefix}"
    hist = st.session_state.setdefault(hist_key, [])
    for msg in hist:
        _bubble(msg["role"], msg["content"])

    tkr = pick["ticker"].replace(".NS", "")
    q = st.text_input("Your question", key=f"{key_prefix}_q",
                      placeholder=f"e.g. Is {tkr} overbought? What's the main risk?",
                      label_visibility="collapsed")
    if st.button("Ask", key=f"{key_prefix}_ask", use_container_width=True) and q.strip():
        hist.append({"role": "user", "content": q.strip()})
        try:
            with st.spinner("Thinking…"):
                ans = ask_ai(pick, hist)
        except Exception as e:  # network / key / quota — show, don't crash
            ans = f"⚠️ Couldn't reach the AI service ({e})."
        hist.append({"role": "assistant", "content": ans})
        st.session_state[hist_key] = hist
        st.rerun()
    if hist and st.button("Clear chat", key=f"{key_prefix}_clear", use_container_width=True):
        st.session_state[hist_key] = []
        st.rerun()


# ── public: render pointers + Deep Dive panel under a pick card ─────────────────
def render_pick_analysis(pick: dict, key_prefix: str):
    """Render reason pointers (always visible) + a Deep Dive expander (narrative +
    score bars + full-analysis button + optional Ask-AI chat) for one pick."""
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
            f'<span style="font-size:18px">🤖</span>'
            f'<div style="font-size:12.5px;color:#dce6ff;line-height:1.5">'
            f'<b>Here\'s my read on {tkr}:</b><br>{html.escape(narr)}</div></div>',
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

        _render_ask_ai(pick, key_prefix)
