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

# â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€ page body (de-indented from app.py) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
st.title("ðŸŽ¯ Command Centre")
st.caption("Market conditions Â· open positions needing action Â· watchlist decisions â€” no digging required.")

# â”€â”€ 0. MORNING SUMMARY CARD â€” your daily brief â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
import datetime as _mb_dt
_mb_now   = _mb_dt.datetime.now(_mb_dt.timezone(_mb_dt.timedelta(hours=5, minutes=30)))
_mb_greet = ("Good morning" if _mb_now.hour < 12 else
             "Good afternoon" if _mb_now.hour < 17 else "Good evening")
_mb_date  = _mb_now.strftime("%A, %d %b %Y Â· %H:%M IST")
_mb_open  = 0
try:
    import trade_store as _mb_ts
    _mbo = _mb_ts.fetch_open()
    _mb_open = 0 if (_mbo is None or _mbo.empty) else len(_mbo)
except Exception as _e:
    st.caption(f"âš ï¸ Couldn't read open paper positions ({_e}) â€” showing 0.")
_mb_reg = get_vix_info().get("regime", "normal")
_mb_focus = {
    "panic":       ("ðŸš¨", "Panic â€” protect capital, avoid new buys"),
    "fear":        ("ðŸ”´", "Fearful â€” be defensive, small sizes only"),
    "elevated":    ("ðŸŸ ", "Elevated volatility â€” only high-conviction setups"),
    "normal":      ("ðŸŸ¢", "Calm conditions â€” trade your setups normally"),
    "complacency": ("ðŸ˜´", "Very calm â€” tighten stops, stay selective"),
}.get(_mb_reg, ("â€¢", "Trade your plan"))
_mb_pos_txt = (f"You have <b style='color:#ff9500'>{_mb_open}</b> open paper position"
               f"{'s' if _mb_open != 1 else ''}." if _mb_open else
               "No open paper positions.")
st.markdown(
    f'<div class="glass-panel" style="margin-bottom:14px;display:flex;'
    f'justify-content:space-between;align-items:center;flex-wrap:wrap;gap:12px">'
    f'<div><div style="font-size:20px;font-weight:800;color:#f0f4ff">â˜€ï¸ {_mb_greet}, Mrinal</div>'
    f'<div style="font-size:12px;color:#8899bb;margin-top:2px">{_mb_date}</div></div>'
    f'<div style="text-align:right">'
    f'<div style="font-size:13px;color:#e0e0e0">{_mb_focus[0]} {_mb_focus[1]}</div>'
    f'<div style="font-size:12px;color:#8899bb;margin-top:3px">{_mb_pos_txt} '
    f'Scroll for today\'s picks &amp; watchlist.</div></div>'
    f'</div>',
    unsafe_allow_html=True,
)

# â”€â”€ 0b. PAPER TRADES OVERVIEW (quick view) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
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

    _u_clr = "#00d4aa" if _pto_unreal >= 0 else "#ff4757"
    _r_clr = "#00d4aa" if _pto_real   >= 0 else "#ff4757"
    _wr_clr = "#00d4aa" if _pto_wr >= 50 else ("#ff9500" if _pto_wr >= 35 else "#ff4757")

    def _pto_cell(_lbl, _val, _clr="#f0f4ff", _sub=""):
        return (f'<div style="flex:1;text-align:center;padding:6px 10px">'
                f'<div style="font-size:10px;color:#4a5568;text-transform:uppercase;'
                f'letter-spacing:1px">{_lbl}</div>'
                f'<div style="font-size:22px;font-weight:800;color:{_clr}">{_val}</div>'
                + (f'<div style="font-size:11px;color:#8899bb">{_sub}</div>' if _sub else "")
                + '</div>')

    st.markdown(
        '<div class="glass-panel" style="margin-bottom:14px;padding:10px 8px">'
        '<div style="font-size:11px;font-weight:700;color:#5a6a8a;text-transform:uppercase;'
        'letter-spacing:1.2px;padding:0 10px 4px">ðŸ“Š Paper Trades Overview</div>'
        '<div style="display:flex;flex-wrap:wrap">'
        + _pto_cell("Open Positions", f"{_pto_n}")
        + _pto_cell("Unrealised P&amp;L", f"â‚¹{_pto_unreal:+,.0f}", _u_clr, "live prices")
        + _pto_cell("Realised P&amp;L", f"â‚¹{_pto_real:+,.0f}", _r_clr,
                    f"{_pto_tot} closed")
        + _pto_cell("Win Rate", f"{_pto_wr:.0f}%", _wr_clr,
                    f"{_pto_wins}/{_pto_tot} wins" if _pto_tot else "no closed trades")
        + '</div></div>',
        unsafe_allow_html=True,
    )
