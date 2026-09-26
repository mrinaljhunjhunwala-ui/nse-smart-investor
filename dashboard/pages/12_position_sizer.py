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
from dashboard.shared.ui_components import fmt_inr, quiet_output  # noqa: E402

st.markdown(
    '<h1 class="page-title-serif">Position <em>Sizer</em></h1>'
    '<p class="page-subtitle">One calculation: how many shares a fixed risk budget '
    'implies for a given entry and stop. Illustrative maths only; nothing is submitted anywhere.</p>',
    unsafe_allow_html=True,
)

_ps_tab1, _ps_tab2 = st.tabs(["Fixed risk", "Kelly criterion"])

with _ps_tab1:
    # ── Optional: auto-fill entry/SL/TP from a stock's LIVE price ──────────────
    for _k, _v in (("ps_entry", 500.0), ("ps_sl", 480.0), ("ps_tp", 550.0)):
        st.session_state.setdefault(_k, _v)
    _ps_opts = sorted(
        f"{n}  ({s.replace('.NS', '')})" for n, s in STOCK_SEARCH_MAP.items()
    )
    _ps_pc1, _ps_pc2 = st.columns([3, 1], vertical_alignment="bottom")
    with _ps_pc1:
        _ps_pick = st.selectbox(
            "Auto-fill from a stock (optional) — pulls the live price",
            ["— none —"] + _ps_opts, index=0, key="ps_pick",
        )
    with _ps_pc2:
        if st.button("Use live price", key="ps_fetch", width="stretch"):
            if _ps_pick != "— none —":
                _psym = _ps_pick.rsplit("(", 1)[-1].rstrip(")")
                _psym = _psym if _psym.endswith(".NS") else _psym + ".NS"
                _plive = _live_quote_price(_psym)
                if _plive:
                    # default SL 2% below, TP 4% above — user can adjust
                    st.session_state["ps_entry"] = round(_plive, 2)
                    st.session_state["ps_sl"]    = round(_plive * 0.98, 2)
                    st.session_state["ps_tp"]    = round(_plive * 1.04, 2)
                    st.toast(f"Loaded live ₹{_plive:,.2f} for "
                             f"{_psym.replace('.NS','')}", icon="✅")
                    st.rerun()
                else:
                    st.warning("Live price unavailable — enter values manually.")
            else:
                st.info("Pick a stock from the list first.")

    _q_in, _q_gap, _q_out = st.columns([1, 0.12, 1])
    with _q_in.container(key="quiet_inputs"):
        st.markdown('<div class="quiet-eyebrow">Risk-first sizing</div>', unsafe_allow_html=True)
        _ps_capital   = st.number_input("Portfolio size (₹)", 50_000, 50_000_000, 500_000, 50_000, key="ps_cap")
        _ps_risk_pct  = st.slider("Risk per trade (%)", 0.5, 3.0, 1.0, 0.25, key="ps_risk_pct")
        st.markdown(f'<div class="quiet-hint">of ₹{fmt_inr(_ps_capital)} · risk budget '
                    f'₹{fmt_inr(_ps_capital * _ps_risk_pct / 100)}</div>', unsafe_allow_html=True)
        _ps_entry     = st.number_input("Entry price (₹)", min_value=1.0, max_value=100_000.0,
                                        step=0.5, key="ps_entry", format="%.2f")
        st.markdown('<div class="quiet-hint">live price if loaded · adjust for expected fill</div>',
                    unsafe_allow_html=True)
        _ps_sl        = st.number_input("Stop-loss price (₹)", min_value=1.0, max_value=100_000.0,
                                        step=0.5, key="ps_sl", format="%.2f")
        st.markdown(f'<div class="quiet-hint">{(_ps_entry - _ps_sl) / _ps_entry * 100:.2f}% below entry</div>',
                    unsafe_allow_html=True)
        _ps_tp        = st.number_input("Target price (₹)", min_value=1.0, max_value=200_000.0,
                                        step=0.5, key="ps_tp", format="%.2f")
        st.markdown('<div class="quiet-hint">a scenario level for the R:R maths, not a call</div>',
                    unsafe_allow_html=True)
        _ps_lot_size  = st.number_input("Lot size (shares, 1 for equity)", 1, 10000, 1, key="ps_lot")

    with _q_out:
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

            _rows = [
                ("Risk per share", f"₹{_rps:,.2f}"),
                ("Risk amount", f"₹{fmt_inr(_actual_risk)} · {_actual_risk / _ps_capital * 100:.2f}%"),
                ("Reward at target (scenario)", f"₹{fmt_inr(_exp_profit)}"),
                ("R:R at target (scenario)", f"{_rr:.1f} : 1"),
                ("Position value, % of capital", f"{_notional / _ps_capital * 100:.1f}%"),
            ]
            if _ps_lot_size > 1:
                _rows.append(("Lots", f"{_lots:,} × {_ps_lot_size:,}"))
            st.markdown(quiet_output(
                "Position size", f"{_shares:,}", "shares",
                f"₹{fmt_inr(_notional)} position value",
                _rows,
                note="Shares at this risk budget, rounded down to whole lots (minimum one lot). "
                     "Educational sizing maths, not investment advice.",
            ), unsafe_allow_html=True)
        else:
            st.warning("Entry price must be greater than stop-loss price.")

