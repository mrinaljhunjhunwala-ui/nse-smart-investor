"""My Portfolio - NSE Smart Investor (multipage page; body verbatim from app.py).

FIXES applied in this revision
───────────────────────────────
MH1  Removed the entire CSV-upload / sample-CSV-download / Angel-One-import
     flow. The page is now driven by manually-entered holdings (ticker, qty,
     avg buy price, date bought) persisted via load_manual_holdings() /
     save_manual_holdings() in trade_utils.py. No price/qty suggestions are
     given — the user types exactly what they hold. This also removes the
     dependency on _safe_tmpfile that was causing the missing-import error.

MH2  Portfolio Heatmap is now inside a collapsed st.expander, matching the
     Sector Breakdown treatment, instead of always rendering full-width.

MH3  The "📊 Analyze" button on each holding card sets
     st.session_state["analyze_ticker"] before navigating — paired with the
     corresponding read on the Analyze Stock page so the ticker is honored
     automatically instead of requiring manual re-entry.

MH4  FIX (this revision) — PortfolioManager(csv_path) does `Path(csv_path)`
     internally, so it has ALWAYS required an actual file path, never a
     DataFrame. MH1 dropped the old CSV-upload flow (and the _safe_tmpfile
     helper that used to bridge this) but nothing replaced that bridge, so
     every portfolio analysis run failed with
     "TypeError: ... not 'DataFrame'". A small temp-file helper
     (_holdings_csv_tmpfile) now writes the in-memory holdings to a real
     temp CSV and hands PortfolioManager that path, exactly as it expects.
     The temp file is cleaned up in a finally block.

MH5  FIX (this revision) — "Manage holdings" rendered raw input widgets with
     no column labels, so an opened expander was a wall of unlabeled boxes.
     Added a header row (Ticker / Qty / Avg ₹ / Date bought) above the list.

MH6  FIX (this revision) — "Add a holding" required typing the exact NSE
     ticker with no help. Added a searchable "Find by company name" dropdown
     (powered by the existing STOCK_SEARCH_MAP) that auto-fills the ticker
     field, similar to the lookup already used elsewhere in the app (e.g.
     Paper Trades). Manual ticker entry still works for anything not in the
     map.

Phase2  UI honesty — all action labels shown to the user go through
     _display_label() so "STRONG BUY" → "Strong Trend ▲▲" etc. Internal
     strings (DB, CSV export, sort keys) are unchanged.

QualityFix  compute_quality_score returns 0 for no-data; UI now treats
     0 as None so the table shows "—" instead of a misleading Quality=0.

DC1  DECISION-CLARITY REORDER (this revision) — the page previously buried
     the actual buy/hold/exit decision (holdings cards with score, action,
     SL/target, headline) below six other sections: live-price table, PM
     scoring spinner, health metrics, signal monitor, sector breakdown, and
     a full Risk & Performance block with NAV curve / correlation matrix.
     Someone opening the page had to scroll past all of that to reach the
     one thing that actually helps them decide anything. Reordered to:
     (1) fast top-line today/overall/value boxes, (2) PM scoring,
     (3) signal-flip alerts + health narrative, (4) the actual decision —
     holdings cards, right up top, (5) everything else under a clearly
     labelled "📊 Deeper Analysis (optional)" divider, unchanged internally.

DC2  MERGED REDUNDANT VIEWS — the old page rendered the SAME per-stock P&L
     twice: once as a plain live-price table, once as the scored holdings
     cards below. That's wasted render work and, worse, gives two numbers
     for "today's change" that can drift apart (table used live-price-cache
     `chg`, cards used PortfolioManager's `today_chg_pct` — same underlying
     data, two code paths). The table is gone; the fast top-line boxes
     (today/overall/value) are the only thing that runs off the quick
     live-price cache now, and the cards are the only per-stock P&L view.

DC3  CARDS NOW SURFACE RISK-REWARD + THE FULL "WHY" — score_stock() already
     computes a risk_reward ratio and a full multi-sentence narrative
     (pattern detection, sector rank, VIX regime context, entry/SL/TP
     reasoning) but the old card only ever showed the one-line headline and
     threw the rest away. No new fetches: added an RR badge on the card and
     a one-click "Why?" expander with the full narrative, straight from the
     HoldingResult that PortfolioManager already computed.
"""
import os
import sys
import tempfile
import pandas as pd
import plotly.express as px
import streamlit as st
import datetime as _dt

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from dashboard.shared.design import apply_design
from dashboard.shared.nav import render_sidebar
from dashboard.shared.chart_helpers import render_top_bar
from dashboard.shared.trade_utils import (
    _action_emoji,
    _display_label,                # Phase 2 UI honesty
    _paper_trade_popover,
    _portfolio_live_prices,
    clear_price_caches,            # FIX3
    load_signal_monitor_state,     # FIX TU5
    save_signal_monitor_state,     # FIX TU5
    load_manual_holdings,          # FIX MH1
    save_manual_holdings,          # FIX MH1
)
from dashboard.shared.chart_helpers import _ROOT, render_top_bar
from dashboard.shared.squareoff_monitor import render_squareoff_monitor
from dashboard.shared.cache import STOCK_SEARCH_MAP  # FIX MH6
from analysis.portfolio_concentration import analyze_concentration, concentration_grade
from analysis.portfolio_fundamentals import batch_fetch_fundamentals, compute_quality_score

apply_design()
render_sidebar(current="My Portfolio")
render_top_bar()

st.title("🏠 My Portfolio")
st.markdown(
    "Your holdings health check — live prices, trend-quality scores, and plain English guidance for each stock."
)

render_squareoff_monitor(poll_every=60, show_badge=True)


# FIX MH4 — PortfolioManager(csv_path) does Path(csv_path) internally and has
# always required a real file path, never a DataFrame. This writes the
# in-memory holdings list to a temp CSV and returns the path; caller is
# responsible for deleting it (done in a finally block below).
def _holdings_csv_tmpfile(df: pd.DataFrame) -> str:
    _tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".csv", prefix="nse_portfolio_", delete=False, newline=""
    )
    try:
        df.to_csv(_tmp.name, index=False)
    finally:
        _tmp.close()
    return _tmp.name


# ════════════════════════════════════════════════════════════════════════
# FIX MH1 — MANUAL HOLDINGS: add / edit / remove
# ════════════════════════════════════════════════════════════════════════
_holdings = load_manual_holdings()

