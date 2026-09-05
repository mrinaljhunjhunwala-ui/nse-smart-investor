"""Command Centre - NSE Smart Investor (multipage page; body verbatim from app.py)."""
import os
import sys
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import threading
import pandas as pd
import streamlit as st
import trade_store as _store

from dashboard.shared.design import apply_design
from dashboard.shared.nav import render_sidebar
from dashboard.shared.picks_ui import render_pick_analysis
from dashboard.shared.chart_helpers import render_top_bar
from dashboard.shared.cache import (
    get_top_picks,
    _persisted_top_picks_snapshot,   # FIX TP-FAST1 / FIX TP-NOOP1
    _top_picks_ticker,
    _score_watchlist,
    _sector_ranks_tuple,
    _sparkline_closes,
    _sparkline_svg,
    _trade_type,
    _picks_live_prices,     # FIX CC-LIVE1
    _horizon_countdown,     # FIX CC-LIVE1
    get_vix_info,
)
from dashboard.shared.trade_utils import (
    _auto_close_breached,
    _display_label,            # Phase 2 UI honesty
    _is_squareoff_time,
    _paper_trade_popover,
    _portfolio_live_prices,
    _render_autoclose_banner,
    paper_close_trade,
)

apply_design()
render_sidebar(current="Command Centre")
render_top_bar()

# ───────────────────────── page body (de-indented from app.py) ─────────────────────────
st.title("Command Centre")

# ── FIX REGIME-CHIP1 - v2 scoring badge (Rec 5 / Task 3.6 flag on) ─────────
# When NSE_USE_REGIME_WEIGHTS is truthy, the Momentum pillar swaps in the
# 5-day mean-reversion percentile (Var M) on bear-regime days. Surface a
# small chip so the user knows they are seeing v2 scoring, not legacy.
# Deferred item from docs/REGIME_WEIGHTS_2026-09.md:93; now landed alongside
# the default flip authorised by docs/REGIME_WEIGHTS_VALIDATION.md.
_v2_flag = os.environ.get("NSE_USE_REGIME_WEIGHTS", "").strip().lower() in {"1", "true", "yes", "on"}
if _v2_flag:
    st.markdown(
        '<div style="margin:-6px 0 10px 0">'
        '<span style="display:inline-flex;align-items:center;gap:6px;'
        'padding:3px 10px;border-radius:999px;font-size:11px;font-weight:700;'
        'letter-spacing:0.4px;text-transform:uppercase;'
        'background:color-mix(in srgb, var(--bull) 14%, transparent);color:var(--bull);'
        'border:1px solid var(--bull)">'
        '<span style="width:6px;height:6px;border-radius:50%;background:var(--bull)"></span>'
        'v2 scoring active'
        '</span>'
        '<span style="margin-left:8px;font-size:11px;color:var(--dim)">'
        'Momentum pillar dispatches to mean-reversion in bear regimes '
        '(Rec 5 · <code style="font-size:10px">NSE_USE_REGIME_WEIGHTS=1</code>)'
        '</span></div>',
        unsafe_allow_html=True,
    )

st.caption("Market conditions · open positions needing action · watchlist decisions — no digging required.")

# ── 0. MORNING SUMMARY CARD — your daily brief ─────────────────────────────
import datetime as _mb_dt
_mb_now   = _mb_dt.datetime.now(_mb_dt.timezone(_mb_dt.timedelta(hours=5, minutes=30)))
_mb_greet = ("Good morning" if _mb_now.hour < 12 else
             "Good afternoon" if _mb_now.hour < 17 else "Good evening")
_mb_date  = _mb_now.strftime("%A, %d %b %Y · %H:%M IST")
_mb_open  = 0
try:
    import trade_store as _mb_ts
    _mbo = _mb_ts.fetch_open()
    _mb_open = 0 if (_mbo is None or _mbo.empty) else len(_mbo)
except Exception as _e:
    st.caption(f"⚠️ Couldn't read open paper positions ({_e}) — showing 0.")
_mb_reg = get_vix_info().get("regime", "normal")
_mb_focus = {
    "panic":       ("🚨", "Panic — protect capital, avoid new buys"),
    "fear":        ("🔴", "Fearful — be defensive, small sizes only"),
    "elevated":    ("🟠", "Elevated volatility — only high-conviction setups"),
    "normal":      ("🟢", "Calm conditions — trade your setups normally"),
    "complacency": ("😴", "Very calm — tighten stops, stay selective"),
}.get(_mb_reg, ("•", "Trade your plan"))
_mb_pos_txt = (f"You have <b style='color:var(--amber)'>{_mb_open}</b> open paper position"
               f"{'s' if _mb_open != 1 else ''}." if _mb_open else
               "No open paper positions.")
st.markdown(
    f'<div class="glass-panel" style="margin-bottom:14px;display:flex;'
    f'justify-content:space-between;align-items:center;flex-wrap:wrap;gap:12px">'
    f'<div><div style="font-size:20px;font-weight:800;color:var(--ink)">☀️ {_mb_greet}, Mrinal</div>'
    f'<div style="font-size:12px;color:var(--dim);margin-top:2px">{_mb_date}</div></div>'
    f'<div style="text-align:right">'
    f'<div style="font-size:13px;color:var(--ink-mid)">{_mb_focus[0]} {_mb_focus[1]}</div>'
    f'<div style="font-size:12px;color:var(--dim);margin-top:3px">{_mb_pos_txt} '
    f'Scroll for today\'s picks &amp; watchlist.</div></div>'
    f'</div>',
    unsafe_allow_html=True,
)

# ── 0b. PAPER TRADES OVERVIEW (quick view) ─────────────────────────────────
try:
    import trade_store as _pto_ts
    _pto_open  = _pto_ts.fetch_open()
    _pto_accts = _pto_ts.list_accounts()
    _pto_all   = (pd.concat([_pto_ts.load_by_account(_a) for _a in _pto_accts],
                            ignore_index=True)
                  if _pto_accts else pd.DataFrame())

    _pto_n = 0 if (_pto_open is None or _pto_open.empty) else len(_pto_open)

    _pto_unreal = 0.0
    if _pto_n:
        _pto_syms = tuple(_pto_open["ticker"].tolist())
        _pto_lp   = _portfolio_live_prices(_pto_syms)
        for _, _por in _pto_open.iterrows():
            _pep = float(_por.get("price", 0) or 0)
            _pqt = int(_por.get("quantity", 0) or 0)
            _pcur = _pto_lp.get(str(_por["ticker"]), {}).get("price", _pep)
            _pto_unreal += (_pcur - _pep) * _pqt

    _pto_real, _pto_wins, _pto_tot = 0.0, 0, 0
    if not _pto_all.empty and "status" in _pto_all.columns:
        _pto_closed = _pto_all[_pto_all["status"].isin(["CLOSED", "STOPPED"])]
        if not _pto_closed.empty and "pnl" in _pto_closed.columns:
            _pnl_series = _pto_closed["pnl"].fillna(0)
            _pto_real = float(_pnl_series.sum())
            _pto_tot  = int(len(_pto_closed))
            _pto_wins = int((_pnl_series > 0).sum())
    _pto_wr = (_pto_wins / _pto_tot * 100) if _pto_tot else 0.0

    # Task 1.3: this block used a bespoke _pto_cell helper + a raw
    # .glass-panel wrapper with drifting hex ("var(--ink)", "var(--faint)",
    # "var(--faint)", "var(--dim)"). Migrated to the shared panel() + stat()
    # components so it renders in the same visual language as every
    # other card in the app and pulls color from CSS custom properties.
    from dashboard.shared.ui_components import panel as _panel, stat as _stat
    _u_tone = "bull" if _pto_unreal >= 0 else "bear"
    _r_tone = "bull" if _pto_real   >= 0 else "bear"
    _wr_tone = ("bull" if _pto_wr >= 50 else
                "amber" if _pto_wr >= 35 else "bear")
    _pto_body = (
        '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));'
        'gap:14px 22px">'
        + _stat("Open Positions", f"{_pto_n}", tone="neutral", align="center")
        + _stat("Unrealised P&amp;L", f"Rs.{_pto_unreal:+,.0f}",
                sub="live prices", tone=_u_tone, align="center")
        + _stat("Realised P&amp;L", f"Rs.{_pto_real:+,.0f}",
                sub=f"{_pto_tot} closed", tone=_r_tone, align="center")
        + _stat("Win Rate", f"{_pto_wr:.0f}%",
                sub=(f"{_pto_wins}/{_pto_tot} wins" if _pto_tot else "no closed trades"),
                tone=_wr_tone, align="center")
        + '</div>'
    )
    st.markdown(
        _panel(_pto_body, kind="glass", tone="neutral",
               title="Paper Trades Overview", margin="0 0 14px 0"),
        unsafe_allow_html=True,
    )
