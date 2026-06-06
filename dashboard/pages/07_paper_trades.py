"""Paper Trades - NSE Smart Investor (multipage page; body verbatim from app.py)."""
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
from dashboard.shared.cache import (
    STOCK_SEARCH_MAP,
    _validate_ticker,
)
from dashboard.shared.trade_utils import (
    _auto_close_breached,
    _ensure_paper_db,
    _portfolio_live_prices,
    _render_autoclose_banner,
    load_trades_by_account,
    paper_account_type,
    paper_close_trade,
    paper_delete_account,
    paper_edit_trade,
    paper_list_accounts,
    paper_open_trade,
    paper_rename_account,
    set_paper_account_type,
)
from dashboard.shared.chart_helpers import (
    _ROOT,
    render_top_bar,
)

apply_design()
render_sidebar(current="Paper Trades")
render_top_bar()

# ───────────────────────── page body (de-indented from app.py) ─────────────────────────
st.title("📂 Paper Trading Simulator")
st.markdown(
    "Practice trading **without real money**. Open virtual trades, track live P&L, "
    "and measure your decision quality over time. All prices are from live market data."
)

# Pre-fill ticker if navigated from Market Live / Market Overview "Trade" button
if "pt_prefill_ticker" in st.session_state and st.session_state["pt_prefill_ticker"]:
    _pf_sym = st.session_state.pop("pt_prefill_ticker")
    _pf_clean = _pf_sym.replace(".NS", "")
    st.session_state["pt_manual_tk"] = _pf_clean
    st.info(f"📝 Pre-filled from Market Overview: **{_pf_clean}** — live price loading…")

_ensure_paper_db()

# ── ACCOUNT MANAGEMENT BAR ─────────────────────────────────────────────────
_all_accounts = paper_list_accounts()
# Ensure session state has a valid account
if "pt_account" not in st.session_state or st.session_state["pt_account"] not in _all_accounts:
    st.session_state["pt_account"] = _all_accounts[0]

with st.container():
    st.markdown(
        '<div style="background:#0d1f3c;padding:12px 18px;border-radius:10px;'
        'border-left:5px solid #2196F3;margin-bottom:16px">',
        unsafe_allow_html=True,
    )
    _acc_c1, _acc_c2, _acc_c3, _acc_c4, _acc_c5 = st.columns([3, 1, 1, 1, 1])

    with _acc_c1:
        _selected_account = st.selectbox(
            "📂 Active Account",
            options=_all_accounts,
            index=_all_accounts.index(st.session_state["pt_account"]),
            key="pt_account_sel",
            label_visibility="collapsed",
        )
        st.session_state["pt_account"] = _selected_account
        _acc_type = paper_account_type(_selected_account)
        _at_badge = ("🔆 INTRADAY (MIS)" if _acc_type == "MIS" else "📦 DELIVERY (CNC)")
        _at_col   = "#ff9500" if _acc_type == "MIS" else "#5b8def"
        st.markdown(
            f'<span style="font-size:11px">📂 <b>{_selected_account}</b> '
            f'<span style="color:{_at_col};font-weight:700">· {_at_badge}</span></span>',
            unsafe_allow_html=True,
        )

    with _acc_c2:
        _new_acc_name = st.text_input(
            "New account name", value="", placeholder="New account…",
            label_visibility="collapsed", key="pt_new_acc_input"
        ).strip()
        _new_acc_type = st.radio(
            "Type", ["Delivery", "Intraday"], horizontal=True,
            label_visibility="collapsed", key="pt_new_acc_type",
        )

    with _acc_c3:
        st.write("")
        if st.button("➕ Create", key="pt_create_acc", use_container_width=True):
            if _new_acc_name and _new_acc_name not in _all_accounts:
                set_paper_account_type(_new_acc_name,
                                       "MIS" if _new_acc_type == "Intraday" else "CNC")
                st.session_state["pt_account"] = _new_acc_name
                st.success(f"**{_new_acc_name}** ({_new_acc_type}) created. Open your first trade to save it.")
                st.rerun()
            elif _new_acc_name in _all_accounts:
                st.warning("Account already exists.")

    with _acc_c4:
        st.write("")
        _rename_to = st.text_input(
            "Rename to", value="", placeholder="Rename to…",
            label_visibility="collapsed", key="pt_rename_input"
        ).strip()

    with _acc_c5:
        st.write("")
        if st.button("✏️ Rename", key="pt_rename_acc", use_container_width=True):
            if _rename_to and _rename_to != _selected_account:
                paper_rename_account(_selected_account, _rename_to)
                st.session_state["pt_account"] = _rename_to
                st.success(f"Renamed to **{_rename_to}**")
                st.rerun()
            elif not _rename_to:
                st.warning("Enter a new name first.")

    st.markdown("</div>", unsafe_allow_html=True)

# Delete account (separate row to avoid layout clutter)
if len(_all_accounts) > 1:
    with st.expander("🗑️ Danger Zone — Delete Account", expanded=False):
        st.warning(
            f"This will permanently delete **all trades** in account "
            f"**{_selected_account}**. This cannot be undone."
        )
        _del_confirm = st.checkbox(
            f"Yes, I want to delete account '{_selected_account}' and all its trades",
            key="pt_del_confirm"
        )
        if st.button("🗑️ Delete Account", key="pt_delete_acc",
                     disabled=not _del_confirm, type="secondary"):
            paper_delete_account(_selected_account)
            # Switch to first remaining account
            _remaining = [a for a in _all_accounts if a != _selected_account]
            st.session_state["pt_account"] = _remaining[0] if _remaining else "My Account"
            st.success(f"Account **{_selected_account}** deleted.")
            st.rerun()