# FIX MH7 — the company-name lookup dropdown lives OUTSIDE the form (so
# picking a name can update the ticker live), which meant clear_on_submit
# never touched it: after a successful add it kept showing the previously
# picked company, and that stale selection then silently overrode whatever
# new ticker you typed manually on the NEXT add (this is the "still shows
# the previous stock name when adding" bug). Streamlit also raises
# "cannot be modified after the widget is instantiated" if you try to reset
# a widget's session_state value after that widget has already rendered in
# the current script run — so the reset can't happen at submit time, it has
# to be deferred to the TOP of the next run, before the selectbox exists
# yet. Same clear-pending pattern Analyze Stock already uses for its own
# search box.
_MH_NONE = "— search by company name (optional) —"
if st.session_state.pop("_mh_clear_pending", False):
    st.session_state["mh_company_lookup"] = _MH_NONE

with st.expander("➕ Add a holding", expanded=(len(_holdings) == 0)):
    st.caption(
        "Enter your holding details manually. No price or quantity suggestions — "
        "type exactly what you hold."
    )

    # FIX MH6 — searchable company lookup, outside the form so picking a
    # name can update the ticker field live (form widgets don't rerun on
    # their own change, so this lives just above the form instead).
    _mh_company_options = [_MH_NONE] + sorted(STOCK_SEARCH_MAP.keys())
    _mh_picked_company = st.selectbox(
        "🔎 Find by company name",
        _mh_company_options,
        key="mh_company_lookup",
        help="Start typing a company name to filter — selecting one fills in the "
             "ticker below. Leave on the default option to type a ticker manually.",
    )
    _mh_looked_up_ticker = (
        STOCK_SEARCH_MAP.get(_mh_picked_company, "") if _mh_picked_company != _MH_NONE else ""
    )
    if _mh_looked_up_ticker:
        st.caption(f"→ Ticker: **{_mh_looked_up_ticker}**")

    with st.form("mh_add_form", clear_on_submit=True):
        _f1, _f2, _f3, _f4 = st.columns([2, 1, 1, 1.3])
        with _f1:
            _mh_ticker_manual = st.text_input(
                "Ticker (or use the lookup above)",
                placeholder="e.g. RELIANCE or RELIANCE.NS",
            ).strip().upper()
        with _f2:
            _mh_qty = st.number_input("Quantity", min_value=0.0, step=1.0, value=0.0)
        with _f3:
            _mh_price = st.number_input(
                "Avg buy price (₹)", min_value=0.0, step=0.05, value=0.0, format="%.2f"
            )
        with _f4:
            _mh_date = st.date_input("Date bought", value=_dt.date.today())
        _mh_submit = st.form_submit_button(
            "Add holding", type="primary", use_container_width=True
        )

    if _mh_submit:
        # FIX MH6 — the company-name lookup wins if a real company was
        # selected; otherwise fall back to whatever was typed manually.
        _mh_ticker = _mh_looked_up_ticker.replace(".NS", "") if _mh_looked_up_ticker else _mh_ticker_manual
        if not _mh_ticker:
            st.error("Ticker is required — type one, or pick a company from the lookup above.")
        elif _mh_qty <= 0:
            st.error("Quantity must be greater than 0.")
        elif _mh_price <= 0:
            st.error("Avg buy price must be greater than 0.")
        else:
            _norm_ticker = _mh_ticker if _mh_ticker.endswith(".NS") else _mh_ticker + ".NS"

            # FIX MH8 — unlike Analyze Stock (which validates the ticker and
            # tells you plainly if NSE doesn't recognise it), this form used
            # to save whatever was typed with zero feedback either way. Now:
            # 1) try resolving via data.universe.resolve_ticker (handles a
            #    correctable typo / partial name), 2) probe a real live
            #    price for the resolved ticker so "saved but is it actually
            #    a tradeable NSE symbol?" gets an honest answer immediately,
            #    not a silent save followed by a blank "Live Price: —" later.
            try:
                from data.universe import resolve_ticker as _mh_resolve
                _resolved = _mh_resolve(_mh_ticker)
                if _resolved:
                    _norm_ticker = _resolved
            except Exception as _res_e:
                import logging; logging.getLogger("dashboard.my_portfolio").debug("resolve_ticker(%s) failed: %s — using raw input", _mh_ticker, _res_e)

            _mh_recognized = False
            try:
                _mh_probe = _portfolio_live_prices((_norm_ticker,))
                _mh_recognized = bool(_mh_probe.get(_norm_ticker, {}).get("price"))
            except Exception as _probe_e:
                import logging; logging.getLogger("dashboard.my_portfolio").debug("live-price probe failed for %s: %s — treating as unrecognized, not blocking save", _norm_ticker, _probe_e)
                _mh_recognized = False  # network hiccup — don't block the save on this

            _holdings = [h for h in _holdings if h["ticker"] != _norm_ticker]
            _holdings.append({
                "ticker":        _norm_ticker,
                "quantity":      float(_mh_qty),
                "avg_buy_price": float(_mh_price),
                "date_bought":   _mh_date.isoformat(),
            })
            save_manual_holdings(_holdings)
            clear_price_caches()
            # FIX MH7 — reset the lookup dropdown on the NEXT run, not now.
            st.session_state["_mh_clear_pending"] = True

            if _mh_recognized:
                st.success(
                    f"✅ Recognized **{_norm_ticker.replace('.NS','')}** on NSE — "
                    "added to your portfolio."
                )
            else:
                st.warning(
                    f"⚠️ Added **{_norm_ticker.replace('.NS','')}**, but couldn't confirm "
                    "it against live NSE prices just now. Double-check the spelling "
                    "(e.g. Vedanta's ticker is **VEDL**, not VEDANTA) — if it's wrong, "
                    "delete it below and re-add with the correct ticker, or use the "
                    "company-name lookup above instead of typing it manually."
                )
            st.success(f"Added {_norm_ticker.replace('.NS','')} to your portfolio.")
            st.rerun()