except Exception as _pto_e:
    st.caption(f"⚠️ Paper trades overview unavailable ({_pto_e}).")

# ── 1. MARKET PULSE ────────────────────────────────────────────────────────
_cc_vix_info = get_vix_info()
_cc_vix_r = _cc_vix_info.get("regime", "unknown").lower()
_cc_vix_v = _cc_vix_info.get("vix")

_cc_nifty_trend = "unknown"
_cc_nifty_val   = None
_cc_nifty_5d    = 0.0
try:
    from data.fetcher import fetch_single as _cc_fs
    _cc_ndf = _cc_fs("^NSEI", period="3mo")
    if not _cc_ndf.empty:
        _cc_nifty_val = float(_cc_ndf["Close"].iloc[-1])
        _cc_nifty_5d  = float((_cc_ndf["Close"].iloc[-1] / _cc_ndf["Close"].iloc[-6] - 1) * 100) if len(_cc_ndf) >= 6 else 0
        _cc_sma20 = float(_cc_ndf["Close"].rolling(20).mean().iloc[-1]) if len(_cc_ndf) >= 20 else _cc_nifty_val
        _cc_sma50 = float(_cc_ndf["Close"].rolling(50).mean().iloc[-1]) if len(_cc_ndf) >= 50 else _cc_nifty_val
        if _cc_nifty_val > _cc_sma20 and _cc_sma20 > _cc_sma50:
            _cc_nifty_trend = "uptrend"
        elif _cc_nifty_val < _cc_sma20 and _cc_sma20 < _cc_sma50:
            _cc_nifty_trend = "downtrend"
        else:
            _cc_nifty_trend = "sideways"
except Exception as _e:
    st.caption(f"⚠️ Couldn't load Nifty trend ({_e}) — market pulse may be incomplete.")

_VIX_LBL = {
    "complacency": ("var(--amber)", "😴", "COMPLACENT"), "normal":  ("var(--bull)", "🟢", "CALM"),
    "elevated":    ("var(--amber)", "🟡", "ELEVATED"),   "fear":    ("var(--bear)", "🔴", "HIGH FEAR"),
    "panic":       ("var(--bear)", "🚨", "PANIC"),      "unknown": ("var(--dim)", "❓", "UNKNOWN"),
}
_NT_LBL = {
    "uptrend":  ("var(--bull)", "📈", "UPTREND"),  "downtrend": ("var(--bear)", "📉", "DOWNTREND"),
    "sideways": ("var(--amber)", "↔️", "SIDEWAYS"), "unknown":   ("var(--dim)", "❓", "NO DATA"),
}
_vc, _vi, _vl = _VIX_LBL.get(_cc_vix_r, _VIX_LBL["unknown"])
_nc, _ni, _nl = _NT_LBL.get(_cc_nifty_trend, _NT_LBL["unknown"])

if _cc_vix_r == "normal" and _cc_nifty_trend == "uptrend":
    _verd, _vbg, _vbdr = "✅ Good conditions — new positions okay", "var(--sunken)", "var(--bull)"
elif _cc_vix_r in ("fear", "panic") or _cc_nifty_trend == "downtrend":
    _verd, _vbg, _vbdr = "🔴 Weak / fearful market — avoid new buys, protect capital", "var(--sunken)", "var(--bear)"
elif _cc_vix_r == "complacency":
    _verd, _vbg, _vbdr = "😴 Market too calm — be selective, tighten stops", "var(--sunken)", "var(--amber)"
else:
    _verd, _vbg, _vbdr = "🟡 Mixed signals — only high-conviction setups today", "var(--sunken)", "var(--amber)"

st.markdown(
    f'<div style="display:flex;gap:12px;margin-bottom:4px">'
    f'<div style="flex:1;background:var(--surface);border-left:5px solid {_vc};border-radius:10px;padding:14px 16px">'
    f'<div style="font-size:10px;color:var(--dim);text-transform:uppercase;letter-spacing:1px;margin-bottom:3px">India VIX</div>'
    f'<div style="font-size:20px;font-weight:700;color:{_vc}">{_vi} {_vl}</div>'
    f'<div style="font-size:12px;color:var(--ink-mid);margin-top:3px">{f"{_cc_vix_v:.1f}" if _cc_vix_v else "—"}</div>'
    f'</div>'
    f'<div style="flex:1;background:var(--surface);border-left:5px solid {_nc};border-radius:10px;padding:14px 16px">'
    f'<div style="font-size:10px;color:var(--dim);text-transform:uppercase;letter-spacing:1px;margin-bottom:3px">Nifty 50</div>'
    f'<div style="font-size:20px;font-weight:700;color:{_nc}">{_ni} {_nl}</div>'
    f'<div style="font-size:12px;color:var(--ink-mid);margin-top:3px">'
    f'{f"{_cc_nifty_val:,.0f}" if _cc_nifty_val else "—"}'
    f'{f"&nbsp;({_cc_nifty_5d:+.1f}% 5d)" if _cc_nifty_val else ""}</div>'
    f'</div>'
    f'<div style="flex:2;background:{_vbg};border-left:5px solid {_vbdr};border-radius:10px;'
    f'padding:14px 16px;display:flex;align-items:center">'
    f'<div style="font-size:16px;font-weight:600;color:var(--ink)">{_verd}</div>'
    f'</div>'
    f'</div>',
    unsafe_allow_html=True,
)
_mood_vix = {"complacency": 85, "normal": 65, "elevated": 45,
             "fear": 22, "panic": 6, "unknown": 50}.get(_cc_vix_r, 50)
_mood_nty = {"uptrend": 80, "sideways": 50, "downtrend": 20,
             "unknown": 50}.get(_cc_nifty_trend, 50)
_mood = int(round((_mood_vix + _mood_nty) / 2))
if   _mood < 20: _mood_lbl, _mood_c = "Extreme Fear", "var(--bear)"
elif _mood < 40: _mood_lbl, _mood_c = "Fear", "var(--bear)"
elif _mood < 60: _mood_lbl, _mood_c = "Neutral", "var(--amber)"
elif _mood < 80: _mood_lbl, _mood_c = "Greed", "var(--bull)"
else:            _mood_lbl, _mood_c = "Extreme Greed", "var(--bull)"
st.markdown(
    f'<div style="background:var(--surface);border:1px solid rgba(255,255,255,.05);border-radius:10px;'
    f'padding:12px 18px;margin-top:8px;display:flex;align-items:center;gap:16px">'
    f'<div style="font-size:11px;color:var(--dim);text-transform:uppercase;letter-spacing:1px;min-width:96px">Market Mood</div>'
    f'<div style="flex:1;position:relative;height:10px;border-radius:6px;'
    f'background:linear-gradient(90deg,var(--bear),var(--bear),var(--amber),var(--bull),var(--bull))">'
    f'<div style="position:absolute;left:{_mood}%;top:-5px;transform:translateX(-50%);'
    f'width:20px;height:20px;border-radius:50%;background:{_mood_c};border:3px solid var(--surface);'
    f'box-shadow:0 0 8px {_mood_c}"></div></div>'
    f'<div style="min-width:130px;text-align:right">'
    f'<span style="font-size:20px;font-weight:800;color:{_mood_c}">{_mood}</span>'
    f'<span style="font-size:13px;color:{_mood_c};font-weight:600"> · {_mood_lbl}</span></div>'
    f'</div>',
    unsafe_allow_html=True,
)

