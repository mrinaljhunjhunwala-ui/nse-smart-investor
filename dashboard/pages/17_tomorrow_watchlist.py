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
from dashboard.shared.cache import (
    _tomorrow_watchlist, get_tomorrow_watchlist, get_display_name, _trade_type,
)
from dashboard.shared.trade_utils import _display_label, _paper_trade_popover
from dashboard.shared.flags_ui import render_flag_badge_html  # QF2: shortlist-only flag badge
from dashboard.shared.ui_components import chip_pill, chip_delta

apply_design()
render_sidebar(current="Tomorrow's Watchlist")
render_top_bar()

# ─────────────────────────────────────────────────────────────────────────────
st.markdown('<h1 class="page-title-serif">Tomorrow\'s <em>Watchlist</em></h1>', unsafe_allow_html=True)
st.markdown(
    "Stocks worth watching for the **next trading session**, based on today's close "
    "signals — distinct from intraday Top Picks. Breakouts setting up, breakdown risks, "
    "and divergence/reversal candidates."
)

# FIX SCR-XREF — see the matching note in 06_smart_screener.py.
with st.expander("↔️ Also see: Smart Screener · TQS Scanner", expanded=False):
    st.markdown(
        "- **Smart Screener** — run the same 4-screen scan interactively with your "
        "own universe / parameters. Use when this pre-computed list doesn't have "
        "what you're after.\n"
        "- **TQS Scanner** — a *different* scoring engine (four-pillar Trend "
        "Quality Score) applied to the same universes. Cross-check a shortlisted "
        "name against its TQS reading before acting."
    )

# ── UI/UX 2026-09 · Task 4.2 β · yesterday's-picks follow-through strip ─────
# Data-unblocked 2026-09-15: ledger has accumulated >1 week of
# source="tomorrow_watchlist" rows since the writes started in PR #65
# on 2026-09-07. The strip solves user complaint: "scanning the full
# table takes too long to tell the stock names". Reads verdict_ledger
# with the backfilled forward returns so no live-price fetch is needed.
try:
    from analysis.verdict_ledger import load_ledger as _yp_load_ledger
    _yp_df = _yp_load_ledger(source="tomorrow_watchlist", limit=40)
    if _yp_df is not None and not _yp_df.empty:
        # Take the most recent row per ticker, up to 5
        _yp_df = _yp_df.sort_values("logged_at", ascending=False)
        _yp_seen: set = set()
        _yp_rows: list = []
        for _r in _yp_df.itertuples():
            _tk = getattr(_r, "ticker", None)
            if not _tk or _tk in _yp_seen:
                continue
            _yp_seen.add(_tk)
            _yp_rows.append(_r)
            if len(_yp_rows) >= 5:
                break
        if _yp_rows:
            _yp_cards_html = []
            for _idx, _r in enumerate(_yp_rows, start=1):
                _sym    = str(getattr(_r, "ticker", "?")).replace(".NS", "")
                _sc     = float(getattr(_r, "score", 0) or 0)
                _act    = str(getattr(_r, "action", "") or "").strip()
                _ret1   = getattr(_r, "ret_1d", None)
                _ret5   = getattr(_r, "ret_5d", None)
                _ret20  = getattr(_r, "ret_20d", None)
                _r_shown = _ret1 if _ret1 is not None else (
                           _ret5 if _ret5 is not None else _ret20)
                _r_label = ("1D" if _ret1 is not None else
                            "5D" if _ret5 is not None else
                            "20D" if _ret20 is not None else "—")
                # Follow-through pill from forward return — routed through
                # chip_pill/chip_delta so every posture chip in the app uses
                # the same vocabulary (see docs/UI_UX_DESIGN_2026-09.md §4).
                if _r_shown is None:
                    _pill_tone, _pill_txt = "neutral", "Pending"
                    _card_bg = "var(--surface)"
                    _card_bd = "var(--hairline)"
                elif _r_shown >= 0.02:
                    _pill_tone, _pill_txt = "good", "Working"
                    _card_bg = "linear-gradient(180deg,rgba(22,199,132,.06),var(--surface) 80%)"
                    _card_bd = "rgba(22,199,132,.3)"
                elif _r_shown <= -0.02:
                    _pill_tone, _pill_txt = "bad", "Stopped"
                    _card_bg = "linear-gradient(180deg,rgba(255,77,77,.06),var(--surface) 80%)"
                    _card_bd = "rgba(255,77,77,.25)"
                else:
                    _pill_tone, _pill_txt = "warn", "Flat"
                    _card_bg = "var(--surface)"
                    _card_bd = "var(--hairline)"
                _ret_html = (
                    chip_delta(_r_shown * 100)
                    if _r_shown is not None else
                    '<span style="color:var(--faint);font-size:11px">no data yet</span>'
                )
                _pill_html = chip_pill(_pill_txt, tone=_pill_tone)
                _yp_cards_html.append(
                    f'<div style="background:{_card_bg};border:1px solid {_card_bd};'
                    f'border-radius:6px;padding:12px 14px;position:relative;overflow:hidden">'
                    f'<div style="position:absolute;top:9px;right:12px;'
                    f'font-family:var(--font-mono);font-size:10px;color:var(--faint);'
                    f'letter-spacing:.08em">RANK {_idx:02d}</div>'
                    f'<div style="font-weight:600;font-size:14px;color:var(--ink);'
                    f'letter-spacing:-.005em">{_sym}</div>'
                    f'<div style="color:var(--dim);font-size:11px;margin-top:1px">'
                    f'Score {_sc:.0f}/90 · {_act or "logged"}</div>'
                    f'<div style="display:flex;justify-content:space-between;'
                    f'align-items:baseline;margin-top:10px;padding-top:8px;'
                    f'border-top:1px dotted var(--hairline)">'
                    f'<span style="color:var(--dim);font-size:10px;'
                    f'text-transform:uppercase;letter-spacing:.08em">{_r_label} ret</span>'
                    f'{_ret_html}</div>'
                    f'<div style="margin-top:9px">{_pill_html}</div>'
                    f'</div>'
                )
            st.markdown(
                '<div style="margin:14px 0 6px 0;display:flex;'
                'justify-content:space-between;align-items:baseline">'
                '<h3 style="margin:0;font-family:\'Instrument Serif\',Georgia,serif;'
                'font-weight:400;font-size:20px;letter-spacing:-.01em;color:var(--ink)">'
                'Yesterday\'s picks · follow-through</h3>'
                f'<span style="font-size:10px;color:var(--faint);'
                'text-transform:uppercase;letter-spacing:.1em;'
                'font-family:var(--font-mono)">source: verdict_ledger · '
                f'{len(_yp_rows)} shown</span>'
                '</div>',
                unsafe_allow_html=True,
            )
            st.markdown(
                '<div style="display:grid;grid-template-columns:repeat(5,1fr);'
                'gap:10px;margin-bottom:22px">'
                + "".join(_yp_cards_html)
                + '</div>',
                unsafe_allow_html=True,
            )