if _holdings:
    with st.expander(f"✏️ Manage holdings ({len(_holdings)})", expanded=False):
        # FIX MH5 — header row so the unlabeled input boxes below are clear
        # at a glance (previously this expander had no labels at all).
        _mhh1, _mhh2, _mhh3, _mhh4, _mhh5 = st.columns([2, 1, 1, 1.3, 0.8])
        _mhh1.markdown("**Ticker**")
        _mhh2.markdown("**Qty**")
        _mhh3.markdown("**Avg ₹**")
        _mhh4.markdown("**Date bought**")
        _mhh5.markdown("**Del**")
        st.markdown(
            '<hr style="margin:2px 0 8px 0;border-color:rgba(255,255,255,.08)">',
            unsafe_allow_html=True,
        )

        for _i, _h in enumerate(_holdings):
            _mc1, _mc2, _mc3, _mc4, _mc5 = st.columns([2, 1, 1, 1.3, 0.8])
            _mc1.markdown(f"**{_h['ticker'].replace('.NS','')}**")
            _new_qty = _mc2.number_input(
                "Qty", min_value=0.0, step=1.0,
                value=float(_h["quantity"]), key=f"mh_qty_{_i}",
                label_visibility="collapsed",
            )
            _new_price = _mc3.number_input(
                "Avg ₹", min_value=0.0, step=0.05,
                value=float(_h["avg_buy_price"]), key=f"mh_price_{_i}",
                format="%.2f", label_visibility="collapsed",
            )
            try:
                _cur_date = _dt.date.fromisoformat(str(_h.get("date_bought"))[:10])
            except Exception as _dtparse_e:
                import logging; logging.getLogger("dashboard.my_portfolio").debug("date_bought parse failed for %s: %s — defaulting to today", _h.get("ticker"), _dtparse_e)
                _cur_date = _dt.date.today()
            _new_date = _mc4.date_input(
                "Date", value=_cur_date, key=f"mh_date_{_i}",
                label_visibility="collapsed",
            )
            if _mc5.button("🗑️", key=f"mh_del_{_i}", use_container_width=True):
                _holdings.pop(_i)
                save_manual_holdings(_holdings)
                clear_price_caches()
                st.rerun()
            if (_new_qty != _h["quantity"] or _new_price != _h["avg_buy_price"]
                    or _new_date.isoformat() != str(_h.get("date_bought"))[:10]):
                _h["quantity"]      = float(_new_qty)
                _h["avg_buy_price"] = float(_new_price)
                _h["date_bought"]   = _new_date.isoformat()
                save_manual_holdings(_holdings)

_csv_source = pd.DataFrame(_holdings) if _holdings else None

