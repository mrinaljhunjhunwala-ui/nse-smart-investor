"""dashboard/shared/trade_utils.py - paper-trade DB helpers + position sizing."""
from __future__ import annotations
import os, sys, sqlite3, warnings, io, json, math, datetime
import logging
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
import plotly.io as pio
from plotly.subplots import make_subplots
from typing import Optional
import streamlit as st
_log = logging.getLogger("dashboard.trade_utils")
warnings.filterwarnings('ignore')
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
import trade_store as _store


def load_trades_db(path: str = "trades.db") -> pd.DataFrame:
    if not os.path.exists(path):
        return pd.DataFrame()
    with sqlite3.connect(path) as conn:
        try:
            return pd.read_sql_query("SELECT * FROM trades ORDER BY id DESC", conn)
        except Exception as _e:
            _log.warning("trade_utils.%s degraded: %s", "load_trades_db", _e)
            return pd.DataFrame()


def load_trades_by_account(account: str, path: str = "trades.db") -> pd.DataFrame:
    """Load trades filtered to a specific paper trading account."""
    return _store.load_by_account(account)


def _ensure_paper_db(path: str = "trades.db"):
    """Ensure the trades schema exists on the active backend."""
    _store.ensure_schema()


def paper_list_accounts(path: str = "trades.db") -> list:
    """Return sorted distinct account names.

    Unions accounts that already have trades with any account that was *created*
    but is still empty (registered in the kv store). Without this, a freshly
    created account vanished on the next rerun — list_accounts() only sees
    accounts that appear in the trades table — so the user could never select it
    to open its first trade. Now an empty account is selectable immediately.
    """
    names = set()
    try:
        names.update(_store.list_accounts())
    except Exception as _e:
        _log.warning("trade_utils.paper_list_accounts (trades) degraded: %s", _e)
    try:
        names.update(_store.kv_get("paper_accounts", []) or [])
    except Exception as _e:
        _log.debug("trade_utils.paper_list_accounts (registry) degraded: %s", _e)
    names.add("My Account")
    return sorted(names)


def _register_paper_account(name: str) -> None:
    """Add an account name to the kv registry so empty accounts survive reruns."""
    try:
        reg = set(_store.kv_get("paper_accounts", []) or [])
        if name not in reg:
            reg.add(name)
            _store.kv_set("paper_accounts", sorted(reg))
    except Exception as _e:
        _log.debug("trade_utils._register_paper_account degraded: %s", _e)


def paper_rename_account(old_name: str, new_name: str, path: str = "trades.db"):
    """Rename an account across all its trades and in the kv registry."""
    _store.rename_account(old_name, new_name)
    try:
        reg = set(_store.kv_get("paper_accounts", []) or [])
        reg.discard(old_name)
        reg.add(new_name)
        _store.kv_set("paper_accounts", sorted(reg))
        _store.kv_set(f"acct_type:{new_name}", paper_account_type(old_name))
    except Exception as _e:
        _log.debug("trade_utils.paper_rename_account registry degraded: %s", _e)


def paper_delete_account(name: str, path: str = "trades.db"):
    """Delete all trades in an account and drop it from the kv registry."""
    _store.delete_account(name)
    try:
        reg = set(_store.kv_get("paper_accounts", []) or [])
        reg.discard(name)
        _store.kv_set("paper_accounts", sorted(reg))
    except Exception as _e:
        _log.debug("trade_utils.paper_delete_account registry degraded: %s", _e)


def paper_open_trade(ticker: str, price: float, qty: int,
                     sl: float, tp: float, reason: str = "",
                     account: str = "My Account",
                     path: str = "trades.db") -> int:
    """Insert a new paper BUY trade. Returns new row id."""
    return _store.open_trade(ticker, price, qty, sl, tp, reason=reason, account=account)


def paper_close_trade(trade_id: int, exit_price: float,
                      reason: str = "Manual close", path: str = "trades.db"):
    """Close an open paper trade by ID."""
    _store.close_trade(trade_id, exit_price, reason=reason)


