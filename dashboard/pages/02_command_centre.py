"""Command Centre - NSE Smart Investor (multipage page; body verbatim from app.py)."""
import os, sys
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
import streamlit as st
from dashboard.shared.design import apply_design
from dashboard.shared.nav import render_sidebar
from dashboard.shared.chart_helpers import render_top_bar
from dashboard.shared.picks_ui import render_pick_analysis
# P3: explicit imports (was a dynamic shared-namespace injection)
import os
import pandas as pd
import streamlit as st
import sys
import trade_store as _store
# Restored (these module-level imports sat inside the old globals() block and were
# dropped by the P3 transform; the page-smoke test caught the resulting NameError).
from data.universe import get_universe
from data.angel_fetcher import is_configured as _ao_is_configured
from dashboard.shared.design import (
    apply_design,
)
from dashboard.shared.cache import (
    _home_top_picks,
    _score_watchlist,
    _sector_ranks_tuple,
    _sparkline_closes,
    _sparkline_svg,
    _trade_type,
    get_vix_info,
)
from dashboard.shared.trade_utils import (
    _auto_close_breached,
    _paper_trade_popover,
    _portfolio_live_prices,
    _render_autoclose_banner,
    _suggest_position,
    paper_close_trade,
)
from dashboard.shared.chart_helpers import (
    _ROOT,
    render_top_bar,
)

apply_design()
render_sidebar(current="Command Centre")
render_top_bar()

# ───────────────────────── page body (de-indented from app.py) ─────────────────────────
st.title("🎯 Command Centre")
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
_mb_pos_txt = (f"You have <b style='color:#ff9500'>{_mb_open}</b> open paper position"
               f"{'s' if _mb_open != 1 else ''}." if _mb_open else
               "No open paper positions.")
st.markdown(
    f'<div class="glass-panel" style="margin-bottom:14px;display:flex;'
    f'justify-content:space-between;align-items:center;flex-wrap:wrap;gap:12px">'
    f'<div><div style="font-size:20px;font-weight:800;color:#f0f4ff">☀️ {_mb_greet}, Mrinal</div>'
    f'<div style="font-size:12px;color:#8899bb;margin-top:2px">{_mb_date}</div></div>'
    f'<div style="text-align:right">'
    f'<div style="font-size:13px;color:#e0e0e0">{_mb_focus[0]} {_mb_focus[1]}</div>'
    f'<div style="font-size:12px;color:#8899bb;margin-top:3px">{_mb_pos_txt} '
    f'Scroll for today\'s picks &amp; watchlist.</div></div>'
    f'</div>',
    unsafe_allow_html=True,
)

# ── 1. MARKET PULSE ────────────────────────────────────────────────────────
_cc_vix_info = get_vix_info()
_cc_vix_r = _cc_vix_info.get("regime", "unknown").lower()
_cc_vix_v = _cc_vix_info.get("vix")

# Nifty trend from cached daily bars
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
    "complacency": ("#FFC107", "😴", "COMPLACENT"), "normal":  ("#26a69a", "🟢", "CALM"),
    "elevated":    ("#FF9800", "🟡", "ELEVATED"),   "fear":    ("#ef5350", "🔴", "HIGH FEAR"),
    "panic":       ("#b71c1c", "🚨", "PANIC"),      "unknown": ("#9e9e9e", "❓", "UNKNOWN"),
}
_NT_LBL = {
    "uptrend":  ("#26a69a", "📈", "UPTREND"),  "downtrend": ("#ef5350", "📉", "DOWNTREND"),
    "sideways": ("#FFC107", "↔️", "SIDEWAYS"), "unknown":   ("#9e9e9e", "❓", "NO DATA"),
}
_vc, _vi, _vl = _VIX_LBL.get(_cc_vix_r, _VIX_LBL["unknown"])
_nc, _ni, _nl = _NT_LBL.get(_cc_nifty_trend, _NT_LBL["unknown"])

# Overall market verdict
if _cc_vix_r == "normal" and _cc_nifty_trend == "uptrend":
    _verd, _vbg, _vbdr = "✅ Good conditions — new positions okay", "#0a2a1a", "#26a69a"
elif _cc_vix_r in ("fear", "panic") or _cc_nifty_trend == "downtrend":
    _verd, _vbg, _vbdr = "🔴 Weak / fearful market — avoid new buys, protect capital", "#2a0a0a", "#ef5350"
elif _cc_vix_r == "complacency":
    _verd, _vbg, _vbdr = "😴 Market too calm — be selective, tighten stops", "#2a2000", "#FFC107"
