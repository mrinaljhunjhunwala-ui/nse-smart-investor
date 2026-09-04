"""Position Sizer - NSE Smart Investor (multipage page; body verbatim from app.py)."""
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
import streamlit as st
import sys
from dashboard.shared.design import (
    apply_design,
)
from dashboard.shared.cache import (
    STOCK_SEARCH_MAP,
)
from dashboard.shared.trade_utils import (
    _live_quote_price,
)
from dashboard.shared.chart_helpers import (
    _ROOT,
    render_top_bar,
)

apply_design()
render_sidebar(current="Position Sizer")
render_top_bar()

# ───────────────────────── page body (de-indented from app.py) ─────────────────────────
st.title("Position Sizer – Kelly Criterion + Risk Calculator")

st.markdown(
    "Calculate exact position size using Kelly Criterion and fixed-risk rules.  \n"
    "Never guess your lot size again — know exactly how many shares to buy *before* you enter."
)

_ps_tab1, _ps_tab2 = st.tabs(["💰 Fixed Risk Calculator", "📊 Kelly Criterion"])

with _ps_tab1:
    st.subheader("Fixed-Risk Position Sizing")
    st.caption("Most common approach: risk a fixed % of capital per trade.")

    # ── Optional: auto-fill entry/SL/TP from a stock's LIVE price ──────────────
    for _k, _v in (("ps_entry", 500.0), ("ps_sl", 480.0), ("ps_tp", 550.0)):
        st.session_state.setdefault(_k, _v)
    _ps_opts = sorted(
        f"{n}  ({s.replace('.NS', '')})" for n, s in STOCK_SEARCH_MAP.items()
    )
    _ps_pc1, _ps_pc2 = st.columns([3, 1])
    with _ps_pc1:
        _ps_pick = st.selectbox(
            "Auto-fill from a stock (optional) — pulls the live price",
            ["— none —"] + _ps_opts, index=0, key="ps_pick",
        )
    with _ps_pc2:
        st.write("")
        st.write("")
        if st.button("⚡ Use live price", key="ps_fetch", width="stretch"):
            if _ps_pick != "— none —":
                _psym = _ps_pick.rsplit("(", 1)[-1].rstrip(")")
                _psym = _psym if _psym.endswith(".NS") else _psym + ".NS"
                _plive = _live_quote_price(_psym)
                if _plive:
                    # default SL 2% below, TP 4% above — user can adjust
                    st.session_state["ps_entry"] = round(_plive, 2)
                    st.session_state["ps_sl"]    = round(_plive * 0.98, 2)
                    st.session_state["ps_tp"]    = round(_plive * 1.04, 2)
                    st.toast(f"⚡ Loaded live ₹{_plive:,.2f} for "
                             f"{_psym.replace('.NS','')}", icon="✅")
                    st.rerun()
                else:
                    st.warning("Live price unavailable — enter values manually.")
            else:
                st.info("Pick a stock from the list first.")

    _psc1, _psc2 = st.columns(2)
    with _psc1:
        _ps_capital   = st.number_input("Portfolio Size (₹)", 50_000, 50_000_000, 500_000, 50_000, key="ps_cap")
        _ps_risk_pct  = st.slider("Risk per trade (%)", 0.5, 3.0, 1.0, 0.25, key="ps_risk_pct")
        _ps_entry     = st.number_input("Entry Price (₹)", min_value=1.0, max_value=100_000.0,
                                        step=0.5, key="ps_entry", format="%.2f")
    with _psc2:
        _ps_sl        = st.number_input("Stop-Loss Price (₹)", min_value=1.0, max_value=100_000.0,
                                        step=0.5, key="ps_sl", format="%.2f")
        _ps_tp        = st.number_input("Target Price (₹)", min_value=1.0, max_value=200_000.0,
                                        step=0.5, key="ps_tp", format="%.2f")
        _ps_lot_size  = st.number_input("Lot / Board Lot (shares, 1 for equity)", 1, 10000, 1, key="ps_lot")

    if _ps_entry > _ps_sl > 0:
        _risk_rs    = _ps_capital * _ps_risk_pct / 100
        _rps        = _ps_entry - _ps_sl
        _raw_shares = _risk_rs / _rps
        _lots       = max(1, int(_raw_shares / _ps_lot_size))
        _shares     = _lots * _ps_lot_size
        _notional   = _shares * _ps_entry
        _actual_risk = _shares * _rps
        _rr         = (_ps_tp - _ps_entry) / _rps if _rps > 0 else 0
        _exp_profit = _shares * (_ps_tp - _ps_entry)

        st.markdown("---")
        r1, r2, r3, r4, r5 = st.columns(5)
        r1.metric("Shares to Buy",   f"{_shares:,}")
        r2.metric("Notional",        f"₹{_notional:,.0f}")
        r3.metric("Risk ₹",          f"₹{_actual_risk:,.0f}",
                  delta=f"{_actual_risk/_ps_capital*100:.2f}% of capital")
        r4.metric("R:R Ratio",       f"{_rr:.1f}x",
                  delta="✅ Good" if _rr >= 2 else "⚠️ Low")
        r5.metric("Potential Profit",f"₹{_exp_profit:,.0f}")

        _card_color = "card-green" if _rr >= 2 else ("card-yellow" if _rr >= 1.5 else "card-red")
        st.markdown(f"""
        <div class="{_card_color}">
        <b>📋 Trade Plan: {_ps_entry:.2f} entry</b><br>
        Buy <b>{_shares:,} shares</b> at ₹{_ps_entry:.2f} &nbsp;|&nbsp;
        Stop ₹{_ps_sl:.2f} &nbsp;|&nbsp;
        Target ₹{_ps_tp:.2f}<br>
        Risk: ₹{_actual_risk:,.0f} ({_actual_risk/_ps_capital*100:.2f}% of ₹{_ps_capital:,}) &nbsp;|&nbsp;
        R:R = {_rr:.1f}:1 &nbsp;|&nbsp; Potential profit: ₹{_exp_profit:,.0f}
        </div>
        """, unsafe_allow_html=True)
    else:
        st.warning("Entry price must be greater than stop-loss price.")

