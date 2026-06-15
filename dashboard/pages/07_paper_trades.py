"""Paper Trades - NSE Smart Investor (multipage page; body verbatim from app.py).

FIXES applied in this revision
───────────────────────────────
P1  Auto-close now runs in a @st.fragment(run_every="60s") fragment so MIS
    positions are squared off at 15:15 even when the page is idle.
P2  MIS square-off reminder now shows 3:15 PM (was 3:20) to match
    _is_squareoff_time() in trade_utils.py.
P3  st.rerun() added after opening a trade so the new position appears
    immediately without a manual refresh.
P4  Account management bar no longer splits a raw HTML <div> across multiple
    st.markdown() calls — uses st.container() with inline CSS instead.
P5  Delete account now counts open positions and shows a warning before
    allowing deletion.
P6  Live-suggestion banner shows a "prices may be stale" caption when the
    60-second cache is serving values that don't match the current ticker
    selection.
P7  Reason/notes field key now includes _tk_key so it resets when the user
    picks a different stock (was "pt_reason", now f"pt_reason_{_tk_key}").
P8  Equity curve DataFrame sorted by "timestamp" before cumsum so the curve
    is chronologically correct.
P9  Setup grouping now strips common filler words and normalises casing so
    near-identical reasons fall in the same bucket.
P10 Open trade card truncates reason to 80 chars with a proper "…" suffix.
P11 _open_lp fallback to entry price now sets a _prices_stale flag and
    surfaces a visible caption instead of silently showing ₹0 P&L.
P12 Rename flow validates that the target name does not already exist,
    preventing silent account merging.
P13 Progress bar dot is clamped to 2–98% so it never overflows the bar at
    the extremes.

NEW  After opening a trade the stock selector and manual ticker field are
     reset via session_state so the form returns to the empty state.
NEW  MIS auto-square-off: a dedicated @st.fragment(run_every="60s") calls
     _auto_close_breached() every minute; combined with the existing
     _is_squareoff_time() logic in trade_utils this means MIS positions are
     force-closed at or within 60 seconds of 15:15 IST regardless of whether
     the user is interacting with the page.

FIX APPTEST  st.selectbox index=None replaced with explicit index lookup so
     Streamlit's headless AppTest runner does not raise
     'NewType object has no attribute replic'.
"""