else:
    _verd, _vbg, _vbdr = "🟡 Mixed signals — only high-conviction setups today", "#1a1a0a", "#FFC107"

st.markdown(
    f'<div style="display:flex;gap:12px;margin-bottom:4px">'
    f'<div style="flex:1;background:#0d1f3c;border-left:5px solid {_vc};border-radius:10px;padding:14px 16px">'
    f'<div style="font-size:10px;color:#888;text-transform:uppercase;letter-spacing:1px;margin-bottom:3px">India VIX</div>'
    f'<div style="font-size:20px;font-weight:700;color:{_vc}">{_vi} {_vl}</div>'
    f'<div style="font-size:12px;color:#bbb;margin-top:3px">{f"{_cc_vix_v:.1f}" if _cc_vix_v else "—"}</div>'
    f'</div>'
    f'<div style="flex:1;background:#0d1f3c;border-left:5px solid {_nc};border-radius:10px;padding:14px 16px">'
    f'<div style="font-size:10px;color:#888;text-transform:uppercase;letter-spacing:1px;margin-bottom:3px">Nifty 50</div>'
    f'<div style="font-size:20px;font-weight:700;color:{_nc}">{_ni} {_nl}</div>'
    f'<div style="font-size:12px;color:#bbb;margin-top:3px">'
    f'{f"{_cc_nifty_val:,.0f}" if _cc_nifty_val else "—"}'
    f'{f"&nbsp;({_cc_nifty_5d:+.1f}% 5d)" if _cc_nifty_val else ""}</div>'
    f'</div>'
    f'<div style="flex:2;background:{_vbg};border-left:5px solid {_vbdr};border-radius:10px;'
    f'padding:14px 16px;display:flex;align-items:center">'
    f'<div style="font-size:16px;font-weight:600;color:#fff">{_verd}</div>'
    f'</div>'
    f'</div>',
    unsafe_allow_html=True,
)
# ── Market Mood meter (Fear ↔ Greed composite) ─────────────────────────────
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
    f'<span style="font-size:13px;color:{_mood_c};font-weight:600"> · {_mood_lbl}</span></div>'
    f'</div>',
    unsafe_allow_html=True,
)

_cc_ref_c = st.columns([6, 1])[1]
if _cc_ref_c.button("🔄 Refresh", key="cc_refresh_pulse", use_container_width=True):
    st.cache_data.clear(); st.rerun()

st.markdown("---")

# ── Top Picks last-updated strip (Part 2) ─────────────────────────────
_scan_t = st.session_state.get("_picks_scan_time")
if _scan_t:
    st.markdown(
        f'<div style="background:#0d2a1a;border:1px solid #1a4a2a;border-radius:8px;'
        f'padding:7px 14px;margin-bottom:10px;display:flex;justify-content:space-between;'
        f'align-items:center">'
        f'<span style="font-size:12px;color:#4caf7d">📊 Top Picks last updated: '
        f'<b>{_scan_t}</b></span>'
        f'<span style="font-size:11px;color:#555">Refreshes every 30 min · '
        f'tap Scan Now to force refresh</span>'
        f'</div>',
        unsafe_allow_html=True,
    )

# ── 2. TODAY'S TOP PICKS — broad NSE scan (above open positions) ──────
_tp_h1, _tp_h2 = st.columns([5, 2])
with _tp_h1:
    st.markdown("### 🔥 Today's Top Picks — NSE Scan")
    st.caption("Best buy & sell setups scored across the **full liquid NSE universe** "
               "on trend + momentum + RSI + volume + sector + VIX. "
               "First scan ~2 min, then cached 30 min.")
with _tp_h2:
    st.write("")
    _run_picks = st.button("🔎 Scan Now", key="cc_run_picks", use_container_width=True)

_scan_univ = get_universe("nifty500")
with st.expander(f"📋 What's scanned? ({len(_scan_univ)} stocks)", expanded=False):
    st.caption(
        f"Top Picks scans the **full liquid NSE universe — {len(_scan_univ)} large/mid/"
        "small-caps** (Nifty 500 set) — scoring each on trend + momentum + RSI + volume "
        "+ sector strength + VIX. The strongest longs and the clearest SELL/EXITs are "
        "surfaced (10 each — buys and sells). First scan ~2 min; results cached 30 min, so reopening the "
        "page is instant.")

# Data-source badge — shows whether the scan is using the fast broker feed or fallback
try:
    if _ao_is_configured():
        st.caption("⚡ **Angel One configured** — the scan uses it first (Tier-0 broker "
                   "feed, throttled to its rate limit). Stooq/Yahoo are only a last-resort "
                   "fallback if an Angel call fails or its session has expired.")
    else:
        st.caption("ℹ️ **Using free sources** (Stooq → Yahoo). Set up **Angel One** on its "
                   "page for faster, more reliable scans.")
