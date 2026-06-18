"""Market Internals - Macro context + Market Breadth."""
import os, sys
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from dashboard.shared.design import apply_design
from dashboard.shared.nav import render_sidebar
from dashboard.shared.chart_helpers import (
    _ROOT,
    _NIFTY50_TICKERS,
    load_macro_data,
    compute_market_breadth,
    render_top_bar,
)

apply_design()
render_sidebar(current="Market Internals")
render_top_bar()

st.title("🌍 Market Internals — Macro + Breadth")

_tab_macro, _tab_breadth = st.tabs(["🌍 Macro Dashboard", "📈 Market Breadth"])

with _tab_macro:
    st.caption(
        "Key rules: Crude ↑ → INR weakens (India imports 85%)  |  "
        "DXY ↑ → FII outflows from India  |  "
        "Gold ↑ → Risk-off globally  |  "
        "USD/INR ↑ → IT exporters benefit"
    )

    if st.button("🔄 Refresh Macro Data", type="primary"):
        # BUGFIX: was a blanket st.cache_data.clear() — since cache_data is
        # global across the whole app, this also wiped Command Centre's
        # 2-minute Top Picks scan and watchlist scores just to refresh 7
        # macro instruments. Only load_macro_data's own cache needs busting.
        load_macro_data.clear()

    with st.spinner("Fetching 7 macro instruments…"):
        try:
            macro_df = load_macro_data()

            # FIX MI2 — surface exactly which instruments came back so a
            # partial fetch (e.g. Yahoo failing for some/all of Gold/Brent/
            # USD-INR/DXY) is visible instead of silently degrading into a
            # broken-looking chart below.
            _expected = ["Nifty 50", "BankNifty", "India VIX",
                         "Gold ($/oz)", "Brent Crude", "USD/INR", "DXY"]
            _missing  = [c for c in _expected if c not in macro_df.columns]

            if macro_df.empty:
                st.warning("Could not fetch macro data. Check internet connection.")
            else:
                if _missing:
                    st.info(
                        f"ℹ️ {len(_missing)} of {len(_expected)} instruments unavailable "
                        f"right now: **{', '.join(_missing)}**. Showing the "
                        f"{len(macro_df.columns)} that loaded successfully."
                    )

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

                # FIX MI2 — only attempt the normalized performance chart and
                # the correlation matrix if there are at least 2 usable
                # columns with enough overlapping history. Previously these
                # ran unconditionally on whatever subset of macro_df existed,
                # so a column with too little/misaligned history could push
                # pct_change()/corr() output to all-NaN, which renders as a
                # blank or visibly broken chart with no explanation.
                _usable_cols = [c for c in macro_df.columns if macro_df[c].dropna().shape[0] >= 30]

                if len(_usable_cols) < 2:
                    st.warning(
                        "⚠️ Not enough overlapping history across instruments right now "
                        "to plot 3-month performance or the correlation matrix "
                        f"(only {len(_usable_cols)} instrument(s) have sufficient data). "
                        "Try **Refresh Macro Data** in a moment."
                    )
                else:
                    _macro_use = macro_df[_usable_cols]

                    # Normalised 3-month performance
                    st.subheader("3-Month Performance (Normalised to 100)")
                    first_valid = _macro_use.apply(
                        lambda s: s.dropna().iloc[0] if not s.dropna().empty else 1
                    )
                    norm_df = _macro_use.div(first_valid) * 100
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
                    rets_30 = _macro_use.pct_change().tail(30)
                    # FIX MI2: drop any column that is still all-NaN after the
                    # 30-day slice (e.g. an instrument with a recent data gap)
                    # so .corr() never returns an all-NaN row/column that
                    # would render as a blank heatmap.
                    rets_30 = rets_30.dropna(axis=1, how="all")
                    if rets_30.shape[1] < 2:
                        st.warning(
                            "⚠️ Not enough recent daily returns to compute a "
                            "correlation matrix right now — try refreshing in a moment."
                        )
                    else:
                        corr_m = rets_30.corr().round(2)
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

