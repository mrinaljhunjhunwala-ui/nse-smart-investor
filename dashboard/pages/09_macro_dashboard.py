"""Macro Dashboard - NSE Smart Investor (multipage page; body verbatim from app.py)."""
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
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
import sys
from dashboard.shared.design import (
    apply_design,
)
from dashboard.shared.chart_helpers import (
    _ROOT,
    load_macro_data,
    render_top_bar,
)

apply_design()
render_sidebar(current="Macro Dashboard")
render_top_bar()

# ───────────────────────── page body (de-indented from app.py) ─────────────────────────
st.title("🌍 Macro Dashboard — Commodities, Currencies & Indices")
st.caption(
    "Key rules: Crude ↑ → INR weakens (India imports 85%)  |  "
    "DXY ↑ → FII outflows from India  |  "
    "Gold ↑ → Risk-off globally  |  "
    "USD/INR ↑ → IT exporters benefit"
)

if st.button("🔄 Refresh Macro Data", type="primary"):
    st.cache_data.clear()

with st.spinner("Fetching 7 macro instruments…"):
    try:
        macro_df = load_macro_data()
        if macro_df.empty:
            st.warning("Could not fetch macro data. Check internet connection.")
        else:
            # Metric cards
            st.subheader("Current Levels & Daily Change")
            card_cols = st.columns(min(len(macro_df.columns), 7))
            for i, col_name in enumerate(macro_df.columns):
                series = macro_df[col_name].dropna()
                if len(series) >= 2:
                    curr_v = float(series.iloc[-1])
                    prev_v = float(series.iloc[-2])
                    chg_v  = (curr_v / max(prev_v, 0.0001) - 1) * 100
                    fmt_v  = f"{curr_v:,.0f}" if curr_v > 500 else f"{curr_v:.2f}"
                    card_cols[i % 7].metric(col_name, fmt_v, f"{chg_v:+.2f}%")

            st.markdown("---")

            # Normalised 3-month performance
            st.subheader("3-Month Performance (Normalised to 100)")
            first_valid = macro_df.apply(
                lambda s: s.dropna().iloc[0] if not s.dropna().empty else 1
            )
            norm_df = macro_df.div(first_valid) * 100
            _colors = ["#4CAF50","#2196F3","#FF6B6B","#FFD700","#FF8C00","#9C27B0","#00BCD4"]
            fig_norm = go.Figure()
            for i, col in enumerate(norm_df.columns):
                fig_norm.add_trace(go.Scatter(
                    x=norm_df.index, y=norm_df[col], name=col,
                    line=dict(color=_colors[i % len(_colors)], width=2),
                ))
            fig_norm.add_hline(y=100, line_dash="dot", line_color="white", opacity=0.3)
            fig_norm.update_layout(
                template="nse_pro", height=380,
                yaxis_title="Indexed (start = 100)",
                legend=dict(orientation="h", y=1.02),
                margin=dict(l=0, r=0, t=40, b=0),
            )
            st.plotly_chart(fig_norm, width="stretch")

            st.markdown("---")

            # 30-day return correlation heatmap
            st.subheader("30-Day Return Correlation Matrix")
            rets_30  = macro_df.pct_change().tail(30)
            corr_m   = rets_30.corr().round(2)
            fig_corr = px.imshow(
                corr_m, text_auto=True, aspect="auto",
                color_continuous_scale="RdBu_r", zmin=-1, zmax=1,
                title="30-Day Daily Return Correlation",
            )
            fig_corr.update_layout(
                template="nse_pro", height=420,
                margin=dict(l=0, r=0, t=40, b=0),
            )
            st.plotly_chart(fig_corr, width="stretch")

            st.markdown("---")

            # India impact table
            st.subheader("India Market Impact Guide")
            st.dataframe(pd.DataFrame([
                {"Move": "Brent Crude ↑", "Sector Impact": "Aviation/Paint/Tyre/FMCG ↓",
                 "INR Effect": "INR weakens (imports 85%)", "Nifty Bias": "🔴 Bearish"},
                {"Move": "Gold ↑",        "Sector Impact": "Jewellery mixed; gold ETFs ↑",
                 "INR Effect": "USD/INR rises if risk-off", "Nifty Bias": "🟡 Risk-off"},
                {"Move": "DXY ↑",         "Sector Impact": "FII outflows from all EM",
                 "INR Effect": "INR weakens",              "Nifty Bias": "🔴 Bearish"},
                {"Move": "DXY ↓",         "Sector Impact": "FII inflows to EM",
                 "INR Effect": "INR strengthens",          "Nifty Bias": "🟢 Bullish"},
                {"Move": "USD/INR ↑",     "Sector Impact": "IT exporters (TCS/Infy/HCL) ↑; Auto ↓",
                 "INR Effect": "Higher import bill",       "Nifty Bias": "🟡 Mixed"},
                {"Move": "USD/INR ↓",     "Sector Impact": "IT exporters ↓; Importers ↑",
                 "INR Effect": "Lower import costs",       "Nifty Bias": "🟡 Mixed"},
            ]), hide_index=True)

    except Exception as e:
        st.error(f"Macro data error: {e}")


# ═══════════════════════════════════════════════════════════════════════════════
# PAGE 8 — MARKET BREADTH  [NEW]  (market-breadth skill)
# ═══════════════════════════════════════════════════════════════════════════════
