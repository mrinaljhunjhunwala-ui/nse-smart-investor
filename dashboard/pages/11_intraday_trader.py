"""Intraday Trader - NSE Smart Investor (multipage page; body verbatim from app.py)."""
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
import plotly.graph_objects as go
import streamlit as st
import sys
from dashboard.shared.design import (
    apply_design,
)
from dashboard.shared.trade_utils import (
    _display_label,            # Phase 2 UI honesty
    _paper_trade_popover,
)
from dashboard.shared.cache import (
    STOCK_SEARCH_MAP,
    get_vix_info,               # FIX MERGE1 — needed for the merged Options tabs
)
from dashboard.shared.chart_helpers import (
    _ROOT,
    make_subplots,
    render_top_bar,
)

apply_design()
render_sidebar(current="Intraday Trader")
render_top_bar()

# ───────────────────────── page body (de-indented from app.py) ─────────────────────────
st.title("Intraday Trader")

st.markdown(
    "Real-time intraday tools — Gap Scanner, CPR Levels, ORB Setup, "
    "live Supertrend/VWAP signals on 5m/15m charts, and Options strategy/OI tools.  \n"
    "⚠️ *Data is 15-min delayed via Yahoo Finance free API.*"
)

# FIX DEDUP1 — the "Live Positions" tab used to live here too, calling the
# same data.angel_fetcher.get_positions() already shown on the dedicated
# 🔗 Angel One page's "Today's Positions" tab. Same data, two places to
# maintain and two places for a user to have to check. Removed here in
# favor of the single copy on the Angel One page.
#
# FIX MERGE1 — the standalone "OI & Options" page (Strategy Selector, Max
# Pain Calculator, PCR Zone Reference) is merged in here as three more tabs.
# Both pages were market-hours trading-decision tools with no shared state
# between them, so this is a pure tab consolidation, not a data/logic
# change — every calculation below is byte-identical to the old page.
_it_tabs = ["📊 Pre-Market Gap Scanner", "📈 Intraday Chart",
            "⚡ ORB Setup", "🎯 Live Intraday Signals",
            "📊 Options Strategy", "🔢 Max Pain Calculator", "📈 PCR Zone Reference"]

_tab_objs   = st.tabs(_it_tabs)
tab_gap     = _tab_objs[0]
tab_chart   = _tab_objs[1]
tab_orb     = _tab_objs[2]
tab_sigs    = _tab_objs[3]
tab_options = _tab_objs[4]
tab_maxpain = _tab_objs[5]
tab_pcr     = _tab_objs[6]

# ── TAB 1: GAP SCANNER ────────────────────────────────────────────────────
with tab_gap:
    st.subheader("📊 Overnight Gap Scanner — Nifty 50")
    st.caption("Shows stocks with opening gap ≥ 0.5%. Run at 9:15 AM for best results.")

    col_gap_thresh, col_gap_btn = st.columns([2, 1])
    with col_gap_thresh:
        _gap_min = st.slider("Minimum gap %", 0.25, 5.0, 0.5, 0.25, key="gap_min_slider")
    with col_gap_btn:
        st.write("")
        st.write("")
        _run_gap = st.button("🔍 Scan Gaps", type="primary", key="run_gap_btn")

    @st.cache_data(ttl=600, show_spinner=False)
    def _cached_gaps(min_pct: float):
        from trading.gap_scanner import get_nifty50_gaps
        return get_nifty50_gaps(min_gap_pct=min_pct)

    if _run_gap or st.session_state.get("gap_scanned"):
        st.session_state["gap_scanned"] = True
        with st.spinner("Scanning Nifty 50 for gaps…"):
            _gap_df = _cached_gaps(_gap_min)

        if _gap_df.empty:
            st.info(f"No stocks with gap ≥ {_gap_min}% today. Market opened flat.")
        else:
            # Summary metrics
            _gup   = _gap_df[_gap_df["gap_pct"] > 0]
            _gdown = _gap_df[_gap_df["gap_pct"] < 0]
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Total Gapped",    len(_gap_df))
            c2.metric("Gap Ups ↑",       len(_gup),   delta=f"{len(_gup)} stocks")
            c3.metric("Gap Downs ↓",     len(_gdown), delta=f"-{len(_gdown)} stocks",
                      delta_color="inverse")
            c4.metric("Largest Gap",
                      f"{_gap_df['gap_pct'].abs().max():.1f}%",
                      delta=_gap_df.iloc[0]['ticker'])

            # Color-coded table
            _disp = _gap_df[["emoji","ticker","prev_close","today_open",
                              "gap_pct","change_pct","vol_ratio","category","strategy"]].copy()
            _disp.columns = ["","Ticker","Prev Close","Open","Gap %","Day Chg %",
                              "Vol Ratio","Category","Intraday Strategy"]

            def _color_gap(val):
                try:
                    v = float(val)
                    if v >= 1.5:  return "background-color:#1a3a2a; color:#4caf50"
                    if v > 0:     return "background-color:#1a2a1a; color:#a5d6a7"
                    if v <= -1.5: return "background-color:#3a1a1a; color:#ef5350"
                    if v < 0:     return "background-color:#2a1a1a; color:#ef9a9a"
                except (ValueError, TypeError):
                    pass  # non-numeric cell — return empty style
                return ""

            styled = _disp.style.map(_color_gap, subset=["Gap %","Day Chg %"])
            st.dataframe(styled, hide_index=True, width="stretch", height=400)

            # Gap distribution bar chart
            _gap_chart_df = _gap_df.sort_values("gap_pct")
            fig_gap = go.Figure(go.Bar(
                x=_gap_chart_df["ticker"].str.replace(".NS","",regex=False),
                y=_gap_chart_df["gap_pct"],
                marker_color=[
                    "#4caf50" if g > 0 else "#ef5350"
                    for g in _gap_chart_df["gap_pct"]
                ],
                text=_gap_chart_df["gap_pct"].apply(lambda x: f"{x:+.1f}%"),
                textposition="outside",
            ))
            fig_gap.update_layout(
                template="nse_pro", height=320,
                title="Gap % Distribution — Nifty 50",
                xaxis_title="Stock", yaxis_title="Gap %",
                showlegend=False,
                yaxis=dict(zeroline=True, zerolinecolor="#666", zerolinewidth=2),
            )
            st.plotly_chart(fig_gap, width="stretch")
    else:
        st.info("Click **🔍 Scan Gaps** to load today's gap data.")