with _tab_breadth:
    st.caption(
        "Breadth confirms price trends. "
        "Price up + breadth expanding = sustainable rally. "
        "Price up + breadth shrinking = narrow / fragile move."
    )

    if st.button("🔄 Refresh Breadth Data", type="primary"):
        # BUGFIX: same blanket-clear issue — only this page's own breadth
        # cache needs busting here.
        compute_market_breadth.clear()

    st.info("⏱️ Scanning all 50 Nifty stocks takes ~3 minutes. Results are cached for 15 minutes.")
    run_breadth = st.button("🔍 Compute Breadth Now", type="primary", key="breadth_btn")

    if run_breadth:
        with st.spinner("Scanning Nifty 50 breadth (~3 min)…"):
            breadth = compute_market_breadth(_NIFTY50_TICKERS)

        st.markdown("---")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Advancing",           breadth["advance"])
        c2.metric("Declining",           breadth["decline"])
        c3.metric("A/D Ratio",           f"{breadth['ad_ratio']:.2f}",
                  help="> 1.5 = strong; < 0.7 = weak")
        c4.metric("Near 52W High / Low", f"{breadth['near_52w_high']} / {breadth['near_52w_low']}")

        st.markdown("---")
        st.subheader("% of Nifty 50 Stocks Above Key Moving Averages")
        bvals = {
            "Above SMA20":  breadth["pct_above_20"],
            "Above SMA50":  breadth["pct_above_50"],
            "Above SMA200": breadth["pct_above_200"],
        }
        bar_fig = go.Figure()
        for label, val in bvals.items():
            bclr = "#4CAF50" if val > 60 else ("#FF9800" if val > 40 else "#F44336")
            bar_fig.add_trace(go.Bar(
                x=[label], y=[val], name=label,
                marker_color=bclr,
                text=[f"{val:.0f}%"], textposition="auto",
            ))
        bar_fig.add_hline(y=70, line_dash="dot", line_color="#4CAF50",
                          annotation_text="Strong (70%)", annotation_position="right")
        bar_fig.add_hline(y=40, line_dash="dot", line_color="#F44336",
                          annotation_text="Weak (40%)", annotation_position="right")
        bar_fig.update_layout(
            template="nse_pro", height=340,
            yaxis_title="% of stocks", yaxis_range=[0, 100],
            showlegend=False,
            margin=dict(l=0, r=0, t=20, b=0),
        )
        st.plotly_chart(bar_fig, width="stretch")

        pct200 = breadth["pct_above_200"]
        if pct200 >= 70:
            sig_txt, sig_clr = "🟢 **Strong Bull Market breadth** — Majority above SMA200. Buy dips with confidence.", "#4CAF50"
        elif pct200 >= 50:
            sig_txt, sig_clr = "🟡 **Moderate breadth** — More than half in uptrend. Stock-selective long approach.", "#FF9800"
        elif pct200 >= 30:
            sig_txt, sig_clr = "🟠 **Weakening breadth** — Over half below SMA200. Reduce position sizes.", "#FF5722"
        else:
            sig_txt, sig_clr = "🔴 **Bear market breadth** — Most below SMA200. Defensive posture; consider hedges.", "#F44336"
        st.markdown(
            f'<div style="background:{sig_clr}22;padding:12px;border-radius:8px;'
            f'border-left:4px solid {sig_clr};font-size:15px;margin:10px 0">'
            f'{sig_txt}</div>', unsafe_allow_html=True
        )

        st.markdown("---")
        col_pie, col_tbl = st.columns([1, 1])
        with col_pie:
            st.subheader("Today's Advance / Decline")
            pie_fig = go.Figure(data=go.Pie(
                labels=["Advancing", "Declining"],
                values=[breadth["advance"], breadth["decline"]],
                marker_colors=["#4CAF50", "#F44336"], hole=0.4,
            ))
            pie_fig.update_layout(
                template="nse_pro", height=260,
                margin=dict(l=0, r=0, t=20, b=0),
            )
            st.plotly_chart(pie_fig, width="stretch")
        with col_tbl:
            st.subheader("Breadth Interpretation Guide")
            st.dataframe(pd.DataFrame([
                {"% Above SMA200": "> 70%",  "Signal": "Strong Bull",    "Action": "Full long — buy dips"},
                {"% Above SMA200": "50–70%", "Signal": "Healthy uptrend","Action": "Long bias, trail stops"},
                {"% Above SMA200": "30–50%", "Signal": "Sector chop",    "Action": "Stock-selective only"},
                {"% Above SMA200": "< 30%",  "Signal": "Bear market",    "Action": "Reduce exposure, hedge"},
            ]), hide_index=True)

        st.markdown("---")
        st.subheader("52-Week High / Low Distribution")
        hl_fig = go.Figure(go.Bar(
            x=["Near 52W High (within 5%)", "Near 52W Low (within 5%)"],
            y=[breadth["near_52w_high"], breadth["near_52w_low"]],
            marker_color=["#4CAF50", "#F44336"],
            text=[breadth["near_52w_high"], breadth["near_52w_low"]],
            textposition="auto",
        ))
        hl_fig.update_layout(
            template="nse_pro", height=260,
            yaxis_title="Number of Nifty 50 stocks",
            margin=dict(l=0, r=0, t=20, b=0),
        )
        st.plotly_chart(hl_fig, width="stretch")