_cc_ref_c = st.columns([6, 1])[1]
if _cc_ref_c.button("🔄 Refresh", key="cc_refresh_pulse", width="stretch"):
    # BUGFIX: this only needs to bust the VIX cache — the previous blanket
    # st.cache_data.clear() also wiped Top Picks (2-min cold scan), watchlist
    # scores, and sparklines, forcing expensive re-fetches the user never
    # asked for just to refresh the VIX/Nifty pulse panel.
    get_vix_info.clear()
    st.rerun()

# ─────────────────────────────────────────────────────────────────────────────
# FIX CC-REGIME — composite regime badge (Phase 2 wiring)
# The 5-year efficacy study established that the composite score's edge is
# regime-dependent: 62-66 % BUY hit rate on train (2020-22, trending), 46 %
# on holdout (2023-25, mean-reverting). Users need to see WHAT REGIME the
# app thinks the market is in RIGHT NOW so they can calibrate expectations
# on every BUY signal below. Fetches are cached at the classifier layer —
# no per-page-load network cost.
# ─────────────────────────────────────────────────────────────────────────────
try:
    @st.cache_data(ttl=1800, show_spinner=False)
    def _cc_regime_snapshot() -> "dict | None":
        from analysis.regime import snapshot_live
        try:
            snap = snapshot_live()
            return snap.as_dict()
        except Exception as _reg_e:
            import logging as _reg_log
            _reg_log.getLogger("dashboard.command_centre").debug(
                "regime snapshot failed: %s", _reg_e)
            return None

    # FIX UI-REGIME — inline regime banner replaced with the shared
    # dashboard.shared.ui_components.regime_badge so this page's regime
    # visual matches Analyze Stock and My Portfolio exactly. Removes ~20
    # lines of duplicated color/emoji/note tables — one source of truth.
    _cc_reg = _cc_regime_snapshot()
    if _cc_reg:
        from dashboard.shared.ui_components import regime_badge as _ui_regime_badge
        st.markdown(
            _ui_regime_badge(_cc_reg.get("label", "unknown"),
                             _cc_reg.get("confidence", "low"),
                             compact=False),
            unsafe_allow_html=True,
        )
except Exception as _cc_reg_e:
    import logging as _cc_reg_log
    _cc_reg_log.getLogger("dashboard.command_centre").debug(
        "regime banner render failed: %s", _cc_reg_e)

st.markdown("---")

# ═══════════════════════════════════════════════════════════════════════════
# ── 1b. TOP PICKS TICKER — scrolling ticker tape, separate from the cards ──
# ═══════════════════════════════════════════════════════════════════════════
# FIX (was "Suggestions Strip") — the old version had two real bugs:
#   1. It mixed the user's raw watchlist (which can be down on any given day)
#      with a few Top Picks candidates, so a strip meant to be "what's worth
#      a look" could show loss-making stocks — it was never actually
#      gainers-only, it was "whatever's on your watchlist".
#   2. It priced everything via trade_utils._portfolio_live_prices, which
#      fetches tickers one at a time in a for-loop (see FIX TU4 there), not
#      in parallel — real, measurable load-time cost.
#
# Replaced first with a NIFTY 50 gainers tape, then with FIX TP3: this strip
# now shows the app's own Top Picks BUY candidates (see _top_picks_ticker in
# cache.py) instead of a generic NIFTY 50 gainers feed — the same
# score-ranked list as the Buy Candidates cards below, priced live via ONE
# parallel batch call. Buys only, not filtered to today's gainers — a Top
# Pick can legitimately be flat or red today, so each chip is colour-coded
# red/green on its own live % change rather than assumed green. It's a real
# horizontal auto-scrolling marquee in a distinct black/teal theme (teal to
# match the Buy Candidates card accent, distinguishing it from the old
# black/amber NIFTY 50 theme) so it reads as a ticker tape, not another card
# section. Still its own @st.fragment(run_every=60) so it refreshes
# independently of the rest of the page. Purely informational (no
# click-through) — a scrolling tape isn't a natural fit for per-item
# buttons; the full Top Picks section below still offers the "click through
# to Analyze Stock" workflow.

@st.fragment(run_every=60)
def _render_top_picks_ticker() -> None:
    _tk_rows = _top_picks_ticker(n=12)

    if not _tk_rows:
        st.markdown(
            "<div style='background:var(--rail);border-top:2px solid var(--bull);"
            "border-bottom:2px solid var(--bull);border-radius:6px;padding:9px 16px;"
            "font-size:12px;color:var(--bull)'>🎯 TOP PICKS — no buy candidates "
            "right now.</div>",
            unsafe_allow_html=True,
        )
        return

    def _chip(_r: dict) -> str:
        _lbl = _r["ticker"].replace(".NS", "")
        _up  = (_r["chg_pct"] or 0) >= 0
        _cc  = "var(--bull)" if _up else "var(--bear)"
        _arr = "▲" if _up else "▼"
        return (
            f'<span style="display:inline-block;margin-right:34px;white-space:nowrap">'
            f'<span style="color:var(--ink-mid);font-weight:700;font-size:13px">{_lbl}</span>'
            f'<span style="color:var(--dim);font-size:12px"> ₹{_r["price"]:,.1f} </span>'
            f'<span style="color:{_cc};font-weight:700;font-size:13px">'
            f'{_arr}{abs(_r["chg_pct"]):.2f}%</span></span>'
        )

    # Content duplicated back-to-back so the marquee loops seamlessly at the
    # 50%-translateX halfway point (standard CSS ticker-tape technique).
    _tape_html = "".join(_chip(r) for r in _tk_rows) * 2

    st.markdown(
        f'<div style="background:var(--rail);border-top:2px solid var(--bull);'
        f'border-bottom:2px solid var(--bull);border-radius:6px;'
        f'display:flex;align-items:center;overflow:hidden">'
        f'<span style="flex-shrink:0;padding:9px 14px;color:var(--bull);'
        f'font-size:10px;font-weight:700;letter-spacing:1px;'
        f'border-right:1px solid var(--sunken);white-space:nowrap">'
        f'🎯 TOP PICKS<br>BUY CANDIDATES</span>'
        f'<div style="flex:1;overflow:hidden;position:relative;padding:9px 0">'
        f'<div style="white-space:nowrap;width:max-content;'
        f'animation:cc_ticker_scroll 32s linear infinite">'
        f'{_tape_html}'
        f'</div></div></div>'
        f'<style>@keyframes cc_ticker_scroll {{'
        f'0% {{ transform:translateX(0%); }} '
        f'100% {{ transform:translateX(-50%); }} }}</style>',
        unsafe_allow_html=True,
    )


_render_top_picks_ticker()

st.markdown("---")

