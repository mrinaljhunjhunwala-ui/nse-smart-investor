"""
dashboard/pages/18_tqs_scanner.py
Trend Quality Score (TQS) — Scanner + Deep Dive page.

Two modes:
  1. Scanner  — score a universe of tickers, rank by TQS, show heatmap
  2. Deep Dive — single stock: pillar breakdown, time-series chart, key indicators
"""

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from dashboard.shared.nav import render_sidebar
from dashboard.shared.design import apply_design


# ── Page config ───────────────────────────────────────────────────────────────
apply_design()
render_sidebar()

st.title("📊 Trend Quality Score")
st.caption(
    "Measures trend **health and persistence** across 4 pillars (max 90 pts). "
    "Validated baseline: +0.41 rank correlation with staying in an uptrend next month."
)

# ── Lazy import engine ────────────────────────────────────────────────────────
@st.cache_resource(show_spinner=False)
def _load_engine():
    from analysis.trend_quality_score import (
        score_ticker, 
        scan_universe, 
        add_indicators, 
        fetch_data, 
        _score_all_pillars
    )
    return score_ticker, scan_universe, add_indicators, fetch_data, _score_all_pillars

try:
    score_ticker, scan_universe, add_indicators, fetch_data, _score_all_pillars = _load_engine()
    ENGINE_OK = True
except Exception as e:
    st.error(f"TQS engine failed to load: {e}")
    ENGINE_OK = False
    st.stop()


# ── Default configurations ───────────────────────────────────────────────────
DEFAULT_TICKERS = [
    "RELIANCE.NS", "TCS.NS",        "HDFCBANK.NS",   "INFY.NS",
    "ICICIBANK.NS","HINDUNILVR.NS",  "ITC.NS",        "SBIN.NS",
    "BHARTIARTL.NS","KOTAKBANK.NS",  "AXISBANK.NS",   "WIPRO.NS",
    "MARUTI.NS",   "TITAN.NS",       "ASIANPAINT.NS", "NESTLEIND.NS",
    "SUNPHARMA.NS","HCLTECH.NS",     "LT.NS",         "ULTRACEMCO.NS",
]

SIGNAL_COLOUR = {
    "STRONG TREND": "#16a34a",
    "TRENDING":     "#65a30d",
    "NEUTRAL":      "#ca8a04",
    "WEAK":         "#ea580c",
    "AVOID":        "#dc2626",
}

GRADE_COLOUR = {
    "A+": "#16a34a", "A": "#65a30d", "B": "#ca8a04",
    "C":  "#ea580c", "D": "#dc2626", "F": "#991b1b",
}


# ── Tabs ──────────────────────────────────────────────────────────────────────
tab_scan, tab_deep = st.tabs(["🔍 Scanner", "🔬 Deep Dive"])