with _ps_tab2:
    st.markdown(
        '<div class="quiet-eyebrow">Edge-based sizing</div>'
        '<p class="page-subtitle">Kelly formula <code>f* = (b × p − q) / b</code>, where b = R:R, '
        'p = win rate, q = 1 − p. Full Kelly is volatile; the fraction slider scales it down.</p>',
        unsafe_allow_html=True,
    )

    _k_in, _k_gap, _k_out = st.columns([1, 0.12, 1])
    with _k_in.container(key="kelly_inputs"):
        _k_capital  = st.number_input("Portfolio size (₹)", 50_000, 50_000_000, 500_000, 50_000, key="k_cap")
        _k_winrate  = st.slider("Historical win rate (%)", 30, 75, 55, 1, key="k_wr") / 100
        _k_rr       = st.slider("Average R:R ratio", 0.5, 5.0, 2.0, 0.1, key="k_rr")
        _k_fraction = st.slider("Kelly fraction (0.5 = half-Kelly)", 0.1, 1.0, 0.5, 0.05, key="k_frac")
        _k_max_risk = st.slider("Max risk cap (%)", 0.5, 5.0, 2.0, 0.25, key="k_maxrisk")
        _k_entry    = st.number_input("Entry price (₹)", 1.0, 100_000.0, 500.0, 0.5, key="k_entry", format="%.2f")
        _k_sl       = st.number_input("Stop-loss (₹)",  1.0, 100_000.0, 480.0, 0.5, key="k_sl",    format="%.2f")

    from trading.signals import kelly_position_size, shares_from_risk
    with _k_out:
        try:
            _k_result   = kelly_position_size(
                win_rate=_k_winrate, rr_ratio=_k_rr,
                capital=_k_capital, fraction=_k_fraction, max_risk_pct=_k_max_risk,
            )
            _k_shares   = shares_from_risk(_k_entry, _k_sl, _k_result["risk_rs"]) if _k_entry > _k_sl else 0
            _k_notional = _k_shares * _k_entry
            _k_actual_r = _k_shares * (_k_entry - _k_sl)

            if _k_result["kelly_pct"] > 0:
                st.markdown(quiet_output(
                    "Kelly-implied size", f"{_k_shares:,}", "shares",
                    f"₹{fmt_inr(_k_notional)} position value",
                    [
                        ("Raw Kelly", f"{_k_result['kelly_pct']:.1f}%"),
                        ("Applied risk", f"{_k_result['risk_pct']:.1f}% · ₹{fmt_inr(_k_result['risk_rs'])}"),
                        ("Risk at stop", f"₹{fmt_inr(_k_actual_r)} · SL ₹{_k_sl:,.2f}"),
                    ],
                    note=_k_result["notes"],
                ), unsafe_allow_html=True)
            else:
                st.markdown(quiet_output(
                    "Kelly-implied size", "0", "shares", "",
                    [("Raw Kelly", f"{_k_result['kelly_pct']:.1f}%")],
                    note=_k_result["notes"],
                ), unsafe_allow_html=True)
                st.error("Negative Kelly — this setup has negative expected value on these inputs.")
        except Exception as _ke:
            st.error(f"Kelly calculation error: {_ke}")