except Exception as _yp_err:
    import logging
    logging.getLogger("dashboard.tomorrow_watchlist").debug(
        "yesterday's-picks strip render failed: %s", _yp_err)

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
    """Background worker — runs the (potentially slow) EOD scan once.
    FIX W-SPEED: calls get_tomorrow_watchlist() (snapshot-aware) rather than
    _tomorrow_watchlist() directly, so a fresh pre-warmed snapshot (written
    by scripts/warm_tomorrow_watchlist.py) is read instantly instead of this
    page unconditionally re-running its own live scan."""
    try:
        _r = get_tomorrow_watchlist()
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
# DT1 + DT2 · scan-time attribution with the source pill.
try:
    from dashboard.shared.ui_components import data_as_of as _tw_asof
    _tw_when = str(_wl.get("scan_time") or "unknown")
    st.markdown(
        _tw_asof(_tw_when, source="yfinance",
                 ttl_hint="EOD scan cached until next session"),
        unsafe_allow_html=True,
    )
except Exception:
    pass

from dashboard.shared.disclosures import (
    render_regime_reliability_note as _tw_regime_note,
)
_tw_regime_note()

_ACCENT = {"breakout": "var(--bull)", "breakdown": "var(--bear)", "reversal": "var(--violet)"}


def _card_bg(tok: str) -> str:
    """Dark tinted card gradient: token hue blended into the ground surface."""
    return (f"linear-gradient(135deg,color-mix(in srgb, var(--{tok}) 12%, var(--ground)),"
            f"color-mix(in srgb, var(--{tok}) 17%, var(--ground)))")


_BG = {"breakout": _card_bg("bull"), "breakdown": _card_bg("bear"), "reversal": _card_bg("violet")}