# ── TAB 2: INTRADAY CHART ─────────────────────────────────────────────────
with tab_chart:
    st.subheader("📈 Intraday Chart — CPR + ORB + AVWAP + Supertrend")

    _ic_search_opts = sorted(
        f"{name}  ({sym.replace('.NS', '')})"
        for name, sym in STOCK_SEARCH_MAP.items()
    )
    _IC_PLACEHOLDER = "— type to search —"

    # FIX IC1: the dropdown and the manual ticker box were independent
    # widgets with no relationship — picking a dropdown stock left old text
    # sitting in the manual box, which silently took priority in the
    # "Resolve ticker" logic below, so a new dropdown pick had no visible
    # effect if the manual box still held something from an earlier search.
    # Same on_change + clear-pending pattern already used (and verified) in
    # dashboard/pages/04_analyze_stock.py's search boxes. The clear-pending
    # flag (rather than writing session_state directly in the button block)
    # is required because Streamlit raises "cannot be modified after the
    # widget ... is instantiated" once a widget has already rendered in the
    # current script run.
    if st.session_state.pop("_ic_clear_pending", False):
        st.session_state["ic_search_select"] = _IC_PLACEHOLDER
        st.session_state["ic_manual"] = ""

    def _ic_on_dropdown_change():
        if st.session_state.get("ic_search_select", _IC_PLACEHOLDER) != _IC_PLACEHOLDER:
            st.session_state["ic_manual"] = ""

    def _ic_on_manual_change():
        if st.session_state.get("ic_manual", "").strip():
            st.session_state["ic_search_select"] = _IC_PLACEHOLDER

    _ic_c1, _ic_c1b, _ic_c1c, _ic_c2, _ic_c3 = st.columns([3, 2, 1, 1, 1])
    with _ic_c1:
        _ic_sel = st.selectbox(
            "Search stock",
            options=[_IC_PLACEHOLDER] + _ic_search_opts,
            index=0, key="ic_search_select",
            on_change=_ic_on_dropdown_change,
        )
    with _ic_c1b:
        _ic_manual = st.text_input(
            "Or type ticker", value="", placeholder="e.g. TCS",
            key="ic_manual",
            on_change=_ic_on_manual_change,
        ).strip().upper()
    with _ic_c1c:
        st.write("")
        st.write("")
        if st.button("✖", key="ic_clear_search", use_container_width=True,
                      help="Clear search"):
            st.session_state["_ic_clear_pending"] = True
            st.rerun()
    with _ic_c2:
        _ic_interval = st.selectbox("Interval", ["5m","15m","30m"], key="ic_interval")
    with _ic_c3:
        _ic_days = st.selectbox("Days", [1, 2, 3, 5], index=2, key="ic_days")
        st.write("")
        _ic_load = st.button("📈 Load Chart", type="primary", key="ic_load")

    # Resolve ticker — manual entry wins, else dropdown selection, else default
    if _ic_manual:
        _ic_ticker = _ic_manual
    elif _ic_sel != _IC_PLACEHOLDER:
        _ic_ticker = _ic_sel.rsplit("(", 1)[-1].rstrip(")")
    else:
        _ic_ticker = "RELIANCE"

    @st.cache_data(ttl=180, show_spinner=False)
    def _load_intraday_chart(tkr: str, intv: str, days: int):
        from data.fetcher import fetch_intraday
        from utils.indicators import add_all_indicators, add_anchored_vwap
        df = fetch_intraday(tkr, interval=intv, days=days)
        df = add_all_indicators(df)
        df = add_anchored_vwap(df)
        return df

    if _ic_load or st.session_state.get("ic_last") == _ic_ticker:
        st.session_state["ic_last"] = _ic_ticker
        _sym = _ic_ticker if _ic_ticker.endswith(".NS") else _ic_ticker + ".NS"
        try:
            with st.spinner(f"Loading {_ic_interval} chart for {_ic_ticker}…"):
                _ic_df = _load_intraday_chart(_sym, _ic_interval, _ic_days)

            if _ic_df.empty:
                st.warning("No intraday data returned. Try a different ticker or interval.")
            else:
                from trading.intraday_signals import compute_orb
                _orb = compute_orb(_ic_df, orb_minutes=15)

                # Get latest CPR values (same for whole day)
                _cpr_tc  = float(_ic_df["CPR_TC"].iloc[-1])  if "CPR_TC"  in _ic_df.columns else None
                _cpr_bc  = float(_ic_df["CPR_BC"].iloc[-1])  if "CPR_BC"  in _ic_df.columns else None
                _pivot   = float(_ic_df["Pivot"].iloc[-1])   if "Pivot"   in _ic_df.columns else None
                _r1      = float(_ic_df["R1"].iloc[-1])      if "R1"      in _ic_df.columns else None
                _s1      = float(_ic_df["S1"].iloc[-1])      if "S1"      in _ic_df.columns else None
                _r2      = float(_ic_df["R2"].iloc[-1])      if "R2"      in _ic_df.columns else None
                _s2      = float(_ic_df["S2"].iloc[-1])      if "S2"      in _ic_df.columns else None

                fig_ic = make_subplots(
                    rows=2, cols=1, shared_xaxes=True,
                    vertical_spacing=0.05, row_heights=[0.75, 0.25]
                )

                # Candlestick
                fig_ic.add_trace(go.Candlestick(
                    x=_ic_df.index,
                    open=_ic_df["Open"], high=_ic_df["High"],
                    low=_ic_df["Low"],   close=_ic_df["Close"],
                    name=_ic_ticker, increasing_line_color="#26a69a",
                    decreasing_line_color="#ef5350",
                ), row=1, col=1)

                # Anchored VWAP
                if "AVWAP" in _ic_df.columns:
                    fig_ic.add_trace(go.Scatter(
                        x=_ic_df.index, y=_ic_df["AVWAP"],
                        line=dict(color="#FFD700", width=1.5, dash="solid"),
                        name="AVWAP", opacity=0.9,
                    ), row=1, col=1)
                    if "AVWAP_SD1_Upper" in _ic_df.columns:
                        fig_ic.add_trace(go.Scatter(
                            x=_ic_df.index, y=_ic_df["AVWAP_SD1_Upper"],
                            line=dict(color="rgba(255,165,0,0.5)", width=1, dash="dot"),
                            name="VWAP+1σ", showlegend=False,
                        ), row=1, col=1)
                        fig_ic.add_trace(go.Scatter(
                            x=_ic_df.index, y=_ic_df["AVWAP_SD1_Lower"],
                            line=dict(color="rgba(255,165,0,0.5)", width=1, dash="dot"),
                            name="VWAP−1σ", fill="tonexty",
                            fillcolor="rgba(255,165,0,0.05)", showlegend=False,
                        ), row=1, col=1)

                # Supertrend
                if "Supertrend" in _ic_df.columns and "ST_Direction" in _ic_df.columns:
                    _bull_st = _ic_df[_ic_df["ST_Direction"] == 1]
                    _bear_st = _ic_df[_ic_df["ST_Direction"] == -1]
                    if not _bull_st.empty:
                        fig_ic.add_trace(go.Scatter(
                            x=_bull_st.index, y=_bull_st["Supertrend"],
                            mode="markers", marker=dict(size=3, color="#26a69a"),
                            name="ST Bull", showlegend=False,
                        ), row=1, col=1)
                    if not _bear_st.empty:
                        fig_ic.add_trace(go.Scatter(
                            x=_bear_st.index, y=_bear_st["Supertrend"],
                            mode="markers", marker=dict(size=3, color="#ef5350"),
                            name="ST Bear", showlegend=False,
                        ), row=1, col=1)

                # CPR levels as horizontal lines
                _level_defs = [
                    (_r2,    "#ff6b6b", "R2", "dash"),
                    (_r1,    "#ff9999", "R1", "dot"),
                    (_cpr_tc,"#64b5f6", "CPR TC", "solid"),
                    (_pivot, "#9e9e9e", "Pivot", "dot"),
                    (_cpr_bc,"#64b5f6", "CPR BC", "solid"),
                    (_s1,    "#81c784", "S1", "dot"),
                    (_s2,    "#4caf50", "S2", "dash"),
                ]
                for _lv, _lc, _ln, _ld in _level_defs:
                    if _lv and not pd.isna(_lv):
                        fig_ic.add_hline(
                            y=_lv, line_dash=_ld, line_color=_lc,
                            line_width=1, opacity=0.7,
                            annotation_text=_ln,
                            annotation_position="right",
                            annotation_font_color=_lc,
                            row=1,
                        )

                # ORB box
                if not pd.isna(_orb.get("orb_high", float("nan"))):
                    try:
                        import datetime as _dt
                        _first_date = _ic_df.index[0].date()
                        _orb_start  = _ic_df.index[0]
                        _orb_end_t  = _dt.datetime.combine(_first_date, _dt.time(9, 29))
                        _orb_end_t  = _orb_end_t.replace(tzinfo=_orb_start.tzinfo)
                        _orb_end_idx = _ic_df.index[_ic_df.index <= _orb_end_t][-1] if len(_ic_df.index[_ic_df.index <= _orb_end_t]) else _ic_df.index[2]
                    except Exception:
                        _orb_start   = _ic_df.index[0]
                        _orb_end_idx = _ic_df.index[min(3, len(_ic_df)-1)]
                    fig_ic.add_vrect(
                        x0=_orb_start, x1=_orb_end_idx,
                        fillcolor="rgba(255,255,0,0.07)",
                        layer="below", line_width=0,
                        annotation_text="ORB Zone",
                        annotation_position="top left",
                    )
                    fig_ic.add_hline(y=_orb["orb_high"], line_dash="dash",
                                     line_color="#ffeb3b", line_width=1.5,
                                     annotation_text=f"ORB H {_orb['orb_high']:.2f}",
                                     annotation_position="right")
                    fig_ic.add_hline(y=_orb["orb_low"], line_dash="dash",
                                     line_color="#ff9800", line_width=1.5,
                                     annotation_text=f"ORB L {_orb['orb_low']:.2f}",
                                     annotation_position="right")

                # Volume subplot
                fig_ic.add_trace(go.Bar(
                    x=_ic_df.index, y=_ic_df["Volume"],
                    name="Volume",
                    marker_color=[
                        "#26a69a" if c >= o else "#ef5350"
                        for c, o in zip(_ic_df["Close"], _ic_df["Open"])
                    ],
                    opacity=0.7,
                ), row=2, col=1)

                fig_ic.update_layout(
                    template="nse_pro", height=680,
                    title=f"{_ic_ticker} — {_ic_interval} Chart | CPR + ORB + AVWAP",
                    xaxis_rangeslider_visible=False,
                    showlegend=True,
                    legend=dict(orientation="h", yanchor="bottom", y=1.02),
                    margin=dict(l=0, r=80, t=60, b=0),
                )
                st.plotly_chart(fig_ic, width="stretch")

                # CPR summary cards
                if _pivot and _cpr_tc and _cpr_bc:
                    _cur_price = float(_ic_df["Close"].iloc[-1])
                    _cpr_zone  = str(_ic_df["Price_vs_CPR"].iloc[-1]) if "Price_vs_CPR" in _ic_df.columns else "unknown"
                    _cpr_bias  = "🟢 Bullish (above CPR)" if _cpr_zone == "above" else ("🔴 Bearish (below CPR)" if _cpr_zone == "below" else "🟡 Inside CPR — wait for breakout")
                    _cpr_w     = float(_ic_df["CPR_Width_Pct"].iloc[-1]) if "CPR_Width_Pct" in _ic_df.columns else 0
                    _day_type  = "Narrow CPR (directional day expected)" if _cpr_w < 0.3 else "Wide CPR (sideways / volatile day)"

                    _cc1, _cc2, _cc3, _cc4, _cc5 = st.columns(5)
                    _cc1.metric("Pivot", f"₹{_pivot:.1f}")
                    _cc2.metric("CPR Top", f"₹{_cpr_tc:.1f}")
                    _cc3.metric("CPR Bottom", f"₹{_cpr_bc:.1f}")
                    _cc4.metric("Price vs CPR", _cpr_bias)
                    _cc5.metric("CPR Width", f"{_cpr_w:.2f}%", delta=_day_type)

                # ORB summary
                if not pd.isna(_orb.get("orb_high", float("nan"))):
                    st.markdown("---")
                    _oc1, _oc2, _oc3, _oc4 = st.columns(4)
                    _oc1.metric("ORB High",  f"₹{_orb['orb_high']:.2f}")
                    _oc2.metric("ORB Low",   f"₹{_orb['orb_low']:.2f}")
                    _oc3.metric("ORB Range", f"{_orb['orb_range_pct']:.2f}%",
                                delta="Narrow" if _orb.get("narrow") else "Normal")
                    _oc4.metric("Open Price", f"₹{_orb.get('open_price',0):.2f}")

        except Exception as _ic_err:
            st.error(f"Could not load intraday data: {_ic_err}")
            st.caption("Yahoo Finance intraday data is limited to recent days and may be unavailable for some tickers.")
    else:
        st.info("Enter a ticker and click **📈 Load Chart** to view intraday data.")

