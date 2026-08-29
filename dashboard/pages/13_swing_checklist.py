"""Swing Checklist - NSE Smart Investor (multipage page; body verbatim from app.py)."""
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import pandas as pd
import streamlit as st

from dashboard.shared.cache import STOCK_SEARCH_MAP
from dashboard.shared.chart_helpers import _ROOT, render_top_bar  # noqa: F811
from dashboard.shared.design import apply_design
from dashboard.shared.nav import render_sidebar

# ── FIX 1: Removed duplicate imports — single clean import block above ──

apply_design()
render_sidebar(current="Swing Checklist")
render_top_bar()

# ───────────────────────── page body ─────────────────────────
st.title("✅ Swing Trade Confluence Checklist")
st.markdown(
    "Run all 8 go/no-go factors for a delivery swing trade in one click.  \n"
    "Green = factor confirms the trade. Red = caution. Need ≥ 5/8 green to enter."
    # ── FIX 7: Updated copy to reflect actual factor count (was 7, now 8 with Volume) ──
)

# FIX ANL-XREF — see the matching note in 04_analyze_stock.py.
with st.expander("↔️ Also see: Analyze Stock · Deep Dive · Quality Watch", expanded=False):
    st.markdown(
        "This page is a **pre-trade go/no-go** — use after you've decided a "
        "name is worth acting on. For the setup itself go to **Analyze Stock**; "
        "for structural / hold-worthiness questions go to **Deep Dive** or "
        "**Quality Watch**."
    )

# ── Stock picker ──
_sc_search_options = sorted(
    f"{name}  ({sym.replace('.NS', '')})"
    for name, sym in STOCK_SEARCH_MAP.items()
)
_SC_PLACEHOLDER = "— type to search —"

# FIX SC1: the dropdown and the manual ticker box were independent widgets
# with no relationship — picking a dropdown stock left old text sitting in
# the manual box, which silently took priority in the "Resolve final
# symbol" logic below. That meant picking a NEW stock from the dropdown
# had no visible effect at all if the manual box still held something from
# an earlier search — the checklist kept running against the old ticker.
# Neither field cleared on its own. Same on_change + clear-pending pattern
# already used (and verified) in dashboard/pages/04_analyze_stock.py's
# search boxes: using one field clears the other, and "✖ Clear" resets both.
# The clear-pending flag (rather than writing session_state directly in the
# button block) is required because Streamlit raises "cannot be modified
# after the widget ... is instantiated" if a widget's key is written to
# after that widget has already rendered in the same script run.
if st.session_state.pop("_sc_clear_pending", False):
    st.session_state["sc_search_select"] = _SC_PLACEHOLDER
    st.session_state["sc_manual_input"] = ""

def _sc_on_dropdown_change():
    if st.session_state.get("sc_search_select", _SC_PLACEHOLDER) != _SC_PLACEHOLDER:
        st.session_state["sc_manual_input"] = ""

def _sc_on_manual_change():
    if st.session_state.get("sc_manual_input", "").strip():
        st.session_state["sc_search_select"] = _SC_PLACEHOLDER

_sc_c1, _sc_c2, _sc_c3, _sc_c4 = st.columns([3, 2, 1, 1])
with _sc_c1:
    _sc_selected = st.selectbox(
        "Search by company name or symbol",
        options=[_SC_PLACEHOLDER] + _sc_search_options,
        index=0,
        key="sc_search_select",
        on_change=_sc_on_dropdown_change,
    )
with _sc_c2:
    _sc_manual = st.text_input(
        "Or type ticker directly",
        value="",
        placeholder="e.g. INFY or INFY.NS",
        key="sc_manual_input",
        on_change=_sc_on_manual_change,
    ).strip().upper()
with _sc_c3:
    st.write("")
    st.write("")
    if st.button("✖ Clear", key="sc_clear_search", use_container_width=True):
        st.session_state["_sc_clear_pending"] = True
        st.rerun()
