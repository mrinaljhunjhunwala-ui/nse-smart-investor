"""Tomorrow's Watchlist - NSE Smart Investor (next-session EOD setups)."""
import os, sys
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
import streamlit as st
from dashboard.shared.design import apply_design
from dashboard.shared.nav import render_sidebar
from dashboard.shared.chart_helpers import render_top_bar
from dashboard.shared.cache import _tomorrow_watchlist, get_display_name, _trade_type
from dashboard.shared.trade_utils import _paper_trade_popover

apply_design()
render_sidebar(current="Tomorrow's Watchlist")
render_top_bar()

# ───────────────────────── page body ─────────────────────────
st.title("📅 Tomorrow's Watchlist")
st.markdown(
    "Stocks worth watching for the **next trading session**, based on today's close "
    "signals — distinct from intraday Top Picks. Breakouts setting up, breakdown risks, "
    "and divergence/reversal candidates."
)

_wl = None
try:
    with st.spinner("Scanning the NSE universe on today's close — first run ~2 min, then cached…"):
        _wl = _tomorrow_watchlist()
except Exception as _e:
    st.error(f"Watchlist scan unavailable: {_e}")

if _wl is None:
    _wl = {"breakout_candidates": [], "breakdown_watch": [], "reversal_watch": [],
           "scan_time": "—"}

st.caption(f"🕒 Scanned: **{_wl.get('scan_time', '—')}** · Runs EOD, cached until the next "
           "session · not intraday. Levels are based on today's daily close.")

# Accent colour per watch type
_ACCENT = {"breakout": "#26a69a", "breakdown": "#ef5350", "reversal": "#ab8bff"}
_BG = {"breakout": "linear-gradient(135deg,#0a2a1a,#0f3320)",
       "breakdown": "linear-gradient(135deg,#2a0a0a,#330f0f)",
       "reversal": "linear-gradient(135deg,#1a1430,#221a3a)"}


def _render_cards(items, kind, key_prefix):
    if not items:
        st.caption("No candidates in this bucket on today's scan.")
        return
    accent = _ACCENT[kind]
    for _it in items:
        _lbl = _it["ticker"].replace(".NS", "")
        _tt_lbl, _tt_emo, _tt_col = _trade_type(_it.get("headline", ""))
        st.markdown(
            f'<div style="background:{_BG[kind]};border-left:4px solid {accent};'
            f'border-radius:10px;padding:11px 14px;margin-bottom:6px">'
            f'<div style="display:flex;justify-content:space-between;align-items:center">'
            f'<span style="font-size:16px;font-weight:700;color:#fff">{_lbl}</span>'
            f'<span style="font-size:13px;font-weight:700;color:{accent}">'
            f'{_it["score"]:.0f}/100 · {_it["action"]}</span>'
            f'</div>'
            f'<div style="font-size:11px;color:{accent};font-weight:600;margin-top:3px">'
            f'{_it["signal_type"]} · key level {_it["key_level"]}</div>'
            f'<div style="font-size:12px;color:#bbb;margin-top:2px">{_it["headline"]}</div>'
            + (f'<div style="font-size:11px;color:#888;margin-top:4px">'
               f'Entry ₹{_it["entry"]:,.2f} · SL ₹{_it["sl"]:,.2f} · TP ₹{_it["tp"]:,.2f}</div>'
               if _it.get("entry") else "")
            + '</div>',
            unsafe_allow_html=True,
        )
        if _it.get("entry"):
            _paper_trade_popover(
                _it["ticker"], _it["entry"], _it["sl"], _it["tp"],
                reason=f"Tomorrow Watch ({_it['signal_type']}): {_it['headline'][:45]}",
                key=f"{key_prefix}_{_it['ticker']}",
                label=f"📌 Paper Trade {_lbl}",
            )


_t1, _t2, _t3 = st.tabs([
    f"🚀 Breakout Watch ({len(_wl['breakout_candidates'])})",
    f"🔻 Breakdown Watch ({len(_wl['breakdown_watch'])})",
    f"🔄 Reversal Watch ({len(_wl['reversal_watch'])})",
])
with _t1:
    st.caption("Constructive setups approaching resistance with momentum & volume building — "
               "watch for a breakout at next open.")
    _render_cards(_wl["breakout_candidates"], "breakout", "tw_brk")
with _t2:
    st.caption("Weak names below key moving averages with distribution volume — watch for a "
               "breakdown / avoid fresh longs.")
    _render_cards(_wl["breakdown_watch"], "breakdown", "tw_bdn")
with _t3:
    st.caption("Divergences — price and momentum disagreeing (a potential turn). Confirm before "
               "acting; these are watch-only, not signals.")
    _render_cards(_wl["reversal_watch"], "reversal", "tw_rev")

st.markdown("---")
st.caption("⚠️ Educational watchlist on end-of-day signals — not investment advice. "
           "Always confirm at next open before acting.")