# ── TAB 3: ORB SETUP ─────────────────────────────────────────────────────
with tab_orb:
    st.subheader("⚡ Opening Range Breakout (ORB) — How to Trade It")
    st.markdown("""
    **ORB Strategy:** Define the first **15 minutes** of trading (9:15–9:30 AM IST) as the *Opening Range*.
    Trade the breakout when price moves outside this range with strong volume.

    | Setup | Trigger | Stop | Target | Best When |
    |-------|---------|------|--------|-----------|
    | **BUY ORB** | Close above ORB High on 5m/15m candle | Below ORB Low | ORB High + 1.5× range | Gap-up day, strong market |
    | **SHORT ORB** | Close below ORB Low on 5m/15m candle | Above ORB High | ORB Low − 1.5× range | Gap-down day, weak market |

    **Filters that improve win rate:**
    - Volume on breakout bar > 1.5× opening range average
    - India VIX < 22 (not in fear regime)
    - Stock is in same direction as Nifty
    - Narrow CPR (< 0.3% width) = directional day expected
    """)

    st.markdown("---")
    st.subheader("ORB Quick Reference — Nifty 50 Watchlist")
    st.caption("Paste tickers below, click Scan to see today's ORB levels.")

    _orb_tickers_input = st.text_area(
        "Tickers (one per line)",
        value="RELIANCE.NS\nTCS.NS\nHDFCBANK.NS\nINFY.NS\nICICIBANK.NS",
        height=120,
        key="orb_tickers_input",
    )
    _orb_scan_btn = st.button("⚡ Compute ORB Levels", key="orb_scan_btn")

    if _orb_scan_btn:
        _orb_tickers = [t.strip() for t in _orb_tickers_input.split("\n") if t.strip()]
        _orb_rows = []
        _orb_prog = st.progress(0)
        for _oi, _ot in enumerate(_orb_tickers):
            try:
                from data.fetcher import fetch_intraday
                from utils.indicators import add_all_indicators, add_anchored_vwap
                from trading.intraday_signals import compute_orb
                _sym = _ot if _ot.endswith(".NS") else _ot + ".NS"
                _idf = fetch_intraday(_sym, interval="5m", days=1)
                _idf = add_anchored_vwap(_idf)
                _orb_r = compute_orb(_idf, 15)
                _cz = str(_idf["Price_vs_CPR"].iloc[-1]) if "Price_vs_CPR" in _idf.columns else "?"
                _av = round(float(_idf["AVWAP"].iloc[-1]), 2) if "AVWAP" in _idf.columns else None
                _cp = round(float(_idf["Close"].iloc[-1]), 2)
                _orb_rows.append({
                    "Ticker":    _ot.replace(".NS",""),
                    "Price":     _cp,
                    "ORB High":  _orb_r.get("orb_high","—"),
                    "ORB Low":   _orb_r.get("orb_low","—"),
                    "Range %":   _orb_r.get("orb_range_pct","—"),
                    "AVWAP":     _av,
                    "CPR Zone":  _cz,
                    "Day Type":  "Narrow⚡" if _orb_r.get("narrow") else "Normal",
                })
            except Exception as _oe:
                _orb_rows.append({"Ticker": _ot.replace(".NS",""), "Price":"err", "ORB High":"—",
                                  "ORB Low":"—","Range %":"—","AVWAP":"—","CPR Zone":"—","Day Type":"error"})
            _orb_prog.progress((_oi+1)/len(_orb_tickers))
        _orb_prog.empty()
        if _orb_rows:
            st.dataframe(pd.DataFrame(_orb_rows), hide_index=True, width="stretch")

