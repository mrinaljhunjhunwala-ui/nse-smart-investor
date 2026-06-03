"""dashboard/shared/nav.py - sidebar + grouped navigation (st.switch_page routing)."""
from __future__ import annotations
import os, sys, sqlite3, warnings, io, json, math, datetime
import numpy as np
import pandas as pd
import streamlit as st
warnings.filterwarnings('ignore')
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
import trade_store as _store


_NAV_GROUPS: dict = {
    "Home":      ["Command Centre"],
    "Markets":   ["Market Live", "Market Overview", "Market Breadth", "Macro Dashboard"],
    "Portfolio": ["My Portfolio", "Paper Trades", "My Watchlist"],
    "Trading":   ["Intraday Trader", "Smart Screener", "OI & Options"],
    "Analysis":  ["Analyze Stock", "Backtest", "Swing Checklist"],
    "Tools":     ["Position Sizer", "Angel One", "Investor Guide"],
}

_PAGE_EMOJI: dict = {
    "Command Centre":  "🎯",
    "Market Live":     "📡",
    "Market Overview": "📊",
    "Market Breadth":  "📈",
    "Macro Dashboard": "🌍",
    "Intraday Trader": "⚡",
    "Smart Screener":  "🔎",
    "OI & Options":    "🏦",
    "My Portfolio":    "🏠",
    "Paper Trades":    "📂",
    "My Watchlist":    "⭐",
    "Analyze Stock":   "🔍",
    "Backtest":        "🧪",
    "Swing Checklist": "✅",
    "Position Sizer":  "📐",
    "Angel One":       "🔗",
    "Investor Guide":  "📖",
}

_PAGE_FULL_NAME: dict = {
    "Command Centre":  "🎯 Command Centre",
    "Market Live":     "📡 Market Live",
    "Market Overview": "📊 Market Overview",
    "Market Breadth":  "📈 Market Breadth",
    "Macro Dashboard": "🌍 Macro Dashboard",
    "Intraday Trader": "⚡ Intraday Trader",
    "Smart Screener":  "🔎 Smart Screener",
    "OI & Options":    "🏦 OI & Options Setup",
    "My Portfolio":    "🏠 My Portfolio",
    "Paper Trades":    "📂 Paper Trades",
    "My Watchlist":    "⭐ My Watchlist",
    "Analyze Stock":   "🔍 Analyze Stock",
    "Backtest":        "🧪 Backtest",
    "Swing Checklist": "✅ Swing Checklist",
    "Position Sizer":  "📐 Position Sizer",
    "Angel One":       "🔗 Angel One",
    "Investor Guide":  "📖 Investor Guide",
}

_group_icons: dict = {
    "Home": "🎯", "Markets": "📊", "Trading": "⚡", "Portfolio": "💼",
    "Analysis": "🔍", "Tools": "🛠",
}



_PAGE_FILE = {
    "Market Live":     "pages/01_market_live.py",
    "Command Centre":  "pages/02_command_centre.py",
    "My Portfolio":    "pages/03_my_portfolio.py",
    "Analyze Stock":   "pages/04_analyze_stock.py",
    "Market Overview": "pages/05_market_overview.py",
    "Smart Screener":  "pages/06_smart_screener.py",
    "Paper Trades":    "pages/07_paper_trades.py",
    "Backtest":        "pages/08_backtest.py",
    "Macro Dashboard": "pages/09_macro_dashboard.py",
    "Market Breadth":  "pages/10_market_breadth.py",
    "OI & Options":    "pages/11_oi_options.py",
    "Intraday Trader": "pages/12_intraday_trader.py",
    "Position Sizer":  "pages/13_position_sizer.py",
    "Swing Checklist": "pages/14_swing_checklist.py",
    "My Watchlist":    "pages/15_my_watchlist.py",
    "Investor Guide":  "pages/16_investor_guide.py",
    "Angel One":       "pages/17_angel_one.py",
}


@st.cache_data(ttl=60, show_spinner=False)

def _qv_prices(tickers: tuple) -> dict:
    """Live prices for the sidebar quick-view."""
    try:
        from utils.live_price import get_live_prices_batch
        raw = get_live_prices_batch(list(tickers))
    except Exception:
        raw = {}
    res = {}
    for t in tickers:
        q = raw.get(t)
        if isinstance(q, dict) and q.get("price"):
            res[t] = {"price": q["price"], "prev": q["prev_close"], "chg": q["chg_pct"]}
    return res