# ═══════════════════════════════════════════════════════════════════════════
# ── 2. TODAY'S TOP PICKS — full NSE-wide scan, stale-while-revalidate ──────
# ═══════════════════════════════════════════════════════════════════════════
# FIX (blanking on rescan): the old version called _home_top_picks() inside
# `with st.spinner(...)`, directly on the page's normal script run. On a
# cache-miss (cold start, or the 5-min TTL expiring), that call blocks for
# ~2 minutes — and because the Top Picks section literally hasn't executed
# yet on this run, there is nothing to show: the previous cards aren't "still
# there", they just haven't been re-drawn, so the whole section reads as
# blank/spinner until the scan finishes.
#
# Fix: the entire section is now an @st.fragment(run_every=...) — Streamlit
# reruns ONLY this fragment on its own timer, not the whole page. The last
# good scan result is kept in st.session_state and rendered immediately on
# every fragment run, BEFORE checking whether a refresh is needed. If the
# cached result is stale, a background thread kicks off _home_top_picks()
# without blocking the render — so the existing cards stay exactly as they
# are (with a small "refreshing…" note) until the new scan lands, at which
# point the next fragment tick swaps them in. Nothing ever goes blank.
#
# Universe: this scans get_universe("niftytotalmarket") inside
# _home_top_picks — the full ~745-ticker liquid NSE list (Nifty 500 +
# Microcap 250), not a Nifty-50-only set. FIX TP2: previously scanned only
# the narrower "nifty500" (~504 tickers) set, which under-used the wider
# universe already built in data/universe.py.

_PICKS_KEY = "_cc_top_picks"
_PICKS_TTL_SECONDS = 300  # matches _home_top_picks' own cache TTL


def _picks_background_fetch(vix_regime: str, sector_ranks: tuple) -> None:
    """Runs in a worker thread. Only touches st.session_state — never calls
    st.* UI functions, which are not safe off the main script thread.

    FIX (stuck-scanning bug): a bare threading.Thread has no Streamlit
    ScriptRunContext attached. Touching st.session_state with no context
    raises NoSessionContext on modern Streamlit — and since BOTH the
    try-block writes AND the except-block's own write below would raise,
    the exception from the except handler itself goes unhandled and the
    thread dies silently (it's a daemon thread) before the `finally` ever
    runs. That left `_fetching` stuck True forever, so the fragment kept
    showing "Running the first scan…" with no result ever landing. The
    caller now attaches the calling thread's ScriptRunContext to this
    thread via add_script_run_ctx() before starting it, so these
    session_state writes work normally.
    """
    try:
        # FIX SPEED1: get_top_picks() reads a scheduled scan snapshot from
        # trade_store first (written every 15 min by scripts/warm_top_picks.py
        # via GitHub Actions) and only falls back to a live ~2-min scan
        # (_home_top_picks, unchanged) if that snapshot is missing or stale.
        result = get_top_picks(vix_regime=vix_regime, sector_ranks=sector_ranks)
        st.session_state[_PICKS_KEY] = result
        # FIX TP-NOOP1: record the snapshot's generated_at (when available)
        # so the next fragment tick can detect "snapshot unchanged" and skip
        # the whole refresh instead of spawning another bg thread every 5 min.
        # Live-scan results carry no generated_at — set to None so any future
        # persisted snapshot will look "different" and load in.
        _gen_at = result.get("generated_at") if isinstance(result, dict) else None
        st.session_state[f"{_PICKS_KEY}_gen_at"] = _gen_at
        # Anchor _ts to the snapshot's true generation time when available,
        # so the "Top Picks last updated" chip reflects when the scan
        # actually ran (not the round-trip time on this thread).
        if _gen_at:
            try:
                st.session_state[f"{_PICKS_KEY}_ts"] = (
                    datetime.datetime.fromisoformat(_gen_at))
            except Exception:
                st.session_state[f"{_PICKS_KEY}_ts"] = datetime.datetime.now()
        else:
            st.session_state[f"{_PICKS_KEY}_ts"] = datetime.datetime.now()
        st.session_state[f"{_PICKS_KEY}_error"] = None
    except Exception as _e:
        st.session_state[f"{_PICKS_KEY}_error"] = str(_e)
    finally:
        st.session_state[f"{_PICKS_KEY}_fetching"] = False


import datetime


# FIX CC-FRESH → dashboard/shared/pick_freshness — pick-card freshness helper
# was extracted here so both Command Centre and My Watchlist use one impl.
# Local aliases kept so the test that scrapes _reanchor_levels + _COST_ROUNDTRIP_PCT
# out of this file still passes.
from dashboard.shared.pick_freshness import (
    COST_ROUNDTRIP_PCT as _COST_ROUNDTRIP_PCT,
    LIVE_DRIFT_THRESHOLD_PCT as _LIVE_DRIFT_THRESHOLD_PCT,
    reanchor_levels as _reanchor_levels,
    compose_finalverdict_for_card as _compose_fv_for_card,
)