# ── Intraday (MIS) square-off reminder ─────────────────────────────────────
if paper_account_type(_selected_account) == "MIS":
    import datetime as _sqdt
    _ist_now = _sqdt.datetime.now(_sqdt.timezone(_sqdt.timedelta(hours=5, minutes=30)))
    _is_weekday = _ist_now.weekday() < 5
    _mins_to_close = (15 * 60 + 20) - (_ist_now.hour * 60 + _ist_now.minute)  # to 3:20 PM
    if _is_weekday and 0 < _mins_to_close <= 60:
        st.markdown(
            f'<div class="card-red pulse-red" style="margin:6px 0">'
            f'⏰ <b>Intraday square-off in {_mins_to_close} min</b> (by 3:20 PM). '
            f'Close MIS positions now — brokers auto-square-off intraday trades near close.</div>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            '<div class="card-yellow" style="margin:6px 0">'
            '🔆 <b>Intraday (MIS) account</b> — positions are meant to be closed the same day '
            '(by ~3:20 PM). Use tighter stops than delivery.</div>',
            unsafe_allow_html=True,
        )

st.markdown("---")

# ── LIVE PRICE + ATR SUGGESTIONS (cached 60 s per ticker) ─────────────────
@st.cache_data(ttl=60, show_spinner=False)
def _paper_trade_suggestions(ticker: str) -> dict:
    """
    Live price (Yahoo JSON API) + ATR-based SL/TP + RSI + trend.
    All data sources are cloud-safe (no yfinance rate limits).
    Returns dict: price, prev, chg, atr, sl, tp, rsi, trend, qty_suggest, error
    """
    import pandas as _pd2
    from utils.live_price import get_live_quote
    from data.fetcher import fetch_single

    result = {"price": None, "prev": None, "chg": 0.0,
              "atr": None, "sl": None, "tp": None,
              "rsi": None, "trend": "—", "qty_suggest": 1, "error": ""}
    try:
        # ── Live price via Yahoo JSON API / NSE / Stooq ────────────────
        q = get_live_quote(ticker)
        if not isinstance(q, dict) or not q.get("price"):
            result["error"] = "Price unavailable — all sources failed. Try again in 30 s."
            return result

        price = q["price"]
        prev  = q["prev_close"]
        chg   = q["chg_pct"]
        result.update({"price": price, "prev": prev, "chg": chg})

        # ── Historical data for ATR + RSI + trend via Stooq ───────────
        df = fetch_single(ticker, period="3mo")
        df = df.dropna(subset=["Close"])
        if len(df) < 15:
            # Fallback: simple % stops
            result["sl"] = round(price * 0.97, 2)   # 3% stop
            result["tp"] = round(price * 1.06, 2)   # 6% target → 2:1
            result["qty_suggest"] = max(1, int(10000 / price))
            return result

        # ATR (14)
        hi, lo, cl = df["High"], df["Low"], df["Close"]
        tr  = _pd2.concat([hi - lo,
                            (hi - cl.shift()).abs(),
                            (lo - cl.shift()).abs()], axis=1).max(axis=1)
        atr = float(tr.rolling(14).mean().dropna().iloc[-1])
        result["atr"] = atr

        # Stop = 1.5 × ATR below live price  →  tight but realistic
        # Target = 3.0 × ATR above live price  →  exactly 2:1 R:R
        sl_calc = round(price - 1.5 * atr, 2)
        tp_calc = round(price + 3.0 * atr, 2)
        result["sl"] = max(0.01, sl_calc)
        result["tp"] = tp_calc

        # RSI (14)
        delta = cl.diff()
        gain  = delta.clip(lower=0).rolling(14).mean()
        loss  = (-delta.clip(upper=0)).rolling(14).mean()
        rsi   = float((100 - 100 / (1 + gain / loss)).dropna().iloc[-1])
        result["rsi"] = rsi

        # Simple trend signal
        sma50  = float(cl.rolling(50).mean().iloc[-1]) if len(df) >= 50 else price
        sma200 = float(cl.rolling(200).mean().iloc[-1]) if len(df) >= 200 else price
        if price > sma50 > sma200:
            result["trend"] = "🟢 Uptrend (above SMA50 & SMA200)"
        elif price > sma50:
            result["trend"] = "🟡 Moderate (above SMA50)"
        elif price < sma50 < sma200:
            result["trend"] = "🔴 Downtrend (below SMA50 & SMA200)"
        else:
            result["trend"] = "🟡 Mixed — check chart"

        # Suggested qty: ~₹10,000 position (small safe default)
        result["qty_suggest"] = max(1, int(10000 / price))

    except Exception as _exc:
        result["error"] = str(_exc)
    return result

