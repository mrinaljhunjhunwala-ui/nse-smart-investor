"""Market Overview - NSE Smart Investor (multipage page; body verbatim from app.py)."""
import os, sys
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
import streamlit as st
from dashboard.shared.design import apply_design
from dashboard.shared.nav import render_sidebar
from dashboard.shared.chart_helpers import render_top_bar
from dashboard.shared import design as _dz, cache as _cache, trade_utils as _tu, chart_helpers as _ch
# Inject every shared module-level name so the verbatim body runs unchanged.
for _m in (_dz, _cache, _tu, _ch):
    globals().update({k: v for k, v in vars(_m).items() if not k.startswith('__')})

apply_design()
render_sidebar(current="Market Overview")
render_top_bar()

# ───────────────────────── page body (de-indented from app.py) ─────────────────────────
st.title("📊 Market Overview")
st.caption("Live market snapshot — VIX, sector momentum, and top movers")

if st.button("🔄 Refresh Data", type="primary"):
    st.cache_data.clear()

# ── India VIX section ──────────────────────────────────────────────────
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

        # Divergence
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

# ── Sector Rotation ────────────────────────────────────────────────────
st.markdown("---")
st.subheader("🔄 Sector Momentum Heatmap")

@st.cache_data(ttl=1800)
def get_sector_data():
    from strategies.sector_rotation import compute_sector_scores
    return compute_sector_scores(period="1y")

with st.spinner("Computing sector scores…"):
    try:
        scores = get_sector_data()
        if not scores.empty:
            s_col1, s_col2 = st.columns([1, 1])
            with s_col1:
                disp = scores[["mom_20d", "mom_60d", "composite_score", "Rank"]].copy()
                disp.columns = ["20d (%)", "60d (%)", "Score", "Rank"]
                st.dataframe(
                    disp.style
                    .background_gradient(subset=["Score"], cmap="RdYlGn")
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

# ── Top movers from NIFTY50 ────────────────────────────────────────────
st.markdown("---")
st.subheader("🚀 NIFTY50 Top Movers")

@st.cache_data(ttl=180)
def get_top_movers():
    """
    Fetch Nifty50 movers using Yahoo JSON direct API (cloud-safe, no rate limits).
    Falls back to Stooq EOD price if Yahoo JSON fails for a ticker.
    """
    from data.fetcher import NIFTY50_TICKERS
    from utils.live_price import get_live_prices_batch
    tickers_list = list(NIFTY50_TICKERS[:50])

    # Parallel fetch — Yahoo JSON tier 1, NSE tier 2, Stooq EOD tier 3
    raw = get_live_prices_batch(tickers_list, max_workers=12)

    rows = []
    for t in tickers_list:
        q = raw.get(t)
        if not isinstance(q, dict) or not q.get("price"):
            continue
        try:
            rows.append({
                "Ticker":   t,                               # keep .NS for routing
                "Price":    round(q["price"],     2),
                "Day (%)":  round(q["chg_pct"],   2),
                "Prev":     round(q["prev_close"], 2),
                "5d (%)":   round(q["chg_pct"],   2),       # same as day when using EOD
                "Vol Ratio": 1.0,
            })
        except Exception:
            continue
    return pd.DataFrame(rows).sort_values("Day (%)", ascending=False) if rows else pd.DataFrame()

with st.spinner("Fetching NIFTY50 movers…"):
    movers = get_top_movers()
    if not movers.empty:
        top5 = movers.head(5)
        bot5 = movers.tail(5)
        m1, m2 = st.columns(2)

        def _mover_row(row, is_gain: bool):
            chg   = row["Day (%)"]
            price = row["Price"]
            tick  = row["Ticker"]  # e.g. "RELIANCE.NS"
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
                st.session_state["_goto_page"] ="🔍 Analyze Stock"
                st.session_state["manual_ticker_input"] = short
                st.session_state["last_analyzed"] = tick
                st.rerun()
            if btn_b.button("📝 Paper Trade", key=f"mover_trade_{tick}",
                            use_container_width=True):
                st.session_state["_goto_page"] ="📂 Paper Trades"
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


# ═══════════════════════════════════════════════════════════════════════════════
# PAGE 4 — SMART SCREENER
# ═══════════════════════════════════════════════════════════════════════════════