# ═════════════════════════════════════════════════════════════════════════════
# TAB 1 — SCANNER
# ═════════════════════════════════════════════════════════════════════════════
with tab_scan:
    st.subheader("Universe Scanner")

    col1, col2 = st.columns([3, 1])
    with col1:
        raw_input = st.text_area(
            "Tickers (comma or newline separated)",
            value=", ".join(DEFAULT_TICKERS),
            height=100,
        )
    with col2:
        period = st.selectbox("Period", ["1y", "2y", "5y"], index=0, key="scan_period")
        min_tqs = st.slider("Min TQS filter", 0, 90, 0, step=5)
        run_scan = st.button("▶ Run Scan", width="stretch", type="primary")

    if run_scan:
        tickers = [t.strip().upper() for t in raw_input.replace("\n", ",").split(",") if t.strip()]
        if not tickers:
            st.warning("Enter at least one ticker.")
        else:
            rows = []
            prog = st.progress(0, text="Scanning…")
            import logging as _tqs_log
            for i, t in enumerate(tickers):
                try:
                    r = score_ticker(t, period=period)
                    rows.append(r.as_dict())
                except Exception as _tqs_e:
                    _tqs_log.getLogger("dashboard.tqs_scanner").debug("score_ticker(%s) failed: %s — skipped", t, _tqs_e)
                prog.progress((i + 1) / len(tickers), text=f"Scored {t}")
            prog.empty()

            if not rows:
                st.error("No data returned for any ticker.")
            else:
                df_scan = (
                    pd.DataFrame(rows)
                    .sort_values("tqs", ascending=False)
                    .reset_index(drop=True)
                )
                df_scan = df_scan[df_scan["tqs"] >= min_tqs]
                st.session_state["tqs_scan"] = df_scan

    # ── Display results ───────────────────────────────────────────────────────
    if "tqs_scan" in st.session_state:
        df_scan = st.session_state["tqs_scan"]
        
        if df_scan.empty:
            st.info("No tickers match the active minimum TQS filter.")
        else:
            total = len(df_scan)
            strong = (df_scan["signal"] == "STRONG TREND").sum()
            trending = (df_scan["signal"] == "TRENDING").sum()
            avoid = (df_scan["signal"] == "AVOID").sum()

            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Stocks Scored", total)
            m2.metric("Strong Trend", strong)
            m3.metric("Trending", trending)
            m4.metric("Avoid", avoid)

            st.divider()

            # Color styling helper functions
            def _colour_signal(val):
                c = SIGNAL_COLOUR.get(str(val).upper(), "#6b7280")
                return f"color: {c}; font-weight: 600"

            def _colour_grade(val):
                c = GRADE_COLOUR.get(str(val).upper(), "#6b7280")
                return f"color: {c}; font-weight: 700"

            def _bar_tqs(val):
                try:
                    val_float = float(val)
                    pct = max(0.0, min(100.0, (val_float / 90.0) * 100))
                except (ValueError, TypeError):
                    pct = 0
                return f"background: linear-gradient(90deg, rgba(59, 130, 246, 0.4) {pct:.0f}%, transparent {pct:.0f}%)"

            display_cols = [
                "ticker", "close", "tqs", "grade", "signal",
                "p1_strength", "p2_persistence", "p3_momentum", "p4_confirmation",
                "rsi", "sharpe_20", "obv_z",
            ]
            
            # Sub-select columns present in DataFrame to avoid KeyError issues
            actual_cols = [col for col in display_cols if col in df_scan.columns]
            
            # Create a clean, renamed dataframe first to simplify styled subset references
            df_display = df_scan[actual_cols].rename(columns={
                "ticker": "Ticker", "close": "Close", "tqs": "TQS",
                "grade": "Grade", "signal": "Signal",
                "p1_strength": "P1 Strength", "p2_persistence": "P2 Persist",
                "p3_momentum": "P3 Momentum", "p4_confirmation": "P4 Volume",
                "rsi": "RSI", "sharpe_20": "Sharpe20", "obv_z": "OBV-Z",
            })

            # Format and apply styling safely
            styled = (
                df_display.style
                .map(_colour_signal, subset=["Signal"] if "Signal" in df_display.columns else [])
                .map(_colour_grade,  subset=["Grade"] if "Grade" in df_display.columns else [])
                .apply(lambda col: [_bar_tqs(v) for v in col], subset=["TQS"] if "TQS" in df_display.columns else [])
                .format({
                    "Close": "₹{:,.2f}", "TQS": "{:.1f}",
                    "P1 Strength": "{:.1f}", "P2 Persist": "{:.1f}",
                    "P3 Momentum": "{:.1f}", "P4 Volume": "{:.1f}",
                    "RSI": "{:.1f}", "Sharpe20": "{:.2f}", "OBV-Z": "{:.2f}",
                }, na_rep="-")
            )
            st.dataframe(styled, width="stretch", height=500)

            # ── Pillar breakdown — top 10 ─────────────────────────────────────
            st.subheader("Pillar breakdown — top 10")
            top10 = df_scan.head(10)
            fig = go.Figure()
            pillars = ["p1_strength", "p2_persistence", "p3_momentum", "p4_confirmation"]
            labels  = ["P1 Strength", "P2 Persistence", "P3 Momentum", "P4 Volume"]
            colours = ["#3b82f6", "#10b981", "#f59e0b", "#8b5cf6"]

            for pillar, label, colour in zip(pillars, labels, colours):
                if pillar in top10.columns:
                    fig.add_trace(go.Bar(
                        name=label,
                        x=top10["ticker"],
                        y=top10[pillar],
                        marker_color=colour,
                    ))

            fig.update_layout(
                barmode="stack",
                xaxis_title="Ticker",
                yaxis_title="Score",
                yaxis_range=[0, 90],
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                margin=dict(t=40, b=40, l=10, r=10),
                height=380,
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)"
            )
            st.plotly_chart(fig, width="stretch")

            # ── Download ──────────────────────────────────────────────────────
            st.download_button(
                "⬇ Download CSV",
                data=df_scan.to_csv(index=False),
                file_name="tqs_scan.csv",
                mime="text/csv",
                width="content"
            )
    else:
        st.info("Input your universe parameters and select 'Run Scan' above to process trend scores.")


