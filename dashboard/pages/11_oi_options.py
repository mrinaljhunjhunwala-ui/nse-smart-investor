"""OI & Options - NSE Smart Investor (multipage page; body verbatim from app.py)."""
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
render_sidebar(current="OI & Options")
render_top_bar()

# ───────────────────────── page body (de-indented from app.py) ─────────────────────────
# In the monolith `vix_val` came from the module-level sidebar code; in the
# multipage split each page must source it independently.
vix_val = (get_vix_info() or {}).get("vix")

st.title("🏦 OI & Options Setup")
st.caption(
    "IV regime (VIX-based) + directional bias → right strategy.  "
    "Max Pain calculator + PCR zone reference for expiry planning."
)

tab1, tab2, tab3 = st.tabs([
    "📊 Strategy Selector",
    "🔢 Max Pain Calculator",
    "📈 PCR Zone Reference",
])

# ── TAB 1: Strategy Selector ───────────────────────────────────────────────
with tab1:
    st.subheader("Options Strategy Selector")
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

# ── TAB 2: Max Pain Calculator ─────────────────────────────────────────────
with tab2:
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

# ── TAB 3: PCR Zone Reference ──────────────────────────────────────────────
with tab3:
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
# PAGE 10 — INTRADAY TRADER  [NEW]
# ═══════════════════════════════════════════════════════════════════════════════
