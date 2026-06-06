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


# ── Paper-trade storage — delegates to trade_store (SQLite default, Postgres
#    if DATABASE_URL/secrets configured). `path` kept for signature compat. ────
import trade_store as _store


def load_trades_by_account(account: str, path: str = "trades.db") -> pd.DataFrame:
    """Load trades filtered to a specific paper trading account."""
    return _store.load_by_account(account)


def _ensure_paper_db(path: str = "trades.db"):
    """Ensure the trades schema exists on the active backend."""
    _store.ensure_schema()


def paper_list_accounts(path: str = "trades.db") -> list:
    """Return sorted list of distinct account names."""
    return _store.list_accounts()


def paper_rename_account(old_name: str, new_name: str, path: str = "trades.db"):
    """Rename an account across all its trades."""
    _store.rename_account(old_name, new_name)


def paper_delete_account(name: str, path: str = "trades.db"):
    """Delete all trades in an account."""
    _store.delete_account(name)


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
# Position sizing — risk-based qty suggestion (used by auto-open paper trades)
# ─────────────────────────────────────────────────────────────────────────────

def _suggest_position(entry: float, sl: float,
                      capital: float = None,
                      risk_pct: float = None,
                      max_alloc_pct: float = 20.0) -> dict:
    """
    Suggest share quantity for a trade using fixed-fractional risk sizing.

    Sizes so that (entry - sl) × qty ≈ risk_pct% of capital, then caps the
    position at max_alloc_pct% of capital so a single name can't dominate.

    capital / risk_pct default to the user's settings in session_state
    (set in the sidebar), falling back to ₹5,00,000 and 1%.

    Returns: {qty, price, risk_per_share, capital_at_risk, position_value, basis}
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
        qty_risk = int(risk_amount / entry)   # no valid stop → notional sizing
        basis = "notional (no valid stop)"

    # Cap at max allocation
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


def _paper_trade_popover(ticker: str, entry: float, sl: float, tp: float,
                         reason: str, key: str, label: str = "📌 Paper Trade") -> None:
    """
    Render a popover that lets the user review & adjust quantity (pre-filled
    with the risk-based suggestion) BEFORE opening a paper trade.

    Confirmation uses st.toast so feedback survives the popover closing on rerun.
    """
    sugg  = _suggest_position(entry, sl)
    _tlbl = ticker.replace(".NS", "")
    _cap  = float(st.session_state.get("trade_capital", 500_000.0))
    _rkp  = float(st.session_state.get("risk_pct", 1.0))
    with st.popover(label, use_container_width=True):
        st.markdown(f"**{_tlbl}** — open paper trade")
        st.caption(
            f"💡 Suggested **{sugg['qty']} shares** — sizes your loss-to-stop to "
            f"≈{_rkp:.2g}% of ₹{_cap:,.0f} (₹{sugg['capital_at_risk']:,.0f} at risk). "
            f"Change capital & risk in the sidebar; adjust qty below."
        )
        qty = st.number_input(
            "Quantity (shares)", min_value=1, max_value=1_000_000,
            value=int(sugg["qty"]), step=1, key=f"{key}_qty",
        )
        _val  = qty * entry
        _risk = abs(entry - (sl or entry)) * qty
        _c1, _c2, _c3 = st.columns(3)
        _c1.metric("Entry", f"₹{entry:,.2f}")
        _c2.metric("Position", f"₹{_val:,.0f}")
        _c3.metric("At Risk", f"₹{_risk:,.0f}")
        if sl or tp:
            st.caption(f"🛑 SL ₹{(sl or 0):,.2f}  ·  🎯 Target ₹{(tp or 0):,.2f}")
        if st.button("✅ Confirm & Open", key=f"{key}_confirm",
                     type="primary", use_container_width=True):
            _id = paper_open_trade(
                ticker, float(entry), int(qty), sl=sl, tp=tp, reason=reason,
                account=st.session_state.get("pt_account", "My Account"),
            )
            st.toast(f"📌 Opened #{_id}: {int(qty)} × {_tlbl} @ ₹{entry:,.2f}", icon="✅")
            st.cache_data.clear()
            st.rerun()


def _auto_close_breached(account: str = None, path: str = "trades.db") -> list:
    """
    Auto-close any OPEN paper trade whose live price has crossed its TP or SL.
    Paper trades only — never touches real broker positions.

    Only runs during NSE market hours: outside hours the live-price feed falls
    back to EOD close, which could falsely trip a stop/target. Returns a list of
    dicts describing what was closed. Caller reruns if the list is non-empty.
    """
    closed = []
    # Guard: only auto-close on live intraday prices, never on stale EOD data
    try:
        from utils.market_hours import market_status as _msx
        if not _msx().get("is_open", False):
            return closed
    except Exception as _e:
        _log.debug("trade_utils.%s degraded: %s", "_auto_close_breached", _e)
        pass
    try:
        rows = _store.fetch_open(account)
        if rows.empty:
            return closed

        syms = tuple(rows["ticker"].tolist())
        lp   = _portfolio_live_prices(syms)

        for _, r in rows.iterrows():
            tk  = str(r["ticker"])
            ep  = float(r.get("price", 0) or 0)
            qty = int(r.get("quantity", 0) or 0)
            sl  = float(r.get("sl", 0) or 0) or None
            tp  = float(r.get("tp", 0) or 0) or None
            cur = lp.get(tk, {}).get("price")
            if cur is None or ep <= 0:
                continue

            hit = None
            if tp and cur >= tp:
                hit, exit_px, why = "target", tp, "Auto-closed: target reached"
            elif sl and cur <= sl:
                hit, exit_px, why = "stop", sl, "Auto-closed: stop-loss hit"
            if hit:
                paper_close_trade(int(r["id"]), exit_px, why, path=path)
                closed.append({
                    "ticker": tk.replace(".NS", ""), "type": hit,
                    "exit": exit_px, "pnl": (exit_px - ep) * qty,
                    "account": str(r.get("account", "My Account")),
                })
    except Exception as _e:
        _log.debug("trade_utils.%s degraded: %s", "_auto_close_breached", _e)
        pass
    return closed


def _render_autoclose_banner(closed: list) -> None:
    """Show a prominent banner listing trades that were just auto-closed."""
    if not closed:
        return
    _rows = ""
    for c in closed:
        _ic  = "🎯" if c["type"] == "target" else "🛑"
        _col = "#26a69a" if c["pnl"] >= 0 else "#ef5350"
        _rows += (
            f'<div style="display:flex;justify-content:space-between;'
            f'padding:5px 0;border-bottom:1px solid rgba(255,255,255,.06);font-size:13px">'
            f'<span style="color:#eee">{_ic} <b>{c["ticker"]}</b> '
            f'<span style="color:#888">({c["account"]})</span> — '
            f'{"target reached" if c["type"]=="target" else "stop-loss hit"} '
            f'@ ₹{c["exit"]:,.2f}</span>'
            f'<span style="color:{_col};font-weight:700">₹{c["pnl"]:+,.0f}</span></div>'
        )
    st.markdown(
        f'<div style="background:linear-gradient(135deg,#1a1200,#2d1f00);'
        f'border:1px solid #FFC107;border-radius:12px;padding:14px 18px;margin-bottom:14px">'
        f'<div style="font-size:14px;font-weight:700;color:#FFC107;margin-bottom:6px">'
        f'🔔 {len(closed)} position{"s" if len(closed)!=1 else ""} auto-closed on SL/TP</div>'
        f'{_rows}</div>',
        unsafe_allow_html=True,
    )


