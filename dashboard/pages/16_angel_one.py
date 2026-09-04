"""Angel One - NSE Smart Investor (multipage page; body verbatim from app.py)."""
import os, sys
import logging

_log = logging.getLogger("dashboard.angel_one")
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
import streamlit as st
import sys
from dashboard.shared.design import (
    apply_design,
)
from dashboard.shared.chart_helpers import (
    _ROOT,
    render_top_bar,
)

apply_design()
render_sidebar(current="Angel One")
render_top_bar()

# ───────────────────────── page body (de-indented from app.py) ─────────────────────────
from data.angel_fetcher import (
    is_configured as _ao_is_configured,
    _get_session as _ao_get_session,
    get_profile as _ao_get_profile,
    get_funds as _ao_get_funds,
    get_holdings as _ao_get_holdings,
    get_positions as _ao_get_positions,
    get_order_book as _ao_get_orders,
    get_trade_book as _ao_get_trades,
    place_order as _ao_place_order,
    cancel_order as _ao_cancel_order,
    get_gtt_list as _ao_get_gtts,
    cancel_gtt as _ao_cancel_gtt,
    clear_session as _ao_clear_session,
)

st.title("Angel One – Broker Integration")

st.markdown("Connect your Angel One SmartAPI account for live data, real holdings, and order placement.")

_ao_ok = _ao_is_configured()

# ── Credentials setup ────────────────────────────────────────────────────
if not _ao_ok:
    st.warning(
        "**Angel One credentials not configured.**  \n"
        "Add them to `.streamlit/secrets.toml` or as environment variables to connect your account."
    )
    with st.expander("📋 Setup Instructions", expanded=True):
        st.markdown("""
**Step 1 — Get your SmartAPI key:**
1. Login to Angel One → My Profile → API Key (or visit [smartapi.angelone.in](https://smartapi.angelone.in))
2. Click **Generate API Key** → copy the key

**Step 2 — Get your TOTP secret:**
1. Angel One → Profile → Security Settings → Two-Factor Authentication → **Re-Setup**
2. Click **"Can't scan QR?"** → copy the **text key** (looks like `JBSWY3DPEHPK3PXP`)

**Step 3 — Add to `.streamlit/secrets.toml`:**
```toml
[angel_one]
api_key      = "C58Sb2tl..."        # SmartAPI key
client_id    = "AABM038127"         # Your Angel One client ID
password     = "yourpassword"       # Login password
totp_secret  = "JBSWY3DPEHPK3PXP"  # Base32 TOTP seed
```

**Or set environment variables:**
```bash
ANGEL_API_KEY=...  ANGEL_CLIENT_ID=...  ANGEL_PASSWORD=...  ANGEL_TOTP_SECRET=...
```

**Step 4 — Restart Streamlit** after adding credentials.
""")
    st.stop()

# ── Connected — show tabs ────────────────────────────────────────────────
st.success("Angel One connected", icon="🟢")

tab_ao1, tab_ao2, tab_ao3, tab_ao4, tab_ao5 = st.tabs([
    "📊 Account Overview",
    "💼 Holdings",
    "⚡ Today's Positions",
    "📋 Orders & Trades",
    "🛒 Quick Order",
])

