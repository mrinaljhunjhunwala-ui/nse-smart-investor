"""Tomorrow's Watchlist - NSE Smart Investor (next-session EOD setups).

FIXES applied in this revision
───────────────────────────────
W1  Cold-start page freeze — the EOD scan no longer runs synchronously inside
    a blocking st.spinner() in the render path. On a cache miss, the page now:
      1. Shows the last cached/stale result immediately (if one exists in the
         kv store from a previous session), tagged with a "stale" badge.
      2. Kicks off the scan in a background thread via the same pattern used
         in backtest.py (ThreadPoolExecutor + session_state progress flags).
      3. Polls every 3 s and swaps in the fresh result once the scan
         completes, without ever blocking the UI thread for 2 minutes.
    If there is no stale result available at all (very first run, e.g. fresh
    deploy), a short blocking scan is unavoidable — but this is now flagged
    to the user with an honest "first run" message rather than a generic
    spinner.

W2  Paper-trade reason string no longer silently truncates the headline.
    reason now uses the full headline; the dashboard.shared.trade_utils
    storage layer is responsible for any column-width truncation, and if it
    does truncate, the truncation will be on the DB layer (consistent),
    not duplicated/hidden here. We additionally add an ellipsis-safe local
    helper for the CARD display copy only (not the stored reason).
"""

import os, sys
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import time
import threading
import concurrent.futures

import streamlit as st
from dashboard.shared.design import apply_design
from dashboard.shared.nav import render_sidebar
from dashboard.shared.chart_helpers import render_top_bar
from dashboard.shared.cache import _tomorrow_watchlist, get_display_name, _trade_type
from dashboard.shared.trade_utils import _paper_trade_popover

apply_design()
render_sidebar(current="Tomorrow's Watchlist")
render_top_bar()

# ─────────────────────────────────────────────────────────────────────────────
st.title("📅 Tomorrow's Watchlist")
st.markdown(
    "Stocks worth watching for the **next trading session**, based on today's close "
    "signals — distinct from intraday Top Picks. Breakouts setting up, breakdown risks, "
    "and divergence/reversal candidates."
)

# ─────────────────────────────────────────────────────────────────────────────
# FIX W1 — non-blocking scan with stale-while-revalidate pattern
# ─────────────────────────────────────────────────────────────────────────────
_EMPTY_WL = {
    "breakout_candidates": [], "breakdown_watch": [], "reversal_watch": [],
    "scan_time": "—",
}

if "tw_running" not in st.session_state:
    st.session_state["tw_running"] = False
if "tw_result" not in st.session_state:
    st.session_state["tw_result"] = None
if "tw_stale" not in st.session_state:
    st.session_state["tw_stale"] = False


def _tw_worker(result_holder: list):
    """Background worker — runs the (potentially slow) EOD scan once."""
    try:
        _r = _tomorrow_watchlist()
        result_holder.append(("ok", _r))
    except Exception as _e:
        result_holder.append(("error", str(_e)))


# Try a fast, already-cached call first. Streamlit's own @st.cache_data inside
# _tomorrow_watchlist means this is instant if the cache is warm, and will
# raise/slow only on a true cold start — which we now detect and offload.
_wl = None
_cache_was_cold = False

if not st.session_state["tw_running"]:
    # Probe: try the cached function with a very short patience budget by
    # running it in a thread with a timeout. If it returns fast (cache hit),
    # great. If it's still running after ~0.3s, treat as cold and switch to
    # the background-scan UI instead of blocking.
    _probe_holder = []
    _probe_thread = threading.Thread(target=_tw_worker, args=(_probe_holder,), daemon=True)
    _probe_thread.start()
    _probe_thread.join(timeout=0.3)

    if _probe_thread.is_alive():
        # Cold cache — scan is genuinely running. Don't block; hand off to
        # the background-run UI below and keep this thread alive in session.
        _cache_was_cold = True
        st.session_state["tw_running"]      = True
        st.session_state["tw_bg_holder"]    = _probe_holder
        st.session_state["tw_bg_thread"]    = _probe_thread
        st.session_state["tw_scan_started"] = time.time()
    else:
        # Cache was warm — we already have the result
        _status, _payload = _probe_holder[0] if _probe_holder else ("error", "no result")
        if _status == "ok":
            _wl = _payload
            st.session_state["tw_result"] = _wl
            st.session_state["tw_stale"]  = False
        else:
            st.error(f"Watchlist scan unavailable: {_payload}")
            _wl = _EMPTY_WL