except Exception as _pto_e:
    st.caption(f"âš ï¸ Paper trades overview unavailable ({_pto_e}).")

# â”€â”€ 1. MARKET PULSE â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
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
    st.caption(f"âš ï¸ Couldn't load Nifty trend ({_e}) â€” market pulse may be incomplete.")

_VIX_LBL = {
    "complacency": ("#FFC107", "ðŸ˜´", "COMPLACENT"), "normal":  ("#26a69a", "ðŸŸ¢", "CALM"),
    "elevated":    ("#FF9800", "ðŸŸ¡", "ELEVATED"),   "fear":    ("#ef5350", "ðŸ”´", "HIGH FEAR"),
    "panic":       ("#b71c1c", "ðŸš¨", "PANIC"),      "unknown": ("#9e9e9e", "â“", "UNKNOWN"),
}
_NT_LBL = {
    "uptrend":  ("#26a69a", "ðŸ“ˆ", "UPTREND"),  "downtrend": ("#ef5350", "ðŸ“‰", "DOWNTREND"),
    "sideways": ("#FFC107", "â†”ï¸", "SIDEWAYS"), "unknown":   ("#9e9e9e", "â“", "NO DATA"),
}
_vc, _vi, _vl = _VIX_LBL.get(_cc_vix_r, _VIX_LBL["unknown"])
_nc, _ni, _nl = _NT_LBL.get(_cc_nifty_trend, _NT_LBL["unknown"])

if _cc_vix_r == "normal" and _cc_nifty_trend == "uptrend":
    _verd, _vbg, _vbdr = "âœ… Good conditions â€” new positions okay", "#0a2a1a", "#26a69a"
elif _cc_vix_r in ("fear", "panic") or _cc_nifty_trend == "downtrend":
    _verd, _vbg, _vbdr = "ðŸ”´ Weak / fearful market â€” avoid new buys, protect capital", "#2a0a0a", "#ef5350"
elif _cc_vix_r == "complacency":
    _verd, _vbg, _vbdr = "ðŸ˜´ Market too calm â€” be selective, tighten stops", "#2a2000", "#FFC107"
else:
    _verd, _vbg, _vbdr = "ðŸŸ¡ Mixed signals â€” only high-conviction setups today", "#1a1a0a", "#FFC107"

st.markdown(
    f'<div style="display:flex;gap:12px;margin-bottom:4px">'
    f'<div style="flex:1;background:#0d1f3c;border-left:5px solid {_vc};border-radius:10px;padding:14px 16px">'
    f'<div style="font-size:10px;color:#888;text-transform:uppercase;letter-spacing:1px;margin-bottom:3px">India VIX</div>'
    f'<div style="font-size:20px;font-weight:700;color:{_vc}">{_vi} {_vl}</div>'
    f'<div style="font-size:12px;color:#bbb;margin-top:3px">{f"{_cc_vix_v:.1f}" if _cc_vix_v else "â€”"}</div>'
    f'</div>'
    f'<div style="flex:1;background:#0d1f3c;border-left:5px solid {_nc};border-radius:10px;padding:14px 16px">'
    f'<div style="font-size:10px;color:#888;text-transform:uppercase;letter-spacing:1px;margin-bottom:3px">Nifty 50</div>'
    f'<div style="font-size:20px;font-weight:700;color:{_nc}">{_ni} {_nl}</div>'
    f'<div style="font-size:12px;color:#bbb;margin-top:3px">'
    f'{f"{_cc_nifty_val:,.0f}" if _cc_nifty_val else "â€”"}'
    f'{f"&nbsp;({_cc_nifty_5d:+.1f}% 5d)" if _cc_nifty_val else ""}</div>'
    f'</div>'
    f'<div style="flex:2;background:{_vbg};border-left:5px solid {_vbdr};border-radius:10px;'
    f'padding:14px 16px;display:flex;align-items:center">'
    f'<div style="font-size:16px;font-weight:600;color:#fff">{_verd}</div>'
    f'</div>'
    f'</div>',
    unsafe_allow_html=True,
)
_mood_vix = {"complacency": 85, "normal": 65, "elevated": 45,
             "fear": 22, "panic": 6, "unknown": 50}.get(_cc_vix_r, 50)
_mood_nty = {"uptrend": 80, "sideways": 50, "downtrend": 20,
             "unknown": 50}.get(_cc_nifty_trend, 50)
