"""Overview - NSE Smart Investor (merged: former Market Overview + Market Internals).

MERGE NOTE: this page replaces the two separate pages "Market Overview"
(pages/05_market_overview.py) and "Market Internals" (pages/09_market_internals.py).
All logic is unchanged from those two pages — just reorganized as tabs under
one page so related market-context views live in one place. After deploying
this file, delete dashboard/pages/09_market_internals.py (its content now
lives in the "🌍 Macro" and "📈 Breadth" tabs below) — nav.py has already
been updated to match.
"""
import os, sys
import logging

_log = logging.getLogger("dashboard.overview")
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
    render_top_bar,
    load_macro_data,
    compute_market_breadth,
    rdylgn_bg,
)
from dashboard.shared.cache import load_vix_data

apply_design()
render_sidebar(current="Overview")
render_top_bar()

st.title("Overview")

st.caption("Market snapshot, macro context, and breadth — everything for a market read in one place")

_tab_snapshot, _tab_macro, _tab_breadth = st.tabs(
    ["📊 Snapshot", "🌍 Macro", "📈 Breadth"]
)

# ═══════════════════════════════════════════════════════════════════════════
# TAB 1 — SNAPSHOT (formerly Market Overview: VIX, sector rotation, movers)
# ═══════════════════════════════════════════════════════════════════════════
with _tab_snapshot:
    _mo_refresh_clicked = st.button("🔄 Refresh Snapshot Data", type="primary", key="ov_snap_refresh")
    if _mo_refresh_clicked:
        # FIX MKT2 (preserved): targeted cache clears only, never a blanket
        # st.cache_data.clear() — that would also wipe Top Picks/watchlist
        # scans on other pages.
        load_vix_data.clear()

    # ── India VIX section ──────────────────────────────────────────────
    with st.spinner("Loading VIX & Nifty…"):
        try:
            vix_df, nifty_df = load_vix_data()
            curr_vix   = float(vix_df["Close"].iloc[-1])
            prev_vix   = float(vix_df["Close"].iloc[-2])
            vix_chg    = (curr_vix / prev_vix - 1) * 100
            vix_52w_hi = float(vix_df["High"].max())
            vix_52w_lo = float(vix_df["Low"].min())
            vix_rank   = (curr_vix - vix_52w_lo) / max(vix_52w_hi - vix_52w_lo, 0.01) * 100
            curr_nifty = float(nifty_df["Close"].iloc[-1])
            nifty_chg  = float(nifty_df["Close"].pct_change().iloc[-1]) * 100

            if curr_vix < 12:    regime, reg_color = "Extreme Complacency", "#FF6B35"
            elif curr_vix < 16:  regime, reg_color = "Low Volatility",       "#4ECDC4"
            elif curr_vix < 22:  regime, reg_color = "Normal",                "#45B7D1"
            elif curr_vix < 28:  regime, reg_color = "Elevated Fear",         "#F7DC6F"
            elif curr_vix < 35:  regime, reg_color = "High Fear",             "#E74C3C"
            else:                regime, reg_color = "PANIC / Crisis",         "#8E44AD"

            if curr_vix < 15:   opt_str = "BUY options (cheap premium)"
            elif curr_vix < 22: opt_str = "SPREADS (balanced IV)"
            elif curr_vix < 28: opt_str = "SELL premium with spreads"
            else:               opt_str = "SELL wide spreads / long if conviction"

            if nifty_chg > 0 and vix_chg > 0:
                div_txt = "⚠️ Warning: Nifty ↑ + VIX ↑ — fragile rally"
            elif nifty_chg < 0 and vix_chg < 0:
                div_txt = "🟢 Nifty ↓ + VIX ↓ — oversold bounce watch"
            elif nifty_chg > 0 and vix_chg < 0:
                div_txt = "✅ Healthy rally — fear leaving market"
            else:
                div_txt = "✅ Normal correction — fear rising with selling"

            st.subheader("🌡️ Fear Gauge — India VIX")
            st.markdown(
                f'<div style="background:{reg_color};padding:12px 18px;border-radius:10px;'
                f'color:#000;font-weight:700;font-size:18px;text-align:center;">'
                f'VIX {curr_vix:.2f}  ({vix_chg:+.1f}% today)  —  {regime}  |  '
                f'Options regime: {opt_str}'
                f'</div>',
                unsafe_allow_html=True
            )
            st.markdown(f"**Divergence signal:** {div_txt}")

            v_col1, v_col2, v_col3, v_col4 = st.columns(4)
            v_col1.metric("India VIX",    f"{curr_vix:.2f}", f"{vix_chg:+.1f}%")
            v_col2.metric("VIX Rank",     f"{vix_rank:.0f}%  (52w)")
            v_col3.metric("Nifty 50",     f"{curr_nifty:,.0f}", f"{nifty_chg:+.2f}%")
            v_col4.metric("52w VIX Range",f"{vix_52w_lo:.1f} – {vix_52w_hi:.1f}")

            fig_vix = go.Figure()
            fig_vix.add_trace(go.Scatter(
                x=vix_df.index, y=vix_df["Close"],
                name="India VIX", line=dict(color="#FF6B6B", width=2),
                fill="tozeroy", fillcolor="rgba(255,107,107,0.1)",
            ))
            for lo, hi, clr, lbl in [
                (0, 12, "rgba(76,175,80,.12)", "Safe"),
                (12, 22, "rgba(255,193,7,.12)", "Normal"),
                (22, 28, "rgba(255,87,34,.12)", "Caution"),
                (28, 100, "rgba(156,39,176,.12)", "Fear"),
            ]:
                fig_vix.add_hrect(y0=lo, y1=hi, fillcolor=clr,
                                  annotation_text=lbl, annotation_position="left",
                                  line_width=0)
            fig_vix.update_layout(
                title="India VIX — 1 Year",
                template="nse_pro", height=300,
                xaxis_rangeslider_visible=False,
                margin=dict(l=0, r=0, t=40, b=0),
            )
            st.plotly_chart(fig_vix, width="stretch")

        except Exception as e:
            st.warning(f"VIX load error: {e}")

    # ── Sector Rotation ──────────────────────────────────────────────
    st.markdown("---")
    st.subheader("🔄 Sector Momentum Heatmap")

    @st.cache_data(ttl=1800)
    def get_sector_data():
        from strategies.sector_rotation import compute_sector_scores
        return compute_sector_scores(period="1y")

    if _mo_refresh_clicked:
        get_sector_data.clear()

    with st.spinner("Computing sector scores…"):
        try:
            scores = get_sector_data()
            if not scores.empty:
                s_col1, s_col2 = st.columns([1, 1])
                with s_col1:
                    disp = scores[["mom_20d", "mom_60d", "composite_score", "Rank"]].copy()
                    disp.columns = ["20d (%)", "60d (%)", "Score", "Rank"]
                    # FIX BT1: Styler.background_gradient() requires matplotlib,
                    # which isn't a project dependency — crashed on Streamlit
                    # Cloud. See dashboard/shared/chart_helpers.rdylgn_bg.
                    _mo_vmin, _mo_vmax = disp["Score"].min(), disp["Score"].max()
                    st.dataframe(
                        disp.style
                        .map(lambda v: rdylgn_bg(v, _mo_vmin, _mo_vmax), subset=["Score"])
                        .format("{:.2f}"),
                        width="stretch",
                    )
                with s_col2:
                    fig_bar = px.bar(
                        scores.reset_index(), x="Sector", y="composite_score",
                        color="composite_score", color_continuous_scale="RdYlGn",
                        title="Sector Scores",
                        labels={"composite_score": "Score (%)"},
                    )
                    fig_bar.update_layout(
                        template="nse_pro", height=340, showlegend=False,
                        margin=dict(l=0, r=0, t=40, b=0),
                    )
                    st.plotly_chart(fig_bar, width="stretch")
        except Exception as e:
            st.warning(f"Sector scores error: {e}")

    # ── Top movers from broad NSE universe ──────────────────────────
    st.markdown("---")
    st.subheader("🚀 NSE Top Movers")
    st.caption("Scanning ~750 stocks across Nifty Total Market universe")

    @st.cache_data(ttl=180)
    def get_top_movers():
        """
        Fetch broad NSE movers using Yahoo JSON direct API (cloud-safe, no rate limits).
        Uses niftytotalmarket (~750 stocks) instead of Nifty50-only for a true market view.
        Falls back gracefully per-ticker if Yahoo JSON fails.
        """
        from data.universe import get_universe as _gu
        from utils.live_price import get_live_prices_batch

        tickers_list = _gu("niftytotalmarket")   # ~750 liquid NSE stocks
        raw = get_live_prices_batch(tickers_list, max_workers=20)

        rows = []
        for t in tickers_list:
            q = raw.get(t)
            if not isinstance(q, dict) or not q.get("price"):
                continue
            try:
                rows.append({
                    "Ticker":    t,
                    "Price":     round(q["price"],     2),
                    "Day (%)":   round(q["chg_pct"],   2),
                    "Prev":      round(q["prev_close"], 2),
                    "Vol Ratio": 1.0,
                })
            except Exception as e:
                _log.debug("overview: failed to build row for %s: %s", t, e)
                continue
        return pd.DataFrame(rows).sort_values("Day (%)", ascending=False) if rows else pd.DataFrame()

    if _mo_refresh_clicked:
        get_top_movers.clear()

    with st.spinner("Fetching NSE broad movers (~750 stocks)…"):
        movers = get_top_movers()
        if not movers.empty:
            top5 = movers.head(5)
            bot5 = movers.tail(5)
            m1, m2 = st.columns(2)

            def _mover_row(row, is_gain: bool):
                chg   = row["Day (%)"]
                price = row["Price"]
                tick  = row["Ticker"]
                short = tick.replace(".NS", "")
                color = "#26a69a" if is_gain else "#ef5350"
                sign  = "+" if is_gain else ""
                card_cls = "card-green" if is_gain else "card-red"
                st.markdown(
                    f'<div class="{card_cls}" style="padding:8px 14px;margin-bottom:4px">'
                    f'<b style="font-size:14px">{short}</b>'
                    f'<span style="float:right;font-size:13px">₹{price:,.2f} '
                    f'<b style="color:{color}">{sign}{chg:.2f}%</b></span>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
                btn_a, btn_b, btn_c = st.columns([1, 1, 1])
                if btn_a.button("📊 Analyze", key=f"mover_analyze_{tick}",
                                use_container_width=True):
                    # FIX NAV1: use the canonical analyze_ticker handoff key
                    # (same as Command Centre / My Portfolio's "Analyze"
                    # buttons — see 04_analyze_stock.py FIX A8) rather than
                    # writing manual_ticker_input + last_analyzed directly.
                    # The latter happened to also auto-trigger in practice,
                    # but it's a second, untested parallel path doing the
                    # same job — one canonical hand-off key is less fragile
                    # and keeps every "Analyze" button in the app consistent.
                    st.session_state["analyze_ticker"] = tick
                    st.session_state["_goto_page"] = "🔍 Analyze Stock"
                    st.rerun()
                if btn_b.button("📝 Paper Trade", key=f"mover_trade_{tick}",
                                use_container_width=True):
                    st.session_state["_goto_page"] = "📂 Paper Trades"
                    st.session_state["pt_prefill_ticker"] = tick
                    st.rerun()
                if btn_c.button("＋ Watchlist", key=f"mover_wl_{tick}",
                                use_container_width=True):
                    if tick not in st.session_state.get("watchlist", []):
                        st.session_state.setdefault("watchlist", []).append(tick)
                    st.toast(f"{short} added to watchlist ✓")

            with m1:
                st.markdown("**📈 Top Gainers Today**")
                for _, row in top5.iterrows():
                    _mover_row(row, is_gain=True)
            with m2:
                st.markdown("**📉 Top Losers Today**")
                for _, row in bot5.iterrows():
                    _mover_row(row, is_gain=False)
        else:
            st.warning("Could not fetch mover data. Try refreshing in 30 seconds.")


# ═══════════════════════════════════════════════════════════════════════════
# TAB 2 — MACRO (formerly Market Internals' Macro Dashboard tab)
# ═══════════════════════════════════════════════════════════════════════════
with _tab_macro:
    st.caption(
        "Key rules: Crude ↑ → INR weakens (India imports 85%)  |  "
        "DXY ↑ → FII outflows from India  |  "
        "Gold ↑ → Risk-off globally  |  "
        "USD/INR ↑ → IT exporters benefit"
    )

    if st.button("🔄 Refresh Macro Data", type="primary", key="ov_macro_refresh"):
        load_macro_data.clear()

    with st.spinner("Fetching 7 macro instruments…"):
        try:
            macro_df = load_macro_data()

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

                    st.subheader("30-Day Return Correlation Matrix")
                    rets_30 = _macro_use.pct_change().tail(30)
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


# ═══════════════════════════════════════════════════════════════════════════
# TAB 3 — BREADTH (formerly Market Internals' Market Breadth tab)
# ═══════════════════════════════════════════════════════════════════════════
with _tab_breadth:
    st.caption(
        "Breadth confirms price trends. "
        "Price up + breadth expanding = sustainable rally. "
        "Price up + breadth shrinking = narrow / fragile move."
    )

    if st.button("🔄 Refresh Breadth Data", type="primary", key="ov_breadth_refresh"):
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