# ═════════════════════════════════════════════════════════════════════════════
# TAB 2 — DEEP DIVE
# ═════════════════════════════════════════════════════════════════════════════
with tab_deep:
    st.subheader("Single Stock Deep Dive")

    col1, col2, col3 = st.columns([2, 1, 1])
    with col1:
        # Retrieve the user's active watchlist from session state
        watchlist_tickers = st.session_state.get("watchlist", [])
        
        # Combine the watchlist and DEFAULT_TICKERS, removing duplicates
        available_tickers = list(dict.fromkeys(watchlist_tickers + DEFAULT_TICKERS))
        
        # 1. Dropdown Selector
        dd_ticker_selected = st.selectbox("Select Ticker", options=available_tickers, index=0)
        
        # 2. Autocomplete override
        custom_ticker = st.text_input(
            "Or enter a custom ticker (e.g. WIPRO.NS)", 
            value="", 
            placeholder="Type here to override dropdown selection"
        ).upper().strip()
        
        # Resolve the active ticker: use custom input if populated, else the dropdown
        dd_ticker = custom_ticker if custom_ticker else dd_ticker_selected

    with col2:
        dd_period = st.selectbox("History", ["1y", "2y", "5y"], index=1, key="dd_period")
    with col3:
        st.write("")
        st.write("")
        run_deep = st.button("▶ Analyse", width="stretch", type="primary")

    if run_deep and dd_ticker:
        with st.spinner(f"Scoring {dd_ticker}…"):
            try:
                df_raw  = fetch_data(dd_ticker, period=dd_period)
                df_ind  = add_indicators(df_raw)
                df_tqs  = _score_all_pillars(df_ind).dropna(subset=["TQS"])
                latest  = score_ticker(dd_ticker, period=dd_period)
                st.session_state["tqs_deep"] = (df_tqs, latest)
            except Exception as e:
                st.error(f"Could not score {dd_ticker}: {e}")

    if "tqs_deep" in st.session_state:
        df_tqs, r = st.session_state["tqs_deep"]

        # ── Scorecard header ──────────────────────────────────────────────────
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("TQS", f"{r.tqs:.1f} / 90")
        c2.metric("Grade", r.grade())
        c3.metric("Signal", r.signal())
        c4.metric("RSI", f"{r.rsi:.1f}")
        c5.metric("ADX", f"{r.adx:.1f}")

        st.divider()

        # ── Pillar gauges ─────────────────────────────────────────────────────
        st.markdown("**Pillar breakdown**")
        cols = st.columns(4)
        pillar_data = [
            ("P1 Trend Strength",    r.p1, "#3b82f6"),
            ("P2 Trend Persistence", r.p2, "#10b981"),
            ("P3 Momentum Quality",  r.p3, "#f59e0b"),
            ("P4 Tech Confirmation", r.p4, "#8b5cf6"),
        ]
        for col, (label, score, colour) in zip(cols, pillar_data):
            fig_g = go.Figure(go.Indicator(
                mode="gauge+number",
                value=score,
                title={"text": label, "font": {"size": 12}},
                gauge={
                    "axis": {"range": [0, 22.5], "tickfont": {"size": 10}},
                    "bar":  {"color": colour},
                    "steps": [
                        {"range": [0, 7.5],   "color": "rgba(241, 245, 249, 0.5)"},
                        {"range": [7.5, 15],  "color": "rgba(226, 232, 240, 0.5)"},
                        {"range": [15, 22.5], "color": "rgba(203, 213, 225, 0.5)"},
                    ],
                },
                number={"suffix": "/22.5", "font": {"size": 16}},
            ))
            fig_g.update_layout(
                height=180, 
                margin=dict(t=30, b=10, l=15, r=15),
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)"
            )
            col.plotly_chart(fig_g, width="stretch")

        # ── TQS time-series chart ─────────────────────────────────────────────
        st.markdown("**TQS over time**")
        fig_ts = go.Figure()

        fig_ts.add_trace(go.Scatter(
            x=df_tqs.index, y=df_tqs["TQS"],
            name="TQS", line=dict(color="#3b82f6", width=2),
            fill="tozeroy", fillcolor="rgba(59,130,246,0.08)",
        ))

        # Reference bands
        for y_val, label, colour in [
            (75, "Strong Trend", "#16a34a"),
            (60, "Trending",     "#65a30d"),
            (45, "Neutral",      "#ca8a04"),
            (30, "Weak",         "#ea580c"),
        ]:
            fig_ts.add_hline(
                y=y_val, line_dash="dot", line_color=colour, line_width=1,
                annotation_text=label, annotation_position="right",
                annotation_font_color=colour,
            )

        fig_ts.update_layout(
            xaxis_title="Date", yaxis_title="TQS",
            yaxis_range=[0, 95],
            legend=dict(orientation="h"),
            margin=dict(t=20, b=40, l=10, r=10),
            height=360,
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)"
        )
        st.plotly_chart(fig_ts, width="stretch")

        # ── Pillar time-series ────────────────────────────────────────────────
        st.markdown("**Pillar scores over time**")
        fig_p = go.Figure()
        for col_name, label, colour in [
            ("P1_Strength",     "P1 Strength",    "#3b82f6"),
            ("P2_Persistence",  "P2 Persistence", "#10b981"),
            ("P3_Momentum",     "P3 Momentum",    "#f59e0b"),
            ("P4_Confirmation", "P4 Volume",      "#8b5cf6"),
        ]:
            if col_name in df_tqs.columns:
                fig_p.add_trace(go.Scatter(
                    x=df_tqs.index, y=df_tqs[col_name],
                    name=label, line=dict(color=colour, width=1.5),
                ))
        fig_p.update_layout(
            xaxis_title="Date", yaxis_title="Pillar Score",
            yaxis_range=[0, 24],
            legend=dict(orientation="h"),
            margin=dict(t=20, b=40, l=10, r=10),
            height=300,
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)"
        )
        st.plotly_chart(fig_p, width="stretch")

        # ── Key indicator table ───────────────────────────────────────────────
        st.markdown("**Latest indicator values**")
        
        # Safe checks for metric validation
        rsi_val = getattr(r, 'rsi', 50.0)
        adx_val = getattr(r, 'adx', 20.0)
        sharpe_val = getattr(r, 'sharpe_20', 0.0)
        obv_val = getattr(r, 'obv_z', 0.0)

        ind_data = {
            "Indicator":  ["RSI-14", "ADX-14", "Sharpe 20d", "OBV Z-score"],
            "Value":      [f"{rsi_val:.1f}", f"{adx_val:.1f}",
                           f"{sharpe_val:.2f}", f"{obv_val:.2f}"],
            "Interpretation": [
                "55–70 = steady grind (best zone)" if 55 <= rsi_val <= 70
                else "Overbought — caution" if rsi_val > 80
                else "Oversold" if rsi_val < 30 else "Neutral",
                "Strong trend (>30)" if adx_val > 30
                else "Trend present (>25)" if adx_val > 25 else "No clear trend",
                "Strong risk-adj momentum (>1.5)" if sharpe_val > 1.5
                else "Positive" if sharpe_val > 0 else "Negative momentum",
                "Accumulation (>1)" if obv_val > 1
                else "Distribution (<-1)" if obv_val < -1 else "Neutral",
            ],
        }
        st.dataframe(pd.DataFrame(ind_data), width="stretch", hide_index=True)

        # ── Download ──────────────────────────────────────────────────────────
        st.download_button(
            "⬇ Download TQS history CSV",
            data=df_tqs.reset_index().to_csv(index=False),
            file_name=f"tqs_{dd_ticker}.csv",
            mime="text/csv",
        )
    else:
        st.info("Select a stock from the dropdown above or enter a custom symbol, then click 'Analyse'.")