with _sc_c4:
    st.write("")
    st.write("")
    _sc_btn = st.button("✅ Run Checklist", type="primary", key="sc_btn")

# Resolve final symbol — manual entry wins, else the dropdown selection
_sc_sym = ""
if _sc_manual:
    _sc_sym = _sc_manual if _sc_manual.endswith(".NS") else _sc_manual + ".NS"
elif _sc_selected != _SC_PLACEHOLDER:
    _sc_raw = _sc_selected.rsplit("(", 1)[-1].rstrip(")")
    _sc_sym = _sc_raw if _sc_raw.endswith(".NS") else _sc_raw + ".NS"
_sc_ticker = _sc_sym.replace(".NS", "")

if _sc_btn and _sc_sym:
    with st.spinner(f"Running confluence checklist for {_sc_ticker}…"):
        try:
            from analysis.mtf import check_daily_weekly_alignment
            from data.fetcher import fetch_single
            from strategies.sector_rotation import SECTORS, compute_sector_scores
            from trading.signals import get_india_vix_regime
            from utils.indicators import add_all_indicators

            # ── FIX 4: Fetch both daily AND weekly data for true MTF alignment ──
            _sc_df_daily  = fetch_single(_sc_sym, period="1y", interval="1d")
            _sc_df_weekly = fetch_single(_sc_sym, period="2y", interval="1wk")

            _sc_df_daily  = add_all_indicators(_sc_df_daily)
            _sc_df_weekly = add_all_indicators(_sc_df_weekly)

            _sc_df_daily.dropna(subset=["RSI", "ATR"], inplace=True)
            _sc_df_weekly.dropna(subset=["RSI"], inplace=True)

            _sc_cur = _sc_df_daily.iloc[-1]
            _price  = float(_sc_cur["Close"])
            _rsi    = float(_sc_cur.get("RSI", 50))
            _adx    = float(_sc_cur.get("ADX", 0)) if not pd.isna(_sc_cur.get("ADX", 0)) else 0
            _sma20  = float(_sc_cur.get("SMA_20", 0))
            _sma50  = float(_sc_cur.get("SMA_50", 0))
            _sma200 = float(_sc_cur.get("SMA_200", 0))
            _atr    = float(_sc_cur.get("ATR", 0))
            _vol_r  = float(_sc_cur.get("Volume_Ratio", 1))
            _fib_zone = str(_sc_cur.get("Fib_Zone", "unknown"))
            _cpr_zone = str(_sc_cur.get("Price_vs_CPR", "unknown"))

            # ── VIX check ──
            _vix_r  = get_india_vix_regime()
            _vix_ok = _vix_r["allow_buy"]
            _vix_val = _vix_r.get("vix") or 0

            # ── Sector rank check ──
            # ── FIX 5: Sector exception now marks as FAILED (False), not silently passed ──
            try:
                _sec_scores   = compute_sector_scores(period="1y")
                _top3         = set(_sec_scores.head(3).index.tolist()) if not _sec_scores.empty else set()
                _ticker_sector = {t: s for s, ts in SECTORS.items() for t in ts}
                _stock_sector  = _ticker_sector.get(_sc_sym, "Unknown")
                _sector_ok     = _stock_sector in _top3
                _sector_str    = f"{_stock_sector} ({'Top 3' if _sector_ok else 'Not top 3'})"
            except Exception as _sec_err:
                _sector_ok  = False  # conservative: don't reward a broken check
                _sector_str = f"Sector check failed: {_sec_err}"

            # ── MTF check (now uses actual weekly dataframe) ──
            # ── FIX 6: MTF exception now marks as FAILED (False), not silently passed ──
            try:
                _mtf     = check_daily_weekly_alignment(_sc_df_daily, _sc_df_weekly)
                _mtf_ok  = _mtf["alignment"] == "bullish"
                _mtf_str = _mtf["confirmation"]
            except Exception as _mtf_err:
                _mtf_ok  = False  # conservative: don't reward a broken check
                _mtf_str = f"MTF check failed: {_mtf_err}"

            # ── Build checklist items ──
            _checks = [
                {
                    "name":   "1️⃣ VIX Regime",
                    "pass":   _vix_ok,
                    "detail": f"India VIX = {_vix_val:.1f} | Regime: {_vix_r.get('regime', '?').upper()}",
                    "tip":    "VIX must be ≤ 28. High VIX = panic = avoid new longs.",
                },
                {
                    "name":   "2️⃣ Long-Term Trend (SMA200)",
                    "pass":   _price > _sma200 > 0,
                    "detail": f"Price ₹{_price:.1f} {'>' if _price > _sma200 else '<'} SMA200 ₹{_sma200:.1f}",
                    "tip":    "Price must be above 200-day SMA to confirm long-term uptrend.",
                },
                {
                    "name":   "3️⃣ MA Stack (SMA20 > SMA50)",
                    "pass":   _sma20 > _sma50 > 0,
                    "detail": f"SMA20 ₹{_sma20:.1f} {'>' if _sma20 > _sma50 else '<'} SMA50 ₹{_sma50:.1f}",
                    "tip":    "Moving average alignment confirms short-term uptrend.",
                },
                {
                    # ── FIX 2: Lower bound corrected from 30 to 25 to match the tip text ──
                    "name":   "4️⃣ RSI Zone (25–72)",
                    "pass":   25 < _rsi < 72,
                    "detail": f"RSI = {_rsi:.1f} | Ideal entry: 40–60",
                    "tip":    "RSI in healthy range — not overbought (>72) or in freefall (<25).",
                },
                {
                    "name":   "5️⃣ ADX Trend Strength",
                    "pass":   _adx >= 20,
                    "detail": f"ADX = {_adx:.1f} | {'Trending ✅' if _adx >= 25 else ('Weak trend' if _adx >= 20 else 'Ranging ❌')}",
                    "tip":    "ADX ≥ 20 confirms trending environment. Below 20 = ranging/choppy.",
                },
                {
                    "name":   "6️⃣ Multi-Timeframe Alignment",
                    "pass":   _mtf_ok,
                    "detail": _mtf_str,
                    "tip":    "Both daily and weekly must be bullish for high-conviction swing entry.",
                },
                {
                    "name":   "7️⃣ Sector in Top-3",
                    "pass":   _sector_ok,
                    "detail": _sector_str,
                    "tip":    "Stocks in top-3 sectors by momentum score have higher win rates.",
                },
                {
                    # ── FIX 9: Volume Ratio was fetched but never used — now a real check ──
                    "name":   "8️⃣ Volume Confirmation (≥ 1.2×)",
                    "pass":   _vol_r >= 1.2,
                    "detail": f"Volume Ratio = {_vol_r:.2f}× avg | {'Above avg ✅' if _vol_r >= 1.2 else 'Below avg ❌'}",
                    "tip":    "Volume ≥ 1.2× 20-day avg confirms participation behind the move.",
                },
            ]

            # ── Score ──
            _score = sum(1 for c in _checks if c["pass"])
            _score_color = "card-green" if _score >= 5 else ("card-yellow" if _score >= 3 else "card-red")

            # ── FIX 7: Verdict thresholds now consistent with "need ≥ 5 to enter" rule ──
            _verdict = (
                "✅ STRONG SETUP — All key factors aligned. Consider entry."
                if _score >= 7 else
                "🟡 MODERATE SETUP — Most factors align. Entry with smaller size."
                if _score >= 5 else
                "🔴 WEAK SETUP — Too many factors against. Wait for improvement."
            )

            st.markdown(f"""
            <div class="{_score_color}">
            <span class="score-big">{_score}/8</span> &nbsp;&nbsp;
            <span class="signal-big">{_verdict}</span><br>
            <b>{_sc_ticker}</b> at ₹{_price:.2f} | RSI {_rsi:.1f} | ADX {_adx:.1f}
            </div>
            """, unsafe_allow_html=True)

            st.markdown("---")
            st.markdown("### Checklist Details")
            for _chk in _checks:
                _icon  = "✅" if _chk["pass"] else "❌"
                _color = "#4caf50" if _chk["pass"] else "#ef5350"
                st.markdown(
                    f"<div style='border-left:4px solid {_color}; padding:8px 12px; "
                    f"margin:6px 0; background:rgba(255,255,255,0.03); border-radius:4px;'>"
                    f"<b>{_icon} {_chk['name']}</b><br>"
                    f"<span style='color:#ccc'>{_chk['detail']}</span><br>"
                    f"<small style='color:#888'>{_chk['tip']}</small></div>",
                    unsafe_allow_html=True,
                )

            # ── Trade plan if score ≥ 5 ──
            # ── FIX 7: Threshold raised from 4 to 5 to match entry rule ──
            if _score >= 5 and _atr > 0:
                st.markdown("---")
                st.markdown("### 📋 Suggested Trade Plan")

                _sl_val = _price - 2 * _atr
                _tp_val = _price + 3 * _atr

                # ── FIX 3: R:R now computed from actual price levels, not a hardcoded constant ──
                _rr_val = (_tp_val - _price) / (_price - _sl_val)

                st.markdown(f"""
                <div class="card-blue">
                <b>Entry:</b> ₹{_price:.2f} &nbsp;|&nbsp;
                <b>SL:</b> ₹{_sl_val:.2f} (2× ATR) &nbsp;|&nbsp;
                <b>TP:</b> ₹{_tp_val:.2f} (3× ATR) &nbsp;|&nbsp;
                <b>R:R:</b> {_rr_val:.1f}x<br>
                <small>ATR = ₹{_atr:.2f} | Fib Zone: {_fib_zone} | CPR: {_cpr_zone}</small>
                </div>
                """, unsafe_allow_html=True)

        except Exception as _sce:
            st.error(f"Checklist error: {_sce}")
            import traceback
            st.code(traceback.format_exc())