# ── TAB 4: LIVE INTRADAY SIGNALS ─────────────────────────────────────────
with tab_sigs:
    st.subheader("🎯 Live Intraday Signals — scan a list (ORB + VWAP + Supertrend)")

    # Data-source indicator — intraday data prefers Angel One (real-time)
    try:
        from data.angel_fetcher import is_configured as _ls_ao_ok
        _ls_ao = _ls_ao_ok()
    except Exception:
        _ls_ao = False
    if _ls_ao:
        st.markdown('<span class="pill-green">⚡ Live data: Angel One (real-time, no rate limits)</span>',
                    unsafe_allow_html=True)
    else:
        st.markdown('<span class="pill-yellow">Angel One not connected — falling back to Yahoo '
                    '(15-min delayed). Connect in <b>Tools › Angel One</b> for real-time intraday.</span>',
                    unsafe_allow_html=True)
    st.caption("Scans every stock in your list for ORB breakout / VWAP / Supertrend signals on the latest bar. "
               "Best 9:30–11:00 AM and after 2 PM.")

    _ls_def = "RELIANCE\nTCS\nHDFCBANK\nICICIBANK\nINFY\nSBIN\nBHARTIARTL\nAXISBANK\nLT\nMARUTI"
    _ls_c1, _ls_c2 = st.columns([3, 1])
    with _ls_c1:
        _ls_list_raw = st.text_area("Stocks to scan (one per line)",
                                    value=_ls_def, height=150, key="ls_scan_list")
    with _ls_c2:
        _ls_interval = st.selectbox("Interval", ["5m", "15m"], key="ls_interval")
        _ls_btn = st.button("🎯 Scan All", type="primary", key="ls_scan_all",
                            width="stretch")

    if _ls_btn:
        _ls_tickers = [t.strip().upper() for t in _ls_list_raw.split("\n") if t.strip()]
        _rows, _fired = [], []
        _prog = st.progress(0, text="Scanning…")
        from trading.intraday_signals import scan_intraday
        for _i, _t in enumerate(_ls_tickers):
            _sym = _t if _t.endswith(".NS") else _t + ".NS"
            try:
                _res = scan_intraday(_sym, interval=_ls_interval)
                if "error" in _res:
                    _rows.append({"Stock": _t, "Price": None, "Trend": "—",
                                  "CPR": "—", "Signal": "no data"})
                else:
                    _sigs = _res.get("signals", [])
                    _sig_txt = ", ".join(f'{s.get("action","")} {s.get("screen","")}'
                                         for s in _sigs) if _sigs else "—"
                    _rows.append({
                        "Stock":  _t,
                        "Price":  round(_res.get("price", 0), 2),
                        "Trend":  "🟢 Bull" if _res.get("st_dir", 0) == 1 else "🔴 Bear",
                        "CPR":    str(_res.get("cpr_zone", "?")).replace("_", " ").title(),
                        "Signal": _sig_txt,
                    })
                    for s in _sigs:
                        _fired.append((_t, _sym, s))
            except Exception:
                _rows.append({"Stock": _t, "Price": None, "Trend": "—",
                              "CPR": "—", "Signal": "err"})
            _prog.progress((_i + 1) / max(len(_ls_tickers), 1),
                           text=f"Scanned {_t} ({_i+1}/{len(_ls_tickers)})")
        _prog.empty()

        # ── Active signals first (with one-click paper trade) ──────────────
        if _fired:
            st.success(f"✅ {len(_fired)} live signal(s) across {len(_ls_tickers)} stocks")
            for _t, _sym, _sig in _fired:
                _act  = _sig.get("action", "")
                _clr  = "card-green" if _act == "BUY" else "card-red"
                _icon = "🟢" if _act == "BUY" else "🔴"
                _p    = _sig.get("price", 0); _sl = _sig.get("sl", 0)
                _tp   = _sig.get("tp", 0);    _rr = _sig.get("rr_ratio", 0)
                st.markdown(
                    f'<div class="{_clr}">'
                    f'<span class="signal-big">{_icon} {_t} — {_display_label(_act)} ({_sig.get("screen","")})</span><br>'
                    f'<b>Entry</b> ₹{_p:,.2f} &nbsp;|&nbsp; <b>SL</b> ₹{_sl:,.2f} &nbsp;|&nbsp; '
                    f'<b>TP</b> ₹{_tp:,.2f} &nbsp;|&nbsp; <b>R:R</b> {_rr:.1f}x<br>'
                    f'<small>{_sig.get("reason","")}</small></div>',
                    unsafe_allow_html=True,
                )
                if _act == "BUY" and _p > 0:
                    _paper_trade_popover(_sym, _p, _sl, _tp,
                                         reason=f"Intraday {_sig.get('screen','')}: {_sig.get('reason','')[:50]}",
                                         key=f"ls_pt_{_sym}", label=f"📌 Paper Trade {_t}")
        else:
            st.info("No active intraday signals right now across the list.")

        # ── Full scan table ────────────────────────────────────────────────
        st.markdown("#### 📋 Full scan")
        if _rows:
            st.dataframe(pd.DataFrame(_rows), hide_index=True, width="stretch")
    else:
        st.info("Add stocks (one per line) and click **🎯 Scan All**.")

