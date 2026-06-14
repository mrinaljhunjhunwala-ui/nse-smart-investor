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
import plotly.express as px
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
    from analysis.trend_quality_score import score_ticker, scan_universe, add_indicators, fetch_data, _score_all_pillars
    return score_ticker, scan_universe, add_indicators, fetch_data, _score_all_pillars

try:
    score_ticker, scan_universe, add_indicators, fetch_data, _score_all_pillars = _load_engine()
    ENGINE_OK = True
except Exception as e:
    st.error(f"TQS engine failed to load: {e}")
    ENGINE_OK = False
    st.stop()


# ── Default universe ──────────────────────────────────────────────────────────
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


# ─────────────────────────────────────────────────────────────────────────────
# Tabs
# ─────────────────────────────────────────────────────────────────────────────
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
        period = st.selectbox("Period", ["1y", "2y", "5y"], index=0)
        min_tqs = st.slider("Min TQS filter", 0, 90, 0, step=5)
        run_scan = st.button("▶ Run Scan", use_container_width=True, type="primary")

    if run_scan:
        tickers = [t.strip().upper() for t in raw_input.replace("\n", ",").split(",") if t.strip()]
        if not tickers:
            st.warning("Enter at least one ticker.")
        else:
            rows = []
            prog = st.progress(0, text="Scanning…")
            for i, t in enumerate(tickers):
                try:
                    r = score_ticker(t, period=period)
                    rows.append(r.as_dict())
                except Exception:
                    pass
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

        # Colour-coded table
        def _colour_signal(val):
            c = SIGNAL_COLOUR.get(val, "#6b7280")
            return f"color: {c}; font-weight: 600"

        def _colour_grade(val):
            c = GRADE_COLOUR.get(val, "#6b7280")
            return f"color: {c}; font-weight: 700"

        def _bar_tqs(val):
            pct = val / 90 * 100
            return f"background: linear-gradient(90deg, #3b82f6 {pct:.0f}%, transparent {pct:.0f}%)"

        display_cols = [
            "ticker", "close", "tqs", "grade", "signal",
            "p1_strength", "p2_persistence", "p3_momentum", "p4_confirmation",
            "rsi", "sharpe_20", "obv_z",
        ]
        styled = (
            df_scan[display_cols]
            .rename(columns={
                "ticker": "Ticker", "close": "Close", "tqs": "TQS",
                "grade": "Grade", "signal": "Signal",
                "p1_strength": "P1 Strength", "p2_persistence": "P2 Persist",
                "p3_momentum": "P3 Momentum", "p4_confirmation": "P4 Volume",
                "rsi": "RSI", "sharpe_20": "Sharpe20", "obv_z": "OBV-Z",
            })
            .style
            .applymap(_colour_signal, subset=["Signal"])
            .applymap(_colour_grade,  subset=["Grade"])
            .apply(lambda col: [_bar_tqs(v) for v in col], subset=["TQS"])
            .format({
                "Close": "₹{:,.2f}", "TQS": "{:.1f}",
                "P1 Strength": "{:.1f}", "P2 Persist": "{:.1f}",
                "P3 Momentum": "{:.1f}", "P4 Volume": "{:.1f}",
                "RSI": "{:.1f}", "Sharpe20": "{:.2f}", "OBV-Z": "{:.2f}",
            })
        )
        st.dataframe(styled, use_container_width=True, height=500)

        # ── Pillar radar / bar chart ──────────────────────────────────────────
        st.subheader("Pillar breakdown — top 10")
        top10 = df_scan.head(10)
        fig = go.Figure()
        pillars = ["p1_strength", "p2_persistence", "p3_momentum", "p4_confirmation"]
        labels  = ["P1 Strength", "P2 Persistence", "P3 Momentum", "P4 Volume"]
        colours = ["#3b82f6", "#10b981", "#f59e0b", "#8b5cf6"]

        for pillar, label, colour in zip(pillars, labels, colours):
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
            legend=dict(orientation="h", yanchor="bottom", y=1.02),
            margin=dict(t=40, b=40),
            height=380,
        )
        st.plotly_chart(fig, use_container_width=True)

        # ── Download ──────────────────────────────────────────────────────────
        st.download_button(
            "⬇ Download CSV",
            data=df_scan.to_csv(index=False),
            file_name="tqs_scan.csv",
            mime="text/csv",
        )