else:
    st.info("Enter a ticker and click **✅ Run Checklist** to see confluence analysis.")

# ── Reference table ──
st.markdown("---")
st.markdown("### 📖 Checklist Reference — What Each Factor Means")
st.dataframe(pd.DataFrame([
    {"Factor": "VIX Regime",        "Pass When": "India VIX ≤ 28",             "Why It Matters": "High VIX = market panic = stop-outs are more likely"},
    {"Factor": "SMA200 Trend",      "Pass When": "Price > SMA200",              "Why It Matters": "Stocks below SMA200 are in a downtrend — buying is fighting the tape"},
    {"Factor": "MA Stack",          "Pass When": "SMA20 > SMA50",               "Why It Matters": "Short-term uptrend confirmed when faster MA is above slower"},
    {"Factor": "RSI Zone",          "Pass When": "RSI 25–72",                   "Why It Matters": "Outside this range = exhaustion (too hot) or freefall (too cold)"},
    {"Factor": "ADX Strength",      "Pass When": "ADX ≥ 20",                   "Why It Matters": "Trending stocks have higher momentum carry than ranging stocks"},
    {"Factor": "MTF Alignment",     "Pass When": "Daily + Weekly both bullish", "Why It Matters": "Same direction on multiple timeframes = higher conviction"},
    {"Factor": "Sector Rank",       "Pass When": "Sector in Top 3",             "Why It Matters": "Rising sectors carry stocks — fighting sector momentum rarely works"},
    {"Factor": "Volume Confirm",    "Pass When": "Volume Ratio ≥ 1.2×",        "Why It Matters": "Above-average volume validates the move; low volume = weak conviction"},
]), hide_index=True, width="stretch")