def paper_edit_trade(trade_id: int, sl: float = None, tp: float = None,
                     reason: str = None, path: str = "trades.db"):
    """Edit stop-loss, target, or reason of an open trade."""
    _store.edit_trade(trade_id, sl=sl, tp=tp, reason=reason)


# ── Account product type (CNC = delivery, MIS = intraday) ─────────────────────
def paper_account_type(name: str) -> str:
    """Return 'MIS' (intraday) or 'CNC' (delivery) for an account; default CNC."""
    try:
        return _store.kv_get(f"acct_type:{name}", "CNC") or "CNC"
    except Exception as _e:
        _log.debug("trade_utils.%s degraded: %s", "paper_account_type", _e)
        return "CNC"


def set_paper_account_type(name: str, atype: str) -> None:
    try:
        _store.kv_set(f"acct_type:{name}", "MIS" if str(atype).upper().startswith("MIS")
                      or "INTRA" in str(atype).upper() else "CNC")
        _register_paper_account(name)
    except Exception as _e:
        _log.debug("trade_utils.%s degraded: %s", "set_paper_account_type", _e)
        pass


@st.cache_data(ttl=60, show_spinner=False)
def _portfolio_live_prices(tickers: tuple) -> dict:
    """
    Live prices for portfolio holdings via Yahoo Finance JSON API (cloud-safe).
    Falls back to Stooq EOD if Yahoo is unavailable.
    """
    from utils.live_price import get_live_prices_batch
    raw = get_live_prices_batch(list(tickers))
    results = {}
    for t in tickers:
        q = raw.get(t)
        if isinstance(q, dict) and q.get("price"):
            results[t] = {
                "price": q["price"],
                "prev":  q["prev_close"],
                "chg":   q["chg_pct"],
            }
    return results


def _action_color(action: str) -> str:
    if action in ("STRONG BUY", "BUY"):
        return "card-green"
    elif action in ("WATCHLIST", "HOLD"):
        return "card-yellow"
    else:
        return "card-red"


def _action_emoji(action: str) -> str:
    return {
        "STRONG BUY": "🚀", "BUY": "🟢", "WATCHLIST": "👀",
        "HOLD": "🟡", "CAUTION": "⚠️", "EXIT": "🔴",
    }.get(action, "")


def _grade_color(grade: str) -> str:
    return {"A+": "#26a69a", "A": "#4CAF50", "B": "#8BC34A",
            "C": "#FFC107", "D": "#FF5722", "F": "#f44336"}.get(grade, "#9E9E9E")


# ─────────────────────────────────────────────────────────────────────────────
# Position sizing — risk-based qty suggestion
# ─────────────────────────────────────────────────────────────────────────────

def _suggest_position(entry: float, sl: float,
                      capital: float = None,
                      risk_pct: float = None,
                      max_alloc_pct: float = 20.0) -> dict:
    """
    Suggest share quantity for a trade using fixed-fractional risk sizing.
    Sizes so that (entry - sl) × qty ≈ risk_pct% of capital, then caps the
    position at max_alloc_pct% of capital so a single name can't dominate.
    """
    if capital is None:
        capital = float(st.session_state.get("trade_capital", 500_000.0))
    if risk_pct is None:
        risk_pct = float(st.session_state.get("risk_pct", 1.0))
    entry = float(entry or 0)
    sl    = float(sl or 0)
    if entry <= 0:
        return {"qty": 1, "price": entry, "risk_per_share": 0,
                "capital_at_risk": 0, "position_value": entry, "basis": "fallback"}

    risk_amount = capital * (risk_pct / 100.0)
    rps = abs(entry - sl)
    if rps > 0.01:
        qty_risk = int(risk_amount / rps)
        basis = f"{risk_pct:.0f}% risk (₹{risk_amount:,.0f}) ÷ ₹{rps:.2f}/share"
    else:
        qty_risk = int(risk_amount / entry)
        basis = "notional (no valid stop)"

    qty_cap = int((capital * max_alloc_pct / 100.0) / entry)
    qty = max(1, min(qty_risk, qty_cap))
    if qty == qty_cap < qty_risk:
        basis += f" · capped at {max_alloc_pct:.0f}% allocation"

    return {
        "qty":             qty,
        "price":           round(entry, 2),
        "risk_per_share":  round(rps, 2),
        "capital_at_risk": round(rps * qty, 0),
        "position_value":  round(entry * qty, 0),
        "basis":           basis,
    }


