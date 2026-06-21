"""Smart Screener - NSE Smart Investor (multipage page; body verbatim from app.py)."""
import os
import sys
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import pandas as pd
import streamlit as st

from dashboard.shared.design import apply_design
from dashboard.shared.nav import render_sidebar
from dashboard.shared.cache import get_vix_info
from dashboard.shared.trade_utils import _action_color, _action_emoji
from dashboard.shared.chart_helpers import render_top_bar

apply_design()
render_sidebar(current="Smart Screener")
render_top_bar()

# ───────────────────────── page body (de-indented from app.py) ─────────────────────────
st.title("🔎 Smart Stock Screener")
st.markdown(
    "Scan the NSE universe using 4 proven screens — oversold bounce, "
    "momentum leaders, breakouts, and pullback entries.  \n"
    "Each match is enriched with a **trend-quality score** (0–100 — trend health, "
    "not a return forecast)."
)

# Phase 1 (UI honesty): regime reliability next to live score output
from dashboard.shared.disclosures import (
    render_regime_reliability_note as _scr_regime_note,
    render_score_methodology as _scr_score_methodology,
)
_scr_regime_note()
_scr_score_methodology()

sc1, sc2, sc3 = st.columns(3)
with sc1:
    universe_choice = st.selectbox(
        "Universe",
        ["NIFTY 50 (50 stocks)", "NIFTY 100 (100 stocks)",
         "NIFTY 200 (200 stocks)", "NIFTY 500 (~400 stocks)"],
    )
    universe_map = {
        "NIFTY 50 (50 stocks)":    "nifty50",
        "NIFTY 100 (100 stocks)":  "nifty100",
        "NIFTY 200 (200 stocks)":  "nifty200",
        "NIFTY 500 (~400 stocks)": "nifty500",
    }
    universe_key = universe_map[universe_choice]
with sc2:
    screen_choice = st.selectbox(
        "Screen type",
        ["All 4 screens", "Oversold Bounce", "Momentum Leaders",
         "Breakouts", "Pullback to SMA"],
    )
    screen_map = {
        "All 4 screens": "all",
        "Oversold Bounce": "oversold",
        "Momentum Leaders": "momentum",
        "Breakouts": "breakout",
        "Pullback to SMA": "pullback_SMA20",
    }
    screen_key = screen_map[screen_choice]
with sc3:
    enrich_scores = st.checkbox("Enrich with trend-quality score", value=True,
                                help="Adds the 0-100 trend-quality score to each result (slower)")

# ── Revenue-growth filter (R1 — per REVENUE_GROWTH_DISCOVERY_AUDIT.md) ────────
# Thresholds capped at 15%: the audit showed >20% concentrates results into one
# sector and silently removes 19/21 top trend-quality names. Default "Any" so
# the column informs without filtering; missing data is included by default.
rgf1, rgf2 = st.columns([2, 3])
with rgf1:
    rg_filter = st.selectbox(
        "Revenue growth filter",
        ["Any", "> 0%", "> 5%", "> 10%", "> 15%"],
        index=0, key="scr_rg_filter",
        help="Filters results by annualised revenue growth (audited statements). "
             "Capped at 15% — higher thresholds were shown to distort discovery.",
    )
with rgf2:
    st.write("")
    rg_excl_missing = st.toggle(
        "Exclude stocks without growth data",
        value=False, key="scr_rg_excl",
        help="Off (default): stocks with no growth data stay visible and show '—'. "
             "Only ~4% of the universe lacks data.",
    )

scan_btn = st.button("🔍 Run Screen", type="primary")