except Exception:
    pass

if _run_picks or st.session_state.get("cc_picks_loaded"):
    st.session_state["cc_picks_loaded"] = True
    with st.spinner("Scanning the full NSE universe — first run ~2 min, then cached…"):
        _sec_tuple = _sector_ranks_tuple()
        st.session_state["_sec_ranks_cache"] = _sec_tuple   # share with watchlist
        _picks = _home_top_picks(vix_regime=_cc_vix_r, sector_ranks=_sec_tuple)

    # ── Auto-update notification (Part 2): toast when a new scan completes ──
    import datetime as _dt
    _prev_scan = st.session_state.get("_picks_last_scan")
    _now_str = _dt.datetime.now().strftime("%H:%M")
    if _prev_scan != _now_str:
        st.session_state["_picks_last_scan"] = _now_str
        if _prev_scan is not None:        # don't toast on first load
            st.toast("🔄 Top Picks updated — new scan complete", icon="📊")
    st.session_state["_picks_scan_time"] = _now_str

    _pk_buy, _pk_sell = st.columns(2)
    with _pk_buy:
        st.markdown("#### 🟢 Buy Candidates")
        if not _picks["buys"]:
            st.caption("No strong buy setups today — market not offering clean entries.")
        for _b in _picks["buys"]:
            _bl = _b["ticker"].replace(".NS", "")
            _bs = _suggest_position(_b["entry"], _b["sl"]) if _b["entry"] else None
            _qty_txt = (f'<span style="color:#888;font-size:11px"> · suggest '
                        f'{_bs["qty"]} sh</span>') if _bs else ""
            _tt_lbl, _tt_emo, _tt_col = _trade_type(_b.get("headline", ""))
            _grade_tag = ("A+" if _b["score"] >= 88 else "A" if _b["score"] >= 75
                          else "B" if _b["score"] >= 62 else "")
            _grade_html = (f'<span style="background:{_tt_col}22;color:{_tt_col};border:1px solid {_tt_col};'
                           f'border-radius:5px;padding:1px 7px;font-size:10px;font-weight:700;margin-left:6px">'
                           f'GRADE {_grade_tag}</span>') if _grade_tag else ""
            st.markdown(
                f'<div style="background:linear-gradient(135deg,#0a2a1a,#0f3320);'
                f'border-left:4px solid #26a69a;border-radius:10px;padding:11px 14px;margin-bottom:6px">'
                f'<div style="display:flex;justify-content:space-between;align-items:center">'
                f'<span><span style="font-size:16px;font-weight:700;color:#fff">{_bl}</span>{_grade_html}</span>'
                f'<span style="font-size:13px;font-weight:700;color:#26a69a">{_b["score"]:.0f}/100 · {_b["action"]}</span>'
                f'</div>'
                f'<div style="font-size:11px;color:{_tt_col};font-weight:600;margin-top:3px">{_tt_emo} {_tt_lbl} setup</div>'
                f'<div style="font-size:12px;color:#bbb;margin-top:2px">{_b["headline"]}</div>'
                + (f'<div style="font-size:11px;color:#888;margin-top:4px">'
                   f'Entry ₹{_b["entry"]:,.2f} · SL ₹{_b["sl"]:,.2f} · TP ₹{_b["tp"]:,.2f}{_qty_txt}</div>'
                   if _b["entry"] else "")
                + '</div>',
                unsafe_allow_html=True,
            )
            if _b["entry"]:
                _paper_trade_popover(
                    _b["ticker"], _b["entry"], _b["sl"], _b["tp"],
                    reason=f"Top Pick: {_b['headline'][:55]}",
                    key=f"cc_pick_{_b['ticker']}",
                    label=f"📌 Paper Trade {_bl}",
                )
            # reason pointers + Deep Dive (narrative, score bars, Ask AI)
            render_pick_analysis(_b, key_prefix=f"cc_buy_{_b['ticker']}")
    with _pk_sell:
        st.markdown("#### 🔴 Sell / Avoid")
        if not _picks["sells"]:
            st.caption("No clear sell signals — nothing flashing red in the scan.")
        for _sv in _picks["sells"]:
            _svl = _sv["ticker"].replace(".NS", "")
            st.markdown(
                f'<div style="background:linear-gradient(135deg,#2a0a0a,#330f0f);'
                f'border-left:4px solid #ef5350;border-radius:10px;padding:11px 14px;margin-bottom:6px">'
                f'<div style="display:flex;justify-content:space-between;align-items:center">'
                f'<span style="font-size:16px;font-weight:700;color:#fff">{_svl}</span>'
                f'<span style="font-size:13px;font-weight:700;color:#ef5350">{_sv["score"]:.0f}/100 · {_sv["action"]}</span>'
                f'</div>'
                f'<div style="font-size:12px;color:#bbb;margin-top:3px">{_sv["headline"]}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )
            # reason pointers + Deep Dive (narrative, score bars, Ask AI)
            render_pick_analysis(_sv, key_prefix=f"cc_sell_{_sv['ticker']}")
else:
    st.info("Click **🔎 Scan Now** to find today's strongest buy & sell setups across NSE.")

st.markdown("---")

# ── 3. OPEN POSITION ALERTS + AUTO-CLOSE ───────────────────────────────────
_cc_h1, _cc_h2 = st.columns([5, 2])
_cc_h1.markdown("### 📌 Open Positions")
with _cc_h2:
    _cc_autoclose = st.toggle(
        "🤖 Auto-close on SL/TP", value=st.session_state.get("auto_close_on", True),
        key="cc_autoclose_toggle",
        help="When ON, paper trades that hit their target or stop-loss are "
             "closed automatically on page load (during market hours only, "
             "on live prices). Real broker holdings are never auto-traded — only alerted.",
    )
    st.session_state["auto_close_on"] = _cc_autoclose

# Run auto-close across ALL accounts, then show what was closed
if _cc_autoclose:
    _cc_closed = _auto_close_breached()
    if _cc_closed:
        _render_autoclose_banner(_cc_closed)
        st.cache_data.clear()

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
        _pbdr = {"target_hit": "#26a69a", "sl_hit": "#ef5350", "big_move": "#FF9800",
                 "normal": "#2196F3"}.get(_pos["status"], "#2196F3")
        _pbg  = {"target_hit": "#0a2a1a", "sl_hit": "#2a0a0a",  "big_move": "#1a1200",
                 "normal": "#0d1f3c"}.get(_pos["status"], "#0d1f3c")
        _purc = "#26a69a" if _pos["unr"] >= 0 else "#ef5350"
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
                f'<div><span style="font-size:16px;font-weight:700;color:#fff">'
                f'{_pos["ticker"].replace(".NS","")}</span>'
                f'<span style="font-size:11px;color:#888;margin-left:8px">📂 {_pos["account"]}</span>'
                f'<span style="font-size:12px;color:#aaa;margin-left:8px">'
                f'Entry ₹{_pos["ep"]:,.2f} → Now ₹{_pos["cur"]:,.2f}</span></div>'
                f'<div style="font-size:16px;font-weight:700;color:{_purc}">'
                f'₹{_pos["unr"]:+,.0f} ({_pos["unr_pct"]:+.1f}%)</div></div>'
                + (f'<div style="font-size:13px;color:#ddd;margin-top:4px">{_palert}</div>' if _palert else '')
                + '</div>',
                unsafe_allow_html=True,
            )
        with _pc2:
            if _pos["status"] in ("target_hit", "sl_hit"):
                if st.button("Close Now", key=f"cc_cl_{_pos['id']}",
                             use_container_width=True, type="primary"):
                    paper_close_trade(_pos["id"], _pos["cur"],
                                      "Closed via Command Centre")
                    st.cache_data.clear(); st.rerun()

