"""Smart Screener - NSE Smart Investor (multipage page; body verbatim from app.py)."""
import os, sys
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
import streamlit as st
from dashboard.shared.design import apply_design
from dashboard.shared.nav import render_sidebar
from dashboard.shared.chart_helpers import render_top_bar
# P3: explicit imports (was a dynamic shared-namespace injection)
import os
import pandas as pd
import streamlit as st
import sys
from dashboard.shared.design import (
    apply_design,
)
from dashboard.shared.cache import (
    get_vix_info,
)
from dashboard.shared.trade_utils import (
    _action_color,
    _action_emoji,
)
from dashboard.shared.chart_helpers import (
    _ROOT,
    render_top_bar,
)

apply_design()
render_sidebar(current="Smart Screener")
render_top_bar()

# ───────────────────────── page body (de-indented from app.py) ─────────────────────────
st.title("🔎 Smart Stock Screener")
st.markdown(
    "Scan the NSE universe using 4 proven screens — oversold bounce, "
    "momentum leaders, breakouts, and pullback entries.  \n"
    "Each match is enriched with a **trend-quality score** (0–100 — trend health, "
    "not a return forecast)."
)

# Phase 1 (UI honesty): regime reliability next to live score output
from dashboard.shared.disclosures import (
    render_regime_reliability_note as _scr_regime_note,
    render_score_methodology as _scr_score_methodology,
)
_scr_regime_note()
_scr_score_methodology()

sc1, sc2, sc3 = st.columns(3)
with sc1:
    universe_choice = st.selectbox(
        "Universe",
        ["NIFTY 50 (50 stocks)", "NIFTY 100 (100 stocks)",
         "NIFTY 200 (200 stocks)", "NIFTY 500 (~400 stocks)"],
    )
    universe_map = {
        "NIFTY 50 (50 stocks)":    "nifty50",
        "NIFTY 100 (100 stocks)":  "nifty100",
        "NIFTY 200 (200 stocks)":  "nifty200",
        "NIFTY 500 (~400 stocks)": "nifty500",
    }
    universe_key = universe_map[universe_choice]
with sc2:
    screen_choice = st.selectbox(
        "Screen type",
        ["All 4 screens", "Oversold Bounce", "Momentum Leaders",
         "Breakouts", "Pullback to SMA"],
    )
    screen_map = {
        "All 4 screens": "all",
        "Oversold Bounce": "oversold",
        "Momentum Leaders": "momentum",
        "Breakouts": "breakout",
        "Pullback to SMA": "pullback_SMA20",
    }
    screen_key = screen_map[screen_choice]
with sc3:
    enrich_scores = st.checkbox("Enrich with trend-quality score", value=True,
                                help="Adds the 0-100 trend-quality score to each result (slower)")

scan_btn = st.button("🔍 Run Screen", type="primary")

if scan_btn:
    from data.universe import get_universe
    from trading.signals import scan_tickers
    universe = get_universe(universe_key)

    with st.spinner(f"Scanning {len(universe)} stocks… this may take a few minutes…"):
        signals = scan_tickers(universe, strategy=screen_key, period="1y")

    if not signals:
        st.info("No signals found for the current screen. Try a broader universe or different screen.")
    else:
        st.success(f"✅ Found **{len(signals)} setups** across {len(universe)} stocks!")
        vix_info = get_vix_info()

        if enrich_scores:
            from analysis.score import score_stock
            scored_signals = []
            prog = st.progress(0)
            for i, sig in enumerate(signals):
                try:
                    cs = score_stock(sig["ticker"], period="1y", vix_info=vix_info)
                    sig["composite_score"] = round(cs.score, 1)
                    sig["grade"]           = cs.grade
                    sig["action"]          = cs.action
                    sig["narrative"]       = cs.headline
                    sig["stop_loss"]       = round(cs.stop_loss, 2)
                    sig["target"]          = round(cs.target, 2)
                except Exception:
                    sig["composite_score"] = 50
                    sig["grade"]           = "C"
                    sig["action"]          = sig.get("action", "WATCHLIST")
                    sig["narrative"]       = "—"
                scored_signals.append(sig)
                prog.progress((i + 1) / len(signals))
            signals = sorted(scored_signals, key=lambda x: x.get("composite_score", 0), reverse=True)

        # Display results as Trade Setup Cards
        for sig in signals[:30]:  # cap at 30 for performance
            t      = sig["ticker"].replace(".NS", "")
            action = sig.get("action", "WATCHLIST")
            card   = _action_color(action)
            emoji  = _action_emoji(action)
            _s_price = sig.get("price", 0)
            _s_sl    = sig.get("sl", sig.get("stop_loss", 0)) or 0
            _s_tp    = sig.get("tp", sig.get("target", None))
            _s_rr    = (
                sig.get("rr_ratio") or
                (round((_s_tp - _s_price) / max(_s_price - _s_sl, 0.01), 1) if _s_tp else None)
            )
            _s_sector    = sig.get("sector", "")
            _s_stop_type = sig.get("stop_type", "atr")
            _s_score_str = (f"Score {sig.get('composite_score','?')}/100 "
                            f"[{sig.get('grade','?')}]" if enrich_scores else "")
            _s_rr_str    = f"R:R {_s_rr:.1f}x" if _s_rr else ""
            _header = (f"{emoji} {t}  |  ₹{_s_price:,.2f}  "
                       f"|  {sig.get('screen','')}  "
                       + (f"|  {_s_rr_str}  " if _s_rr_str else "")
                       + (f"|  {_s_sector}  " if _s_sector else "")
                       + _s_score_str)
            with st.expander(_header, expanded=False):
                d1, d2, d3, d4, d5 = st.columns(5)
                d1.metric("Entry",  f"₹{_s_price:,.2f}")
                d2.metric("Stop-Loss", f"₹{_s_sl:,.2f}",
                          delta=f"({_s_stop_type})",
                          delta_color="off")
                d3.metric("Target", f"₹{_s_tp:,.2f}" if _s_tp else "Trail SMA20")
                d4.metric("R:R",    f"{_s_rr:.1f}x" if _s_rr else "—",
                          delta="✅ Good" if (_s_rr or 0) >= 2 else "⚠️ Low",
                          delta_color="normal" if (_s_rr or 0) >= 2 else "inverse")
                d5.metric("Sector", _s_sector or "—")
                if sig.get("reason"):
                    st.caption(f"📌 {sig['reason']}")
                if enrich_scores and sig.get("narrative"):
                    st.markdown(
                        f'<div class="{card}" style="padding:10px 14px">'
                        f'<b>{sig.get("narrative","")}</b></div>',
                        unsafe_allow_html=True
                    )

        # Download results
        result_df = pd.DataFrame(signals)
        if not result_df.empty:
            st.download_button(
                "📥 Download Watchlist CSV",
                data=result_df.to_csv(index=False).encode(),
                file_name="nse_watchlist.csv",
                mime="text/csv",
            )


# ═══════════════════════════════════════════════════════════════════════════════
# PAGE 5 — PAPER TRADES  (full UI — enter, track, close, analyse)
# ═══════════════════════════════════════════════════════════════════════════════