def _render_cards(items, kind, key_prefix):
    if not items:
        st.caption("No candidates in this bucket on today's scan.")
        return
    accent = _ACCENT[kind]
    # Task 4.2 PR beta (audit docs/TOMORROW_WATCHLIST_AUDIT_2026-09.md, FM2
    # follow-up): rank prefix so a user reading a card can tell at a glance
    # whether this is the #1 conviction pick of the bucket or #15 of 15.
    # Items already arrive sorted by _tomorrow_watchlist (desc score for
    # breakout / reversal, asc for breakdown) so enumerate() from 1 is the
    # displayed rank directly.
    for _idx, _it in enumerate(items, start=1):
        _lbl = _it["ticker"].replace(".NS", "")
        _rank_chip = (
            f'<span style="display:inline-block;padding:1px 6px;border-radius:4px;'
            f'font-size:10px;font-weight:700;font-family:var(--font-mono, ui-monospace);'
            f'letter-spacing:0.3px;color:{accent};'
            f'background:color-mix(in srgb, {accent} 14%, transparent);'
            f'border:1px solid color-mix(in srgb, {accent} 40%, transparent);'
            f'margin-right:8px">#{_idx}</span>'
        )
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

        # FIX HZ1-WL: holding-period label — already computed by score_stock()
        # for every stock (see analysis/score.py's _pick_horizon), just wasn't
        # threaded through this page before. Answers "how long is this setup
        # good for" directly on the card instead of leaving it unclear.
        _horizon = _it.get("horizon", "")
        _valid_until = _it.get("valid_until", "")

        # QF2: qualitative flag badge — safe to call here because this is
        # the already-shortlisted, already-ranked list (≤15 items/bucket),
        # NOT the wide universe scan. Never call this inside the scan pass
        # in dashboard/shared/cache.py — see flags_ui.py docstring for why.
        try:
            _flag_badge = render_flag_badge_html(_it["ticker"])
        except Exception:
            _flag_badge = ""

        # Task 4.2 M2 (audit docs/TOMORROW_WATCHLIST_AUDIT_2026-09.md): show
        # an honest conviction chip based on the composite score band, so a
        # card's visible label matches what the score actually says instead
        # of promising more than the number supports. Bands match the
        # composite-score grade thresholds elsewhere in the app.
        _sc = float(_it.get("score", 0) or 0)
        if _sc >= 70:
            _conv_label, _conv_col = "high conviction", "var(--bull)"
        elif _sc >= 55:
            _conv_label, _conv_col = "developing", "var(--amber)"
        else:
            _conv_label, _conv_col = "watch only", "var(--dim)"
        _conv_chip = (
            f'<span style="display:inline-block;padding:1px 7px;border-radius:999px;'
            f'font-size:10px;font-weight:700;letter-spacing:0.4px;text-transform:uppercase;'
            f'color:{_conv_col};border:1px solid {_conv_col};'
            f'background:color-mix(in srgb, {_conv_col} 12%, transparent);'
            f'margin-left:6px">{_conv_label}</span>'
        )

        st.markdown(
            f'<div style="background:{_BG[kind]};border-left:4px solid {accent};'
            f'border-radius:10px;padding:11px 14px;margin-bottom:6px">'
            f'<div style="display:flex;justify-content:space-between;align-items:center">'
            f'<span style="font-size:16px;font-weight:700;color:var(--ink)">{_rank_chip}{_lbl}{_conv_chip}</span>'
            f'<span style="font-size:13px;font-weight:700;color:{accent}">'
            f'{_it["score"]:.0f}/90 · {_display_label(_it["action"])}</span>'
            f'</div>'
            f'{_flag_badge}'
            f'<div style="font-size:11px;color:{accent};font-weight:600;margin-top:3px">'
            f'{_it["signal_type"]} · key level {_it["key_level"]}</div>'
            f'<div style="font-size:12px;color:var(--ink-mid);margin-top:2px">{_headline_card}</div>'
            + (
                f'<div style="font-size:11px;color:var(--dim);margin-top:2px">'
                f'⏳ {_horizon}' + (f' · fresh until {_valid_until}' if _valid_until else '')
                + '</div>'
                if _horizon else ""
            )
            + (
                f'<div style="font-size:11px;color:var(--dim);margin-top:4px">'
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
            _btn_col1, _btn_col2 = st.columns([1, 1])
            with _btn_col1:
                _paper_trade_popover(
                    _it["ticker"], _entry, _sl, _tp,
                    reason=f"Tomorrow Watch ({_it['signal_type']}): {_headline_full}",
                    key=f"{key_prefix}_{_it['ticker']}",
                    label=f"📌 Paper Trade {_lbl}",
                )
            with _btn_col2:
                # FIX NAV-TW: this page had no way to jump into the full
                # Analyze Stock view at all — same canonical handoff used on
                # My Portfolio / Command Centre / Quality Watch (FIX NAV1).
                if st.button(f"📊 Analyze {_lbl}", key=f"{key_prefix}_{_it['ticker']}_analyze",
                             width="stretch"):
                    st.session_state["analyze_ticker"] = _it["ticker"]
                    st.session_state["_goto_page"] = "🔍 Analyze Stock"
                    st.rerun()
        else:
            # No valid entry/SL/TP to paper-trade on, but Analyze is still useful.
            if st.button(f"📊 Analyze {_lbl}", key=f"{key_prefix}_{_it['ticker']}_analyze_only",
                         width="stretch"):
                st.session_state["analyze_ticker"] = _it["ticker"]
                st.session_state["_goto_page"] = "🔍 Analyze Stock"
                st.rerun()


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
        "potential breakdown."
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