# FIX CC-FRAG — this decorator used to live above the old inline
# _reanchor_levels() helper (before it was extracted to pick_freshness).
# The extraction left the decorator dangling above the import block, which
# is a SyntaxError on real Python (streamlit-testing's AppTest was swallowing
# it as a startup error, so the local smoke test passed while the actual
# Streamlit Cloud runtime crashed with "invalid syntax" on ast.parse).
# The decorator belongs on _render_top_picks_section — that's what should
# rerun every 20s to keep the pick cards' live prices ticking.
@st.fragment(run_every=20)
def _render_top_picks_section(vix_regime: str, sector_tuple: tuple) -> None:
    _tp_h1, _tp_h2 = st.columns([5, 2])
    with _tp_h1:
        st.markdown("### 🔥 Today's Top Picks — NSE Scan")
        st.caption("Strongest and weakest **trend-quality** setups today. "
                   "Scores rank trend health — they are **not a forecast of returns**. "
                   "The pick list is regenerated every ~15 min by a scheduled scan and this page "
                   "picks up each new snapshot within seconds; prices on each card tick live "
                   "(~60s) in between. Old picks stay on screen while a refresh runs in the "
                   "background.")
    with _tp_h2:
        st.write("")
        _run_picks = st.button("🔎 Scan Now", key="cc_run_picks", width="stretch")

    from dashboard.shared.disclosures import (
        render_regime_reliability_note as _cc_regime_note,
        render_score_methodology as _cc_score_methodology,
    )
    _cc_regime_note()
    _cc_score_methodology()

    # ── Decide whether a (re)scan is needed, then kick it off in the background ──
    _now = datetime.datetime.now()
    _last_ts = st.session_state.get(f"{_PICKS_KEY}_ts")
    _is_stale = (_last_ts is None) or ((_now - _last_ts).total_seconds() > _PICKS_TTL_SECONDS)
    _fetching = st.session_state.get(f"{_PICKS_KEY}_fetching", False)

    # FIX (stuck-scanning watchdog): if a scan has been "fetching" for longer
    # than any real scan should ever take, the background thread has died
    # (crashed, killed, or — before the ScriptRunContext fix above — a
    # NoSessionContext error) without ever resetting the flag. Self-heal
    # instead of showing "scanning…" forever.
    #
    # FIX TP-WATCHDOG1: raised 180 → 300 s. The user-facing copy in the
    # first-scan banner says the live scan "can take ~2 minutes", and the
    # underlying _home_top_picks worst case observed at 745 tickers × 16
    # workers on a bad Angel-throttle day is closer to 3 min, not 2. At the
    # old 180 s threshold a slow-but-healthy live scan could be falsely
    # marked "stalled and was reset automatically" while the bg thread was
    # still working — then it would land seconds later against session_state
    # already flipped to a fresh scan attempt, causing a needless second
    # 2-min scan on top of the one that would have succeeded. 300 s comfortably
    # brackets the real worst case while still self-healing a genuinely dead
    # thread within a fragment tick or two.
    _fetch_started = st.session_state.get(f"{_PICKS_KEY}_fetch_started")
    if _fetching and _fetch_started and (_now - _fetch_started).total_seconds() > 300:
        st.session_state[f"{_PICKS_KEY}_fetching"] = False
        st.session_state[f"{_PICKS_KEY}_error"] = (
            "Previous scan attempt stalled and was reset automatically."
        )
        _fetching = False
        _is_stale = True

    # ── FIX TP-FAST1 + FIX TP-NOOP1 — cheap snapshot peek before any bg work ──
    # Previously EVERY refresh (first render, and every 5 min thereafter) went
    # straight to the bg-thread path, which:
    #   (a) on first render, showed a scary "~2 minutes" banner even though the
    #       persisted snapshot returns in ~1 s from Postgres, and
    #   (b) on every 5-min tick, flashed the "🔄 Refreshing…" banner and paid
    #       a DB round-trip even though the warmer only advances the snapshot
    #       every 15 min — so 2 in 3 refreshes had nothing new to fetch.
    #
    # Fix: peek at the persisted snapshot's generated_at directly. If it hasn't
    # advanced since we last loaded it, no-op the whole refresh (no bg thread,
    # no banner). If it HAS advanced, load it synchronously — a Postgres KV
    # read is fast enough to do on the main thread. Only the true slow path
    # (Scan Now, or persisted snapshot genuinely missing / older than
    # _TOP_PICKS_MAX_AGE_SECONDS in trade_store) still spawns the bg thread
    # and shows the "~2 minutes" banner. This makes the common case both
    # faster (no bg thread ceremony) and quieter (no misleading banners).
    _prev_gen_at = st.session_state.get(f"{_PICKS_KEY}_gen_at")
    _needs_bg_scan = False
    if _run_picks:
        # User forced: skip the peek and go straight to the slow live-scan
        # path (Scan Now is the escape hatch for "the snapshot looks stale
        # even though the warmer says otherwise").
        _needs_bg_scan = True
    elif _is_stale:
        _snap_peek = _persisted_top_picks_snapshot()
        _snap_gen = _snap_peek.get("generated_at") if _snap_peek else None
        if _snap_peek is None:
            # No persisted snapshot at all (or it's older than the tolerance
            # window) — this is the real slow path. Bg thread + banner.
            _needs_bg_scan = True
        elif _snap_gen and _snap_gen == _prev_gen_at:
            # Snapshot unchanged since our last load — no work to do. Push our
            # local _ts forward so we don't re-peek every 20s fragment tick.
            st.session_state[f"{_PICKS_KEY}_ts"] = _now
            _last_ts = _now
            _is_stale = False
        else:
            # Snapshot advanced — swap it in synchronously. No bg thread, no
            # "refreshing…" banner flash, cards update in one clean render.
            st.session_state[_PICKS_KEY] = _snap_peek
            st.session_state[f"{_PICKS_KEY}_gen_at"] = _snap_gen
            # Anchor _ts to the snapshot's real generation time (not local
            # render time) so the "Top Picks last updated" chip below shows
            # when the scan actually ran, not when we happened to read it.
            try:
                st.session_state[f"{_PICKS_KEY}_ts"] = (
                    datetime.datetime.fromisoformat(_snap_gen))
            except Exception:
                st.session_state[f"{_PICKS_KEY}_ts"] = _now
            st.session_state[f"{_PICKS_KEY}_error"] = None
            _last_ts = st.session_state[f"{_PICKS_KEY}_ts"]
            _is_stale = False

    if _needs_bg_scan and not _fetching:
        st.session_state[f"{_PICKS_KEY}_fetching"] = True
        st.session_state[f"{_PICKS_KEY}_fetch_started"] = _now
        _bg_thread = threading.Thread(
            target=_picks_background_fetch,
            args=(vix_regime, sector_tuple),
            daemon=True,
        )
        # FIX (stuck-scanning bug): without this, st.session_state writes
        # inside _picks_background_fetch raise NoSessionContext and the
        # thread dies before `_fetching` is ever reset to False — see the
        # docstring on _picks_background_fetch for the full failure chain.
        try:
            from streamlit.runtime.scriptrunner import add_script_run_ctx
            add_script_run_ctx(_bg_thread)
        except Exception as _ctx_e:
            import logging as _ctx_log
            _ctx_log.getLogger("dashboard.command_centre").warning(
                "Could not attach ScriptRunContext to Top Picks scan thread: %s", _ctx_e
            )
        _bg_thread.start()
        _fetching = True

    _picks = st.session_state.get(_PICKS_KEY)
    _err = st.session_state.get(f"{_PICKS_KEY}_error")

    # Status strip — always non-blocking; never replaces the cards below.
    if _picks is None and _fetching:
        st.info("⏳ Running the first scan of the full NSE universe — this can take ~2 minutes. "
                "This page will update on its own the moment it's ready; feel free to keep "
                "using the rest of Command Centre meanwhile.")
        return
    if _picks is None and _err:
        st.error(f"⚠️ Last scan attempt failed: {_err}")
        return
    if _picks is None:
        st.caption("Waiting for the first scan to start…")
        return

    if _fetching:
        st.markdown(
            '<div style="background:var(--sunken);border:1px solid var(--sunken);border-radius:8px;'
            'padding:6px 14px;margin-bottom:10px">'
            '<span style="font-size:12px;color:var(--bull)">🔄 Refreshing in the background — '
            'current picks below stay as-is until the new scan lands.</span></div>',
            unsafe_allow_html=True,
        )
    elif _last_ts:
        # FIX TP-NOOP1: the freshness chip now shows the snapshot's actual
        # generation time (from the warmer's generated_at, when the picks came
        # from the persisted snapshot) rather than the moment this session
        # happened to load them. Copy updated to match reality: the warmer
        # advances the snapshot every ~15 min in market hours, and the page
        # picks up the new one on its next 20s fragment tick — the old copy
        # ("auto-refreshes every 5 min") was true of the fragment cadence,
        # not of when the cards actually change.
        # FIX TP-VIX1: also surface the vix_regime the scan was scored under,
        # so it's obvious the picks reflect the market regime at scan time
        # (which may lag the live regime by up to ~15 min).
        _src = (_picks or {}).get("source") if isinstance(_picks, dict) else None
        _src_label = "live scan" if _src == "live_scan" else "scheduled scan"
        _snap_regime = ((_picks or {}).get("meta", {}) or {}).get("vix_regime")
        _regime_html = (
            f' <span style="color:var(--dim)">· regime <b style="color:var(--ink-mid)">{_snap_regime}</b></span>'
            if _snap_regime else ""
        )
        st.markdown(
            f'<div style="background:var(--sunken);border:1px solid var(--sunken);border-radius:8px;'
            f'padding:7px 14px;margin-bottom:10px;display:flex;justify-content:space-between;'
            f'align-items:center">'
            f'<span style="font-size:12px;color:var(--bull)">📊 Top Picks last scored: '
            f'<b>{_last_ts.strftime("%H:%M:%S")}</b> '
            f'<span style="color:var(--dim)">({_src_label})</span>{_regime_html}</span>'
            f'<span style="font-size:11px;color:var(--faint)">Scan refreshes every ~15 min · '
            f'tap Scan Now to force a live rescan</span>'
            f'</div>',
            unsafe_allow_html=True,
        )

    # ── FIX TP-VIX1: warn on regime mismatch ──
    # If VIX has flipped between when the snapshot was scored and now, the
    # picks (esp. their allow_buy gating and any regime-sensitive scoring)
    # may no longer be appropriate. This is deliberately a soft warning, not
    # an auto-rescan — the warmer will catch up within one 15-min tick, and
    # the escape hatch is "Scan Now" which is one click away below.
    _snap_meta_for_regime = (_picks or {}).get("meta", {}) or {}
    _snap_regime = _snap_meta_for_regime.get("vix_regime")
    _current_regime = vix_regime
    if (_snap_regime and _current_regime and _snap_regime != _current_regime):
        # Only actually flag it as a mismatch worth warning about if either
        # side is one of the risk-off regimes — a normal↔calm drift is not
        # meaningful for the scoring model (allow_buy is identical for both).
        _risk_off = {"fear", "panic"}
        _material = (_snap_regime in _risk_off) != (_current_regime in _risk_off)
        if _material:
            st.markdown(
                f'<div style="background:var(--sunken);border:1px solid var(--sunken);border-radius:8px;'
                f'padding:8px 14px;margin-bottom:10px">'
                f'<span style="font-size:12px;color:var(--amber)">⚠ VIX regime has shifted since '
                f'the last scan (was <b>{_snap_regime}</b>, now <b>{_current_regime}</b>). '
                f'The picks below were scored under the earlier regime. The scheduled scan '
                f'will catch up within ~15 min — or tap <b>Scan Now</b> above to force a '
                f'live rescan under the current regime.</span></div>',
                unsafe_allow_html=True,
            )

    # ── FIX TP1 (page side) — honest "no strong picks" banner + tier-aware cards ──
    _picks_meta = _picks.get("meta", {})

    # ── FIX TP-HEALTH1: scan-health chip when data-fetch degraded ──
    # _home_top_picks now records n_scanned / n_scored_ok / n_unavailable in
    # meta. When the unavailable fraction crosses UNAVAIL_WARN_FRACTION, show
    # a small chip so users understand a short Buy Candidates column reflects
    # a data-source problem (Stooq breaker open, Yahoo throttle, Angel token
    # expired), not a genuinely quiet market. Threshold is deliberate: below
    # ~10 % is normal noise (illiquid tail names, new listings without SMA200
    # history, etc.) and would just add banner fatigue.
    _UNAVAIL_WARN_FRACTION = 0.10
    _n_scanned    = int(_picks_meta.get("n_scanned", 0) or 0)
    _n_unavail    = int(_picks_meta.get("n_unavailable", 0) or 0)
    if _n_scanned > 0 and (_n_unavail / _n_scanned) >= _UNAVAIL_WARN_FRACTION:
        _pct = 100.0 * _n_unavail / _n_scanned
        st.markdown(
            f'<div style="background:var(--sunken);border:1px solid var(--sunken);border-radius:8px;'
            f'padding:8px 14px;margin-bottom:10px">'
            f'<span style="font-size:12px;color:var(--amber)">⚠ Data quality alert: '
            f'<b>{_n_unavail}/{_n_scanned}</b> tickers ({_pct:.1f}%) were unavailable this '
            f'scan — the pick list below is drawn from the remaining '
            f'<b>{_n_scanned - _n_unavail}</b>. A source (Stooq / Yahoo / Angel) may be '
            f'throttled or degraded; picks are still valid but the universe is narrower '
            f'than usual.</span></div>',
            unsafe_allow_html=True,
        )

    if _picks_meta.get("no_strong_picks"):
        st.markdown(
            '<div style="background:var(--sunken);border:1px solid var(--sunken);border-radius:8px;'
            'padding:10px 14px;margin-bottom:10px">'
            '<span style="font-size:13px;color:var(--amber)">⚠️ <b>No strong BUY-grade setups '
            'in today\'s scan.</b> The names below are the closest watchlist-grade '
            'candidates — none currently meet the bar for a confident new entry. '
            'Consider waiting for a cleaner setup.</span></div>',
            unsafe_allow_html=True,
        )
    elif _picks_meta.get("n_strong_buys", 0) < len(_picks["buys"]):
        st.caption(
            f"📊 {_picks_meta.get('n_strong_buys', 0)} genuine strong BUY-grade setup(s) today — "
            "remaining cards below are watchlist-grade backfill, marked accordingly."
        )

    # FIX CC-LOAD1 (original): this section used to batch-fetch live price,
    # re-anchor entry/SL/TP AND compute suggested qty for every buy+sell
    # ticker (up to ~40) on EVERY Command Centre rerun — real, unbounded
    # network cost paid whether or not anyone was about to act on any of it.
    # All three were removed; SL/TP re-anchoring + qty sizing still live only
    # in Deep Dive's on-demand Live Snapshot, for the one ticker actually
    # being looked at — sizing off a stale price is a worse failure mode
    # than a stale price label, so that boundary stays.
    #
    # FIX CC-LIVE1: price alone is reinstated, on the same bounded pattern
    # already proven safe by the Top Picks ticker strip above — one tiered
    # batch call (_picks_live_prices, cached 60s) for every ticker actually
    # on screen, not a fetch-per-card. This fragment reruns every 20s, but
    # the 60s cache means the live-price network cost only actually fires
    # once every 3rd rerun, same cost profile as the strip.
    _pk_tickers = tuple(sorted({b["ticker"] for b in _picks["buys"]} |
                               {s["ticker"] for s in _picks["sells"]}))
    _pk_live = _picks_live_prices(_pk_tickers)

    _pk_buy, _pk_sell = st.columns(2)
    with _pk_buy:
        st.markdown("#### 🟢 Buy Candidates")
        if not _picks["buys"]:
            st.caption("No strong buy setups today — market not offering clean entries.")
        for _b in _picks["buys"]:
            _bl = _b["ticker"].replace(".NS", "")
            _tt_lbl, _tt_emo, _tt_col = _trade_type(_b.get("headline", ""))
            _grade_tag = ("A+" if _b["score"] >= 88 else "A" if _b["score"] >= 75
                          else "B" if _b["score"] >= 62 else "")
            _grade_html = (f'<span style="background:{_tt_col}22;color:{_tt_col};border:1px solid {_tt_col};'
                           f'border-radius:5px;padding:1px 7px;font-size:10px;font-weight:700;margin-left:6px">'
                           f'GRADE {_grade_tag}</span>') if _grade_tag else ""

            _is_watch_tier = _b.get("tier") == "watch"
            _card_border = "var(--amber)" if _is_watch_tier else "var(--bull)"
            _card_grad   = ("linear-gradient(135deg,var(--sunken),var(--sunken))" if _is_watch_tier
                            else "linear-gradient(135deg,var(--sunken),var(--sunken))")
            _score_color = "var(--amber)" if _is_watch_tier else "var(--bull)"
            _tier_badge  = (
                '<span style="background:var(--tint-amber);color:var(--amber);border:1px solid var(--amber);'
                'border-radius:5px;padding:1px 7px;font-size:10px;font-weight:700;margin-left:6px">'
                'WATCHLIST-GRADE</span>'
            ) if _is_watch_tier else ""

            # FIX FV-PILL — surface the ONE-verdict answer on the pick card.
            # Horizon is inferred from the pick's own "horizon" hint so a
            # Swing-labelled pick is scored on the short lens and a
            # Positional-labelled one on medium. See
            # dashboard/shared/pick_freshness._horizon_for_pick.
            _fv_pill = ""
            try:
                _fv = _compose_fv_for_card(_b, tqs=None)
                _fv_pill_colors = {
                    "STRONG BUY": "var(--bull)", "BUY": "var(--bull)", "WATCH": "var(--accent)",
                    "HOLD": "var(--dim)", "AVOID": "var(--bear)",
                }
                _pc = _fv_pill_colors.get(_fv.verdict, "var(--dim)")
                _fv_pill = (
                    f'<span style="background:{_pc}22;color:{_pc};border:1px solid {_pc};'
                    f'border-radius:5px;padding:1px 7px;font-size:10px;font-weight:700;margin-left:6px" '
                    f'title="FinalVerdict on the {_fv.horizon} horizon — '
                    f'{_fv.confidence} confidence, conviction {_fv.conviction}/100. '
                    f'{_fv.primary_reason}">'
                    f'VERDICT: {_fv.verdict}</span>'
                )
            except Exception as _fv_pill_e:
                import logging
                logging.getLogger("dashboard.command_centre").debug(
                    "FinalVerdict pill failed for %s: %s", _b.get("ticker"), _fv_pill_e)

            # FIX CC-LIVE1: live price if the batch fetch resolved this
            # ticker, otherwise the same honest "(last close)" fallback as
            # before — never silently pretend a stale price is live.
            _b_lp = _pk_live.get(_b["ticker"])
            _b_live_price = float(_b_lp["price"]) if _b_lp else None

            # FIX CC-FRESH — re-anchor entry/SL/TP to live price if it's
            # drifted > 0.5 % from the scored entry, and compute honest
            # cost-adjusted R:R. See _reanchor_levels() docstring above.
            _b_lvl = _reanchor_levels(
                float(_b.get("entry") or 0), float(_b.get("sl") or 0),
                float(_b.get("tp") or 0), _b_live_price,
            )
            if _b_lp:
                _b_up = (_b_lp.get("chg_pct") or 0) >= 0
                _b_pc = "var(--bull)" if _b_up else "var(--bear)"
                _b_live_span = (
                    f'<span style="color:{_b_pc};font-weight:700">₹{_b_lp["price"]:,.2f} '
                    f'{"▲" if _b_up else "▼"}{abs(_b_lp.get("chg_pct") or 0):.2f}%</span>'
                    f' <span style="color:var(--faint)">live</span>'
                )
                if _b_lvl["reanchored"]:
                    _b_live_span += (
                        f' <span style="color:var(--amber)"> · re-anchored '
                        f'({_b_lvl["drift_pct"]:+.1f}% drift from scored entry)</span>'
                    )
            else:
                _b_live_span = '<span style="color:var(--faint)">(last close — live price unavailable)</span>'

            _b_rr_html = ""
            if _b_lvl["entry"] and _b_lvl["sl"] and _b_lvl["tp"]:
                _rr_gross = _b_lvl["rr"]
                _rr_net   = _b_lvl["rr_net"]
                _b_rr_html = (
                    f'<div style="font-size:11px;color:var(--dim);margin-top:2px">'
                    f'R:R <span style="color:var(--ink)">{_rr_gross:.1f}:1</span> gross, '
                    f'<span style="color:var(--amber)">{_rr_net:.1f}:1 net of ~{_COST_ROUNDTRIP_PCT:.2f}% costs</span></div>'
                )

            # Freshness stamps — score time and live-price time
            _b_scored_at = st.session_state.get(f"{_PICKS_KEY}_ts")
            _stamp_html = (
                f'<div style="font-size:10px;color:var(--faint);margin-top:3px">'
                f'📊 Scored at {_b_scored_at.strftime("%H:%M") if _b_scored_at else "unknown"}'
                f' · 💹 Live price {"as of now" if _b_lp else "unavailable"}'
                f'</div>'
            )

            st.markdown(
                f'<div style="background:{_card_grad};'
                f'border-left:4px solid {_card_border};border-radius:10px;padding:11px 14px;margin-bottom:6px">'
                f'<div style="display:flex;justify-content:space-between;align-items:center">'
                f'<span><span style="font-size:16px;font-weight:700;color:var(--ink)">{_bl}</span>{_grade_html}{_tier_badge}{_fv_pill}</span>'
                f'<span style="font-size:13px;font-weight:700;color:{_score_color}">{_b["score"]:.0f}/100 · {_b["action"]}</span>'
                f'</div>'
                f'<div style="font-size:11px;color:{_tt_col};font-weight:600;margin-top:3px">{_tt_emo} {_tt_lbl} setup</div>'
                f'<div style="font-size:12px;color:var(--ink-mid);margin-top:2px">{_b["headline"]}</div>'
                + (f'<div style="font-size:11px;color:var(--dim);margin-top:4px">'
                   f'Entry ₹{_b_lvl["entry"]:,.2f} · SL ₹{_b_lvl["sl"]:,.2f} · TP ₹{_b_lvl["tp"]:,.2f} '
                   f'{_b_live_span}</div>'
                   if _b_lvl["entry"] else "")
                + _b_rr_html
                + (f'<div style="font-size:11px;color:var(--azure);margin-top:2px">'
                   f'⏱ {_b.get("horizon")}'
                   + (f' · {_horizon_countdown(_b.get("valid_until"))}' if _b.get("valid_until") else '')
                   + '</div>'
                   if _b.get("horizon") else "")
                + _stamp_html
                + '</div>',
                unsafe_allow_html=True,
            )
            if _b_lvl["entry"]:
                # Paper trade uses the RE-ANCHORED levels — a live-price
                # entry with SL/TP at the stale-scored values would set stops
                # in the wrong place from the moment the trade opens.
                _paper_trade_popover(
                    _b["ticker"], _b_lvl["entry"], _b_lvl["sl"], _b_lvl["tp"],
                    reason=f"Top Pick: {_b['headline'][:55]}",
                    key=f"cc_pick_{_b['ticker']}",
                    label=f"📌 Paper Trade {_bl}",
                )
            render_pick_analysis(_b, key_prefix=f"cc_buy_{_b['ticker']}")
    with _pk_sell:
        st.markdown("#### 🔴 Sell / Avoid")
        if not _picks["sells"]:
            st.caption("No clear sell signals — nothing flashing red in the scan.")
        for _sv in _picks["sells"]:
            _svl = _sv["ticker"].replace(".NS", "")
            # FIX CC-LIVE1: same bounded pattern as the Buy loop above —
            # price only, from the one shared _pk_live batch fetch already
            # done for every ticker on screen this rerun.
            _sv_lp = _pk_live.get(_sv["ticker"])
            if _sv_lp:
                _sv_up = (_sv_lp.get("chg_pct") or 0) >= 0
                _sv_pc = "var(--bull)" if _sv_up else "var(--bear)"
                _sv_live_html = (
                    f'<div style="font-size:11px;margin-top:4px">'
                    f'<span style="color:{_sv_pc};font-weight:700">₹{_sv_lp["price"]:,.2f} '
                    f'{"▲" if _sv_up else "▼"}{abs(_sv_lp.get("chg_pct") or 0):.2f}%</span> '
                    f'<span style="color:var(--faint)">live</span></div>'
                )
            else:
                _sv_live_html = ""
            st.markdown(
                f'<div style="background:linear-gradient(135deg,var(--sunken),var(--sunken));'
                f'border-left:4px solid var(--bear);border-radius:10px;padding:11px 14px;margin-bottom:6px">'
                f'<div style="display:flex;justify-content:space-between;align-items:center">'
                f'<span style="font-size:16px;font-weight:700;color:var(--ink)">{_svl}</span>'
                f'<span style="font-size:13px;font-weight:700;color:var(--bear)">{_sv["score"]:.0f}/100 · {_sv["action"]}</span>'
                f'</div>'
                f'<div style="font-size:12px;color:var(--ink-mid);margin-top:3px">{_sv["headline"]}</div>'
                f'{_sv_live_html}'
                + '</div>',
                unsafe_allow_html=True,
            )
            render_pick_analysis(_sv, key_prefix=f"cc_sell_{_sv['ticker']}")