# ═════════════════════════════════════════════════════════════════════════════
# TAB 2 — DEEP DIVE
# ═════════════════════════════════════════════════════════════════════════════
with tab_deep:
    st.subheader("Single Stock Deep Dive")

    col1, col2, col3 = st.columns([2, 1, 1])
    with col1:
        dd_ticker = st.text_input("Ticker", value="RELIANCE.NS").upper().strip()
    with col2:
        dd_period = st.selectbox("History", ["1y", "2y", "5y"], index=1, key="dd_period")
    with col3:
        st.write("")
        st.write("")
        run_deep = st.button("▶ Analyse", use_container_width=True, type="primary")

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
        grade_col = GRADE_COLOUR.get(r.grade(), "#6b7280")
        sig_col   = SIGNAL_COLOUR.get(r.signal(), "#6b7280")

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
            pct = score / 22.5
            fig_g = go.Figure(go.Indicator(
                mode="gauge+number",
                value=score,
                title={"text": label, "font": {"size": 12}},
                gauge={
                    "axis": {"range": [0, 22.5], "tickfont": {"size": 10}},
                    "bar":  {"color": colour},
                    "steps": [
                        {"range": [0, 7.5],   "color": "#f1f5f9"},
                        {"range": [7.5, 15],  "color": "#e2e8f0"},
                        {"range": [15, 22.5], "color": "#cbd5e1"},
                    ],
                },
                number={"suffix": "/22.5", "font": {"size": 16}},
            ))
            fig_g.update_layout(height=200, margin=dict(t=40, b=10, l=20, r=20))
            col.plotly_chart(fig_g, use_container_width=True)

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
            yaxis_range=[0, 90],
            legend=dict(orientation="h"),
            margin=dict(t=20, b=40),
            height=360,
        )
        st.plotly_chart(fig_ts, use_container_width=True)

        # ── Pillar time-series ────────────────────────────────────────────────
        st.markdown("**Pillar scores over time**")
        fig_p = go.Figure()
        for col_name, label, colour in [
            ("P1_Strength",     "P1 Strength",    "#3b82f6"),
            ("P2_Persistence",  "P2 Persistence", "#10b981"),
            ("P3_Momentum",     "P3 Momentum",    "#f59e0b"),
            ("P4_Confirmation", "P4 Volume",      "#8b5cf6"),
        ]:
            fig_p.add_trace(go.Scatter(
                x=df_tqs.index, y=df_tqs[col_name],
                name=label, line=dict(color=colour, width=1.5),
            ))
        fig_p.update_layout(
            xaxis_title="Date", yaxis_title="Pillar Score",
            yaxis_range=[0, 22.5],
            legend=dict(orientation="h"),
            margin=dict(t=20, b=40),
            height=300,
        )
        st.plotly_chart(fig_p, use_container_width=True)

        # ── Key indicator table ───────────────────────────────────────────────
        st.markdown("**Latest indicator values**")
        last = df_tqs.iloc[-1]
        ind_data = {
            "Indicator":  ["RSI-14", "ADX-14", "Sharpe 20d", "OBV Z-score"],
            "Value":      [f"{r.rsi:.1f}", f"{r.adx:.1f}",
                           f"{r.sharpe_20:.2f}", f"{r.obv_z:.2f}"],
            "Interpretation": [
                "55–70 = steady grind (best zone)" if 55 <= r.rsi <= 70
                else "Overbought — caution" if r.rsi > 80
                else "Oversold" if r.rsi < 30 else "Neutral",
                "Strong trend (>30)" if r.adx > 30
                else "Trend present (>25)" if r.adx > 25 else "No clear trend",
                "Strong risk-adj momentum (>1.5)" if r.sharpe_20 > 1.5
                else "Positive" if r.sharpe_20 > 0 else "Negative momentum",
                "Accumulation (>1)" if r.obv_z > 1
                else "Distribution (<-1)" if r.obv_z < -1 else "Neutral",
            ],
        }
        st.dataframe(pd.DataFrame(ind_data), use_container_width=True, hide_index=True)

        # ── Download ──────────────────────────────────────────────────────────
        st.download_button(
            "⬇ Download TQS history CSV",
            data=df_tqs.reset_index().to_csv(index=False),
            file_name=f"tqs_{dd_ticker}.csv",
            mime="text/csv",
        )