# ── TAB 1: ACCOUNT OVERVIEW ───────────────────────────────────────────────
with tab_ao1:
    st.subheader("Account Overview")
    col_p, col_f = st.columns(2)

    with col_p:
        try:
            _prof = _ao_get_profile()
            if _prof:
                st.markdown(
                    f'<div class="card-blue"><b>{_prof["name"]}</b><br>'
                    f'Client ID: {_prof["client_id"]}<br>'
                    f'Email: {_prof["email"]}<br>'
                    f'Exchanges: {", ".join(_prof["exchanges"])}</div>',
                    unsafe_allow_html=True,
                )
        except Exception as e:
            _log.debug("Angel One profile display failed: %s", e)
            st.markdown("*Profile unavailable*")

    with col_f:
        try:
            _funds = _ao_get_funds()
            if _funds:
                _cash = _funds["available_cash"]
                _used = _funds["used_margin"]
                _m2m  = _funds["m2m"]
                _m2m_clr = "#26a69a" if _m2m >= 0 else "#ef5350"
                st.markdown(
                    f'<div class="card-green">'
                    f'<div class="metric-lbl">Available Cash</div>'
                    f'<div class="metric-val">Rs {_cash:,.0f}</div>'
                    f'Used Margin: Rs {_used:,.0f}<br>'
                    f'Unrealised P&L: <span style="color:{_m2m_clr}">Rs {_m2m:+,.0f}</span>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
        except Exception as e:
            _log.debug("Angel One funds display failed: %s", e)
            st.markdown("*Funds data unavailable*")

    if st.button("🔄 Refresh Session", key="ao_refresh"):
        # FIX MKT6: was also calling a blanket st.cache_data.clear() here,
        # which wiped every other page's cached data (Top Picks, watchlist
        # scans, etc.) for zero benefit — this page doesn't actually use
        # st.cache_data for any of its own data (funds/holdings/positions
        # are fetched live from angel_fetcher on every rerun already).
        # _ao_clear_session() is what actually matters: it forces a fresh
        # login on the next request.
        _ao_clear_session()
        st.success("Session cleared — reconnecting on next request")
        st.rerun()

# ── TAB 2: HOLDINGS ────────────────────────────────────────────────────────
with tab_ao2:
    st.subheader("Demat Holdings")
    with st.spinner("Fetching holdings from Angel One…"):
        _holdings = _ao_get_holdings()

    if _holdings is None:
        st.error("Could not fetch holdings. Check credentials and try again.")
    elif len(_holdings) == 0:
        st.info("No holdings found in your demat account.")
    else:
        _total_invested = sum(h["avg_price"] * h["qty"] for h in _holdings)
        _total_value    = sum(h["value_rs"] for h in _holdings)
        _total_pnl      = _total_value - _total_invested
        _total_pnl_pct  = (_total_pnl / _total_invested * 100) if _total_invested > 0 else 0

        mh1, mh2, mh3, mh4 = st.columns(4)
        mh1.metric("Stocks", len(_holdings))
        mh2.metric("Portfolio Value", f"Rs {_total_value:,.0f}")
        mh3.metric("Total P&L",
                   f"Rs {_total_pnl:+,.0f}",
                   delta=f"{_total_pnl_pct:+.2f}%",
                   delta_color="normal")
        mh4.metric("Invested", f"Rs {_total_invested:,.0f}")

        st.markdown("---")

        _hdf = pd.DataFrame(_holdings)
        _hdf = _hdf[["symbol", "qty", "avg_price", "ltp", "pnl", "pnl_pct", "value_rs"]]
        _hdf.columns = ["Symbol", "Qty", "Avg Price", "LTP", "P&L (Rs)", "P&L %", "Value (Rs)"]

        def _color_pnl(val):
            if isinstance(val, (int, float)):
                color = "#26a69a" if val >= 0 else "#ef5350"
                return f"color: {color}; font-weight:600"
            return ""

        _hdf_styled = (
            _hdf.style
            .format({
                "Avg Price": "Rs {:.2f}",
                "LTP":       "Rs {:.2f}",
                "P&L (Rs)":  "Rs {:.0f}",
                "P&L %":     "{:.2f}%",
                "Value (Rs)":"Rs {:.0f}",
            })
            .map(_color_pnl, subset=["P&L (Rs)", "P&L %"])
        )
        st.dataframe(_hdf_styled, hide_index=True, width="stretch")

        # Export
        _holdings_csv = _hdf.to_csv(index=False).encode("utf-8")
        st.download_button(
            "⬇ Export Holdings CSV",
            _holdings_csv,
            file_name="angel_one_holdings.csv",
            mime="text/csv",
        )

# ── TAB 3: TODAY'S POSITIONS ───────────────────────────────────────────────
with tab_ao3:
    st.subheader("Today's Positions")
    with st.spinner("Fetching positions…"):
        _positions = _ao_get_positions()

    if _positions is None:
        st.error("Could not fetch positions.")
    else:
        _net_pos = _positions.get("net", [])
        if not _net_pos:
            st.info("No open positions today.")
        else:
            _pos_df = pd.DataFrame(_net_pos)
            _pos_df = _pos_df[["symbol", "qty", "avg_price", "ltp", "pnl", "product", "side"]]
            _pos_df.columns = ["Symbol", "Qty", "Avg Price", "LTP", "P&L", "Product", "Side"]

            _total_pos_pnl = sum(p["pnl"] for p in _net_pos)
            pos_c1, pos_c2, pos_c3 = st.columns(3)
            pos_c1.metric("Open Positions", len(_net_pos))
            pos_c2.metric("Total P&L Today",
                          f"Rs {_total_pos_pnl:+,.0f}",
                          delta_color="normal")
            pos_c3.metric("Long / Short",
                          f"{sum(1 for p in _net_pos if p['qty']>0)} / "
                          f"{sum(1 for p in _net_pos if p['qty']<0)}")

            st.dataframe(
                _pos_df.style
                .format({
                    "Avg Price": "Rs {:.2f}",
                    "LTP":       "Rs {:.2f}",
                    "P&L":       "Rs {:.0f}",
                })
                .map(lambda v: "color:#26a69a;font-weight:600" if isinstance(v, (int,float)) and v >= 0
                     else ("color:#ef5350;font-weight:600" if isinstance(v, (int,float)) else ""),
                     subset=["P&L"]),
                hide_index=True,
                width="stretch",
            )

# ── TAB 4: ORDERS & TRADES ─────────────────────────────────────────────────
with tab_ao4:
    st.subheader("Today's Orders & Trades")
    ord_t1, ord_t2, ord_t3 = st.tabs(["📑 Order Book", "✅ Trade Book", "🎯 GTT Orders"])

    with ord_t1:
        with st.spinner("Fetching order book…"):
            _orders = _ao_get_orders()
        if _orders is None:
            st.error("Could not fetch orders.")
        elif not _orders:
            st.info("No orders today.")
        else:
            _odf = pd.DataFrame(_orders)[
                ["order_id", "symbol", "side", "qty", "filled_qty",
                 "order_type", "price", "avg_price", "status", "time"]
            ]
            _odf.columns = ["Order ID", "Symbol", "Side", "Qty", "Filled",
                             "Type", "Price", "Fill Price", "Status", "Time"]

            def _status_color(val):
                colors = {
                    "complete": "#26a69a", "rejected": "#ef5350",
                    "cancelled": "#888",   "open": "#f9a825",
                    "pending": "#f9a825",
                }
                c = colors.get(str(val).lower(), "#aaa")
                return f"color:{c}; font-weight:600"

            st.dataframe(
                _odf.style.map(_status_color, subset=["Status"]),
                hide_index=True,
                width="stretch",
            )

            # Cancel pending order
            _pending = [o for o in _orders if o["status"].lower() in ("open", "pending", "trigger pending")]
            if _pending:
                st.markdown("**Cancel Pending Order:**")
                _cancel_opts = {f"{o['symbol']} — {o['side']} {o['qty']} @ {o['price']}": o["order_id"]
                                for o in _pending}
                _to_cancel = st.selectbox("Select order", list(_cancel_opts.keys()), key="ao_cancel_sel")
                if st.button("Cancel Order", key="ao_cancel_btn", type="primary"):
                    if _ao_cancel_order(_cancel_opts[_to_cancel]):
                        st.success("Order cancelled")
                        st.rerun()
                    else:
                        st.error("Cancel failed — order may already be processed")

    with ord_t2:
        with st.spinner("Fetching trade book…"):
            _trades = _ao_get_trades()
        if _trades is None:
            st.error("Could not fetch trades.")
        elif not _trades:
            st.info("No executed trades today.")
        else:
            _tdf = pd.DataFrame(_trades)[
                ["symbol", "side", "qty", "price", "product", "time"]
            ]
            _tdf.columns = ["Symbol", "Side", "Qty", "Price", "Product", "Time"]
            _total_traded = sum(
                t["qty"] * t["price"]
                for t in _trades
                if isinstance(t.get("qty"), (int, float)) and isinstance(t.get("price"), (int, float))
            )
            st.metric("Total Turnover Today", f"Rs {_total_traded:,.0f}")
            st.dataframe(_tdf, hide_index=True, width="stretch")

    with ord_t3:
        with st.spinner("Fetching GTT rules…"):
            _gtts = _ao_get_gtts()
        if _gtts is None:
            st.error("Could not fetch GTT rules.")
        elif not _gtts:
            st.info("No active GTT orders.")
        else:
            _gdf = pd.DataFrame(_gtts)[
                ["rule_id", "symbol", "side", "qty", "trigger", "limit_price", "status"]
            ]
            _gdf.columns = ["Rule ID", "Symbol", "Side", "Qty", "Trigger", "Limit", "Status"]
            st.dataframe(_gdf, hide_index=True, width="stretch")

            _active_gtts = [g for g in _gtts if g["status"].lower() in ("new", "active")]
            if _active_gtts:
                st.markdown("**Cancel GTT:**")
                _gtt_opts = {f"{g['symbol']} {g['side']} {g['qty']} @ trigger {g['trigger']}": g
                             for g in _active_gtts}
                _gtt_sel = st.selectbox("Select GTT", list(_gtt_opts.keys()), key="ao_gtt_sel")
                if st.button("Cancel GTT", key="ao_gtt_cancel_btn"):
                    _g = _gtt_opts[_gtt_sel]
                    if _ao_cancel_gtt(_g["rule_id"], _g["symbol"]):
                        st.success("GTT cancelled")
                        st.rerun()
                    else:
                        st.error("Could not cancel GTT")

# ── TAB 5: QUICK ORDER ─────────────────────────────────────────────────────
with tab_ao5:
    st.subheader("Quick Order")
    st.warning(
        "This places a **real order** in your Angel One account using live funds. "
        "Double-check all details before confirming.",
        icon="⚠️",
    )

    qo_c1, qo_c2 = st.columns(2)
    with qo_c1:
        _qo_sym   = st.text_input("Stock Symbol (NSE)", value="", placeholder="e.g. RELIANCE", key="qo_sym").strip().upper()
        _qo_qty   = st.number_input("Quantity", min_value=1, value=1, step=1, key="qo_qty")
        _qo_side  = st.radio("Transaction", ["BUY", "SELL"], horizontal=True, key="qo_side")
        _qo_prod  = st.radio("Product", ["DELIVERY", "INTRADAY"], horizontal=True, key="qo_prod")

    with qo_c2:
        _qo_type  = st.selectbox("Order Type", ["MARKET", "LIMIT", "SL", "SL-M"], key="qo_type")
        _qo_price = st.number_input("Limit/Trigger Price (0 = market)",
                                     min_value=0.0, value=0.0, step=0.05, format="%.2f", key="qo_price")
        _qo_trig  = st.number_input("SL Trigger Price (only for SL orders)",
                                     min_value=0.0, value=0.0, step=0.05, format="%.2f", key="qo_trig")
        _qo_valid = st.radio("Validity", ["DAY", "IOC"], horizontal=True, key="qo_valid")

    if _qo_sym:
        _card_cls = "order-buy" if _qo_side == "BUY" else "order-sell"
        st.markdown(
            f'<div class="{_card_cls}">'
            f'<b>{_qo_side} {_qo_qty} × {_qo_sym}</b>  |  '
            f'{_qo_prod} · {_qo_type}'
            + (f'  |  Price: Rs {_qo_price:.2f}' if _qo_price > 0 else "  |  Market Order")
            + f'</div>',
            unsafe_allow_html=True,
        )

    _ao_confirm = st.checkbox(
        "I confirm this is a real order with real money", key="qo_confirm"
    )
    _place_col, _ = st.columns([1, 3])
    with _place_col:
        if st.button("Place Order", type="primary", key="qo_place",
                     disabled=not (_qo_sym and _ao_confirm)):
            with st.spinner("Placing order…"):
                _result = _ao_place_order(
                    symbol=_qo_sym,
                    qty=int(_qo_qty),
                    side=_qo_side,
                    order_type=_qo_type,
                    price=float(_qo_price),
                    trigger_price=float(_qo_trig),
                    product=_qo_prod,
                    validity=_qo_valid,
                )
            if _result and _result.get("status") == "placed":
                st.success(f"Order placed! Order ID: {_result.get('order_id')}")
            elif _result:
                st.error(f"Order failed: {_result.get('message', 'Unknown error')}")
            else:
                st.error("Could not connect to Angel One — check session")
