"""My Watchlist view, rendered by dashboard/pages/08_watchlist_journal.py via render().

Moved out of its own page on 2026-11-09 (page simplification); the body is
unchanged apart from being wrapped in render() and st.stop() becoming return.

My Watchlist - NSE Smart Investor (multipage page; body verbatim from app.py)."""


def render() -> None:
    """Render the My Watchlist view (body moved verbatim from its old page)."""
    import os
    import sys
    import logging

    _log = logging.getLogger("dashboard.my_watchlist")
    _ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if _ROOT not in sys.path:
        sys.path.insert(0, _ROOT)
    import streamlit as st
    # P3: explicit imports (was a dynamic shared-namespace injection)
    import os
    import pandas as pd
    import sys
    from dashboard.shared.cache import (
        get_composite_score,
    )
    from dashboard.shared.trade_utils import (
        _display_label,   # Phase 2 UI honesty — was missing on this page
    )
    from dashboard.shared.ui_components import empty_state, ticker_hover_wrap  # F5, UX2
    from dashboard.shared.disclosures import (
        render_score_methodology as _wl_score_methodology,
    )
    from dashboard.shared.chart_helpers import (
        _ROOT,
    )


    # ───────────────────────── page body (de-indented from app.py) ─────────────────────────
    st.markdown('<h1 class="page-title-serif">My <em>Watchlist</em></h1>', unsafe_allow_html=True)

    st.markdown("Save stocks you're tracking. Scores and prices update automatically.")

    # One list with the sidebar: st.session_state["watchlist"] (persisted to KV "watchlist" by
    # nav._persist_user_state). Load it here too in case the sidebar has not run yet.
    if "watchlist" not in st.session_state:
        try:
            import trade_store as _wl_ts
            st.session_state["watchlist"] = list(_wl_ts.kv_get("watchlist", None) or [])
        except Exception:
            st.session_state["watchlist"] = []
    _wl_list = st.session_state["watchlist"]
    merge_into(_wl_list)
    st.caption("The same list as the sidebar's 👀 My Watchlist; notes, target and stop are optional.")

    # Add to watchlist form
    # FIX WL2 — none of these four fields cleared after a successful add.
    # st.rerun() alone doesn't reset session_state: the widgets are keyed
    # ("wl_new_tkr" etc.), so on the next run Streamlit re-displays whatever's
    # already in session_state[key] rather than an empty default. Directly
    # clearing session_state for these keys inside the button's own block
    # would raise "cannot be modified after the widget ... is instantiated"
    # since the widgets have already rendered earlier in this same run. Fixed
    # with the same deferred-flag pattern used in dashboard/shared/nav.py's
    # Add-ticker box and dashboard/pages/05_analyze_stock.py's search boxes:
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
            _new_target = st.number_input("Target ₹", 0.0, 1000000.0, 0.0, key="wl_target", format="%.1f") or None
        with _wl_f4:
            _new_sl = st.number_input("Stop ₹", 0.0, 1000000.0, 0.0, key="wl_sl", format="%.1f",
                                      help="For your reference in the table; no alert is sent on it.") or None
        if st.button("⭐ Add", key="wl_page_add_btn") and _new_tkr:
            from dashboard.shared.cache import _validate_ticker
            _clean, _err = _validate_ticker(_new_tkr)
            _sym = _clean + ".NS"
            if _err:
                st.error(_err)
            elif add_row(_wl_list, _sym, _new_notes, _new_target, _new_sl):
                st.success(f"Added {_sym} to watchlist!")
                st.session_state["_wl_page_add_clear_pending"] = True
                st.rerun()
            else:
                st.warning(f"The watchlist is full ({WL_MAX} stocks); remove one first.")

    # Display watchlist with live scores
    _wl_data = load_rows(_wl_list)
    if _wl_data.empty:
        # F5 empty-state kit -- soft neutral panel reads as "empty by design"
        # rather than the blue "info" tone st.info carries.
        st.markdown(
            empty_state(
                title="Your watchlist is empty",
                hint="Use the form above to add tickers you want to track. "
                     "Live scores and prices will update automatically once you do.",
                icon="⭐",
            ),
            unsafe_allow_html=True,
        )
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
        if _refresh_btn:          # the button was never read, so it refreshed nothing
            _wl_scores.clear()
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
                "Target ₹":     f"₹{row['target_price']:.1f}" if pd.notna(row["target_price"]) and row["target_price"] else "—",
                "Stop ₹":       f"₹{row['alert_sl']:.1f}" if pd.notna(row["alert_sl"]) and row["alert_sl"] else "—",
                "Notes":        row["notes"] or "",
                "Added":        str(row["added_at"])[:10],
            })

        # UX2 · hover-preview strip — st.dataframe cells can't host HTML hover,
        # so the watchlist symbols are echoed as a compact chip row above the
        # table. Uses the score rows already loaded above (no extra fetch).
        _wl_hover_bits = []
        for _tkr in _tickers_tuple:
            _sc = _score_map.get(_tkr, {})
            _wl_hover_bits.append(ticker_hover_wrap(
                str(_tkr).replace(".NS", ""),
                price=_sc.get("price") or None,
                chg_pct=_sc.get("change_1d"),
                score=_sc.get("score"),
            ))
        if _wl_hover_bits:
            st.markdown(
                '<div style="display:flex;flex-wrap:wrap;gap:6px 14px;font-weight:600;'
                'font-size:13px;margin:4px 0 8px">'
                '<span style="color:var(--faint);font-weight:400">Hover for preview:</span>'
                + "".join(_wl_hover_bits) + '</div>',
                unsafe_allow_html=True,
            )

        _wl_display_df = pd.DataFrame(_merged)
        st.dataframe(_wl_display_df, hide_index=True, width="stretch", height=420)
        # DT1 + DT2 · watchlist scores are computed via a 15-min piggyback
        # scan (see commit 5594fd1); surface the cadence + source here.
        try:
            from dashboard.shared.ui_components import data_as_of as _wl_asof
            from utils.snapshot_time import ist_now as _ist_now_
            _wl_when = _ist_now_().strftime("%H:%M IST")
            st.markdown(
                _wl_asof(_wl_when, source="yfinance",
                         ttl_hint="piggyback scan 15 min"),
                unsafe_allow_html=True,
            )
        except Exception:
            pass

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
                remove_row(_wl_list, _rm_tkr)
                st.success(f"Removed {_rm_tkr}")
                st.rerun()


    # ═══════════════════════════════════════════════════════════════════════════════
    # PAGE 11 — INVESTOR GUIDE (SOP)
    # ═══════════════════════════════════════════════════════════════════════════════