if _csv_source is not None:

    # ── FAST TOP-LINE (DC2) — today's/overall P&L + value only, off the ─────
    # quick 60s live-price cache. No per-stock table here anymore — that's
    # what the Decision Summary cards below are for, using PM's own
    # today_chg_pct so there's exactly one number per stock, not two.
    try:
        _port_csv = _csv_source.copy()
        _port_tickers = tuple(
            (t if t.endswith(".NS") else t + ".NS")
            for t in _port_csv["ticker"].tolist()
        )
        _live_col, _refresh_col = st.columns([5, 1])
        with _refresh_col:
            st.write("")
            if st.button("🔄 Refresh Prices", key="port_refresh_live"):
                clear_price_caches()
        with _live_col:
            st.markdown("#### 📡 Live Prices (updates every 60 s)")
        _live_prices = _portfolio_live_prices(_port_tickers)
        if _live_prices:
            _total_today_pnl   = 0.0
            _total_overall_pnl = 0.0
            _total_port_value  = 0.0
            _total_invested    = 0.0
            for _row in _port_csv.itertuples():
                _sym = _row.ticker if str(_row.ticker).endswith(".NS") else f"{_row.ticker}.NS"
                _lp  = _live_prices.get(_sym, {})
                _cur = _lp.get("price")
                _qty = getattr(_row, "quantity", 1)
                _buy = getattr(_row, "avg_buy_price", 0)
                if _cur:
                    _total_today_pnl   += (_cur - _lp.get("prev", _cur)) * _qty
                    _total_overall_pnl += (_cur - _buy) * _qty
                    _total_port_value  += _cur * _qty
                    _total_invested    += _buy * _qty

            _td_c = "#16c784" if _total_today_pnl >= 0 else "#ff4d4d"
            _ov_c = "#16c784" if _total_overall_pnl >= 0 else "#ff4d4d"
            _td_a = "▲" if _total_today_pnl >= 0 else "▼"
            _ov_a = "▲" if _total_overall_pnl >= 0 else "▼"
            _ov_p = (_total_overall_pnl / _total_invested * 100) if _total_invested > 0 else 0
            st.markdown(
                f'<div style="display:flex;gap:14px;margin:0 0 14px 0">'
                f'<div style="flex:1;background:#131316;padding:14px 18px;border-radius:10px;border-left:5px solid {_td_c}">'
                f'<div style="font-size:10px;color:#aaa;text-transform:uppercase;letter-spacing:1px;margin-bottom:3px">Today\'s Change</div>'
                f'<div style="font-size:24px;font-weight:700;color:{_td_c}">{_td_a} ₹{abs(_total_today_pnl):,.0f}</div>'
                f'</div>'
                f'<div style="flex:1;background:#131316;padding:14px 18px;border-radius:10px;border-left:5px solid {_ov_c}">'
                f'<div style="font-size:10px;color:#aaa;text-transform:uppercase;letter-spacing:1px;margin-bottom:3px">Overall P&amp;L</div>'
                f'<div style="font-size:24px;font-weight:700;color:{_ov_c}">{_ov_a} ₹{abs(_total_overall_pnl):,.0f} '
                f'<span style="font-size:14px">({_ov_p:+.1f}%)</span></div>'
                f'</div>'
                f'<div style="flex:1;background:#131316;padding:14px 18px;border-radius:10px;border-left:5px solid #2fd1e0">'
                f'<div style="font-size:10px;color:#aaa;text-transform:uppercase;letter-spacing:1px;margin-bottom:3px">Portfolio Value</div>'
                f'<div style="font-size:24px;font-weight:700;color:#fff">₹{_total_port_value:,.0f}</div>'
                f'</div>'
                f'</div>',
                unsafe_allow_html=True,
            )
        else:
            st.caption("⚠️ Live prices unavailable — trying again. Showing scored data below once ready.")
    except Exception as _e:
        st.caption(f"Live price strip skipped: {_e}")

    st.markdown("---")
    # FIX MH4 — PortfolioManager always expected a real CSV file path
    # (it does Path(csv_path) internally), never a DataFrame. Write the
    # in-memory holdings to a temp file and point PortfolioManager at that,
    # cleaning the temp file up afterwards regardless of success/failure.
    _pm_tmp_csv_path = None
    with st.spinner("Scoring your portfolio (parallel)… ~10–20 s for 5–10 stocks"):
        try:
            from analysis.portfolio_manager import PortfolioManager
            _pm_tmp_csv_path = _holdings_csv_tmpfile(_csv_source)
            pm = PortfolioManager(_pm_tmp_csv_path)
            summary = pm.mark_to_market(parallel=True)

            pnl_sign  = "+" if summary.total_pnl >= 0 else ""
            pnl_color = "#16c784" if summary.total_pnl >= 0 else "#ff4d4d"

            # ── DC1 — Health metrics + narrative come right after scoring ──
            st.markdown("---")
            c1, c2, c3, c4, c5 = st.columns(5)
            c1.metric("Portfolio Value",
                      f"₹{summary.total_current_value:,.0f}",
                      f"{pnl_sign}₹{summary.total_pnl:,.0f}")
            c2.metric("Total Return",
                      f"{pnl_sign}{summary.total_pnl_pct:.1f}%",
                      delta_color="normal" if summary.total_pnl >= 0 else "inverse")
            c3.metric("Health Score",
                      f"{summary.portfolio_score:.0f}/100",
                      f"Grade {summary.portfolio_grade}")
            c4.metric("Diversification", summary.diversification.concentration_risk)
            c5.metric("VIX Regime", summary.vix_regime)

            st.markdown(
                f'<div class="card-blue"><span class="narrative">'
                f'💡 <b>Portfolio Summary:</b> {summary.summary_narrative}'
                f'</span></div>',
                unsafe_allow_html=True
            )

            # ── Auto-Signal Monitor — signal changes right above the decision cards ─
            _PF_BUY  = {"STRONG BUY", "BUY"}
            _PF_SELL = {"CAUTION", "EXIT", "SELL", "REDUCE"}
            _pf_cur  = {h.ticker: h.action for h in summary.holdings}
            _pf_prev = load_signal_monitor_state()
            _pf_flips = []
            for _tk, _ac in _pf_cur.items():
                _pv = _pf_prev.get(_tk)
                if _pv and _pv != _ac and (_ac in _PF_BUY or _ac in _PF_SELL):
                    _pf_flips.append((_tk.replace(".NS", ""), _pv, _ac,
                                      "buy" if _ac in _PF_BUY else "sell"))
            save_signal_monitor_state(_pf_cur)

            _sg1, _sg2 = st.columns([5, 2])
            _sg1.markdown("### 🎯 Your Decision Summary")
            _pf_auto = _sg2.toggle("Auto-refresh (5 min)", key="pf_auto_signal")

            _pf_buys  = [h for h in summary.holdings if h.action in _PF_BUY]
            _pf_sells = [h for h in summary.holdings if h.action in _PF_SELL]

            if _pf_flips:
                _fl_rows = "".join(
                    f'<div style="font-size:12.5px;color:#fff;margin:2px 0">'
                    f'{"🟢" if _d == "buy" else "🔴"} <b>{_t}</b> '
                    f'<span style="color:#9aa">{_display_label(_p)}</span> → '
                    f'<b style="color:{"#16c784" if _d == "buy" else "#ff4d4d"}">{_display_label(_a)}</b></div>'
                    for _t, _p, _a, _d in _pf_flips)
                st.markdown(
                    f'<div style="background:rgba(242,169,59,.08);'
                    f'border-left:4px solid #f2a93b;border-radius:10px;padding:10px 14px;'
                    f'margin:4px 0 8px">'
                    f'<div style="font-size:12px;font-weight:700;color:#f2a93b;margin-bottom:3px">'
                    f'⚡ {len(_pf_flips)} signal change(s) since your last check</div>'
                    f'{_fl_rows}</div>', unsafe_allow_html=True)
                for _t, _p, _a, _d in _pf_flips:
                    st.toast(
                        f'{"🟢" if _d == "buy" else "🔴"} {_t}: '
                        f'{_display_label(_p)} → {_display_label(_a)}',
                        icon="⚡",
                    )

            st.caption(
                f"📡 **{len(_pf_buys)}** holding(s) in an **Uptrend / Strong Trend**, "
                f"**{len(_pf_sells)}** showing **Weakening / Exit Signal** right now — see the cards below. "
                "Trend-quality scores only; the app never auto-executes real trades. "
                "Toggle **Auto-refresh** to keep this live while the page is open.")

            if _pf_auto:
                @st.fragment(run_every="300s")
                def _pf_signal_tick():
                    st.rerun()
                _pf_signal_tick()

            # ── DC1/DC2/DC3 — THE DECISION: holdings cards, moved up front, ──
            # merged with per-stock P&L (no separate table anymore), each
            # card now also shows the risk-reward ratio and a "Why?"
            # expander with the full narrative already computed by
            # score_stock() — sector rank, VIX context, pattern detection,
            # entry/SL/TP reasoning — instead of throwing it away.
            _hh1, _hh2 = st.columns([3, 2])
            _hh1.markdown("Sorted so the stock most needing a decision is easy to find.")
            with _hh2:
                _h_sort = st.selectbox(
                    "Sort by",
                    ["Action (buy→exit)", "Total P&L (high→low)", "Total P&L (low→high)",
                     "Today's change", "Score (best first)", "Value (high→low)"],
                    key="pf_holdings_sort", label_visibility="collapsed",
                )
            _ACT_ORDER = {"STRONG BUY": 0, "BUY": 1, "WATCHLIST": 2, "HOLD": 3,
                          "CAUTION": 4, "EXIT": 5}
            _hold_sorted = list(summary.holdings)
            try:
                if _h_sort == "Action (buy→exit)":
                    _hold_sorted.sort(key=lambda h: _ACT_ORDER.get(h.action, 9))
                elif _h_sort == "Total P&L (high→low)":
                    _hold_sorted.sort(key=lambda h: -h.pnl)
                elif _h_sort == "Total P&L (low→high)":
                    _hold_sorted.sort(key=lambda h: h.pnl)
                elif _h_sort == "Today's change":
                    _hold_sorted.sort(
                        key=lambda h: -getattr(h, "today_chg_pct", getattr(h, "pnl_pct", 0))
                    )
                elif _h_sort == "Score (best first)":
                    _hold_sorted.sort(key=lambda h: -getattr(h, "score", 0))
                elif _h_sort == "Value (high→low)":
                    _hold_sorted.sort(key=lambda h: -(h.current_price * h.quantity))
            except Exception as _sort_e:
                import logging; logging.getLogger("dashboard.my_portfolio").debug("Holdings sort failed (%s): %s — using default order", _h_sort, _sort_e)
                _hold_sorted = list(summary.holdings)

            # Aligned to design.py's "Dealing Room v2" tokens (bull #16c784 /
            # bear #ff4d4d / caution #f2a93b / accent #2fd1e0) instead of the
            # pre-redesign teal/material-green/blue set, so this page matches
            # the rest of the app now.
            _ACT_CARD_STYLE = {
                "STRONG BUY": ("#16c784", "rgba(22,199,132,.10)"), "BUY": ("#3dbd8f", "rgba(61,189,143,.09)"),
                "WATCHLIST":  ("#2fd1e0", "rgba(47,209,224,.09)"), "HOLD": ("#8b8d93", "rgba(255,255,255,.04)"),
                "CAUTION":    ("#f2a93b", "rgba(242,169,59,.09)"), "EXIT": ("#ff4d4d", "rgba(255,77,77,.10)"),
            }
            _hc_grid = st.columns(2)
            for _hi, h in enumerate(_hold_sorted):
                _h_ac, _h_bg = _ACT_CARD_STYLE.get(h.action, ("#8b8d93", "#1a1a1a"))
                _h_emoji  = _action_emoji(h.action)
                _h_pnl_c  = "#16c784" if h.pnl >= 0 else "#ff4d4d"
                _h_pnl_a  = "▲" if h.pnl >= 0 else "▼"
                _h_lbl    = h.ticker.replace(".NS", "")
                _h_inv    = h.avg_buy_price * h.quantity
                _h_val    = h.current_price * h.quantity
                _h_sl     = h.stop_loss or (h.avg_buy_price * 0.95)
                _h_tp     = h.target    or (h.avg_buy_price * 1.10)
                _h_rng    = max(_h_tp - _h_sl, 0.01)
                _h_cur_pct = min(100, max(0, (h.current_price - _h_sl) / _h_rng * 100))
                _h_bar_c  = "#16c784" if h.current_price >= h.avg_buy_price else "#ff4d4d"
                _h_score_w = min(int(h.score), 100)
                _h_today  = getattr(h, "today_chg_pct", None)
                _h_today_c = "#16c784" if (_h_today or 0) >= 0 else "#ff4d4d"
                # PGF (Portfolio Gap Fix) — the removed live-price table used to be
                # the only place showing today's ₹ P&L per stock; the cards never
                # picked that up when the table was dropped. Derived here from
                # fields HoldingResult already has (current_price, quantity,
                # today_chg_pct) — no extra fetch, same number the top-line
                # "Today's Change" box would show if summed across holdings.
                _h_today_pnl = (
                    h.current_price * h.quantity * (_h_today / 100.0)
                    if _h_today is not None else None
                )
                _h_today_txt = (
                    f"{_h_today:+.2f}% · ₹{_h_today_pnl:+,.0f} today"
                    if _h_today is not None else ""
                )
                # DC3 — risk-reward badge, already computed, just unused before
                _h_rr = getattr(h, "risk_reward", None)
                _h_rr_txt = f"RR {_h_rr:.1f}:1" if _h_rr else ""

                # Phase 2 — honest display label, not raw action string
                _h_html = (
                    f'<div style="background:{_h_bg};border-left:5px solid {_h_ac};'
                    f'border-radius:10px;padding:14px 16px;margin-bottom:8px">'
                    f'<div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:6px">'
                    f'<div>'
                    f'<span style="font-size:20px;font-weight:700;color:#fff">{_h_lbl}</span>'
                    f'&nbsp;&nbsp;<span style="font-size:13px;font-weight:700;color:{_h_ac}">'
                    f'{_h_emoji} {_display_label(h.action)}</span>'
                    f'</div>'
                    f'<div style="text-align:right">'
                    f'<span style="font-size:13px;font-weight:700;color:{_h_ac}">{h.score:.0f}/100</span>'
                    f'<div style="width:60px;height:5px;background:#333;border-radius:3px;margin-top:3px">'
                    f'<div style="width:{_h_score_w}%;height:100%;background:{_h_ac};border-radius:3px"></div>'
                    f'</div></div></div>'
                    f'<div style="font-size:15px;color:#fff;margin-bottom:4px">'
                    f'<b>₹{h.current_price:,.2f}</b>'
                    f'<span style="font-size:12px;color:{_h_today_c};margin-left:8px;font-weight:600">{_h_today_txt}</span>'
                    f'<span style="font-size:12px;color:#aaa;margin-left:8px">'
                    f'{h.quantity:.0f} shares · held {h.days_held}d</span>'
                    f'</div>'
                    f'<div style="font-size:12px;color:#aaa;margin-bottom:6px">'
                    f'Invested ₹{_h_inv:,.0f} → Now ₹{_h_val:,.0f}'
                    f'{"  ·  " + _h_rr_txt if _h_rr_txt else ""}'
                    f'</div>'
                    f'<div style="font-size:18px;font-weight:700;color:{_h_pnl_c};margin-bottom:8px">'
                    f'{_h_pnl_a} ₹{abs(h.pnl):,.0f} ({h.pnl_pct:+.1f}%)'
                    f'</div>'
                    f'<div style="margin-bottom:6px">'
                    f'<div style="display:flex;justify-content:space-between;font-size:10px;color:#666;margin-bottom:2px">'
                    f'<span>SL ₹{_h_sl:,.0f}</span><span>Target ₹{_h_tp:,.0f}</span></div>'
                    f'<div style="width:100%;height:6px;background:#333;border-radius:3px;position:relative">'
                    f'<div style="position:absolute;left:0;width:{_h_cur_pct:.0f}%;height:100%;'
                    f'background:{_h_bar_c};border-radius:3px;opacity:0.7"></div>'
                    f'<div style="position:absolute;left:{_h_cur_pct:.0f}%;transform:translateX(-50%);'
                    f'top:-4px;width:14px;height:14px;background:{_h_bar_c};border-radius:50%;'
                    f'border:2px solid #fff"></div>'
                    f'</div></div>'
                    f'<div style="font-size:12px;color:#ccc;margin-top:6px">{h.headline}</div>'
                    f'</div>'
                )
                with _hc_grid[_hi % 2]:
                    st.markdown(_h_html, unsafe_allow_html=True)
                    _hb1, _hb2, _hb3 = st.columns(3)
                    with _hb1:
                        if st.button(f"📊 Analyze", key=f"ph_an_{h.ticker}",
                                     use_container_width=True):
                            # FIX MH3
                            st.session_state["analyze_ticker"] = h.ticker
                            st.session_state["_goto_page"]     = "🔍 Analyze Stock"
                            st.rerun()
                    with _hb2:
                        _ph_price = h.current_price or h.avg_buy_price
                        _paper_trade_popover(
                            h.ticker, _ph_price, h.stop_loss or _ph_price * 0.95, h.target,
                            reason=f"{h.action}: {h.headline}",
                            key=f"ph_pt_{h.ticker}",
                        )
                    with _hb3:
                        # DC3 — the full narrative was always computed, just
                        # never shown. One click, no extra fetch.
                        with st.popover("❓ Why?", use_container_width=True):
                            st.caption(h.narrative or h.headline)
                    if h.error:
                        st.caption(f"⚠️ {h.error}")

            # ══════════════════════════════════════════════════════════════
            # DC1 — DEEPER ANALYSIS (optional), everything below unchanged
            # internally, just moved beneath the decision cards.
            # ══════════════════════════════════════════════════════════════
            st.markdown("---")
            st.markdown("## 📊 Deeper Analysis (optional)")

            # ── Diversification ────────────────────────────────────────
            div = summary.diversification
            if div.sector_weights:
                with st.expander("📊 Sector Breakdown", expanded=False):
                    div_df = pd.DataFrame(
                        list(div.sector_weights.items()),
                        columns=["Sector", "Weight (%)"]
                    ).sort_values("Weight (%)", ascending=False)
                    col_pie, col_txt = st.columns([1, 1])
                    with col_pie:
                        fig_pie = px.pie(
                            div_df, names="Sector", values="Weight (%)",
                            title="Portfolio by Sector",
                            color_discrete_sequence=px.colors.qualitative.Set3,
                        )
                        fig_pie.update_layout(
                            template="nse_pro", height=300,
                            margin=dict(l=0, r=0, t=40, b=0),
                        )
                        st.plotly_chart(fig_pie, width="stretch")
                    with col_txt:
                        risk_color = {"LOW": "card-green", "MEDIUM": "card-yellow",
                                      "HIGH": "card-red", "VERY HIGH": "card-red"}.get(
                            div.concentration_risk, "card-blue")
                        st.markdown(
                            f'<div class="{risk_color}">'
                            f'<b>Concentration Risk: {div.concentration_risk}</b><br>'
                            f'{div.advice}</div>',
                            unsafe_allow_html=True
                        )

            # ── Portfolio Heatmap (moved here from the old top-of-page ──
            # live-price strip — this is deeper analysis, not a decision).
            _hm_rows = []
            for _row in _port_csv.itertuples():
                _sym = _row.ticker if str(_row.ticker).endswith(".NS") else f"{_row.ticker}.NS"
                _lp  = _live_prices.get(_sym, {}) if _live_prices else {}
                _cur = _lp.get("price")
                _buy = getattr(_row, "avg_buy_price", 0)
                _qty = getattr(_row, "quantity", 1)
                if _cur and _buy and _buy > 0:
                    _pct = (_cur / _buy - 1) * 100
                    _val = _cur * _qty
                    _hm_rows.append({
                        "label": _row.ticker, "value": _val,
                        "pct": round(_pct, 2),
                        "text": f"{_row.ticker}<br>{_pct:+.1f}%<br>₹{_val/1000:.0f}K",
                    })
            if _hm_rows:
                with st.expander(
                    "📊 Portfolio Heatmap — sized by value, coloured by P&L", expanded=False
                ):
                    _hm_df = pd.DataFrame(_hm_rows)
                    import plotly.express as _px2
                    _fig_hm = _px2.treemap(
                        _hm_df, path=["label"], values="value", color="pct",
                        color_continuous_scale=["#ff4d4d", "#555555", "#16c784"],
                        color_continuous_midpoint=0, custom_data=["pct", "text"],
                    )
                    _fig_hm.update_traces(
                        texttemplate="%{customdata[1]}", textfont_size=13,
                        hovertemplate="<b>%{label}</b><br>P&L: %{customdata[0]:+.1f}%<extra></extra>",
                    )
                    _fig_hm.update_layout(
                        template="nse_pro", height=300,
                        margin=dict(l=0, r=0, t=10, b=0),
                        coloraxis_showscale=False,
                    )
                    st.plotly_chart(_fig_hm, use_container_width=True)

            # ── Portfolio Risk & Performance ───────────────────────────
            st.markdown("---")
            _rh1, _rh2 = st.columns([5, 2])
            _rh1.subheader("📉 Portfolio Risk & Performance")
            with _rh2:
                _risk_period = st.selectbox(
                    "Lookback", ["6mo", "1y", "2y", "3y"], index=1,
                    key="pf_risk_period", label_visibility="collapsed")

            _db_map = {}
            for _hr in getattr(pm, "holdings_raw", []) or []:
                _rt = str(_hr.get("ticker", "")).strip().upper()
                if _rt and not _rt.endswith(".NS"):
                    _rt += ".NS"
                if _rt:
                    _db_map[_rt] = _hr.get("date_bought")
            _risk_holds = tuple(
                (h.ticker, float(getattr(h, "quantity", 0) or 0),
                 _db_map.get(str(h.ticker).upper()))
                for h in summary.holdings if getattr(h, "quantity", 0))

            @st.cache_data(ttl=900, show_spinner=False)
            def _pf_risk(_holds, _period):
                import pandas as _pd
                from analysis.portfolio_risk import compute_portfolio_risk
                from data.fetcher import fetch_single as _fs

                def _tz_safe_loader(_tkr, period="1y"):
                    _df = _fs(_tkr, period=period)
                    try:
                        if _df is not None and not getattr(_df, "empty", True):
                            _ix = _df.index
                            if isinstance(_ix, _pd.DatetimeIndex) and _ix.tz is not None:
                                _df = _df.copy()
                                _df.index = _ix.tz_localize(None)
                    except Exception as _tz_e:
                        import logging; logging.getLogger("dashboard.my_portfolio").debug("tz_localize skipped for %s: %s", _tkr, _tz_e)
                    return _df

                return compute_portfolio_risk(
                    [{"ticker": t, "quantity": q, "date_bought": db}
                     for t, q, db in _holds], period=_period, price_loader=_tz_safe_loader)

            def _rm(_col, _label, _val, _unit=""):
                if _val is None:
                    _col.metric(_label, "N/A")
                elif _unit == "%":
                    _col.metric(_label, f"{_val:.1f}%")
                else:
                    _col.metric(_label, f"{_val:.2f}")

            if not _risk_holds:
                st.caption("No holdings with quantity to analyze.")
            else:
                with st.spinner("Reconstructing NAV & computing risk metrics…"):
                    _rr = _pf_risk(_risk_holds, _risk_period)
                if _rr.error:
                    st.warning(f"⚠️ Risk analytics unavailable: {_rr.error}")
                else:
                    if (_rr.affected_weight_pct or 0) >= 25 or not _rr.purchase_dates_known:
                        st.warning(f"⚠️ {_rr.disclosure}")
                    else:
                        st.info(f"ℹ️ {_rr.disclosure}")
                    st.caption(f"Confidence: **{_rr.confidence}** — {_rr.confidence_reason}")

                    st.markdown("##### 📈 Hypothetical Performance — *if you'd held today's exact book*")
                    _perf = _rr.performance_metrics()
                    _p1 = st.columns(3)
                    for _i, (_l, _v, _u) in enumerate(_perf[:3]):
                        _rm(_p1[_i], _l, _v, _u)
                    _p2 = st.columns(3)
                    for _i, (_l, _v, _u) in enumerate(_perf[3:]):
                        _rm(_p2[_i], _l, _v, _u)
                    if _rr.nav_curve is not None:
                        _nav_df = _rr.nav_curve.rename("NAV").reset_index()
                        _nav_df.columns = ["Date", "NAV"]
                        _fig_nav = px.area(_nav_df, x="Date", y="NAV",
                                           title="Portfolio NAV / Equity Curve (reconstructed)")
                        _fig_nav.update_layout(template="nse_pro", height=280,
                                               margin=dict(l=0, r=0, t=40, b=0))
                        st.plotly_chart(_fig_nav, width="stretch")

                    st.markdown("##### 🛡️ Risk Profile (current book) — *robust to the holdings assumption*")
                    _rk = _rr.risk_metrics()
                    _rcols = st.columns(4)
                    _rm(_rcols[0], _rk[0][0], _rk[0][1], _rk[0][2])
                    _rm(_rcols[1], _rk[1][0], _rk[1][1], _rk[1][2])
                    _rcols[2].metric("Holdings analysed", len(_rr.holdings_used))
                    _rcols[3].metric("Lookback (days)", _rr.n_days)
                    _rcL, _rcR = st.columns([1, 1])
                    with _rcL:
                        if _rr.correlation_matrix is not None:
                            _figc = px.imshow(_rr.correlation_matrix, text_auto=True,
                                              color_continuous_scale="RdBu_r",
                                              zmin=-1, zmax=1, aspect="auto",
                                              title="Holdings Correlation")
                            _figc.update_layout(template="nse_pro", height=360,
                                                margin=dict(l=0, r=0, t=40, b=0))
                            st.plotly_chart(_figc, width="stretch")
                        else:
                            st.caption("Correlation needs ≥2 holdings with shared history.")
                    with _rcR:
                        st.markdown("**Risk contribution by position**")
                        _rc_df = pd.DataFrame(
                            [{"Stock": p.ticker, "Weight %": p.weight_pct,
                              "Beta": p.beta, "Risk %": p.risk_contribution_pct}
                             for p in _rr.risk_contributions])
                        st.dataframe(_rc_df, width="stretch", hide_index=True)
                        st.caption("**Risk %** = share of portfolio *variance* from each "
                                   "position — concentration of risk, which can differ from "
                                   "capital weight.")

                    with st.expander("ℹ️ Methodology & assumptions", expanded=False):
                        st.markdown("**Two metric groups, two interpretations:**")
                        st.markdown("- **Hypothetical Performance** assumes today's holdings were held "
                                    "over the whole lookback — read as *current-book hypothetical*, "
                                    "not realised returns.")
                        st.markdown("- **Risk Profile** (Beta, Volatility, Correlation, Risk "
                                    "Contribution) are current-book snapshots — safe to trust.")
                        for _n in _rr.notes:
                            st.markdown(f"- {_n}")
                        st.caption("Informational analytics — not investment advice.")

            # ── Concentration & Diversification (HHI) ─────────────────
            st.markdown("---")
            st.markdown("##### 🎯 Concentration & Diversification")
            try:
                _conc_holdings = []
                _tot_val = sum(max(h.current_price * h.quantity, 0) for h in summary.holdings)
                if _tot_val > 0:
                    for h in summary.holdings:
                        _w = (h.current_price * h.quantity) / _tot_val * 100
                        _row = {"ticker": h.ticker.replace(".NS", ""), "weight_pct": _w}
                        _sec = getattr(h, "sector", None)
                        if _sec:
                            _row["sector"] = _sec
                        _conc_holdings.append(_row)
                _conc  = analyze_concentration(_conc_holdings)
                _grade = concentration_grade(_conc.hhi)
                _risk_color = {"LOW": "#16c784", "MEDIUM": "#f2a93b",
                               "HIGH": "#ff4d4d"}.get(_conc.risk_level, "#8b8d93")
                _cc = st.columns(4)
                _cc[0].markdown(
                    f'<div class="metric-box"><div class="metric-lbl">HHI Index</div>'
                    f'<div class="metric-val" style="color:{_risk_color}">{_conc.hhi:,.0f}</div>'
                    f'<div style="font-size:11px;color:#8b8d93">{_conc.hhi_category} · Grade {_grade}</div></div>',
                    unsafe_allow_html=True)
                _cc[1].metric("Largest Position", f"{_conc.top_1_weight:.1f}%")
                _cc[2].metric("Top 5 Weight",     f"{_conc.top_5_weight:.1f}%")
                _cc[3].metric("Holdings",          _conc.total_holdings)
                _cm = "card-green" if _conc.risk_level == "LOW" else (
                    "card-yellow" if _conc.risk_level == "MEDIUM" else "card-red")
                st.markdown(
                    f'<div class="{_cm}"><b>Concentration risk: {_conc.risk_level}</b><br>'
                    f'<span class="narrative">{_conc.recommendation}</span></div>',
                    unsafe_allow_html=True)
                if _conc.sector_concentration is not None:
                    st.caption(f"Sector HHI: {_conc.sector_concentration:,.0f} "
                               "(higher = more concentrated by sector).")
                st.caption("**HHI** = Σ(weight%)². <1500 diversified · 1500–2500 moderate · "
                           ">2500 concentrated. Informational, not advice.")
            except Exception as _conc_err:
                st.caption(f"Concentration analysis unavailable: {_conc_err}")

            # ── Fundamental Quality ────────────────────────────────────
            st.markdown("##### 🔬 Fundamental Quality Scores")
            st.caption("Quality score (0–100) from ROE/ROCE, revenue & EPS CAGR, "
                       "leverage, and FCF health. Fetches live fundamentals — opt-in.")
            if st.button("📊 Score my holdings on fundamentals", key="pf_fund_btn"):
                _fund_tickers = [h.ticker for h in summary.holdings]

                @st.cache_data(ttl=86400, show_spinner=False)
                def _cached_fundamentals(tickers_tuple: tuple):
                    rows = []
                    for _f in batch_fetch_fundamentals(list(tickers_tuple)):
                        try:
                            _q = compute_quality_score(_f)
                        except Exception as _qs_e:
                            import logging; logging.getLogger("dashboard.my_portfolio").debug("compute_quality_score failed for %s: %s", _f.get("ticker"), _qs_e)
                            _q = None
                        rows.append({
                            "Stock":      str(_f.get("ticker", "")).replace(".NS", ""),
                            # QualityFix: 0 means no data — render as "—" not "0"
                            "Quality":    round(_q, 0) if (_q is not None and _q > 0) else None,
                            "ROE %":      _f.get("roe"),
                            "ROCE %":     _f.get("roce"),
                            "Rev CAGR %": _f.get("revenue_cagr_5y") or _f.get("revenue_cagr_3y"),
                            "EPS CAGR %": _f.get("eps_cagr_5y") or _f.get("eps_cagr_3y"),
                            "D/E":        _f.get("debt_to_equity"),
                        })
                    return rows

                with st.spinner("Fetching fundamentals for your holdings…"):
                    _fund_rows = _cached_fundamentals(tuple(_fund_tickers))

                if _fund_rows:
                    _fdf = pd.DataFrame(_fund_rows).sort_values(
                        "Quality", ascending=False, na_position="last")
                    st.dataframe(
                        _fdf.style.format({
                            "Quality": "{:.0f}", "ROE %": "{:.1f}", "ROCE %": "{:.1f}",
                            "Rev CAGR %": "{:.1f}", "EPS CAGR %": "{:.1f}", "D/E": "{:.2f}",
                        }, na_rep="—").background_gradient(
                            subset=["Quality"], cmap="RdYlGn", vmin=0, vmax=100),
                        hide_index=True, width="stretch")
                    _avg_q = _fdf["Quality"].dropna().mean()
                    if pd.notna(_avg_q):
                        st.caption(f"Average portfolio quality: **{_avg_q:.0f}/100** "
                                   f"across {_fdf['Quality'].notna().sum()} scored holdings.")
                else:
                    st.info("No fundamental data could be retrieved (source may be rate-limited).")

            # ── Best / Worst ───────────────────────────────────────────
            st.markdown("---")
            bw_cols = st.columns(2)
            if summary.best_holding:
                bh = summary.best_holding
                with bw_cols[0]:
                    st.markdown(
                        f'<div class="card-green">'
                        f'🏆 <b>Best Performer:</b> {bh.ticker.replace(".NS","")} '
                        f'(+{bh.pnl_pct:.1f}%, ₹+{bh.pnl:,.0f})</div>',
                        unsafe_allow_html=True)
            if summary.worst_holding:
                wh = summary.worst_holding
                with bw_cols[1]:
                    sign = "+" if wh.pnl_pct >= 0 else ""
                    st.markdown(
                        f'<div class="card-red">'
                        f'📉 <b>Needs Attention:</b> {wh.ticker.replace(".NS","")} '
                        f'({sign}{wh.pnl_pct:.1f}%, ₹{sign}{wh.pnl:,.0f})</div>',
                        unsafe_allow_html=True)

            # ── Export ─────────────────────────────────────────────────
            st.markdown("---")
            export_df = pd.DataFrame([{
                "Ticker":   h.ticker.replace(".NS", ""),
                "Qty":      h.quantity,
                "Buy Price": h.avg_buy_price,
                "Current":  h.current_price,
                "P&L (₹)":  round(h.pnl, 2),
                "P&L (%)":  round(h.pnl_pct, 2),
                "Score":    h.score,
                "Grade":    h.grade,
                "Action":   h.action,   # internal string kept in CSV
                "Signal":   h.signal.replace("🟢","G").replace("🟡","Y").replace("🔴","R"),
                "Sector":   h.sector,
            } for h in summary.holdings])
            st.download_button(
                "📥 Download Full Report CSV",
                data=export_df.to_csv(index=False).encode(),
                file_name="portfolio_health_report.csv",
                mime="text/csv",
            )

        except Exception as e:
            import logging as _pf_logging, traceback as _pf_tb
            _pf_logging.getLogger("dashboard.my_portfolio").error(
                "Portfolio analysis failed: %s", e, exc_info=True)
            st.error(f"Portfolio analysis failed: {type(e).__name__}: {e}")
            with st.expander("Show technical details (for debugging)"):
                st.code(_pf_tb.format_exc())
        finally:
            # FIX MH4 — always clean up the temp CSV, success or failure.
            if _pm_tmp_csv_path:
                try:
                    os.remove(_pm_tmp_csv_path)
                except Exception as _rm_e:
                    import logging; logging.getLogger("dashboard.my_portfolio").debug("Could not remove tmp CSV %s: %s", _pm_tmp_csv_path, _rm_e)