def _live_quote_price(ticker: str) -> Optional[float]:
    """Best-effort live LTP for a ticker (Angel One → Yahoo). None if unavailable."""
    try:
        from utils.live_price import get_live_quote
        q = get_live_quote(ticker)
        if isinstance(q, dict) and q.get("price"):
            return float(q["price"])
    except Exception as _e:
        _log.debug("trade_utils._live_quote_price degraded: %s", _e)
    return None


def _paper_trade_popover(ticker: str, entry: float, sl: float, tp: float,
                         reason: str, key: str, label: str = "📌 Paper Trade") -> None:
    """
    Open-a-paper-trade popover that enters at the live market price by default.
    Preserves analysis SL/TP distances so R:R stays identical under re-anchoring.

    FIX: Account selector is now rendered INSIDE the popover so the user can
    choose which paper account to book the trade into. Previously the popover
    always silently fell back to session_state["pt_account"] (usually "My Account")
    with no way to change it mid-flow.
    """
    _tlbl = ticker.replace(".NS", "")
    _cap  = float(st.session_state.get("trade_capital", 500_000.0))
    _rkp  = float(st.session_state.get("risk_pct", 1.0))

    _analysis_entry = float(entry or 0)
    _sl_dist = (_analysis_entry - float(sl)) if (sl and _analysis_entry) else None
    _tp_dist = (float(tp) - _analysis_entry) if (tp and _analysis_entry) else None

    with st.popover(label, use_container_width=True):
        st.markdown(f"**{_tlbl}** — open paper trade")

        # ── PATCH 1: Account selector ─────────────────────────────────────
        # Render a selectbox so the user picks the destination account.
        # Previously this was read silently from session_state and never shown,
        # meaning the trade always landed in "My Account" regardless of intent.
        _acct_list = paper_list_accounts()
        _default_acct = st.session_state.get("pt_account", "My Account")
        _default_idx  = (_acct_list.index(_default_acct)
                         if _default_acct in _acct_list else 0)
        _selected_acct = st.selectbox(
            "Account",
            options=_acct_list,
            index=_default_idx,
            key=f"{key}_acct",
            help="Choose which paper trading account to book this trade into.",
        )
        _acct_type = paper_account_type(_selected_acct)
        _acct_type_label = ("⏱ Intraday (MIS) — auto squared off at 15:15"
                            if _acct_type == "MIS"
                            else "📦 Delivery (CNC) — held until you close manually")
        st.caption(f"Account type: **{_acct_type_label}** · Change in Paper Trades → Accounts.")
        # ── END PATCH 1 ──────────────────────────────────────────────────

        _live = _live_quote_price(ticker)
        _default_entry = _live if (_live and _live > 0) else _analysis_entry

        if _live and _analysis_entry and abs(_live - _analysis_entry) / _analysis_entry > 0.002:
            _drift = (_live / _analysis_entry - 1) * 100
            st.caption(
                f"🔴 **Live ₹{_live:,.2f}** vs analysis ₹{_analysis_entry:,.2f} "
                f"({_drift:+.2f}%). Entry defaults to live; SL/TP re-anchored to keep "
                f"the same risk/reward."
            )
        elif _live:
            st.caption(f"🟢 Entering at **live ₹{_live:,.2f}** (matches analysis).")
        else:
            st.caption("⚠️ Live price unavailable — using the analysis entry. "
                       "Verify before trusting the fill.")

        entry_use = st.number_input(
            "Entry price (₹) — defaults to LIVE, editable for a limit",
            min_value=0.01, value=round(float(_default_entry or 0.01), 2),
            step=0.05, format="%.2f", key=f"{key}_entry",
        )
        sl_use = round(entry_use - _sl_dist, 2) if _sl_dist is not None else (float(sl) if sl else 0.0)
        tp_use = round(entry_use + _tp_dist, 2) if _tp_dist is not None else (float(tp) if tp else 0.0)

        sugg = _suggest_position(entry_use, sl_use)
        st.caption(
            f"💡 Suggested **{sugg['qty']} shares** — sizes your loss-to-stop to "
            f"≈{_rkp:.2g}% of ₹{_cap:,.0f} (₹{sugg['capital_at_risk']:,.0f} at risk). "
            f"Change capital & risk in the sidebar; adjust qty below."
        )
        qty = st.number_input(
            "Quantity (shares)", min_value=1, max_value=1_000_000,
            value=int(sugg["qty"]), step=1, key=f"{key}_qty",
        )
        _val  = qty * entry_use
        _risk = abs(entry_use - (sl_use or entry_use)) * qty
        _c1, _c2, _c3 = st.columns(3)
        _c1.metric("Entry",    f"₹{entry_use:,.2f}")
        _c2.metric("Position", f"₹{_val:,.0f}")
        _c3.metric("At Risk",  f"₹{_risk:,.0f}")
        if sl_use or tp_use:
            _rr = ((tp_use - entry_use) / (entry_use - sl_use)
                   if (entry_use - sl_use) > 0.01 and tp_use else 0)
            st.caption(f"🛑 SL ₹{(sl_use or 0):,.2f}  ·  🎯 Target ₹{(tp_use or 0):,.2f}"
                       + (f"  ·  R:R {_rr:.1f}x" if _rr else ""))
        if st.button("✅ Confirm & Open", key=f"{key}_confirm",
                     type="primary", use_container_width=True):
            _id = paper_open_trade(
                ticker, float(entry_use), int(qty), sl=sl_use, tp=tp_use, reason=reason,
                # PATCH 1: use _selected_acct from the selectbox above, not session_state
                account=_selected_acct,
            )
            st.toast(f"📌 Opened #{_id}: {int(qty)} × {_tlbl} @ ₹{entry_use:,.2f} "
                     f"in '{_selected_acct}'", icon="✅")
            st.cache_data.clear()
            st.rerun()