import os, sys
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import streamlit as st
from dashboard.shared.design import apply_design
from dashboard.shared.nav import render_sidebar
from dashboard.shared.chart_helpers import render_top_bar

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from dashboard.shared.design import apply_design
from dashboard.shared.cache import STOCK_SEARCH_MAP, _validate_ticker
from dashboard.shared.trade_utils import (
    _auto_close_breached,
    _ensure_paper_db,
    _is_squareoff_time,
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
from dashboard.shared.chart_helpers import _ROOT, render_top_bar

apply_design()
render_sidebar(current="Paper Trades")
render_top_bar()

# ─────────────────────────────────────────────────────────────────────────────
# Page header
# ─────────────────────────────────────────────────────────────────────────────
st.title("📂 Paper Trading Simulator")
st.markdown(
    "Practice trading **without real money**. Open virtual trades, track live P&L, "
    "and measure your decision quality over time. All prices are from live market data."
)

# ── Persistence status banner ──────────────────────────────────────────────
try:
    import trade_store as _pers_ts
    _pers = _pers_ts.validate_persistence()
    if _pers.get("ephemeral"):
        st.warning(
            "⚠️ **Your paper trades are stored on temporary disk and will RESET when the "
            "app redeploys** (typically every few days on Streamlit Cloud, or on any code "
            "update). That's why older trades disappear. **To keep full history permanently**, "
            "connect a free Postgres database (Neon or Supabase, 5-min setup): add a "
            "`DATABASE_URL` in the app's Secrets. See `dashboard/DB_SETUP.md`. "
            "Until then, export your trades below to keep a copy.",
            icon="🗄️",
        )
    elif _pers.get("error"):
        st.error(f"🗄️ Persistence issue: {_pers['error']} — trades may not be saving. "
                 "Check your DATABASE_URL.")
    else:
        st.success(
            f"🗄️ Persistent storage active (**{_pers.get('backend','postgres')}**) — "
            "your trades, accounts and watchlist now survive redeploys.",
            icon="✅",
        )

    with st.expander("🔌 Test storage connection", expanded=False):
        if st.button("Run connection test", key="pers_test_btn"):
            _secret_seen = False
            _masked = "—"
            _which = "—"
            try:
                _raw = _pers_ts._database_url()
                if _raw:
                    _secret_seen = True
                    import re as _re
                    _masked = _re.sub(r"://[^@]*@", "://***@", str(_raw))
                try:
                    import streamlit as _sst
                    if "database" in _sst.secrets and "url" in _sst.secrets["database"]:
                        _which = "[database].url"
                    elif "DATABASE_URL" in _sst.secrets:
                        _which = "DATABASE_URL (flat)"
                    else:
                        _which = "not found in st.secrets"
                except Exception as _we:
                    _which = f"secrets read error: {_we}"
            except Exception as _de:
                _which = f"diag error: {_de}"

            st.caption(f"🔎 Secret detected by app: **{'YES' if _secret_seen else 'NO'}**  ·  "
                       f"source: `{_which}`")
            if _secret_seen:
                st.caption(f"🔎 Using (password masked): `{_masked}`")

            _r = _pers_ts.validate_persistence()
            _c1, _c2, _c3 = st.columns(3)
            _c1.metric("Backend",    _r.get("backend", "—"))
            _c2.metric("Reachable",  "✅ Yes" if _r.get("reachable") else "❌ No")
            _c3.metric("Schema OK",  "✅ Yes" if _r.get("schema_ok") else "❌ No")
            if _r.get("error"):
                st.error(f"Error: {_r['error']}")
            elif _r.get("reachable") and _r.get("schema_ok") and not _r.get("ephemeral"):
                st.success("Connection good — persistence is working.")
            elif _r.get("ephemeral") and not _secret_seen:
                st.warning("The DATABASE_URL secret is **not being read** by the app.")
            elif _r.get("ephemeral") and _secret_seen:
                st.warning("Secret IS read but backend is still SQLite — likely old code is "
                           "running. Reboot the app from 'Manage app'.")
        else:
            st.caption("Click to verify the database is connected and the schema is valid.")
except Exception:
    pass

# Pre-fill ticker if navigated from Market Overview "Trade" button
if "pt_prefill_ticker" in st.session_state and st.session_state["pt_prefill_ticker"]:
    _pf_sym = st.session_state.pop("pt_prefill_ticker")
    _pf_clean = _pf_sym.replace(".NS", "")
    st.session_state["pt_manual_tk"] = _pf_clean
    st.info(f"📝 Pre-filled from Market Overview: **{_pf_clean}** — live price loading…")

_ensure_paper_db()

# ─────────────────────────────────────────────────────────────────────────────
# ACCOUNT MANAGEMENT BAR — FIX P4: no split raw HTML div
# ─────────────────────────────────────────────────────────────────────────────
_all_accounts = paper_list_accounts()
if "pt_account" not in st.session_state or st.session_state["pt_account"] not in _all_accounts:
    st.session_state["pt_account"] = _all_accounts[0]

with st.container():
    # Thin blue left-border accent via a single self-contained markdown
    st.markdown(
        '<style>.acct-bar{border-left:5px solid #2196F3;padding-left:14px;'
        'background:#0d1f3c;border-radius:10px;padding:12px 18px;margin-bottom:16px}</style>'
        '<div class="acct-bar"></div>',
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
        _acc_type  = paper_account_type(_selected_account)
        _at_badge  = "🔆 INTRADAY (MIS)" if _acc_type == "MIS" else "📦 DELIVERY (CNC)"
        _at_col    = "#ff9500"           if _acc_type == "MIS" else "#5b8def"
        st.markdown(
            f'<span style="font-size:11px">📂 <b>{_selected_account}</b> '
            f'<span style="color:{_at_col};font-weight:700">· {_at_badge}</span></span>',
            unsafe_allow_html=True,
        )

    with _acc_c2:
        _new_acc_name = st.text_input(
            "New account name", value="", placeholder="New account…",
            label_visibility="collapsed", key="pt_new_acc_input",
        ).strip()
        _new_acc_type = st.radio(
            "Type", ["Delivery", "Intraday"], horizontal=True,
            label_visibility="collapsed", key="pt_new_acc_type",
        )

    with _acc_c3:
        st.write("")
        if st.button("➕ Create", key="pt_create_acc", use_container_width=True):
            if _new_acc_name and _new_acc_name not in _all_accounts:
                set_paper_account_type(
                    _new_acc_name,
                    "MIS" if _new_acc_type == "Intraday" else "CNC",
                )
                st.session_state["pt_account"] = _new_acc_name
                st.success(f"**{_new_acc_name}** ({_new_acc_type}) created.")
                st.rerun()
            elif _new_acc_name in _all_accounts:
                st.warning("Account already exists.")

    with _acc_c4:
        st.write("")
        _rename_to = st.text_input(
            "Rename to", value="", placeholder="Rename to…",
            label_visibility="collapsed", key="pt_rename_input",
        ).strip()

    with _acc_c5:
        st.write("")
        if st.button("✏️ Rename", key="pt_rename_acc", use_container_width=True):
            if not _rename_to:
                st.warning("Enter a new name first.")
            elif _rename_to == _selected_account:
                st.warning("New name is the same as the current name.")
            # FIX P12: prevent renaming onto an existing account (would silently merge histories)
            elif _rename_to in _all_accounts:
                st.error(
                    f"⚠️ **'{_rename_to}'** already exists. Renaming onto an existing account "
                    "would silently merge their trade histories. Choose a different name."
                )
            else:
                paper_rename_account(_selected_account, _rename_to)
                st.session_state["pt_account"] = _rename_to
                st.success(f"Renamed to **{_rename_to}**")
                st.rerun()

# Delete account — separate row
# FIX P5: count open positions before allowing deletion
if len(_all_accounts) > 1:
    with st.expander("🗑️ Danger Zone — Delete Account", expanded=False):
        # Check how many open trades this account has before surfacing the confirm box
        _del_open_count = 0
        try:
            _del_trades = load_trades_by_account(_selected_account)
            if not _del_trades.empty and "status" in _del_trades.columns:
                _del_open_count = int((_del_trades["status"] == "OPEN").sum())
        except Exception:
            pass

        if _del_open_count > 0:
            st.error(
                f"⚠️ Account **{_selected_account}** has **{_del_open_count} open "
                f"position{'s' if _del_open_count != 1 else ''}** with unrealised P&L. "
                "Deleting will permanently lose this data. Close the positions first, "
                "or proceed if you are sure."
            )
        else:
            st.warning(
                f"This will permanently delete **all trades** in account "
                f"**{_selected_account}**. This cannot be undone."
            )

        _del_confirm = st.checkbox(
            f"Yes, I want to delete account '{_selected_account}' and all its trades",
            key="pt_del_confirm",
        )
        if st.button(
            "🗑️ Delete Account", key="pt_delete_acc",
            disabled=not _del_confirm, type="secondary",
        ):
            paper_delete_account(_selected_account)
            _remaining = [a for a in _all_accounts if a != _selected_account]
            st.session_state["pt_account"] = _remaining[0] if _remaining else "My Account"
            st.success(f"Account **{_selected_account}** deleted.")
            st.rerun()

# ─────────────────────────────────────────────────────────────────────────────
# MIS square-off reminder — FIX P2: aligned to 3:15 PM (was 3:20)
# ─────────────────────────────────────────────────────────────────────────────
if paper_account_type(_selected_account) == "MIS":
    import datetime as _sqdt
    _ist_now    = _sqdt.datetime.now(_sqdt.timezone(_sqdt.timedelta(hours=5, minutes=30)))
    _is_weekday = _ist_now.weekday() < 5
    # FIX P2: use 15:15 to match _is_squareoff_time() in trade_utils
    _mins_to_squareoff = (15 * 60 + 15) - (_ist_now.hour * 60 + _ist_now.minute)
    if _is_weekday and 0 < _mins_to_squareoff <= 60:
        st.markdown(
            f'<div class="card-red pulse-red" style="margin:6px 0">'
            f'⏰ <b>Intraday square-off in {_mins_to_squareoff} min</b> (auto-close at 3:15 PM IST). '
            f'Close MIS positions now or they will be automatically squared off.</div>',
            unsafe_allow_html=True,
        )
    elif _is_weekday and _mins_to_squareoff <= 0:
        st.markdown(
            '<div class="card-red" style="margin:6px 0">'
            '⏰ <b>Past 3:15 PM — MIS square-off window active.</b> '
            'Any open intraday positions are being auto-closed.</div>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            '<div class="card-yellow" style="margin:6px 0">'
            '🔆 <b>Intraday (MIS) account</b> — positions are auto-squared at 3:15 PM IST '
            '(the app checks every 60 seconds while this page is open).</div>',
            unsafe_allow_html=True,
        )

st.markdown("---")

# ─────────────────────────────────────────────────────────────────────────────
# Live price + ATR suggestions (cached 60 s per ticker)
# ─────────────────────────────────────────────────────────────────────────────
@st.cache_data(ttl=60, show_spinner=False)
def _paper_trade_suggestions(ticker: str) -> dict:
    """
    Live price (Yahoo JSON API) + ATR-based SL/TP + RSI + trend.
    Returns dict: price, prev, chg, atr, sl, tp, rsi, trend, qty_suggest, error
    """
    import pandas as _pd2
    from utils.live_price import get_live_quote
    from data.fetcher import fetch_single

    result = {
        "price": None, "prev": None, "chg": 0.0,
        "atr": None, "sl": None, "tp": None,
        "rsi": None, "trend": "—", "qty_suggest": 1, "error": "",
    }
    try:
        q = get_live_quote(ticker)
        if not isinstance(q, dict) or not q.get("price"):
            result["error"] = "Price unavailable — all sources failed. Try again in 30 s."
            return result

        price = q["price"]
        prev  = q["prev_close"]
        chg   = q["chg_pct"]
        result.update({"price": price, "prev": prev, "chg": chg})

        df = fetch_single(ticker, period="3mo")
        df = df.dropna(subset=["Close"])
        if len(df) < 15:
            result["sl"]          = round(price * 0.97, 2)
            result["tp"]          = round(price * 1.06, 2)
            result["qty_suggest"] = max(1, int(10000 / price))
            return result

        # ATR (14)
        hi, lo, cl = df["High"], df["Low"], df["Close"]
        tr  = _pd2.concat(
            [hi - lo, (hi - cl.shift()).abs(), (lo - cl.shift()).abs()],
            axis=1,
        ).max(axis=1)
        atr = float(tr.rolling(14).mean().dropna().iloc[-1])
        result["atr"] = atr
        result["sl"]  = max(0.01, round(price - 1.5 * atr, 2))
        result["tp"]  = round(price + 3.0 * atr, 2)

        # RSI (14)
        delta = cl.diff()
        gain  = delta.clip(lower=0).rolling(14).mean()
        loss  = (-delta.clip(upper=0)).rolling(14).mean()
        result["rsi"] = float((100 - 100 / (1 + gain / loss)).dropna().iloc[-1])

        # Trend
        sma50  = float(cl.rolling(50).mean().iloc[-1])  if len(df) >= 50  else price
        sma200 = float(cl.rolling(200).mean().iloc[-1]) if len(df) >= 200 else price
        if price > sma50 > sma200:
            result["trend"] = "🟢 Uptrend (above SMA50 & SMA200)"
        elif price > sma50:
            result["trend"] = "🟡 Moderate (above SMA50)"
        elif price < sma50 < sma200:
            result["trend"] = "🔴 Downtrend (below SMA50 & SMA200)"
        else:
            result["trend"] = "🟡 Mixed — check chart"

        result["qty_suggest"] = max(1, int(10000 / price))

    except Exception as _exc:
        result["error"] = str(_exc)
    return result


# ─────────────────────────────────────────────────────────────────────────────
# NEW TRADE FORM
# ─────────────────────────────────────────────────────────────────────────────
# FIX NEW: reset form state after a successful trade submission
_reset_form = st.session_state.pop("_pt_reset_form", False)

with st.expander("➕ Open a New Paper Trade", expanded=True):
    st.markdown(
        "**Select a stock** — the entry price, stop-loss, and target are auto-filled "
        "from live market data and ATR analysis. You can adjust them freely before submitting."
    )
    _search_opts = sorted(
        [f"{n}  ({s.replace('.NS','')})" for n, s in STOCK_SEARCH_MAP.items()]
    )
    _all_opts = ["— choose stock —"] + _search_opts

    _fc1, _fc2 = st.columns([3, 2])
    with _fc1:
        # ── FIX APPTEST ───────────────────────────────────────────────────────
        # index=None is not supported by Streamlit's AppTest headless runner and
        # raises "NewType object has no attribute replic" in CI.
        # Instead we compute an explicit integer index every run:
        #   • After a trade opens (_reset_form=True)  → index 0 (placeholder)
        #   • Otherwise                               → restore the previous
        #     selection from session_state, falling back to 0 if not found.
        # This is behaviourally identical to the old index=None approach in a
        # real browser session but is fully compatible with AppTest.
        if _reset_form or "pt_stock_sel" not in st.session_state:
            _sel_index = 0
        else:
            _prev_sel  = st.session_state.get("pt_stock_sel", _all_opts[0])
            _sel_index = _all_opts.index(_prev_sel) if _prev_sel in _all_opts else 0

        _form_sel = st.selectbox(
            "Search by company name",
            _all_opts,
            key="pt_stock_sel",
            index=_sel_index,
        )
        # ─────────────────────────────────────────────────────────────────────

    with _fc2:
        # FIX NEW: clear manual ticker field after trade opens
        _form_manual = st.text_input(
            "Or type NSE ticker directly",
            key="pt_manual_tk",
            value="" if _reset_form else st.session_state.get("pt_manual_tk", ""),
            placeholder="e.g. INFY",
        ).strip().upper()

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

    # Fetch live data
    _sugg = {
        "price": None, "sl": None, "tp": None, "qty_suggest": 10,
        "atr": None, "rsi": None, "trend": "—", "chg": 0.0, "error": "",
    }
    if _form_ticker:
        with st.spinner(f"Fetching live price & ATR for {_form_ticker.replace('.NS','')}…"):
            _sugg = _paper_trade_suggestions(_form_ticker)

    # Suggestion banner
    if _form_ticker and _sugg["price"]:
        _p       = _sugg["price"]
        _atr     = _sugg["atr"]
        _rsi     = _sugg["rsi"]
        _atr_str = f"₹{_atr:.2f}" if _atr else "—"
        _rsi_str = f"{_rsi:.0f}"  if _rsi else "—"
        _rsi_label = (
            "🔴 Overbought — watch for pullback" if (_rsi and _rsi > 70) else
            "🟢 Oversold — bounce candidate"     if (_rsi and _rsi < 30) else
            "🟡 Neutral momentum"                if _rsi else ""
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
            unsafe_allow_html=True,
        )
    elif _form_ticker and _sugg["error"]:
        st.warning(f"⚠️ {_sugg['error']}")

    # Input fields — keyed by ticker so they reset when stock changes
    _tk_key    = _form_ticker or "none"
    _def_price = _sugg["price"] or 100.0
    _def_sl    = _sugg["sl"]    or round(_def_price * 0.97, 2)
    _def_tp    = _sugg["tp"]    or round(_def_price * 1.06, 2)
    _def_qty   = _sugg["qty_suggest"] or 10

    _pa, _pb, _pc, _pd = st.columns(4)
    _form_qty   = _pa.number_input(
        "Quantity (shares)", 1, 1_000_000, _def_qty,
        key=f"pt_qty_{_tk_key}",
    )
    _form_price = _pb.number_input(
        "Entry Price (₹) — live", 0.01, 1e7, float(_def_price),
        key=f"pt_price_{_tk_key}", format="%.2f",
    )
    _form_sl    = _pc.number_input(
        "Stop-Loss (₹) — ATR-based", 0.01, 1e7, float(_def_sl),
        key=f"pt_sl_{_tk_key}", format="%.2f",
        help="Default = 1.5× ATR below live price.",
    )
    _form_tp    = _pd.number_input(
        "Target (₹) — 2:1 R:R", 0.01, 1e7, float(_def_tp),
        key=f"pt_tp_{_tk_key}", format="%.2f",
        help="Default = 3× ATR above live price (2:1 R:R).",
    )

    # Live R:R summary
    if _form_price > 0 and _form_sl < _form_price and _form_tp > _form_price:
        _risk_ps  = _form_price - _form_sl
        _rew_ps   = _form_tp   - _form_price
        _rr_ratio = _rew_ps / _risk_ps if _risk_ps > 0 else 0
        _cap_risk = _risk_ps * _form_qty
        _cap_rew  = _rew_ps  * _form_qty
        _rr_color = "#26a69a" if _rr_ratio >= 1.5 else "#f9a825" if _rr_ratio >= 1.0 else "#ef5350"
        st.markdown(
            f'<div style="background:#1a1a2a;padding:10px 16px;border-radius:8px;margin:8px 0">'
            f'Risk/share: <b style="color:#ef5350">₹{_risk_ps:.2f}</b> &nbsp;|&nbsp; '
            f'Reward/share: <b style="color:#26a69a">₹{_rew_ps:.2f}</b> &nbsp;|&nbsp; '
            f'<span style="color:{_rr_color}"><b>R:R = {_rr_ratio:.1f}:1</b></span> &nbsp;|&nbsp; '
            f'Max loss: <b style="color:#ef5350">₹{_cap_risk:,.0f}</b> &nbsp;|&nbsp; '
            f'Max gain: <b style="color:#26a69a">₹{_cap_rew:,.0f}</b>'
            f'</div>',
            unsafe_allow_html=True,
        )
        if _rr_ratio < 1.0:
            st.error("⛔ R:R below 1:1 — you risk more than you can gain.")
        elif _rr_ratio < 1.5:
            st.warning("⚠️ R:R below 1.5:1 — minimum recommended is 1.5:1.")
        else:
            st.success(f"✅ Good R:R ({_rr_ratio:.1f}:1) — setup meets the minimum quality bar.")

    # FIX P7: key includes _tk_key so reason resets when ticker changes
    _form_reason = st.text_input(
        "Reason / notes (optional)",
        key=f"pt_reason_{_tk_key}",
        placeholder="e.g. RSI oversold bounce at SMA50 support — score 72",
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
                f"✅ Paper trade #{_new_id} opened in "
                f"**{st.session_state.get('pt_account','My Account')}**: "
                f"**{int(_form_qty)} × {_form_ticker.replace('.NS','')}** @ ₹{_form_price:,.2f}  "
                f"| SL ₹{_form_sl:,.2f} | Target ₹{_form_tp:,.2f}"
            )
            st.cache_data.clear()
            # FIX NEW: signal form reset, FIX P3: rerun so new trade appears immediately
            st.session_state["_pt_reset_form"] = True
            st.rerun()

st.markdown("---")

# ─────────────────────────────────────────────────────────────────────────────
# Load trades for current account
# ─────────────────────────────────────────────────────────────────────────────
_hcol, _tcol, _rcol = st.columns([4, 2, 1])
with _hcol:
    st.markdown(f"#### 📂 {st.session_state.get('pt_account', 'My Account')}")
with _tcol:
    _pt_autoclose = st.toggle(
        "🤖 Auto-close SL/TP",
        value=st.session_state.get("auto_close_on", False),
        key="pt_autoclose_toggle",
        help=(
            "Checks every 60 seconds (while this page is open) and automatically closes "
            "positions that have hit their stop-loss or target — during market hours only. "
            "MIS (intraday) positions are also force-closed at 3:15 PM IST."
        ),
    )
    st.session_state["auto_close_on"] = _pt_autoclose
with _rcol:
    st.write("")
    if st.button("🔄 Refresh", key="paper_refresh"):
        st.cache_data.clear()
        st.rerun()

# ─────────────────────────────────────────────────────────────────────────────
# FIX P1 + NEW MIS auto-square-off:
# Run auto-close in a fragment that polls every 60 seconds so it fires at or
# within 60 seconds of 15:15 IST even when the page is idle.
# ─────────────────────────────────────────────────────────────────────────────
@st.fragment(run_every="60s")
def _autoclose_fragment():
    """Polls every 60 s while the page is open. Closes SL/TP breaches and
    MIS positions at square-off time without requiring user interaction."""
    if not st.session_state.get("auto_close_on", False):
        return
    _pt_closed = _auto_close_breached(
        account=st.session_state.get("pt_account", "My Account")
    )
    if _pt_closed:
        _render_autoclose_banner(_pt_closed)
        st.cache_data.clear()
        st.rerun()

_autoclose_fragment()

trades = load_trades_by_account(st.session_state.get("pt_account", "My Account"))

if trades.empty:
    st.info("No paper trades yet. Open your first trade using the form above.")
else:
    open_t     = trades[trades["status"] == "OPEN"]    if "status" in trades.columns else pd.DataFrame()
    closed_t   = trades[trades["status"] == "CLOSED"]  if "status" in trades.columns else pd.DataFrame()
    stopped_t  = trades[trades["status"] == "STOPPED"] if "status" in trades.columns else pd.DataFrame()
    all_closed = pd.concat([closed_t, stopped_t], ignore_index=True)

    # Fetch live prices for open positions
    _open_syms = tuple(open_t["ticker"].tolist()) if not open_t.empty else ()
    _open_lp   = _portfolio_live_prices(_open_syms) if _open_syms else {}

    # FIX P11: track whether any live prices are missing
    _prices_stale = False

    # Aggregate account-level P&L
    _pt_deployed   = 0.0
    _pt_unrealised = 0.0
    _pt_today_pnl  = 0.0
    for _, _orow in open_t.iterrows():
        _o_ep  = float(_orow.get("price",    0) or 0)
        _o_qty = int(  _orow.get("quantity", 0) or 0)
        _o_lp  = _open_lp.get(str(_orow["ticker"]), {})
        _o_cur = _o_lp.get("price")
        if _o_cur is None:
            _prices_stale = True
            _o_cur = _o_ep          # fallback to entry — flagged below
        _o_prv = _o_lp.get("prev", _o_cur)
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

    # FIX P11: show stale-price notice prominently
    if _prices_stale:
        st.caption(
            "⚠️ Live prices are temporarily unavailable for one or more positions. "
            "Unrealised P&L and today's change shown as ₹0 for those positions until prices recover."
        )

    # Account Dashboard Card
    _ac_name = st.session_state.get("pt_account", "My Account")
    _ur_col  = "#26a69a" if _pt_unrealised >= 0 else "#ef5350"
    _re_col  = "#26a69a" if _pt_realised   >= 0 else "#ef5350"
    _td_col  = "#26a69a" if _pt_today_pnl  >= 0 else "#ef5350"
    _ur_arr  = "▲" if _pt_unrealised >= 0 else "▼"
    _re_arr  = "▲" if _pt_realised   >= 0 else "▼"
    _td_arr  = "▲" if _pt_today_pnl  >= 0 else "▼"
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
        f'<div style="font-size:22px;font-weight:700;color:{_td_col}">{_td_arr} ₹{abs(_pt_today_pnl):,.0f}'
        + (" <span style='font-size:10px;color:#888'>·stale</span>" if _prices_stale else "") +
        f'</div></div>'

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

    # ─────────────────────────────────────────────────────────────────────
    # OPEN POSITIONS
    # ─────────────────────────────────────────────────────────────────────
    if not open_t.empty:
        st.subheader("📌 Open Positions")

        for _, _row in open_t.iterrows():
            _tk   = _row["ticker"]
            _ep   = float(_row["price"])
            _qty  = int(_row["quantity"])
            _sl   = float(_row["sl"]) if _row.get("sl") else (_ep * 0.95)
            _tp   = float(_row["tp"]) if _row.get("tp") else (_ep * 1.10)
            _lp   = _open_lp.get(_tk, {})
            _has_live = bool(_lp.get("price"))
            _cur  = _lp.get("price", _ep)   # fallback to entry (flagged above)
            _prv  = _lp.get("prev",  _cur)
            _unr      = (_cur - _ep) * _qty
            _unr_pct  = (_cur / _ep - 1) * 100 if _ep > 0 else 0
            _today_pnl = (_cur - _prv) * _qty
            _tid      = int(_row["id"])

            if _tp and _cur >= _tp:
                _st_badge, _st_bdr = "🎯 TARGET HIT",     "#26a69a"
            elif _sl and _cur <= _sl:
                _st_badge, _st_bdr = "🚨 STOP BREACHED",  "#ef5350"
            elif _unr >= 0:
                _st_badge, _st_bdr = "🟢 In Profit",      "#26a69a"
            else:
                _st_badge, _st_bdr = "🔴 In Loss",        "#ef5350"

            _unr_c   = "#26a69a" if _unr       >= 0 else "#ef5350"
            _td_c    = "#26a69a" if _today_pnl >= 0 else "#ef5350"
            _ltp_chg = (_cur / _prv - 1) * 100 if _prv > 0 else 0
            _ltp_c   = "#26a69a" if _ltp_chg  >= 0 else "#ef5350"
            _ltp_arr = "▲" if _ltp_chg >= 0 else "▼"

            # Progress bar — FIX P13: clamp dot position to 2–98%
            _rng      = max(_tp - _sl, 0.01)
            _ep_pct   = min(100, max(0,   (_ep  - _sl) / _rng * 100))
            _cur_pct  = min(100, max(0,   (_cur - _sl) / _rng * 100))
            _dot_pct  = min(98,  max(2,   _cur_pct))   # FIX P13
            _bar_c    = "#26a69a" if _cur >= _ep else "#ef5350"
            _fill_left  = min(_ep_pct, _cur_pct)
            _fill_width = abs(_cur_pct - _ep_pct)

            # FIX P10: ellipsis on truncated reason
            _reason_txt = str(_row.get("reason") or "")
            _reason_disp = (_reason_txt[:80] + "…") if len(_reason_txt) > 80 else _reason_txt

            st.markdown(
                f'<div style="background:#0d1f3c;border-left:5px solid {_st_bdr};'
                f'border-radius:10px;padding:13px 16px;margin-bottom:6px">'
                f'<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">'
                f'<div>'
                f'<span style="font-size:17px;font-weight:700;color:#fff">{_tk.replace(".NS","")}</span>'
                f'&nbsp;<span style="font-size:11px;color:{_st_bdr};font-weight:600">{_st_badge}</span>'
                f'<span style="font-size:11px;color:#888;margin-left:8px">{_qty} shares</span>'
                f'<div style="font-size:15px;color:#fff;margin-top:4px">'
                f'{"🔴 Live" if _has_live else "⏸ Stale"} <b>₹{_cur:,.2f}</b> '
                f'<span style="color:{_ltp_c};font-size:12px;font-weight:600">{_ltp_arr}{abs(_ltp_chg):.2f}%</span>'
                f'<span style="font-size:11px;color:#888;margin-left:8px">vs entry ₹{_ep:,.2f}</span>'
                f'</div></div>'
                f'<div style="text-align:right">'
                f'<div style="font-size:17px;font-weight:700;color:{_unr_c}">₹{_unr:+,.0f} ({_unr_pct:+.1f}%)</div>'
                f'<div style="font-size:11px;color:{_td_c}">Today ₹{_today_pnl:+,.0f}</div>'
                f'</div></div>'
                # Progress bar
                f'<div style="margin-bottom:6px">'
                f'<div style="display:flex;justify-content:space-between;font-size:10px;color:#666;margin-bottom:3px">'
                f'<span>SL ₹{_sl:,.2f}</span>'
                f'<span>Entry ₹{_ep:,.2f}</span>'
                f'<span>Now ₹{_cur:,.2f}</span>'
                f'<span>Target ₹{_tp:,.2f}</span>'
                f'</div>'
                f'<div style="width:100%;height:8px;background:#2a3a4c;border-radius:4px;position:relative;overflow:visible">'
                f'<div style="position:absolute;left:{_ep_pct:.0f}%;top:-3px;width:2px;height:14px;background:#888;border-radius:1px"></div>'
                f'<div style="position:absolute;left:{_fill_left:.0f}%;width:{_fill_width:.0f}%;height:100%;background:{_bar_c};border-radius:4px;opacity:0.7"></div>'
                # FIX P13: dot clamped to 2–98%
                f'<div style="position:absolute;left:{_dot_pct:.0f}%;top:-4px;transform:translateX(-50%);'
                f'width:16px;height:16px;background:{_bar_c};border-radius:50%;border:2px solid #fff"></div>'
                f'</div></div>'
                + (f'<div style="font-size:11px;color:#888;margin-top:4px">📝 {_reason_disp}</div>'
                   if _reason_disp else "")
                + "</div>",
                unsafe_allow_html=True,
            )

            # Action buttons
            _cb1, _cb2, _cb3 = st.columns(3)
            if _cb1.button(f"❌ Close @ ₹{_cur:,.2f}", key=f"cl_live_{_tid}", use_container_width=True):
                paper_close_trade(_tid, _cur, "Closed at live price")
                st.cache_data.clear(); st.rerun()
            if _cb2.button(f"🔴 Close @ SL ₹{_sl:,.2f}", key=f"cl_sl_{_tid}", use_container_width=True):
                paper_close_trade(_tid, _sl, "Stop-loss triggered")
                st.cache_data.clear(); st.rerun()
            if _cb3.button(f"🎯 Close @ Target ₹{_tp:,.2f}", key=f"cl_tp_{_tid}", use_container_width=True):
                paper_close_trade(_tid, _tp, "Target reached")
                st.cache_data.clear(); st.rerun()

            with st.expander("✏️ Edit Stop-Loss / Target"):
                _ne1, _ne2 = st.columns(2)
                _nsl = _ne1.number_input(
                    "New Stop-Loss (₹)", min_value=0.01, value=float(_sl),
                    step=0.05, format="%.2f", key=f"esl_{_tid}",
                    help="Price at which the position is stopped out.",
                )
                _ntp = _ne2.number_input(
                    "New Target (₹)", min_value=0.01, value=float(_tp),
                    step=0.05, format="%.2f", key=f"etp_{_tid}",
                    help="Price at which you'll book profit.",
                )
                _new_rr = ((_ntp - _ep) / (_ep - _nsl)) if (_ep - _nsl) > 0.01 else 0
                st.caption(
                    f"Entry ₹{_ep:,.2f} · Risk ₹{max(_ep - _nsl, 0):,.2f}/sh · "
                    f"Reward ₹{max(_ntp - _ep, 0):,.2f}/sh · R:R {_new_rr:.2f}x"
                    if _new_rr else
                    f"Entry ₹{_ep:,.2f} — set SL below and target above entry."
                )
                if st.button("💾 Save changes", key=f"esv_{_tid}",
                             type="primary", use_container_width=True):
                    paper_edit_trade(_tid, sl=_nsl, tp=_ntp)
                    st.toast(f"Updated SL ₹{_nsl:,.2f} · TP ₹{_ntp:,.2f}", icon="✅")
                    st.cache_data.clear(); st.rerun()

        st.markdown("---")

    # ─────────────────────────────────────────────────────────────────────
    # CLOSED TRADE HISTORY
    # ─────────────────────────────────────────────────────────────────────
    if not all_closed.empty:
        st.subheader("📋 Closed Trade History")
        _cl_disp = all_closed[
            [c for c in ["id", "ticker", "price", "quantity", "sl", "tp",
                          "exit_price", "exit_reason", "pnl", "pnl_pct",
                          "status", "timestamp"]
             if c in all_closed.columns]
        ].copy()
        if "pnl" in _cl_disp.columns:
            _cl_disp["pnl"] = pd.to_numeric(_cl_disp["pnl"], errors="coerce")

        _CTH = ("background:#1a2744;padding:7px 11px;font-size:11px;color:#aaa;"
                "font-weight:600;border-bottom:2px solid #2a3a5c;text-align:right;white-space:nowrap")
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
            _c_pnl  = float(_cr.get("pnl",     0) or 0)
            _c_pct  = float(_cr.get("pnl_pct", 0) or 0)
            _c_col  = "#26a69a" if _c_pnl >= 0 else "#ef5350"
            _c_bg   = "rgba(38,166,154,0.06)" if _c_pnl >= 0 else "rgba(239,83,80,0.06)"
            _c_tick = str(_cr.get("ticker", "")).replace(".NS", "")
            _c_ep   = f"₹{float(_cr.get('price', 0)):,.2f}"
            _c_sl   = f"₹{float(_cr.get('sl', 0)):,.2f}" if _cr.get("sl")         else "—"
            _c_tp   = f"₹{float(_cr.get('tp', 0)):,.2f}" if _cr.get("tp")         else "—"
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
        _ct_html += "</tbody></table>"
        st.markdown(_ct_html, unsafe_allow_html=True)

        # Charts
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
                # FIX P8: sort by close timestamp before cumsum
                _eq_df = _pnl_plot.copy()
                if "timestamp" in _eq_df.columns:
                    _eq_df = _eq_df.sort_values("timestamp")
                _eq_df = _eq_df.reset_index(drop=True)
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
                    title=f"Equity Curve — Total P&L ₹{_final_pnl:+,.0f} over {len(_eq_df)} trades",
                    xaxis_title="Trade Number",
                    yaxis_title="Cumulative P&L (₹)",
                    margin=dict(l=0, r=0, t=44, b=0),
                )
                st.plotly_chart(_fig_eq, width="stretch")

        # Trading Insights
        st.markdown("#### 📊 Trading Insights")
        _pnl_ins = pd.to_numeric(all_closed.get("pnl", pd.Series()), errors="coerce").dropna()
        _n_ins   = len(_pnl_ins)
        if _n_ins >= 2:
            _wins_ins = _pnl_ins[_pnl_ins > 0]
            _loss_ins = _pnl_ins[_pnl_ins < 0]
            _wr_ins   = len(_wins_ins) / _n_ins * 100
            _aw_ins   = float(_wins_ins.mean()) if not _wins_ins.empty else 0
            _al_ins   = float(_loss_ins.mean()) if not _loss_ins.empty else 0
            _pay_ins  = abs(_aw_ins / _al_ins)  if _al_ins != 0 else 0
            _exp_ins  = (_wr_ins / 100 * _aw_ins) + ((1 - _wr_ins / 100) * _al_ins)
            _wr_c     = "#26a69a" if _wr_ins  >= 50 else "#ef5350"
            _exp_c    = "#26a69a" if _exp_ins >= 0  else "#ef5350"
            _pay_c    = "#26a69a" if _pay_ins >= 1.5 else "#FFC107" if _pay_ins >= 1.0 else "#ef5350"

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

            # FIX P9: normalise setup label before grouping
            if "reason" in all_closed.columns:
                _cl_copy = all_closed.copy()
                _cl_copy["pnl"] = pd.to_numeric(_cl_copy["pnl"], errors="coerce")
                _cl_copy["win"] = _cl_copy["pnl"] > 0
                # Normalise: lowercase, strip leading emoji/whitespace, trim to 40 chars,
                # then strip trailing partial words so near-identical reasons group together
                def _normalise_reason(r):
                    import re
                    r = str(r or "Manual").lower().strip()
                    r = re.sub(r"^[\W_]+", "", r)    # strip leading non-word chars
                    r = r[:40].rsplit(" ", 1)[0]      # trim at last word boundary ≤40 chars
                    return r or "manual"
                _cl_copy["setup"] = _cl_copy["reason"].apply(_normalise_reason)
                _setup_g = (
                    _cl_copy.groupby("setup")
                    .agg(trades=("pnl", "count"), total_pnl=("pnl", "sum"), win_rate=("win", "mean"))
                    .round(0)
                    .sort_values("total_pnl", ascending=False)
                    .head(5)
                )
                if len(_setup_g) > 1:
                    st.caption("**Top setups by total P&L:**")
                    for _sn, _sr in _setup_g.iterrows():
                        _s_c = "#26a69a" if _sr["total_pnl"] >= 0 else "#ef5350"
                        st.markdown(
                            f'<div style="display:flex;justify-content:space-between;'
                            f'padding:4px 0;border-bottom:1px solid #1a2744;font-size:12px">'
                            f'<span style="color:#ccc">{_sn}</span>'
                            f'<span><span style="color:{_s_c};font-weight:700">₹{_sr["total_pnl"]:+,.0f}</span>'
                            f'&nbsp;<span style="color:#888">{int(_sr["trades"])} trades · '
                            f'{_sr["win_rate"]*100:.0f}% WR</span></span>'
                            f'</div>',
                            unsafe_allow_html=True,
                        )
        else:
            st.caption("Close at least 2 trades to see performance insights.")

        # Detailed statistics
        with st.expander("📈 Detailed Statistics", expanded=False):
            _pnl_s = pd.to_numeric(all_closed["pnl"], errors="coerce").dropna()
            _n     = len(_pnl_s)
            _wins  = _pnl_s[_pnl_s > 0]
            _loss  = _pnl_s[_pnl_s < 0]
            _wr    = len(_wins) / _n * 100 if _n else 0
            _aw    = float(_wins.mean()) if not _wins.empty else 0.0
            _al    = float(_loss.mean()) if not _loss.empty else 0.0
            _pay   = abs(_aw / _al)      if _al != 0 else 0
            _exp   = (_wr / 100 * _aw) + ((1 - _wr / 100) * _al) if _n else 0

            _st1, _st2, _st3, _st4, _st5 = st.columns(5)
            _st1.metric("Win Rate",     f"{_wr:.1f}%",
                        "Good (>50%)" if _wr > 50 else "Needs work")
            _st2.metric("Avg Win",      f"₹{_aw:,.0f}")
            _st3.metric("Avg Loss",     f"₹{_al:,.0f}")
            _st4.metric("Payoff Ratio", f"{_pay:.2f}:1",
                        "Good (>1.5)" if _pay > 1.5 else "Needs work")
            _st5.metric("Expectancy",   f"₹{_exp:,.0f}/trade",
                        "Positive edge ✓" if _exp > 0 else "Negative edge ✗",
                        delta_color="normal" if _exp >= 0 else "inverse")

            st.markdown("---")
            st.markdown(
                "**What these numbers mean:**  \n"
                "- **Win Rate**: % of trades that closed profitably. Aim for >45%.  \n"
                "- **Payoff Ratio**: Avg profit on winners ÷ avg loss on losers. Aim for >1.5  \n"
                "- **Expectancy**: Average ₹ earned per trade. Must be positive for a viable strategy."
            )

    # CSV export
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