if scan_btn:
    from data.universe import get_universe
    from trading.signals import scan_tickers
    universe = get_universe(universe_key)

    with st.spinner(f"Scanning {len(universe)} stocks… this may take a few minutes…"):
        signals = scan_tickers(universe, strategy=screen_key, period="1y")

    if not signals:
        st.info("No signals found for the current screen. Try a broader universe or different screen.")
    else:
        st.success(f"✅ Found **{len(signals)} setups** across {len(universe)} stocks!")
        vix_info = get_vix_info()

        if enrich_scores:
            from analysis.score import score_stock
            scored_signals = []
            prog = st.progress(0)
            for i, sig in enumerate(signals):
                try:
                    cs = score_stock(sig["ticker"], period="1y", vix_info=vix_info)
                    sig["composite_score"] = round(cs.score, 1)
                    sig["grade"]           = cs.grade
                    sig["action"]          = cs.action
                    sig["narrative"]       = cs.headline
                    sig["stop_loss"]       = round(cs.stop_loss, 2)
                    sig["target"]          = round(cs.target, 2)
                except Exception as _score_e:
                    import logging; logging.getLogger("dashboard.smart_screener").debug("score_stock failed for %s: %s — using neutral fallback", sig.get("ticker"), _score_e)
                    sig["composite_score"] = 50
                    sig["grade"]           = "C"
                    sig["action"]          = sig.get("action", "WATCHLIST")
                    sig["narrative"]       = "—"
                scored_signals.append(sig)
                prog.progress((i + 1) / len(signals))
            signals = sorted(scored_signals, key=lambda x: x.get("composite_score", 0), reverse=True)

        # ── Revenue-growth enrichment (R1) — bounded fetch, graceful "—" ──────
        # Per the discovery audit: never block indefinitely; anything not back
        # within the time budget renders as "—". Display/filter only — the
        # ordering above (composite score) is never touched.
        with st.spinner("Fetching revenue growth for results…"):
            from concurrent.futures import ThreadPoolExecutor, wait as _fwait

            def _rg_for(sig):
                try:
                    from analysis.fundamentals.service import default_service
                    from analysis.fundamentals.analytics import revenue_cagr
                    cf = default_service().get_fundamentals(sig["ticker"])
                    if cf is not None:
                        r = revenue_cagr(cf, years=5)
                        if getattr(r, "available", False) and r.value is not None:
                            return float(r.value)
                except Exception as _rg_thr_e:
                    import logging; logging.getLogger("dashboard.smart_screener").debug("rev growth fetch failed for %s: %s", sig.get('ticker'), _rg_thr_e)
                return None

            _rg_pool = ThreadPoolExecutor(max_workers=8)
            try:
                _rg_futs = {_rg_pool.submit(_rg_for, s): s for s in signals}
                _done, _ = _fwait(list(_rg_futs.keys()), timeout=30)
                for _f in _done:
                    try:
                        _rg_futs[_f]["rev_growth"] = _f.result(timeout=0)
                    except Exception as _rg_res_e:
                        import logging; logging.getLogger("dashboard.smart_screener").debug("rev growth result fetch failed for %s: %s", _rg_futs[_f].get("ticker"), _rg_res_e)
                        _rg_futs[_f]["rev_growth"] = None
            finally:
                # BUGFIX: previously shutdown(wait=False) left any still-running
                # fetch threads executing in the background indefinitely after
                # this function returned. cancel_futures=True (Py3.9+) drops
                # everything that hasn't started yet instead of leaking threads;
                # already-running fetches still finish naturally but are no
                # longer joined or waited on.
                _rg_pool.shutdown(wait=False, cancel_futures=True)
            for s in signals:
                s.setdefault("rev_growth", None)

        # ── Apply the growth filter (subsets only — never reorders) ───────────
        _rg_th = {"Any": None, "> 0%": 0.0, "> 5%": 5.0,
                  "> 10%": 10.0, "> 15%": 15.0}[rg_filter]
        _n_before = len(signals)
        if _rg_th is not None or rg_excl_missing:
            def _passes(s):
                g = s.get("rev_growth")
                if g is None:
                    return not rg_excl_missing
                return True if _rg_th is None else g > _rg_th
            signals = [s for s in signals if _passes(s)]
            _n_missing_kept = sum(1 for s in signals if s.get("rev_growth") is None)
            st.caption(
                f"🔎 Revenue-growth filter: **{len(signals)} of {_n_before}** setups kept"
                + (f" (incl. {_n_missing_kept} without growth data — shown as '—')"
                   if _n_missing_kept else "")
                + ". Ordering is unchanged — the filter only narrows the list."
            )
        from dashboard.shared.disclosures import (
            render_revenue_growth_evidence as _scr_rg_evidence,
        )
        _scr_rg_evidence()

        # Display results as Trade Setup Cards
        for sig in signals[:30]:  # cap at 30 for performance
            t      = sig["ticker"].replace(".NS", "")
            action = sig.get("action", "WATCHLIST")
            card   = _action_color(action)
            emoji  = _action_emoji(action)
            _s_price = sig.get("price", 0)
            _s_sl    = sig.get("sl", sig.get("stop_loss", 0)) or 0
            _s_tp    = sig.get("tp", sig.get("target", None))
            # BUGFIX: previously max(_s_price - _s_sl, 0.01) clamped a negative
            # or zero risk denominator (stop-loss at/above price) up to 0.01,
            # which inflated R:R into misleadingly huge numbers instead of
            # signalling "this setup's risk is invalid". Now falls back to
            # None ("—" downstream) whenever the risk leg isn't a sane long.
            _s_rr = sig.get("rr_ratio")
            if _s_rr is None and _s_tp:
                _risk = _s_price - _s_sl
                _s_rr = round((_s_tp - _s_price) / _risk, 1) if _risk > 0.01 else None
            _s_sector    = sig.get("sector", "")
            _s_stop_type = sig.get("stop_type", "atr")
            _s_score_str = (f"Score {sig.get('composite_score','?')}/100 "
                            f"[{sig.get('grade','?')}]" if enrich_scores else "")
            _s_rr_str    = f"R:R {_s_rr:.1f}x" if _s_rr else ""
            _header = (f"{emoji} {t}  |  ₹{_s_price:,.2f}  "
                       f"|  {sig.get('screen','')}  "
                       + (f"|  {_s_rr_str}  " if _s_rr_str else "")
                       + (f"|  {_s_sector}  " if _s_sector else "")
                       + _s_score_str)
            _s_rg = sig.get("rev_growth")
            with st.expander(_header, expanded=False):
                d1, d2, d3, d4, d5, d6 = st.columns(6)
                d1.metric("Entry",  f"₹{_s_price:,.2f}")
                d2.metric("Stop-Loss", f"₹{_s_sl:,.2f}",
                          delta=f"({_s_stop_type})",
                          delta_color="off")
                d3.metric("Target", f"₹{_s_tp:,.2f}" if _s_tp else "Trail SMA20")
                d4.metric("R:R",    f"{_s_rr:.1f}x" if _s_rr else "—",
                          delta="✅ Good" if (_s_rr or 0) >= 2 else "⚠️ Low",
                          delta_color="normal" if (_s_rr or 0) >= 2 else "inverse")
                d5.metric("Sector", _s_sector or "—")
                d6.metric("Rev Growth /yr",
                          f"{_s_rg:+.1f}%" if _s_rg is not None else "—",
                          help="Annualised revenue growth from audited statements — "
                               "a research-backed observation, not a buy signal.")
                if sig.get("reason"):
                    st.caption(f"📌 {sig['reason']}")
                if enrich_scores and sig.get("narrative"):
                    st.markdown(
                        f'<div class="{card}" style="padding:10px 14px">'
                        f'<b>{sig.get("narrative","")}</b></div>',
                        unsafe_allow_html=True
                    )

        # Download results
        result_df = pd.DataFrame(signals)
        if not result_df.empty:
            st.download_button(
                "📥 Download Watchlist CSV",
                data=result_df.to_csv(index=False).encode(),
                file_name="nse_watchlist.csv",
                mime="text/csv",
            )


# ═══════════════════════════════════════════════════════════════════════════════
# PAGE 5 — PAPER TRADES  (full UI — enter, track, close, analyse)
# ═══════════════════════════════════════════════════════════════════════════════