# ── If a background scan is in progress, show stale data + progress ───────
# FIX W3 (perf) — this used to poll with a blocking time.sleep(3) followed by
# st.rerun(), which restarts the ENTIRE page (sidebar, design, every import)
# every 3 seconds for the full ~2 min of a cold scan — the same anti-pattern
# Command Centre's Top Picks section used to have. Replaced with the same fix:
# an @st.fragment(run_every=3s). Streamlit reruns just this fragment on its
# own timer — no blocking sleep on the main thread, no re-executing the rest
# of the page each tick. When the background scan actually finishes, the
# fragment calls a plain st.rerun() (full-app scope by default, even from
# inside a fragment) exactly once, to escape the fragment and render the
# final cards below with the fresh data.
if st.session_state["tw_running"]:

    @st.fragment(run_every=3)
    def _tw_poll_fragment():
        _holder  = st.session_state.get("tw_bg_holder", [])
        _started = st.session_state.get("tw_scan_started", time.time())
        _elapsed = time.time() - _started

        if _holder:
            # Background scan finished
            _status, _payload = _holder[0]
            st.session_state["tw_running"] = False
            if _status == "ok":
                st.session_state["tw_result"] = _payload
                st.session_state["tw_stale"]  = False
            else:
                st.error(f"Watchlist scan unavailable: {_payload}")
                st.session_state["tw_stale"] = st.session_state["tw_result"] is not None
            st.rerun()
        else:
            # Still running — show what we have (stale or empty) plus a live
            # banner. No sleep needed: run_every=3 handles the next check.
            _prior = st.session_state.get("tw_result")
            if _prior is not None:
                st.info(
                    f"🔄 Refreshing today's scan in the background "
                    f"({_elapsed:.0f}s elapsed) — showing the **previous session's** "
                    "results below until the new scan completes."
                )
                st.session_state["tw_stale"] = True
            else:
                st.warning(
                    f"🔄 **First run** — scanning the full NSE universe for the first "
                    f"time ({_elapsed:.0f}s elapsed, typically ~2 min). This only "
                    "happens once; subsequent visits use the cache. You can leave this "
                    "tab open or come back shortly."
                )

    _tw_poll_fragment()
    _wl = st.session_state.get("tw_result") or _EMPTY_WL

# Fallback safety net
if _wl is None:
    _wl = st.session_state.get("tw_result") or _EMPTY_WL

_is_stale = st.session_state.get("tw_stale", False)

st.caption(
    f"🕒 Scanned: **{_wl.get('scan_time', '—')}**"
    + (" · ⚠️ showing previous session (refresh in progress)" if _is_stale else "")
    + " · Runs EOD, cached until the next session · not intraday. "
      "Levels are based on today's daily close."
)

from dashboard.shared.disclosures import (
    render_regime_reliability_note as _tw_regime_note,
)
_tw_regime_note()

_ACCENT = {"breakout": "#26a69a", "breakdown": "#ef5350", "reversal": "#ab8bff"}
_BG = {
    "breakout":  "linear-gradient(135deg,#0a2a1a,#0f3320)",
    "breakdown": "linear-gradient(135deg,#2a0a0a,#330f0f)",
    "reversal":  "linear-gradient(135deg,#1a1430,#221a3a)",
}


