"""Market Breadth - NSE Smart Investor (multipage page; body verbatim from app.py)."""
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
render_sidebar(current="Market Breadth")
render_top_bar()

# ───────────────────────── page body (de-indented from app.py) ─────────────────────────
st.title("📈 Market Breadth — Nifty 50 Internal Health")
st.caption(
    "Breadth confirms price trends. "
    "Price up + breadth expanding = sustainable rally. "
    "Price up + breadth shrinking = narrow / fragile move."
)

if st.button("🔄 Refresh Breadth Data", type="primary"):
    st.cache_data.clear()

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

    # % above key MAs bar chart
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

    # Signal interpretation
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

    # A/D pie + reference table side by side
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

    # 52W high / low bars
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


# ═══════════════════════════════════════════════════════════════════════════════
# PAGE 9 — OI & OPTIONS SETUP  [NEW]  (oi-pcr-analysis + options-fno skills)
# ═══════════════════════════════════════════════════════════════════════════════