# NOTE: the "Live Positions — Angel One" tab that used to live here has been
# removed as a duplicate. Real-time Angel One positions (MIS + CNC), along
# with holdings, funds, orders/trades, and quick order placement, all live
# on the dedicated 🔗 Angel One page.

# ── TAB 5: Options Strategy Selector (FIX MERGE1 — from old OI & Options page) ──
with tab_options:
    st.subheader("Options Strategy Selector")
    st.caption(
        "IV regime (VIX-based) + directional bias → right strategy.  "
        "Max Pain calculator + PCR zone reference for expiry planning."
    )
    vix_val = (get_vix_info() or {}).get("vix")

    c1, c2 = st.columns(2)
    with c1:
        direction = st.selectbox(
            "Your Directional Bias",
            ["Strongly Bullish", "Mildly Bullish", "Neutral / Range-bound",
             "Mildly Bearish", "Strongly Bearish"],
            key="opts_dir",
        )
    with c2:
        curr_vix_opt = st.number_input(
            "India VIX (current)", min_value=5.0, max_value=80.0,
            value=float(vix_val) if vix_val else 18.0, step=0.5, key="opts_vix",
        )

    ivr_proxy = min(100, max(0, (curr_vix_opt - 10) / (35 - 10) * 100))
    iv_regime = "Low" if ivr_proxy < 40 else ("Normal" if ivr_proxy < 65 else "High")

    _smap = {
        ("Strongly Bullish",      "Low"):    ("Long Call (ATM)",        "Buy 1 ATM CE, 20–45 DTE",                  "Low IVR = cheap premium — buy directional"),
        ("Strongly Bullish",      "Normal"): ("Bull Call Spread",       "Buy ATM CE + Sell OTM CE (1–2 strikes above)", "Spread cuts cost at normal IV"),
        ("Strongly Bullish",      "High"):   ("Bull Call Spread",       "Buy ATM CE + Sell OTM CE",                  "High IVR: spread essential — naked buy overpriced"),
        ("Mildly Bullish",        "Low"):    ("Bull Call Spread",       "Buy ATM CE + Sell OTM CE",                  "Defined risk for moderate bullish view"),
        ("Mildly Bullish",        "Normal"): ("Bull Call Spread",       "Buy ATM CE + Sell OTM CE",                  "Balanced IV — spread preferred"),
        ("Mildly Bullish",        "High"):   ("Cash-Secured Put (CSP)", "Sell OTM PE at key support strike",         "Collect rich premium; happy to own stock lower"),
        ("Neutral / Range-bound", "Low"):    ("Long Straddle",          "Buy ATM CE + ATM PE, same expiry",          "Expect big move but unsure of direction (event play)"),
        ("Neutral / Range-bound", "Normal"): ("Iron Condor",            "Sell OTM CE+PE + buy further OTM wings",    "Range-bound + normal IV = classic condor setup"),
        ("Neutral / Range-bound", "High"):   ("Iron Condor",            "Sell OTM CE+PE + buy further OTM wings",    "High IVR: sell rich premium in sideways market"),
        ("Mildly Bearish",        "Low"):    ("Bear Put Spread",        "Buy ATM PE + Sell OTM PE",                  "Defined-risk bearish at low IV"),
        ("Mildly Bearish",        "Normal"): ("Bear Put Spread",        "Buy ATM PE + Sell OTM PE",                  "Spread reduces debit"),
        ("Mildly Bearish",        "High"):   ("Bear Put Spread",        "Buy ATM PE + Sell deeper OTM PE",           "High IV: spread essential — naked put costly"),
        ("Strongly Bearish",      "Low"):    ("Long Put (ATM)",         "Buy 1 ATM PE, 20–45 DTE",                  "Strong conviction + cheap premium"),
        ("Strongly Bearish",      "Normal"): ("Bear Put Spread",        "Buy ATM PE + Sell OTM PE",                  "Spread for cost management"),
        ("Strongly Bearish",      "High"):   ("Bear Put Spread",        "Buy ATM PE + Sell OTM PE",                  "High IV: never buy naked options — use spreads"),
    }
    strat, setup, reason = _smap.get(
        (direction, iv_regime),
        ("Review setup", "Use defined-risk spreads", "Unclear IV regime"),
    )

    vbc = "#4CAF50" if curr_vix_opt < 16 else ("#FF9800" if curr_vix_opt < 25 else "#F44336")
    st.markdown(
        f'<div style="background:#1a1a2e;padding:18px;border-radius:10px;'
        f'border-left:5px solid {vbc};margin:12px 0">'
        f'<h3 style="margin:0;color:#fff">Recommended: {strat}</h3>'
        f'<p style="margin:6px 0;color:#ccc"><b>Setup:</b> {setup}</p>'
        f'<p style="margin:6px 0;color:#aaa"><b>Why:</b> {reason}</p>'
        f'<hr style="border-color:#333;margin:10px 0">'
        f'VIX: <b style="color:#fff">{curr_vix_opt:.1f}</b>  |  '
        f'IV Rank (proxy): <b style="color:#fff">{ivr_proxy:.0f}%</b>  |  '
        f'Regime: <b style="color:{vbc}">{iv_regime} IV</b>'
        f'</div>', unsafe_allow_html=True
    )

    st.markdown("---")
    st.subheader("Greeks Quick Reference")
    st.dataframe(pd.DataFrame([
        {"Greek": "Delta (Δ)", "Measures": "₹ change per ₹1 underlying move",   "Rule of Thumb": "ATM ≈ 0.50. OTM 2 strikes ≈ 0.30"},
        {"Greek": "Gamma (Γ)", "Measures": "Rate delta changes",                 "Rule of Thumb": "Highest near ATM + near expiry — P&L swings fast"},
        {"Greek": "Theta (Θ)", "Measures": "Daily time decay (₹)",              "Rule of Thumb": "ATM 30 DTE: ~0.3–0.5%/day. 7 DTE: ~1.5–2%/day"},
        {"Greek": "Vega (V)",  "Measures": "P&L change per 1% IV move",         "Rule of Thumb": "Long options lose value if IV collapses post-event"},
    ]), hide_index=True)

    st.markdown("---")
    st.subheader("NSE Lot Sizes *(verify quarterly)*")
    st.dataframe(pd.DataFrame([
        {"Contract": "Nifty 50",  "Lot Size": 75,  "Approx Margin": "₹1.0–1.5L"},
        {"Contract": "BankNifty", "Lot Size": 30,  "Approx Margin": "₹0.8–1.2L"},
        {"Contract": "FinNifty",  "Lot Size": 65,  "Approx Margin": "₹0.5–0.8L"},
        {"Contract": "RELIANCE",  "Lot Size": 250, "Approx Margin": "₹3–4L"},
        {"Contract": "HDFC Bank", "Lot Size": 550, "Approx Margin": "₹6–8L"},
        {"Contract": "TCS",       "Lot Size": 175, "Approx Margin": "₹6–8L"},
        {"Contract": "Infosys",   "Lot Size": 400, "Approx Margin": "₹5–6L"},
    ]), hide_index=True)