# ── storage ───────────────────────────────────────────────────────────────────────────────
# FIX WL-STORE (audit 2026-11): this list lived in a raw sqlite3 file
# (dashboard/paper_trades.db) that trade_store never sees, so on Streamlit Cloud every
# entry, target and stop vanished on each reboot / redeploy even with Postgres set up.
# It now lives in trade_store KV (Postgres when DATABASE_URL is set); rows left in the
# old file are imported once.
import os as _os  # noqa: E402

WL_KV_KEY = "my_watchlist_rows"
_COLS = ["ticker", "notes", "added_at", "target_price", "alert_sl"]


_LEGACY_DB = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), "paper_trades.db")


def _legacy_rows() -> list:
    import os
    import sqlite3
    path = _LEGACY_DB
    if not os.path.exists(path):
        return []
    try:
        with sqlite3.connect(path) as con:
            cur = con.execute("SELECT ticker, notes, added_at, target_price, alert_sl FROM watchlist")
            return [dict(zip(_COLS, r)) for r in cur.fetchall()]
    except Exception:
        return []


def _rows() -> list:
    import trade_store as store
    rows = store.kv_get(WL_KV_KEY, None)
    if rows is None:                          # first run on this store: bring over the old file
        rows = _legacy_rows()
        if rows:
            store.kv_set(WL_KV_KEY, rows)
    return [r for r in (rows or []) if isinstance(r, dict) and r.get("ticker")]


# FIX ONE-WATCHLIST (owner, 17 Nov): the sidebar list (KV "watchlist", the list every page adds
# to through st.session_state["watchlist"]) and this page were two separate lists. There is now
# one list: the sidebar's. This page shows exactly those stocks; notes / target / stop are
# optional details per stock kept in WL_KV_KEY. Stocks that were only on this page are merged
# into the list, and removing a stock anywhere removes its details too.
WL_MAX = 30                     # list size cap (the sidebar used to stop at 12)


def details() -> dict:
    """{ticker: {"notes", "added_at", "target_price", "alert_sl"}} for stocks with details."""
    return {r["ticker"].upper(): r for r in _rows()}


def merge_into(wl: list) -> list:
    """Add stocks that only had details here to the shared list ``wl`` (in place)."""
    for t in sorted(details(), key=lambda k: str(details()[k].get("added_at") or "")):
        if t not in wl and len(wl) < WL_MAX:
            wl.append(t)
    return wl


def load_rows(wl: list):
    """One row per stock in the shared list, newest first, with any saved details."""
    import pandas as pd
    det = details()
    rows = [{**{"notes": "", "added_at": "", "target_price": None, "alert_sl": None},
             **det.get(t.upper(), {}), "ticker": t.upper()} for t in reversed(list(wl))]
    return pd.DataFrame(rows, columns=_COLS)


def add_row(wl: list, ticker: str, notes: str = "", target: float = None, sl: float = None) -> bool:
    """Add to the shared list (in place) and save the details. False when the list is full."""
    import trade_store as store
    from utils.snapshot_time import ist_now
    t = ticker.upper()
    if t not in wl:
        if len(wl) >= WL_MAX:
            return False
        wl.append(t)
    rows = [r for r in _rows() if r["ticker"].upper() != t]
    rows.append({"ticker": t, "notes": notes or "", "added_at": ist_now().strftime("%Y-%m-%d %H:%M:%S"),
                 "target_price": target, "alert_sl": sl})
    return bool(store.kv_set(WL_KV_KEY, rows))


def remove_row(wl: list, ticker: str) -> bool:
    """Remove from the shared list (in place) and drop its details."""
    import trade_store as store
    t = ticker.upper()
    if t in wl:
        wl.remove(t)
    rows = [r for r in _rows() if r["ticker"].upper() != t]
    return bool(store.kv_set(WL_KV_KEY, rows))