_mood = int(round((_mood_vix + _mood_nty) / 2))
if   _mood < 20: _mood_lbl, _mood_c = "Extreme Fear", "#ff1744"
elif _mood < 40: _mood_lbl, _mood_c = "Fear", "#ff4757"
elif _mood < 60: _mood_lbl, _mood_c = "Neutral", "#FFC107"
elif _mood < 80: _mood_lbl, _mood_c = "Greed", "#26a69a"
else:            _mood_lbl, _mood_c = "Extreme Greed", "#00e5cc"
st.markdown(
    f'<div style="background:#0d1526;border:1px solid rgba(255,255,255,.05);border-radius:10px;'
    f'padding:12px 18px;margin-top:8px;display:flex;align-items:center;gap:16px">'
    f'<div style="font-size:11px;color:#888;text-transform:uppercase;letter-spacing:1px;min-width:96px">Market Mood</div>'
    f'<div style="flex:1;position:relative;height:10px;border-radius:6px;'
    f'background:linear-gradient(90deg,#ff1744,#ff4757,#FFC107,#26a69a,#00e5cc)">'
    f'<div style="position:absolute;left:{_mood}%;top:-5px;transform:translateX(-50%);'
    f'width:20px;height:20px;border-radius:50%;background:{_mood_c};border:3px solid #0d1526;'
    f'box-shadow:0 0 8px {_mood_c}"></div></div>'
    f'<div style="min-width:130px;text-align:right">'
    f'<span style="font-size:20px;font-weight:800;color:{_mood_c}">{_mood}</span>'
    f'<span style="font-size:13px;color:{_mood_c};font-weight:600"> Â· {_mood_lbl}</span></div>'
    f'</div>',
    unsafe_allow_html=True,
)

_cc_ref_c = st.columns([6, 1])[1]
if _cc_ref_c.button("ðŸ”„ Refresh", key="cc_refresh_pulse", width="stretch"):
    # BUGFIX: this only needs to bust the VIX cache â€” the previous blanket
    # st.cache_data.clear() also wiped Top Picks (2-min cold scan), watchlist
    # scores, and sparklines, forcing expensive re-fetches the user never
    # asked for just to refresh the VIX/Nifty pulse panel.
    get_vix_info.clear()
    st.rerun()

st.markdown("---")

# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# â”€â”€ 1b. TOP PICKS TICKER â€” scrolling ticker tape, separate from the cards â”€â”€
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# FIX (was "Suggestions Strip") â€” the old version had two real bugs:
#   1. It mixed the user's raw watchlist (which can be down on any given day)
#      with a few Top Picks candidates, so a strip meant to be "what's worth
#      a look" could show loss-making stocks â€” it was never actually
#      gainers-only, it was "whatever's on your watchlist".
#   2. It priced everything via trade_utils._portfolio_live_prices, which
#      fetches tickers one at a time in a for-loop (see FIX TU4 there), not
#      in parallel â€” real, measurable load-time cost.
#
# Replaced first with a NIFTY 50 gainers tape, then with FIX TP3: this strip
# now shows the app's own Top Picks BUY candidates (see _top_picks_ticker in
# cache.py) instead of a generic NIFTY 50 gainers feed â€” the same
# score-ranked list as the Buy Candidates cards below, priced live via ONE
# parallel batch call. Buys only, not filtered to today's gainers â€” a Top
# Pick can legitimately be flat or red today, so each chip is colour-coded
# red/green on its own live % change rather than assumed green. It's a real
# horizontal auto-scrolling marquee in a distinct black/teal theme (teal to
# match the Buy Candidates card accent, distinguishing it from the old
# black/amber NIFTY 50 theme) so it reads as a ticker tape, not another card
# section. Still its own @st.fragment(run_every=60) so it refreshes
# independently of the rest of the page. Purely informational (no
# click-through) â€” a scrolling tape isn't a natural fit for per-item
# buttons; the full Top Picks section below still offers the "click through
# to Analyze Stock" workflow.

