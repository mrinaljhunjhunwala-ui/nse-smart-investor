"""My Watchlist - NSE Smart Investor (multipage page; body verbatim from app.py)."""
import os, sys
import logging

_log = logging.getLogger("dashboard.my_watchlist")
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
from dashboard.shared.cache import (
    get_composite_score,
)
from dashboard.shared.trade_utils import (
    _display_label,   # Phase 2 UI honesty — was missing on this page
)
from dashboard.shared.disclosures import (
    render_score_methodology as _wl_score_methodology,
)
from dashboard.shared.chart_helpers import (
    _ROOT,
    render_top_bar,
)

apply_design()
render_sidebar(current="My Watchlist")
render_top_bar()

# ───────────────────────── page body (de-indented from app.py) ─────────────────────────
st.title("⭐ My Watchlist")
st.markdown("Save stocks you're tracking. Scores and prices update automatically.")

# SQLite-backed watchlist (same DB as paper trades)
import sqlite3 as _sql
_WL_DB = os.path.join(_ROOT, "dashboard", "paper_trades.db")

def _wl_init():
    with _sql.connect(_WL_DB) as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS watchlist (
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker   TEXT NOT NULL UNIQUE,
                notes    TEXT DEFAULT '',
                added_at TEXT DEFAULT (datetime('now','localtime')),
                target_price REAL DEFAULT NULL,
                alert_sl     REAL DEFAULT NULL
            )
        """)
    return _sql.connect(_WL_DB)

_wl_con = _wl_init()

def _wl_add(ticker: str, notes: str = "", target: float = None, sl: float = None):
    try:
        _wl_con.execute(
            "INSERT OR IGNORE INTO watchlist(ticker, notes, target_price, alert_sl) VALUES(?,?,?,?)",
            (ticker.upper(), notes, target, sl)
        )
        _wl_con.commit()
        return True
    except Exception as e:
        _log.warning("watchlist DB write failed for %s: %s", ticker, e)
        return False

def _wl_remove(ticker: str):
    _wl_con.execute("DELETE FROM watchlist WHERE ticker=?", (ticker.upper(),))
    _wl_con.commit()

def _wl_get_all():
    return pd.read_sql("SELECT * FROM watchlist ORDER BY added_at DESC", _wl_con)

# Add to watchlist form
# FIX WL2 — none of these four fields cleared after a successful add.
# st.rerun() alone doesn't reset session_state: the widgets are keyed
# ("wl_new_tkr" etc.), so on the next run Streamlit re-displays whatever's
# already in session_state[key] rather than an empty default. Directly
# clearing session_state for these keys inside the button's own block
# would raise "cannot be modified after the widget ... is instantiated"
# since the widgets have already rendered earlier in this same run. Fixed
# with the same deferred-flag pattern used in dashboard/shared/nav.py's
# Add-ticker box and dashboard/pages/04_analyze_stock.py's search boxes:
# set a flag before the existing st.rerun(), consume it up here before any
# of the four widgets are instantiated on the next run.
if st.session_state.pop("_wl_page_add_clear_pending", False):
    st.session_state["wl_new_tkr"] = ""
    st.session_state["wl_new_notes"] = ""
    st.session_state["wl_target"] = 0.0
    st.session_state["wl_sl"] = 0.0

with st.expander("➕ Add Stock to Watchlist", expanded=False):
    _wl_f1, _wl_f2, _wl_f3, _wl_f4 = st.columns([2, 2, 1, 1])
    with _wl_f1:
        _new_tkr = st.text_input("Ticker (e.g. INFY)", key="wl_new_tkr").strip().upper()
    with _wl_f2:
        _new_notes = st.text_input("Notes (optional)", key="wl_new_notes")
    with _wl_f3:
        _new_target = st.number_input("Target ₹", 0.0, 100000.0, 0.0, key="wl_target", format="%.1f") or None
    with _wl_f4:
        _new_sl = st.number_input("Alert SL ₹", 0.0, 100000.0, 0.0, key="wl_sl", format="%.1f") or None
    if st.button("⭐ Add", key="wl_page_add_btn") and _new_tkr:
        _sym = _new_tkr if _new_tkr.endswith(".NS") else _new_tkr + ".NS"
        if _wl_add(_sym, _new_notes, _new_target, _new_sl):
            st.success(f"Added {_sym} to watchlist!")
            st.session_state["_wl_page_add_clear_pending"] = True
            st.rerun()

# Display watchlist with live scores
_wl_data = _wl_get_all()
if _wl_data.empty:
    st.info("Your watchlist is empty. Add stocks using the form above.")
else:
    _refresh_btn = st.button("🔄 Refresh Scores", key="wl_refresh")
    _wl_score_methodology()  # Phase 2 UI honesty — was missing on this page

    @st.cache_data(ttl=600, show_spinner=False)
    def _wl_scores(tickers_tuple):
        """
        Score every watchlist ticker via cache.get_composite_score.

        FIX WL-ATTRS — this used to read cs.composite_score / cs.current_price /
        cs.overall_signal, none of which exist on the current CompositeScore
        dataclass (the real names are cs.score, cs.price, cs.action). Every
        row was silently falling into the except block and showing "Error" —
        the entire watchlist has been broken since the dataclass was renamed.
        Now uses the actual attribute names and derives change_1d directly
        (CompositeScore already exposes .return_1d per FIX WL1).

        FIX WL-FV — attach a FinalVerdict per row (short horizon by default
        since a watchlist card is a "should I do something this week?" view).
        The verdict column is what a user actually scans for.
        """
        from dashboard.shared.pick_freshness import compose_finalverdict_for_card
        rows = []
        for tkr in tickers_tuple:
            try:
                cs = get_composite_score(tkr)
                # Build the dict shape compose_finalverdict_for_card expects
                _pick_shape = {
                    "score":   float(getattr(cs, "score", 0) or 0),
                    "action":  getattr(cs, "action", "HOLD"),
                    "horizon": getattr(cs, "horizon", ""),
                }
                _fv = compose_finalverdict_for_card(_pick_shape, tqs=None)
                rows.append({
                    "ticker":       tkr,
                    "price":        float(getattr(cs, "price", 0) or 0),
                    "score":        float(getattr(cs, "score", 0) or 0),
                    "action":       getattr(cs, "action", "HOLD"),
                    "rsi":          round(float(getattr(cs, "rsi", 50) or 50), 1),
                    "change_1d":    round(float(getattr(cs, "return_1d", 0) or 0), 2),
                    "verdict":      _fv.verdict,
                    "conviction":   _fv.conviction,
                    "horizon_used": _fv.horizon,
                })
            except Exception as e:
                _log.debug("watchlist scoring failed for %s: %s", tkr, e)
                rows.append({"ticker": tkr, "price": None, "score": None,
                             "action": "Error", "rsi": None, "change_1d": None,
                             "verdict": "—", "conviction": None,
                             "horizon_used": ""})
        return rows

    _tickers_tuple = tuple(_wl_data["ticker"].tolist())
    with st.spinner("Loading scores…"):
        _score_rows = _wl_scores(_tickers_tuple)

    _score_map = {r["ticker"]: r for r in _score_rows}

    # Merge with watchlist data
    _merged = []
    for _, row in _wl_data.iterrows():
        tkr = row["ticker"]
        sc  = _score_map.get(tkr, {})
        _merged.append({
            "Ticker":       tkr.replace(".NS",""),
            "Verdict":      sc.get("verdict", "—"),           # FIX WL-FV
            "Conviction":   sc.get("conviction") if sc.get("conviction") is not None else "—",
            "Price ₹":      f"₹{sc.get('price',0):,.2f}" if sc.get("price") else "—",
            "1d %":         f"{sc.get('change_1d',0):+.2f}%" if sc.get("change_1d") is not None else "—",
            "Score":        f"{sc.get('score',0):.0f}" if sc.get("score") is not None else "—",
            "Action":       _display_label(sc.get("action", "—")),
            "RSI":          sc.get("rsi","—"),
            "Target ₹":     f"₹{row['target_price']:.1f}" if row["target_price"] else "—",
            "Alert SL ₹":   f"₹{row['alert_sl']:.1f}"   if row["alert_sl"]     else "—",
            "Notes":        row["notes"] or "",
            "Added":        str(row["added_at"])[:10],
        })

    _wl_display_df = pd.DataFrame(_merged)
    st.dataframe(_wl_display_df, hide_index=True, width="stretch", height=420)

    # Remove ticker
    st.markdown("---")
    _rm_col1, _rm_col2 = st.columns([3, 1])
    with _rm_col1:
        _rm_tkr = st.selectbox("Remove from watchlist", ["— select —"] + _wl_data["ticker"].tolist(),
                               key="wl_remove_sel")
    with _rm_col2:
        st.write("")
        st.write("")
        if st.button("🗑️ Remove", key="wl_remove_btn") and _rm_tkr != "— select —":
            _wl_remove(_rm_tkr)
            st.success(f"Removed {_rm_tkr}")
            st.rerun()


# ═══════════════════════════════════════════════════════════════════════════════
# PAGE 11 — INVESTOR GUIDE (SOP)
# ═══════════════════════════════════════════════════════════════════════════════