with _ps_tab2:
    st.subheader("Kelly Criterion Position Sizing")
    st.caption("Mathematically optimal position size based on your historical win rate and R:R.")
    st.markdown("""
    **Kelly Formula:**  `f* = (b × p − q) / b`  where `b` = R:R ratio, `p` = win rate, `q` = 1 − p

    ⚠️ *Use Half-Kelly (50% of Kelly output) in practice — full Kelly is too aggressive.*
    """)

    _kc1, _kc2 = st.columns(2)
    with _kc1:
        _k_capital  = st.number_input("Portfolio Size (₹)", 50_000, 50_000_000, 500_000, 50_000, key="k_cap")
        _k_winrate  = st.slider("Historical Win Rate (%)", 30, 75, 55, 1, key="k_wr") / 100
        _k_rr       = st.slider("Average R:R Ratio", 0.5, 5.0, 2.0, 0.1, key="k_rr")
    with _kc2:
        _k_fraction = st.slider("Kelly Fraction (0.5 = Half-Kelly)", 0.1, 1.0, 0.5, 0.05, key="k_frac")
        _k_max_risk = st.slider("Max Risk Cap (%)", 0.5, 5.0, 2.0, 0.25, key="k_maxrisk")
        _k_entry    = st.number_input("Entry Price (₹)", 1.0, 100_000.0, 500.0, 0.5, key="k_entry", format="%.2f")
        _k_sl       = st.number_input("Stop-Loss (₹)",  1.0, 100_000.0, 480.0, 0.5, key="k_sl",    format="%.2f")

    from trading.signals import kelly_position_size, shares_from_risk
    try:
        _k_result   = kelly_position_size(
            win_rate=_k_winrate, rr_ratio=_k_rr,
            capital=_k_capital, fraction=_k_fraction, max_risk_pct=_k_max_risk,
        )
        _k_shares   = shares_from_risk(_k_entry, _k_sl, _k_result["risk_rs"]) if _k_entry > _k_sl else 0
        _k_notional = _k_shares * _k_entry
        _k_actual_r = _k_shares * (_k_entry - _k_sl)

        st.markdown("---")
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Kelly %",       f"{_k_result['kelly_pct']:.1f}%")
        k2.metric("Applied Risk %", f"{_k_result['risk_pct']:.1f}%")
        k3.metric("Risk ₹",        f"₹{_k_result['risk_rs']:,.0f}")
        k4.metric("Shares",        f"{_k_shares:,}")

        st.info(_k_result["notes"])
        if _k_result["kelly_pct"] > 0:
            st.markdown(f"""
            <div class="card-blue">
            <b>Kelly Plan @ ₹{_k_entry:.2f}</b><br>
            Optimal risk: <b>{_k_result['risk_pct']:.1f}%</b> of capital = ₹{_k_result['risk_rs']:,.0f}<br>
            Shares: <b>{_k_shares:,}</b> × ₹{_k_entry:.2f} = ₹{_k_notional:,.0f} notional<br>
            Actual risk: ₹{_k_actual_r:,.0f} with SL at ₹{_k_sl:.2f}
            </div>
            """, unsafe_allow_html=True)
        else:
            st.error("Negative Kelly — this setup has negative expected value. Do not trade.")
    except Exception as _ke:
        st.error(f"Kelly calculation error: {_ke}")


# ═══════════════════════════════════════════════════════════════════════════════
# PAGE 13 — SWING TRADE CHECKLIST  [NEW]
# ═══════════════════════════════════════════════════════════════════════════════