_sec_tuple = _sector_ranks_tuple()
st.session_state["_sec_ranks_cache"] = _sec_tuple   # share with watchlist
_render_top_picks_section(_cc_vix_r, _sec_tuple)

st.markdown("---")

@st.fragment
def _render_open_positions_section():
    """Own fragment so Close Now / autoclose-toggle clicks only rerun this section, not the whole Command Centre page."""
    # ── 3. OPEN POSITION ALERTS + AUTO-CLOSE ───────────────────────────────────
    _cc_h1, _cc_h2 = st.columns([5, 2])
    _cc_h1.markdown("### 📌 Open Positions")
    with _cc_h2:
        _cc_autoclose = st.toggle(
            "🤖 Auto-close CNC on SL/TP",
            value=st.session_state.get("auto_close_on", False),
            key="cc_autoclose_toggle",
            help="When ON, CNC (delivery) paper trades that hit their target or stop-loss are "
                 "closed automatically on page load (during market hours only, on live prices). "
                 "MIS (intraday) positions are ALWAYS squared off at 15:15 regardless of this toggle. "
                 "Real broker holdings are never auto-traded — only alerted.",
        )
        st.session_state["auto_close_on"] = _cc_autoclose
    
    _cc_sq_banner_shown = False
    if _is_squareoff_time():
        _sq_all_closed = _auto_close_breached()
        _sq_mis_closed = [c for c in _sq_all_closed if c["type"] == "squareoff"]
        if _sq_mis_closed:
            _render_autoclose_banner(_sq_mis_closed)
            # BUGFIX: only live prices need to be re-fetched after an auto-close —
            # a blanket st.cache_data.clear() here also nuked Top Picks, watchlist
            # scores, and VIX info on every squareoff event.
            _portfolio_live_prices.clear()
            _cc_sq_banner_shown = True
    
    if _cc_autoclose:
        _cc_all_closed = _auto_close_breached()
        _cc_sltp_closed = [c for c in _cc_all_closed if c["type"] in ("target", "stop")]
        if _cc_sltp_closed:
            _render_autoclose_banner(_cc_sltp_closed)
            _portfolio_live_prices.clear()
    
    _cc_open_df = pd.DataFrame()
    try:
        _cc_open_df = _store.fetch_open()
    except Exception as _e:
        st.caption(f"⚠️ Couldn't load open paper positions ({_e}).")
    
    if _cc_open_df.empty:
        st.info("No open paper positions. Use **Paper Trades** or click **Paper Trade** on any BUY signal below.")
    else:
        _cc_syms = tuple(_cc_open_df["ticker"].tolist())
        _cc_lp   = _portfolio_live_prices(_cc_syms)
    
        _cc_alerts, _cc_normal_pos = [], []
        for _, _ccr in _cc_open_df.iterrows():
            _ck  = _ccr["ticker"]
            _cep = float(_ccr.get("price", 0) or 0)
            _cqt = int(  _ccr.get("quantity", 0) or 0)
            _csl = float(_ccr.get("sl", 0) or 0) or None
            _ctp = float(_ccr.get("tp", 0) or 0) or None
            _clp_d = _cc_lp.get(_ck, {})
            _ccur  = _clp_d.get("price", _cep)
            _cunr  = (_ccur - _cep) * _cqt
            _cunr_pct = (_ccur / _cep - 1) * 100 if _cep > 0 else 0
    
            _cst = "normal"
            if _ctp and _ccur >= _ctp:       _cst = "target_hit"
            elif _csl and _ccur <= _csl:     _cst = "sl_hit"
            elif abs(_cunr_pct) >= 5:        _cst = "big_move"
    
            _entry_d = dict(id=int(_ccr["id"]), ticker=_ck,
                            account=str(_ccr.get("account","My Account")),
                            ep=_cep, cur=_ccur, qty=_cqt, sl=_csl, tp=_ctp,
                            unr=_cunr, unr_pct=_cunr_pct, status=_cst)
            (_cc_alerts if _cst != "normal" else _cc_normal_pos).append(_entry_d)
    
        if _cc_alerts:
            st.markdown("**⚠️ These positions need your attention:**")
    
        for _pos in _cc_alerts + _cc_normal_pos:
            _pbdr = {"target_hit": "var(--bull)", "sl_hit": "var(--bear)", "big_move": "var(--amber)",
                     "normal": "var(--accent)"}.get(_pos["status"], "var(--accent)")
            _pbg  = {"target_hit": "var(--sunken)", "sl_hit": "var(--sunken)",  "big_move": "var(--sunken)",
                     "normal": "var(--surface)"}.get(_pos["status"], "var(--surface)")
            _purc = "var(--bull)" if _pos["unr"] >= 0 else "var(--bear)"
            _palert = {
                "target_hit": f"🎯 Target hit — close to lock in profit",
                "sl_hit":     f"🚨 Stop-loss breached — consider exiting to limit loss",
                "big_move":   f"{'📈' if _pos['unr_pct']>0 else '📉'} Large move — review your stop and target",
            }.get(_pos["status"], "")
    
            _pc1, _pc2 = st.columns([5, 1])
            with _pc1:
                st.markdown(
                    f'<div style="background:{_pbg};border-left:5px solid {_pbdr};'
                    f'border-radius:10px;padding:11px 15px;margin-bottom:6px">'
                    f'<div style="display:flex;justify-content:space-between;align-items:center">'
                    f'<div><span style="font-size:16px;font-weight:700;color:var(--ink)">'
                    f'{_pos["ticker"].replace(".NS","")}</span>'
                    f'<span style="font-size:11px;color:var(--dim);margin-left:8px">📂 {_pos["account"]}</span>'
                    f'<span style="font-size:12px;color:var(--dim);margin-left:8px">'
                    f'Entry ₹{_pos["ep"]:,.2f} → Now ₹{_pos["cur"]:,.2f}</span></div>'
                    f'<div style="font-size:16px;font-weight:700;color:{_purc}">'
                    f'₹{_pos["unr"]:+,.0f} ({_pos["unr_pct"]:+.1f}%)</div></div>'
                    + (f'<div style="font-size:13px;color:var(--ink-mid);margin-top:4px">{_palert}</div>' if _palert else '')
                    + '</div>',
                    unsafe_allow_html=True,
                )
            with _pc2:
                if _pos["status"] in ("target_hit", "sl_hit"):
                    if st.button("Close Now", key=f"cc_cl_{_pos['id']}",
                                 width="stretch", type="primary"):
                        paper_close_trade(_pos["id"], _pos["cur"],
                                          "Closed via Command Centre")
                        # BUGFIX: closing one position only needs fresh live
                        # prices for the remaining open positions — it doesn't
                        # need to invalidate Top Picks or watchlist scores too.
                        _portfolio_live_prices.clear()
                        st.rerun()
    