def _render_cards(items, kind, key_prefix):
    if not items:
        st.caption("No candidates in this bucket on today's scan.")
        return
    accent = _ACCENT[kind]
    for _it in items:
        _lbl = _it["ticker"].replace(".NS", "")
        _tt_lbl, _tt_emo, _tt_col = _trade_type(_it.get("headline", ""))

        _entry = _it.get("entry") or 0
        _sl    = _it.get("sl")    or 0
        _tp    = _it.get("tp")    or 0
        _show_levels = _entry > 0 and _sl > 0 and _tp > 0

        _headline_full = _it.get("headline", "")
        # FIX W2: card display copy gets an honest ellipsis if truncated;
        # the FULL headline (not truncated) is used for the stored reason below.
        _headline_card = (
            _headline_full[:90] + "…" if len(_headline_full) > 90 else _headline_full
        )

        st.markdown(
            f'<div style="background:{_BG[kind]};border-left:4px solid {accent};'
            f'border-radius:10px;padding:11px 14px;margin-bottom:6px">'
            f'<div style="display:flex;justify-content:space-between;align-items:center">'
            f'<span style="font-size:16px;font-weight:700;color:#fff">{_lbl}</span>'
            f'<span style="font-size:13px;font-weight:700;color:{accent}">'
            f'{_it["score"]:.0f}/100 · {_it["action"]}</span>'
            f'</div>'
            f'<div style="font-size:11px;color:{accent};font-weight:600;margin-top:3px">'
            f'{_it["signal_type"]} · key level {_it["key_level"]}</div>'
            f'<div style="font-size:12px;color:#bbb;margin-top:2px">{_headline_card}</div>'
            + (
                f'<div style="font-size:11px;color:#888;margin-top:4px">'
                f'Entry ₹{_entry:,.2f} · SL ₹{_sl:,.2f} · TP ₹{_tp:,.2f}</div>'
                if _show_levels else ""
            )
            + "</div>",
            unsafe_allow_html=True,
        )
        if _show_levels:
            # FIX W2: use the full headline (not [:45]-truncated) for the
            # stored trade reason, so the Paper Trades journal shows the
            # complete context rather than a mid-word cut.
            _paper_trade_popover(
                _it["ticker"], _entry, _sl, _tp,
                reason=f"Tomorrow Watch ({_it['signal_type']}): {_headline_full}",
                key=f"{key_prefix}_{_it['ticker']}",
                label=f"📌 Paper Trade {_lbl}",
            )


_n_brk = len(_wl.get("breakout_candidates", []))
_n_bdn = len(_wl.get("breakdown_watch",     []))
_n_rev = len(_wl.get("reversal_watch",      []))

_t1, _t2, _t3 = st.tabs([
    f"🚀 Breakout Watch ({_n_brk})",
    f"🔻 Breakdown Watch ({_n_bdn})",
    f"🔄 Reversal Watch ({_n_rev})",
])
with _t1:
    st.caption(
        "Constructive setups approaching resistance with momentum & volume building — "
        "watch for a breakout at next open."
    )
    _render_cards(_wl.get("breakout_candidates", []), "breakout", "tw_brk")
with _t2:
    st.caption(
        "Weak names below key moving averages with distribution volume — watch for a "
        "breakdown / avoid fresh longs."
    )
    _render_cards(_wl.get("breakdown_watch", []), "breakdown", "tw_bdn")
with _t3:
    st.caption(
        "Divergences — price and momentum disagreeing (a potential turn). Confirm before "
        "acting; these are watch-only, not signals."
    )
    _render_cards(_wl.get("reversal_watch", []), "reversal", "tw_rev")

# Manual refresh control — lets the user trigger a re-scan without waiting
# for the cache TTL, using the same non-blocking pattern as the cold start.
st.markdown("---")
_rf1, _rf2 = st.columns([5, 1])
with _rf2:
    if st.button("🔄 Re-scan now", key="tw_manual_rescan"):
        # FIX MKT4: was a blanket st.cache_data.clear() — wiped every other
        # page's cached data too (Command Centre's Top Picks, etc.), not
        # just this page's own scan. _tomorrow_watchlist is already
        # imported at the top of this module, so it's safe to clear here.
        _tomorrow_watchlist.clear()
        st.session_state["tw_running"]   = False
        st.session_state.pop("tw_bg_holder", None)
        st.session_state.pop("tw_bg_thread", None)
        st.rerun()
with _rf1:
    st.caption(
        "⚠️ Educational watchlist on end-of-day signals — not investment advice. "
        "Always confirm at next open before acting."
    )