# ─────────────────────────────────────────────────────────────────────────────
# Market hours helpers
# ─────────────────────────────────────────────────────────────────────────────

def _is_market_open() -> bool:
    """True if NSE is currently in a live session (9:15–15:30 IST, Mon–Fri)."""
    try:
        from utils.market_hours import market_status as _msx
        return bool(_msx().get("is_open", False))
    except Exception:
        pass
    # Fallback: manual IST check so a missing/broken module never blocks auto-close
    import datetime as _dt
    ist = _dt.datetime.now(_dt.timezone(_dt.timedelta(hours=5, minutes=30)))
    if ist.weekday() >= 5:          # Saturday / Sunday
        return False
    mins = ist.hour * 60 + ist.minute
    return 555 <= mins <= 930       # 9:15 AM – 15:30 PM


def _is_squareoff_time() -> bool:
    """True from 15:15 IST onward on weekdays — MIS intraday square-off window."""
    import datetime as _dt
    ist = _dt.datetime.now(_dt.timezone(_dt.timedelta(hours=5, minutes=30)))
    if ist.weekday() >= 5:
        return False
    mins = ist.hour * 60 + ist.minute
    return mins >= 915              # 15:15 PM


# ─────────────────────────────────────────────────────────────────────────────
# Auto-close logic
# ─────────────────────────────────────────────────────────────────────────────