# ── NEW TRADE FORM ─────────────────────────────────────────────────────────
with st.expander("➕ Open a New Paper Trade", expanded=True):
    st.markdown(
        "**Select a stock** — the entry price, stop-loss, and target are auto-filled "
        "from live market data and ATR analysis. You can adjust them freely before submitting."
    )
    _search_opts = sorted([f"{n}  ({s.replace('.NS','')})" for n, s in STOCK_SEARCH_MAP.items()])
    _fc1, _fc2 = st.columns([3, 2])
    with _fc1:
        _form_sel = st.selectbox("Search by company name", ["— choose stock —"] + _search_opts, key="pt_stock_sel")
    with _fc2:
        _form_manual = st.text_input("Or type NSE ticker directly", key="pt_manual_tk",
                                     placeholder="e.g. INFY").strip().upper()

    # Validate the manually-typed symbol before any API call
    _pf_clean, _pf_err = _validate_ticker(_form_manual)
    if _pf_err:
        st.error(f"⚠️ {_pf_err}")

    # Resolve ticker
    _form_ticker = ""
    if _pf_clean and not _pf_err:
        _form_ticker = _pf_clean + ".NS"
    elif _form_sel != "— choose stock —":
        _raw = _form_sel.rsplit("(", 1)[-1].rstrip(")")
        _form_ticker = _raw + ".NS" if not _raw.endswith(".NS") else _raw

    # ── Fetch live data & suggestions ─────────────────────────────────
    _sugg = {"price": None, "sl": None, "tp": None, "qty_suggest": 10,
             "atr": None, "rsi": None, "trend": "—", "chg": 0.0, "error": ""}
    if _form_ticker:
        with st.spinner(f"Fetching live price & ATR for {_form_ticker.replace('.NS','')}…"):
            _sugg = _paper_trade_suggestions(_form_ticker)

    # ── Suggestion banner ──────────────────────────────────────────────
    if _form_ticker and _sugg["price"]:
        _p    = _sugg["price"]
        _atr  = _sugg["atr"]
        _rsi  = _sugg["rsi"]
        _atr_str = f"₹{_atr:.2f}" if _atr else "—"
        _rsi_str = f"{_rsi:.0f}" if _rsi else "—"
        _rsi_label = (
            "🔴 Overbought — watch for pullback" if (_rsi and _rsi > 70)
            else "🟢 Oversold — bounce candidate"  if (_rsi and _rsi < 30)
            else "🟡 Neutral momentum"              if _rsi
            else ""
        )
        st.markdown(
            f'<div style="background:#0d1f3c;padding:12px 18px;border-radius:10px;'
            f'border-left:5px solid #2196F3;margin:8px 0">'
            f'<b style="font-size:18px">₹{_p:,.2f}</b>'
            f'<span style="color:{"#26a69a" if _sugg["chg"]>=0 else "#ef5350"};margin-left:10px">'
            f'{"▲" if _sugg["chg"]>=0 else "▼"} {abs(_sugg["chg"]):.2f}% today</span>'
            f'<br><span style="font-size:12px;color:#aaa">'
            f'ATR(14): {_atr_str} &nbsp;|&nbsp; RSI: {_rsi_str} {_rsi_label}'
            f' &nbsp;|&nbsp; Trend: {_sugg["trend"]}</span>'
            f'</div>',
            unsafe_allow_html=True
        )
    elif _form_ticker and _sugg["error"]:
        st.warning(f"⚠️ {_sugg['error']}")

    # ── Input fields — defaults from live data, keyed by ticker so they
    #    reset automatically when the user picks a different stock ────────
    _tk_key = _form_ticker or "none"      # key suffix changes → fresh widget defaults
    _def_price = _sugg["price"]  or 100.0
    _def_sl    = _sugg["sl"]     or round(_def_price * 0.97, 2)
    _def_tp    = _sugg["tp"]     or round(_def_price * 1.06, 2)
    _def_qty   = _sugg["qty_suggest"] or 10

    _pa, _pb, _pc, _pd = st.columns(4)
    _form_qty   = _pa.number_input(
        "Quantity (shares)", 1, 1000000, _def_qty,
        key=f"pt_qty_{_tk_key}"
    )
    _form_price = _pb.number_input(
        "Entry Price (₹) — live", 0.01, 1e7, float(_def_price),
        key=f"pt_price_{_tk_key}", format="%.2f"
    )
    _form_sl    = _pc.number_input(
        "Stop-Loss (₹) — ATR-based", 0.01, 1e7, float(_def_sl),
        key=f"pt_sl_{_tk_key}", format="%.2f",
        help="Default = 1.5× ATR below live price. Adjust to your preferred risk level."
    )
    _form_tp    = _pd.number_input(
        "Target (₹) — 2:1 R:R", 0.01, 1e7, float(_def_tp),
        key=f"pt_tp_{_tk_key}", format="%.2f",
        help="Default = 3× ATR above live price (gives 2:1 Risk:Reward). Adjust as needed."
    )

    # ── Live Risk:Reward summary ───────────────────────────────────────
    if _form_price > 0 and _form_sl < _form_price and _form_tp > _form_price:
        _risk_ps  = _form_price - _form_sl
        _rew_ps   = _form_tp    - _form_price
        _rr_ratio = _rew_ps / _risk_ps if _risk_ps > 0 else 0
        _cap_risk = _risk_ps * _form_qty
        _cap_rew  = _rew_ps  * _form_qty
        _rr_color = "#26a69a" if _rr_ratio >= 1.5 else "#f9a825" if _rr_ratio >= 1.0 else "#ef5350"
        st.markdown(
            f'<div style="background:#1a1a2a;padding:10px 16px;border-radius:8px;margin:8px 0">'
            f'Risk/share: <b style="color:#ef5350">₹{_risk_ps:.2f}</b> &nbsp;|&nbsp; '
            f'Reward/share: <b style="color:#26a69a">₹{_rew_ps:.2f}</b> &nbsp;|&nbsp; '
            f'<span style="color:{_rr_color}"><b>R:R = {_rr_ratio:.1f}:1</b></span> &nbsp;|&nbsp; '
            f'Max loss on trade: <b style="color:#ef5350">₹{_cap_risk:,.0f}</b> &nbsp;|&nbsp; '
            f'Max gain on trade: <b style="color:#26a69a">₹{_cap_rew:,.0f}</b>'
            f'</div>',
            unsafe_allow_html=True
        )
        if _rr_ratio < 1.0:
            st.error("⛔ R:R below 1:1 — you risk more than you can gain. Adjust your stop or target.")
        elif _rr_ratio < 1.5:
            st.warning("⚠️ R:R below 1.5:1 — minimum recommended is 1.5:1 for a consistent edge.")
        else:
            st.success(f"✅ Good R:R ({_rr_ratio:.1f}:1) — trade setup meets the minimum quality bar.")

    _form_reason = st.text_input(
        "Reason / notes (optional)", key="pt_reason",
        placeholder="e.g. RSI oversold bounce at SMA50 support — score 72"
    )

    if st.button("🟢 Open Paper Trade", type="primary", key="pt_submit"):
        if not _form_ticker:
            st.error("Please select a stock first.")
        elif _form_sl >= _form_price:
            st.error("Stop-loss must be BELOW entry price.")
        elif _form_tp <= _form_price:
            st.error("Target must be ABOVE entry price.")
        else:
            _new_id = paper_open_trade(
                _form_ticker, _form_price, int(_form_qty),
                sl=_form_sl, tp=_form_tp, reason=_form_reason,
                account=st.session_state.get("pt_account", "My Account"),
            )
            st.success(
                f"✅ Paper trade #{_new_id} opened in **{st.session_state.get('pt_account','My Account')}**: "
                f"**{int(_form_qty)} × {_form_ticker.replace('.NS','')}** @ ₹{_form_price:,.2f}  "
                f"| SL ₹{_form_sl:,.2f} | Target ₹{_form_tp:,.2f}"
            )
            st.cache_data.clear()