@st.cache_data(ttl=600, show_spinner=False)

def _sidebar_all():
    """Fetch VIX + 4 macro instruments concurrently. Returns in <10s or gives up.

    Cloud-safe: uses Yahoo Finance JSON API directly (no yfinance library),
    which avoids the rate-limiting that hits yf.download() from datacenter IPs.
    """
    from utils.live_price import _yahoo_json_quote
    from concurrent.futures import ThreadPoolExecutor, wait as _wait

    symbols = {
        "^INDIAVIX": "vix",
        "^NSEI":     "Nifty",
        "^NSEBANK":  "BNifty",
        "GC=F":      "Gold",
        "BZ=F":      "Crude",
    }
    results = {}
    pool = ThreadPoolExecutor(max_workers=5)
    try:
        futs = {pool.submit(_yahoo_json_quote, sym): (sym, name)
                for sym, name in symbols.items()}
        done, _ = _wait(list(futs.keys()), timeout=12)
        for fut in done:
            sym, name = futs[fut]
            try:
                q = fut.result(timeout=0)
                if q:
                    results[name] = q   # {"price": float, "prev_close": float}
            except Exception:
                pass
    finally:
        pool.shutdown(wait=False)

    # Parse VIX
    vix_data = (None, None, "Unknown", "⚪")
    if "vix" in results:
        try:
            import math as _m
            val = results["vix"]["price"]
            prev= results["vix"]["prev_close"]
            chg = (val / prev - 1) * 100 if prev > 0 else 0.0
            if _m.isnan(val) or val <= 0:
                raise ValueError("VIX NaN")
            if val < 16:   reg, col = "Normal",   "🟢"
            elif val < 22: reg, col = "Elevated",  "🟡"
            elif val < 28: reg, col = "Fear",      "🔴"
            else:          reg, col = "PANIC",     "🔴"
            vix_data = (val, chg, reg, col)
        except Exception:
            pass

    # Parse macro pulse
    pulse = {}
    dp_map = {"Nifty": 0, "BNifty": 0, "Gold": 1, "Crude": 2}
    for name in ("Nifty", "BNifty", "Gold", "Crude"):
        if name in results:
            try:
                c  = results[name]["price"]
                pc = results[name]["prev_close"]
                pulse[name] = (c, (c / pc - 1) * 100 if pc > 0 else 0.0, dp_map[name])
            except Exception:
                pass

    return vix_data, pulse

def _persist_user_state():
    """Save watchlist + sizing settings to the store if they changed since last save."""
    try:
        import trade_store as _ts_p
        _snap = (
            tuple(st.session_state.get("watchlist", [])),
            st.session_state.get("trade_capital"),
            st.session_state.get("risk_pct"),
        )
        if st.session_state.get("_user_state_snapshot") != _snap:
            _ts_p.kv_set("watchlist", list(st.session_state.get("watchlist", [])))
            _ts_p.kv_set("trade_capital", st.session_state.get("trade_capital", 500_000))
            _ts_p.kv_set("risk_pct", st.session_state.get("risk_pct", 1.0))
            st.session_state["_user_state_snapshot"] = _snap
    except Exception:
        pass

@st.cache_data(ttl=60, show_spinner=False)

def _watchlist_prices(tickers_tuple: tuple) -> dict:
    from utils.live_price import get_live_prices_batch
    raw = get_live_prices_batch(list(tickers_tuple))
    out = {}
    for t in tickers_tuple:
        q = raw.get(t)
        if isinstance(q, dict) and q.get("price"):
            out[t] = q
    return out