st.markdown("---")

# ── 4. WATCHLIST DECISIONS ─────────────────────────────────────────────────
_cc_wl = st.session_state.get("watchlist", ["RELIANCE.NS", "TCS.NS", "HDFCBANK.NS"])
_wh1, _wh2 = st.columns([5, 2])
with _wh1:
    st.markdown("### ⭐ Watchlist — What to Do Today")
    st.caption("Scores update every 30 min. First load takes ~20-40 s while data is fetched.")
with _wh2:
    st.write("")
    if st.button("🔄 Re-score All", key="cc_rescore", use_container_width=True):
        st.cache_data.clear(); st.rerun()

# Speed: the watchlist uses the sector ranking only if it's already been
# computed this session (stored when Top Picks ran) — so the heavy ~10 s
# sector multi-fetch never blocks the Command Centre's first load.
_wl_sector = st.session_state.get("_sec_ranks_cache", ())
with st.spinner(f"Scoring your {len(_cc_wl)} watchlist stocks (parallel, cached 30 min)…"):
    _cc_scores = _score_watchlist(tuple(_cc_wl), _cc_vix_r, sector_ranks=_wl_sector)

# Sort: BUY signals first, EXIT last
_A_ORDER = {"STRONG BUY": 0, "BUY": 1, "WATCHLIST": 2,
            "HOLD": 3, "CAUTION": 4, "EXIT": 5, "UNAVAILABLE": 9}