# ── TAB 6: Max Pain Calculator (FIX MERGE1 — from old OI & Options page) ──
with tab_maxpain:
    st.subheader("Max Pain Calculator")
    st.caption(
        "Max Pain = strike where option buyers lose the most (writers profit most).  "
        "Price gravitates toward Max Pain near expiry — strongest in the last hour."
    )

    strikes_inp = st.text_area("Strike prices (comma-separated)",
                                "24000,24100,24200,24300,24400,24500,24600", height=60)
    calls_inp   = st.text_area("Call OI at each strike (lots, comma-separated)",
                                "45000,75000,120000,95000,65000,42000,30000", height=60)
    puts_inp    = st.text_area("Put OI at each strike (lots, comma-separated)",
                                "35000,55000,100000,88000,58000,40000,22000", height=60)

    if st.button("🎯 Calculate Max Pain", type="primary", key="maxpain_btn"):
        try:
            sl = [float(x.strip()) for x in strikes_inp.split(",") if x.strip()]
            cl = [float(x.strip()) for x in calls_inp.split(",")   if x.strip()]
            pl = [float(x.strip()) for x in puts_inp.split(",")    if x.strip()]

            if len(sl) == len(cl) == len(pl) >= 2:
                oi_df = pd.DataFrame({"strike": sl, "call_oi": cl, "put_oi": pl})
                pain_vals = []
                for k in oi_df["strike"]:
                    cp = ((oi_df["strike"] - k).clip(lower=0) * oi_df["call_oi"]).sum()
                    pp = ((k - oi_df["strike"]).clip(lower=0) * oi_df["put_oi"]).sum()
                    pain_vals.append(cp + pp)
                oi_df["total_pain"] = pain_vals
                mp = float(oi_df.loc[oi_df["total_pain"].idxmin(), "strike"])

                st.success(f"🎯 **Max Pain Strike: {mp:,.0f}**")

                mp_fig = go.Figure()
                mp_fig.add_trace(go.Bar(x=oi_df["strike"].astype(str), y=oi_df["call_oi"],
                                        name="Call OI", marker_color="#ef5350"))
                mp_fig.add_trace(go.Bar(x=oi_df["strike"].astype(str), y=oi_df["put_oi"],
                                        name="Put OI", marker_color="#26a69a"))
                mp_fig.add_vline(x=str(int(mp)), line_dash="dash",
                                 line_color="#FFD700", line_width=2,
                                 annotation_text=f"Max Pain: {mp:,.0f}",
                                 annotation_font_color="#FFD700")
                mp_fig.update_layout(
                    template="nse_pro", barmode="group", height=340,
                    title="Call vs Put OI by Strike",
                    margin=dict(l=0, r=0, t=40, b=0),
                )
                st.plotly_chart(mp_fig, width="stretch")

                pcr_auto = sum(pl) / max(sum(cl), 1)
                st.metric("PCR (from your input)", f"{pcr_auto:.2f}",
                          help="Total Put OI / Total Call OI")
            else:
                st.error("All three lists must have the same length (>= 2 strikes).")
        except Exception as e:
            st.error(f"Calculation error: {e}")