else:
    st.markdown("---")
    st.info(
        "No holdings yet. Use **➕ Add a holding** above to get started.  \n\n"
        "**What you'll see once added:**  \n"
        "- 🚀 Strong Trend / Uptrend = strong, persistent trend momentum  \n"
        "- 🟡 Neutral = mixed signals, no clear edge  \n"
        "- ⚠️ Weakening / Exit Signal = trend deteriorating  \n"
        "- Trend-quality score (0–100) — higher = stronger trend (not a return forecast)  \n"
        "- Plain English explanation and suggested stop-loss / target per holding"
    )
    col_ex1, col_ex2, col_ex3 = st.columns(3)
    with col_ex1:
        st.markdown("""
        <div class="card-green">
        <b>🚀 Strong Trend ▲▲ / Uptrend ▲ (Score ≥ 65)</b><br>
        Technicals, momentum, and volume are aligned.
        This is a trend-quality score — not a return forecast or advice to buy.
        </div>
        """, unsafe_allow_html=True)
    with col_ex2:
        st.markdown("""
        <div class="card-yellow">
        <b>🟡 Neutral (Score 40–64)</b><br>
        Mixed signals — some positives, some caution.
        Monitor your position; no clear directional edge right now.
        </div>
        """, unsafe_allow_html=True)
    with col_ex3:
        st.markdown("""
        <div class="card-red">
        <b>⚠️ Weakening ▼ / Exit Signal ▼▼ (Score &lt; 40)</b><br>
        Trend quality is deteriorating.
        Consider reviewing your position size or tightening your stop-loss.
        </div>
        """, unsafe_allow_html=True)