st.markdown("---")

# ── LOAD TRADES FOR CURRENT ACCOUNT ───────────────────────────────────────
_hcol, _tcol, _rcol = st.columns([4, 2, 1])
with _hcol:
    st.markdown(f"#### 📂 {st.session_state.get('pt_account', 'My Account')}")
with _tcol:
    _pt_autoclose = st.toggle(
        "🤖 Auto-close SL/TP", value=st.session_state.get("auto_close_on", True),
        key="pt_autoclose_toggle",
        help="Automatically close any position that hits its target or stop-loss "
             "on page load — during market hours only, on live prices.",
    )
    st.session_state["auto_close_on"] = _pt_autoclose
with _rcol:
    st.write("")
    if st.button("🔄 Refresh", key="paper_refresh"):
        st.cache_data.clear()

# Run auto-close for this account, then surface what was closed
if _pt_autoclose:
    _pt_closed = _auto_close_breached(account=st.session_state.get("pt_account", "My Account"))
    if _pt_closed:
        _render_autoclose_banner(_pt_closed)
        st.cache_data.clear()

trades = load_trades_by_account(st.session_state.get("pt_account", "My Account"))

if trades.empty:
    st.info("No paper trades yet. Open your first trade using the form above.")
else:
    open_t     = trades[trades["status"] == "OPEN"]    if "status" in trades.columns else pd.DataFrame()
    closed_t   = trades[trades["status"] == "CLOSED"]  if "status" in trades.columns else pd.DataFrame()
    stopped_t  = trades[trades["status"] == "STOPPED"] if "status" in trades.columns else pd.DataFrame()
    all_closed = pd.concat([closed_t, stopped_t], ignore_index=True)

    # ── Fetch live prices BEFORE summary so we can show unrealised P&L ──
    _open_syms = tuple(open_t["ticker"].tolist()) if not open_t.empty else ()
    _open_lp   = _portfolio_live_prices(_open_syms) if _open_syms else {}

    # ── Aggregate account-level P&L ────────────────────────────────────
    _pt_deployed   = 0.0
    _pt_unrealised = 0.0
    _pt_today_pnl  = 0.0
    for _, _orow in open_t.iterrows():
        _o_ep   = float(_orow.get("price",    0) or 0)
        _o_qty  = int(  _orow.get("quantity", 0) or 0)
        _o_lp   = _open_lp.get(str(_orow["ticker"]), {})
        _o_cur  = _o_lp.get("price", _o_ep)
        _o_prv  = _o_lp.get("prev",  _o_cur)
        _pt_deployed   += _o_ep  * _o_qty
        _pt_unrealised += (_o_cur - _o_ep) * _o_qty
        _pt_today_pnl  += (_o_cur - _o_prv) * _o_qty

    _pt_realised = 0.0
    _wins_cnt    = 0
    if not all_closed.empty and "pnl" in all_closed.columns:
        _all_cl_pnl  = pd.to_numeric(all_closed["pnl"], errors="coerce")
        _pt_realised = float(_all_cl_pnl.sum())
        _wins_cnt    = int((_all_cl_pnl > 0).sum())

    _pt_unr_pct = (_pt_unrealised / _pt_deployed * 100) if _pt_deployed > 0 else 0

    # ── Account Dashboard Card ─────────────────────────────────────────
    _ac_name  = st.session_state.get("pt_account", "My Account")
    _ur_col = "#26a69a" if _pt_unrealised >= 0 else "#ef5350"
    _re_col = "#26a69a" if _pt_realised   >= 0 else "#ef5350"
    _td_col = "#26a69a" if _pt_today_pnl  >= 0 else "#ef5350"
    _ur_arr = "▲" if _pt_unrealised >= 0 else "▼"
    _re_arr = "▲" if _pt_realised   >= 0 else "▼"
    _td_arr = "▲" if _pt_today_pnl  >= 0 else "▼"
    _n_open   = len(open_t)
    _n_closed = len(all_closed)
    st.markdown(
        f'<div style="background:#0d1f3c;border-radius:12px;padding:18px 22px;'
        f'margin-bottom:16px;border-left:5px solid #2196F3">'
        f'<div style="font-size:11px;color:#5c8dd6;text-transform:uppercase;'
        f'letter-spacing:1.5px;margin-bottom:12px">📂 {_ac_name}</div>'
        f'<div style="display:flex;gap:20px;flex-wrap:wrap;align-items:flex-end">'

        f'<div style="flex:1;min-width:130px">'
        f'<div style="font-size:10px;color:#aaa;text-transform:uppercase;letter-spacing:1px;margin-bottom:3px">Today\'s P&amp;L</div>'
        f'<div style="font-size:22px;font-weight:700;color:{_td_col}">{_td_arr} ₹{abs(_pt_today_pnl):,.0f}</div>'
        f'</div>'

        f'<div style="flex:1;min-width:130px">'
        f'<div style="font-size:10px;color:#aaa;text-transform:uppercase;letter-spacing:1px;margin-bottom:3px">Unrealised P&amp;L</div>'
        f'<div style="font-size:22px;font-weight:700;color:{_ur_col}">{_ur_arr} ₹{abs(_pt_unrealised):,.0f} '
        f'<span style="font-size:13px">({_pt_unr_pct:+.1f}%)</span></div>'
        f'</div>'

        f'<div style="flex:1;min-width:130px">'
        f'<div style="font-size:10px;color:#aaa;text-transform:uppercase;letter-spacing:1px;margin-bottom:3px">'
        f'Realised P&amp;L &nbsp;<span style="color:#888">({_wins_cnt}/{_n_closed} won)</span></div>'
        f'<div style="font-size:22px;font-weight:700;color:{_re_col}">{_re_arr} ₹{abs(_pt_realised):,.0f}</div>'
        f'</div>'

        f'<div style="flex:1;min-width:130px">'
        f'<div style="font-size:10px;color:#aaa;text-transform:uppercase;letter-spacing:1px;margin-bottom:3px">Deployed Capital</div>'
        f'<div style="font-size:22px;font-weight:700;color:#fff">₹{_pt_deployed:,.0f}</div>'
        f'</div>'

        f'<div style="flex:1;min-width:130px">'
        f'<div style="font-size:10px;color:#aaa;text-transform:uppercase;letter-spacing:1px;margin-bottom:3px">Positions</div>'
        f'<div style="font-size:20px;font-weight:700">'
        f'<span style="color:#26a69a">{_n_open}</span> open &nbsp; '
        f'<span style="color:#aaa;font-size:16px">{_n_closed} closed</span></div>'
        f'</div>'

        f'</div></div>',
        unsafe_allow_html=True,
    )

    st.markdown("---")

    # ── OPEN POSITIONS — compact cards with progress bar ───────────────
    if not open_t.empty:
        st.subheader("📌 Open Positions")

        for _, _row in open_t.iterrows():
            _tk   = _row["ticker"]
            _ep   = float(_row["price"])
            _qty  = int(_row["quantity"])
            _sl   = float(_row["sl"]) if _row.get("sl") else (_ep * 0.95)
            _tp   = float(_row["tp"]) if _row.get("tp") else (_ep * 1.10)
            _lp   = _open_lp.get(_tk, {})
            _cur  = _lp.get("price", _ep)
            _prv  = _lp.get("prev", _cur)
            _unr  = (_cur - _ep) * _qty
            _unr_pct = (_cur / _ep - 1) * 100 if _ep > 0 else 0
            _tid  = int(_row["id"])
            _today_pnl = (_cur - _prv) * _qty

            # Status
            if _tp and _cur >= _tp:     _st_badge, _st_bdr = "🎯 TARGET HIT", "#26a69a"
            elif _sl and _cur <= _sl:   _st_badge, _st_bdr = "🚨 STOP BREACHED", "#ef5350"
            elif _unr >= 0:             _st_badge, _st_bdr = "🟢 In Profit", "#26a69a"
            else:                       _st_badge, _st_bdr = "🔴 In Loss", "#ef5350"

            _unr_c = "#26a69a" if _unr >= 0 else "#ef5350"
            _td_c  = "#26a69a" if _today_pnl >= 0 else "#ef5350"

            # Progress bar: SL → current → target
            _rng = max(_tp - _sl, 0.01)
            _ep_pct  = min(100, max(0, (_ep  - _sl) / _rng * 100))
            _cur_pct = min(100, max(0, (_cur - _sl) / _rng * 100))
            _bar_c   = "#26a69a" if _cur >= _ep else "#ef5350"
            # Width of colored fill = distance from entry to current
            _fill_left  = min(_ep_pct, _cur_pct)
            _fill_width = abs(_cur_pct - _ep_pct)

            _reason_txt = str(_row.get("reason") or "")

            _pt_card = st.container()
            with _pt_card:
                st.markdown(
                    f'<div style="background:#0d1f3c;border-left:5px solid {_st_bdr};'
                    f'border-radius:10px;padding:13px 16px;margin-bottom:6px">'
                    # Row 1: name + status + P&L numbers
                    f'<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">'
                    f'<div>'
                    f'<span style="font-size:17px;font-weight:700;color:#fff">{_tk.replace(".NS","")}</span>'
                    f'&nbsp;<span style="font-size:11px;color:{_st_bdr};font-weight:600">{_st_badge}</span>'
                    f'<span style="font-size:11px;color:#888;margin-left:8px">{_qty} shares</span>'
                    f'</div>'
                    f'<div style="text-align:right">'
                    f'<div style="font-size:17px;font-weight:700;color:{_unr_c}">₹{_unr:+,.0f} ({_unr_pct:+.1f}%)</div>'
                    f'<div style="font-size:11px;color:{_td_c}">Today ₹{_today_pnl:+,.0f}</div>'
                    f'</div></div>'
                    # Row 2: Entry → Current bar
                    f'<div style="margin-bottom:6px">'
                    f'<div style="display:flex;justify-content:space-between;font-size:10px;color:#666;margin-bottom:3px">'
                    f'<span style="min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;padding:0 2px">SL ₹{_sl:,.2f}</span>'
                    f'<span style="min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;padding:0 2px">Entry ₹{_ep:,.2f}</span>'
                    f'<span style="min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;padding:0 2px">Now ₹{_cur:,.2f}</span>'
                    f'<span style="min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;padding:0 2px">Target ₹{_tp:,.2f}</span>'
                    f'</div>'
                    f'<div style="width:100%;height:8px;background:#2a3a4c;border-radius:4px;position:relative;overflow:visible">'
                    # Entry marker
                    f'<div style="position:absolute;left:{_ep_pct:.0f}%;top:-3px;width:2px;height:14px;background:#888;border-radius:1px"></div>'
                    # Fill from entry to current
                    f'<div style="position:absolute;left:{_fill_left:.0f}%;width:{_fill_width:.0f}%;height:100%;background:{_bar_c};border-radius:4px;opacity:0.7"></div>'
                    # Current dot
                    f'<div style="position:absolute;left:{_cur_pct:.0f}%;top:-4px;transform:translateX(-50%);width:16px;height:16px;background:{_bar_c};border-radius:50%;border:2px solid #fff"></div>'
                    f'</div></div>'
                    + (f'<div style="font-size:11px;color:#888;margin-top:4px">📝 {_reason_txt[:80]}</div>' if _reason_txt else '')
                    + '</div>',
                    unsafe_allow_html=True,
                )
                # Action buttons inline (Fix 5: align the row's items to the top)
                st.markdown('<div style="align-items:flex-start">', unsafe_allow_html=True)
                _cb1, _cb2, _cb3, _cb4 = st.columns([2, 2, 2, 1])
                if _cb1.button(f"❌ Close @ ₹{_cur:,.2f}", key=f"cl_live_{_tid}", use_container_width=True):
                    paper_close_trade(_tid, _cur, "Closed at live price")
                    st.cache_data.clear(); st.rerun()
                if _cb2.button(f"🔴 Close @ SL ₹{_sl:,.2f}", key=f"cl_sl_{_tid}", use_container_width=True):
                    paper_close_trade(_tid, _sl, "Stop-loss triggered")
                    st.cache_data.clear(); st.rerun()
                if _cb3.button(f"🎯 Close @ Target ₹{_tp:,.2f}", key=f"cl_tp_{_tid}", use_container_width=True):
                    paper_close_trade(_tid, _tp, "Target reached")
                    st.cache_data.clear(); st.rerun()
                with _cb4.expander("✏️ Edit"):
                    _ne1, _ne2 = st.columns(2)
                    _nsl = _ne1.number_input("New SL", value=float(_sl), format="%.2f", key=f"esl_{_tid}")
                    _ntp = _ne2.number_input("New TP", value=float(_tp), format="%.2f", key=f"etp_{_tid}")
                    if st.button("Save", key=f"esv_{_tid}"):
                        paper_edit_trade(_tid, sl=_nsl, tp=_ntp)
                        st.cache_data.clear(); st.rerun()
                st.markdown('</div>', unsafe_allow_html=True)   # Fix 5: close button-row wrapper

        st.markdown("---")

    # ── CLOSED TRADE HISTORY ───────────────────────────────────────────
    if not all_closed.empty:
        st.subheader("📋 Closed Trade History")
        _cl_disp = all_closed[
            [c for c in ["id","ticker","price","quantity","sl","tp","exit_price",
                          "exit_reason","pnl","pnl_pct","status","timestamp"]
             if c in all_closed.columns]
        ].copy()
        if "pnl" in _cl_disp.columns:
            _cl_disp["pnl"] = pd.to_numeric(_cl_disp["pnl"], errors="coerce")

        # Colored HTML table for closed trades
        _CTH = "background:#1a2744;padding:7px 11px;font-size:11px;color:#aaa;font-weight:600;border-bottom:2px solid #2a3a5c;text-align:right;white-space:nowrap"
        _CTL = _CTH.replace("text-align:right", "text-align:left")
        _CTD = "padding:7px 11px;font-size:12px;border-bottom:1px solid #1a2744;text-align:right"
        _CTX = _CTD.replace("text-align:right", "text-align:left")
        _ct_html = (
            '<table style="width:100%;border-collapse:collapse;margin-bottom:6px">'
            f'<thead><tr>'
            f'<th style="{_CTL}">Stock</th>'
            f'<th style="{_CTH}">Entry ₹</th>'
            f'<th style="{_CTH}">Qty</th>'
            f'<th style="{_CTH}">SL ₹</th>'
            f'<th style="{_CTH}">TP ₹</th>'
            f'<th style="{_CTH}">Exit ₹</th>'
            f'<th style="{_CTL}">Exit Reason</th>'
            f'<th style="{_CTH}">P&amp;L ₹</th>'
            f'<th style="{_CTH}">P&amp;L %</th>'
            f'<th style="{_CTH}">Date</th>'
            f'</tr></thead><tbody>'
        )
        for _, _cr in _cl_disp.iterrows():
            _c_pnl  = float(_cr.get("pnl", 0) or 0)
            _c_pct  = float(_cr.get("pnl_pct", 0) or 0)
            _c_col  = "#26a69a" if _c_pnl >= 0 else "#ef5350"
            _c_bg   = "rgba(38,166,154,0.06)" if _c_pnl >= 0 else "rgba(239,83,80,0.06)"
            _c_tick = str(_cr.get("ticker", "")).replace(".NS", "")
            _c_ep   = f"₹{float(_cr.get('price', 0)):,.2f}"
            _c_sl   = f"₹{float(_cr.get('sl', 0)):,.2f}" if _cr.get("sl") else "—"
            _c_tp   = f"₹{float(_cr.get('tp', 0)):,.2f}" if _cr.get("tp") else "—"
            _c_xp   = f"₹{float(_cr.get('exit_price', 0)):,.2f}" if _cr.get("exit_price") else "—"
            _c_xr   = str(_cr.get("exit_reason", "") or "")
            _c_dt   = str(_cr.get("timestamp", ""))[:10]
            _ct_html += (
                f'<tr style="background:{_c_bg}">'
                f'<td style="{_CTX}"><b>{_c_tick}</b></td>'
                f'<td style="{_CTD}">{_c_ep}</td>'
                f'<td style="{_CTD}">{int(_cr.get("quantity", 0))}</td>'
                f'<td style="{_CTD}">{_c_sl}</td>'
                f'<td style="{_CTD}">{_c_tp}</td>'
                f'<td style="{_CTD}"><b>{_c_xp}</b></td>'
                f'<td style="{_CTX}">{_c_xr}</td>'
                f'<td style="{_CTD};color:{_c_col};font-weight:700">₹{_c_pnl:+,.0f}</td>'
                f'<td style="{_CTD};color:{_c_col}">{_c_pct:+.1f}%</td>'
                f'<td style="{_CTD}">{_c_dt}</td>'
                f'</tr>'
            )
        _ct_html += '</tbody></table>'
        st.markdown(_ct_html, unsafe_allow_html=True)

        # P&L Bar Chart + Cumulative Equity Curve
        _pnl_plot = all_closed.copy()
        _pnl_plot["pnl"] = pd.to_numeric(_pnl_plot["pnl"], errors="coerce")
        _pnl_plot = _pnl_plot.dropna(subset=["pnl"])
        if not _pnl_plot.empty:
            _chart_tab1, _chart_tab2 = st.tabs(["📊 P&L per Trade", "📈 Equity Curve"])

            with _chart_tab1:
                _fig_pnl = px.bar(
                    _pnl_plot, x="ticker", y="pnl",
                    color="pnl", color_continuous_scale="RdYlGn",
                    title="Realised P&L per Closed Trade (₹)",
                    labels={"pnl": "P&L (₹)", "ticker": "Stock"},
                )
                _fig_pnl.update_layout(template="nse_pro", height=320,
                                       margin=dict(l=0, r=0, t=40, b=0))
                st.plotly_chart(_fig_pnl, width="stretch")

            with _chart_tab2:
                # Cumulative P&L over sequential trades
                _eq_df = _pnl_plot.reset_index(drop=True)
                _eq_df["trade_no"]   = range(1, len(_eq_df) + 1)
                _eq_df["cumulative"] = _eq_df["pnl"].cumsum()
                _eq_colors = [
                    "#26a69a" if v >= 0 else "#ef5350"
                    for v in _eq_df["cumulative"]
                ]
                _fig_eq = go.Figure()
                _fig_eq.add_trace(go.Scatter(
                    x=_eq_df["trade_no"], y=_eq_df["cumulative"],
                    mode="lines+markers",
                    line=dict(color="#2196F3", width=2.5),
                    marker=dict(color=_eq_colors, size=8, line=dict(width=1, color="#fff")),
                    fill="tozeroy",
                    fillcolor="rgba(33,150,243,0.08)",
                    name="Cumulative P&L",
                    customdata=_eq_df[["ticker", "pnl"]].values,
                    hovertemplate=(
                        "Trade #%{x} — %{customdata[0]}<br>"
                        "This trade: ₹%{customdata[1]:,.0f}<br>"
                        "Cumulative: ₹%{y:,.0f}<extra></extra>"
                    ),
                ))
                _fig_eq.add_hline(y=0, line_dash="dot", line_color="rgba(150,150,150,0.5)")
                _final_pnl = float(_eq_df["cumulative"].iloc[-1])
                _fig_eq.update_layout(
                    template="nse_pro", height=320,
                    title=f"Equity Curve — Total P&L ₹{_final_pnl:+,.0f} "
                          f"over {len(_eq_df)} trades",
                    xaxis_title="Trade Number",
                    yaxis_title="Cumulative P&L (₹)",
                    margin=dict(l=0, r=0, t=44, b=0),
                )
                st.plotly_chart(_fig_eq, width="stretch")

        # ── Closed Trade Insights (always visible, not behind expander) ────
        st.markdown("#### 📊 Trading Insights")
        _pnl_ins = pd.to_numeric(all_closed.get("pnl", pd.Series()), errors="coerce").dropna()
        _n_ins   = len(_pnl_ins)
        if _n_ins >= 2:
            _wins_ins  = _pnl_ins[_pnl_ins > 0]
            _loss_ins  = _pnl_ins[_pnl_ins < 0]
            _wr_ins    = len(_wins_ins) / _n_ins * 100
            _aw_ins    = float(_wins_ins.mean()) if not _wins_ins.empty else 0
            _al_ins    = float(_loss_ins.mean()) if not _loss_ins.empty else 0
            _pay_ins   = abs(_aw_ins / _al_ins) if _al_ins != 0 else 0
            _exp_ins   = (_wr_ins/100 * _aw_ins) + ((1-_wr_ins/100) * _al_ins)
            _wr_c   = "#26a69a" if _wr_ins >= 50 else "#ef5350"
            _exp_c  = "#26a69a" if _exp_ins >= 0 else "#ef5350"
            _pay_c  = "#26a69a" if _pay_ins >= 1.5 else "#FFC107" if _pay_ins >= 1.0 else "#ef5350"
            st.markdown(
                f'<div style="display:flex;gap:12px;margin-bottom:12px;flex-wrap:wrap">'
                f'<div style="flex:1;min-width:120px;background:#0d1f3c;border-radius:8px;padding:12px 14px;border-top:3px solid {_wr_c}">'
                f'<div style="font-size:10px;color:#888;text-transform:uppercase">Win Rate</div>'
                f'<div style="font-size:22px;font-weight:700;color:{_wr_c}">{_wr_ins:.0f}%</div>'
                f'<div style="font-size:11px;color:#888">{len(_wins_ins)}/{_n_ins} trades</div></div>'
                f'<div style="flex:1;min-width:120px;background:#0d1f3c;border-radius:8px;padding:12px 14px;border-top:3px solid {_pay_c}">'
                f'<div style="font-size:10px;color:#888;text-transform:uppercase">Payoff Ratio</div>'
                f'<div style="font-size:22px;font-weight:700;color:{_pay_c}">{_pay_ins:.2f}:1</div>'
                f'<div style="font-size:11px;color:#888">avg win / avg loss</div></div>'
                f'<div style="flex:1;min-width:140px;background:#0d1f3c;border-radius:8px;padding:12px 14px;border-top:3px solid {_exp_c}">'
                f'<div style="font-size:10px;color:#888;text-transform:uppercase">Expectancy</div>'
                f'<div style="font-size:22px;font-weight:700;color:{_exp_c}">₹{_exp_ins:,.0f}</div>'
                f'<div style="font-size:11px;color:#888">avg ₹ per trade</div></div>'
                f'<div style="flex:1;min-width:120px;background:#0d1f3c;border-radius:8px;padding:12px 14px;border-top:3px solid #2196F3">'
                f'<div style="font-size:10px;color:#888;text-transform:uppercase">Avg Win</div>'
                f'<div style="font-size:22px;font-weight:700;color:#26a69a">₹{_aw_ins:,.0f}</div>'
                f'<div style="font-size:11px;color:#888">avg loss ₹{abs(_al_ins):,.0f}</div></div>'
                f'</div>',
                unsafe_allow_html=True,
            )
            # What setup types worked?
            if "reason" in all_closed.columns:
                _cl_copy = all_closed.copy()
                _cl_copy["pnl"] = pd.to_numeric(_cl_copy["pnl"], errors="coerce")
                _cl_copy["win"] = _cl_copy["pnl"] > 0
                # Truncate reason to setup label (first 30 chars)
                _cl_copy["setup"] = _cl_copy["reason"].fillna("Manual").str[:35]
                _setup_g = _cl_copy.groupby("setup").agg(
                    trades=("pnl","count"), total_pnl=("pnl","sum"),
                    win_rate=("win","mean")
                ).round(0).sort_values("total_pnl", ascending=False).head(5)
                if len(_setup_g) > 1:
                    st.caption("**Top setups by total P&L:**")
                    for _sn, _sr in _setup_g.iterrows():
                        _s_c = "#26a69a" if _sr["total_pnl"] >= 0 else "#ef5350"
                        st.markdown(
                            f'<div style="display:flex;justify-content:space-between;'
                            f'padding:4px 0;border-bottom:1px solid #1a2744;font-size:12px">'
                            f'<span style="color:#ccc">{_sn}</span>'
                            f'<span><span style="color:{_s_c};font-weight:700">₹{_sr["total_pnl"]:+,.0f}</span>'
                            f'&nbsp;<span style="color:#888">{int(_sr["trades"])} trades · {_sr["win_rate"]*100:.0f}% WR</span></span>'
                            f'</div>',
                            unsafe_allow_html=True,
                        )
        else:
            st.caption("Close at least 2 trades to see performance insights.")

        # ── Performance Stats ──────────────────────────────────────────
        with st.expander("📈 Detailed Statistics", expanded=False):
            _pnl_s = pd.to_numeric(all_closed["pnl"], errors="coerce").dropna()
            _n     = len(_pnl_s)
            _wins  = _pnl_s[_pnl_s > 0]
            _loss  = _pnl_s[_pnl_s < 0]
            _wr    = len(_wins) / _n * 100 if _n else 0
            _aw    = float(_wins.mean()) if not _wins.empty else 0.0
            _al    = float(_loss.mean()) if not _loss.empty else 0.0
            _pay   = abs(_aw / _al) if _al != 0 else 0
            _exp   = (_wr/100 * _aw) + ((1-_wr/100) * _al) if _n else 0

            _st1, _st2, _st3, _st4, _st5 = st.columns(5)
            _st1.metric("Win Rate",      f"{_wr:.1f}%",
                        "Good (>50%)" if _wr > 50 else "Needs work")
            _st2.metric("Avg Win",       f"₹{_aw:,.0f}")
            _st3.metric("Avg Loss",      f"₹{_al:,.0f}")
            _st4.metric("Payoff Ratio",  f"{_pay:.2f}:1",
                        "Good (>1.5)" if _pay > 1.5 else "Needs work")
            _st5.metric("Expectancy",    f"₹{_exp:,.0f}/trade",
                        "Positive edge ✓" if _exp > 0 else "Negative edge ✗",
                        delta_color="normal" if _exp >= 0 else "inverse")

            st.markdown("---")
            st.markdown(
                "**What these numbers mean:**  \n"
                "- **Win Rate**: % of trades that closed profitably. Aim for >45%.  \n"
                "- **Payoff Ratio**: Avg profit on winners ÷ avg loss on losers. Aim for >1.5  \n"
                "- **Expectancy**: Average ₹ earned per trade across all trades. Must be positive for a viable strategy."
            )

    # ── CSV export ─────────────────────────────────────────────────────
    st.markdown("---")
    if not trades.empty:
        _export_bytes = trades.to_csv(index=False).encode()
        _safe_acc = st.session_state.get("pt_account", "MyAccount").replace(" ", "_")
        st.download_button(
            f"📥 Download Trade Journal — {st.session_state.get('pt_account','My Account')} (CSV)",
            data=_export_bytes,
            file_name=f"paper_trades_{_safe_acc}.csv",
            mime="text/csv",
        )


# ═══════════════════════════════════════════════════════════════════════════════
# PAGE 6 — BACKTEST
# ═══════════════════════════════════════════════════════════════════════════════