# ── TAB 7: PCR Zone Reference (FIX MERGE1 — from old OI & Options page) ──
with tab_pcr:
    st.subheader("Put-Call Ratio (PCR) Zone Reference")
    st.caption("PCR = Total Put OI / Total Call OI. Contrarian indicator — extremes signal reversals.")

    pcr_input = st.slider("Current PCR (OI-based)", 0.3, 2.5, 1.0, 0.05, key="pcr_slider")

    if pcr_input < 0.6:
        pcr_sig, pcr_hex = "🔴 Extreme Complacency — too many call buyers. Contrarian BEARISH. Correction likely.", "#F44336"
    elif pcr_input < 0.8:
        pcr_sig, pcr_hex = "🟡 Mildly Bullish sentiment — neutral with slight upward tilt.", "#FF9800"
    elif pcr_input < 1.2:
        pcr_sig, pcr_hex = "🟢 Healthy range — no extreme reading, normal conditions.", "#4CAF50"
    elif pcr_input < 1.5:
        pcr_sig, pcr_hex = "🟡 Mildly Bearish — fear building. Caution on fresh longs.", "#FF9800"
    else:
        pcr_sig, pcr_hex = "🟢 Extreme Fear — too many put buyers. Contrarian BULLISH. Bounce setup.", "#4CAF50"

    st.markdown(
        f'<div style="background:{pcr_hex}22;padding:14px;border-radius:8px;'
        f'border-left:5px solid {pcr_hex};font-size:16px;margin:10px 0">'
        f'PCR = <b>{pcr_input:.2f}</b> → {pcr_sig}'
        f'</div>', unsafe_allow_html=True
    )

    st.markdown("---")
    st.dataframe(pd.DataFrame([
        {"PCR Value": "< 0.6",    "Sentiment": "Extreme complacency",  "Signal": "🔴 Contrarian bearish"},
        {"PCR Value": "0.6–0.8",  "Sentiment": "Mildly bullish",       "Signal": "🟡 Neutral/bullish tilt"},
        {"PCR Value": "0.8–1.2",  "Sentiment": "Healthy (normal)",     "Signal": "🟢 No extreme"},
        {"PCR Value": "1.2–1.5",  "Sentiment": "Mildly bearish",       "Signal": "🟡 Caution"},
        {"PCR Value": "> 1.5",    "Sentiment": "Extreme fear",         "Signal": "🟢 Contrarian bullish"},
    ]), hide_index=True)

    st.markdown("---")
    st.subheader("OI Price Interpretation Framework")
    st.dataframe(pd.DataFrame([
        {"Price": "↑ Rising", "OI": "↑ Rising",  "Meaning": "Long Buildup — fresh bulls entering",  "Signal": "🟢 Strongly Bullish"},
        {"Price": "↓ Falling","OI": "↑ Rising",  "Meaning": "Short Buildup — fresh bears entering", "Signal": "🔴 Strongly Bearish"},
        {"Price": "↑ Rising", "OI": "↓ Falling", "Meaning": "Short Covering — shorts buying back",  "Signal": "🟡 Bullish but weak"},
        {"Price": "↓ Falling","OI": "↓ Falling", "Meaning": "Long Unwinding — longs exiting",       "Signal": "🟡 Bearish but weak"},
    ]), hide_index=True)
    st.caption(
        "Key: Long Buildup (Price ↑ + OI ↑) is the strongest bullish signal. "
        "Short Covering (Price ↑ + OI ↓) is weaker — shorts exiting, not fresh bulls."
    )


# ═══════════════════════════════════════════════════════════════════════════════
# PAGE 12 — POSITION SIZER  [NEW]
# ═══════════════════════════════════════════════════════════════════════════════