_cc_sorted = sorted(_cc_wl, key=lambda t: _A_ORDER.get(
    _cc_scores.get(t, {}).get("action", "HOLD"), 3))

_ACT_STYLE = {
    "STRONG BUY": ("#26a69a", "🚀", "#0a2a1a"),
    "BUY":        ("#4CAF50", "🟢", "#0d2510"),
    "WATCHLIST":  ("#2196F3", "👀", "#0d1f3c"),
    "HOLD":       ("#9E9E9E", "🟡", "#1a1a1a"),
    "CAUTION":    ("#FF9800", "⚠️", "#1a1200"),
    "EXIT":       ("#ef5350", "🔴", "#2a0a0a"),
    "UNAVAILABLE":("#555555", "❓", "#111111"),
}

for _cct in _cc_sorted:
    _s     = _cc_scores.get(_cct, {})
    _act   = _s.get("action", "HOLD")
    _score = float(_s.get("score", 0))
    _hl    = _s.get("headline", "")
    _entry = float(_s.get("entry", 0))
    _sl    = float(_s.get("sl",    0))
    _tp    = float(_s.get("tp",    0))
    _rr    = float(_s.get("rr",    0))
    _price = float(_s.get("price", 0))

    _ac, _ai, _abg = _ACT_STYLE.get(_act, _ACT_STYLE["HOLD"])
    _lbl   = _cct.replace(".NS", "")
    _bar_w = min(int(_score), 100)

    # Price levels block (only shown for actionable signals)
    _price_block = ""
    if _act in ("STRONG BUY", "BUY", "EXIT", "WATCHLIST", "CAUTION") and _entry > 0:
        _sl_str = f'<span style="color:#ef5350">SL ₹{_sl:,.2f}</span>' if _sl else ""
        _tp_str = f'<span style="color:#26a69a">Target ₹{_tp:,.2f}</span>' if _tp else ""
        _price_block = (
            f'<div style="font-size:12px;color:#aaa;margin-top:6px">'
            f'Entry ₹{_entry:,.2f} &nbsp;·&nbsp; {_sl_str} &nbsp;·&nbsp; {_tp_str}'
            + (f' &nbsp;·&nbsp; <span style="color:#fff">R:R {_rr:.1f}:1</span>' if _rr > 0 else "")
            + '</div>'
        )

    _spark = _sparkline_svg(_sparkline_closes(_cct))   # 30-day mini chart
    _cc1, _cc2 = st.columns([5, 1])
    with _cc1:
        st.markdown(
            f'<div style="background:{_abg};border-left:5px solid {_ac};'
            f'border-radius:10px;padding:13px 16px;margin-bottom:6px">'
            f'<div style="display:flex;justify-content:space-between;align-items:flex-start">'
            f'<div style="flex:1">'
            f'<span style="font-size:18px;font-weight:700;color:#fff">{_lbl}</span>'
            f'&nbsp;&nbsp;<span style="font-size:14px;font-weight:700;color:{_ac}">{_ai} {_act}</span>'
            f'<div style="margin:5px 0 3px 0;display:flex;align-items:center;gap:8px">'
            f'<span style="font-size:12px;font-weight:700;color:{_ac}">{_score:.0f}/100</span>'
            f'<div style="width:120px;height:6px;background:#333;border-radius:3px">'
            f'<div style="width:{_bar_w}%;height:100%;background:{_ac};border-radius:3px"></div></div>'
            f'</div>'
            f'<div style="font-size:13px;color:#ccc">{_hl}</div>'
            f'{_price_block}'
            f'</div>'
            f'<div style="text-align:right;min-width:124px">'
            f'<div style="font-size:14px;color:#aaa">{"₹" + f"{_price:,.2f}" if _price else ""}</div>'
            f'<div style="margin-top:4px">{_spark}</div>'
            f'</div>'
            f'</div></div>',
            unsafe_allow_html=True,
        )
    with _cc2:
        if _act in ("STRONG BUY", "BUY") and _entry > 0:
            _paper_trade_popover(
                _cct, _entry, _sl, _tp,
                reason=f"Command Centre: {_hl[:60]}",
                key=f"cc_wl_{_cct}",
            )
        else:
            if st.button("🔍 Deep Dive", key=f"cc_dd_{_cct}",
                         use_container_width=True):
                st.session_state["analyze_ticker"] = _cct
                st.session_state["_goto_page"] ="🔍 Analyze Stock"
                st.rerun()

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
                st.dataframe(_al_show, hide_index=True, use_container_width=True)
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