_render_open_positions_section()

# FIX CC-TRIM — the bottom "Watchlist — What to Do Today" section was removed
# from this page on request. It duplicated 14_my_watchlist.py, which is where
# per-name scoring lives exclusively. Home page below is Top Picks + Open
# Positions + Background Alerts.

# ── 5. BACKGROUND TELEGRAM ALERTS (viewer) ─────────────────────────────────
st.markdown("---")
with st.expander("🔔 Background Alerts (Telegram) — fire even when this app is closed", expanded=False):
    st.caption(
        "A GitHub Actions job checks these every 15 min during market hours and "
        "messages you on Telegram. Edit **data/alerts.csv** in your GitHub repo to "
        "change them. Full setup: **alerts/README.md**."
    )
    try:
        import pathlib as _alp
        _alerts_path = _alp.Path(_ROOT) / "data" / "alerts.csv"
        if _alerts_path.exists():
            _al_df = pd.read_csv(_alerts_path)
            _act_df = _al_df[_al_df["enabled"].astype(str).isin(["1", "True", "true"])]
            st.markdown(f"**{len(_act_df)} active** of {len(_al_df)} configured price alerts:")
            if not _act_df.empty:
                _al_show = _act_df[["ticker", "condition", "level", "note"]].copy()
                _al_show.columns = ["Stock", "When price goes", "Level (₹)", "Note"]
                st.dataframe(_al_show, hide_index=True, width="stretch")
            else:
                st.info("No active price alerts. All rows are examples (enabled=0). "
                        "Set `enabled=1` on a row in data/alerts.csv to activate it.")
        else:
            st.info("No alerts.csv found yet.")
    except Exception as _ale:
        st.caption(f"Could not read alerts.csv: {_ale}")

    st.markdown(
        "**Also alerted automatically:** 🔴 VIX entering fear/panic · 📉 Nifty breaking into a downtrend.  \n"
        "**One-time setup:** create a Telegram bot via @BotFather, then add "
        "`TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` as GitHub Actions secrets "
        "(Settings → Secrets and variables → Actions)."
    )

# ═══════════════════════════════════════════════════════════════════════════════
# PAGE 1 — MY PORTFOLIO
# ═══════════════════════════════════════════════════════════════════════════════