@st.fragment(run_every=60)
def _render_top_picks_ticker() -> None:
    _tk_rows = _top_picks_ticker(n=12)

    if not _tk_rows:
        st.markdown(
            "<div style='background:#0a0a0a;border-top:2px solid #26a69a;"
            "border-bottom:2px solid #26a69a;border-radius:6px;padding:9px 16px;"
            "font-size:12px;color:#26a69a'>ðŸŽ¯ TOP PICKS â€” no buy candidates "
            "right now.</div>",
            unsafe_allow_html=True,
        )
        return

    def _chip(_r: dict) -> str:
        _lbl = _r["ticker"].replace(".NS", "")
        _up  = (_r["chg_pct"] or 0) >= 0
        _cc  = "#3ddc84" if _up else "#ef5350"
        _arr = "â–²" if _up else "â–¼"
        return (
            f'<span style="display:inline-block;margin-right:34px;white-space:nowrap">'
            f'<span style="color:#eee;font-weight:700;font-size:13px">{_lbl}</span>'
            f'<span style="color:#888;font-size:12px"> â‚¹{_r["price"]:,.1f} </span>'
            f'<span style="color:{_cc};font-weight:700;font-size:13px">'
            f'{_arr}{abs(_r["chg_pct"]):.2f}%</span></span>'
        )

    # Content duplicated back-to-back so the marquee loops seamlessly at the
    # 50%-translateX halfway point (standard CSS ticker-tape technique).
    _tape_html = "".join(_chip(r) for r in _tk_rows) * 2

    st.markdown(
        f'<div style="background:#0a0a0a;border-top:2px solid #26a69a;'
        f'border-bottom:2px solid #26a69a;border-radius:6px;'
        f'display:flex;align-items:center;overflow:hidden">'
        f'<span style="flex-shrink:0;padding:9px 14px;color:#26a69a;'
        f'font-size:10px;font-weight:700;letter-spacing:1px;'
        f'border-right:1px solid #143a34;white-space:nowrap">'
        f'ðŸŽ¯ TOP PICKS<br>BUY CANDIDATES</span>'
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

# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# â”€â”€ 2. TODAY'S TOP PICKS â€” full NSE-wide scan, stale-while-revalidate â”€â”€â”€â”€â”€â”€
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# FIX (blanking on rescan): the old version called _home_top_picks() inside
# `with st.spinner(...)`, directly on the page's normal script run. On a
# cache-miss (cold start, or the 5-min TTL expiring), that call blocks for
# ~2 minutes â€” and because the Top Picks section literally hasn't executed
# yet on this run, there is nothing to show: the previous cards aren't "still
# there", they just haven't been re-drawn, so the whole section reads as
# blank/spinner until the scan finishes.
#
# Fix: the entire section is now an @st.fragment(run_every=...) â€” Streamlit
# reruns ONLY this fragment on its own timer, not the whole page. The last
# good scan result is kept in st.session_state and rendered immediately on
# every fragment run, BEFORE checking whether a refresh is needed. If the
# cached result is stale, a background thread kicks off _home_top_picks()
# without blocking the render â€” so the existing cards stay exactly as they
# are (with a small "refreshingâ€¦" note) until the new scan lands, at which
# point the next fragment tick swaps them in. Nothing ever goes blank.
#
# Universe: this scans get_universe("niftytotalmarket") inside
# _home_top_picks â€” the full ~745-ticker liquid NSE list (Nifty 500 +
# Microcap 250), not a Nifty-50-only set. FIX TP2: previously scanned only
# the narrower "nifty500" (~504 tickers) set, which under-used the wider
# universe already built in data/universe.py.

_PICKS_KEY = "_cc_top_picks"
_PICKS_TTL_SECONDS = 300  # matches _home_top_picks' own cache TTL


def _picks_background_fetch(vix_regime: str, sector_ranks: tuple) -> None:
    """Runs in a worker thread. Only touches st.session_state â€” never calls
    st.* UI functions, which are not safe off the main script thread.

    FIX (stuck-scanning bug): a bare threading.Thread has no Streamlit
    ScriptRunContext attached. Touching st.session_state with no context
    raises NoSessionContext on modern Streamlit â€” and since BOTH the
    try-block writes AND the except-block's own write below would raise,
    the exception from the except handler itself goes unhandled and the
    thread dies silently (it's a daemon thread) before the `finally` ever
    runs. That left `_fetching` stuck True forever, so the fragment kept
    showing "Running the first scanâ€¦" with no result ever landing. The
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
        st.session_state[f"{_PICKS_KEY}_ts"] = datetime.datetime.now()
        st.session_state[f"{_PICKS_KEY}_error"] = None
    except Exception as _e:
        st.session_state[f"{_PICKS_KEY}_error"] = str(_e)
    finally:
        st.session_state[f"{_PICKS_KEY}_fetching"] = False


import datetime


@st.fragment(run_every=20)
def _render_top_picks_section(vix_regime: str, sector_tuple: tuple) -> None:
    _tp_h1, _tp_h2 = st.columns([5, 2])
    with _tp_h1:
        st.markdown("### ðŸ”¥ Today's Top Picks â€” NSE Scan")
        st.caption("Strongest and weakest **trend-quality** setups today. "
                   "Scores rank trend health â€” they are **not a forecast of returns**. "
                   "The pick list itself refreshes every 5 min during market hours; prices "
                   "on each card tick live (~60s) in between. Old picks stay on screen "
                   "while a refresh runs in the background.")
    with _tp_h2:
        st.write("")
        _run_picks = st.button("ðŸ”Ž Scan Now", key="cc_run_picks", width="stretch")

    from dashboard.shared.disclosures import (
        render_regime_reliability_note as _cc_regime_note,
        render_score_methodology as _cc_score_methodology,
    )
    _cc_regime_note()
    _cc_score_methodology()

    # â”€â”€ Decide whether a (re)scan is needed, then kick it off in the background â”€â”€
    _now = datetime.datetime.now()
    _last_ts = st.session_state.get(f"{_PICKS_KEY}_ts")
    _is_stale = (_last_ts is None) or ((_now - _last_ts).total_seconds() > _PICKS_TTL_SECONDS)
    _fetching = st.session_state.get(f"{_PICKS_KEY}_fetching", False)

    # FIX (stuck-scanning watchdog): if a scan has been "fetching" for longer
    # than any real scan should ever take, the background thread has died
    # (crashed, killed, or â€” before the ScriptRunContext fix above â€” a
    # NoSessionContext error) without ever resetting the flag. Self-heal
    # instead of showing "scanningâ€¦" forever.
    _fetch_started = st.session_state.get(f"{_PICKS_KEY}_fetch_started")
    if _fetching and _fetch_started and (_now - _fetch_started).total_seconds() > 180:
        st.session_state[f"{_PICKS_KEY}_fetching"] = False
        st.session_state[f"{_PICKS_KEY}_error"] = (
            "Previous scan attempt stalled and was reset automatically."
        )
        _fetching = False
        _is_stale = True

    if _run_picks:
        # "Scan Now" always forces a fresh background fetch â€” but the cards
        # already on screen are left untouched until it completes.
        _is_stale = True

    if _is_stale and not _fetching:
        st.session_state[f"{_PICKS_KEY}_fetching"] = True
        st.session_state[f"{_PICKS_KEY}_fetch_started"] = _now
        _bg_thread = threading.Thread(
            target=_picks_background_fetch,
            args=(vix_regime, sector_tuple),
            daemon=True,
        )
        # FIX (stuck-scanning bug): without this, st.session_state writes
        # inside _picks_background_fetch raise NoSessionContext and the
        # thread dies before `_fetching` is ever reset to False â€” see the
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

    # Status strip â€” always non-blocking; never replaces the cards below.
    if _picks is None and _fetching:
        st.info("â³ Running the first scan of the full NSE universe â€” this can take ~2 minutes. "
                "This page will update on its own the moment it's ready; feel free to keep "
                "using the rest of Command Centre meanwhile.")
        return
    if _picks is None and _err:
        st.error(f"âš ï¸ Last scan attempt failed: {_err}")
        return
    if _picks is None:
        st.caption("Waiting for the first scan to startâ€¦")
        return

    if _fetching:
        st.markdown(
            '<div style="background:#0d2a1a;border:1px solid #1a4a2a;border-radius:8px;'
            'padding:6px 14px;margin-bottom:10px">'
            '<span style="font-size:12px;color:#4caf7d">ðŸ”„ Refreshing in the background â€” '
            'current picks below stay as-is until the new scan lands.</span></div>',
            unsafe_allow_html=True,
        )
    elif _last_ts:
        st.markdown(
            f'<div style="background:#0d2a1a;border:1px solid #1a4a2a;border-radius:8px;'
            f'padding:7px 14px;margin-bottom:10px;display:flex;justify-content:space-between;'
            f'align-items:center">'
            f'<span style="font-size:12px;color:#4caf7d">ðŸ“Š Top Picks last updated: '
            f'<b>{_last_ts.strftime("%H:%M:%S")}</b></span>'
            f'<span style="font-size:11px;color:#555">Auto-refreshes every 5 min Â· '
            f'tap Scan Now to force refresh</span>'
            f'</div>',
            unsafe_allow_html=True,
        )

    # â”€â”€ FIX TP1 (page side) â€” honest "no strong picks" banner + tier-aware cards â”€â”€
    _picks_meta = _picks.get("meta", {})
    if _picks_meta.get("no_strong_picks"):
        st.markdown(
            '<div style="background:#1a1200;border:1px solid #4a3a00;border-radius:8px;'
            'padding:10px 14px;margin-bottom:10px">'
            '<span style="font-size:13px;color:#ffb300">âš ï¸ <b>No strong BUY-grade setups '
            'in today\'s scan.</b> The names below are the closest watchlist-grade '
            'candidates â€” none currently meet the bar for a confident new entry. '
            'Consider waiting for a cleaner setup.</span></div>',
            unsafe_allow_html=True,
        )
    elif _picks_meta.get("n_strong_buys", 0) < len(_picks["buys"]):
        st.caption(
            f"ðŸ“Š {_picks_meta.get('n_strong_buys', 0)} genuine strong BUY-grade setup(s) today â€” "
            "remaining cards below are watchlist-grade backfill, marked accordingly."
        )

    # FIX CC-LOAD1 (original): this section used to batch-fetch live price,
    # re-anchor entry/SL/TP AND compute suggested qty for every buy+sell
    # ticker (up to ~40) on EVERY Command Centre rerun â€” real, unbounded
    # network cost paid whether or not anyone was about to act on any of it.
    # All three were removed; SL/TP re-anchoring + qty sizing still live only
    # in Deep Dive's on-demand Live Snapshot, for the one ticker actually
    # being looked at â€” sizing off a stale price is a worse failure mode
    # than a stale price label, so that boundary stays.
    #
    # FIX CC-LIVE1: price alone is reinstated, on the same bounded pattern
    # already proven safe by the Top Picks ticker strip above â€” one tiered
    # batch call (_picks_live_prices, cached 60s) for every ticker actually
    # on screen, not a fetch-per-card. This fragment reruns every 20s, but
    # the 60s cache means the live-price network cost only actually fires
    # once every 3rd rerun, same cost profile as the strip.
    _pk_tickers = tuple(sorted({b["ticker"] for b in _picks["buys"]} |
                               {s["ticker"] for s in _picks["sells"]}))
    _pk_live = _picks_live_prices(_pk_tickers)

    _pk_buy, _pk_sell = st.columns(2)
    with _pk_buy:
        st.markdown("#### ðŸŸ¢ Buy Candidates")
        if not _picks["buys"]:
            st.caption("No strong buy setups today â€” market not offering clean entries.")
        for _b in _picks["buys"]:
            _bl = _b["ticker"].replace(".NS", "")
            _tt_lbl, _tt_emo, _tt_col = _trade_type(_b.get("headline", ""))
            _grade_tag = ("A+" if _b["score"] >= 88 else "A" if _b["score"] >= 75
                          else "B" if _b["score"] >= 62 else "")
            _grade_html = (f'<span style="background:{_tt_col}22;color:{_tt_col};border:1px solid {_tt_col};'
                           f'border-radius:5px;padding:1px 7px;font-size:10px;font-weight:700;margin-left:6px">'
                           f'GRADE {_grade_tag}</span>') if _grade_tag else ""

            _is_watch_tier = _b.get("tier") == "watch"
            _card_border = "#FF9800" if _is_watch_tier else "#26a69a"
            _card_grad   = ("linear-gradient(135deg,#2a2000,#332b0a)" if _is_watch_tier
                            else "linear-gradient(135deg,#0a2a1a,#0f3320)")
            _score_color = "#FF9800" if _is_watch_tier else "#26a69a"
            _tier_badge  = (
                '<span style="background:#FF980022;color:#FF9800;border:1px solid #FF9800;'
                'border-radius:5px;padding:1px 7px;font-size:10px;font-weight:700;margin-left:6px">'
                'WATCHLIST-GRADE</span>'
            ) if _is_watch_tier else ""

            # FIX CC-LIVE1: live price if the batch fetch resolved this
            # ticker, otherwise the same honest "(last close)" fallback as
            # before â€” never silently pretend a stale price is live.
            _b_lp = _pk_live.get(_b["ticker"])
            if _b_lp:
                _b_up = (_b_lp.get("chg_pct") or 0) >= 0
                _b_pc = "#3ddc84" if _b_up else "#ef5350"
                _b_live_span = (
                    f'<span style="color:{_b_pc};font-weight:700">â‚¹{_b_lp["price"]:,.2f} '
                    f'{"â–²" if _b_up else "â–¼"}{abs(_b_lp.get("chg_pct") or 0):.2f}%</span>'
                    f' <span style="color:#666">live Â· qty in full analysis</span>'
                )
            else:
                _b_live_span = '<span style="color:#666">(last close â€” open full analysis for live price + qty)</span>'

            st.markdown(
                f'<div style="background:{_card_grad};'
                f'border-left:4px solid {_card_border};border-radius:10px;padding:11px 14px;margin-bottom:6px">'
                f'<div style="display:flex;justify-content:space-between;align-items:center">'
                f'<span><span style="font-size:16px;font-weight:700;color:#fff">{_bl}</span>{_grade_html}{_tier_badge}</span>'
                f'<span style="font-size:13px;font-weight:700;color:{_score_color}">{_b["score"]:.0f}/100 Â· {_b["action"]}</span>'
                f'</div>'
                f'<div style="font-size:11px;color:{_tt_col};font-weight:600;margin-top:3px">{_tt_emo} {_tt_lbl} setup</div>'
                f'<div style="font-size:12px;color:#bbb;margin-top:2px">{_b["headline"]}</div>'
                + (f'<div style="font-size:11px;color:#888;margin-top:4px">'
                   f'Entry â‚¹{_b["entry"]:,.2f} Â· SL â‚¹{_b["sl"]:,.2f} Â· TP â‚¹{_b["tp"]:,.2f} '
                   f'{_b_live_span}</div>'
                   if _b["entry"] else "")
                + (f'<div style="font-size:11px;color:#6a8caf;margin-top:2px">'
                   f'â± {_b.get("horizon")}'
                   + (f' Â· {_horizon_countdown(_b.get("valid_until"))}' if _b.get("valid_until") else '')
                   + '</div>'
                   if _b.get("horizon") else "")
                + '</div>',
                unsafe_allow_html=True,
            )
            if _b["entry"]:
                _paper_trade_popover(
                    _b["ticker"], _b["entry"], _b["sl"], _b["tp"],
                    reason=f"Top Pick: {_b['headline'][:55]}",
                    key=f"cc_pick_{_b['ticker']}",
                    label=f"ðŸ“Œ Paper Trade {_bl}",
                )
            render_pick_analysis(_b, key_prefix=f"cc_buy_{_b['ticker']}")
    with _pk_sell:
        st.markdown("#### ðŸ”´ Sell / Avoid")
        if not _picks["sells"]:
            st.caption("No clear sell signals â€” nothing flashing red in the scan.")
        for _sv in _picks["sells"]:
            _svl = _sv["ticker"].replace(".NS", "")
            # FIX CC-LIVE1: same bounded pattern as the Buy loop above â€”
            # price only, from the one shared _pk_live batch fetch already
            # done for every ticker on screen this rerun.
            _sv_lp = _pk_live.get(_sv["ticker"])
            if _sv_lp:
                _sv_up = (_sv_lp.get("chg_pct") or 0) >= 0
                _sv_pc = "#3ddc84" if _sv_up else "#ef5350"
                _sv_live_html = (
                    f'<div style="font-size:11px;margin-top:4px">'
                    f'<span style="color:{_sv_pc};font-weight:700">â‚¹{_sv_lp["price"]:,.2f} '
                    f'{"â–²" if _sv_up else "â–¼"}{abs(_sv_lp.get("chg_pct") or 0):.2f}%</span> '
                    f'<span style="color:#666">live</span></div>'
                )
            else:
                _sv_live_html = ""
            st.markdown(
                f'<div style="background:linear-gradient(135deg,#2a0a0a,#330f0f);'
                f'border-left:4px solid #ef5350;border-radius:10px;padding:11px 14px;margin-bottom:6px">'
                f'<div style="display:flex;justify-content:space-between;align-items:center">'
                f'<span style="font-size:16px;font-weight:700;color:#fff">{_svl}</span>'
                f'<span style="font-size:13px;font-weight:700;color:#ef5350">{_sv["score"]:.0f}/100 Â· {_sv["action"]}</span>'
                f'</div>'
                f'<div style="font-size:12px;color:#bbb;margin-top:3px">{_sv["headline"]}</div>'
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
    # â”€â”€ 3. OPEN POSITION ALERTS + AUTO-CLOSE â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    _cc_h1, _cc_h2 = st.columns([5, 2])
    _cc_h1.markdown("### ðŸ“Œ Open Positions")
    with _cc_h2:
        _cc_autoclose = st.toggle(
            "ðŸ¤– Auto-close CNC on SL/TP",
            value=st.session_state.get("auto_close_on", False),
            key="cc_autoclose_toggle",
            help="When ON, CNC (delivery) paper trades that hit their target or stop-loss are "
                 "closed automatically on page load (during market hours only, on live prices). "
                 "MIS (intraday) positions are ALWAYS squared off at 15:15 regardless of this toggle. "
                 "Real broker holdings are never auto-traded â€” only alerted.",
        )
        st.session_state["auto_close_on"] = _cc_autoclose
    
    _cc_sq_banner_shown = False
    if _is_squareoff_time():
        _sq_all_closed = _auto_close_breached()
        _sq_mis_closed = [c for c in _sq_all_closed if c["type"] == "squareoff"]
        if _sq_mis_closed:
            _render_autoclose_banner(_sq_mis_closed)
            # BUGFIX: only live prices need to be re-fetched after an auto-close â€”
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
        st.caption(f"âš ï¸ Couldn't load open paper positions ({_e}).")
    
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
            st.markdown("**âš ï¸ These positions need your attention:**")
    
        for _pos in _cc_alerts + _cc_normal_pos:
            _pbdr = {"target_hit": "#26a69a", "sl_hit": "#ef5350", "big_move": "#FF9800",
                     "normal": "#2196F3"}.get(_pos["status"], "#2196F3")
            _pbg  = {"target_hit": "#0a2a1a", "sl_hit": "#2a0a0a",  "big_move": "#1a1200",
                     "normal": "#0d1f3c"}.get(_pos["status"], "#0d1f3c")
            _purc = "#26a69a" if _pos["unr"] >= 0 else "#ef5350"
            _palert = {
                "target_hit": f"ðŸŽ¯ Target hit â€” close to lock in profit",
                "sl_hit":     f"ðŸš¨ Stop-loss breached â€” consider exiting to limit loss",
                "big_move":   f"{'ðŸ“ˆ' if _pos['unr_pct']>0 else 'ðŸ“‰'} Large move â€” review your stop and target",
            }.get(_pos["status"], "")
    
            _pc1, _pc2 = st.columns([5, 1])
            with _pc1:
                st.markdown(
                    f'<div style="background:{_pbg};border-left:5px solid {_pbdr};'
                    f'border-radius:10px;padding:11px 15px;margin-bottom:6px">'
                    f'<div style="display:flex;justify-content:space-between;align-items:center">'
                    f'<div><span style="font-size:16px;font-weight:700;color:#fff">'
                    f'{_pos["ticker"].replace(".NS","")}</span>'
                    f'<span style="font-size:11px;color:#888;margin-left:8px">ðŸ“‚ {_pos["account"]}</span>'
                    f'<span style="font-size:12px;color:#aaa;margin-left:8px">'
                    f'Entry â‚¹{_pos["ep"]:,.2f} â†’ Now â‚¹{_pos["cur"]:,.2f}</span></div>'
                    f'<div style="font-size:16px;font-weight:700;color:{_purc}">'
                    f'â‚¹{_pos["unr"]:+,.0f} ({_pos["unr_pct"]:+.1f}%)</div></div>'
                    + (f'<div style="font-size:13px;color:#ddd;margin-top:4px">{_palert}</div>' if _palert else '')
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
                        # prices for the remaining open positions â€” it doesn't
                        # need to invalidate Top Picks or watchlist scores too.
                        _portfolio_live_prices.clear()
                        st.rerun()
    

_render_open_positions_section()


# FIX CC-TRIM — the bottom "Watchlist — What to Do Today" section was removed
# from this page on request. It duplicated 14_my_watchlist.py, which is where
# per-name scoring now lives exclusively. Home page below is Top Picks +
# Open Positions + Background Alerts.


# â”€â”€ 5. BACKGROUND TELEGRAM ALERTS (viewer) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
st.markdown("---")
with st.expander("ðŸ”” Background Alerts (Telegram) â€” fire even when this app is closed", expanded=False):
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
                _al_show.columns = ["Stock", "When price goes", "Level (â‚¹)", "Note"]
                st.dataframe(_al_show, hide_index=True, width="stretch")
            else:
                st.info("No active price alerts. All rows are examples (enabled=0). "
                        "Set `enabled=1` on a row in data/alerts.csv to activate it.")
        else:
            st.info("No alerts.csv found yet.")
    except Exception as _ale:
        st.caption(f"Could not read alerts.csv: {_ale}")

    st.markdown(
        "**Also alerted automatically:** ðŸ”´ VIX entering fear/panic Â· ðŸ“‰ Nifty breaking into a downtrend.  \n"
        "**One-time setup:** create a Telegram bot via @BotFather, then add "
        "`TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` as GitHub Actions secrets "
        "(Settings â†’ Secrets and variables â†’ Actions)."
    )

# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# PAGE 1 â€” MY PORTFOLIO
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