def render_sidebar(current: str = None) -> None:
    """Render the full sidebar. `current` = this page's name (for routing)."""
    st.sidebar.title("NSE Smart Investor")
    st.sidebar.markdown("*AI-powered equity companion*")
    st.sidebar.markdown("---")

    # Two-level grouped navigation — Home + 5 sections

    # Emoji map for display

    # Restore old page key names for backward-compat with all elif checks below



    # ── Grouped navigation ───────────────────────────────────────────────────
    # The widgets are SYNCED to the page we're on each run (so the radio highlights
    # the current page and no spurious switch fires on a fresh/deep-linked load).
    # Navigation happens only via explicit user action: the on_change callbacks
    # below (radio = pick page, selectbox = jump to a section's first page) and the
    # _goto_page programmatic hook used by buttons across the app.
    def _nav_to(_name):
        _t = _PAGE_FILE.get(_name)
        if _t:
            st.switch_page(_t)

    # Callbacks only RECORD the desired target — they must not call st.switch_page /
    # st.rerun (those are no-ops inside a callback). The actual switch happens in the
    # script body below, after the widgets render.
    def _on_page_change():
        st.session_state['_nav_target'] = st.session_state.get('nav', '').split(' ', 1)[-1]

    def _on_group_change():
        _g = st.session_state.get('nav_group', '').split(' ', 1)[-1]
        if _g in _NAV_GROUPS:
            st.session_state['_nav_target'] = _NAV_GROUPS[_g][0]   # section's first page

    # Programmatic nav: a button elsewhere set _goto_page to a full page name.
    if st.session_state.get('_goto_page'):
        _goto = st.session_state.pop('_goto_page')
        _match = next((p for _g, _ps in _NAV_GROUPS.items() for p in _ps
                       if _goto in (f'{_PAGE_EMOJI[p]} {p}', _PAGE_FULL_NAME.get(p, p))), None)
        if _match and _match != current:
            _nav_to(_match)

    # Force both widgets to reflect the current page BEFORE they are instantiated.
    _cur_grp = next((_g for _g, _ps in _NAV_GROUPS.items() if current in _ps), None)
    if _cur_grp:
        st.session_state['nav_group'] = f'{_group_icons[_cur_grp]} {_cur_grp}'
        st.session_state['nav']       = f'{_PAGE_EMOJI[current]} {current}'

    st.sidebar.selectbox('Section', [f'{_group_icons[g]} {g}' for g in _NAV_GROUPS],
                         key='nav_group', label_visibility='collapsed',
                         on_change=_on_group_change)
    _selected_group = st.session_state['nav_group'].split(' ', 1)[1]
    st.sidebar.radio('Page', [f'{_PAGE_EMOJI[p]} {p}' for p in _NAV_GROUPS[_selected_group]],
                     key='nav', label_visibility='collapsed', on_change=_on_page_change)

    # Resolve a pending nav request HERE (valid in the body; a no-op inside a callback).
    _target = st.session_state.pop('_nav_target', None)
    if _target and _target != current:
        _nav_to(_target)


    # ── Portfolio quick-view (right under the nav — value + today's P&L) ───────────
    st.sidebar.markdown("---")
    with st.sidebar.expander("💼 Portfolio Quick View", expanded=True):
        try:
            import pathlib as _qpl
            _qcsv = _qpl.Path(_ROOT) / "portfolio.csv"
            _qsrc = st.session_state.get("_ao_portfolio_path") or (_qcsv if _qcsv.exists() else None)
            if _qsrc:
                _qdf = pd.read_csv(_qsrc)
                _qsyms = tuple((t if str(t).endswith(".NS") else f"{t}.NS")
                               for t in _qdf["ticker"].tolist())
                _qlp = _qv_prices(_qsyms)
                _q_val = _q_today = _q_total = _q_inv = 0.0
                _q_rows = []
                for _qr in _qdf.itertuples():
                    _qsym = _qr.ticker if str(_qr.ticker).endswith(".NS") else f"{_qr.ticker}.NS"
                    _ql = _qlp.get(_qsym, {})
                    _qcur = _ql.get("price")
                    _qty  = getattr(_qr, "quantity", 0)
                    _qbuy = getattr(_qr, "avg_buy_price", 0)
                    if _qcur:
                        _q_val   += _qcur * _qty
                        _q_inv   += _qbuy * _qty
                        _q_today += (_qcur - _ql.get("prev", _qcur)) * _qty
                        _q_total += (_qcur - _qbuy) * _qty
                        _q_rows.append((str(_qr.ticker).replace(".NS",""),
                                        (_qcur/_qbuy-1)*100 if _qbuy else 0))
                _tc = "#00d4aa" if _q_today >= 0 else "#ff4757"
                _oc = "#00d4aa" if _q_total >= 0 else "#ff4757"
                _op = (_q_total/_q_inv*100) if _q_inv else 0
                st.markdown(
                    f'<div style="font-size:11px;color:#4a5568;text-transform:uppercase;letter-spacing:1px">Value</div>'
                    f'<div style="font-size:22px;font-weight:800;color:#f0f4ff">₹{_q_val:,.0f}</div>'
                    f'<div style="display:flex;gap:14px;margin-top:6px">'
                    f'<div><div style="font-size:10px;color:#4a5568">TODAY</div>'
                    f'<div style="font-size:14px;font-weight:700;color:{_tc}">{"▲" if _q_today>=0 else "▼"} ₹{abs(_q_today):,.0f}</div></div>'
                    f'<div><div style="font-size:10px;color:#4a5568">OVERALL</div>'
                    f'<div style="font-size:14px;font-weight:700;color:{_oc}">{"▲" if _q_total>=0 else "▼"} ₹{abs(_q_total):,.0f} ({_op:+.1f}%)</div></div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
                if _q_rows:
                    _q_rows.sort(key=lambda x: -x[1])
                    _best, _worst = _q_rows[0], _q_rows[-1]
                    st.caption(f"🏆 {_best[0]} {_best[1]:+.1f}%  ·  🔻 {_worst[0]} {_worst[1]:+.1f}%")
                if st.button("📂 Open Full Portfolio", key="sb_open_portfolio", use_container_width=True):
                    st.session_state["_goto_page"] = "🏠 My Portfolio"
                    st.rerun()
            else:
                st.caption("No portfolio.csv found. Upload one on the My Portfolio page.")
        except Exception as _qe:
            st.caption(f"Quick view unavailable: {str(_qe)[:50]}")

    st.sidebar.markdown("---")

    # ── Sidebar live data — fetched in parallel with a hard 12-second timeout ────
    try:
        _vix_data, _pulse = _sidebar_all()
        vix_val, vix_chg, vix_reg, vix_col = _vix_data
    except Exception:
        vix_val, vix_chg, vix_reg, vix_col = None, None, "Unknown", "⚪"
        _pulse = {}

    if vix_val:
        chg_str = f"{vix_chg:+.1f}%"
        st.sidebar.markdown(
            f"**Market Fear Gauge (VIX)**  \n"
            f"{vix_col} **{vix_val:.2f}** ({chg_str})  \n"
            f"Regime: **{vix_reg}**"
        )
    else:
        st.sidebar.markdown("VIX: *—*")

    for name, (price, chg, dp) in _pulse.items():
        clr   = "#26a69a" if chg >= 0 else "#ef5350"
        arrow = "▲" if chg >= 0 else "▼"
        st.sidebar.markdown(
            f'<span style="font-size:11px"><b>{name}</b> '
            f'{price:,.{dp}f} '
            f'<span style="color:{clr}">{arrow}{abs(chg):.1f}%</span></span>',
            unsafe_allow_html=True,
        )

    st.sidebar.markdown("---")

    # ── Market status indicator ────────────────────────────────────────────────────
    try:
        from utils.market_hours import market_status as _mstatus
        _ms = _mstatus()
        st.sidebar.markdown(
            f"**NSE Market**  \n"
            f"{_ms['color']} **{_ms['status']}**  \n"
            f"<span style='font-size:11px'>{_ms['time_ist']} · {_ms['detail']}</span>",
            unsafe_allow_html=True,
        )
        if _ms["is_open"]:
            if st.sidebar.button("🔄 Refresh Prices", key="sidebar_refresh"):
                st.cache_data.clear()
                st.rerun()
    except Exception:
        pass

    # ── Angel One connection status ───────────────────────────────────────────────
    try:
        from data.angel_fetcher import is_configured as _ao_configured
        _ao_on = _ao_configured()
        if _ao_on:
            st.sidebar.markdown(
                '<span class="ao-badge-on">🔗 Angel One <b>Connected</b></span>',
                unsafe_allow_html=True,
            )
        else:
            st.sidebar.markdown(
                '<span class="ao-badge-off">🔗 Angel One  <b>Not connected</b> '
                '— go to Tools › Angel One to set up</span>',
                unsafe_allow_html=True,
            )
    except Exception:
        _ao_on = False

    st.sidebar.markdown("---")

    # ── Personal Watchlist ────────────────────────────────────────────────────────
    st.sidebar.markdown("#### 👀 My Watchlist")

    # Initialise watchlist in session state with 5 popular defaults
    # Initialise persisted user state (watchlist + sizing settings) from the store
    # once per session, so they survive page refreshes (and redeploys on Postgres).
    if "_user_state_loaded" not in st.session_state:
        try:
            import trade_store as _ts_init
            _saved_wl = _ts_init.kv_get("watchlist", None)
            st.session_state["watchlist"] = _saved_wl if _saved_wl else [
                "RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "INFY.NS", "SBIN.NS"
            ]
            st.session_state["trade_capital"] = float(_ts_init.kv_get("trade_capital", 500_000))
            st.session_state["risk_pct"]      = float(_ts_init.kv_get("risk_pct", 1.0))
        except Exception:
            st.session_state.setdefault("watchlist",
                ["RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "INFY.NS", "SBIN.NS"])
        st.session_state["_user_state_loaded"] = True

    if "watchlist" not in st.session_state:
        st.session_state["watchlist"] = [
            "RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "INFY.NS", "SBIN.NS"
        ]


    _wl_add_col, _wl_btn_col = st.sidebar.columns([3, 1])
    with _wl_add_col:
        _wl_input = st.text_input(
            "Add ticker", value="", placeholder="e.g. WIPRO",
            label_visibility="collapsed", key="wl_add_input"
        ).strip().upper()
    with _wl_btn_col:
        st.write("")
        _wl_add_clicked = st.button("＋", key="wl_add_btn", use_container_width=True)

    if _wl_add_clicked and _wl_input:
        _sym = _wl_input if _wl_input.endswith(".NS") else f"{_wl_input}.NS"
        if _sym not in st.session_state["watchlist"] and len(st.session_state["watchlist"]) < 12:
            st.session_state["watchlist"].append(_sym)

    # Fetch live prices for watchlist tickers
    _wl_tickers = tuple(st.session_state["watchlist"])
    try:
        _wl_prices = _watchlist_prices(_wl_tickers)
    except Exception:
        _wl_prices = {}

    _wl_to_remove = None
    for _wl_sym in list(st.session_state["watchlist"]):
        _wl_q   = _wl_prices.get(_wl_sym)
        _wl_label = _wl_sym.replace(".NS", "")
        _wl_c1, _wl_c2, _wl_c3 = st.sidebar.columns([2, 2, 1])
        _wl_c1.markdown(f"<span style='font-size:12px;font-weight:700'>{_wl_label}</span>",
                        unsafe_allow_html=True)
        if _wl_q:
            _wl_p   = _wl_q["price"]
            _wl_chg = _wl_q.get("chg_pct", 0.0)
            _wl_clr = "#26a69a" if _wl_chg >= 0 else "#ef5350"
            _wl_arr = "▲" if _wl_chg >= 0 else "▼"
            _wl_c2.markdown(
                f'<span style="font-size:11px">₹{_wl_p:,.1f} '
                f'<span style="color:{_wl_clr}">{_wl_arr}{abs(_wl_chg):.1f}%</span></span>',
                unsafe_allow_html=True,
            )
        else:
            _wl_c2.markdown('<span style="font-size:11px;color:#777">—</span>',
                            unsafe_allow_html=True)
        if _wl_c3.button("✕", key=f"wl_rm_{_wl_sym}", use_container_width=True):
            _wl_to_remove = _wl_sym

    if _wl_to_remove and _wl_to_remove in st.session_state["watchlist"]:
        st.session_state["watchlist"].remove(_wl_to_remove)
        st.rerun()

    # ── Notification bell (sidebar — visible on every page) ───────────────────────
    _notifs = []
    try:
        import trade_store as _nb
        _nb_open = _nb.fetch_open()
        if _nb_open is not None and not _nb_open.empty:
            _nb_syms = tuple(_nb_open["ticker"].tolist())
            _nb_lp = _qv_prices(_nb_syms)
            for _, _nr in _nb_open.iterrows():
                _ncur = _nb_lp.get(str(_nr["ticker"]), {}).get("price")
                if _ncur is None:
                    continue
                _nsl = float(_nr.get("sl", 0) or 0)
                _ntp = float(_nr.get("tp", 0) or 0)
                _nt = str(_nr["ticker"]).replace(".NS", "")
                if _ntp and _ncur >= _ntp:
                    _notifs.append(("🎯", f"{_nt} hit target ₹{_ntp:,.2f}", "#00d4aa"))
                elif _nsl and _ncur <= _nsl:
                    _notifs.append(("🚨", f"{_nt} hit stop ₹{_nsl:,.2f}", "#ff4757"))
    except Exception:
        pass
    try:
        from utils.vix import get_india_vix_regime as _nb_vix
        _nvr = _nb_vix().get("regime", "normal")
        if _nvr in ("fear", "panic"):
            _notifs.append(("🔴", f"Market in {_nvr.upper()} (VIX) — protect capital", "#ff4757"))
        elif _nvr == "complacency":
            _notifs.append(("😴", "VIX complacent — tighten stops", "#ff9500"))
    except Exception:
        pass

    st.sidebar.markdown("---")
    _nb_count = len(_notifs)
    _nb_color = "#ff4757" if any(c == "#ff4757" for _, _, c in _notifs) else ("#00d4aa" if _nb_count else "#4a5568")
    with st.sidebar.expander(f"🔔 Notifications ({_nb_count})", expanded=_nb_count > 0):
        if _notifs:
            for _ic, _msg, _col in _notifs:
                st.markdown(
                    f'<div style="border-left:3px solid {_col};background:rgba(255,255,255,.02);'
                    f'border-radius:6px;padding:7px 11px;margin:4px 0;font-size:12px;color:#d0d0d0">'
                    f'{_ic} {_msg}</div>', unsafe_allow_html=True)
            if st.button("🎯 Go to Command Centre", key="nb_goto_cc", use_container_width=True):
                st.session_state["_goto_page"] = "🎯 Command Centre"
                st.rerun()
        else:
            st.caption("✅ All clear — no positions at SL/TP, market calm.")

    # ── Sound + desktop alert on a NEW SL/TP hit (fires once per new alert) ────────
    try:
        _sltp = [m for _i, m, _c in _notifs if "hit target" in m or "hit stop" in m]
        _alert_key = "|".join(sorted(_sltp))
        if _sltp and st.session_state.get("_last_alert_key") != _alert_key:
            st.session_state["_last_alert_key"] = _alert_key
            import streamlit.components.v1 as _components
            _amsg = _sltp[0].replace('"', "'")[:90]
            _components.html(
                f"""<script>
                try {{
                    var ctx = new (window.AudioContext || window.webkitAudioContext)();
                    [880, 1175].forEach(function(f, i) {{
                        var o = ctx.createOscillator(), g = ctx.createGain();
                        o.frequency.value = f; o.connect(g); g.connect(ctx.destination);
                        g.gain.setValueAtTime(0.0001, ctx.currentTime + i*0.18);
                        g.gain.exponentialRampToValueAtTime(0.25, ctx.currentTime + i*0.18 + 0.02);
                        g.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + i*0.18 + 0.16);
                        o.start(ctx.currentTime + i*0.18); o.stop(ctx.currentTime + i*0.18 + 0.17);
                    }});
                }} catch(e) {{}}
                try {{
                    var show = function() {{ new Notification("📈 NSE Smart Investor", {{ body: "{_amsg}" }}); }};
                    if (window.Notification) {{
                        if (Notification.permission === "granted") show();
                        else if (Notification.permission !== "denied")
                            Notification.requestPermission().then(function(p) {{ if (p === "granted") show(); }});
                    }}
                }} catch(e) {{}}
                </script>""",
                height=0,
            )
    except Exception:
        pass

    # ── Position-sizing settings (drive all suggested quantities) ─────────────────
    st.sidebar.markdown("---")
    with st.sidebar.expander("⚙️ Position Sizing", expanded=False):
        st.caption("Used to suggest how many shares to buy on every Paper Trade button.")
        st.session_state["trade_capital"] = st.number_input(
            "Trading capital (₹)", min_value=10_000, max_value=100_000_000,
            value=int(st.session_state.get("trade_capital", 500_000)), step=10_000,
            key="sb_trade_capital",
            help="Your total trading capital. Suggested quantity is sized against this.",
        )
        st.session_state["risk_pct"] = st.slider(
            "Risk per trade (%)", min_value=0.25, max_value=5.0,
            value=float(st.session_state.get("risk_pct", 1.0)), step=0.25,
            key="sb_risk_pct",
            help="Max % of capital you're willing to lose if the stop-loss is hit. "
                 "1% is the common rule.",
        )
        _eg = st.session_state["trade_capital"] * st.session_state["risk_pct"] / 100
        st.caption(f"→ Risking up to **₹{_eg:,.0f}** per trade.")

    # Persist watchlist + sizing settings whenever they change (survives refresh)
    _persist_user_state()

    # ── Storage backend badge (paper trades persistence) ──────────────────────────
    try:
        import trade_store as _ts_badge
        if _ts_badge.backend_name() == "postgres":
            st.sidebar.caption("🟢 Paper trades: cloud DB (persistent)")
        else:
            st.sidebar.caption("🟡 Paper trades: local (resets on redeploy) — see dashboard/DB_SETUP.md")
    except Exception:
        pass

    st.sidebar.markdown("---")
    st.sidebar.markdown(
        "⚠️ *For educational use only.*  \n"
        "Not SEBI registered advice.  \n"
        "Past performance ≠ future results."
    )