def _auto_close_breached(account: str = None, path: str = "trades.db") -> list:
    """
    Auto-close OPEN paper trades whose live price has crossed SL or TP.

    Rules:
    • CNC (delivery) accounts — SL/TP breach only, during live market hours.
      Prices outside hours are stale EOD; closing on them would be wrong.
    • MIS (intraday) accounts — SL/TP breach during market hours, AND
      force-close ALL remaining open MIS positions at 15:15 (square-off),
      mirroring what brokers do with intraday positions.

    Returns list of dicts describing what was closed.
    Caller should rerun if the list is non-empty.
    """
    closed  = []
    _open   = _is_market_open()
    _sqoff  = _is_squareoff_time()

    # Nothing to do outside market hours for any account type
    if not _open and not _sqoff:
        return closed

    try:
        rows = _store.fetch_open(account)
        if rows.empty:
            return closed

        syms = tuple(rows["ticker"].tolist())
        lp   = _portfolio_live_prices(syms)

        for _, r in rows.iterrows():
            tk        = str(r["ticker"])
            ep        = float(r.get("price",    0) or 0)
            qty       = int(  r.get("quantity", 0) or 0)
            sl        = float(r.get("sl",       0) or 0) or None
            tp        = float(r.get("tp",       0) or 0) or None
            trade_id  = int(r["id"])
            acct      = str(r.get("account", account or "My Account"))
            acct_type = paper_account_type(acct)   # "MIS" or "CNC"
            cur       = lp.get(tk, {}).get("price")

            # ── MIS square-off: force-close at live price (or entry fallback) ──
            if acct_type == "MIS" and _sqoff:
                exit_px = cur if (cur and cur > 0) else ep
                paper_close_trade(trade_id, exit_px,
                                  "Auto square-off: MIS position closed at 15:15")
                closed.append({
                    "ticker":  tk.replace(".NS", ""),
                    "type":    "squareoff",
                    "exit":    exit_px,
                    "pnl":     (exit_px - ep) * qty,
                    "account": acct,
                })
                continue   # skip the SL/TP check — already closed

            # ── SL / TP breach — only during live hours with a valid price ──
            if not _open or cur is None or ep <= 0:
                continue

            hit      = None
            exit_px  = None
            why      = ""
            if tp and cur >= tp:
                hit, exit_px, why = "target", tp,  "Auto-closed: target reached"
            elif sl and cur <= sl:
                hit, exit_px, why = "stop",   sl,  "Auto-closed: stop-loss hit"

            if hit:
                paper_close_trade(trade_id, exit_px, why)
                closed.append({
                    "ticker":  tk.replace(".NS", ""),
                    "type":    hit,
                    "exit":    exit_px,
                    "pnl":     (exit_px - ep) * qty,
                    "account": acct,
                })

    except Exception as _e:
        _log.warning("trade_utils._auto_close_breached error: %s", _e)

    return closed


def _render_autoclose_banner(closed: list) -> None:
    """Show a prominent banner listing trades that were just auto-closed."""
    if not closed:
        return

    _TYPE_LABEL = {
        "target":    "target reached",
        "stop":      "stop-loss hit",
        "squareoff": "MIS square-off @ 15:15",
    }
    _TYPE_ICON = {
        "target":    "🎯",
        "stop":      "🛑",
        "squareoff": "⏰",
    }

    _rows = ""
    for c in closed:
        _ic  = _TYPE_ICON.get(c["type"], "🔔")
        _lbl = _TYPE_LABEL.get(c["type"], c["type"])
        _col = "#26a69a" if c["pnl"] >= 0 else "#ef5350"
        _rows += (
            f'<div style="display:flex;justify-content:space-between;'
            f'padding:5px 0;border-bottom:1px solid rgba(255,255,255,.06);font-size:13px">'
            f'<span style="color:#eee">{_ic} <b>{c["ticker"]}</b> '
            f'<span style="color:#888">({c["account"]})</span> — '
            f'{_lbl} @ ₹{c["exit"]:,.2f}</span>'
            f'<span style="color:{_col};font-weight:700">₹{c["pnl"]:+,.0f}</span></div>'
        )

    st.markdown(
        f'<div style="background:linear-gradient(135deg,#1a1200,#2d1f00);'
        f'border:1px solid #FFC107;border-radius:12px;padding:14px 18px;margin-bottom:14px">'
        f'<div style="font-size:14px;font-weight:700;color:#FFC107;margin-bottom:6px">'
        f'🔔 {len(closed)} position{"s" if len(closed)!=1 else ""} auto-closed</div>'
        f'{_rows}</div>',
        unsafe_allow_html=True,
    )
