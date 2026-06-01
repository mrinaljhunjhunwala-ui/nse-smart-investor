"""
dashboard/app.py — NSE Smart Investor Platform
Streamlit web dashboard — 6-page non-trader friendly interface.

Pages:
    1. 🏠 My Portfolio    — Upload CSV → traffic-light health per holding
    2. 🔍 Analyze Stock   — Enter any NSE ticker → composite score + narrative
    3. 📊 Market Overview — India VIX gauge + top movers + sector heatmap
    4. 🔎 Smart Screener  — 4-screen scanner across NIFTY50/100/200/500
    5. 📂 Paper Trades    — Live paper trading log + journal export
    6. 🧪 Backtest        — Historical strategy performance

Run:
    streamlit run dashboard/app.py
"""

import os
import sys
import sqlite3
import warnings
import io

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
import streamlit as st

warnings.filterwarnings("ignore")

# ── ensure project root is on sys.path ───────────────────────────────────────
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="NSE Smart Investor",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── NSE Pro Design System — trading-dashboard-design skill applied ─────────────
st.markdown(
    """<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&family=JetBrains+Mono:wght@400;500&display=swap');

/* ── Global ──────────────────────────────────────────────────────────────── */
html, body, [class*="css"] {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif !important;
    -webkit-font-smoothing: antialiased;
}
.stApp {
    background: radial-gradient(ellipse 130% 60% at 50% -8%, #0f1e3d 0%, #070c18 65%) fixed;
}
.mono { font-family:'JetBrains Mono','Courier New',monospace !important; }

/* ── Cards ───────────────────────────────────────────────────────────────── */
.card-green, .card-yellow, .card-red, .card-blue, .card-purple, .card-orange {
    transition: transform .18s ease, box-shadow .18s ease;
}
.card-green:hover, .card-yellow:hover, .card-red:hover,
.card-blue:hover, .card-purple:hover, .card-orange:hover {
    transform: translateY(-3px);
}
.card-green  { background:linear-gradient(135deg,#061f16,#0a2e1f); border-left:3px solid #00d4aa; border-radius:12px; padding:16px 20px; margin:6px 0; box-shadow:0 4px 20px rgba(0,212,170,.12); }
.card-yellow { background:linear-gradient(135deg,#1f1500,#2e1f00); border-left:3px solid #ff9500; border-radius:12px; padding:16px 20px; margin:6px 0; box-shadow:0 4px 20px rgba(255,149,0,.12); }
.card-red    { background:linear-gradient(135deg,#1f0608,#2e0a0e); border-left:3px solid #ff4757; border-radius:12px; padding:16px 20px; margin:6px 0; box-shadow:0 4px 20px rgba(255,71,87,.12); }
.card-blue   { background:linear-gradient(135deg,#040e2a,#081633); border-left:3px solid #5b8def; border-radius:12px; padding:16px 20px; margin:6px 0; box-shadow:0 4px 20px rgba(91,141,239,.12); }
.card-purple { background:linear-gradient(135deg,#120820,#1c0d30); border-left:3px solid #a78bfa; border-radius:12px; padding:16px 20px; margin:6px 0; box-shadow:0 4px 20px rgba(167,139,250,.12); }
.card-orange { background:linear-gradient(135deg,#1f0e00,#2d1500); border-left:3px solid #ff9500; border-radius:12px; padding:16px 20px; margin:6px 0; }

/* ── Score & typography ───────────────────────────────────────────────────── */
.score-big    { font-size:56px; font-weight:900; letter-spacing:-2px; }
.signal-big   { font-size:22px; font-weight:700; letter-spacing:.3px; }
.narrative    { font-size:14px; line-height:1.75; color:#8899bb; }
.ticker-label { font-size:24px; font-weight:800; color:#f0f4ff; }

/* ── Pills ───────────────────────────────────────────────────────────────── */
.pill-green  { display:inline-block; background:rgba(0,212,170,.12); color:#00d4aa; border:1px solid rgba(0,212,170,.4); border-radius:20px; padding:3px 14px; font-size:12px; font-weight:600; }
.pill-red    { display:inline-block; background:rgba(255,71,87,.12); color:#ff4757; border:1px solid rgba(255,71,87,.4); border-radius:20px; padding:3px 14px; font-size:12px; font-weight:600; }
.pill-yellow { display:inline-block; background:rgba(255,149,0,.12); color:#ff9500; border:1px solid rgba(255,149,0,.4); border-radius:20px; padding:3px 14px; font-size:12px; font-weight:600; }
.pill-gray   { display:inline-block; background:rgba(255,255,255,.06); color:#8899bb; border:1px solid rgba(255,255,255,.12); border-radius:20px; padding:3px 14px; font-size:12px; }
.pill-blue   { display:inline-block; background:rgba(91,141,239,.12); color:#5b8def; border:1px solid rgba(91,141,239,.4); border-radius:20px; padding:3px 14px; font-size:12px; font-weight:600; }

/* ── Signal badges ───────────────────────────────────────────────────────── */
.badge-buy   { background:#004d35; color:#00d4aa; border:1px solid #00d4aa; border-radius:6px; padding:4px 14px; font-size:13px; font-weight:700; letter-spacing:.5px; display:inline-block; }
.badge-sell  { background:#4d0009; color:#ff4757; border:1px solid #ff4757; border-radius:6px; padding:4px 14px; font-size:13px; font-weight:700; letter-spacing:.5px; display:inline-block; }
.badge-hold  { background:#4d3800; color:#ff9500; border:1px solid #ff9500; border-radius:6px; padding:4px 14px; font-size:13px; font-weight:700; letter-spacing:.5px; display:inline-block; }
.badge-watch { background:#1a2540; color:#5b8def; border:1px solid #5b8def; border-radius:6px; padding:4px 14px; font-size:13px; font-weight:700; letter-spacing:.5px; display:inline-block; }

/* ── Angel One badges ────────────────────────────────────────────────────── */
.ao-badge-on  { background:linear-gradient(90deg,#061f10,#0a2e18); border:1px solid rgba(0,212,170,.4); border-radius:10px; padding:10px 14px; font-size:12px; color:#00d4aa; margin:4px 0; display:flex; align-items:center; gap:8px; }
.ao-badge-off { background:rgba(255,255,255,.02); border:1px solid rgba(255,255,255,.08); border-radius:10px; padding:10px 14px; font-size:12px; color:#4a5568; margin:4px 0; display:block; }

/* ── Streamlit metric override ───────────────────────────────────────────── */
[data-testid="stMetric"] {
    background: linear-gradient(135deg, #0d1526, #0a1120);
    border: 1px solid rgba(255,255,255,.05);
    border-radius: 12px; padding: 14px 18px;
    box-shadow: 0 2px 12px rgba(0,0,0,.3);
}
[data-testid="stMetricValue"] { font-weight:800; letter-spacing:-.5px; font-size:24px; }
[data-testid="stMetricLabel"] { font-size:11px; color:#4a5568; text-transform:uppercase; letter-spacing:1px; font-weight:600; }

/* ── Buttons ─────────────────────────────────────────────────────────────── */
.stButton > button {
    border-radius:10px; font-weight:600; letter-spacing:.2px;
    border: 1px solid rgba(255,255,255,.08); transition: all .15s ease;
    background: rgba(255,255,255,.04);
}
.stButton > button:hover { transform:translateY(-1px); filter:brightness(1.15); box-shadow:0 4px 15px rgba(0,0,0,.3); }
.stButton > button[kind="primary"] {
    background: linear-gradient(135deg,#1a5fbd,#1248a0); border:none;
    box-shadow: 0 4px 15px rgba(26,95,189,.35);
}

/* ── Tabs ────────────────────────────────────────────────────────────────── */
.stTabs [data-baseweb="tab-list"] {
    gap: 4px; background: rgba(255,255,255,.02);
    border-radius: 12px; padding: 4px;
    border: 1px solid rgba(255,255,255,.04);
}
.stTabs [data-baseweb="tab"] {
    border-radius: 9px; padding: 8px 18px; font-weight: 500;
    color: #4a5568; transition: all .15s;
}
.stTabs [aria-selected="true"] {
    background: #0d1526; font-weight: 700; color: #f0f4ff;
}

/* ── Sidebar ─────────────────────────────────────────────────────────────── */
[data-testid="stSidebar"] {
    background: linear-gradient(180deg,#070c18 0%,#050811 100%);
    border-right: 1px solid rgba(255,255,255,.04);
}
[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p {
    font-size: 13px; color: #8899bb;
}

/* ── Selectbox / inputs ──────────────────────────────────────────────────── */
[data-baseweb="select"] > div:first-child {
    background: #0d1526; border-color: rgba(255,255,255,.08) !important;
    border-radius: 8px;
}
.stTextInput > div > div > input {
    background: #0d1526; border-color: rgba(255,255,255,.08);
    border-radius: 8px; color: #f0f4ff;
}
.stNumberInput > div > div > input {
    background: #0d1526; border-color: rgba(255,255,255,.08);
    border-radius: 8px; color: #f0f4ff;
}

/* ── Expanders ───────────────────────────────────────────────────────────── */
[data-testid="stExpander"] {
    background: rgba(255,255,255,.02);
    border: 1px solid rgba(255,255,255,.05) !important;
    border-radius: 10px;
}

/* ── DataFrames ──────────────────────────────────────────────────────────── */
[data-testid="stDataFrame"] { border-radius: 10px; overflow: hidden; }
[data-testid="stDataFrame"] thead th {
    background: #0d1526 !important; color: #4a5568 !important;
    font-size: 11px; text-transform: uppercase; letter-spacing: .8px;
    font-weight: 600; border-bottom: 1px solid rgba(255,255,255,.06) !important;
}
[data-testid="stDataFrame"] tbody td { color: #c8d0e0 !important; }
[data-testid="stDataFrame"] tbody tr:hover td { background: rgba(91,141,239,.05) !important; }

/* ── Order form ──────────────────────────────────────────────────────────── */
.order-buy  { background:rgba(0,212,170,.06); border:1px solid rgba(0,212,170,.3); border-radius:12px; padding:18px; }
.order-sell { background:rgba(255,71,87,.06); border:1px solid rgba(255,71,87,.3); border-radius:12px; padding:18px; }

/* ── Custom metric box ───────────────────────────────────────────────────── */
.metric-box       { background:#0d1526; border-radius:12px; padding:16px; text-align:center; border:1px solid rgba(255,255,255,.04); }
.metric-val       { font-size:28px; font-weight:800; margin:4px 0; letter-spacing:-.5px; }
.metric-lbl       { font-size:11px; color:#4a5568; text-transform:uppercase; letter-spacing:1px; font-weight:600; }
.metric-delta-pos { color:#00d4aa; font-size:13px; font-weight:600; }
.metric-delta-neg { color:#ff4757; font-size:13px; font-weight:600; }

/* ── Section divider ─────────────────────────────────────────────────────── */
.sec-div { display:flex; align-items:center; gap:12px; margin:28px 0 18px; }
.sec-div-label { font-size:11px; font-weight:700; color:#3a4a6a; text-transform:uppercase; letter-spacing:1.5px; white-space:nowrap; }
.sec-div-line  { flex:1; height:1px; background:linear-gradient(90deg,rgba(255,255,255,.07),transparent); }

/* ── Glassmorphism panel ─────────────────────────────────────────────────── */
.glass-panel {
    background: rgba(255,255,255,.03);
    backdrop-filter: blur(12px);
    -webkit-backdrop-filter: blur(12px);
    border: 1px solid rgba(255,255,255,.07);
    border-radius: 16px; padding: 20px;
    box-shadow: 0 8px 32px rgba(0,0,0,.3), inset 0 1px 0 rgba(255,255,255,.06);
}

/* ── Scrollbars ──────────────────────────────────────────────────────────── */
::-webkit-scrollbar { width:6px; height:6px; }
::-webkit-scrollbar-thumb { background:#1e2d4a; border-radius:3px; }
::-webkit-scrollbar-thumb:hover { background:#2a3d5e; }
::-webkit-scrollbar-track { background:transparent; }

/* ── Alerts & info boxes ─────────────────────────────────────────────────── */
[data-testid="stAlert"] { border-radius: 10px; }

/* ── Animations ──────────────────────────────────────────────────────────── */
@keyframes pulse-green { 0%,100%{box-shadow:0 0 0 0 rgba(0,212,170,.3)} 50%{box-shadow:0 0 0 8px rgba(0,212,170,0)} }
@keyframes pulse-red   { 0%,100%{box-shadow:0 0 0 0 rgba(255,71,87,.3)}  50%{box-shadow:0 0 0 8px rgba(255,71,87,0)}  }
.pulse-green { animation:pulse-green 2s infinite; }
.pulse-red   { animation:pulse-red 2s infinite; }

@keyframes ticker-scroll { 0%{transform:translateX(0)} 100%{transform:translateX(-50%)} }
.ticker-wrap { overflow:hidden; border-top:1px solid rgba(255,255,255,.04); border-bottom:1px solid rgba(255,255,255,.04); padding:8px 0; margin:8px 0; }
.ticker-content { display:inline-block; white-space:nowrap; animation:ticker-scroll 80s linear infinite; font-size:13px; font-family:'JetBrains Mono','Courier New',monospace; }
.ticker-wrap:hover .ticker-content { animation-play-state:paused; }
</style>""",
    unsafe_allow_html=True,
)


# ── Design helper functions (NSE Pro — from trading-dashboard-design skill) ───
def _glass_metric(label: str, value: str, delta: str = "", delta_pos: bool = True) -> str:
    d_color = "#00d4aa" if delta_pos else "#ff4757"
    d_sym   = "▲" if delta_pos else "▼"
    d_html  = (f'<div style="font-size:12px;color:{d_color};margin-top:4px;font-weight:600">'
               f'{d_sym} {delta}</div>') if delta else ""
    return (
        f'<div class="glass-panel" style="text-align:center;min-height:80px">'
        f'<div style="font-size:11px;color:#4a5568;text-transform:uppercase;letter-spacing:1.2px;font-weight:600">{label}</div>'
        f'<div style="font-size:24px;font-weight:800;color:#f0f4ff;margin-top:6px;letter-spacing:-.5px">{value}</div>'
        f'{d_html}</div>'
    )

def _section_div(label: str, icon: str = "") -> None:
    st.markdown(
        f'<div class="sec-div"><div class="sec-div-label">{icon}&nbsp;{label}</div>'
        f'<div class="sec-div-line"></div></div>',
        unsafe_allow_html=True,
    )

def _spacer(size: str = "md") -> None:
    px = {"sm": "12px", "md": "24px", "lg": "40px"}.get(size, "24px")
    st.markdown(f'<div style="height:{px}"></div>', unsafe_allow_html=True)

def _signal_card(ticker, action, price, entry, stop, target, reason, score=None, sector="") -> str:
    COLORS = {
        "BUY":  ("#00d4aa","#004d35"),
        "SELL": ("#ff4757","#4d0009"),
        "HOLD": ("#ff9500","#4d3800"),
        "WATCH":("#5b8def","#1a2540"),
    }
    tc, bc = COLORS.get(action, COLORS["HOLD"])
    rr = (target - entry) / (entry - stop) if (entry - stop) > 0.01 else 0
    sc_html = (f'<div style="font-size:30px;font-weight:900;color:{tc}">{score}</div>'
               f'<div style="font-size:10px;color:#666">SCORE</div>') if score is not None else ""
    sect_html = (f'<span style="font-size:11px;color:#4a5568;font-weight:400;margin-left:8px">{sector}</span>'
                 if sector else "")
    return (
        f'<div style="background:linear-gradient(135deg,{bc}22,{bc}11);border:1px solid {tc}44;'
        f'border-left:4px solid {tc};border-radius:12px;padding:16px 20px;margin:8px 0;'
        f'display:flex;align-items:flex-start;gap:16px">'
        f'<div style="min-width:60px;text-align:center">{sc_html}'
        f'<div style="background:{bc};color:{tc};border:1px solid {tc};border-radius:6px;'
        f'padding:4px 10px;font-size:14px;font-weight:800;letter-spacing:1px;margin-top:4px">{action}</div></div>'
        f'<div style="flex:1">'
        f'<div style="font-size:18px;font-weight:800;color:#f0f4ff">{ticker}{sect_html}</div>'
        f'<div style="font-size:12px;color:#4a5568;margin:4px 0">{reason}</div>'
        f'<div style="display:flex;gap:20px;margin-top:10px;font-size:13px">'
        f'<div><span style="color:#4a5568;font-size:11px">LTP</span><br><b style="color:#c8d0e0">₹{price:.2f}</b></div>'
        f'<div><span style="color:#4a5568;font-size:11px">ENTRY</span><br><b style="color:#c8d0e0">₹{entry:.2f}</b></div>'
        f'<div><span style="color:#4a5568;font-size:11px">STOP</span><br><b style="color:#ff4757">₹{stop:.2f}</b></div>'
        f'<div><span style="color:#4a5568;font-size:11px">TARGET</span><br><b style="color:#00d4aa">₹{target:.2f}</b></div>'
        f'<div><span style="color:#4a5568;font-size:11px">R:R</span><br><b style="color:{tc}">{rr:.1f}x</b></div>'
        f'</div></div></div>'
    )


# ─────────────────────────────────────────────────────────────────────────────
# Sidebar — grouped navigation
# ─────────────────────────────────────────────────────────────────────────────
st.sidebar.title("NSE Smart Investor")
st.sidebar.markdown("*AI-powered equity companion*")
st.sidebar.markdown("---")

# Two-level grouped navigation — Home + 5 sections
_NAV_GROUPS: dict = {
    "Home":      ["Command Centre"],
    "Markets":   ["Market Live", "Market Overview", "Market Breadth", "Macro Dashboard"],
    "Portfolio": ["My Portfolio", "Paper Trades", "My Watchlist"],
    "Trading":   ["Intraday Trader", "Smart Screener", "OI & Options"],
    "Analysis":  ["Analyze Stock", "Backtest", "Swing Checklist"],
    "Tools":     ["Position Sizer", "Angel One", "Investor Guide"],
}

# Emoji map for display
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

# Restore old page key names for backward-compat with all elif checks below
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

_nav_group = st.sidebar.selectbox(
    "Section",
    [f"{_group_icons[g]} {g}" for g in _NAV_GROUPS],
    key="nav_group",
    label_visibility="collapsed",
)
_selected_group = _nav_group.split(" ", 1)[1]  # strip emoji

_page_short = st.sidebar.radio(
    "Page",
    [f"{_PAGE_EMOJI[p]} {p}" for p in _NAV_GROUPS[_selected_group]],
    key="nav",
    label_visibility="collapsed",
)
_page_key   = _page_short.split(" ", 1)[1]   # strip emoji prefix
page        = _PAGE_FULL_NAME.get(_page_key, _page_short)

# ── Portfolio quick-view (right under the nav — value + today's P&L) ───────────
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
                st.session_state["nav_group"] = "💼 Portfolio"
                st.session_state["nav"] = "🏠 My Portfolio"
                st.rerun()
        else:
            st.caption("No portfolio.csv found. Upload one on the My Portfolio page.")
    except Exception as _qe:
        st.caption(f"Quick view unavailable: {str(_qe)[:50]}")

st.sidebar.markdown("---")

# ── Sidebar live data — fetched in parallel with a hard 12-second timeout ────
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
            st.session_state["nav"] = "🎯 Command Centre"
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


# ─────────────────────────────────────────────────────────────────────────────
# Company name → ticker map  (used for search autocomplete)
# ─────────────────────────────────────────────────────────────────────────────
STOCK_SEARCH_MAP = {
    # Large-cap / Nifty 50
    "Reliance Industries": "RELIANCE.NS",
    "Tata Consultancy Services (TCS)": "TCS.NS",
    "HDFC Bank": "HDFCBANK.NS",
    "Bharti Airtel": "BHARTIARTL.NS",
    "ICICI Bank": "ICICIBANK.NS",
    "Infosys": "INFY.NS",
    "State Bank of India (SBI)": "SBIN.NS",
    "Hindustan Unilever (HUL)": "HINDUNILVR.NS",
    "ITC": "ITC.NS",
    "Larsen & Toubro (L&T)": "LT.NS",
    "Kotak Mahindra Bank": "KOTAKBANK.NS",
    "Axis Bank": "AXISBANK.NS",
    "Bajaj Finance": "BAJFINANCE.NS",
    "Asian Paints": "ASIANPAINT.NS",
    "Maruti Suzuki": "MARUTI.NS",
    "NTPC": "NTPC.NS",
    "ONGC": "ONGC.NS",
    "Wipro": "WIPRO.NS",
    "UltraTech Cement": "ULTRACEMCO.NS",
    "Titan Company": "TITAN.NS",
    "HCL Technologies": "HCLTECH.NS",
    "Sun Pharma": "SUNPHARMA.NS",
    "Power Grid": "POWERGRID.NS",
    "Coal India": "COALINDIA.NS",
    "Nestle India": "NESTLEIND.NS",
    "Bajaj Finserv": "BAJAJFINSV.NS",
    "Tata Motors (TMPV - PV)": "TMPV.NS",
    "Adani Enterprises": "ADANIENT.NS",
    "JSW Steel": "JSWSTEEL.NS",
    "Grasim Industries": "GRASIM.NS",
    "Tech Mahindra": "TECHM.NS",
    "IndusInd Bank": "INDUSINDBK.NS",
    "Cipla": "CIPLA.NS",
    "Dr. Reddy's Laboratories": "DRREDDY.NS",
    "Eicher Motors": "EICHERMOT.NS",
    "Hindalco Industries": "HINDALCO.NS",
    "BPCL": "BPCL.NS",
    "Divi's Laboratories": "DIVISLAB.NS",
    "Tata Consumer Products": "TATACONSUM.NS",
    "Britannia Industries": "BRITANNIA.NS",
    "Hero MotoCorp": "HEROMOTOCO.NS",
    "Apollo Hospitals": "APOLLOHOSP.NS",
    "Bajaj Auto": "BAJAJ-AUTO.NS",
    "SBI Life Insurance": "SBILIFE.NS",
    "HDFC Life Insurance": "HDFCLIFE.NS",
    "Tata Power": "TATAPOWER.NS",
    "Adani Ports": "ADANIPORTS.NS",
    "Mahindra & Mahindra (M&M)": "M&M.NS",
    "LTIMindtree": "LTIM.NS",
    "Shriram Finance": "SHRIRAMFIN.NS",
    # Nifty Next 50
    "Cholamandalam Finance": "CHOLAFIN.NS",
    "Muthoot Finance": "MUTHOOTFIN.NS",
    "HDFC AMC": "HDFCAMC.NS",
    "ICICI Lombard": "ICICIGI.NS",
    "ICICI Prudential Life": "ICICIPRULI.NS",
    "SBI Cards": "SBICARD.NS",
    "Persistent Systems": "PERSISTENT.NS",
    "Coforge": "COFORGE.NS",
    "Mphasis": "MPHASIS.NS",
    "L&T Technology Services": "LTTS.NS",
    "Bosch India": "BOSCHLTD.NS",
    "TVS Motor Company": "TVSMOTOR.NS",
    "Bharat Electronics (BEL)": "BEL.NS",
    "Siemens India": "SIEMENS.NS",
    "ABB India": "ABB.NS",
    "Havells India": "HAVELLS.NS",
    "Voltas": "VOLTAS.NS",
    "Cummins India": "CUMMINSIND.NS",
    "Torrent Pharma": "TORNTPHARM.NS",
    "Aurobindo Pharma": "AUROPHARMA.NS",
    "Mankind Pharma": "MANKIND.NS",
    "Marico": "MARICO.NS",
    "Dabur India": "DABUR.NS",
    "Godrej Consumer Products": "GODREJCP.NS",
    "Colgate Palmolive": "COLPAL.NS",
    "United Spirits (McDowell's)": "MCDOWELL-N.NS",
    "Trent": "TRENT.NS",
    "Nykaa (FSN E-Commerce)": "NYKAA.NS",
    "Ambuja Cements": "AMBUJACEM.NS",
    "ACC": "ACC.NS",
    "Oberoi Realty": "OBEROIRLTY.NS",
    "DLF": "DLF.NS",
    "Adani Green Energy": "ADANIGREEN.NS",
    "PFC (Power Finance)": "PFC.NS",
    "REC Limited": "RECLTD.NS",
    "Canara Bank": "CANBK.NS",
    "Bank of Baroda": "BANKBARODA.NS",
    "Vedanta": "VEDL.NS",
    "Pidilite Industries": "PIDILITIND.NS",
    "Berger Paints": "BERGEPAINT.NS",
    "Indus Towers": "INDUSTOWER.NS",
    "Zydus Lifesciences": "ZYDUSLIFE.NS",
    "Lupin": "LUPIN.NS",
    "Lodha (Macrotech)": "LODHA.NS",
    "IRCTC": "IRCTC.NS",
    "Info Edge (Naukri)": "NAUKRI.NS",
    "Eternal Ltd (Zomato)": "ETERNAL.NS",
    # Midcap / Popular stocks
    "IDFC First Bank": "IDFCFIRSTB.NS",
    "Federal Bank": "FEDERALBNK.NS",
    "Bandhan Bank": "BANDHANBNK.NS",
    "AU Small Finance Bank": "AUBANK.NS",
    "Punjab National Bank (PNB)": "PNB.NS",
    "Union Bank of India": "UNIONBANK.NS",
    "IDBI Bank": "IDBI.NS",
    "RBL Bank": "RBLBANK.NS",
    "KPIT Technologies": "KPITTECH.NS",
    "Tata Elxsi": "TATAELXSI.NS",
    "Cyient": "CYIENT.NS",
    "Angel One": "ANGELONE.NS",
    "Balkrishna Industries (BKT)": "BALKRISIND.NS",
    "Exide Industries": "EXIDEIND.NS",
    "Ashok Leyland": "ASHOKLEY.NS",
    "Motherson Sumi (Samvardhana)": "MOTHERSON.NS",
    "Alkem Laboratories": "ALKEM.NS",
    "Glenmark Pharma": "GLENMARK.NS",
    "Granules India": "GRANULES.NS",
    "Laurus Labs": "LAURUSLABS.NS",
    "IPCA Laboratories": "IPCALAB.NS",
    "GlaxoSmithKline Pharma": "GLAXO.NS",
    "Natco Pharma": "NATCOPHARM.NS",
    "Varun Beverages (VBL)": "VBL.NS",
    "Radico Khaitan": "RADICO.NS",
    "Emami": "EMAMILTD.NS",
    "Avenue Supermarts (DMart)": "DMART.NS",
    "IndiaMART": "INDIAMART.NS",
    "Ramco Cements": "RAMCOCEM.NS",
    "JK Cement": "JKCEMENT.NS",
    "Astral Poly Technik": "ASTRAL.NS",
    "APL Apollo Tubes": "APLAPOLLO.NS",
    "BHEL": "BHEL.NS",
    "RVNL (Rail Vikas Nigam)": "RVNL.NS",
    "KEC International": "KEC.NS",
    "Thermax": "THERMAX.NS",
    "NBCC India": "NBCC.NS",
    "Container Corporation (CONCOR)": "CONCOR.NS",
    "IRFC": "IRFC.NS",
    "IGL (Indraprastha Gas)": "IGL.NS",
    "MGL (Mahanagar Gas)": "MGL.NS",
    "Petronet LNG": "PETRONET.NS",
    "GAIL India": "GAIL.NS",
    "NHPC": "NHPC.NS",
    "SJVN": "SJVN.NS",
    "HPCL": "HPCL.NS",
    "Indian Oil (IOC)": "IOC.NS",
    "Suzlon Energy": "SUZLON.NS",
    "Hindustan Zinc": "HINDZINC.NS",
    "NMDC": "NMDC.NS",
    "SAIL (Steel Authority)": "SAIL.NS",
    "Godrej Properties": "GODREJPROP.NS",
    "Phoenix Mills": "PHOENIXLTD.NS",
    "Prestige Estates": "PRESTIGE.NS",
    "Sobha Developers": "SOBHA.NS",
    "Aarti Industries": "AARTIIND.NS",
    "Deepak Nitrite": "DEEPAKNITR.NS",
    "SRF": "SRF.NS",
    "CDSL (Depository)": "CDSL.NS",
    "BSE": "BSE.NS",
    "MCX (Multi Commodity Exchange)": "MCX.NS",
    "CAMS": "CAMS.NS",
    "Max Healthcare": "MAXHEALTH.NS",
    "Fortis Healthcare": "FORTIS.NS",
    "Dr. Lal PathLabs": "LALPATHLAB.NS",
    "Metropolis Healthcare": "METROPOLIS.NS",
    "Indian Hotels (Taj)": "INDHOTEL.NS",
    "Polycab India": "POLYCAB.NS",
    "Dixon Technologies": "DIXON.NS",
    "Page Industries (Jockey)": "PAGEIND.NS",
    "MRF": "MRF.NS",
    "Jubilant Foodworks (Dominos)": "JUBLFOOD.NS",
    "Tata Communications": "TATACOMM.NS",
    "Sun TV Network": "SUNTV.NS",
    "Manappuram Finance": "MANAPPURAM.NS",
    "Tatasteel": "TATASTEEL.NS",
    # User portfolio stocks
    "Balrampur Chini Mills": "BALRAMCHIN.NS",
    "Xchanging Solutions": "XCHANGING.NS",
    "Bajaj Hindusthan Sugar": "BAJAJHIND.NS",
    "Dhanlaxmi Bank": "DHANBANK.NS",
}

# Reverse lookup: ticker → display name
_TICKER_TO_NAME = {v: k for k, v in STOCK_SEARCH_MAP.items()}


def get_display_name(ticker: str) -> str:
    t = ticker if ticker.endswith(".NS") else ticker + ".NS"
    return _TICKER_TO_NAME.get(t, ticker.replace(".NS", ""))


def _plain_english(action: str, entry: float, sl: float, tp: float, rr: float) -> str:
    """One-line 'what this means + what to do' for non-traders."""
    risk_amt = entry - sl
    rew_amt  = tp - entry
    if action in ("STRONG BUY", "BUY"):
        return (f"✅ <b>Looks like a good buy.</b> If you want in, buy near "
                f"<b>₹{entry:,.2f}</b>. Set a stop-loss at <b>₹{sl:,.2f}</b> — that's your "
                f"exit if it goes wrong (max loss ≈ ₹{risk_amt:,.2f}/share). Aim to take "
                f"profit near <b>₹{tp:,.2f}</b> (≈ ₹{rew_amt:,.2f}/share gain). "
                f"You're risking 1 to make {rr:.1f}.")
    if action == "WATCHLIST":
        return ("👀 <b>Not a buy yet.</b> It's close but not strong enough — add it to your "
                "watchlist and wait for it to firm up before committing money.")
    if action == "HOLD":
        return ("🟡 <b>Hold, don't add.</b> If you already own it, keep holding. But this isn't "
                "a good level to put fresh money in.")
    if action == "CAUTION":
        return ("⚠️ <b>Be careful.</b> Momentum is fading. If you own it, consider trimming or "
                "tightening your stop. Not a place to buy more.")
    if action == "EXIT":
        return ("🔴 <b>Weak — avoid buying.</b> If you own it, consider selling and moving the "
                "money to a stronger stock. The trend is against it right now.")
    return ("This stock is in a neutral zone — no strong edge either way. Wait for a clearer setup.")


def _trade_type(headline: str) -> tuple:
    """
    Categorise a setup into a trade type from its narrative headline.
    Returns (label, emoji, color). Zero extra data needed.
    """
    h = (headline or "").lower()
    if any(k in h for k in ("breakout", "52-week high", "52w high", "new high", "all-time high")):
        return ("Breakout", "🚀", "#00d4aa")
    if any(k in h for k in ("oversold", "bounce", "reversal", "support")):
        return ("Oversold Bounce", "🔄", "#5b8def")
    if any(k in h for k in ("momentum", "uptrend", "above sma", "strong trend", "trending")):
        return ("Momentum", "📈", "#ff9500")
    if any(k in h for k in ("pullback", "dip")):
        return ("Pullback", "🎯", "#a78bfa")
    return ("Trend", "•", "#8899bb")


# ─────────────────────────────────────────────────────────────────────────────
# Shared helpers
# ─────────────────────────────────────────────────────────────────────────────

@st.cache_data(ttl=300)
def load_ticker_df(ticker: str, period: str = "2y") -> pd.DataFrame:
    """
    Fetch OHLCV + compute all technical indicators.

    Always fetches at least 2 years so that SMA_200, RSI(14), MACD(26) etc.
    are valid at the *most recent* row.  The UI chart period controls what
    slice is *displayed*, not how much data is loaded.
    """
    from data.fetcher import fetch_single
    from utils.indicators import add_all_indicators
    df = fetch_single(ticker, period=period)
    df = add_all_indicators(df)
    # Drop warm-up rows where core indicators are NaN so iloc[-1] is always valid
    df.dropna(subset=["RSI", "ATR", "SMA_200"], inplace=True)
    return df


def _trim_to_period(df: pd.DataFrame, period: str) -> pd.DataFrame:
    """
    Return a date-sliced copy of df matching the UI display period.
    Indicators were computed on the full dataset so they remain accurate
    at the most-recent row after slicing.
    """
    if df.empty:
        return df
    last_ts = df.index[-1]
    _DAYS = {"1d": 8, "5d": 12, "1m": 35, "6m": 185, "1y": 375, "2y": 740}
    if period in _DAYS:
        cutoff = last_ts - pd.Timedelta(days=_DAYS[period])
        return df[df.index >= cutoff]
    if period == "ytd":
        return df[df.index >= pd.Timestamp(last_ts.year, 1, 1)]
    return df  # "max" or anything else → full history


@st.cache_data(ttl=600)
def load_vix_data():
    """Load VIX + Nifty daily history via Stooq (no rate limits on cloud)."""
    from data.fetcher import fetch_single
    try:
        vix   = fetch_single("^INDIAVIX", period="1y")
    except Exception:
        vix   = pd.DataFrame()
    try:
        nifty = fetch_single("^NSEI", period="1y")
    except Exception:
        nifty = pd.DataFrame()
    return vix, nifty


@st.cache_data(ttl=600)
def get_vix_info():
    # Route through utils.vix — has 10-min TTL and proper crumb auth
    # (trading.signals had a missing urllib.request import bug)
    try:
        from utils.vix import get_india_vix_regime
        return get_india_vix_regime()
    except Exception:
        return {"vix": 18.0, "regime": "normal", "allow_buy": True, "vix_pct_chg": 0.0}


@st.cache_data(ttl=1800, show_spinner=False)   # 30-min cache — powers Command Centre
def _score_for_cc(ticker: str, vix_regime: str = "normal") -> dict:
    """Score one stock for Command Centre. Pass vix_regime so we don't re-fetch VIX 5×."""
    try:
        import sys, os as _os
        sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
        from analysis.score import score_stock
        _vix_info = {
            "regime": vix_regime, "vix": None,
            "allow_buy": vix_regime not in ("fear", "panic"),
        }
        s = score_stock(ticker, vix_info=_vix_info)
        return {
            "ticker": ticker, "price": s.price,
            "score": s.score, "grade": s.grade, "action": s.action,
            "headline": s.headline, "entry": s.entry,
            "sl": s.stop_loss, "tp": s.target, "rr": s.risk_reward,
        }
    except Exception as _e:
        return {
            "ticker": ticker, "price": 0, "score": 0, "grade": "?",
            "action": "UNAVAILABLE",
            "headline": f"Data unavailable ({type(_e).__name__}: {str(_e)[:70]})",
            "entry": 0, "sl": 0, "tp": 0, "rr": 0,
        }


@st.cache_data(ttl=1800, show_spinner=False)   # 30-min cache, whole watchlist
def _score_watchlist(tickers: tuple, vix_regime: str = "normal", sector_ranks: tuple = ()) -> dict:
    """
    Score a whole watchlist IN PARALLEL (one thread per stock) and cache the
    result for 30 min. Calls score_stock directly (not the cached single-stock
    wrapper) so it is safe to run inside worker threads. Sector strength is
    folded in via sector_ranks. Returns {ticker: score_dict}.
    """
    import concurrent.futures as _cf
    import sys, os as _os
    sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))

    _vix = {"regime": vix_regime, "vix": None,
            "allow_buy": vix_regime not in ("fear", "panic")}
    _sec_df = _sector_df_from_tuple(sector_ranks)

    def _one(tk):
        try:
            from analysis.score import score_stock
            s = score_stock(tk, vix_info=_vix, sector_scores_df=_sec_df)
            return tk, {"ticker": tk, "price": s.price, "score": s.score,
                        "grade": s.grade, "action": s.action, "headline": s.headline,
                        "entry": s.entry, "sl": s.stop_loss, "tp": s.target, "rr": s.risk_reward}
        except Exception as e:
            return tk, {"ticker": tk, "price": 0, "score": 0, "grade": "?",
                        "action": "UNAVAILABLE",
                        "headline": f"Data unavailable ({type(e).__name__})",
                        "entry": 0, "sl": 0, "tp": 0, "rr": 0}

    out: dict = {}
    if not tickers:
        return out
    try:
        with _cf.ThreadPoolExecutor(max_workers=min(8, max(1, len(tickers)))) as ex:
            for tk, sc in ex.map(_one, tickers):
                out[tk] = sc
    except Exception:
        for tk in tickers:
            _tk, _sc = _one(tk)
            out[_tk] = _sc
    return out


# Curated liquid large/mid-cap universe for the home-page "Top Picks" scan.
# Kept ~36 names so a full scan finishes fast (Angel One: ~15-25 s) and stays cached.
_HOME_SCAN_UNIVERSE = [
    "RELIANCE.NS","TCS.NS","HDFCBANK.NS","ICICIBANK.NS","INFY.NS","SBIN.NS",
    "BHARTIARTL.NS","LT.NS","ITC.NS","AXISBANK.NS","KOTAKBANK.NS","HINDUNILVR.NS",
    "BAJFINANCE.NS","MARUTI.NS","SUNPHARMA.NS","TATAMOTORS.NS","NTPC.NS","TITAN.NS",
    "ULTRACEMCO.NS","ASIANPAINT.NS","WIPRO.NS","ADANIENT.NS","JSWSTEEL.NS","POWERGRID.NS",
    "TATASTEEL.NS","HCLTECH.NS","ONGC.NS","COALINDIA.NS","BAJAJFINSV.NS","TECHM.NS",
    "DRREDDY.NS","CIPLA.NS","HINDALCO.NS","GRASIM.NS","EICHERMOT.NS","TRENT.NS",
]


def _sector_df_from_tuple(sector_ranks: tuple):
    """Rebuild a sector-rank DataFrame (index=sector, col=Rank) from a hashable tuple."""
    if not sector_ranks:
        return None
    try:
        return pd.DataFrame(
            [{"Rank": int(r)} for _, r in sector_ranks],
            index=[str(s) for s, _ in sector_ranks],
        )
    except Exception:
        return None


@st.cache_data(ttl=1800, show_spinner=False)   # 30-min cache
def _home_top_picks(vix_regime: str = "normal", n: int = 5, sector_ranks: tuple = ()) -> dict:
    """
    Scan a curated NSE large/mid-cap universe and return the strongest
    BUY candidates and the clearest SELL/EXIT candidates for the day.

    Each stock's CompositeScore folds in trend, momentum, RSI, volume, VIX
    sentiment AND sector strength (via sector_ranks) — "self-analysis +
    volatility" in one number. Returns {"buys": [...], "sells": [...]}.
    """
    import concurrent.futures as _cf
    import sys, os as _os
    sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
    buys, sells = [], []

    _vix = {"regime": vix_regime, "vix": None,
            "allow_buy": vix_regime not in ("fear", "panic")}
    _sec_df = _sector_df_from_tuple(sector_ranks)

    def _one(tk):
        """Score directly via score_stock (not the cached wrapper) — safe in threads."""
        try:
            from analysis.score import score_stock
            s = score_stock(tk, vix_info=_vix, sector_scores_df=_sec_df)
            return {"ticker": tk, "price": s.price, "score": s.score,
                    "grade": s.grade, "action": s.action, "headline": s.headline,
                    "entry": s.entry, "sl": s.stop_loss, "tp": s.target, "rr": s.risk_reward}
        except Exception:
            return {"ticker": tk, "price": 0, "score": 0, "grade": "?",
                    "action": "UNAVAILABLE", "headline": "", "entry": 0,
                    "sl": 0, "tp": 0, "rr": 0}

    results = []
    try:
        with _cf.ThreadPoolExecutor(max_workers=8) as ex:
            results = list(ex.map(_one, _HOME_SCAN_UNIVERSE))
    except Exception:
        results = [_one(tk) for tk in _HOME_SCAN_UNIVERSE]

    for s in results:
        act = s.get("action", "")
        if act in ("STRONG BUY", "BUY") and s.get("score", 0) > 0:
            buys.append(s)
        elif act in ("EXIT", "CAUTION") and s.get("score", 0) > 0:
            sells.append(s)

    buys.sort(key=lambda x: -x.get("score", 0))
    sells.sort(key=lambda x: x.get("score", 0))   # lowest score = weakest
    return {"buys": buys[:n], "sells": sells[:n]}


@st.cache_data(ttl=3600, show_spinner=False)   # 1-hour cache — heavy multi-fetch
def _sector_ranking():
    """
    Rank all NSE sectors by constituent momentum (cached 1 h). Returns a
    DataFrame indexed by sector with a 'Rank' column for score_stock(), or None.
    """
    try:
        from analysis.sector_strength import rank_sectors
        return rank_sectors()
    except Exception:
        return None


def _sector_ranks_tuple() -> tuple:
    """Hashable ((sector, rank), …) form of _sector_ranking() for cached scorers."""
    df = _sector_ranking()
    if df is None or df.empty:
        return ()
    try:
        return tuple((str(idx), int(row["Rank"])) for idx, row in df.iterrows())
    except Exception:
        return ()


@st.cache_data(ttl=600)
def get_composite_score(ticker: str):
    """
    Deep-dive score over a 2-YEAR lookback (was 1y). The longer window means
    every signal is computed on a full, valid history — SMA_200 (296 valid rows
    vs ~49 on 1y), RSI divergence, candlestick patterns, ADX, volume trend and
    momentum all have enough warmup, so the composite reflects real multi-signal
    analysis, not just the latest bar. Sector strength + VIX are folded in too.
    """
    from analysis.score import score_stock
    vix_info = get_vix_info()
    sectors  = _sector_ranking()
    return score_stock(ticker, period="2y", vix_info=vix_info,
                       sector_scores_df=sectors)


@st.cache_data(ttl=600, show_spinner=False)
def _deep_confirmation(ticker: str) -> dict:
    """
    Confirmation layer on top of the composite score:
      • Multi-timeframe — weekly trend (filters daily false signals)
      • Relative strength — 1-month return vs Nifty (is it a leader?)
      • Earnings proximity — days to next result (avoid buying into a gap)
      • Signal agreement — how many of 9 checks are bullish (conviction)
    """
    out = {"weekly": None, "rel_strength": None, "rs_pct": None,
           "earnings_days": None, "bull": 0, "total": 0, "signals": []}
    try:
        from data.fetcher import fetch_single
        from utils.indicators import add_all_indicators
        df  = add_all_indicators(fetch_single(ticker, period="2y")).dropna(axis=1, how="all")
        cur = df.iloc[-1]
        price = float(cur["Close"])

        # Weekly trend
        wk = df["Close"].resample("W").last().dropna()
        if len(wk) >= 11:
            _wma10 = float(wk.rolling(10).mean().iloc[-1])
            _wkchg = (wk.iloc[-1] / wk.iloc[-5] - 1) * 100 if len(wk) >= 5 else 0
            out["weekly"] = ("uptrend" if wk.iloc[-1] > _wma10 and _wkchg > 0
                             else "downtrend" if wk.iloc[-1] < _wma10 and _wkchg < 0
                             else "sideways")

        # Relative strength vs Nifty (1 month ≈ 22 sessions)
        try:
            nf = fetch_single("^NSEI", period="6mo")["Close"].dropna()
            if len(nf) >= 22 and len(df) >= 22:
                _s1 = (price / float(df["Close"].iloc[-22]) - 1) * 100
                _n1 = (float(nf.iloc[-1]) / float(nf.iloc[-22]) - 1) * 100
                out["rs_pct"] = round(_s1 - _n1, 1)
                out["rel_strength"] = "outperforming" if out["rs_pct"] > 0 else "underperforming"
        except Exception:
            pass

        # Earnings proximity
        try:
            from data.events import get_earnings_date
            import datetime as _ed_dt
            ed = get_earnings_date(ticker)
            if ed:
                out["earnings_days"] = (ed - _ed_dt.datetime.now()).days
        except Exception:
            pass

        # Signal agreement (9 checks)
        rsi = float(cur.get("RSI", 50))
        sigs = [
            ("RSI not overbought (<70)",  rsi < 70),
            ("MACD above signal",         float(cur.get("MACD", 0)) > float(cur.get("MACD_Signal", 0))),
            ("Above 20-day avg",          price > float(cur.get("SMA_20", price * 1.1))),
            ("Above 50-day avg",          price > float(cur.get("SMA_50", price * 1.1))),
            ("Above 200-day avg",         price > float(cur.get("SMA_200", price * 1.1))),
            ("Trend has strength (ADX>20)", float(cur.get("ADX", 0)) > 20),
            ("Volume supportive",         float(cur.get("Volume_Ratio", 1)) >= 1.0),
            ("No bearish divergence",     not bool(cur.get("RSI_Bear_Div", 0))),
            ("Weekly trend not down",     out["weekly"] != "downtrend"),
        ]
        out["signals"] = sigs
        out["bull"]    = sum(1 for _, ok in sigs if ok)
        out["total"]   = len(sigs)
    except Exception:
        pass
    return out


@st.cache_data(ttl=1800, show_spinner=False)
def _sparkline_closes(ticker: str, n: int = 22) -> list:
    """Last `n` daily closes for a mini sparkline (cached 30 min)."""
    try:
        from data.fetcher import fetch_single
        c = fetch_single(ticker, period="3mo")["Close"].dropna().tolist()
        return [round(float(x), 2) for x in c[-n:]]
    except Exception:
        return []


def _sparkline_svg(prices: list, w: int = 120, h: int = 28) -> str:
    """Inline SVG sparkline from a price list — green if up over the window, else red."""
    if not prices or len(prices) < 2:
        return ""
    lo, hi = min(prices), max(prices)
    rng = (hi - lo) or 1
    pts = " ".join(
        f"{i/(len(prices)-1)*w:.1f},{h - (p-lo)/rng*(h-4) - 2:.1f}"
        for i, p in enumerate(prices)
    )
    col = "#00d4aa" if prices[-1] >= prices[0] else "#ff4757"
    return (f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}" style="display:block">'
            f'<polyline points="{pts}" fill="none" stroke="{col}" stroke-width="1.6" '
            f'stroke-linejoin="round" stroke-linecap="round"/></svg>')


def load_trades_db(path: str = "trades.db") -> pd.DataFrame:
    if not os.path.exists(path):
        return pd.DataFrame()
    with sqlite3.connect(path) as conn:
        try:
            return pd.read_sql_query("SELECT * FROM trades ORDER BY id DESC", conn)
        except Exception:
            return pd.DataFrame()


# ── Paper-trade storage — delegates to trade_store (SQLite default, Postgres
#    if DATABASE_URL/secrets configured). `path` kept for signature compat. ────
import trade_store as _store


def load_trades_by_account(account: str, path: str = "trades.db") -> pd.DataFrame:
    """Load trades filtered to a specific paper trading account."""
    return _store.load_by_account(account)


def _ensure_paper_db(path: str = "trades.db"):
    """Ensure the trades schema exists on the active backend."""
    _store.ensure_schema()


def paper_list_accounts(path: str = "trades.db") -> list:
    """Return sorted list of distinct account names."""
    return _store.list_accounts()


def paper_rename_account(old_name: str, new_name: str, path: str = "trades.db"):
    """Rename an account across all its trades."""
    _store.rename_account(old_name, new_name)


def paper_delete_account(name: str, path: str = "trades.db"):
    """Delete all trades in an account."""
    _store.delete_account(name)


def paper_open_trade(ticker: str, price: float, qty: int,
                     sl: float, tp: float, reason: str = "",
                     account: str = "My Account",
                     path: str = "trades.db") -> int:
    """Insert a new paper BUY trade. Returns new row id."""
    return _store.open_trade(ticker, price, qty, sl, tp, reason=reason, account=account)


def paper_close_trade(trade_id: int, exit_price: float,
                      reason: str = "Manual close", path: str = "trades.db"):
    """Close an open paper trade by ID."""
    _store.close_trade(trade_id, exit_price, reason=reason)


def paper_edit_trade(trade_id: int, sl: float = None, tp: float = None,
                     reason: str = None, path: str = "trades.db"):
    """Edit stop-loss, target, or reason of an open trade."""
    _store.edit_trade(trade_id, sl=sl, tp=tp, reason=reason)


# ── Account product type (CNC = delivery, MIS = intraday) ─────────────────────
def paper_account_type(name: str) -> str:
    """Return 'MIS' (intraday) or 'CNC' (delivery) for an account; default CNC."""
    try:
        return _store.kv_get(f"acct_type:{name}", "CNC") or "CNC"
    except Exception:
        return "CNC"


def set_paper_account_type(name: str, atype: str) -> None:
    try:
        _store.kv_set(f"acct_type:{name}", "MIS" if str(atype).upper().startswith("MIS")
                      or "INTRA" in str(atype).upper() else "CNC")
    except Exception:
        pass


@st.cache_data(ttl=60, show_spinner=False)
def _portfolio_live_prices(tickers: tuple) -> dict:
    """
    Live prices for portfolio holdings via Yahoo Finance JSON API (cloud-safe).
    Falls back to Stooq EOD if Yahoo is unavailable.
    """
    from utils.live_price import get_live_prices_batch
    raw = get_live_prices_batch(list(tickers))
    results = {}
    for t in tickers:
        q = raw.get(t)
        if isinstance(q, dict) and q.get("price"):
            results[t] = {
                "price": q["price"],
                "prev":  q["prev_close"],
                "chg":   q["chg_pct"],
            }
    return results


def _action_color(action: str) -> str:
    if action in ("STRONG BUY", "BUY"):
        return "card-green"
    elif action in ("WATCHLIST", "HOLD"):
        return "card-yellow"
    else:
        return "card-red"


def _action_emoji(action: str) -> str:
    return {
        "STRONG BUY": "🚀", "BUY": "🟢", "WATCHLIST": "👀",
        "HOLD": "🟡", "CAUTION": "⚠️", "EXIT": "🔴",
    }.get(action, "")


def _grade_color(grade: str) -> str:
    return {"A+": "#26a69a", "A": "#4CAF50", "B": "#8BC34A",
            "C": "#FFC107", "D": "#FF5722", "F": "#f44336"}.get(grade, "#9E9E9E")


# ─────────────────────────────────────────────────────────────────────────────
# Position sizing — risk-based qty suggestion (used by auto-open paper trades)
# ─────────────────────────────────────────────────────────────────────────────

def _suggest_position(entry: float, sl: float,
                      capital: float = None,
                      risk_pct: float = None,
                      max_alloc_pct: float = 20.0) -> dict:
    """
    Suggest share quantity for a trade using fixed-fractional risk sizing.

    Sizes so that (entry - sl) × qty ≈ risk_pct% of capital, then caps the
    position at max_alloc_pct% of capital so a single name can't dominate.

    capital / risk_pct default to the user's settings in session_state
    (set in the sidebar), falling back to ₹5,00,000 and 1%.

    Returns: {qty, price, risk_per_share, capital_at_risk, position_value, basis}
    """
    if capital is None:
        capital = float(st.session_state.get("trade_capital", 500_000.0))
    if risk_pct is None:
        risk_pct = float(st.session_state.get("risk_pct", 1.0))
    entry = float(entry or 0)
    sl    = float(sl or 0)
    if entry <= 0:
        return {"qty": 1, "price": entry, "risk_per_share": 0,
                "capital_at_risk": 0, "position_value": entry, "basis": "fallback"}

    risk_amount = capital * (risk_pct / 100.0)
    rps = abs(entry - sl)
    if rps > 0.01:
        qty_risk = int(risk_amount / rps)
        basis = f"{risk_pct:.0f}% risk (₹{risk_amount:,.0f}) ÷ ₹{rps:.2f}/share"
    else:
        qty_risk = int(risk_amount / entry)   # no valid stop → notional sizing
        basis = "notional (no valid stop)"

    # Cap at max allocation
    qty_cap = int((capital * max_alloc_pct / 100.0) / entry)
    qty = max(1, min(qty_risk, qty_cap))
    if qty == qty_cap < qty_risk:
        basis += f" · capped at {max_alloc_pct:.0f}% allocation"

    return {
        "qty":             qty,
        "price":           round(entry, 2),
        "risk_per_share":  round(rps, 2),
        "capital_at_risk": round(rps * qty, 0),
        "position_value":  round(entry * qty, 0),
        "basis":           basis,
    }


def _paper_trade_popover(ticker: str, entry: float, sl: float, tp: float,
                         reason: str, key: str, label: str = "📌 Paper Trade") -> None:
    """
    Render a popover that lets the user review & adjust quantity (pre-filled
    with the risk-based suggestion) BEFORE opening a paper trade.

    Confirmation uses st.toast so feedback survives the popover closing on rerun.
    """
    sugg  = _suggest_position(entry, sl)
    _tlbl = ticker.replace(".NS", "")
    _cap  = float(st.session_state.get("trade_capital", 500_000.0))
    _rkp  = float(st.session_state.get("risk_pct", 1.0))
    with st.popover(label, use_container_width=True):
        st.markdown(f"**{_tlbl}** — open paper trade")
        st.caption(
            f"💡 Suggested **{sugg['qty']} shares** — sizes your loss-to-stop to "
            f"≈{_rkp:.2g}% of ₹{_cap:,.0f} (₹{sugg['capital_at_risk']:,.0f} at risk). "
            f"Change capital & risk in the sidebar; adjust qty below."
        )
        qty = st.number_input(
            "Quantity (shares)", min_value=1, max_value=1_000_000,
            value=int(sugg["qty"]), step=1, key=f"{key}_qty",
        )
        _val  = qty * entry
        _risk = abs(entry - (sl or entry)) * qty
        _c1, _c2, _c3 = st.columns(3)
        _c1.metric("Entry", f"₹{entry:,.2f}")
        _c2.metric("Position", f"₹{_val:,.0f}")
        _c3.metric("At Risk", f"₹{_risk:,.0f}")
        if sl or tp:
            st.caption(f"🛑 SL ₹{(sl or 0):,.2f}  ·  🎯 Target ₹{(tp or 0):,.2f}")
        if st.button("✅ Confirm & Open", key=f"{key}_confirm",
                     type="primary", use_container_width=True):
            _id = paper_open_trade(
                ticker, float(entry), int(qty), sl=sl, tp=tp, reason=reason,
                account=st.session_state.get("pt_account", "My Account"),
            )
            st.toast(f"📌 Opened #{_id}: {int(qty)} × {_tlbl} @ ₹{entry:,.2f}", icon="✅")
            st.cache_data.clear()
            st.rerun()


def _auto_close_breached(account: str = None, path: str = "trades.db") -> list:
    """
    Auto-close any OPEN paper trade whose live price has crossed its TP or SL.
    Paper trades only — never touches real broker positions.

    Only runs during NSE market hours: outside hours the live-price feed falls
    back to EOD close, which could falsely trip a stop/target. Returns a list of
    dicts describing what was closed. Caller reruns if the list is non-empty.
    """
    closed = []
    # Guard: only auto-close on live intraday prices, never on stale EOD data
    try:
        from utils.market_hours import market_status as _msx
        if not _msx().get("is_open", False):
            return closed
    except Exception:
        pass
    try:
        rows = _store.fetch_open(account)
        if rows.empty:
            return closed

        syms = tuple(rows["ticker"].tolist())
        lp   = _portfolio_live_prices(syms)

        for _, r in rows.iterrows():
            tk  = str(r["ticker"])
            ep  = float(r.get("price", 0) or 0)
            qty = int(r.get("quantity", 0) or 0)
            sl  = float(r.get("sl", 0) or 0) or None
            tp  = float(r.get("tp", 0) or 0) or None
            cur = lp.get(tk, {}).get("price")
            if cur is None or ep <= 0:
                continue

            hit = None
            if tp and cur >= tp:
                hit, exit_px, why = "target", tp, "Auto-closed: target reached"
            elif sl and cur <= sl:
                hit, exit_px, why = "stop", sl, "Auto-closed: stop-loss hit"
            if hit:
                paper_close_trade(int(r["id"]), exit_px, why, path=path)
                closed.append({
                    "ticker": tk.replace(".NS", ""), "type": hit,
                    "exit": exit_px, "pnl": (exit_px - ep) * qty,
                    "account": str(r.get("account", "My Account")),
                })
    except Exception:
        pass
    return closed


def _render_autoclose_banner(closed: list) -> None:
    """Show a prominent banner listing trades that were just auto-closed."""
    if not closed:
        return
    _rows = ""
    for c in closed:
        _ic  = "🎯" if c["type"] == "target" else "🛑"
        _col = "#26a69a" if c["pnl"] >= 0 else "#ef5350"
        _rows += (
            f'<div style="display:flex;justify-content:space-between;'
            f'padding:5px 0;border-bottom:1px solid rgba(255,255,255,.06);font-size:13px">'
            f'<span style="color:#eee">{_ic} <b>{c["ticker"]}</b> '
            f'<span style="color:#888">({c["account"]})</span> — '
            f'{"target reached" if c["type"]=="target" else "stop-loss hit"} '
            f'@ ₹{c["exit"]:,.2f}</span>'
            f'<span style="color:{_col};font-weight:700">₹{c["pnl"]:+,.0f}</span></div>'
        )
    st.markdown(
        f'<div style="background:linear-gradient(135deg,#1a1200,#2d1f00);'
        f'border:1px solid #FFC107;border-radius:12px;padding:14px 18px;margin-bottom:14px">'
        f'<div style="font-size:14px;font-weight:700;color:#FFC107;margin-bottom:6px">'
        f'🔔 {len(closed)} position{"s" if len(closed)!=1 else ""} auto-closed on SL/TP</div>'
        f'{_rows}</div>',
        unsafe_allow_html=True,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Macro / Breadth helpers  (for new pages 7–9)
# ─────────────────────────────────────────────────────────────────────────────

@st.cache_data(ttl=600)
def load_macro_data():
    """
    Fetch 3-month daily history for macro instruments.
    NSE indices via fetch_single() (Stooq first).
    Commodities/FX via Yahoo Finance JSON history (cloud-safe direct HTTP).
    """
    import json, io, datetime, urllib.request
    from data.fetcher import fetch_single

    data = {}

    # Indian index series — Stooq handles these reliably
    index_map = {
        "Nifty 50":  "^NSEI",
        "BankNifty": "^NSEBANK",
        "India VIX": "^INDIAVIX",
    }
    for name, sym in index_map.items():
        try:
            df = fetch_single(sym, period="3mo")
            if not df.empty:
                data[name] = df["Close"]
        except Exception:
            pass

    # Commodities / FX — use Yahoo Finance JSON history (v8 chart API)
    commodity_map = {
        "Gold ($/oz)": "GC=F",
        "Brent Crude": "BZ=F",
        "USD/INR":     "USDINR=X",
        "DXY":         "DX-Y.NYB",
    }
    for name, sym in commodity_map.items():
        try:
            url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}"
                   "?interval=1d&range=3mo")
            req = urllib.request.Request(
                url, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=10) as r:
                raw = json.loads(r.read())
            res = raw["chart"]["result"][0]
            ts  = res["timestamp"]
            cl  = res["indicators"]["quote"][0]["close"]
            df  = pd.DataFrame({"Close": cl},
                               index=pd.to_datetime(ts, unit="s")).dropna()
            if not df.empty:
                data[name] = df["Close"]
        except Exception:
            pass

    return pd.DataFrame(data).dropna(how="all")


_NIFTY50_TICKERS = (
    "RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "ICICIBANK.NS", "BHARTIARTL.NS",
    "INFY.NS", "SBIN.NS", "HINDUNILVR.NS", "ITC.NS", "LT.NS",
    "BAJFINANCE.NS", "HCLTECH.NS", "MARUTI.NS", "SUNPHARMA.NS", "ADANIENT.NS",
    "KOTAKBANK.NS", "TITAN.NS", "ONGC.NS", "NTPC.NS", "AXISBANK.NS",
    "WIPRO.NS", "ULTRACEMCO.NS", "ASIANPAINT.NS", "BAJAJFINSV.NS", "POWERGRID.NS",
    "M&M.NS", "NESTLEIND.NS", "JSWSTEEL.NS", "TMPV.NS", "TATASTEEL.NS",
    "TECHM.NS", "GRASIM.NS", "BPCL.NS", "ADANIPORTS.NS", "CIPLA.NS",
    "BRITANNIA.NS", "EICHERMOT.NS", "DRREDDY.NS", "HINDALCO.NS", "COALINDIA.NS",
    "DIVISLAB.NS", "TATACONSUM.NS", "SBILIFE.NS", "APOLLOHOSP.NS", "HDFCLIFE.NS",
    "INDUSINDBK.NS", "HEROMOTOCO.NS", "BAJAJ-AUTO.NS", "ETERNAL.NS", "SHRIRAMFIN.NS",
)


@st.cache_data(ttl=900)  # 15-min cache
def compute_market_breadth(tickers: tuple):
    """
    Fetch 1-year OHLCV for each ticker via Stooq (no rate limits) in parallel,
    then compute advance/decline, SMA positions, and 52-week extremes.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from data.fetcher import fetch_single

    tickers_list = list(tickers)

    def _fetch_one(t):
        try:
            return t, fetch_single(t, period="1y")
        except Exception:
            return t, None

    data_map = {}
    with ThreadPoolExecutor(max_workers=10) as pool:
        futs = {pool.submit(_fetch_one, t): t for t in tickers_list}
        for fut in as_completed(futs, timeout=45):
            try:
                t, df = fut.result(timeout=0)
                if df is not None and not df.empty:
                    data_map[t] = df
            except Exception:
                pass

    adv = dec = above_20 = above_50 = above_200 = near_hi = near_lo = counted = 0
    for t in tickers_list:
        try:
            df = data_map.get(t)
            if df is None or len(df) < 10:
                continue
            close = df["Close"]
            curr  = float(close.iloc[-1])
            prev  = float(close.iloc[-2])
            counted += 1
            if curr > prev:
                adv += 1
            else:
                dec += 1
            if len(df) >= 20 and curr > float(close.rolling(20).mean().iloc[-1]):
                above_20 += 1
            if len(df) >= 50 and curr > float(close.rolling(50).mean().iloc[-1]):
                above_50 += 1
            if len(df) >= 200 and curr > float(close.rolling(200).mean().iloc[-1]):
                above_200 += 1
            high52 = float(df["High"].max())
            low52  = float(df["Low"].min())
            if (high52 - curr) / max(high52, 1) * 100 < 5:
                near_hi += 1
            if (curr - low52) / max(low52, 1) * 100 < 5:
                near_lo += 1
        except Exception:
            continue

    n = max(counted, 1)
    return {
        "advance":       adv,
        "decline":       dec,
        "total":         counted,
        "ad_ratio":      round(adv / max(dec, 1), 2),
        "pct_above_20":  round(above_20  / n * 100, 1),
        "pct_above_50":  round(above_50  / n * 100, 1),
        "pct_above_200": round(above_200 / n * 100, 1),
        "near_52w_high": near_hi,
        "near_52w_low":  near_lo,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Shared chart builder
# ─────────────────────────────────────────────────────────────────────────────

def build_price_chart(df: pd.DataFrame, ticker: str) -> go.Figure:
    """
    4-panel trading chart: Price (candlestick + SMAs + BB) / Volume / RSI / MACD.
    Matches the layout of professional trading terminals.
    """
    fig = make_subplots(
        rows=4, cols=1, shared_xaxes=True,
        row_heights=[0.52, 0.14, 0.17, 0.17],
        vertical_spacing=0.02,
        subplot_titles=[f"{ticker} — Price", "Volume", "RSI (14)", "MACD"],
    )

    # ── Row 1: Candlestick ──────────────────────────────────────────────────
    fig.add_trace(go.Candlestick(
        x=df.index, open=df["Open"], high=df["High"],
        low=df["Low"], close=df["Close"],
        name="OHLC",
        increasing_line_color="#26a69a", increasing_fillcolor="#26a69a",
        decreasing_line_color="#ef5350", decreasing_fillcolor="#ef5350",
    ), row=1, col=1)

    if "BB_Upper" in df.columns:
        fig.add_trace(go.Scatter(
            x=df.index, y=df["BB_Upper"],
            line=dict(color="rgba(100,160,255,0.4)", dash="dash", width=1),
            name="BB Upper", showlegend=False,
        ), row=1, col=1)
        fig.add_trace(go.Scatter(
            x=df.index, y=df["BB_Lower"],
            fill="tonexty", fillcolor="rgba(100,160,255,0.06)",
            line=dict(color="rgba(100,160,255,0.4)", dash="dash", width=1),
            name="BB Lower", showlegend=False,
        ), row=1, col=1)

    for sma, color in [("SMA_20", "#FF9800"), ("SMA_50", "#2196F3"), ("SMA_200", "#9C27B0")]:
        if sma in df.columns:
            fig.add_trace(go.Scatter(
                x=df.index, y=df[sma], name=sma,
                line=dict(color=color, width=1.2),
            ), row=1, col=1)

    # ── Row 2: Volume bars (green = up day, red = down day) ─────────────────
    if "Volume" in df.columns:
        vol_colors = [
            "#26a69a" if c >= o else "#ef5350"
            for c, o in zip(df["Close"], df["Open"])
        ]
        fig.add_trace(go.Bar(
            x=df.index, y=df["Volume"],
            marker_color=vol_colors,
            name="Volume", showlegend=False,
            opacity=0.7,
        ), row=2, col=1)
        # 20-day avg volume line
        vol_ma = df["Volume"].rolling(20).mean()
        fig.add_trace(go.Scatter(
            x=df.index, y=vol_ma,
            line=dict(color="#FFD700", width=1.2, dash="dot"),
            name="Vol MA20", showlegend=False,
        ), row=2, col=1)

    # ── Row 3: RSI ──────────────────────────────────────────────────────────
    if "RSI" in df.columns:
        fig.add_trace(go.Scatter(
            x=df.index, y=df["RSI"], name="RSI",
            line=dict(color="#CE93D8", width=1.5),
        ), row=3, col=1)
        for level, color in [(30, "#26a69a"), (70, "#ef5350"), (50, "rgba(150,150,150,0.5)")]:
            fig.add_hline(y=level, line_dash="dot", line_color=color, row=3, col=1)
        # RSI overbought / oversold shading
        fig.add_hrect(y0=70, y1=100, fillcolor="rgba(239,83,80,0.06)",
                      line_width=0, row=3, col=1)
        fig.add_hrect(y0=0, y1=30, fillcolor="rgba(38,166,154,0.06)",
                      line_width=0, row=3, col=1)

    # ── Row 4: MACD ─────────────────────────────────────────────────────────
    if "MACD" in df.columns and "MACD_Signal" in df.columns:
        fig.add_trace(go.Scatter(
            x=df.index, y=df["MACD"], name="MACD",
            line=dict(color="#2196F3", width=1.5),
        ), row=4, col=1)
        fig.add_trace(go.Scatter(
            x=df.index, y=df["MACD_Signal"], name="Signal",
            line=dict(color="#FF9800", width=1.5),
        ), row=4, col=1)
        if "MACD_Hist" in df.columns:
            hist_colors = ["#26a69a" if v >= 0 else "#ef5350" for v in df["MACD_Hist"]]
            fig.add_trace(go.Bar(
                x=df.index, y=df["MACD_Hist"], name="Hist",
                marker_color=hist_colors, opacity=0.6,
            ), row=4, col=1)

    # ── NSE Pro Plotly layout ────────────────────────────────────────────────
    _NSE_GRID = dict(gridcolor="rgba(255,255,255,.04)", linecolor="rgba(255,255,255,.06)")
    _NSE_TICK = dict(color="#4a5568", size=10)
    fig.update_layout(
        height=720,
        paper_bgcolor="#070c18",
        plot_bgcolor="#0a1020",
        xaxis_rangeslider_visible=False,
        font=dict(family="Inter, -apple-system, sans-serif", color="#8899bb", size=11),
        legend=dict(
            orientation="h", y=1.02, x=0,
            bgcolor="rgba(7,12,24,.85)",
            bordercolor="rgba(255,255,255,.06)", borderwidth=1,
            font=dict(color="#8899bb", size=11),
        ),
        margin=dict(l=0, r=60, t=40, b=0),
        hoverlabel=dict(
            bgcolor="#0d1526", bordercolor="rgba(255,255,255,.1)",
            font=dict(color="#f0f4ff", family="Inter", size=12),
        ),
        hovermode="x unified",
    )
    # Apply grid style to all rows
    for row in range(1, 5):
        fig.update_xaxes(
            **_NSE_GRID, zeroline=False, tickfont=_NSE_TICK,
            row=row, col=1,
        )
        fig.update_yaxes(
            **_NSE_GRID, zeroline=False, tickfont=_NSE_TICK,
            side="right", row=row, col=1,
        )
    fig.update_yaxes(title_text="₹ Price",  title_font=dict(size=10,color="#4a5568"), row=1, col=1)
    fig.update_yaxes(title_text="Volume",   title_font=dict(size=10,color="#4a5568"), tickformat=".2s", row=2, col=1)
    fig.update_yaxes(title_text="RSI",      title_font=dict(size=10,color="#4a5568"), range=[0,100], row=3, col=1)
    fig.update_yaxes(title_text="MACD",     title_font=dict(size=10,color="#4a5568"), row=4, col=1)
    # Spike lines for crosshair
    fig.update_xaxes(showspikes=True, spikethickness=1, spikecolor="#5a6a8a", spikedash="dot")
    fig.update_yaxes(showspikes=True, spikethickness=1, spikecolor="#5a6a8a")
    return fig


# ── Live top bar: Nifty indices strip + scrolling ticker (auto-refresh 5 s) ───
# All Nifty indices the strip tries to show (failures are skipped gracefully).
_INDEX_STRIP = [
    ("NIFTY 50",   "^NSEI"),      ("BANK NIFTY", "^NSEBANK"),
    ("NIFTY IT",   "^CNXIT"),     ("NIFTY AUTO",  "^CNXAUTO"),
    ("NIFTY FMCG", "^CNXFMCG"),   ("NIFTY PHARMA","^CNXPHARMA"),
    ("NIFTY METAL","^CNXMETAL"),  ("NIFTY ENERGY","^CNXENERGY"),
]


@st.cache_data(ttl=5, show_spinner=False)        # 5-second freshness for live feel
def _index_strip_data():
    """Live value + day-change % for each Nifty index via Yahoo chart meta."""
    import json, urllib.parse, urllib.request
    try:
        from data.fetcher import _get_yf_crumb
        _opener, _crumb = _get_yf_crumb()
    except Exception:
        _opener, _crumb = None, ""
    _qs = f"&crumb={urllib.parse.quote(_crumb)}" if _crumb else ""
    _open = _opener.open if _opener else urllib.request.urlopen
    out = []
    for label, sym in _INDEX_STRIP:
        try:
            url = (f"https://query1.finance.yahoo.com/v8/finance/chart/"
                   f"{urllib.parse.quote(sym)}?interval=1d&range=5d{_qs}")
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0", "Accept": "application/json"})
            with _open(req, timeout=6) as r:
                meta = json.loads(r.read())["chart"]["result"][0]["meta"]
            price = meta.get("regularMarketPrice")
            prev  = meta.get("chartPreviousClose") or meta.get("previousClose")
            if price and prev:
                out.append((label, float(price), (float(price) / float(prev) - 1) * 100))
        except Exception:
            continue
    return out


@st.cache_data(ttl=30, show_spinner=False)
def _ticker_tape_data():
    _names = ["RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "ICICIBANK.NS", "INFY.NS",
              "SBIN.NS", "BHARTIARTL.NS", "ITC.NS", "LT.NS", "AXISBANK.NS",
              "MARUTI.NS", "TATAMOTORS.NS", "SUNPHARMA.NS", "TITAN.NS"]
    try:
        from utils.live_price import get_live_prices_batch
        raw = get_live_prices_batch(_names, max_workers=10)
    except Exception:
        raw = {}
    out = []
    for t in _names:
        q = raw.get(t)
        if isinstance(q, dict) and q.get("price"):
            out.append((t.replace(".NS", ""), float(q["price"]), float(q.get("chg_pct", 0.0))))
    return out


@st.fragment(run_every="5s")     # auto-updates ONLY this bar every 5 s, no page reload
def _live_top_bar():
    # ── VIX + market-status chips, then Nifty indices strip ──────────────────
    try:
        _chips = ""
        # India VIX chip
        try:
            from utils.vix import get_india_vix_regime as _ltb_vix
            _vinfo = _ltb_vix()
            _vv = _vinfo.get("vix")
            if _vv:
                _vcol = "#00d4aa" if _vv < 16 else "#ff9500" if _vv < 22 else "#ff4757"
                _chips += (
                    f'<div style="background:#0d1526;border:1px solid rgba(255,255,255,.05);'
                    f'border-left:3px solid {_vcol};border-radius:8px;padding:6px 12px;min-width:96px">'
                    f'<div style="font-size:9px;color:#4a5568;letter-spacing:.6px;font-weight:600">INDIA VIX</div>'
                    f'<div style="font-size:14px;font-weight:700;color:{_vcol}">{_vv:.1f} '
                    f'<span style="font-size:10px;color:#8899bb">{_vinfo.get("regime","").title()}</span></div></div>'
                )
        except Exception:
            pass
        # Market-status chip
        try:
            from utils.market_hours import market_status as _ltb_ms
            _msd = _ltb_ms()
            _scol = "#00d4aa" if _msd.get("is_open") else "#ff4757"
            _chips += (
                f'<div style="background:#0d1526;border:1px solid rgba(255,255,255,.05);'
                f'border-left:3px solid {_scol};border-radius:8px;padding:6px 12px;min-width:110px">'
                f'<div style="font-size:9px;color:#4a5568;letter-spacing:.6px;font-weight:600">MARKET</div>'
                f'<div style="font-size:13px;font-weight:700;color:{_scol}">{_msd.get("status","")}</div></div>'
            )
        except Exception:
            pass

        _idx = _index_strip_data()
        for _lbl, _val, _chg in (_idx or []):
            _c = "#00d4aa" if _chg >= 0 else "#ff4757"
            _a = "▲" if _chg >= 0 else "▼"
            _chips += (
                f'<div style="background:#0d1526;border:1px solid rgba(255,255,255,.05);'
                f'border-left:3px solid {_c};border-radius:8px;padding:6px 12px;min-width:118px">'
                f'<div style="font-size:9px;color:#4a5568;letter-spacing:.6px;font-weight:600">{_lbl}</div>'
                f'<div style="font-size:14px;font-weight:700;color:#f0f4ff">{_val:,.0f} '
                f'<span style="font-size:11px;color:{_c}">{_a}{abs(_chg):.2f}%</span></div></div>'
            )
        if _chips:
            st.markdown(
                f'<div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:8px">{_chips}</div>',
                unsafe_allow_html=True,
            )
    except Exception:
        pass

    # ── Scrolling stock ticker ───────────────────────────────────────────────
    try:
        _tt = _ticker_tape_data()
        if _tt:
            _tt_items = ""
            for _sym, _px, _chg in _tt:
                _tc = "#00d4aa" if _chg >= 0 else "#ff4757"
                _ta = "▲" if _chg >= 0 else "▼"
                _tt_items += (
                    f'<span style="margin:0 22px">'
                    f'<b style="color:#f0f4ff">{_sym}</b> '
                    f'<span style="color:#c8d0e0">₹{_px:,.2f}</span> '
                    f'<span style="color:{_tc}">{_ta}{abs(_chg):.2f}%</span></span>'
                )
            st.markdown(
                f'<div class="ticker-wrap"><div class="ticker-content">{_tt_items}{_tt_items}</div></div>',
                unsafe_allow_html=True,
            )
    except Exception:
        pass


try:
    _live_top_bar()
except Exception:
    pass  # live bar is cosmetic — never break the page over it

# ── Index explorer: open any index to see its stocks + day changes ────────────
# Maps each index label to its constituent ticker list (from the app universe).
_INDEX_CONSTITUENTS = {
    "NIFTY 50":     ("universe", "nifty50"),
    "BANK NIFTY":   ("sector",   "Banking"),
    "NIFTY IT":     ("sector",   "IT"),
    "NIFTY AUTO":   ("sector",   "Auto"),
    "NIFTY FMCG":   ("sector",   "FMCG"),
    "NIFTY PHARMA": ("sector",   "Pharma"),
    "NIFTY METAL":  ("sector",   "Metal"),
    "NIFTY ENERGY": ("sector",   "Energy"),
}

@st.cache_data(ttl=60, show_spinner=False)
def _index_constituent_rows(index_label: str):
    """Return [(ticker, price, chg%), …] for an index's constituents (live)."""
    try:
        kind, key = _INDEX_CONSTITUENTS.get(index_label, ("universe", "nifty50"))
        if kind == "universe":
            from data.universe import get_universe
            tickers = get_universe(key)
        else:
            from data.universe import get_tickers_by_sector
            tickers = get_tickers_by_sector(key)
        from utils.live_price import get_live_prices_batch
        raw = get_live_prices_batch(list(tickers), max_workers=12)
        rows = []
        for t in tickers:
            q = raw.get(t)
            if isinstance(q, dict) and q.get("price"):
                rows.append((t.replace(".NS", ""), float(q["price"]), float(q.get("chg_pct", 0.0))))
        rows.sort(key=lambda x: -x[2])   # biggest gainers first
        return rows
    except Exception:
        return []

with st.expander("📑 Open an index — see its stocks & day changes", expanded=False):
    _ix_pick = st.selectbox("Index", list(_INDEX_CONSTITUENTS.keys()),
                            key="ix_explorer_sel", label_visibility="collapsed")
    with st.spinner(f"Loading {_ix_pick} stocks…"):
        _ix_rows = _index_constituent_rows(_ix_pick)
    if _ix_rows:
        _ix_up = sum(1 for _, _, c in _ix_rows if c >= 0)
        st.caption(f"**{_ix_pick}** — {len(_ix_rows)} stocks · {_ix_up} up / {len(_ix_rows)-_ix_up} down")
        # color-coded HTML grid
        _ix_html = '<div style="display:flex;flex-wrap:wrap;gap:6px">'
        for _nm, _px, _ch in _ix_rows:
            _cc = "#00d4aa" if _ch >= 0 else "#ff4757"
            _ar = "▲" if _ch >= 0 else "▼"
            _ix_html += (
                f'<div style="background:#0d1526;border:1px solid rgba(255,255,255,.05);'
                f'border-left:3px solid {_cc};border-radius:7px;padding:6px 11px;min-width:120px">'
                f'<div style="font-size:12px;font-weight:700;color:#f0f4ff">{_nm}</div>'
                f'<div style="font-size:12px;color:#c8d0e0">₹{_px:,.2f} '
                f'<span style="color:{_cc};font-weight:600">{_ar}{abs(_ch):.2f}%</span></div></div>'
            )
        _ix_html += '</div>'
        st.markdown(_ix_html, unsafe_allow_html=True)
    else:
        st.caption("Couldn't load constituents — try again in a moment.")

# ═══════════════════════════════════════════════════════════════════════════════
# PAGE 0 — MARKET LIVE
# ═══════════════════════════════════════════════════════════════════════════════
if page == "📡 Market Live":
    from utils.market_hours import market_status as _ms_fn, refresh_interval_seconds
    from utils.news import get_market_news, get_stock_news, _quick_sentiment

    _ms = _ms_fn()
    ri  = refresh_interval_seconds()

    # ── Auto-refresh via meta tag when market is open ──────────────────────────
    if ri > 0:
        st.markdown(f'<meta http-equiv="refresh" content="{ri}">',
                    unsafe_allow_html=True)

    # ── Header ─────────────────────────────────────────────────────────────────
    col_h1, col_h2 = st.columns([3, 1])
    with col_h1:
        st.title("📡 Market Live")
        st.markdown("Real-time NSE prices · Top movers · News signals")
    with col_h2:
        st.markdown(f"""
        <div style='text-align:right;margin-top:12px'>
        <span style='font-size:22px'>{_ms['color']}</span><br>
        <b style='font-size:16px'>{_ms['status']}</b><br>
        <span style='font-size:11px;color:#aaa'>{_ms['time_ist']}</span>
        </div>""", unsafe_allow_html=True)
        if st.button("🔄 Refresh Now"):
            st.cache_data.clear()
            st.rerun()

    st.markdown(f"*{_ms['day']} — {_ms['detail']}*")
    st.markdown("---")

    # ── Fetch NSE 500 prices — Angel One (priority) → Yahoo → NSE fallback ───────
    @st.cache_data(ttl=60 if _ms["is_open"] else 3600, show_spinner=False)
    def _load_nifty_snapshot():
        """
        Cloud-safe NSE broad snapshot (Nifty 500 universe).
        Priority: Angel One batch quotes → Yahoo Finance JSON API.
        """
        from data.universe import get_universe as _gu

        tickers_list = _gu("nifty500")   # ~400 liquid NSE stocks
        raw: dict = {}
        _source = "Yahoo Finance"

        # Tier 1: Angel One (real-time, preferred)
        try:
            from data.angel_fetcher import (
                is_configured as _aoc,
                get_batch_quotes as _ao_batch,
            )
            if _aoc():
                _ao_raw = _ao_batch(tickers_list)
                if _ao_raw and sum(1 for v in _ao_raw.values() if v) > 10:
                    raw     = _ao_raw
                    _source = "Angel One (real-time)"
        except Exception:
            pass

        # Tier 2: Yahoo Finance JSON
        if not raw:
            from utils.live_price import get_live_prices_batch
            raw     = get_live_prices_batch(tickers_list, max_workers=12)
            _source = "Yahoo Finance"

        rows = []
        for t in tickers_list:
            q = raw.get(t)
            if not isinstance(q, dict) or not q.get("price"):
                continue
            try:
                chg = q.get("chg_pct", (q["price"] / q["prev_close"] - 1) * 100
                             if q.get("prev_close", 0) > 0 else 0.0)
                rows.append({
                    "ticker":     t,
                    "name":       get_display_name(t),
                    "price":      q["price"],
                    "prev_close": q.get("prev_close", q["price"]),
                    "chg_pct":    chg,
                    "vol_ratio":  1.0,
                    "volume":     q.get("volume", 0),
                    "_source":    _source,
                })
            except Exception:
                continue

        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(rows).sort_values("chg_pct", ascending=False)
        return df

    with st.spinner("Loading NSE market snapshot…"):
        snap = _load_nifty_snapshot()

    if snap.empty:
        st.warning("Could not fetch market data. Try again in 30 seconds.")
    else:
        # ── Data source badge ──────────────────────────────────────────────────
        _src = snap.get("_source", pd.Series(["Yahoo Finance"])).iloc[0] if "_source" in snap.columns else "Yahoo Finance"
        _src_pill = "pill-green" if "Angel One" in _src else "pill-gray"
        st.markdown(
            f'<span class="{_src_pill}">Data: {_src}</span>',
            unsafe_allow_html=True,
        )

        # ── Top metrics row ────────────────────────────────────────────────────
        adv = int((snap["chg_pct"] > 0).sum())
        dec = int((snap["chg_pct"] < 0).sum())
        unch = len(snap) - adv - dec
        avg_chg = snap["chg_pct"].mean()
        _breadth_pct = adv / max(adv + dec, 1) * 100

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("NSE Stocks Tracked", f"{len(snap)}")
        m2.metric("Advances / Declines", f"{adv} / {dec}",
                  delta=f"{adv-dec:+d} net", delta_color="normal" if adv >= dec else "inverse")
        m3.metric("Avg Change", f"{avg_chg:+.2f}%",
                  delta_color="normal" if avg_chg >= 0 else "inverse")
        m4.metric("Breadth", f"{_breadth_pct:.0f}% up",
                  delta_color="normal" if _breadth_pct >= 50 else "inverse")

        st.markdown("---")

        # ── Today's Trade Ideas (from live % change + market breadth) ──────────
        # NOTE: intraday volume isn't available in the batch feed, so ideas are
        # ranked on live price change + breadth, not volume.
        st.markdown("##### 💡 Today's Trade Ideas")
        _sg_items = []
        _top_gain = snap.iloc[0]   if len(snap) else None       # sorted desc
        _top_lose = snap.iloc[-1]  if len(snap) else None
        if _top_gain is not None and _top_gain["chg_pct"] >= 1.0:
            _sg_items.append(("🟢 STRONGEST TODAY", "#26a69a", "#0a2a1a",
                              _top_gain["ticker"].replace(".NS",""),
                              f"₹{_top_gain['price']:,.2f}  ·  {_top_gain['chg_pct']:+.2f}%",
                              "Leading the market higher — momentum / long-bias candidate"))
        if _top_lose is not None and _top_lose["chg_pct"] <= -1.0:
            _sg_items.append(("🔴 WEAKEST TODAY", "#ef5350", "#2a0a0a",
                              _top_lose["ticker"].replace(".NS",""),
                              f"₹{_top_lose['price']:,.2f}  ·  {_top_lose['chg_pct']:+.2f}%",
                              "Under the heaviest selling — avoid / short-bias candidate"))
        # Market-regime idea from breadth
        if _breadth_pct >= 65:
            _sg_items.append(("📈 BROAD STRENGTH", "#26a69a", "#0a2a1a", "Market-wide",
                              f"{_breadth_pct:.0f}% of stocks up · avg {avg_chg:+.2f}%",
                              "Risk-on day — trend-following longs favoured"))
        elif _breadth_pct <= 35:
            _sg_items.append(("📉 BROAD WEAKNESS", "#ef5350", "#2a0a0a", "Market-wide",
                              f"{100-_breadth_pct:.0f}% of stocks down · avg {avg_chg:+.2f}%",
                              "Risk-off day — protect capital, avoid fresh longs"))
        else:
            _sg_items.append(("↔️ MIXED MARKET", "#FFC107", "#1a1400", "Market-wide",
                              f"{_breadth_pct:.0f}% up · avg {avg_chg:+.2f}%",
                              "No clear breadth edge — be selective, stock-specific only"))

        _sg_html = '<div style="display:flex;gap:10px;margin-bottom:4px;flex-wrap:wrap">'
        for _lbl, _c, _bg, _tk, _sub, _why in _sg_items:
            _sg_html += (
                f'<div style="flex:1;min-width:200px;background:{_bg};border-left:5px solid {_c};'
                f'border-radius:10px;padding:12px 15px">'
                f'<div style="font-size:10px;color:{_c};text-transform:uppercase;'
                f'letter-spacing:1px;font-weight:700;margin-bottom:2px">{_lbl}</div>'
                f'<div style="font-size:20px;font-weight:700;color:#fff">{_tk}</div>'
                f'<div style="font-size:12px;color:#ccc;margin:2px 0">{_sub}</div>'
                f'<div style="font-size:11px;color:#999">{_why}</div></div>'
            )
        _sg_html += '</div>'
        st.markdown(_sg_html, unsafe_allow_html=True)
        st.caption("Ideas ranked on live price change + market breadth (intraday volume not in feed). "
                   "Not financial advice — confirm with the Analyze page before trading.")

        st.markdown("---")

        # ── Gainers and Losers — clean HTML cards (robust, no nested expanders) ─
        top5 = snap.head(5)
        bot5 = snap.tail(5).iloc[::-1]

        def _movers_block(rows, is_gainer):
            _acc = "#26a69a" if is_gainer else "#ef5350"
            _html = ""
            for _i, (_, _row) in enumerate(rows.iterrows(), 1):
                _ch = _row["chg_pct"]
                _cc2 = "#26a69a" if _ch >= 0 else "#ef5350"
                _ar = "▲" if _ch >= 0 else "▼"
                _nm = str(_row.get("name", ""))[:26]
                _html += (
                    f'<div style="background:#0d1f3c;border-left:4px solid {_acc};'
                    f'border-radius:9px;padding:9px 13px;margin-bottom:6px;'
                    f'display:flex;justify-content:space-between;align-items:center">'
                    f'<div><span style="color:#666;font-size:11px;margin-right:6px">#{_i}</span>'
                    f'<span style="font-size:15px;font-weight:700;color:#fff">{_row["ticker"].replace(".NS","")}</span>'
                    f'<div style="font-size:11px;color:#888">{_nm}</div></div>'
                    f'<div style="text-align:right">'
                    f'<div style="font-size:15px;font-weight:700;color:#fff">₹{_row["price"]:,.2f}</div>'
                    f'<div style="font-size:13px;font-weight:600;color:{_cc2}">{_ar} {abs(_ch):.2f}%</div>'
                    f'</div></div>'
                )
            return _html

        _mc1, _mc2 = st.columns(2)
        with _mc1:
            st.markdown("#### 🟢 Top Gainers")
            st.markdown(_movers_block(top5, True), unsafe_allow_html=True)
        with _mc2:
            st.markdown("#### 🔴 Top Losers")
            st.markdown(_movers_block(bot5, False), unsafe_allow_html=True)

        @st.cache_data(ttl=300, show_spinner=False)
        def _explain_mover(ticker: str, chg_pct: float, vol_ratio: float) -> list:
            """Generate 2-4 plain-English reasons why a stock is moving."""
            reasons = []
            try:
                import math
                from data.fetcher import fetch_single
                df = fetch_single(ticker, period="3mo")
                df = df.dropna(subset=["Close"])
                if len(df) < 20:
                    return reasons

                last    = df.iloc[-1]
                close   = float(last["Close"])
                high52  = float(df["High"].max())
                low52   = float(df["Low"].min())
                sma20   = df["Close"].rolling(20).mean().iloc[-1]
                sma50   = df["Close"].rolling(50).mean().iloc[-1] if len(df) >= 50 else close

                # RSI
                delta   = df["Close"].diff()
                gain    = delta.clip(lower=0).rolling(14).mean()
                loss    = (-delta.clip(upper=0)).rolling(14).mean()
                rs      = gain / loss
                rsi     = float((100 - 100 / (1 + rs)).iloc[-1])

                # Volume
                if vol_ratio >= 2.5:
                    reasons.append(f"Massive volume surge ({vol_ratio:.1f}x average) — likely institutional activity")
                elif vol_ratio >= 1.5:
                    reasons.append(f"Above-average volume ({vol_ratio:.1f}x) — elevated interest")

                # RSI
                if rsi > 72:
                    reasons.append(f"RSI overbought ({rsi:.0f}) — strong momentum, watch for pullback")
                elif rsi < 30:
                    reasons.append(f"RSI oversold ({rsi:.0f}) — heavy selling, potential bounce zone")
                elif 50 < rsi < 65 and chg_pct > 0:
                    reasons.append(f"RSI healthy ({rsi:.0f}) — momentum building, not yet overbought")

                # 52-week position
                pct_from_high = (high52 - close) / high52 * 100
                pct_from_low  = (close - low52) / low52 * 100
                if pct_from_high < 2:
                    reasons.append("At 52-week high — breakout territory")
                elif pct_from_low < 3:
                    reasons.append("Near 52-week low — support zone / turnaround candidate")

                # Trend
                if not math.isnan(sma20) and not math.isnan(sma50):
                    if close > sma20 > sma50:
                        reasons.append("Above SMA20 and SMA50 — uptrend intact")
                    elif close < sma20 < sma50:
                        reasons.append("Below SMA20 and SMA50 — downtrend pressure")

                # News
                news = get_stock_news(ticker, max_articles=1)
                if news:
                    h = news[0]["title"][:90]
                    s = news[0]["sentiment"]
                    icon = "📰" if s == "neutral" else ("🟢" if s == "positive" else "🔴")
                    reasons.append(f"{icon} News: {h}…")

            except Exception:
                pass
            return reasons if reasons else ["No specific technical catalyst detected"]

        # ── Drill into any mover (one panel, no nested-expander clutter) ───────
        st.markdown("")
        _drill_pool = pd.concat([top5, bot5]).drop_duplicates(subset=["ticker"])
        _drill_opts = ["— pick a stock —"] + [
            f"{r['ticker'].replace('.NS','')}  ({r['chg_pct']:+.2f}%)"
            for _, r in _drill_pool.iterrows()
        ]
        _drill_sel = st.selectbox("🔍 Drill into a mover", _drill_opts, key="ml_drill_sel")
        if _drill_sel != "— pick a stock —":
            _dt_label = _drill_sel.split("  (")[0].strip()
            _dt_full  = _dt_label if _dt_label.endswith(".NS") else _dt_label + ".NS"
            _drow = _drill_pool[_drill_pool["ticker"].str.replace(".NS", "") == _dt_label]
            if not _drow.empty:
                _dr = _drow.iloc[0]
                _dchg = _dr["chg_pct"]
                _dd1, _dd2, _dd3 = st.columns(3)
                _dd1.metric("Live Price", f"₹{_dr['price']:,.2f}", f"{_dchg:+.2f}%",
                            delta_color="normal" if _dchg >= 0 else "inverse")
                _dd2.metric("Prev Close", f"₹{_dr.get('prev_close', _dr['price']):,.2f}")
                _dd3.metric("Company", str(_dr.get("name", ""))[:20])
                with st.spinner("Reading the chart…"):
                    for _rs in _explain_mover(_dt_full, _dchg, 1.0):
                        st.markdown(f"• {_rs}")
                _da, _db, _dc = st.columns(3)
                if _da.button("📊 Analyze", key=f"ml_an_{_dt_full}", use_container_width=True):
                    st.session_state["nav"] = "🔍 Analyze Stock"
                    st.session_state["manual_ticker_input"] = _dt_label
                    st.session_state["last_analyzed"] = _dt_full
                    st.rerun()
                if _db.button("📝 Paper Trade", key=f"ml_pt_{_dt_full}", use_container_width=True):
                    st.session_state["nav"] = "📂 Paper Trades"
                    st.session_state["pt_prefill_ticker"] = _dt_full
                    st.rerun()
                if _dc.button("＋ Watchlist", key=f"ml_wl_{_dt_full}", use_container_width=True):
                    if _dt_full not in st.session_state.get("watchlist", []):
                        st.session_state.setdefault("watchlist", []).append(_dt_full)
                    st.toast(f"{_dt_label} added to watchlist ✓")

        # ── Full NSE snapshot table ────────────────────────────────────────────
        st.markdown("---")
        with st.expander(f"📋 Full NSE Snapshot ({len(snap)} stocks)", expanded=False):
            disp = snap[["name", "ticker", "price", "chg_pct"]].copy()
            disp.columns = ["Company", "Ticker", "Price (₹)", "Change %"]
            disp["Ticker"]    = disp["Ticker"].str.replace(".NS", "")
            disp["Price (₹)"] = disp["Price (₹)"].map("₹{:,.2f}".format)
            disp["Change %"]  = disp["Change %"].map("{:+.2f}%".format)
            st.dataframe(disp, hide_index=True, use_container_width=True, height=400)

    # ── Market News ────────────────────────────────────────────────────────────
    st.markdown("---")
    st.subheader("📰 Latest Market News")
    with st.spinner("Loading news…"):
        mkt_news = get_market_news(max_articles=8)

    if mkt_news:
        for article in mkt_news:
            s = article["sentiment"]
            icon = "🟢" if s == "positive" else ("🔴" if s == "negative" else "⚪")
            st.markdown(
                f'{icon} **[{article["title"]}]({article["link"]})**  \n'
                f'<span style="font-size:11px;color:#aaa">'
                f'{article["publisher"]} · {article["time"]}</span>',
                unsafe_allow_html=True,
            )
    else:
        st.info("News unavailable — yfinance may be rate-limited. Try again shortly.")

    if ri > 0:
        st.caption(f"Auto-refreshes every {ri//60} minutes while market is open.")


# ═══════════════════════════════════════════════════════════════════════════════
# PAGE 0 — COMMAND CENTRE
# ═══════════════════════════════════════════════════════════════════════════════
elif page == "🎯 Command Centre":
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
    except Exception:
        pass
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
    except Exception:
        pass

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

    # ── 2. OPEN POSITION ALERTS + AUTO-CLOSE ───────────────────────────────────
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
    except Exception:
        pass

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

    # ── 3. TODAY'S TOP PICKS — broad NSE scan (shown ABOVE the watchlist) ──────
    _tp_h1, _tp_h2 = st.columns([5, 2])
    with _tp_h1:
        st.markdown("### 🔥 Today's Top Picks — NSE Scan")
        st.caption("Best buy & sell setups from ~36 liquid large/mid-caps, "
                   "scored on trend + momentum + RSI + volume + sector + VIX. "
                   "Cached 30 min · first load ~20-40 s.")
    with _tp_h2:
        st.write("")
        _run_picks = st.button("🔎 Scan Now", key="cc_run_picks", use_container_width=True)

    if _run_picks or st.session_state.get("cc_picks_loaded"):
        st.session_state["cc_picks_loaded"] = True
        with st.spinner("Scanning NSE for the strongest setups…"):
            _picks = _home_top_picks(vix_regime=_cc_vix_r,
                                     sector_ranks=_sector_ranks_tuple())

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
                if st.button(f"🔍 Deep Dive {_svl}", key=f"cc_pick_dd_{_sv['ticker']}",
                             use_container_width=True):
                    st.session_state["analyze_ticker"] = _sv["ticker"]
                    st.session_state["nav"] = "🔍 Analyze Stock"
                    st.rerun()
    else:
        st.info("Click **🔎 Scan Now** to find today's strongest buy & sell setups across NSE.")

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

    with st.spinner(f"Scoring your {len(_cc_wl)} watchlist stocks (parallel, cached 30 min)…"):
        _cc_scores = _score_watchlist(tuple(_cc_wl), _cc_vix_r,
                                      sector_ranks=_sector_ranks_tuple())

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
                    st.session_state["nav"] = "🔍 Analyze Stock"
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
elif page == "🏠 My Portfolio":
    st.title("🏠 My Portfolio")
    st.markdown(
        "Your holdings health check — live prices, plain English buy/hold/sell recommendations, and news for each stock."
    )

    # ── Angel One real holdings shortcut ──────────────────────────────────────
    try:
        from data.angel_fetcher import is_configured as _pf_ao_ok, get_holdings as _pf_ao_holdings
        if _pf_ao_ok():
            with st.expander("🔗 Import from Angel One account", expanded=False):
                st.info(
                    "Your Angel One account is connected. Click below to import your "
                    "real demat holdings directly — no CSV upload needed."
                )
                if st.button("Import Angel One Holdings", key="pf_ao_import"):
                    _ao_h = _pf_ao_holdings()
                    if _ao_h:
                        import tempfile as _tmf
                        import pathlib as _tmpl
                        _rows = [
                            f"{h['symbol']}.NS,{h['qty']},{h['avg_price']},2024-01-01"
                            for h in _ao_h
                        ]
                        _ao_csv_content = "ticker,quantity,avg_buy_price,date_bought\n" + "\n".join(_rows)
                        _ao_tmp = _tmpl.Path(_tmf.mktemp(suffix=".csv"))
                        _ao_tmp.write_text(_ao_csv_content, encoding="utf-8")
                        st.session_state["_ao_portfolio_path"] = str(_ao_tmp)
                        st.success(f"Imported {len(_ao_h)} holdings from Angel One")
                        st.rerun()
                    else:
                        st.error("Could not fetch holdings from Angel One")
    except Exception:
        pass

    # ── Auto-load default portfolio.csv OR let user upload ────────────────────
    import pathlib as _pl
    _DEFAULT_CSV = _pl.Path(_ROOT) / "portfolio.csv"

    col_ul, col_sample = st.columns([2, 1])

    with col_ul:
        uploaded = st.file_uploader(
            "Upload a different portfolio CSV (optional — default portfolio.csv auto-loads)",
            type=["csv"],
            help="Columns: ticker, quantity, avg_buy_price, date_bought",
        )

    with col_sample:
        sample_csv = (
            "ticker,quantity,avg_buy_price,date_bought\n"
            "RELIANCE,10,1350.00,2024-01-15\n"
            "TCS,5,3800.00,2024-03-10\n"
            "HDFCBANK,20,1600.00,2024-02-01\n"
        )
        st.download_button(
            "📥 Download sample CSV",
            data=sample_csv,
            file_name="sample_portfolio.csv",
            mime="text/csv",
        )
        st.caption("Tickers without .NS suffix are auto-resolved (e.g. RELIANCE → RELIANCE.NS)")

    # Resolve which file to analyse
    import tempfile
    if uploaded is not None:
        tmp = _pl.Path(tempfile.mktemp(suffix=".csv"))
        tmp.write_bytes(uploaded.read())
        _csv_source = tmp
        st.success("Using uploaded portfolio file.")
    elif st.session_state.get("_ao_portfolio_path"):
        _csv_source = _pl.Path(st.session_state["_ao_portfolio_path"])
        st.success("Using Angel One holdings (imported from broker)")
    elif _DEFAULT_CSV.exists():
        _csv_source = _DEFAULT_CSV
        st.info(f"Auto-loaded: **portfolio.csv** ({len(pd.read_csv(_DEFAULT_CSV))} holdings found)")
    else:
        _csv_source = None

    if _csv_source is not None:

        # ── LIVE PRICES STRIP (fast, 60-second cache) ─────────────────────────
        try:
            _port_csv = pd.read_csv(_csv_source)
            _port_tickers = tuple(
                (t if t.endswith(".NS") else t + ".NS")
                for t in _port_csv["ticker"].tolist()
            )
            _live_col, _refresh_col = st.columns([5, 1])
            with _refresh_col:
                st.write("")
                if st.button("🔄 Refresh Prices", key="port_refresh_live"):
                    st.cache_data.clear()
            with _live_col:
                st.markdown("#### 📡 Live Prices (updates every 60 s)")
            _live_prices = _portfolio_live_prices(_port_tickers)
            if _live_prices:
                _lp_rows = []
                _total_today_pnl   = 0.0
                _total_overall_pnl = 0.0
                _total_port_value  = 0.0
                _total_invested    = 0.0
                for _row in _port_csv.itertuples():
                    _sym = _row.ticker if str(_row.ticker).endswith(".NS") else f"{_row.ticker}.NS"
                    _lp  = _live_prices.get(_sym, {})
                    _cur = _lp.get("price")
                    _chg = _lp.get("chg", 0.0)
                    _qty = getattr(_row, "quantity", 1)
                    _buy = getattr(_row, "avg_buy_price", 0)
                    if _cur:
                        _today_pnl  = (_cur - _lp.get("prev", _cur)) * _qty
                        _total_pnl  = (_cur - _buy) * _qty
                        _total_pct  = (_cur / _buy - 1) * 100 if _buy > 0 else 0
                        _total_today_pnl   += _today_pnl
                        _total_overall_pnl += _total_pnl
                        _total_port_value  += _cur * _qty
                        _total_invested    += _buy * _qty
                        _lp_rows.append({
                            "ticker":      str(_row.ticker).replace(".NS", ""),
                            "qty":         int(_qty),
                            "avg_cost":    float(_buy),
                            "live_price":  float(_cur),
                            "chg_pct":     float(_chg),
                            "today_pnl":   float(_today_pnl),
                            "total_pct":   float(_total_pct),
                            "total_pnl":   float(_total_pnl),
                        })
                    else:
                        _lp_rows.append({
                            "ticker":      str(_row.ticker).replace(".NS", ""),
                            "qty":         int(getattr(_row, "quantity", 1)),
                            "avg_cost":    float(getattr(_row, "avg_buy_price", 0)),
                            "live_price":  None,
                            "chg_pct":     None,
                            "today_pnl":   None,
                            "total_pct":   None,
                            "total_pnl":   None,
                        })

                # ── Today's Change Banner ─────────────────────────────────────
                _td_c = "#26a69a" if _total_today_pnl >= 0 else "#ef5350"
                _ov_c = "#26a69a" if _total_overall_pnl >= 0 else "#ef5350"
                _td_a = "▲" if _total_today_pnl >= 0 else "▼"
                _ov_a = "▲" if _total_overall_pnl >= 0 else "▼"
                _ov_p = (_total_overall_pnl / _total_invested * 100) if _total_invested > 0 else 0
                st.markdown(
                    f'<div style="display:flex;gap:14px;margin:0 0 14px 0">'
                    f'<div style="flex:1;background:#0d1f3c;padding:14px 18px;border-radius:10px;border-left:5px solid {_td_c}">'
                    f'<div style="font-size:10px;color:#aaa;text-transform:uppercase;letter-spacing:1px;margin-bottom:3px">Today\'s Change</div>'
                    f'<div style="font-size:24px;font-weight:700;color:{_td_c}">{_td_a} ₹{abs(_total_today_pnl):,.0f}</div>'
                    f'</div>'
                    f'<div style="flex:1;background:#0d1f3c;padding:14px 18px;border-radius:10px;border-left:5px solid {_ov_c}">'
                    f'<div style="font-size:10px;color:#aaa;text-transform:uppercase;letter-spacing:1px;margin-bottom:3px">Overall P&amp;L</div>'
                    f'<div style="font-size:24px;font-weight:700;color:{_ov_c}">{_ov_a} ₹{abs(_total_overall_pnl):,.0f} '
                    f'<span style="font-size:14px">({_ov_p:+.1f}%)</span></div>'
                    f'</div>'
                    f'<div style="flex:1;background:#0d1f3c;padding:14px 18px;border-radius:10px;border-left:5px solid #2196F3">'
                    f'<div style="font-size:10px;color:#aaa;text-transform:uppercase;letter-spacing:1px;margin-bottom:3px">Portfolio Value</div>'
                    f'<div style="font-size:24px;font-weight:700;color:#fff">₹{_total_port_value:,.0f}</div>'
                    f'</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )

                # ── Colored holdings table ────────────────────────────────────
                _TH  = "background:#1a2744;padding:8px 12px;font-size:11px;color:#aaa;font-weight:600;border-bottom:2px solid #2a3a5c;text-align:right;white-space:nowrap"
                _THL = _TH.replace("text-align:right", "text-align:left")
                _TD  = "padding:8px 12px;font-size:13px;border-bottom:1px solid #1a2744;text-align:right"
                _TDL = _TD.replace("text-align:right", "text-align:left")
                _tbl = (
                    '<table style="width:100%;border-collapse:collapse;margin-bottom:6px">'
                    f'<thead><tr>'
                    f'<th style="{_THL}">Stock</th>'
                    f'<th style="{_TH}">Qty</th>'
                    f'<th style="{_TH}">Avg Cost</th>'
                    f'<th style="{_TH}">Live Price</th>'
                    f'<th style="{_TH}">Today %</th>'
                    f'<th style="{_TH}">Today P&amp;L</th>'
                    f'<th style="{_TH}">Total Return</th>'
                    f'<th style="{_TH}">Total P&amp;L</th>'
                    f'</tr></thead><tbody>'
                )
                for _r in _lp_rows:
                    _lv   = f"₹{_r['live_price']:,.2f}" if _r['live_price'] else "—"
                    _cg   = f"{_r['chg_pct']:+.2f}%"   if _r['chg_pct']   is not None else "—"
                    _tp2  = f"₹{_r['today_pnl']:+,.0f}" if _r['today_pnl'] is not None else "—"
                    _tr2  = f"{_r['total_pct']:+.1f}%"  if _r['total_pct'] is not None else "—"
                    _tnl  = f"₹{_r['total_pnl']:+,.0f}" if _r['total_pnl'] is not None else "—"
                    _cgc  = "#26a69a" if (_r['chg_pct']   or 0) >= 0 else "#ef5350"
                    _tpc  = "#26a69a" if (_r['today_pnl'] or 0) >= 0 else "#ef5350"
                    _tnc  = "#26a69a" if (_r['total_pnl'] or 0) >= 0 else "#ef5350"
                    _rbg  = "rgba(38,166,154,0.04)" if (_r['today_pnl'] or 0) >= 0 else "rgba(239,83,80,0.04)"
                    _tbl += (
                        f'<tr style="background:{_rbg}">'
                        f'<td style="{_TDL}"><b>{_r["ticker"]}</b></td>'
                        f'<td style="{_TD}">{_r["qty"]}</td>'
                        f'<td style="{_TD}">₹{_r["avg_cost"]:,.2f}</td>'
                        f'<td style="{_TD}"><b>{_lv}</b></td>'
                        f'<td style="{_TD};color:{_cgc};font-weight:600">{_cg}</td>'
                        f'<td style="{_TD};color:{_tpc};font-weight:700">{_tp2}</td>'
                        f'<td style="{_TD};color:{_tnc}">{_tr2}</td>'
                        f'<td style="{_TD};color:{_tnc};font-weight:600">{_tnl}</td>'
                        f'</tr>'
                    )
                _tbl += '</tbody></table>'
                st.markdown(_tbl, unsafe_allow_html=True)

                # ── Portfolio Heatmap ──────────────────────────────────────
                _hm_rows = []
                for _row in _port_csv.itertuples():
                    _sym  = _row.ticker if str(_row.ticker).endswith(".NS") else f"{_row.ticker}.NS"
                    _lp   = _live_prices.get(_sym, {})
                    _cur  = _lp.get("price")
                    _buy  = getattr(_row, "avg_buy_price", 0)
                    _qty  = getattr(_row, "quantity", 1)
                    if _cur and _buy and _buy > 0:
                        _pct   = (_cur / _buy - 1) * 100
                        _val   = _cur * _qty
                        _hm_rows.append({
                            "label":  _row.ticker,
                            "value":  _val,
                            "pct":    round(_pct, 2),
                            "text":   f"{_row.ticker}<br>{_pct:+.1f}%<br>₹{_val/1000:.0f}K",
                        })
                if _hm_rows:
                    _hm_df = pd.DataFrame(_hm_rows)
                    import plotly.express as _px2
                    _fig_hm = _px2.treemap(
                        _hm_df, path=["label"], values="value",
                        color="pct",
                        color_continuous_scale=["#ef5350", "#555555", "#26a69a"],
                        color_continuous_midpoint=0,
                        custom_data=["pct", "text"],
                        title="📊 Portfolio Heatmap — sized by value, coloured by P&L",
                    )
                    _fig_hm.update_traces(
                        texttemplate="%{customdata[1]}",
                        textfont_size=13,
                        hovertemplate="<b>%{label}</b><br>P&L: %{customdata[0]:+.1f}%<extra></extra>",
                    )
                    _fig_hm.update_layout(
                        template="plotly_dark", height=300,
                        margin=dict(l=0, r=0, t=40, b=0),
                        coloraxis_showscale=False,
                    )
                    st.plotly_chart(_fig_hm, use_container_width=True)
            else:
                st.caption("⚠️ Live prices unavailable — trying again. Showing EOD data below.")
        except Exception as _e:
            st.caption(f"Live price strip skipped: {_e}")

        st.markdown("---")
        with st.spinner("Scoring your portfolio (parallel)… ~10–20 s for 5–10 stocks"):
            try:
                from analysis.portfolio_manager import PortfolioManager
                pm = PortfolioManager(_csv_source)
                summary = pm.mark_to_market(parallel=True)

                # ── Top summary banner ─────────────────────────────────────
                pnl_sign = "+" if summary.total_pnl >= 0 else ""
                pnl_color = "#26a69a" if summary.total_pnl >= 0 else "#ef5350"

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
                c4.metric("Diversification",
                          summary.diversification.concentration_risk)
                c5.metric("VIX Regime", summary.vix_regime)

                # ── Overall narrative ──────────────────────────────────────
                st.markdown(
                    f'<div class="card-blue"><span class="narrative">'
                    f'💡 <b>Portfolio Summary:</b> {summary.summary_narrative}'
                    f'</span></div>',
                    unsafe_allow_html=True
                )

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
                                template="plotly_dark", height=300,
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
                                f'{div.advice}'
                                f'</div>',
                                unsafe_allow_html=True
                            )

                # ── Holdings cards (2-column grid) ────────────────────────
                st.markdown("---")
                _hh1, _hh2 = st.columns([3, 2])
                _hh1.subheader("📋 Your Holdings — What to Do")
                with _hh2:
                    _h_sort = st.selectbox(
                        "Sort by",
                        ["Total P&L (high→low)", "Total P&L (low→high)", "Today's change",
                         "Score (best first)", "Value (high→low)", "Action (buy→exit)"],
                        key="pf_holdings_sort", label_visibility="collapsed",
                    )
                _ACT_ORDER = {"STRONG BUY": 0, "BUY": 1, "WATCHLIST": 2, "HOLD": 3,
                              "CAUTION": 4, "EXIT": 5}
                _hold_sorted = list(summary.holdings)
                try:
                    if _h_sort == "Total P&L (high→low)":
                        _hold_sorted.sort(key=lambda h: -h.pnl)
                    elif _h_sort == "Total P&L (low→high)":
                        _hold_sorted.sort(key=lambda h: h.pnl)
                    elif _h_sort == "Today's change":
                        _hold_sorted.sort(key=lambda h: -getattr(h, "pnl_pct", 0))
                    elif _h_sort == "Score (best first)":
                        _hold_sorted.sort(key=lambda h: -getattr(h, "score", 0))
                    elif _h_sort == "Value (high→low)":
                        _hold_sorted.sort(key=lambda h: -(h.current_price * h.quantity))
                    elif _h_sort == "Action (buy→exit)":
                        _hold_sorted.sort(key=lambda h: _ACT_ORDER.get(h.action, 9))
                except Exception:
                    _hold_sorted = list(summary.holdings)

                _ACT_CARD_STYLE = {
                    "STRONG BUY": ("#26a69a", "#0a2a1a"), "BUY": ("#4CAF50", "#0d2510"),
                    "WATCHLIST":  ("#2196F3", "#0d1f3c"), "HOLD": ("#9E9E9E", "#1a1a1a"),
                    "CAUTION":    ("#FF9800", "#1a1200"),  "EXIT": ("#ef5350", "#2a0a0a"),
                }
                _hc_grid = st.columns(2)
                for _hi, h in enumerate(_hold_sorted):
                    _h_ac, _h_bg = _ACT_CARD_STYLE.get(h.action, ("#9E9E9E", "#1a1a1a"))
                    _h_emoji = _action_emoji(h.action)
                    _h_pnl_c = "#26a69a" if h.pnl >= 0 else "#ef5350"
                    _h_pnl_a = "▲" if h.pnl >= 0 else "▼"
                    _h_lbl   = h.ticker.replace(".NS", "")
                    _h_inv   = h.avg_buy_price * h.quantity
                    _h_val   = h.current_price * h.quantity

                    # Progress bar: SL → Entry → Current → Target
                    _h_sl  = h.stop_loss or (h.avg_buy_price * 0.95)
                    _h_tp  = h.target    or (h.avg_buy_price * 1.10)
                    _h_rng = max(_h_tp - _h_sl, 0.01)
                    _h_ep_pct  = min(100, max(0, (_h_sl + (_h_rng * 0.3) - _h_sl) / _h_rng * 100))
                    _h_cur_pct = min(100, max(0, (h.current_price - _h_sl) / _h_rng * 100))
                    _h_bar_c   = "#26a69a" if h.current_price >= h.avg_buy_price else "#ef5350"
                    _h_score_w = min(int(h.score), 100)

                    _h_html = (
                        f'<div style="background:{_h_bg};border-left:5px solid {_h_ac};'
                        f'border-radius:10px;padding:14px 16px;margin-bottom:8px">'
                        # Header row: name + action + score
                        f'<div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:6px">'
                        f'<div>'
                        f'<span style="font-size:20px;font-weight:700;color:#fff">{_h_lbl}</span>'
                        f'&nbsp;&nbsp;<span style="font-size:13px;font-weight:700;color:{_h_ac}">{_h_emoji} {h.action}</span>'
                        f'</div>'
                        f'<div style="text-align:right">'
                        f'<span style="font-size:13px;font-weight:700;color:{_h_ac}">{h.score:.0f}/100</span>'
                        f'<div style="width:60px;height:5px;background:#333;border-radius:3px;margin-top:3px">'
                        f'<div style="width:{_h_score_w}%;height:100%;background:{_h_ac};border-radius:3px"></div></div>'
                        f'</div></div>'
                        # Price row
                        f'<div style="font-size:15px;color:#fff;margin-bottom:4px">'
                        f'<b>₹{h.current_price:,.2f}</b>'
                        f'<span style="font-size:12px;color:#aaa;margin-left:8px">{h.quantity:.0f} shares · held {h.days_held}d</span>'
                        f'</div>'
                        # Invested vs Now
                        f'<div style="font-size:12px;color:#aaa;margin-bottom:6px">'
                        f'Invested ₹{_h_inv:,.0f} → Now ₹{_h_val:,.0f}'
                        f'</div>'
                        # P&L
                        f'<div style="font-size:18px;font-weight:700;color:{_h_pnl_c};margin-bottom:8px">'
                        f'{_h_pnl_a} ₹{abs(h.pnl):,.0f} ({h.pnl_pct:+.1f}%)'
                        f'</div>'
                        # Progress bar: SL → current → target
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
                        # Headline reason
                        f'<div style="font-size:12px;color:#ccc;margin-top:6px">{h.headline}</div>'
                        f'</div>'
                    )
                    with _hc_grid[_hi % 2]:
                        st.markdown(_h_html, unsafe_allow_html=True)
                        _hb1, _hb2 = st.columns(2)
                        with _hb1:
                            if st.button(f"📊 Analyze", key=f"ph_an_{h.ticker}", use_container_width=True):
                                st.session_state["analyze_ticker"] = h.ticker
                                st.session_state["nav"] = "🔍 Analyze Stock"
                                st.rerun()
                        with _hb2:
                            _ph_price = h.current_price or h.avg_buy_price
                            _paper_trade_popover(
                                h.ticker, _ph_price, h.stop_loss or _ph_price * 0.95, h.target,
                                reason=f"{h.action}: {h.headline}",
                                key=f"ph_pt_{h.ticker}",
                            )
                        if h.error:
                            st.caption(f"⚠️ {h.error}")

                # ── Best / Worst ───────────────────────────────────────────
                st.markdown("---")
                bw_cols = st.columns(2)
                if summary.best_holding:
                    bh = summary.best_holding
                    with bw_cols[0]:
                        st.markdown(
                            f'<div class="card-green">'
                            f'🏆 <b>Best Performer:</b> {bh.ticker.replace(".NS","")} '
                            f'(+{bh.pnl_pct:.1f}%, ₹+{bh.pnl:,.0f})'
                            f'</div>',
                            unsafe_allow_html=True
                        )
                if summary.worst_holding:
                    wh = summary.worst_holding
                    with bw_cols[1]:
                        sign = "+" if wh.pnl_pct >= 0 else ""
                        st.markdown(
                            f'<div class="card-red">'
                            f'📉 <b>Needs Attention:</b> {wh.ticker.replace(".NS","")} '
                            f'({sign}{wh.pnl_pct:.1f}%, ₹{sign}{wh.pnl:,.0f})'
                            f'</div>',
                            unsafe_allow_html=True
                        )

                # ── Export ─────────────────────────────────────────────────
                st.markdown("---")
                export_path = pm.export_summary_csv(summary)
                export_df = pd.DataFrame([{
                    "Ticker": h.ticker.replace(".NS",""),
                    "Qty": h.quantity,
                    "Buy Price": h.avg_buy_price,
                    "Current": h.current_price,
                    "P&L (₹)": round(h.pnl, 2),
                    "P&L (%)": round(h.pnl_pct, 2),
                    "Score": h.score,
                    "Grade": h.grade,
                    "Action": h.action,
                    "Signal": h.signal.replace("🟢","G").replace("🟡","Y").replace("🔴","R"),
                    "Sector": h.sector,
                } for h in summary.holdings])

                csv_bytes = export_df.to_csv(index=False).encode()
                st.download_button(
                    "📥 Download Full Report CSV",
                    data=csv_bytes,
                    file_name="portfolio_health_report.csv",
                    mime="text/csv",
                )

            except Exception as e:
                st.error(f"Portfolio analysis failed: {e}")
                import traceback
                st.code(traceback.format_exc())
    else:
        # Empty state guidance
        st.markdown("---")
        st.warning(
            "No portfolio.csv found at the default path. "
            "Upload a CSV above to get started.  \n\n"
            "**Required columns:** `ticker, quantity, avg_buy_price, date_bought`  \n"
            "**What you'll see:**  \n"
            "- 🟢 Green = BUY MORE  |  🟡 Yellow = HOLD  |  🔴 Red = Consider Selling  \n"
            "- Composite score (0–100) for each stock — higher is better  \n"
            "- Plain English explanation and suggested stop-loss / target per holding"
        )
        col_ex1, col_ex2, col_ex3 = st.columns(3)
        with col_ex1:
            st.markdown("""
            <div class="card-green">
            <b>🟢 STRONG BUY (Score ≥ 80)</b><br>
            The stock's technicals, momentum, and volume are all aligned.
            Adding to your position here makes sense.
            </div>
            """, unsafe_allow_html=True)
        with col_ex2:
            st.markdown("""
            <div class="card-yellow">
            <b>🟡 HOLD (Score 40–65)</b><br>
            Mixed signals — some positives, some caution.
            Best to hold your current position and monitor.
            </div>
            """, unsafe_allow_html=True)
        with col_ex3:
            st.markdown("""
            <div class="card-red">
            <b>🔴 CAUTION / EXIT (Score &lt; 40)</b><br>
            Technicals are deteriorating.
            Consider reducing position size or setting a tight stop-loss.
            </div>
            """, unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════════════════════
# PAGE 2 — ANALYZE ANY STOCK
# ═══════════════════════════════════════════════════════════════════════════════
elif page == "🔍 Analyze Stock":
    st.title("🔍 Analyze Any NSE Stock")
    st.markdown("Search by company name or ticker — get a full AI score, chart, stop-loss, and plain-English recommendation.")

    # ── Stock search: name autocomplete + manual ticker ────────────────────────
    search_options = [f"{name}  ({sym.replace('.NS','')})"
                      for name, sym in STOCK_SEARCH_MAP.items()]
    search_options_sorted = sorted(search_options)

    _AS_PERIOD_MAP = {"1D":"1d","5D":"5d","1M":"1m","6M":"6m","YTD":"ytd","Max":"max"}

    col_search, col_manual, col_btn = st.columns([3, 2, 1])
    with col_search:
        selected_option = st.selectbox(
            "Search by company name or symbol",
            options=["— type to search —"] + search_options_sorted,
            index=0,
            key="stock_search_select",
        )
    with col_manual:
        manual_ticker = st.text_input(
            "Or type ticker directly",
            value="",
            placeholder="e.g. INFY or INFY.NS",
            key="manual_ticker_input",
        ).strip().upper()
    with col_btn:
        st.write("")
        st.write("")
        analyze_btn = st.button("🔍 Analyze", type="primary", key="analyze_btn")

    # ── Period selector — horizontal pill-style radio ──────────────────────
    _ui_period = st.radio(
        "Chart period",
        list(_AS_PERIOD_MAP.keys()),
        index=3,                      # default = 6M
        horizontal=True,
        key="analyze_period",
    )
    period = _AS_PERIOD_MAP[_ui_period]

    # Resolve final ticker
    ticker = ""
    if manual_ticker:
        ticker = manual_ticker if manual_ticker.endswith(".NS") else manual_ticker + ".NS"
    elif selected_option != "— type to search —":
        # Extract ticker from "Company Name  (TICKER)" format
        raw_sym = selected_option.rsplit("(", 1)[-1].rstrip(")")
        ticker = raw_sym + ".NS" if not raw_sym.endswith(".NS") else raw_sym

    if not ticker:
        ticker = "RELIANCE.NS"

    if analyze_btn or ("last_analyzed" in st.session_state and st.session_state.last_analyzed == ticker):
        st.session_state.last_analyzed = ticker

        with st.spinner(f"Scoring {ticker}…"):
            try:
                # Deep-dive score over 2Y data — changing chart period won't re-fetch
                cs = get_composite_score(ticker)
                # Live price reconciliation: the score's price is the last DAILY close
                # (used for all indicators); the live quote may be more recent.
                _an_live = None
                try:
                    from utils.live_price import get_live_quote as _an_lq
                    _anq = _an_lq(ticker)
                    if isinstance(_anq, dict) and _anq.get("price"):
                        _an_live = float(_anq["price"])
                except Exception:
                    _an_live = None
                _an_drift = (abs(_an_live - cs.price) / cs.price * 100) if (_an_live and cs.price) else 0.0
                # Full 2Y dataframe (all indicators valid at most-recent row)
                df = load_ticker_df(ticker)
                # Chart-display slice — only controls what the user SEES on the chart
                df_chart = _trim_to_period(df, period)

                # ── Score hero section ─────────────────────────────────────
                st.markdown("---")
                hero_col, detail_col = st.columns([1, 2])

                with hero_col:
                    grade_c = _grade_color(cs.grade)
                    card_c = _action_color(cs.action)
                    emoji = _action_emoji(cs.action)
                    st.markdown(
                        f'<div class="{card_c}" style="text-align:center;padding:24px">'
                        f'<div class="ticker-label">{ticker.replace(".NS","")}</div>'
                        f'<div style="font-size:14px;color:#aaa">₹{cs.price:,.2f}</div>'
                        f'<div class="score-big" style="color:{grade_c}">{cs.score:.0f}</div>'
                        f'<div style="font-size:13px;color:#aaa">out of 100</div>'
                        f'<div style="font-size:28px;font-weight:700;color:{grade_c};margin:8px 0">'
                        f'Grade: {cs.grade}</div>'
                        f'<div class="signal-big">{emoji} {cs.action}</div>'
                        f'</div>',
                        unsafe_allow_html=True
                    )
                    st.markdown("")
                    # Score breakdown mini-table
                    score_breakdown = {
                        "Technical (40)":  cs.technical_score,
                        "Momentum (25)":   cs.momentum_score,
                        "Volume (15)":     cs.volume_score,
                        "Pattern (10)":    cs.pattern_score,
                        "Sentiment (10)":  cs.sentiment_score,
                    }
                    for label, val in score_breakdown.items():
                        pct = val / {"Technical (40)": 40, "Momentum (25)": 25,
                                     "Volume (15)": 15, "Pattern (10)": 10,
                                     "Sentiment (10)": 10}[label] * 100
                        bar_color = "#26a69a" if pct >= 60 else "#f9a825" if pct >= 35 else "#ef5350"
                        st.markdown(
                            f'<div style="display:flex;align-items:center;margin:3px 0;">'
                            f'<span style="width:160px;font-size:12px;color:#ccc">{label}</span>'
                            f'<div style="flex:1;background:#333;border-radius:4px;height:10px">'
                            f'<div style="width:{pct:.0f}%;background:{bar_color};'
                            f'border-radius:4px;height:10px"></div></div>'
                            f'<span style="width:42px;text-align:right;font-size:12px;color:#ccc">'
                            f'{val:.0f}</span></div>',
                            unsafe_allow_html=True
                        )

                with detail_col:
                    # Trade levels
                    latest = df.iloc[-1]
                    prev   = df.iloc[-2]
                    day_chg = (latest["Close"] / prev["Close"] - 1) * 100

                    # Show the LIVE price as the headline current price when available
                    _disp_price = _an_live if _an_live else cs.price
                    mc1, mc2, mc3, mc4 = st.columns(4)
                    mc1.metric("Price (live)" if _an_live else "Close",
                               f"₹{_disp_price:,.2f}", f"{day_chg:+.2f}%")
                    mc2.metric("Sector",     cs.sector)
                    mc3.metric("VIX Regime", cs.vix_regime)
                    mc4.metric("Sector Rank",f"#{cs.sector_rank}")

                    # Close-price status + live-vs-daily reconciliation
                    try:
                        from utils.market_hours import market_status as _an_ms
                        _ms_an = _an_ms()
                        try:
                            _dlabel = df.index[-1].strftime("%d-%b")
                        except Exception:
                            _dlabel = ""
                        if _an_live and _an_drift >= 0.5:
                            st.caption(
                                f"ℹ️ Live price **₹{_an_live:,.2f}** · indicators & levels computed on the "
                                f"last daily close **₹{cs.price:,.2f}**{f' ({_dlabel})' if _dlabel else ''} "
                                f"— {_an_drift:.1f}% apart, so treat the entry/target as a guide near the live price."
                            )
                        elif _ms_an.get("is_open"):
                            st.caption("🔴 LIVE · market open — the official close settles after 3:30 PM.")
                        else:
                            st.caption(f"🟢 Settled EOD close{f' · {_dlabel}' if _dlabel else ''} "
                                       f"(market closed — official end-of-day price).")
                    except Exception:
                        pass

                    tc1, tc2, tc3, tc4 = st.columns(4)
                    tc1.metric("Entry (now)",  f"₹{cs.entry:,.2f}")
                    tc2.metric("Stop-Loss",    f"₹{cs.stop_loss:,.2f}",
                               f"-{(cs.price - cs.stop_loss)/cs.price*100:.1f}%",
                               delta_color="inverse")
                    tc3.metric("Target",       f"₹{cs.target:,.2f}",
                               f"+{(cs.target - cs.price)/cs.price*100:.1f}%")
                    tc4.metric("Risk : Reward",f"{cs.risk_reward:.1f} : 1")

                    # Headline + Narrative
                    st.markdown(
                        f'<div class="{_action_color(cs.action)}">'
                        f'<b style="font-size:16px">{cs.headline}</b><br><br>'
                        f'<span class="narrative">{cs.narrative}</span>'
                        f'</div>',
                        unsafe_allow_html=True
                    )

                # ── Action strip — prominent recommendation banner ─────────
                _as_colors = {
                    "BUY":          ("#0a2a1a", "#26a69a"),
                    "CAUTIOUS BUY": ("#0d2210", "#4caf50"),
                    "HOLD":         ("#2a2a00", "#f9a825"),
                    "WATCHLIST":    ("#0d1f3c", "#2196F3"),
                    "EXIT":         ("#2a0a0a", "#ef5350"),
                }
                _as_bg, _as_border = _as_colors.get(cs.action, ("#1a1a2e", "#2196F3"))
                _as_rr_ok = cs.risk_reward >= 1.5
                _as_rr_color = "#26a69a" if _as_rr_ok else "#f9a825"

                st.markdown(
                    f'<div style="background:{_as_bg};border-left:6px solid {_as_border};'
                    f'border-radius:8px;padding:16px 22px;margin:14px 0 6px 0">'
                    f'<span style="font-size:22px;font-weight:700">'
                    f'{_action_emoji(cs.action)} Recommendation: <span style="color:{_as_border}">'
                    f'{cs.action}</span></span>'
                    f'<span style="font-size:13px;color:#bbb;margin-left:16px">'
                    f'Score {cs.score:.0f}/100</span><br>'
                    f'<span style="font-size:13px;color:#ccc">'
                    f'Entry <b style="color:#fff">₹{cs.entry:,.2f}</b> &nbsp;·&nbsp; '
                    f'Stop <b style="color:#ef5350">₹{cs.stop_loss:,.2f}</b> '
                    f'<span style="color:#888">(-{(cs.price-cs.stop_loss)/cs.price*100:.1f}%)</span> &nbsp;·&nbsp; '
                    f'Target <b style="color:#26a69a">₹{cs.target:,.2f}</b> '
                    f'<span style="color:#888">(+{(cs.target-cs.price)/cs.price*100:.1f}%)</span> &nbsp;·&nbsp; '
                    f'R:R <b style="color:{_as_rr_color}">{cs.risk_reward:.1f}:1</b>'
                    f'</span></div>',
                    unsafe_allow_html=True,
                )

                # ── Plain-English explanation (easy to understand) ─────────
                st.markdown(
                    f'<div class="glass-panel" style="margin:8px 0 14px 0;padding:14px 18px">'
                    f'<div style="font-size:11px;color:#ff9500;font-weight:700;text-transform:uppercase;'
                    f'letter-spacing:1px;margin-bottom:6px">💬 In plain English</div>'
                    f'<div style="font-size:14px;line-height:1.7;color:#e0e0e0">'
                    f'{_plain_english(cs.action, cs.entry, cs.stop_loss, cs.target, cs.risk_reward)}'
                    f'</div></div>',
                    unsafe_allow_html=True,
                )

                # ── Multi-signal confirmation (timeframe + RS + earnings + agreement) ──
                with st.spinner("Running deep confirmation…"):
                    _dc = _deep_confirmation(ticker)
                _wk_map = {"uptrend": ("🟢 Uptrend", "#00d4aa"), "downtrend": ("🔴 Downtrend", "#ff4757"),
                           "sideways": ("🟡 Sideways", "#ff9500"), None: ("—", "#8899bb")}
                _wk_txt, _wk_c = _wk_map.get(_dc["weekly"], ("—", "#8899bb"))
                _rs_c   = "#00d4aa" if (_dc["rs_pct"] or 0) > 0 else "#ff4757"
                _rs_txt = (f'{_dc["rel_strength"].title()} ({_dc["rs_pct"]:+.1f}% vs Nifty)'
                           if _dc["rel_strength"] else "—")
                _ed_days = _dc["earnings_days"]
                if _ed_days is not None and 0 <= _ed_days <= 7:
                    _ed_txt, _ed_c = f"⚠️ Results in {_ed_days}d — avoid fresh buys", "#ff4757"
                elif _ed_days is not None and 0 <= _ed_days <= 21:
                    _ed_txt, _ed_c = f"Results in {_ed_days}d", "#ff9500"
                elif _ed_days is not None:
                    _ed_txt, _ed_c = f"Results in {_ed_days}d (clear)", "#00d4aa"
                else:
                    _ed_txt, _ed_c = "Unknown", "#8899bb"
                _bull, _tot = _dc["bull"], _dc["total"] or 9
                _agr_pct = _bull / _tot * 100
                _agr_c = "#00d4aa" if _agr_pct >= 67 else "#ff9500" if _agr_pct >= 40 else "#ff4757"

                st.markdown(
                    f'<div style="background:#0d1526;border:1px solid rgba(255,255,255,.06);border-radius:12px;'
                    f'padding:14px 18px;margin-bottom:12px">'
                    f'<div style="font-size:11px;color:#5b8def;font-weight:700;text-transform:uppercase;'
                    f'letter-spacing:1px;margin-bottom:10px">🔬 Multi-Signal Confirmation</div>'
                    f'<div style="display:flex;gap:22px;flex-wrap:wrap">'
                    f'<div><div style="font-size:10px;color:#4a5568">WEEKLY TREND</div>'
                    f'<div style="font-size:14px;font-weight:700;color:{_wk_c}">{_wk_txt}</div></div>'
                    f'<div><div style="font-size:10px;color:#4a5568">RELATIVE STRENGTH</div>'
                    f'<div style="font-size:14px;font-weight:700;color:{_rs_c}">{_rs_txt}</div></div>'
                    f'<div><div style="font-size:10px;color:#4a5568">EARNINGS</div>'
                    f'<div style="font-size:14px;font-weight:700;color:{_ed_c}">{_ed_txt}</div></div>'
                    f'<div><div style="font-size:10px;color:#4a5568">SIGNAL AGREEMENT</div>'
                    f'<div style="font-size:14px;font-weight:700;color:{_agr_c}">{_bull} of {_tot} bullish</div></div>'
                    f'</div></div>',
                    unsafe_allow_html=True,
                )
                # Signal checklist (expandable)
                with st.expander(f"🔎 See all {_tot} signals", expanded=False):
                    for _sname, _sok in _dc["signals"]:
                        st.markdown(
                            f'<div style="font-size:13px;color:#ccc;padding:2px 0">'
                            f'{"🟢" if _sok else "⚪"} {_sname}</div>',
                            unsafe_allow_html=True,
                        )

                _as_c1, _as_c2, _as_c3, _as_c4 = st.columns([1, 1, 1, 3])
                if _as_c1.button("➕ Watchlist", key=f"as_wl_{ticker}", use_container_width=True):
                    _wl = st.session_state.setdefault("watchlist", [])
                    if ticker not in _wl:
                        _wl.append(ticker)
                    st.toast(f"{ticker.replace('.NS','')} added to watchlist ✓")
                if _as_c2.button("📝 Paper Trade", key=f"as_pt_{ticker}", use_container_width=True):
                    st.session_state["nav"] = "📂 Paper Trades"
                    st.session_state["pt_prefill_ticker"] = ticker
                    st.rerun()
                if _as_c3.button("🔄 Re-Analyze", key=f"as_re_{ticker}", use_container_width=True):
                    st.cache_data.clear()
                    st.rerun()

                # ── Technical indicators ───────────────────────────────────
                st.markdown("---")
                ti_cols = st.columns(6)
                indicators_display = [
                    ("RSI (14)",    f"{latest.get('RSI', 0):.1f}",
                     "Oversold (<30)" if latest.get("RSI", 50) < 30
                     else "Overbought (>70)" if latest.get("RSI", 50) > 70
                     else "Normal"),
                    ("ADX",         f"{latest.get('ADX', 0):.1f}",
                     "Trending (>25)" if latest.get("ADX", 0) > 25 else "Ranging"),
                    ("ATR",         f"₹{latest.get('ATR', 0):.1f}", "Daily move range"),
                    ("Vol Ratio",   f"{latest.get('Volume_Ratio', 0):.2f}x",
                     "High volume" if latest.get("Volume_Ratio", 1) > 1.5 else "Normal"),
                    ("Stoch K",     f"{latest.get('Stoch_K', 50):.1f}",
                     "Oversold" if latest.get("Stoch_K", 50) < 20
                     else "Overbought" if latest.get("Stoch_K", 50) > 80 else ""),
                    ("VWAP %",      f"{latest.get('VWAP_Pct', 0):+.1f}%",
                     "Above VWAP" if latest.get("VWAP_Pct", 0) > 0 else "Below VWAP"),
                ]
                for (label, value, note), col in zip(indicators_display, ti_cols):
                    col.metric(label, value, note)

                # ── Candlestick patterns ───────────────────────────────────
                pat_cols = [c for c in df.columns if c.startswith("Pat_")]
                active_pats = [c.replace("Pat_", "").replace("_", " ")
                               for c in pat_cols if latest.get(c, 0) == 1]
                if active_pats:
                    st.info(f"📍 **Candlestick signals today:** {', '.join(active_pats)}")

                # RSI divergence
                if latest.get("RSI_Bull_Div", 0):
                    st.success("📈 **Bullish RSI Divergence detected** — momentum improving despite lower price")
                if latest.get("RSI_Bear_Div", 0):
                    st.warning("📉 **Bearish RSI Divergence detected** — momentum fading despite higher price")

                # ── Chart ─────────────────────────────────────────────────
                st.markdown("---")
                st.subheader("📊 Price Chart")
                # df_chart is the period-trimmed slice (indicators stay accurate
                # because they were computed on the full 2-year dataset)
                st.plotly_chart(build_price_chart(df_chart, ticker), width="stretch")

                # ── News feed ─────────────────────────────────────────────
                st.markdown("---")
                st.subheader(f"📰 Latest News — {get_display_name(ticker)}")
                with st.spinner("Loading news…"):
                    from utils.news import get_stock_news as _gsn
                    articles = _gsn(ticker, max_articles=6)
                if articles:
                    for art in articles:
                        s = art["sentiment"]
                        icon = "🟢" if s == "positive" else ("🔴" if s == "negative" else "⚪")
                        impact = ("Positive catalyst" if s == "positive"
                                  else "Negative signal" if s == "negative"
                                  else "Neutral update")
                        st.markdown(
                            f'{icon} **[{art["title"]}]({art["link"]})**  \n'
                            f'<span style="font-size:11px;color:#aaa">'
                            f'{art["publisher"]} · {art["time"]} · *{impact}*</span>',
                            unsafe_allow_html=True,
                        )
                else:
                    st.info("No recent news found for this stock.")

                # ── Trading summary box ────────────────────────────────────
                st.markdown("---")
                action_c = _action_color(cs.action)
                atr = float(df["ATR"].iloc[-1]) if "ATR" in df.columns else cs.price * 0.02
                st.markdown(
                    f'<div class="{action_c}" style="padding:16px">'
                    f'<b style="font-size:16px">Trading Plan — {ticker.replace(".NS","")}</b><br><br>'
                    f'<b>Signal:</b> {_action_emoji(cs.action)} {cs.action}&nbsp;&nbsp;'
                    f'<b>Score:</b> {cs.score:.0f}/100 [{cs.grade}]<br>'
                    f'<b>Entry zone:</b> ₹{cs.entry:,.2f} — ₹{cs.entry * 1.01:,.2f}<br>'
                    f'<b>Stop-loss:</b> ₹{cs.stop_loss:,.2f} '
                    f'<span style="color:#aaa;font-size:12px">'
                    f'(~{abs(cs.entry - cs.stop_loss)/cs.entry*100:.1f}% below entry, '
                    f'~1× ATR = ₹{atr:.1f})</span><br>'
                    f'<b>Target:</b> ₹{cs.target:,.2f} '
                    f'<span style="color:#aaa;font-size:12px">'
                    f'(R:R = {cs.risk_reward:.1f}:1)</span><br><br>'
                    f'<i>{cs.headline}</i>'
                    f'</div>',
                    unsafe_allow_html=True,
                )

                # ── Paper Trade This Signal ────────────────────────────────
                st.markdown("---")
                _pbt_col, _pbt_info = st.columns([1, 3])
                with _pbt_col:
                    if st.button(f"📌 Paper Trade This Signal", type="primary", key="analyze_pt_btn"):
                        _pt_qty = max(1, int(10000 / cs.entry)) if cs.entry > 0 else 1
                        _new_trade_id = paper_open_trade(
                            ticker, cs.entry, _pt_qty,
                            sl=cs.stop_loss, tp=cs.target,
                            reason=f"{cs.action} score={cs.score:.0f}: {cs.headline}",
                            account=st.session_state.get("pt_account", "My Account"),
                        )
                        st.success(
                            f"✅ Paper trade #{_new_trade_id} opened:  "
                            f"**{_pt_qty} × {ticker.replace('.NS','')}** @ ₹{cs.entry:,.2f}  "
                            f"| SL ₹{cs.stop_loss:,.2f} | Target ₹{cs.target:,.2f}  "
                            f"| Potential gain ₹{(cs.target - cs.entry)*_pt_qty:,.0f}"
                        )
                with _pbt_info:
                    st.info(
                        "📌 **Paper Trading** lets you test this signal without real money. "
                        "Track it in the **📂 Paper Trades** page to see if the model's calls are accurate."
                    )

            except Exception as e:
                st.error(f"Analysis failed: {e}")
                import traceback
                st.code(traceback.format_exc())


# ═══════════════════════════════════════════════════════════════════════════════
# PAGE 3 — MARKET OVERVIEW
# ═══════════════════════════════════════════════════════════════════════════════
elif page == "📊 Market Overview":
    st.title("📊 Market Overview")
    st.caption("Live market snapshot — VIX, sector momentum, and top movers")

    if st.button("🔄 Refresh Data", type="primary"):
        st.cache_data.clear()

    # ── India VIX section ──────────────────────────────────────────────────
    with st.spinner("Loading VIX & Nifty…"):
        try:
            vix_df, nifty_df = load_vix_data()
            curr_vix   = float(vix_df["Close"].iloc[-1])
            prev_vix   = float(vix_df["Close"].iloc[-2])
            vix_chg    = (curr_vix / prev_vix - 1) * 100
            vix_52w_hi = float(vix_df["High"].max())
            vix_52w_lo = float(vix_df["Low"].min())
            vix_rank   = (curr_vix - vix_52w_lo) / max(vix_52w_hi - vix_52w_lo, 0.01) * 100
            curr_nifty = float(nifty_df["Close"].iloc[-1])
            nifty_chg  = float(nifty_df["Close"].pct_change().iloc[-1]) * 100

            if curr_vix < 12:    regime, reg_color = "Extreme Complacency", "#FF6B35"
            elif curr_vix < 16:  regime, reg_color = "Low Volatility",       "#4ECDC4"
            elif curr_vix < 22:  regime, reg_color = "Normal",                "#45B7D1"
            elif curr_vix < 28:  regime, reg_color = "Elevated Fear",         "#F7DC6F"
            elif curr_vix < 35:  regime, reg_color = "High Fear",             "#E74C3C"
            else:                regime, reg_color = "PANIC / Crisis",         "#8E44AD"

            if curr_vix < 15:   opt_str = "BUY options (cheap premium)"
            elif curr_vix < 22: opt_str = "SPREADS (balanced IV)"
            elif curr_vix < 28: opt_str = "SELL premium with spreads"
            else:               opt_str = "SELL wide spreads / long if conviction"

            # Divergence
            if nifty_chg > 0 and vix_chg > 0:
                div_txt = "⚠️ Warning: Nifty ↑ + VIX ↑ — fragile rally"
            elif nifty_chg < 0 and vix_chg < 0:
                div_txt = "🟢 Nifty ↓ + VIX ↓ — oversold bounce watch"
            elif nifty_chg > 0 and vix_chg < 0:
                div_txt = "✅ Healthy rally — fear leaving market"
            else:
                div_txt = "✅ Normal correction — fear rising with selling"

            st.subheader("🌡️ Fear Gauge — India VIX")
            st.markdown(
                f'<div style="background:{reg_color};padding:12px 18px;border-radius:10px;'
                f'color:#000;font-weight:700;font-size:18px;text-align:center;">'
                f'VIX {curr_vix:.2f}  ({vix_chg:+.1f}% today)  —  {regime}  |  '
                f'Options regime: {opt_str}'
                f'</div>',
                unsafe_allow_html=True
            )
            st.markdown(f"**Divergence signal:** {div_txt}")

            v_col1, v_col2, v_col3, v_col4 = st.columns(4)
            v_col1.metric("India VIX",    f"{curr_vix:.2f}", f"{vix_chg:+.1f}%")
            v_col2.metric("VIX Rank",     f"{vix_rank:.0f}%  (52w)")
            v_col3.metric("Nifty 50",     f"{curr_nifty:,.0f}", f"{nifty_chg:+.2f}%")
            v_col4.metric("52w VIX Range",f"{vix_52w_lo:.1f} – {vix_52w_hi:.1f}")

            fig_vix = go.Figure()
            fig_vix.add_trace(go.Scatter(
                x=vix_df.index, y=vix_df["Close"],
                name="India VIX", line=dict(color="#FF6B6B", width=2),
                fill="tozeroy", fillcolor="rgba(255,107,107,0.1)",
            ))
            for lo, hi, clr, lbl in [
                (0, 12, "rgba(76,175,80,.12)", "Safe"),
                (12, 22, "rgba(255,193,7,.12)", "Normal"),
                (22, 28, "rgba(255,87,34,.12)", "Caution"),
                (28, 100, "rgba(156,39,176,.12)", "Fear"),
            ]:
                fig_vix.add_hrect(y0=lo, y1=hi, fillcolor=clr,
                                  annotation_text=lbl, annotation_position="left",
                                  line_width=0)
            fig_vix.update_layout(
                title="India VIX — 1 Year",
                template="plotly_dark", height=300,
                xaxis_rangeslider_visible=False,
                margin=dict(l=0, r=0, t=40, b=0),
            )
            st.plotly_chart(fig_vix, width="stretch")

        except Exception as e:
            st.warning(f"VIX load error: {e}")

    # ── Sector Rotation ────────────────────────────────────────────────────
    st.markdown("---")
    st.subheader("🔄 Sector Momentum Heatmap")

    @st.cache_data(ttl=1800)
    def get_sector_data():
        from strategies.sector_rotation import compute_sector_scores
        return compute_sector_scores(period="1y")

    with st.spinner("Computing sector scores…"):
        try:
            scores = get_sector_data()
            if not scores.empty:
                s_col1, s_col2 = st.columns([1, 1])
                with s_col1:
                    disp = scores[["mom_20d", "mom_60d", "composite_score", "Rank"]].copy()
                    disp.columns = ["20d (%)", "60d (%)", "Score", "Rank"]
                    st.dataframe(
                        disp.style
                        .background_gradient(subset=["Score"], cmap="RdYlGn")
                        .format("{:.2f}"),
                        width="stretch",
                    )
                with s_col2:
                    fig_bar = px.bar(
                        scores.reset_index(), x="Sector", y="composite_score",
                        color="composite_score", color_continuous_scale="RdYlGn",
                        title="Sector Scores",
                        labels={"composite_score": "Score (%)"},
                    )
                    fig_bar.update_layout(
                        template="plotly_dark", height=340, showlegend=False,
                        margin=dict(l=0, r=0, t=40, b=0),
                    )
                    st.plotly_chart(fig_bar, width="stretch")
        except Exception as e:
            st.warning(f"Sector scores error: {e}")

    # ── Top movers from NIFTY50 ────────────────────────────────────────────
    st.markdown("---")
    st.subheader("🚀 NIFTY50 Top Movers")

    @st.cache_data(ttl=180)
    def get_top_movers():
        """
        Fetch Nifty50 movers using Yahoo JSON direct API (cloud-safe, no rate limits).
        Falls back to Stooq EOD price if Yahoo JSON fails for a ticker.
        """
        from data.fetcher import NIFTY50_TICKERS
        from utils.live_price import get_live_prices_batch
        tickers_list = list(NIFTY50_TICKERS[:50])

        # Parallel fetch — Yahoo JSON tier 1, NSE tier 2, Stooq EOD tier 3
        raw = get_live_prices_batch(tickers_list, max_workers=12)

        rows = []
        for t in tickers_list:
            q = raw.get(t)
            if not isinstance(q, dict) or not q.get("price"):
                continue
            try:
                rows.append({
                    "Ticker":   t,                               # keep .NS for routing
                    "Price":    round(q["price"],     2),
                    "Day (%)":  round(q["chg_pct"],   2),
                    "Prev":     round(q["prev_close"], 2),
                    "5d (%)":   round(q["chg_pct"],   2),       # same as day when using EOD
                    "Vol Ratio": 1.0,
                })
            except Exception:
                continue
        return pd.DataFrame(rows).sort_values("Day (%)", ascending=False) if rows else pd.DataFrame()

    with st.spinner("Fetching NIFTY50 movers…"):
        movers = get_top_movers()
        if not movers.empty:
            top5 = movers.head(5)
            bot5 = movers.tail(5)
            m1, m2 = st.columns(2)

            def _mover_row(row, is_gain: bool):
                chg   = row["Day (%)"]
                price = row["Price"]
                tick  = row["Ticker"]  # e.g. "RELIANCE.NS"
                short = tick.replace(".NS", "")
                color = "#26a69a" if is_gain else "#ef5350"
                sign  = "+" if is_gain else ""
                card_cls = "card-green" if is_gain else "card-red"
                st.markdown(
                    f'<div class="{card_cls}" style="padding:8px 14px;margin-bottom:4px">'
                    f'<b style="font-size:14px">{short}</b>'
                    f'<span style="float:right;font-size:13px">₹{price:,.2f} '
                    f'<b style="color:{color}">{sign}{chg:.2f}%</b></span>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
                btn_a, btn_b, btn_c = st.columns([1, 1, 1])
                if btn_a.button("📊 Analyze", key=f"mover_analyze_{tick}",
                                use_container_width=True):
                    st.session_state["nav"] = "🔍 Analyze Stock"
                    st.session_state["manual_ticker_input"] = short
                    st.session_state["last_analyzed"] = tick
                    st.rerun()
                if btn_b.button("📝 Paper Trade", key=f"mover_trade_{tick}",
                                use_container_width=True):
                    st.session_state["nav"] = "📂 Paper Trades"
                    st.session_state["pt_prefill_ticker"] = tick
                    st.rerun()
                if btn_c.button("＋ Watchlist", key=f"mover_wl_{tick}",
                                use_container_width=True):
                    if tick not in st.session_state.get("watchlist", []):
                        st.session_state.setdefault("watchlist", []).append(tick)
                    st.toast(f"{short} added to watchlist ✓")

            with m1:
                st.markdown("**📈 Top Gainers Today**")
                for _, row in top5.iterrows():
                    _mover_row(row, is_gain=True)
            with m2:
                st.markdown("**📉 Top Losers Today**")
                for _, row in bot5.iterrows():
                    _mover_row(row, is_gain=False)


# ═══════════════════════════════════════════════════════════════════════════════
# PAGE 4 — SMART SCREENER
# ═══════════════════════════════════════════════════════════════════════════════
elif page == "🔎 Smart Screener":
    st.title("🔎 Smart Stock Screener")
    st.markdown(
        "Scan the NSE universe using 4 proven screens — oversold bounce, "
        "momentum leaders, breakouts, and pullback entries.  \n"
        "Each match is enriched with a composite score."
    )

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
        enrich_scores = st.checkbox("Enrich with composite score", value=True,
                                    help="Adds 0-100 score to each result (slower)")

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
                    except Exception:
                        sig["composite_score"] = 50
                        sig["grade"]           = "C"
                        sig["action"]          = sig.get("action", "WATCHLIST")
                        sig["narrative"]       = "—"
                    scored_signals.append(sig)
                    prog.progress((i + 1) / len(signals))
                signals = sorted(scored_signals, key=lambda x: x.get("composite_score", 0), reverse=True)

            # Display results as Trade Setup Cards
            for sig in signals[:30]:  # cap at 30 for performance
                t      = sig["ticker"].replace(".NS", "")
                action = sig.get("action", "WATCHLIST")
                card   = _action_color(action)
                emoji  = _action_emoji(action)
                _s_price = sig.get("price", 0)
                _s_sl    = sig.get("sl", sig.get("stop_loss", 0)) or 0
                _s_tp    = sig.get("tp", sig.get("target", None))
                _s_rr    = (
                    sig.get("rr_ratio") or
                    (round((_s_tp - _s_price) / max(_s_price - _s_sl, 0.01), 1) if _s_tp else None)
                )
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
                with st.expander(_header, expanded=False):
                    d1, d2, d3, d4, d5 = st.columns(5)
                    d1.metric("Entry",  f"₹{_s_price:,.2f}")
                    d2.metric("Stop-Loss", f"₹{_s_sl:,.2f}",
                              delta=f"({_s_stop_type})",
                              delta_color="off")
                    d3.metric("Target", f"₹{_s_tp:,.2f}" if _s_tp else "Trail SMA20")
                    d4.metric("R:R",    f"{_s_rr:.1f}x" if _s_rr else "—",
                              delta="✅ Good" if (_s_rr or 0) >= 2 else "⚠️ Low",
                              delta_color="normal" if (_s_rr or 0) >= 2 else "inverse")
                    d5.metric("Sector", _s_sector or "—")
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
elif page == "📂 Paper Trades":
    st.title("📂 Paper Trading Simulator")
    st.markdown(
        "Practice trading **without real money**. Open virtual trades, track live P&L, "
        "and measure your decision quality over time. All prices are from live market data."
    )

    # Pre-fill ticker if navigated from Market Live / Market Overview "Trade" button
    if "pt_prefill_ticker" in st.session_state and st.session_state["pt_prefill_ticker"]:
        _pf_sym = st.session_state.pop("pt_prefill_ticker")
        _pf_clean = _pf_sym.replace(".NS", "")
        st.session_state["pt_manual_tk"] = _pf_clean
        st.info(f"📝 Pre-filled from Market Overview: **{_pf_clean}** — live price loading…")

    _ensure_paper_db()

    # ── ACCOUNT MANAGEMENT BAR ─────────────────────────────────────────────────
    _all_accounts = paper_list_accounts()
    # Ensure session state has a valid account
    if "pt_account" not in st.session_state or st.session_state["pt_account"] not in _all_accounts:
        st.session_state["pt_account"] = _all_accounts[0]

    with st.container():
        st.markdown(
            '<div style="background:#0d1f3c;padding:12px 18px;border-radius:10px;'
            'border-left:5px solid #2196F3;margin-bottom:16px">',
            unsafe_allow_html=True,
        )
        _acc_c1, _acc_c2, _acc_c3, _acc_c4, _acc_c5 = st.columns([3, 1, 1, 1, 1])

        with _acc_c1:
            _selected_account = st.selectbox(
                "📂 Active Account",
                options=_all_accounts,
                index=_all_accounts.index(st.session_state["pt_account"]),
                key="pt_account_sel",
                label_visibility="collapsed",
            )
            st.session_state["pt_account"] = _selected_account
            _acc_type = paper_account_type(_selected_account)
            _at_badge = ("🔆 INTRADAY (MIS)" if _acc_type == "MIS" else "📦 DELIVERY (CNC)")
            _at_col   = "#ff9500" if _acc_type == "MIS" else "#5b8def"
            st.markdown(
                f'<span style="font-size:11px">📂 <b>{_selected_account}</b> '
                f'<span style="color:{_at_col};font-weight:700">· {_at_badge}</span></span>',
                unsafe_allow_html=True,
            )

        with _acc_c2:
            _new_acc_name = st.text_input(
                "New account name", value="", placeholder="New account…",
                label_visibility="collapsed", key="pt_new_acc_input"
            ).strip()
            _new_acc_type = st.radio(
                "Type", ["Delivery", "Intraday"], horizontal=True,
                label_visibility="collapsed", key="pt_new_acc_type",
            )

        with _acc_c3:
            st.write("")
            if st.button("➕ Create", key="pt_create_acc", use_container_width=True):
                if _new_acc_name and _new_acc_name not in _all_accounts:
                    set_paper_account_type(_new_acc_name,
                                           "MIS" if _new_acc_type == "Intraday" else "CNC")
                    st.session_state["pt_account"] = _new_acc_name
                    st.success(f"**{_new_acc_name}** ({_new_acc_type}) created. Open your first trade to save it.")
                    st.rerun()
                elif _new_acc_name in _all_accounts:
                    st.warning("Account already exists.")

        with _acc_c4:
            st.write("")
            _rename_to = st.text_input(
                "Rename to", value="", placeholder="Rename to…",
                label_visibility="collapsed", key="pt_rename_input"
            ).strip()

        with _acc_c5:
            st.write("")
            if st.button("✏️ Rename", key="pt_rename_acc", use_container_width=True):
                if _rename_to and _rename_to != _selected_account:
                    paper_rename_account(_selected_account, _rename_to)
                    st.session_state["pt_account"] = _rename_to
                    st.success(f"Renamed to **{_rename_to}**")
                    st.rerun()
                elif not _rename_to:
                    st.warning("Enter a new name first.")

        st.markdown("</div>", unsafe_allow_html=True)

    # Delete account (separate row to avoid layout clutter)
    if len(_all_accounts) > 1:
        with st.expander("🗑️ Danger Zone — Delete Account", expanded=False):
            st.warning(
                f"This will permanently delete **all trades** in account "
                f"**{_selected_account}**. This cannot be undone."
            )
            _del_confirm = st.checkbox(
                f"Yes, I want to delete account '{_selected_account}' and all its trades",
                key="pt_del_confirm"
            )
            if st.button("🗑️ Delete Account", key="pt_delete_acc",
                         disabled=not _del_confirm, type="secondary"):
                paper_delete_account(_selected_account)
                # Switch to first remaining account
                _remaining = [a for a in _all_accounts if a != _selected_account]
                st.session_state["pt_account"] = _remaining[0] if _remaining else "My Account"
                st.success(f"Account **{_selected_account}** deleted.")
                st.rerun()

    # ── Intraday (MIS) square-off reminder ─────────────────────────────────────
    if paper_account_type(_selected_account) == "MIS":
        import datetime as _sqdt
        _ist_now = _sqdt.datetime.now(_sqdt.timezone(_sqdt.timedelta(hours=5, minutes=30)))
        _is_weekday = _ist_now.weekday() < 5
        _mins_to_close = (15 * 60 + 20) - (_ist_now.hour * 60 + _ist_now.minute)  # to 3:20 PM
        if _is_weekday and 0 < _mins_to_close <= 60:
            st.markdown(
                f'<div class="card-red pulse-red" style="margin:6px 0">'
                f'⏰ <b>Intraday square-off in {_mins_to_close} min</b> (by 3:20 PM). '
                f'Close MIS positions now — brokers auto-square-off intraday trades near close.</div>',
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                '<div class="card-yellow" style="margin:6px 0">'
                '🔆 <b>Intraday (MIS) account</b> — positions are meant to be closed the same day '
                '(by ~3:20 PM). Use tighter stops than delivery.</div>',
                unsafe_allow_html=True,
            )

    st.markdown("---")

    # ── LIVE PRICE + ATR SUGGESTIONS (cached 60 s per ticker) ─────────────────
    @st.cache_data(ttl=60, show_spinner=False)
    def _paper_trade_suggestions(ticker: str) -> dict:
        """
        Live price (Yahoo JSON API) + ATR-based SL/TP + RSI + trend.
        All data sources are cloud-safe (no yfinance rate limits).
        Returns dict: price, prev, chg, atr, sl, tp, rsi, trend, qty_suggest, error
        """
        import pandas as _pd2
        from utils.live_price import get_live_quote
        from data.fetcher import fetch_single

        result = {"price": None, "prev": None, "chg": 0.0,
                  "atr": None, "sl": None, "tp": None,
                  "rsi": None, "trend": "—", "qty_suggest": 1, "error": ""}
        try:
            # ── Live price via Yahoo JSON API / NSE / Stooq ────────────────
            q = get_live_quote(ticker)
            if not isinstance(q, dict) or not q.get("price"):
                result["error"] = "Price unavailable — all sources failed. Try again in 30 s."
                return result

            price = q["price"]
            prev  = q["prev_close"]
            chg   = q["chg_pct"]
            result.update({"price": price, "prev": prev, "chg": chg})

            # ── Historical data for ATR + RSI + trend via Stooq ───────────
            df = fetch_single(ticker, period="3mo")
            df = df.dropna(subset=["Close"])
            if len(df) < 15:
                # Fallback: simple % stops
                result["sl"] = round(price * 0.97, 2)   # 3% stop
                result["tp"] = round(price * 1.06, 2)   # 6% target → 2:1
                result["qty_suggest"] = max(1, int(10000 / price))
                return result

            # ATR (14)
            hi, lo, cl = df["High"], df["Low"], df["Close"]
            tr  = _pd2.concat([hi - lo,
                                (hi - cl.shift()).abs(),
                                (lo - cl.shift()).abs()], axis=1).max(axis=1)
            atr = float(tr.rolling(14).mean().dropna().iloc[-1])
            result["atr"] = atr

            # Stop = 1.5 × ATR below live price  →  tight but realistic
            # Target = 3.0 × ATR above live price  →  exactly 2:1 R:R
            sl_calc = round(price - 1.5 * atr, 2)
            tp_calc = round(price + 3.0 * atr, 2)
            result["sl"] = max(0.01, sl_calc)
            result["tp"] = tp_calc

            # RSI (14)
            delta = cl.diff()
            gain  = delta.clip(lower=0).rolling(14).mean()
            loss  = (-delta.clip(upper=0)).rolling(14).mean()
            rsi   = float((100 - 100 / (1 + gain / loss)).dropna().iloc[-1])
            result["rsi"] = rsi

            # Simple trend signal
            sma50  = float(cl.rolling(50).mean().iloc[-1]) if len(df) >= 50 else price
            sma200 = float(cl.rolling(200).mean().iloc[-1]) if len(df) >= 200 else price
            if price > sma50 > sma200:
                result["trend"] = "🟢 Uptrend (above SMA50 & SMA200)"
            elif price > sma50:
                result["trend"] = "🟡 Moderate (above SMA50)"
            elif price < sma50 < sma200:
                result["trend"] = "🔴 Downtrend (below SMA50 & SMA200)"
            else:
                result["trend"] = "🟡 Mixed — check chart"

            # Suggested qty: ~₹10,000 position (small safe default)
            result["qty_suggest"] = max(1, int(10000 / price))

        except Exception as _exc:
            result["error"] = str(_exc)
        return result

    # ── NEW TRADE FORM ─────────────────────────────────────────────────────────
    with st.expander("➕ Open a New Paper Trade", expanded=True):
        st.markdown(
            "**Select a stock** — the entry price, stop-loss, and target are auto-filled "
            "from live market data and ATR analysis. You can adjust them freely before submitting."
        )
        _search_opts = sorted([f"{n}  ({s.replace('.NS','')})" for n, s in STOCK_SEARCH_MAP.items()])
        _fc1, _fc2 = st.columns([3, 2])
        with _fc1:
            _form_sel = st.selectbox("Search by company name", ["— choose stock —"] + _search_opts, key="pt_stock_sel")
        with _fc2:
            _form_manual = st.text_input("Or type NSE ticker directly", key="pt_manual_tk",
                                         placeholder="e.g. INFY").strip().upper()

        # Resolve ticker
        _form_ticker = ""
        if _form_manual:
            _form_ticker = _form_manual if _form_manual.endswith(".NS") else _form_manual + ".NS"
        elif _form_sel != "— choose stock —":
            _raw = _form_sel.rsplit("(", 1)[-1].rstrip(")")
            _form_ticker = _raw + ".NS" if not _raw.endswith(".NS") else _raw

        # ── Fetch live data & suggestions ─────────────────────────────────
        _sugg = {"price": None, "sl": None, "tp": None, "qty_suggest": 10,
                 "atr": None, "rsi": None, "trend": "—", "chg": 0.0, "error": ""}
        if _form_ticker:
            with st.spinner(f"Fetching live price & ATR for {_form_ticker.replace('.NS','')}…"):
                _sugg = _paper_trade_suggestions(_form_ticker)

        # ── Suggestion banner ──────────────────────────────────────────────
        if _form_ticker and _sugg["price"]:
            _p    = _sugg["price"]
            _atr  = _sugg["atr"]
            _rsi  = _sugg["rsi"]
            _atr_str = f"₹{_atr:.2f}" if _atr else "—"
            _rsi_str = f"{_rsi:.0f}" if _rsi else "—"
            _rsi_label = (
                "🔴 Overbought — watch for pullback" if (_rsi and _rsi > 70)
                else "🟢 Oversold — bounce candidate"  if (_rsi and _rsi < 30)
                else "🟡 Neutral momentum"              if _rsi
                else ""
            )
            st.markdown(
                f'<div style="background:#0d1f3c;padding:12px 18px;border-radius:10px;'
                f'border-left:5px solid #2196F3;margin:8px 0">'
                f'<b style="font-size:18px">₹{_p:,.2f}</b>'
                f'<span style="color:{"#26a69a" if _sugg["chg"]>=0 else "#ef5350"};margin-left:10px">'
                f'{"▲" if _sugg["chg"]>=0 else "▼"} {abs(_sugg["chg"]):.2f}% today</span>'
                f'<br><span style="font-size:12px;color:#aaa">'
                f'ATR(14): {_atr_str} &nbsp;|&nbsp; RSI: {_rsi_str} {_rsi_label}'
                f' &nbsp;|&nbsp; Trend: {_sugg["trend"]}</span>'
                f'</div>',
                unsafe_allow_html=True
            )
        elif _form_ticker and _sugg["error"]:
            st.warning(f"⚠️ {_sugg['error']}")

        # ── Input fields — defaults from live data, keyed by ticker so they
        #    reset automatically when the user picks a different stock ────────
        _tk_key = _form_ticker or "none"      # key suffix changes → fresh widget defaults
        _def_price = _sugg["price"]  or 100.0
        _def_sl    = _sugg["sl"]     or round(_def_price * 0.97, 2)
        _def_tp    = _sugg["tp"]     or round(_def_price * 1.06, 2)
        _def_qty   = _sugg["qty_suggest"] or 10

        _pa, _pb, _pc, _pd = st.columns(4)
        _form_qty   = _pa.number_input(
            "Quantity (shares)", 1, 1000000, _def_qty,
            key=f"pt_qty_{_tk_key}"
        )
        _form_price = _pb.number_input(
            "Entry Price (₹) — live", 0.01, 1e7, float(_def_price),
            key=f"pt_price_{_tk_key}", format="%.2f"
        )
        _form_sl    = _pc.number_input(
            "Stop-Loss (₹) — ATR-based", 0.01, 1e7, float(_def_sl),
            key=f"pt_sl_{_tk_key}", format="%.2f",
            help="Default = 1.5× ATR below live price. Adjust to your preferred risk level."
        )
        _form_tp    = _pd.number_input(
            "Target (₹) — 2:1 R:R", 0.01, 1e7, float(_def_tp),
            key=f"pt_tp_{_tk_key}", format="%.2f",
            help="Default = 3× ATR above live price (gives 2:1 Risk:Reward). Adjust as needed."
        )

        # ── Live Risk:Reward summary ───────────────────────────────────────
        if _form_price > 0 and _form_sl < _form_price and _form_tp > _form_price:
            _risk_ps  = _form_price - _form_sl
            _rew_ps   = _form_tp    - _form_price
            _rr_ratio = _rew_ps / _risk_ps if _risk_ps > 0 else 0
            _cap_risk = _risk_ps * _form_qty
            _cap_rew  = _rew_ps  * _form_qty
            _rr_color = "#26a69a" if _rr_ratio >= 1.5 else "#f9a825" if _rr_ratio >= 1.0 else "#ef5350"
            st.markdown(
                f'<div style="background:#1a1a2a;padding:10px 16px;border-radius:8px;margin:8px 0">'
                f'Risk/share: <b style="color:#ef5350">₹{_risk_ps:.2f}</b> &nbsp;|&nbsp; '
                f'Reward/share: <b style="color:#26a69a">₹{_rew_ps:.2f}</b> &nbsp;|&nbsp; '
                f'<span style="color:{_rr_color}"><b>R:R = {_rr_ratio:.1f}:1</b></span> &nbsp;|&nbsp; '
                f'Max loss on trade: <b style="color:#ef5350">₹{_cap_risk:,.0f}</b> &nbsp;|&nbsp; '
                f'Max gain on trade: <b style="color:#26a69a">₹{_cap_rew:,.0f}</b>'
                f'</div>',
                unsafe_allow_html=True
            )
            if _rr_ratio < 1.0:
                st.error("⛔ R:R below 1:1 — you risk more than you can gain. Adjust your stop or target.")
            elif _rr_ratio < 1.5:
                st.warning("⚠️ R:R below 1.5:1 — minimum recommended is 1.5:1 for a consistent edge.")
            else:
                st.success(f"✅ Good R:R ({_rr_ratio:.1f}:1) — trade setup meets the minimum quality bar.")

        _form_reason = st.text_input(
            "Reason / notes (optional)", key="pt_reason",
            placeholder="e.g. RSI oversold bounce at SMA50 support — score 72"
        )

        if st.button("🟢 Open Paper Trade", type="primary", key="pt_submit"):
            if not _form_ticker:
                st.error("Please select a stock first.")
            elif _form_sl >= _form_price:
                st.error("Stop-loss must be BELOW entry price.")
            elif _form_tp <= _form_price:
                st.error("Target must be ABOVE entry price.")
            else:
                _new_id = paper_open_trade(
                    _form_ticker, _form_price, int(_form_qty),
                    sl=_form_sl, tp=_form_tp, reason=_form_reason,
                    account=st.session_state.get("pt_account", "My Account"),
                )
                st.success(
                    f"✅ Paper trade #{_new_id} opened in **{st.session_state.get('pt_account','My Account')}**: "
                    f"**{int(_form_qty)} × {_form_ticker.replace('.NS','')}** @ ₹{_form_price:,.2f}  "
                    f"| SL ₹{_form_sl:,.2f} | Target ₹{_form_tp:,.2f}"
                )
                st.cache_data.clear()

    st.markdown("---")

    # ── LOAD TRADES FOR CURRENT ACCOUNT ───────────────────────────────────────
    _hcol, _tcol, _rcol = st.columns([4, 2, 1])
    with _hcol:
        st.markdown(f"#### 📂 {st.session_state.get('pt_account', 'My Account')}")
    with _tcol:
        _pt_autoclose = st.toggle(
            "🤖 Auto-close SL/TP", value=st.session_state.get("auto_close_on", True),
            key="pt_autoclose_toggle",
            help="Automatically close any position that hits its target or stop-loss "
                 "on page load — during market hours only, on live prices.",
        )
        st.session_state["auto_close_on"] = _pt_autoclose
    with _rcol:
        st.write("")
        if st.button("🔄 Refresh", key="paper_refresh"):
            st.cache_data.clear()

    # Run auto-close for this account, then surface what was closed
    if _pt_autoclose:
        _pt_closed = _auto_close_breached(account=st.session_state.get("pt_account", "My Account"))
        if _pt_closed:
            _render_autoclose_banner(_pt_closed)
            st.cache_data.clear()

    trades = load_trades_by_account(st.session_state.get("pt_account", "My Account"))

    if trades.empty:
        st.info("No paper trades yet. Open your first trade using the form above.")
    else:
        open_t     = trades[trades["status"] == "OPEN"]    if "status" in trades.columns else pd.DataFrame()
        closed_t   = trades[trades["status"] == "CLOSED"]  if "status" in trades.columns else pd.DataFrame()
        stopped_t  = trades[trades["status"] == "STOPPED"] if "status" in trades.columns else pd.DataFrame()
        all_closed = pd.concat([closed_t, stopped_t], ignore_index=True)

        # ── Fetch live prices BEFORE summary so we can show unrealised P&L ──
        _open_syms = tuple(open_t["ticker"].tolist()) if not open_t.empty else ()
        _open_lp   = _portfolio_live_prices(_open_syms) if _open_syms else {}

        # ── Aggregate account-level P&L ────────────────────────────────────
        _pt_deployed   = 0.0
        _pt_unrealised = 0.0
        _pt_today_pnl  = 0.0
        for _, _orow in open_t.iterrows():
            _o_ep   = float(_orow.get("price",    0) or 0)
            _o_qty  = int(  _orow.get("quantity", 0) or 0)
            _o_lp   = _open_lp.get(str(_orow["ticker"]), {})
            _o_cur  = _o_lp.get("price", _o_ep)
            _o_prv  = _o_lp.get("prev",  _o_cur)
            _pt_deployed   += _o_ep  * _o_qty
            _pt_unrealised += (_o_cur - _o_ep) * _o_qty
            _pt_today_pnl  += (_o_cur - _o_prv) * _o_qty

        _pt_realised = 0.0
        _wins_cnt    = 0
        if not all_closed.empty and "pnl" in all_closed.columns:
            _all_cl_pnl  = pd.to_numeric(all_closed["pnl"], errors="coerce")
            _pt_realised = float(_all_cl_pnl.sum())
            _wins_cnt    = int((_all_cl_pnl > 0).sum())

        _pt_unr_pct = (_pt_unrealised / _pt_deployed * 100) if _pt_deployed > 0 else 0

        # ── Account Dashboard Card ─────────────────────────────────────────
        _ac_name  = st.session_state.get("pt_account", "My Account")
        _ur_col = "#26a69a" if _pt_unrealised >= 0 else "#ef5350"
        _re_col = "#26a69a" if _pt_realised   >= 0 else "#ef5350"
        _td_col = "#26a69a" if _pt_today_pnl  >= 0 else "#ef5350"
        _ur_arr = "▲" if _pt_unrealised >= 0 else "▼"
        _re_arr = "▲" if _pt_realised   >= 0 else "▼"
        _td_arr = "▲" if _pt_today_pnl  >= 0 else "▼"
        _n_open   = len(open_t)
        _n_closed = len(all_closed)
        st.markdown(
            f'<div style="background:#0d1f3c;border-radius:12px;padding:18px 22px;'
            f'margin-bottom:16px;border-left:5px solid #2196F3">'
            f'<div style="font-size:11px;color:#5c8dd6;text-transform:uppercase;'
            f'letter-spacing:1.5px;margin-bottom:12px">📂 {_ac_name}</div>'
            f'<div style="display:flex;gap:20px;flex-wrap:wrap;align-items:flex-start">'

            f'<div style="min-width:140px">'
            f'<div style="font-size:10px;color:#aaa;text-transform:uppercase;letter-spacing:1px;margin-bottom:3px">Today\'s P&amp;L</div>'
            f'<div style="font-size:22px;font-weight:700;color:{_td_col}">{_td_arr} ₹{abs(_pt_today_pnl):,.0f}</div>'
            f'</div>'

            f'<div style="min-width:170px">'
            f'<div style="font-size:10px;color:#aaa;text-transform:uppercase;letter-spacing:1px;margin-bottom:3px">Unrealised P&amp;L</div>'
            f'<div style="font-size:22px;font-weight:700;color:{_ur_col}">{_ur_arr} ₹{abs(_pt_unrealised):,.0f} '
            f'<span style="font-size:13px">({_pt_unr_pct:+.1f}%)</span></div>'
            f'</div>'

            f'<div style="min-width:170px">'
            f'<div style="font-size:10px;color:#aaa;text-transform:uppercase;letter-spacing:1px;margin-bottom:3px">'
            f'Realised P&amp;L &nbsp;<span style="color:#888">({_wins_cnt}/{_n_closed} won)</span></div>'
            f'<div style="font-size:22px;font-weight:700;color:{_re_col}">{_re_arr} ₹{abs(_pt_realised):,.0f}</div>'
            f'</div>'

            f'<div style="min-width:140px">'
            f'<div style="font-size:10px;color:#aaa;text-transform:uppercase;letter-spacing:1px;margin-bottom:3px">Deployed Capital</div>'
            f'<div style="font-size:22px;font-weight:700;color:#fff">₹{_pt_deployed:,.0f}</div>'
            f'</div>'

            f'<div style="min-width:110px">'
            f'<div style="font-size:10px;color:#aaa;text-transform:uppercase;letter-spacing:1px;margin-bottom:3px">Positions</div>'
            f'<div style="font-size:20px;font-weight:700">'
            f'<span style="color:#26a69a">{_n_open}</span> open &nbsp; '
            f'<span style="color:#aaa;font-size:16px">{_n_closed} closed</span></div>'
            f'</div>'

            f'</div></div>',
            unsafe_allow_html=True,
        )

        st.markdown("---")

        # ── OPEN POSITIONS — compact cards with progress bar ───────────────
        if not open_t.empty:
            st.subheader("📌 Open Positions")

            for _, _row in open_t.iterrows():
                _tk   = _row["ticker"]
                _ep   = float(_row["price"])
                _qty  = int(_row["quantity"])
                _sl   = float(_row["sl"]) if _row.get("sl") else (_ep * 0.95)
                _tp   = float(_row["tp"]) if _row.get("tp") else (_ep * 1.10)
                _lp   = _open_lp.get(_tk, {})
                _cur  = _lp.get("price", _ep)
                _prv  = _lp.get("prev", _cur)
                _unr  = (_cur - _ep) * _qty
                _unr_pct = (_cur / _ep - 1) * 100 if _ep > 0 else 0
                _tid  = int(_row["id"])
                _today_pnl = (_cur - _prv) * _qty

                # Status
                if _tp and _cur >= _tp:     _st_badge, _st_bdr = "🎯 TARGET HIT", "#26a69a"
                elif _sl and _cur <= _sl:   _st_badge, _st_bdr = "🚨 STOP BREACHED", "#ef5350"
                elif _unr >= 0:             _st_badge, _st_bdr = "🟢 In Profit", "#26a69a"
                else:                       _st_badge, _st_bdr = "🔴 In Loss", "#ef5350"

                _unr_c = "#26a69a" if _unr >= 0 else "#ef5350"
                _td_c  = "#26a69a" if _today_pnl >= 0 else "#ef5350"

                # Progress bar: SL → current → target
                _rng = max(_tp - _sl, 0.01)
                _ep_pct  = min(100, max(0, (_ep  - _sl) / _rng * 100))
                _cur_pct = min(100, max(0, (_cur - _sl) / _rng * 100))
                _bar_c   = "#26a69a" if _cur >= _ep else "#ef5350"
                # Width of colored fill = distance from entry to current
                _fill_left  = min(_ep_pct, _cur_pct)
                _fill_width = abs(_cur_pct - _ep_pct)

                _reason_txt = str(_row.get("reason") or "")

                _pt_card = st.container()
                with _pt_card:
                    st.markdown(
                        f'<div style="background:#0d1f3c;border-left:5px solid {_st_bdr};'
                        f'border-radius:10px;padding:13px 16px;margin-bottom:6px">'
                        # Row 1: name + status + P&L numbers
                        f'<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">'
                        f'<div>'
                        f'<span style="font-size:17px;font-weight:700;color:#fff">{_tk.replace(".NS","")}</span>'
                        f'&nbsp;<span style="font-size:11px;color:{_st_bdr};font-weight:600">{_st_badge}</span>'
                        f'<span style="font-size:11px;color:#888;margin-left:8px">{_qty} shares</span>'
                        f'</div>'
                        f'<div style="text-align:right">'
                        f'<div style="font-size:17px;font-weight:700;color:{_unr_c}">₹{_unr:+,.0f} ({_unr_pct:+.1f}%)</div>'
                        f'<div style="font-size:11px;color:{_td_c}">Today ₹{_today_pnl:+,.0f}</div>'
                        f'</div></div>'
                        # Row 2: Entry → Current bar
                        f'<div style="margin-bottom:6px">'
                        f'<div style="display:flex;justify-content:space-between;font-size:10px;color:#666;margin-bottom:3px">'
                        f'<span>SL ₹{_sl:,.2f}</span>'
                        f'<span>Entry ₹{_ep:,.2f}</span>'
                        f'<span>Now ₹{_cur:,.2f}</span>'
                        f'<span>Target ₹{_tp:,.2f}</span>'
                        f'</div>'
                        f'<div style="width:100%;height:8px;background:#2a3a4c;border-radius:4px;position:relative;overflow:visible">'
                        # Entry marker
                        f'<div style="position:absolute;left:{_ep_pct:.0f}%;top:-3px;width:2px;height:14px;background:#888;border-radius:1px"></div>'
                        # Fill from entry to current
                        f'<div style="position:absolute;left:{_fill_left:.0f}%;width:{_fill_width:.0f}%;height:100%;background:{_bar_c};border-radius:4px;opacity:0.7"></div>'
                        # Current dot
                        f'<div style="position:absolute;left:{_cur_pct:.0f}%;top:-4px;transform:translateX(-50%);width:16px;height:16px;background:{_bar_c};border-radius:50%;border:2px solid #fff"></div>'
                        f'</div></div>'
                        + (f'<div style="font-size:11px;color:#888;margin-top:4px">📝 {_reason_txt[:80]}</div>' if _reason_txt else '')
                        + '</div>',
                        unsafe_allow_html=True,
                    )
                    # Action buttons inline
                    _cb1, _cb2, _cb3, _cb4 = st.columns([2, 2, 2, 1])
                    if _cb1.button(f"❌ Close @ ₹{_cur:,.2f}", key=f"cl_live_{_tid}", use_container_width=True):
                        paper_close_trade(_tid, _cur, "Closed at live price")
                        st.cache_data.clear(); st.rerun()
                    if _cb2.button(f"🔴 Close @ SL ₹{_sl:,.2f}", key=f"cl_sl_{_tid}", use_container_width=True):
                        paper_close_trade(_tid, _sl, "Stop-loss triggered")
                        st.cache_data.clear(); st.rerun()
                    if _cb3.button(f"🎯 Close @ Target ₹{_tp:,.2f}", key=f"cl_tp_{_tid}", use_container_width=True):
                        paper_close_trade(_tid, _tp, "Target reached")
                        st.cache_data.clear(); st.rerun()
                    with _cb4.expander("✏️ Edit"):
                        _ne1, _ne2 = st.columns(2)
                        _nsl = _ne1.number_input("New SL", value=float(_sl), format="%.2f", key=f"esl_{_tid}")
                        _ntp = _ne2.number_input("New TP", value=float(_tp), format="%.2f", key=f"etp_{_tid}")
                        if st.button("Save", key=f"esv_{_tid}"):
                            paper_edit_trade(_tid, sl=_nsl, tp=_ntp)
                            st.cache_data.clear(); st.rerun()

            st.markdown("---")

        # ── CLOSED TRADE HISTORY ───────────────────────────────────────────
        if not all_closed.empty:
            st.subheader("📋 Closed Trade History")
            _cl_disp = all_closed[
                [c for c in ["id","ticker","price","quantity","sl","tp","exit_price",
                              "exit_reason","pnl","pnl_pct","status","timestamp"]
                 if c in all_closed.columns]
            ].copy()
            if "pnl" in _cl_disp.columns:
                _cl_disp["pnl"] = pd.to_numeric(_cl_disp["pnl"], errors="coerce")

            # Colored HTML table for closed trades
            _CTH = "background:#1a2744;padding:7px 11px;font-size:11px;color:#aaa;font-weight:600;border-bottom:2px solid #2a3a5c;text-align:right;white-space:nowrap"
            _CTL = _CTH.replace("text-align:right", "text-align:left")
            _CTD = "padding:7px 11px;font-size:12px;border-bottom:1px solid #1a2744;text-align:right"
            _CTX = _CTD.replace("text-align:right", "text-align:left")
            _ct_html = (
                '<table style="width:100%;border-collapse:collapse;margin-bottom:6px">'
                f'<thead><tr>'
                f'<th style="{_CTL}">Stock</th>'
                f'<th style="{_CTH}">Entry ₹</th>'
                f'<th style="{_CTH}">Qty</th>'
                f'<th style="{_CTH}">SL ₹</th>'
                f'<th style="{_CTH}">TP ₹</th>'
                f'<th style="{_CTH}">Exit ₹</th>'
                f'<th style="{_CTL}">Exit Reason</th>'
                f'<th style="{_CTH}">P&amp;L ₹</th>'
                f'<th style="{_CTH}">P&amp;L %</th>'
                f'<th style="{_CTL}">Date</th>'
                f'</tr></thead><tbody>'
            )
            for _, _cr in _cl_disp.iterrows():
                _c_pnl  = float(_cr.get("pnl", 0) or 0)
                _c_pct  = float(_cr.get("pnl_pct", 0) or 0)
                _c_col  = "#26a69a" if _c_pnl >= 0 else "#ef5350"
                _c_bg   = "rgba(38,166,154,0.06)" if _c_pnl >= 0 else "rgba(239,83,80,0.06)"
                _c_tick = str(_cr.get("ticker", "")).replace(".NS", "")
                _c_ep   = f"₹{float(_cr.get('price', 0)):,.2f}"
                _c_sl   = f"₹{float(_cr.get('sl', 0)):,.2f}" if _cr.get("sl") else "—"
                _c_tp   = f"₹{float(_cr.get('tp', 0)):,.2f}" if _cr.get("tp") else "—"
                _c_xp   = f"₹{float(_cr.get('exit_price', 0)):,.2f}" if _cr.get("exit_price") else "—"
                _c_xr   = str(_cr.get("exit_reason", "") or "")
                _c_dt   = str(_cr.get("timestamp", ""))[:10]
                _ct_html += (
                    f'<tr style="background:{_c_bg}">'
                    f'<td style="{_CTX}"><b>{_c_tick}</b></td>'
                    f'<td style="{_CTD}">{_c_ep}</td>'
                    f'<td style="{_CTD}">{int(_cr.get("quantity", 0))}</td>'
                    f'<td style="{_CTD}">{_c_sl}</td>'
                    f'<td style="{_CTD}">{_c_tp}</td>'
                    f'<td style="{_CTD}"><b>{_c_xp}</b></td>'
                    f'<td style="{_CTX}">{_c_xr}</td>'
                    f'<td style="{_CTD};color:{_c_col};font-weight:700">₹{_c_pnl:+,.0f}</td>'
                    f'<td style="{_CTD};color:{_c_col}">{_c_pct:+.1f}%</td>'
                    f'<td style="{_CTX}">{_c_dt}</td>'
                    f'</tr>'
                )
            _ct_html += '</tbody></table>'
            st.markdown(_ct_html, unsafe_allow_html=True)

            # P&L Bar Chart + Cumulative Equity Curve
            _pnl_plot = all_closed.copy()
            _pnl_plot["pnl"] = pd.to_numeric(_pnl_plot["pnl"], errors="coerce")
            _pnl_plot = _pnl_plot.dropna(subset=["pnl"])
            if not _pnl_plot.empty:
                _chart_tab1, _chart_tab2 = st.tabs(["📊 P&L per Trade", "📈 Equity Curve"])

                with _chart_tab1:
                    _fig_pnl = px.bar(
                        _pnl_plot, x="ticker", y="pnl",
                        color="pnl", color_continuous_scale="RdYlGn",
                        title="Realised P&L per Closed Trade (₹)",
                        labels={"pnl": "P&L (₹)", "ticker": "Stock"},
                    )
                    _fig_pnl.update_layout(template="plotly_dark", height=320,
                                           margin=dict(l=0, r=0, t=40, b=0))
                    st.plotly_chart(_fig_pnl, width="stretch")

                with _chart_tab2:
                    # Cumulative P&L over sequential trades
                    _eq_df = _pnl_plot.reset_index(drop=True)
                    _eq_df["trade_no"]   = range(1, len(_eq_df) + 1)
                    _eq_df["cumulative"] = _eq_df["pnl"].cumsum()
                    _eq_colors = [
                        "#26a69a" if v >= 0 else "#ef5350"
                        for v in _eq_df["cumulative"]
                    ]
                    _fig_eq = go.Figure()
                    _fig_eq.add_trace(go.Scatter(
                        x=_eq_df["trade_no"], y=_eq_df["cumulative"],
                        mode="lines+markers",
                        line=dict(color="#2196F3", width=2.5),
                        marker=dict(color=_eq_colors, size=8, line=dict(width=1, color="#fff")),
                        fill="tozeroy",
                        fillcolor="rgba(33,150,243,0.08)",
                        name="Cumulative P&L",
                        customdata=_eq_df[["ticker", "pnl"]].values,
                        hovertemplate=(
                            "Trade #%{x} — %{customdata[0]}<br>"
                            "This trade: ₹%{customdata[1]:,.0f}<br>"
                            "Cumulative: ₹%{y:,.0f}<extra></extra>"
                        ),
                    ))
                    _fig_eq.add_hline(y=0, line_dash="dot", line_color="rgba(150,150,150,0.5)")
                    _final_pnl = float(_eq_df["cumulative"].iloc[-1])
                    _fig_eq.update_layout(
                        template="plotly_dark", height=320,
                        title=f"Equity Curve — Total P&L ₹{_final_pnl:+,.0f} "
                              f"over {len(_eq_df)} trades",
                        xaxis_title="Trade Number",
                        yaxis_title="Cumulative P&L (₹)",
                        margin=dict(l=0, r=0, t=44, b=0),
                    )
                    st.plotly_chart(_fig_eq, width="stretch")

            # ── Closed Trade Insights (always visible, not behind expander) ────
            st.markdown("#### 📊 Trading Insights")
            _pnl_ins = pd.to_numeric(all_closed.get("pnl", pd.Series()), errors="coerce").dropna()
            _n_ins   = len(_pnl_ins)
            if _n_ins >= 2:
                _wins_ins  = _pnl_ins[_pnl_ins > 0]
                _loss_ins  = _pnl_ins[_pnl_ins < 0]
                _wr_ins    = len(_wins_ins) / _n_ins * 100
                _aw_ins    = float(_wins_ins.mean()) if not _wins_ins.empty else 0
                _al_ins    = float(_loss_ins.mean()) if not _loss_ins.empty else 0
                _pay_ins   = abs(_aw_ins / _al_ins) if _al_ins != 0 else 0
                _exp_ins   = (_wr_ins/100 * _aw_ins) + ((1-_wr_ins/100) * _al_ins)
                _wr_c   = "#26a69a" if _wr_ins >= 50 else "#ef5350"
                _exp_c  = "#26a69a" if _exp_ins >= 0 else "#ef5350"
                _pay_c  = "#26a69a" if _pay_ins >= 1.5 else "#FFC107" if _pay_ins >= 1.0 else "#ef5350"
                st.markdown(
                    f'<div style="display:flex;gap:12px;margin-bottom:12px;flex-wrap:wrap">'
                    f'<div style="flex:1;min-width:120px;background:#0d1f3c;border-radius:8px;padding:12px 14px;border-top:3px solid {_wr_c}">'
                    f'<div style="font-size:10px;color:#888;text-transform:uppercase">Win Rate</div>'
                    f'<div style="font-size:22px;font-weight:700;color:{_wr_c}">{_wr_ins:.0f}%</div>'
                    f'<div style="font-size:11px;color:#888">{len(_wins_ins)}/{_n_ins} trades</div></div>'
                    f'<div style="flex:1;min-width:120px;background:#0d1f3c;border-radius:8px;padding:12px 14px;border-top:3px solid {_pay_c}">'
                    f'<div style="font-size:10px;color:#888;text-transform:uppercase">Payoff Ratio</div>'
                    f'<div style="font-size:22px;font-weight:700;color:{_pay_c}">{_pay_ins:.2f}:1</div>'
                    f'<div style="font-size:11px;color:#888">avg win / avg loss</div></div>'
                    f'<div style="flex:1;min-width:140px;background:#0d1f3c;border-radius:8px;padding:12px 14px;border-top:3px solid {_exp_c}">'
                    f'<div style="font-size:10px;color:#888;text-transform:uppercase">Expectancy</div>'
                    f'<div style="font-size:22px;font-weight:700;color:{_exp_c}">₹{_exp_ins:,.0f}</div>'
                    f'<div style="font-size:11px;color:#888">avg ₹ per trade</div></div>'
                    f'<div style="flex:1;min-width:120px;background:#0d1f3c;border-radius:8px;padding:12px 14px;border-top:3px solid #2196F3">'
                    f'<div style="font-size:10px;color:#888;text-transform:uppercase">Avg Win</div>'
                    f'<div style="font-size:22px;font-weight:700;color:#26a69a">₹{_aw_ins:,.0f}</div>'
                    f'<div style="font-size:11px;color:#888">avg loss ₹{abs(_al_ins):,.0f}</div></div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
                # What setup types worked?
                if "reason" in all_closed.columns:
                    _cl_copy = all_closed.copy()
                    _cl_copy["pnl"] = pd.to_numeric(_cl_copy["pnl"], errors="coerce")
                    _cl_copy["win"] = _cl_copy["pnl"] > 0
                    # Truncate reason to setup label (first 30 chars)
                    _cl_copy["setup"] = _cl_copy["reason"].fillna("Manual").str[:35]
                    _setup_g = _cl_copy.groupby("setup").agg(
                        trades=("pnl","count"), total_pnl=("pnl","sum"),
                        win_rate=("win","mean")
                    ).round(0).sort_values("total_pnl", ascending=False).head(5)
                    if len(_setup_g) > 1:
                        st.caption("**Top setups by total P&L:**")
                        for _sn, _sr in _setup_g.iterrows():
                            _s_c = "#26a69a" if _sr["total_pnl"] >= 0 else "#ef5350"
                            st.markdown(
                                f'<div style="display:flex;justify-content:space-between;'
                                f'padding:4px 0;border-bottom:1px solid #1a2744;font-size:12px">'
                                f'<span style="color:#ccc">{_sn}</span>'
                                f'<span><span style="color:{_s_c};font-weight:700">₹{_sr["total_pnl"]:+,.0f}</span>'
                                f'&nbsp;<span style="color:#888">{int(_sr["trades"])} trades · {_sr["win_rate"]*100:.0f}% WR</span></span>'
                                f'</div>',
                                unsafe_allow_html=True,
                            )
            else:
                st.caption("Close at least 2 trades to see performance insights.")

            # ── Performance Stats ──────────────────────────────────────────
            with st.expander("📈 Detailed Statistics", expanded=False):
                _pnl_s = pd.to_numeric(all_closed["pnl"], errors="coerce").dropna()
                _n     = len(_pnl_s)
                _wins  = _pnl_s[_pnl_s > 0]
                _loss  = _pnl_s[_pnl_s < 0]
                _wr    = len(_wins) / _n * 100 if _n else 0
                _aw    = float(_wins.mean()) if not _wins.empty else 0.0
                _al    = float(_loss.mean()) if not _loss.empty else 0.0
                _pay   = abs(_aw / _al) if _al != 0 else 0
                _exp   = (_wr/100 * _aw) + ((1-_wr/100) * _al) if _n else 0

                _st1, _st2, _st3, _st4, _st5 = st.columns(5)
                _st1.metric("Win Rate",      f"{_wr:.1f}%",
                            "Good (>50%)" if _wr > 50 else "Needs work")
                _st2.metric("Avg Win",       f"₹{_aw:,.0f}")
                _st3.metric("Avg Loss",      f"₹{_al:,.0f}")
                _st4.metric("Payoff Ratio",  f"{_pay:.2f}:1",
                            "Good (>1.5)" if _pay > 1.5 else "Needs work")
                _st5.metric("Expectancy",    f"₹{_exp:,.0f}/trade",
                            "Positive edge ✓" if _exp > 0 else "Negative edge ✗",
                            delta_color="normal" if _exp >= 0 else "inverse")

                st.markdown("---")
                st.markdown(
                    "**What these numbers mean:**  \n"
                    "- **Win Rate**: % of trades that closed profitably. Aim for >45%.  \n"
                    "- **Payoff Ratio**: Avg profit on winners ÷ avg loss on losers. Aim for >1.5  \n"
                    "- **Expectancy**: Average ₹ earned per trade across all trades. Must be positive for a viable strategy."
                )

        # ── CSV export ─────────────────────────────────────────────────────
        st.markdown("---")
        if not trades.empty:
            _export_bytes = trades.to_csv(index=False).encode()
            _safe_acc = st.session_state.get("pt_account", "MyAccount").replace(" ", "_")
            st.download_button(
                f"📥 Download Trade Journal — {st.session_state.get('pt_account','My Account')} (CSV)",
                data=_export_bytes,
                file_name=f"paper_trades_{_safe_acc}.csv",
                mime="text/csv",
            )


# ═══════════════════════════════════════════════════════════════════════════════
# PAGE 6 — BACKTEST
# ═══════════════════════════════════════════════════════════════════════════════
elif page == "🧪 Backtest":
    st.title("🧪 Backtest Results")
    st.caption("Historical strategy performance — how would these signals have done in the past?")

    def load_backtest_csv(path: str = "portfolio_results.csv") -> pd.DataFrame:
        if os.path.exists(path):
            return pd.read_csv(path, index_col=0)
        return pd.DataFrame()

    df = load_backtest_csv()

    if df.empty:
        st.info(
            "No backtest results found.  \n\n"
            "Run:  `python main.py --mode backtest --portfolio --index nifty50`  \n"
            "Results will appear here automatically."
        )
    else:
        r_col = next((c for c in ["Return (%)", "Return(%)"] if c in df.columns), None)
        s_col = next((c for c in ["Sharpe", "Sharpe Ratio"] if c in df.columns), None)
        t_col = next((c for c in ["# Trades", "Trades"] if c in df.columns), None)

        bt1, bt2, bt3, bt4 = st.columns(4)
        bt1.metric("Tickers Tested", len(df))
        bt2.metric("Avg Return",   f"{df[r_col].mean():.2f}%" if r_col else "—")
        bt3.metric("Avg Sharpe",   f"{df[s_col].mean():.2f}" if s_col else "—")
        bt4.metric("Total Trades", f"{df[t_col].sum():,.0f}" if t_col else "—")

        grad_cols = [r_col] if r_col else []
        st.dataframe(
            df.style.background_gradient(subset=grad_cols, cmap="RdYlGn").format("{:.2f}"),
            width="stretch",
        )

        if r_col:
            fig = px.bar(
                df.reset_index(), x=df.index, y=r_col,
                color=r_col, color_continuous_scale="RdYlGn",
                title=f"Return (%) per Ticker",
                labels={r_col: "Return (%)"},
            )
            fig.update_layout(template="plotly_dark", height=400,
                              margin=dict(l=0, r=0, t=40, b=0))
            st.plotly_chart(fig, width="stretch")

    # ── In-app backtest runner (Nifty 50 → 500) ────────────────────────────────
    st.markdown("---")
    st.subheader("⚡ Run a Backtest — in the app")

    _bt_c1, _bt_c2, _bt_c3, _bt_c4 = st.columns([2, 2, 1, 1])
    with _bt_c1:
        _bt_uni = st.selectbox("Universe", ["Nifty 50", "Nifty 100", "Nifty 200", "Nifty 500"],
                               key="bt_uni")
    with _bt_c2:
        _bt_strat = st.selectbox("Strategy", ["RSI + MACD", "Momentum"], key="bt_strat")
    with _bt_c3:
        _bt_period = st.selectbox("Period", ["2y", "3y"], index=0, key="bt_period",
                                  help="Needs 2y+ so all indicators have enough warmup history.")
    with _bt_c4:
        st.write("")
        _bt_run = st.button("🚀 Run", type="primary", key="bt_run", use_container_width=True)

    _uni_map = {"Nifty 50": "nifty50", "Nifty 100": "nifty100",
                "Nifty 200": "nifty200", "Nifty 500": "nifty500"}
    _est = {"Nifty 50": "~1-2 min", "Nifty 100": "~3-4 min",
            "Nifty 200": "~6-8 min", "Nifty 500": "~10-15 min"}[_bt_uni]
    st.caption(f"⏱️ Estimated run time: **{_est}**. Larger universes are slower — "
               "the page stays busy while it runs. Results are cached for this session.")

    if _bt_run:
        try:
            from data.universe import get_universe
            from data.fetcher import fetch_single as _bt_fs
            from utils.indicators import add_all_indicators as _bt_ind
            from backtesting import Backtest as _BT
            from strategies.rsi_macd import RSIMACDStrategy
            from strategies.momentum import MomentumStrategy
            try:
                from backtest.runner import TOTAL_COST as _BT_COST
            except Exception:
                _BT_COST = 0.0023

            _strat_cls = RSIMACDStrategy if _bt_strat.startswith("RSI") else MomentumStrategy
            _bt_tickers = get_universe(_uni_map[_bt_uni])
            _bt_rows = []
            _bt_prog = st.progress(0, text="Backtesting…")
            for _bi, _bt_t in enumerate(_bt_tickers):
                try:
                    _bd = _bt_fs(_bt_t, period=_bt_period)
                    _bd = _bt_ind(_bd)
                    _bd = _bd.dropna(axis=1, how="all")   # drop all-NaN cols (e.g. Supertrend)
                    _bd.dropna(inplace=True)               # then drop warmup rows
                    if len(_bd) >= 60:
                        _stats = _BT(_bd, _strat_cls, cash=1_000_000,
                                     commission=_BT_COST, exclusive_orders=True).run()
                        _bt_rows.append({
                            "Ticker":          _bt_t.replace(".NS", ""),
                            "Return (%)":      round(float(_stats["Return [%]"]), 2),
                            "Buy & Hold (%)":  round(float(_stats["Buy & Hold Return [%]"]), 2),
                            "Sharpe":          round(float(_stats["Sharpe Ratio"]), 2),
                            "Max Drawdown (%)":round(float(_stats["Max. Drawdown [%]"]), 2),
                            "Win Rate (%)":    round(float(_stats["Win Rate [%]"]), 2),
                            "# Trades":        int(_stats["# Trades"]),
                        })
                except Exception:
                    pass
                _bt_prog.progress((_bi + 1) / max(len(_bt_tickers), 1),
                                  text=f"Backtesting {_bt_t.replace('.NS','')} ({_bi+1}/{len(_bt_tickers)})")
            _bt_prog.empty()
            if _bt_rows:
                _bt_res = pd.DataFrame(_bt_rows).set_index("Ticker")
                st.session_state["bt_result"] = _bt_res
                st.session_state["bt_result_label"] = f"{_bt_strat} · {_bt_uni} · {_bt_period}"
                try:
                    _bt_res.to_csv("backtest_results.csv")
                except Exception:
                    pass
                st.success(f"✅ Backtested {len(_bt_res)} stocks ({_bt_strat} · {_bt_uni}).")
            else:
                st.warning("No results — data may be unavailable. Try again.")
        except Exception as _bt_err:
            st.error(f"Backtest failed: {_bt_err}")

    # ── Show last in-app backtest result ───────────────────────────────────────
    if "bt_result" in st.session_state:
        _bt_res = st.session_state["bt_result"]
        st.markdown(f"#### 📊 Results — {st.session_state.get('bt_result_label','')}")
        _rb1, _rb2, _rb3, _rb4 = st.columns(4)
        _rb1.metric("Stocks", len(_bt_res))
        _rb2.metric("Avg Return", f"{_bt_res['Return (%)'].mean():.1f}%",
                    delta_color="normal" if _bt_res['Return (%)'].mean() >= 0 else "inverse")
        _rb3.metric("Avg Sharpe", f"{_bt_res['Sharpe'].mean():.2f}")
        _rb4.metric("Beat Buy&Hold",
                    f"{(_bt_res['Return (%)'] > _bt_res['Buy & Hold (%)']).sum()}/{len(_bt_res)}")
        _bt_sorted = _bt_res.sort_values("Return (%)", ascending=False)
        st.dataframe(
            _bt_sorted.style.background_gradient(subset=["Return (%)", "Sharpe"], cmap="RdYlGn"),
            use_container_width=True, height=380,
        )
        st.caption("Sorted by return. Green = better. 'Beat Buy&Hold' = how often the strategy "
                   "outperformed simply holding the stock.")

    st.subheader("🔍 Quick Chart Comparison")
    raw2 = st.text_input(
        "Compare tickers (space-separated)",
        value="RELIANCE.NS TCS.NS HDFCBANK.NS",
        key="backtest_tickers",
    )
    _comp_ui = st.radio("Period", ["1M", "6M", "YTD", "1Y", "Max"], index=1,
                        horizontal=True, key="comp_period")
    comp_period = {"1M":"1m","6M":"6m","YTD":"ytd","1Y":"1y","Max":"max"}[_comp_ui]

    if st.button("📊 Show Normalised Performance", key="compare_btn"):
        tickers_list = [t.strip().upper() for t in raw2.split() if t.strip()]
        if not all(t.endswith(".NS") for t in tickers_list):
            tickers_list = [t if t.endswith(".NS") else t + ".NS" for t in tickers_list]

        fig_comp = go.Figure()
        with st.spinner("Loading price data…"):
            for t in tickers_list:
                try:
                    d = load_ticker_df(t, period=comp_period)
                    norm = d["Close"] / d["Close"].iloc[0] * 100
                    fig_comp.add_trace(go.Scatter(
                        x=d.index, y=norm, name=t.replace(".NS", ""),
                        line=dict(width=2),
                    ))
                except Exception:
                    pass
        if fig_comp.data:
            fig_comp.add_hline(y=100, line_dash="dot", line_color="gray")
            fig_comp.update_layout(
                title="Normalised Price Performance (Base = 100)",
                template="plotly_dark", height=400, yaxis_title="% of Start Price",
                margin=dict(l=0, r=0, t=40, b=0),
            )
            st.plotly_chart(fig_comp, width="stretch")


# ═══════════════════════════════════════════════════════════════════════════════
# PAGE 7 — MACRO DASHBOARD  [NEW]  (commodity-currency-correlations skill)
# ═══════════════════════════════════════════════════════════════════════════════
elif page == "🌍 Macro Dashboard":
    st.title("🌍 Macro Dashboard — Commodities, Currencies & Indices")
    st.caption(
        "Key rules: Crude ↑ → INR weakens (India imports 85%)  |  "
        "DXY ↑ → FII outflows from India  |  "
        "Gold ↑ → Risk-off globally  |  "
        "USD/INR ↑ → IT exporters benefit"
    )

    if st.button("🔄 Refresh Macro Data", type="primary"):
        st.cache_data.clear()

    with st.spinner("Fetching 7 macro instruments…"):
        try:
            macro_df = load_macro_data()
            if macro_df.empty:
                st.warning("Could not fetch macro data. Check internet connection.")
            else:
                # Metric cards
                st.subheader("Current Levels & Daily Change")
                card_cols = st.columns(min(len(macro_df.columns), 7))
                for i, col_name in enumerate(macro_df.columns):
                    series = macro_df[col_name].dropna()
                    if len(series) >= 2:
                        curr_v = float(series.iloc[-1])
                        prev_v = float(series.iloc[-2])
                        chg_v  = (curr_v / max(prev_v, 0.0001) - 1) * 100
                        fmt_v  = f"{curr_v:,.0f}" if curr_v > 500 else f"{curr_v:.2f}"
                        card_cols[i % 7].metric(col_name, fmt_v, f"{chg_v:+.2f}%")

                st.markdown("---")

                # Normalised 3-month performance
                st.subheader("3-Month Performance (Normalised to 100)")
                first_valid = macro_df.apply(
                    lambda s: s.dropna().iloc[0] if not s.dropna().empty else 1
                )
                norm_df = macro_df.div(first_valid) * 100
                _colors = ["#4CAF50","#2196F3","#FF6B6B","#FFD700","#FF8C00","#9C27B0","#00BCD4"]
                fig_norm = go.Figure()
                for i, col in enumerate(norm_df.columns):
                    fig_norm.add_trace(go.Scatter(
                        x=norm_df.index, y=norm_df[col], name=col,
                        line=dict(color=_colors[i % len(_colors)], width=2),
                    ))
                fig_norm.add_hline(y=100, line_dash="dot", line_color="white", opacity=0.3)
                fig_norm.update_layout(
                    template="plotly_dark", height=380,
                    yaxis_title="Indexed (start = 100)",
                    legend=dict(orientation="h", y=1.02),
                    margin=dict(l=0, r=0, t=40, b=0),
                )
                st.plotly_chart(fig_norm, width="stretch")

                st.markdown("---")

                # 30-day return correlation heatmap
                st.subheader("30-Day Return Correlation Matrix")
                rets_30  = macro_df.pct_change().tail(30)
                corr_m   = rets_30.corr().round(2)
                fig_corr = px.imshow(
                    corr_m, text_auto=True, aspect="auto",
                    color_continuous_scale="RdBu_r", zmin=-1, zmax=1,
                    title="30-Day Daily Return Correlation",
                )
                fig_corr.update_layout(
                    template="plotly_dark", height=420,
                    margin=dict(l=0, r=0, t=40, b=0),
                )
                st.plotly_chart(fig_corr, width="stretch")

                st.markdown("---")

                # India impact table
                st.subheader("India Market Impact Guide")
                st.dataframe(pd.DataFrame([
                    {"Move": "Brent Crude ↑", "Sector Impact": "Aviation/Paint/Tyre/FMCG ↓",
                     "INR Effect": "INR weakens (imports 85%)", "Nifty Bias": "🔴 Bearish"},
                    {"Move": "Gold ↑",        "Sector Impact": "Jewellery mixed; gold ETFs ↑",
                     "INR Effect": "USD/INR rises if risk-off", "Nifty Bias": "🟡 Risk-off"},
                    {"Move": "DXY ↑",         "Sector Impact": "FII outflows from all EM",
                     "INR Effect": "INR weakens",              "Nifty Bias": "🔴 Bearish"},
                    {"Move": "DXY ↓",         "Sector Impact": "FII inflows to EM",
                     "INR Effect": "INR strengthens",          "Nifty Bias": "🟢 Bullish"},
                    {"Move": "USD/INR ↑",     "Sector Impact": "IT exporters (TCS/Infy/HCL) ↑; Auto ↓",
                     "INR Effect": "Higher import bill",       "Nifty Bias": "🟡 Mixed"},
                    {"Move": "USD/INR ↓",     "Sector Impact": "IT exporters ↓; Importers ↑",
                     "INR Effect": "Lower import costs",       "Nifty Bias": "🟡 Mixed"},
                ]), hide_index=True)

        except Exception as e:
            st.error(f"Macro data error: {e}")


# ═══════════════════════════════════════════════════════════════════════════════
# PAGE 8 — MARKET BREADTH  [NEW]  (market-breadth skill)
# ═══════════════════════════════════════════════════════════════════════════════
elif page == "📈 Market Breadth":
    st.title("📈 Market Breadth — Nifty 50 Internal Health")
    st.caption(
        "Breadth confirms price trends. "
        "Price up + breadth expanding = sustainable rally. "
        "Price up + breadth shrinking = narrow / fragile move."
    )

    if st.button("🔄 Refresh Breadth Data", type="primary"):
        st.cache_data.clear()

    st.info("⏱️ Scanning all 50 Nifty stocks takes ~3 minutes. Results are cached for 15 minutes.")
    run_breadth = st.button("🔍 Compute Breadth Now", type="primary", key="breadth_btn")

    if run_breadth:
        with st.spinner("Scanning Nifty 50 breadth (~3 min)…"):
            breadth = compute_market_breadth(_NIFTY50_TICKERS)

        st.markdown("---")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Advancing",           breadth["advance"])
        c2.metric("Declining",           breadth["decline"])
        c3.metric("A/D Ratio",           f"{breadth['ad_ratio']:.2f}",
                  help="> 1.5 = strong; < 0.7 = weak")
        c4.metric("Near 52W High / Low", f"{breadth['near_52w_high']} / {breadth['near_52w_low']}")

        # % above key MAs bar chart
        st.markdown("---")
        st.subheader("% of Nifty 50 Stocks Above Key Moving Averages")
        bvals = {
            "Above SMA20":  breadth["pct_above_20"],
            "Above SMA50":  breadth["pct_above_50"],
            "Above SMA200": breadth["pct_above_200"],
        }
        bar_fig = go.Figure()
        for label, val in bvals.items():
            bclr = "#4CAF50" if val > 60 else ("#FF9800" if val > 40 else "#F44336")
            bar_fig.add_trace(go.Bar(
                x=[label], y=[val], name=label,
                marker_color=bclr,
                text=[f"{val:.0f}%"], textposition="auto",
            ))
        bar_fig.add_hline(y=70, line_dash="dot", line_color="#4CAF50",
                          annotation_text="Strong (70%)", annotation_position="right")
        bar_fig.add_hline(y=40, line_dash="dot", line_color="#F44336",
                          annotation_text="Weak (40%)", annotation_position="right")
        bar_fig.update_layout(
            template="plotly_dark", height=340,
            yaxis_title="% of stocks", yaxis_range=[0, 100],
            showlegend=False,
            margin=dict(l=0, r=0, t=20, b=0),
        )
        st.plotly_chart(bar_fig, width="stretch")

        # Signal interpretation
        pct200 = breadth["pct_above_200"]
        if pct200 >= 70:
            sig_txt, sig_clr = "🟢 **Strong Bull Market breadth** — Majority above SMA200. Buy dips with confidence.", "#4CAF50"
        elif pct200 >= 50:
            sig_txt, sig_clr = "🟡 **Moderate breadth** — More than half in uptrend. Stock-selective long approach.", "#FF9800"
        elif pct200 >= 30:
            sig_txt, sig_clr = "🟠 **Weakening breadth** — Over half below SMA200. Reduce position sizes.", "#FF5722"
        else:
            sig_txt, sig_clr = "🔴 **Bear market breadth** — Most below SMA200. Defensive posture; consider hedges.", "#F44336"
        st.markdown(
            f'<div style="background:{sig_clr}22;padding:12px;border-radius:8px;'
            f'border-left:4px solid {sig_clr};font-size:15px;margin:10px 0">'
            f'{sig_txt}</div>', unsafe_allow_html=True
        )

        # A/D pie + reference table side by side
        st.markdown("---")
        col_pie, col_tbl = st.columns([1, 1])
        with col_pie:
            st.subheader("Today's Advance / Decline")
            pie_fig = go.Figure(data=go.Pie(
                labels=["Advancing", "Declining"],
                values=[breadth["advance"], breadth["decline"]],
                marker_colors=["#4CAF50", "#F44336"], hole=0.4,
            ))
            pie_fig.update_layout(
                template="plotly_dark", height=260,
                margin=dict(l=0, r=0, t=20, b=0),
            )
            st.plotly_chart(pie_fig, width="stretch")
        with col_tbl:
            st.subheader("Breadth Interpretation Guide")
            st.dataframe(pd.DataFrame([
                {"% Above SMA200": "> 70%",  "Signal": "Strong Bull",    "Action": "Full long — buy dips"},
                {"% Above SMA200": "50–70%", "Signal": "Healthy uptrend","Action": "Long bias, trail stops"},
                {"% Above SMA200": "30–50%", "Signal": "Sector chop",    "Action": "Stock-selective only"},
                {"% Above SMA200": "< 30%",  "Signal": "Bear market",    "Action": "Reduce exposure, hedge"},
            ]), hide_index=True)

        # 52W high / low bars
        st.markdown("---")
        st.subheader("52-Week High / Low Distribution")
        hl_fig = go.Figure(go.Bar(
            x=["Near 52W High (within 5%)", "Near 52W Low (within 5%)"],
            y=[breadth["near_52w_high"], breadth["near_52w_low"]],
            marker_color=["#4CAF50", "#F44336"],
            text=[breadth["near_52w_high"], breadth["near_52w_low"]],
            textposition="auto",
        ))
        hl_fig.update_layout(
            template="plotly_dark", height=260,
            yaxis_title="Number of Nifty 50 stocks",
            margin=dict(l=0, r=0, t=20, b=0),
        )
        st.plotly_chart(hl_fig, width="stretch")


# ═══════════════════════════════════════════════════════════════════════════════
# PAGE 9 — OI & OPTIONS SETUP  [NEW]  (oi-pcr-analysis + options-fno skills)
# ═══════════════════════════════════════════════════════════════════════════════
elif page == "🏦 OI & Options Setup":
    st.title("🏦 OI & Options Setup")
    st.caption(
        "IV regime (VIX-based) + directional bias → right strategy.  "
        "Max Pain calculator + PCR zone reference for expiry planning."
    )

    tab1, tab2, tab3 = st.tabs([
        "📊 Strategy Selector",
        "🔢 Max Pain Calculator",
        "📈 PCR Zone Reference",
    ])

    # ── TAB 1: Strategy Selector ───────────────────────────────────────────────
    with tab1:
        st.subheader("Options Strategy Selector")
        c1, c2 = st.columns(2)
        with c1:
            direction = st.selectbox(
                "Your Directional Bias",
                ["Strongly Bullish", "Mildly Bullish", "Neutral / Range-bound",
                 "Mildly Bearish", "Strongly Bearish"],
                key="opts_dir",
            )
        with c2:
            curr_vix_opt = st.number_input(
                "India VIX (current)", min_value=5.0, max_value=80.0,
                value=float(vix_val) if vix_val else 18.0, step=0.5, key="opts_vix",
            )

        ivr_proxy = min(100, max(0, (curr_vix_opt - 10) / (35 - 10) * 100))
        iv_regime = "Low" if ivr_proxy < 40 else ("Normal" if ivr_proxy < 65 else "High")

        _smap = {
            ("Strongly Bullish",      "Low"):    ("Long Call (ATM)",        "Buy 1 ATM CE, 20–45 DTE",                  "Low IVR = cheap premium — buy directional"),
            ("Strongly Bullish",      "Normal"): ("Bull Call Spread",       "Buy ATM CE + Sell OTM CE (1–2 strikes above)", "Spread cuts cost at normal IV"),
            ("Strongly Bullish",      "High"):   ("Bull Call Spread",       "Buy ATM CE + Sell OTM CE",                  "High IVR: spread essential — naked buy overpriced"),
            ("Mildly Bullish",        "Low"):    ("Bull Call Spread",       "Buy ATM CE + Sell OTM CE",                  "Defined risk for moderate bullish view"),
            ("Mildly Bullish",        "Normal"): ("Bull Call Spread",       "Buy ATM CE + Sell OTM CE",                  "Balanced IV — spread preferred"),
            ("Mildly Bullish",        "High"):   ("Cash-Secured Put (CSP)", "Sell OTM PE at key support strike",         "Collect rich premium; happy to own stock lower"),
            ("Neutral / Range-bound", "Low"):    ("Long Straddle",          "Buy ATM CE + ATM PE, same expiry",          "Expect big move but unsure of direction (event play)"),
            ("Neutral / Range-bound", "Normal"): ("Iron Condor",            "Sell OTM CE+PE + buy further OTM wings",    "Range-bound + normal IV = classic condor setup"),
            ("Neutral / Range-bound", "High"):   ("Iron Condor",            "Sell OTM CE+PE + buy further OTM wings",    "High IVR: sell rich premium in sideways market"),
            ("Mildly Bearish",        "Low"):    ("Bear Put Spread",        "Buy ATM PE + Sell OTM PE",                  "Defined-risk bearish at low IV"),
            ("Mildly Bearish",        "Normal"): ("Bear Put Spread",        "Buy ATM PE + Sell OTM PE",                  "Spread reduces debit"),
            ("Mildly Bearish",        "High"):   ("Bear Put Spread",        "Buy ATM PE + Sell deeper OTM PE",           "High IV: spread essential — naked put costly"),
            ("Strongly Bearish",      "Low"):    ("Long Put (ATM)",         "Buy 1 ATM PE, 20–45 DTE",                  "Strong conviction + cheap premium"),
            ("Strongly Bearish",      "Normal"): ("Bear Put Spread",        "Buy ATM PE + Sell OTM PE",                  "Spread for cost management"),
            ("Strongly Bearish",      "High"):   ("Bear Put Spread",        "Buy ATM PE + Sell OTM PE",                  "High IV: never buy naked options — use spreads"),
        }
        strat, setup, reason = _smap.get(
            (direction, iv_regime),
            ("Review setup", "Use defined-risk spreads", "Unclear IV regime"),
        )

        vbc = "#4CAF50" if curr_vix_opt < 16 else ("#FF9800" if curr_vix_opt < 25 else "#F44336")
        st.markdown(
            f'<div style="background:#1a1a2e;padding:18px;border-radius:10px;'
            f'border-left:5px solid {vbc};margin:12px 0">'
            f'<h3 style="margin:0;color:#fff">Recommended: {strat}</h3>'
            f'<p style="margin:6px 0;color:#ccc"><b>Setup:</b> {setup}</p>'
            f'<p style="margin:6px 0;color:#aaa"><b>Why:</b> {reason}</p>'
            f'<hr style="border-color:#333;margin:10px 0">'
            f'VIX: <b style="color:#fff">{curr_vix_opt:.1f}</b>  |  '
            f'IV Rank (proxy): <b style="color:#fff">{ivr_proxy:.0f}%</b>  |  '
            f'Regime: <b style="color:{vbc}">{iv_regime} IV</b>'
            f'</div>', unsafe_allow_html=True
        )

        st.markdown("---")
        st.subheader("Greeks Quick Reference")
        st.dataframe(pd.DataFrame([
            {"Greek": "Delta (Δ)", "Measures": "₹ change per ₹1 underlying move",   "Rule of Thumb": "ATM ≈ 0.50. OTM 2 strikes ≈ 0.30"},
            {"Greek": "Gamma (Γ)", "Measures": "Rate delta changes",                 "Rule of Thumb": "Highest near ATM + near expiry — P&L swings fast"},
            {"Greek": "Theta (Θ)", "Measures": "Daily time decay (₹)",              "Rule of Thumb": "ATM 30 DTE: ~0.3–0.5%/day. 7 DTE: ~1.5–2%/day"},
            {"Greek": "Vega (V)",  "Measures": "P&L change per 1% IV move",         "Rule of Thumb": "Long options lose value if IV collapses post-event"},
        ]), hide_index=True)

        st.markdown("---")
        st.subheader("NSE Lot Sizes *(verify quarterly)*")
        st.dataframe(pd.DataFrame([
            {"Contract": "Nifty 50",  "Lot Size": 75,  "Approx Margin": "₹1.0–1.5L"},
            {"Contract": "BankNifty", "Lot Size": 30,  "Approx Margin": "₹0.8–1.2L"},
            {"Contract": "FinNifty",  "Lot Size": 65,  "Approx Margin": "₹0.5–0.8L"},
            {"Contract": "RELIANCE",  "Lot Size": 250, "Approx Margin": "₹3–4L"},
            {"Contract": "HDFC Bank", "Lot Size": 550, "Approx Margin": "₹6–8L"},
            {"Contract": "TCS",       "Lot Size": 175, "Approx Margin": "₹6–8L"},
            {"Contract": "Infosys",   "Lot Size": 400, "Approx Margin": "₹5–6L"},
        ]), hide_index=True)

    # ── TAB 2: Max Pain Calculator ─────────────────────────────────────────────
    with tab2:
        st.subheader("Max Pain Calculator")
        st.caption(
            "Max Pain = strike where option buyers lose the most (writers profit most).  "
            "Price gravitates toward Max Pain near expiry — strongest in the last hour."
        )

        strikes_inp = st.text_area("Strike prices (comma-separated)",
                                    "24000,24100,24200,24300,24400,24500,24600", height=60)
        calls_inp   = st.text_area("Call OI at each strike (lots, comma-separated)",
                                    "45000,75000,120000,95000,65000,42000,30000", height=60)
        puts_inp    = st.text_area("Put OI at each strike (lots, comma-separated)",
                                    "35000,55000,100000,88000,58000,40000,22000", height=60)

        if st.button("🎯 Calculate Max Pain", type="primary", key="maxpain_btn"):
            try:
                sl = [float(x.strip()) for x in strikes_inp.split(",") if x.strip()]
                cl = [float(x.strip()) for x in calls_inp.split(",")   if x.strip()]
                pl = [float(x.strip()) for x in puts_inp.split(",")    if x.strip()]

                if len(sl) == len(cl) == len(pl) >= 2:
                    oi_df = pd.DataFrame({"strike": sl, "call_oi": cl, "put_oi": pl})
                    pain_vals = []
                    for k in oi_df["strike"]:
                        cp = ((oi_df["strike"] - k).clip(lower=0) * oi_df["call_oi"]).sum()
                        pp = ((k - oi_df["strike"]).clip(lower=0) * oi_df["put_oi"]).sum()
                        pain_vals.append(cp + pp)
                    oi_df["total_pain"] = pain_vals
                    mp = float(oi_df.loc[oi_df["total_pain"].idxmin(), "strike"])

                    st.success(f"🎯 **Max Pain Strike: {mp:,.0f}**")

                    mp_fig = go.Figure()
                    mp_fig.add_trace(go.Bar(x=oi_df["strike"].astype(str), y=oi_df["call_oi"],
                                            name="Call OI", marker_color="#ef5350"))
                    mp_fig.add_trace(go.Bar(x=oi_df["strike"].astype(str), y=oi_df["put_oi"],
                                            name="Put OI", marker_color="#26a69a"))
                    mp_fig.add_vline(x=str(int(mp)), line_dash="dash",
                                     line_color="#FFD700", line_width=2,
                                     annotation_text=f"Max Pain: {mp:,.0f}",
                                     annotation_font_color="#FFD700")
                    mp_fig.update_layout(
                        template="plotly_dark", barmode="group", height=340,
                        title="Call vs Put OI by Strike",
                        margin=dict(l=0, r=0, t=40, b=0),
                    )
                    st.plotly_chart(mp_fig, width="stretch")

                    pcr_auto = sum(pl) / max(sum(cl), 1)
                    st.metric("PCR (from your input)", f"{pcr_auto:.2f}",
                              help="Total Put OI / Total Call OI")
                else:
                    st.error("All three lists must have the same length (>= 2 strikes).")
            except Exception as e:
                st.error(f"Calculation error: {e}")

    # ── TAB 3: PCR Zone Reference ──────────────────────────────────────────────
    with tab3:
        st.subheader("Put-Call Ratio (PCR) Zone Reference")
        st.caption("PCR = Total Put OI / Total Call OI. Contrarian indicator — extremes signal reversals.")

        pcr_input = st.slider("Current PCR (OI-based)", 0.3, 2.5, 1.0, 0.05, key="pcr_slider")

        if pcr_input < 0.6:
            pcr_sig, pcr_hex = "🔴 Extreme Complacency — too many call buyers. Contrarian BEARISH. Correction likely.", "#F44336"
        elif pcr_input < 0.8:
            pcr_sig, pcr_hex = "🟡 Mildly Bullish sentiment — neutral with slight upward tilt.", "#FF9800"
        elif pcr_input < 1.2:
            pcr_sig, pcr_hex = "🟢 Healthy range — no extreme reading, normal conditions.", "#4CAF50"
        elif pcr_input < 1.5:
            pcr_sig, pcr_hex = "🟡 Mildly Bearish — fear building. Caution on fresh longs.", "#FF9800"
        else:
            pcr_sig, pcr_hex = "🟢 Extreme Fear — too many put buyers. Contrarian BULLISH. Bounce setup.", "#4CAF50"

        st.markdown(
            f'<div style="background:{pcr_hex}22;padding:14px;border-radius:8px;'
            f'border-left:5px solid {pcr_hex};font-size:16px;margin:10px 0">'
            f'PCR = <b>{pcr_input:.2f}</b> → {pcr_sig}'
            f'</div>', unsafe_allow_html=True
        )

        st.markdown("---")
        st.dataframe(pd.DataFrame([
            {"PCR Value": "< 0.6",    "Sentiment": "Extreme complacency",  "Signal": "🔴 Contrarian bearish"},
            {"PCR Value": "0.6–0.8",  "Sentiment": "Mildly bullish",       "Signal": "🟡 Neutral/bullish tilt"},
            {"PCR Value": "0.8–1.2",  "Sentiment": "Healthy (normal)",     "Signal": "🟢 No extreme"},
            {"PCR Value": "1.2–1.5",  "Sentiment": "Mildly bearish",       "Signal": "🟡 Caution"},
            {"PCR Value": "> 1.5",    "Sentiment": "Extreme fear",         "Signal": "🟢 Contrarian bullish"},
        ]), hide_index=True)

        st.markdown("---")
        st.subheader("OI Price Interpretation Framework")
        st.dataframe(pd.DataFrame([
            {"Price": "↑ Rising", "OI": "↑ Rising",  "Meaning": "Long Buildup — fresh bulls entering",  "Signal": "🟢 Strongly Bullish"},
            {"Price": "↓ Falling","OI": "↑ Rising",  "Meaning": "Short Buildup — fresh bears entering", "Signal": "🔴 Strongly Bearish"},
            {"Price": "↑ Rising", "OI": "↓ Falling", "Meaning": "Short Covering — shorts buying back",  "Signal": "🟡 Bullish but weak"},
            {"Price": "↓ Falling","OI": "↓ Falling", "Meaning": "Long Unwinding — longs exiting",       "Signal": "🟡 Bearish but weak"},
        ]), hide_index=True)
        st.caption(
            "Key: Long Buildup (Price ↑ + OI ↑) is the strongest bullish signal. "
            "Short Covering (Price ↑ + OI ↓) is weaker — shorts exiting, not fresh bulls."
        )


# ═══════════════════════════════════════════════════════════════════════════════
# PAGE 10 — INTRADAY TRADER  [NEW]
# ═══════════════════════════════════════════════════════════════════════════════
elif page == "⚡ Intraday Trader":
    st.title("⚡ Intraday Trader")
    st.markdown(
        "Real-time intraday tools — Gap Scanner, CPR Levels, ORB Setup, "
        "and live Supertrend/VWAP signals on 5m/15m charts.  \n"
        "⚠️ *Data is 15-min delayed via Yahoo Finance free API.*"
    )

    # Determine if Angel One is connected for live positions tab
    try:
        from data.angel_fetcher import is_configured as _it_ao_ok
        _it_ao = _it_ao_ok()
    except Exception:
        _it_ao = False

    _it_tabs = ["📊 Pre-Market Gap Scanner", "📈 Intraday Chart",
                "⚡ ORB Setup", "🎯 Live Intraday Signals"]
    if _it_ao:
        _it_tabs.append("💼 Live Positions")

    _tab_objs = st.tabs(_it_tabs)
    tab_gap   = _tab_objs[0]
    tab_chart = _tab_objs[1]
    tab_orb   = _tab_objs[2]
    tab_sigs  = _tab_objs[3]
    tab_pos   = _tab_objs[4] if _it_ao else None

    # ── TAB 1: GAP SCANNER ────────────────────────────────────────────────────
    with tab_gap:
        st.subheader("📊 Overnight Gap Scanner — Nifty 50")
        st.caption("Shows stocks with opening gap ≥ 0.5%. Run at 9:15 AM for best results.")

        col_gap_thresh, col_gap_btn = st.columns([2, 1])
        with col_gap_thresh:
            _gap_min = st.slider("Minimum gap %", 0.25, 5.0, 0.5, 0.25, key="gap_min_slider")
        with col_gap_btn:
            st.write("")
            st.write("")
            _run_gap = st.button("🔍 Scan Gaps", type="primary", key="run_gap_btn")

        @st.cache_data(ttl=600, show_spinner=False)
        def _cached_gaps(min_pct: float):
            from trading.gap_scanner import get_nifty50_gaps
            return get_nifty50_gaps(min_gap_pct=min_pct)

        if _run_gap or st.session_state.get("gap_scanned"):
            st.session_state["gap_scanned"] = True
            with st.spinner("Scanning Nifty 50 for gaps…"):
                _gap_df = _cached_gaps(_gap_min)

            if _gap_df.empty:
                st.info(f"No stocks with gap ≥ {_gap_min}% today. Market opened flat.")
            else:
                # Summary metrics
                _gup   = _gap_df[_gap_df["gap_pct"] > 0]
                _gdown = _gap_df[_gap_df["gap_pct"] < 0]
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("Total Gapped",    len(_gap_df))
                c2.metric("Gap Ups ↑",       len(_gup),   delta=f"{len(_gup)} stocks")
                c3.metric("Gap Downs ↓",     len(_gdown), delta=f"-{len(_gdown)} stocks",
                          delta_color="inverse")
                c4.metric("Largest Gap",
                          f"{_gap_df['gap_pct'].abs().max():.1f}%",
                          delta=_gap_df.iloc[0]['ticker'])

                # Color-coded table
                _disp = _gap_df[["emoji","ticker","prev_close","today_open",
                                  "gap_pct","change_pct","vol_ratio","category","strategy"]].copy()
                _disp.columns = ["","Ticker","Prev Close","Open","Gap %","Day Chg %",
                                  "Vol Ratio","Category","Intraday Strategy"]

                def _color_gap(val):
                    try:
                        v = float(val)
                        if v >= 1.5:  return "background-color:#1a3a2a; color:#4caf50"
                        if v > 0:     return "background-color:#1a2a1a; color:#a5d6a7"
                        if v <= -1.5: return "background-color:#3a1a1a; color:#ef5350"
                        if v < 0:     return "background-color:#2a1a1a; color:#ef9a9a"
                    except Exception:
                        pass
                    return ""

                styled = _disp.style.map(_color_gap, subset=["Gap %","Day Chg %"])
                st.dataframe(styled, hide_index=True, use_container_width=True, height=400)

                # Gap distribution bar chart
                _gap_chart_df = _gap_df.sort_values("gap_pct")
                fig_gap = go.Figure(go.Bar(
                    x=_gap_chart_df["ticker"].str.replace(".NS","",regex=False),
                    y=_gap_chart_df["gap_pct"],
                    marker_color=[
                        "#4caf50" if g > 0 else "#ef5350"
                        for g in _gap_chart_df["gap_pct"]
                    ],
                    text=_gap_chart_df["gap_pct"].apply(lambda x: f"{x:+.1f}%"),
                    textposition="outside",
                ))
                fig_gap.update_layout(
                    template="plotly_dark", height=320,
                    title="Gap % Distribution — Nifty 50",
                    xaxis_title="Stock", yaxis_title="Gap %",
                    showlegend=False,
                    yaxis=dict(zeroline=True, zerolinecolor="#666", zerolinewidth=2),
                )
                st.plotly_chart(fig_gap, use_container_width=True)
        else:
            st.info("Click **🔍 Scan Gaps** to load today's gap data.")

    # ── TAB 2: INTRADAY CHART ─────────────────────────────────────────────────
    with tab_chart:
        st.subheader("📈 Intraday Chart — CPR + ORB + AVWAP + Supertrend")

        _ic_c1, _ic_c2, _ic_c3 = st.columns([3, 1, 1])
        with _ic_c1:
            _ic_ticker = st.text_input(
                "NSE Ticker", value="RELIANCE",
                placeholder="RELIANCE / HDFCBANK / TCS",
                key="ic_ticker",
            ).strip().upper()
        with _ic_c2:
            _ic_interval = st.selectbox("Interval", ["5m","15m","30m"], key="ic_interval")
        with _ic_c3:
            _ic_days = st.selectbox("Days", [1, 2, 3, 5], index=2, key="ic_days")
            st.write("")
            _ic_load = st.button("📈 Load Chart", type="primary", key="ic_load")

        @st.cache_data(ttl=180, show_spinner=False)
        def _load_intraday_chart(tkr: str, intv: str, days: int):
            from data.fetcher import fetch_intraday
            from utils.indicators import add_all_indicators, add_anchored_vwap
            df = fetch_intraday(tkr, interval=intv, days=days)
            df = add_all_indicators(df)
            df = add_anchored_vwap(df)
            return df

        if _ic_load or st.session_state.get("ic_last") == _ic_ticker:
            st.session_state["ic_last"] = _ic_ticker
            _sym = _ic_ticker if _ic_ticker.endswith(".NS") else _ic_ticker + ".NS"
            try:
                with st.spinner(f"Loading {_ic_interval} chart for {_ic_ticker}…"):
                    _ic_df = _load_intraday_chart(_sym, _ic_interval, _ic_days)

                if _ic_df.empty:
                    st.warning("No intraday data returned. Try a different ticker or interval.")
                else:
                    from trading.intraday_signals import compute_orb
                    _orb = compute_orb(_ic_df, orb_minutes=15)

                    # Get latest CPR values (same for whole day)
                    _cpr_tc  = float(_ic_df["CPR_TC"].iloc[-1])  if "CPR_TC"  in _ic_df.columns else None
                    _cpr_bc  = float(_ic_df["CPR_BC"].iloc[-1])  if "CPR_BC"  in _ic_df.columns else None
                    _pivot   = float(_ic_df["Pivot"].iloc[-1])   if "Pivot"   in _ic_df.columns else None
                    _r1      = float(_ic_df["R1"].iloc[-1])      if "R1"      in _ic_df.columns else None
                    _s1      = float(_ic_df["S1"].iloc[-1])      if "S1"      in _ic_df.columns else None
                    _r2      = float(_ic_df["R2"].iloc[-1])      if "R2"      in _ic_df.columns else None
                    _s2      = float(_ic_df["S2"].iloc[-1])      if "S2"      in _ic_df.columns else None

                    fig_ic = make_subplots(
                        rows=2, cols=1, shared_xaxes=True,
                        vertical_spacing=0.05, row_heights=[0.75, 0.25]
                    )

                    # Candlestick
                    fig_ic.add_trace(go.Candlestick(
                        x=_ic_df.index,
                        open=_ic_df["Open"], high=_ic_df["High"],
                        low=_ic_df["Low"],   close=_ic_df["Close"],
                        name=_ic_ticker, increasing_line_color="#26a69a",
                        decreasing_line_color="#ef5350",
                    ), row=1, col=1)

                    # Anchored VWAP
                    if "AVWAP" in _ic_df.columns:
                        fig_ic.add_trace(go.Scatter(
                            x=_ic_df.index, y=_ic_df["AVWAP"],
                            line=dict(color="#FFD700", width=1.5, dash="solid"),
                            name="AVWAP", opacity=0.9,
                        ), row=1, col=1)
                        if "AVWAP_SD1_Upper" in _ic_df.columns:
                            fig_ic.add_trace(go.Scatter(
                                x=_ic_df.index, y=_ic_df["AVWAP_SD1_Upper"],
                                line=dict(color="rgba(255,165,0,0.5)", width=1, dash="dot"),
                                name="VWAP+1σ", showlegend=False,
                            ), row=1, col=1)
                            fig_ic.add_trace(go.Scatter(
                                x=_ic_df.index, y=_ic_df["AVWAP_SD1_Lower"],
                                line=dict(color="rgba(255,165,0,0.5)", width=1, dash="dot"),
                                name="VWAP−1σ", fill="tonexty",
                                fillcolor="rgba(255,165,0,0.05)", showlegend=False,
                            ), row=1, col=1)

                    # Supertrend
                    if "Supertrend" in _ic_df.columns and "ST_Direction" in _ic_df.columns:
                        _bull_st = _ic_df[_ic_df["ST_Direction"] == 1]
                        _bear_st = _ic_df[_ic_df["ST_Direction"] == -1]
                        if not _bull_st.empty:
                            fig_ic.add_trace(go.Scatter(
                                x=_bull_st.index, y=_bull_st["Supertrend"],
                                mode="markers", marker=dict(size=3, color="#26a69a"),
                                name="ST Bull", showlegend=False,
                            ), row=1, col=1)
                        if not _bear_st.empty:
                            fig_ic.add_trace(go.Scatter(
                                x=_bear_st.index, y=_bear_st["Supertrend"],
                                mode="markers", marker=dict(size=3, color="#ef5350"),
                                name="ST Bear", showlegend=False,
                            ), row=1, col=1)

                    # CPR levels as horizontal lines
                    _level_defs = [
                        (_r2,    "#ff6b6b", "R2", "dash"),
                        (_r1,    "#ff9999", "R1", "dot"),
                        (_cpr_tc,"#64b5f6", "CPR TC", "solid"),
                        (_pivot, "#9e9e9e", "Pivot", "dot"),
                        (_cpr_bc,"#64b5f6", "CPR BC", "solid"),
                        (_s1,    "#81c784", "S1", "dot"),
                        (_s2,    "#4caf50", "S2", "dash"),
                    ]
                    for _lv, _lc, _ln, _ld in _level_defs:
                        if _lv and not pd.isna(_lv):
                            fig_ic.add_hline(
                                y=_lv, line_dash=_ld, line_color=_lc,
                                line_width=1, opacity=0.7,
                                annotation_text=_ln,
                                annotation_position="right",
                                annotation_font_color=_lc,
                                row=1,
                            )

                    # ORB box
                    if not pd.isna(_orb.get("orb_high", float("nan"))):
                        try:
                            import datetime as _dt
                            _first_date = _ic_df.index[0].date()
                            _orb_start  = _ic_df.index[0]
                            _orb_end_t  = _dt.datetime.combine(_first_date, _dt.time(9, 29))
                            _orb_end_t  = _orb_end_t.replace(tzinfo=_orb_start.tzinfo)
                            _orb_end_idx = _ic_df.index[_ic_df.index <= _orb_end_t][-1] if len(_ic_df.index[_ic_df.index <= _orb_end_t]) else _ic_df.index[2]
                        except Exception:
                            _orb_start   = _ic_df.index[0]
                            _orb_end_idx = _ic_df.index[min(3, len(_ic_df)-1)]
                        fig_ic.add_vrect(
                            x0=_orb_start, x1=_orb_end_idx,
                            fillcolor="rgba(255,255,0,0.07)",
                            layer="below", line_width=0,
                            annotation_text="ORB Zone",
                            annotation_position="top left",
                        )
                        fig_ic.add_hline(y=_orb["orb_high"], line_dash="dash",
                                         line_color="#ffeb3b", line_width=1.5,
                                         annotation_text=f"ORB H {_orb['orb_high']:.2f}",
                                         annotation_position="right")
                        fig_ic.add_hline(y=_orb["orb_low"], line_dash="dash",
                                         line_color="#ff9800", line_width=1.5,
                                         annotation_text=f"ORB L {_orb['orb_low']:.2f}",
                                         annotation_position="right")

                    # Volume subplot
                    fig_ic.add_trace(go.Bar(
                        x=_ic_df.index, y=_ic_df["Volume"],
                        name="Volume",
                        marker_color=[
                            "#26a69a" if c >= o else "#ef5350"
                            for c, o in zip(_ic_df["Close"], _ic_df["Open"])
                        ],
                        opacity=0.7,
                    ), row=2, col=1)

                    fig_ic.update_layout(
                        template="plotly_dark", height=680,
                        title=f"{_ic_ticker} — {_ic_interval} Chart | CPR + ORB + AVWAP",
                        xaxis_rangeslider_visible=False,
                        showlegend=True,
                        legend=dict(orientation="h", yanchor="bottom", y=1.02),
                        margin=dict(l=0, r=80, t=60, b=0),
                    )
                    st.plotly_chart(fig_ic, use_container_width=True)

                    # CPR summary cards
                    if _pivot and _cpr_tc and _cpr_bc:
                        _cur_price = float(_ic_df["Close"].iloc[-1])
                        _cpr_zone  = str(_ic_df["Price_vs_CPR"].iloc[-1]) if "Price_vs_CPR" in _ic_df.columns else "unknown"
                        _cpr_bias  = "🟢 Bullish (above CPR)" if _cpr_zone == "above" else ("🔴 Bearish (below CPR)" if _cpr_zone == "below" else "🟡 Inside CPR — wait for breakout")
                        _cpr_w     = float(_ic_df["CPR_Width_Pct"].iloc[-1]) if "CPR_Width_Pct" in _ic_df.columns else 0
                        _day_type  = "Narrow CPR (directional day expected)" if _cpr_w < 0.3 else "Wide CPR (sideways / volatile day)"

                        _cc1, _cc2, _cc3, _cc4, _cc5 = st.columns(5)
                        _cc1.metric("Pivot", f"₹{_pivot:.1f}")
                        _cc2.metric("CPR Top", f"₹{_cpr_tc:.1f}")
                        _cc3.metric("CPR Bottom", f"₹{_cpr_bc:.1f}")
                        _cc4.metric("Price vs CPR", _cpr_bias)
                        _cc5.metric("CPR Width", f"{_cpr_w:.2f}%", delta=_day_type)

                    # ORB summary
                    if not pd.isna(_orb.get("orb_high", float("nan"))):
                        st.markdown("---")
                        _oc1, _oc2, _oc3, _oc4 = st.columns(4)
                        _oc1.metric("ORB High",  f"₹{_orb['orb_high']:.2f}")
                        _oc2.metric("ORB Low",   f"₹{_orb['orb_low']:.2f}")
                        _oc3.metric("ORB Range", f"{_orb['orb_range_pct']:.2f}%",
                                    delta="Narrow" if _orb.get("narrow") else "Normal")
                        _oc4.metric("Open Price", f"₹{_orb.get('open_price',0):.2f}")

            except Exception as _ic_err:
                st.error(f"Could not load intraday data: {_ic_err}")
                st.caption("Yahoo Finance intraday data is limited to recent days and may be unavailable for some tickers.")
        else:
            st.info("Enter a ticker and click **📈 Load Chart** to view intraday data.")

    # ── TAB 3: ORB SETUP ─────────────────────────────────────────────────────
    with tab_orb:
        st.subheader("⚡ Opening Range Breakout (ORB) — How to Trade It")
        st.markdown("""
        **ORB Strategy:** Define the first **15 minutes** of trading (9:15–9:30 AM IST) as the *Opening Range*.
        Trade the breakout when price moves outside this range with strong volume.

        | Setup | Trigger | Stop | Target | Best When |
        |-------|---------|------|--------|-----------|
        | **BUY ORB** | Close above ORB High on 5m/15m candle | Below ORB Low | ORB High + 1.5× range | Gap-up day, strong market |
        | **SHORT ORB** | Close below ORB Low on 5m/15m candle | Above ORB High | ORB Low − 1.5× range | Gap-down day, weak market |

        **Filters that improve win rate:**
        - Volume on breakout bar > 1.5× opening range average
        - India VIX < 22 (not in fear regime)
        - Stock is in same direction as Nifty
        - Narrow CPR (< 0.3% width) = directional day expected
        """)

        st.markdown("---")
        st.subheader("ORB Quick Reference — Nifty 50 Watchlist")
        st.caption("Paste tickers below, click Scan to see today's ORB levels.")

        _orb_tickers_input = st.text_area(
            "Tickers (one per line)",
            value="RELIANCE.NS\nTCS.NS\nHDFCBANK.NS\nINFY.NS\nICICIBANK.NS",
            height=120,
            key="orb_tickers_input",
        )
        _orb_scan_btn = st.button("⚡ Compute ORB Levels", key="orb_scan_btn")

        if _orb_scan_btn:
            _orb_tickers = [t.strip() for t in _orb_tickers_input.split("\n") if t.strip()]
            _orb_rows = []
            _orb_prog = st.progress(0)
            for _oi, _ot in enumerate(_orb_tickers):
                try:
                    from data.fetcher import fetch_intraday
                    from utils.indicators import add_all_indicators, add_anchored_vwap
                    from trading.intraday_signals import compute_orb
                    _sym = _ot if _ot.endswith(".NS") else _ot + ".NS"
                    _idf = fetch_intraday(_sym, interval="5m", days=1)
                    _idf = add_anchored_vwap(_idf)
                    _orb_r = compute_orb(_idf, 15)
                    _cz = str(_idf["Price_vs_CPR"].iloc[-1]) if "Price_vs_CPR" in _idf.columns else "?"
                    _av = round(float(_idf["AVWAP"].iloc[-1]), 2) if "AVWAP" in _idf.columns else None
                    _cp = round(float(_idf["Close"].iloc[-1]), 2)
                    _orb_rows.append({
                        "Ticker":    _ot.replace(".NS",""),
                        "Price":     _cp,
                        "ORB High":  _orb_r.get("orb_high","—"),
                        "ORB Low":   _orb_r.get("orb_low","—"),
                        "Range %":   _orb_r.get("orb_range_pct","—"),
                        "AVWAP":     _av,
                        "CPR Zone":  _cz,
                        "Day Type":  "Narrow⚡" if _orb_r.get("narrow") else "Normal",
                    })
                except Exception as _oe:
                    _orb_rows.append({"Ticker": _ot.replace(".NS",""), "Price":"err", "ORB High":"—",
                                      "ORB Low":"—","Range %":"—","AVWAP":"—","CPR Zone":"—","Day Type":"error"})
                _orb_prog.progress((_oi+1)/len(_orb_tickers))
            _orb_prog.empty()
            if _orb_rows:
                st.dataframe(pd.DataFrame(_orb_rows), hide_index=True, use_container_width=True)

    # ── TAB 4: LIVE INTRADAY SIGNALS ─────────────────────────────────────────
    with tab_sigs:
        st.subheader("🎯 Live Intraday Signals — scan a list (ORB + VWAP + Supertrend)")

        # Data-source indicator — intraday data prefers Angel One (real-time)
        try:
            from data.angel_fetcher import is_configured as _ls_ao_ok
            _ls_ao = _ls_ao_ok()
        except Exception:
            _ls_ao = False
        if _ls_ao:
            st.markdown('<span class="pill-green">⚡ Live data: Angel One (real-time, no rate limits)</span>',
                        unsafe_allow_html=True)
        else:
            st.markdown('<span class="pill-yellow">Angel One not connected — falling back to Yahoo '
                        '(15-min delayed). Connect in <b>Tools › Angel One</b> for real-time intraday.</span>',
                        unsafe_allow_html=True)
        st.caption("Scans every stock in your list for ORB breakout / VWAP / Supertrend signals on the latest bar. "
                   "Best 9:30–11:00 AM and after 2 PM.")

        _ls_def = "RELIANCE\nTCS\nHDFCBANK\nICICIBANK\nINFY\nSBIN\nBHARTIARTL\nAXISBANK\nLT\nMARUTI"
        _ls_c1, _ls_c2 = st.columns([3, 1])
        with _ls_c1:
            _ls_list_raw = st.text_area("Stocks to scan (one per line)",
                                        value=_ls_def, height=150, key="ls_scan_list")
        with _ls_c2:
            _ls_interval = st.selectbox("Interval", ["5m", "15m"], key="ls_interval")
            _ls_btn = st.button("🎯 Scan All", type="primary", key="ls_scan_all",
                                use_container_width=True)

        if _ls_btn:
            _ls_tickers = [t.strip().upper() for t in _ls_list_raw.split("\n") if t.strip()]
            _rows, _fired = [], []
            _prog = st.progress(0, text="Scanning…")
            from trading.intraday_signals import scan_intraday
            for _i, _t in enumerate(_ls_tickers):
                _sym = _t if _t.endswith(".NS") else _t + ".NS"
                try:
                    _res = scan_intraday(_sym, interval=_ls_interval)
                    if "error" in _res:
                        _rows.append({"Stock": _t, "Price": None, "Trend": "—",
                                      "CPR": "—", "Signal": "no data"})
                    else:
                        _sigs = _res.get("signals", [])
                        _sig_txt = ", ".join(f'{s.get("action","")} {s.get("screen","")}'
                                             for s in _sigs) if _sigs else "—"
                        _rows.append({
                            "Stock":  _t,
                            "Price":  round(_res.get("price", 0), 2),
                            "Trend":  "🟢 Bull" if _res.get("st_dir", 0) == 1 else "🔴 Bear",
                            "CPR":    str(_res.get("cpr_zone", "?")).replace("_", " ").title(),
                            "Signal": _sig_txt,
                        })
                        for s in _sigs:
                            _fired.append((_t, _sym, s))
                except Exception:
                    _rows.append({"Stock": _t, "Price": None, "Trend": "—",
                                  "CPR": "—", "Signal": "err"})
                _prog.progress((_i + 1) / max(len(_ls_tickers), 1),
                               text=f"Scanned {_t} ({_i+1}/{len(_ls_tickers)})")
            _prog.empty()

            # ── Active signals first (with one-click paper trade) ──────────────
            if _fired:
                st.success(f"✅ {len(_fired)} live signal(s) across {len(_ls_tickers)} stocks")
                for _t, _sym, _sig in _fired:
                    _act  = _sig.get("action", "")
                    _clr  = "card-green" if _act == "BUY" else "card-red"
                    _icon = "🟢" if _act == "BUY" else "🔴"
                    _p    = _sig.get("price", 0); _sl = _sig.get("sl", 0)
                    _tp   = _sig.get("tp", 0);    _rr = _sig.get("rr_ratio", 0)
                    st.markdown(
                        f'<div class="{_clr}">'
                        f'<span class="signal-big">{_icon} {_t} — {_act} ({_sig.get("screen","")})</span><br>'
                        f'<b>Entry</b> ₹{_p:,.2f} &nbsp;|&nbsp; <b>SL</b> ₹{_sl:,.2f} &nbsp;|&nbsp; '
                        f'<b>TP</b> ₹{_tp:,.2f} &nbsp;|&nbsp; <b>R:R</b> {_rr:.1f}x<br>'
                        f'<small>{_sig.get("reason","")}</small></div>',
                        unsafe_allow_html=True,
                    )
                    if _act == "BUY" and _p > 0:
                        _paper_trade_popover(_sym, _p, _sl, _tp,
                                             reason=f"Intraday {_sig.get('screen','')}: {_sig.get('reason','')[:50]}",
                                             key=f"ls_pt_{_sym}", label=f"📌 Paper Trade {_t}")
            else:
                st.info("No active intraday signals right now across the list.")

            # ── Full scan table ────────────────────────────────────────────────
            st.markdown("#### 📋 Full scan")
            if _rows:
                st.dataframe(pd.DataFrame(_rows), hide_index=True, use_container_width=True)
        else:
            st.info("Add stocks (one per line) and click **🎯 Scan All**.")

    # ── TAB 5: LIVE POSITIONS (Angel One only) ─────────────────────────────────
    if tab_pos is not None:
        with tab_pos:
            st.subheader("Live Intraday Positions — Angel One")
            st.caption("Real-time MIS + CNC positions from your Angel One account.")
            if st.button("🔄 Refresh Positions", key="it_pos_refresh"):
                st.cache_data.clear()

            @st.cache_data(ttl=30, show_spinner=False)
            def _it_positions():
                from data.angel_fetcher import get_positions as _gp, get_funds as _gf
                return _gp(), _gf()

            with st.spinner("Fetching positions…"):
                _it_pos_data, _it_funds = _it_positions()

            # Funds strip
            if _it_funds:
                _fc1, _fc2, _fc3 = st.columns(3)
                _fc1.metric("Available Cash", f"Rs {_it_funds['available_cash']:,.0f}")
                _fc2.metric("Used Margin",    f"Rs {_it_funds['used_margin']:,.0f}")
                _m2m_val = _it_funds.get("m2m", 0)
                _fc3.metric("Unrealised P&L", f"Rs {_m2m_val:+,.0f}",
                            delta_color="normal" if _m2m_val >= 0 else "inverse")

            st.markdown("---")

            if _it_pos_data is None:
                st.error("Could not fetch positions.")
            elif not _it_pos_data.get("net"):
                st.info("No open positions. All flat.")
            else:
                _pos_list = _it_pos_data["net"]
                for _p in _pos_list:
                    _p_clr  = "card-green" if _p["pnl"] >= 0 else "card-red"
                    _p_side_badge = (
                        '<span class="pill-green">LONG</span>'
                        if _p["qty"] > 0
                        else '<span class="pill-red">SHORT</span>'
                    )
                    _p_pnl_clr = "#26a69a" if _p["pnl"] >= 0 else "#ef5350"
                    st.markdown(
                        f'<div class="{_p_clr}">'
                        f'<b>{_p["symbol"]}</b>  {_p_side_badge}  '
                        f'<span style="font-size:12px;color:#aaa">{_p["product"]}</span><br>'
                        f'Qty: {abs(_p["qty"])}  ·  '
                        f'Avg: Rs {_p["avg_price"]:.2f}  ·  '
                        f'LTP: Rs {_p["ltp"]:.2f}  ·  '
                        f'P&L: <span style="color:{_p_pnl_clr};font-weight:700">'
                        f'Rs {_p["pnl"]:+,.0f}</span>'
                        f'</div>',
                        unsafe_allow_html=True,
                    )


# ═══════════════════════════════════════════════════════════════════════════════
# PAGE 12 — POSITION SIZER  [NEW]
# ═══════════════════════════════════════════════════════════════════════════════
elif page == "📐 Position Sizer":
    st.title("📐 Position Sizer — Kelly Criterion + Risk Calculator")
    st.markdown(
        "Calculate exact position size using Kelly Criterion and fixed-risk rules.  \n"
        "Never guess your lot size again — know exactly how many shares to buy *before* you enter."
    )

    _ps_tab1, _ps_tab2 = st.tabs(["💰 Fixed Risk Calculator", "📊 Kelly Criterion"])

    with _ps_tab1:
        st.subheader("Fixed-Risk Position Sizing")
        st.caption("Most common approach: risk a fixed % of capital per trade.")

        _psc1, _psc2 = st.columns(2)
        with _psc1:
            _ps_capital   = st.number_input("Portfolio Size (₹)", 50_000, 50_000_000, 500_000, 50_000, key="ps_cap")
            _ps_risk_pct  = st.slider("Risk per trade (%)", 0.5, 3.0, 1.0, 0.25, key="ps_risk_pct")
            _ps_entry     = st.number_input("Entry Price (₹)", 1.0, 100_000.0, 500.0, 0.5, key="ps_entry",
                                            format="%.2f")
        with _psc2:
            _ps_sl        = st.number_input("Stop-Loss Price (₹)", 1.0, 100_000.0, 480.0, 0.5, key="ps_sl",
                                            format="%.2f")
            _ps_tp        = st.number_input("Target Price (₹)", 1.0, 200_000.0, 550.0, 0.5, key="ps_tp",
                                            format="%.2f")
            _ps_lot_size  = st.number_input("Lot / Board Lot (shares, 1 for equity)", 1, 10000, 1, key="ps_lot")

        if _ps_entry > _ps_sl > 0:
            _risk_rs    = _ps_capital * _ps_risk_pct / 100
            _rps        = _ps_entry - _ps_sl
            _raw_shares = _risk_rs / _rps
            _lots       = max(1, int(_raw_shares / _ps_lot_size))
            _shares     = _lots * _ps_lot_size
            _notional   = _shares * _ps_entry
            _actual_risk = _shares * _rps
            _rr         = (_ps_tp - _ps_entry) / _rps if _rps > 0 else 0
            _exp_profit = _shares * (_ps_tp - _ps_entry)

            st.markdown("---")
            r1, r2, r3, r4, r5 = st.columns(5)
            r1.metric("Shares to Buy",   f"{_shares:,}")
            r2.metric("Notional",        f"₹{_notional:,.0f}")
            r3.metric("Risk ₹",          f"₹{_actual_risk:,.0f}",
                      delta=f"{_actual_risk/_ps_capital*100:.2f}% of capital")
            r4.metric("R:R Ratio",       f"{_rr:.1f}x",
                      delta="✅ Good" if _rr >= 2 else "⚠️ Low")
            r5.metric("Potential Profit",f"₹{_exp_profit:,.0f}")

            _card_color = "card-green" if _rr >= 2 else ("card-yellow" if _rr >= 1.5 else "card-red")
            st.markdown(f"""
            <div class="{_card_color}">
            <b>📋 Trade Plan: {_ps_entry:.2f} entry</b><br>
            Buy <b>{_shares:,} shares</b> at ₹{_ps_entry:.2f} &nbsp;|&nbsp;
            Stop ₹{_ps_sl:.2f} &nbsp;|&nbsp;
            Target ₹{_ps_tp:.2f}<br>
            Risk: ₹{_actual_risk:,.0f} ({_actual_risk/_ps_capital*100:.2f}% of ₹{_ps_capital:,}) &nbsp;|&nbsp;
            R:R = {_rr:.1f}:1 &nbsp;|&nbsp; Potential profit: ₹{_exp_profit:,.0f}
            </div>
            """, unsafe_allow_html=True)
        else:
            st.warning("Entry price must be greater than stop-loss price.")

    with _ps_tab2:
        st.subheader("Kelly Criterion Position Sizing")
        st.caption("Mathematically optimal position size based on your historical win rate and R:R.")
        st.markdown("""
        **Kelly Formula:**  `f* = (b × p − q) / b`  where `b` = R:R ratio, `p` = win rate, `q` = 1 − p

        ⚠️ *Use Half-Kelly (50% of Kelly output) in practice — full Kelly is too aggressive.*
        """)

        _kc1, _kc2 = st.columns(2)
        with _kc1:
            _k_capital  = st.number_input("Portfolio Size (₹)", 50_000, 50_000_000, 500_000, 50_000, key="k_cap")
            _k_winrate  = st.slider("Historical Win Rate (%)", 30, 75, 55, 1, key="k_wr") / 100
            _k_rr       = st.slider("Average R:R Ratio", 0.5, 5.0, 2.0, 0.1, key="k_rr")
        with _kc2:
            _k_fraction = st.slider("Kelly Fraction (0.5 = Half-Kelly)", 0.1, 1.0, 0.5, 0.05, key="k_frac")
            _k_max_risk = st.slider("Max Risk Cap (%)", 0.5, 5.0, 2.0, 0.25, key="k_maxrisk")
            _k_entry    = st.number_input("Entry Price (₹)", 1.0, 100_000.0, 500.0, 0.5, key="k_entry", format="%.2f")
            _k_sl       = st.number_input("Stop-Loss (₹)",  1.0, 100_000.0, 480.0, 0.5, key="k_sl",    format="%.2f")

        from trading.signals import kelly_position_size, shares_from_risk
        try:
            _k_result   = kelly_position_size(
                win_rate=_k_winrate, rr_ratio=_k_rr,
                capital=_k_capital, fraction=_k_fraction, max_risk_pct=_k_max_risk,
            )
            _k_shares   = shares_from_risk(_k_entry, _k_sl, _k_result["risk_rs"]) if _k_entry > _k_sl else 0
            _k_notional = _k_shares * _k_entry
            _k_actual_r = _k_shares * (_k_entry - _k_sl)

            st.markdown("---")
            k1, k2, k3, k4 = st.columns(4)
            k1.metric("Kelly %",       f"{_k_result['kelly_pct']:.1f}%")
            k2.metric("Applied Risk %", f"{_k_result['risk_pct']:.1f}%")
            k3.metric("Risk ₹",        f"₹{_k_result['risk_rs']:,.0f}")
            k4.metric("Shares",        f"{_k_shares:,}")

            st.info(_k_result["notes"])
            if _k_result["kelly_pct"] > 0:
                st.markdown(f"""
                <div class="card-blue">
                <b>Kelly Plan @ ₹{_k_entry:.2f}</b><br>
                Optimal risk: <b>{_k_result['risk_pct']:.1f}%</b> of capital = ₹{_k_result['risk_rs']:,.0f}<br>
                Shares: <b>{_k_shares:,}</b> × ₹{_k_entry:.2f} = ₹{_k_notional:,.0f} notional<br>
                Actual risk: ₹{_k_actual_r:,.0f} with SL at ₹{_k_sl:.2f}
                </div>
                """, unsafe_allow_html=True)
            else:
                st.error("Negative Kelly — this setup has negative expected value. Do not trade.")
        except Exception as _ke:
            st.error(f"Kelly calculation error: {_ke}")


# ═══════════════════════════════════════════════════════════════════════════════
# PAGE 13 — SWING TRADE CHECKLIST  [NEW]
# ═══════════════════════════════════════════════════════════════════════════════
elif page == "✅ Swing Checklist":
    st.title("✅ Swing Trade Confluence Checklist")
    st.markdown(
        "Run all 7 go/no-go factors for a delivery swing trade in one click.  \n"
        "Green = factor confirms the trade. Red = caution. Need ≥ 5/7 green to enter."
    )

    _sc_c1, _sc_c2 = st.columns([3, 1])
    with _sc_c1:
        _sc_ticker = st.text_input("NSE Ticker", value="RELIANCE",
                                   placeholder="RELIANCE / TCS / INFY",
                                   key="sc_ticker").strip().upper()
    with _sc_c2:
        st.write("")
        st.write("")
        _sc_btn = st.button("✅ Run Checklist", type="primary", key="sc_btn")

    if _sc_btn and _sc_ticker:
        _sc_sym = _sc_ticker if _sc_ticker.endswith(".NS") else _sc_ticker + ".NS"
        with st.spinner(f"Running confluence checklist for {_sc_ticker}…"):
            try:
                from data.fetcher import fetch_single
                from utils.indicators import add_all_indicators
                from trading.signals import (get_india_vix_regime, check_oversold_bounce,
                                              check_momentum_leader, check_fibonacci_pullback,
                                              check_pullback_to_sma)
                from strategies.sector_rotation import compute_sector_scores, SECTORS

                _sc_df = fetch_single(_sc_sym, period="1y")
                _sc_df = add_all_indicators(_sc_df)
                _sc_df.dropna(subset=["RSI","ATR"], inplace=True)

                _sc_cur = _sc_df.iloc[-1]
                _price  = float(_sc_cur["Close"])
                _rsi    = float(_sc_cur.get("RSI", 50))
                _adx    = float(_sc_cur.get("ADX", 0)) if not pd.isna(_sc_cur.get("ADX",0)) else 0
                _sma20  = float(_sc_cur.get("SMA_20", 0))
                _sma50  = float(_sc_cur.get("SMA_50", 0))
                _sma200 = float(_sc_cur.get("SMA_200", 0))
                _atr    = float(_sc_cur.get("ATR", 0))
                _vol_r  = float(_sc_cur.get("Volume_Ratio", 1))
                _st_dir = int(_sc_cur.get("ST_Direction", 0))
                _fib_zone = str(_sc_cur.get("Fib_Zone", "unknown"))
                _cpr_zone = str(_sc_cur.get("Price_vs_CPR", "unknown"))

                # VIX check
                _vix_r = get_india_vix_regime()
                _vix_ok = _vix_r["allow_buy"]
                _vix_val = _vix_r.get("vix") or 0

                # Sector rank check
                try:
                    _sec_scores = compute_sector_scores(period="1y")
                    _top3 = set(_sec_scores.head(3).index.tolist()) if not _sec_scores.empty else set()
                    _ticker_sector = {t: s for s, ts in SECTORS.items() for t in ts}
                    _stock_sector = _ticker_sector.get(_sc_sym, "Unknown")
                    _sector_ok = _stock_sector in _top3
                    _sector_str = f"{_stock_sector} ({('Top 3' if _sector_ok else 'Not top 3')})"
                except Exception:
                    _sector_ok, _sector_str = True, "Unknown (not filtered)"

                # MTF check (weekly trend)
                try:
                    from analysis.mtf import check_daily_weekly_alignment
                    _mtf = check_daily_weekly_alignment(_sc_df)
                    _mtf_ok = _mtf["alignment"] == "bullish"
                    _mtf_str = _mtf["confirmation"]
                except Exception:
                    _mtf_ok, _mtf_str = True, "MTF check skipped"

                # Build checklist items
                _checks = [
                    {
                        "name":   "1️⃣ VIX Regime",
                        "pass":   _vix_ok,
                        "detail": f"India VIX = {_vix_val:.1f} | Regime: {_vix_r.get('regime','?').upper()}",
                        "tip":    "VIX must be ≤ 28. High VIX = panic = avoid new longs.",
                    },
                    {
                        "name":   "2️⃣ Long-Term Trend (SMA200)",
                        "pass":   _price > _sma200 > 0,
                        "detail": f"Price ₹{_price:.1f} {'>' if _price > _sma200 else '<'} SMA200 ₹{_sma200:.1f}",
                        "tip":    "Price must be above 200-day SMA to confirm long-term uptrend.",
                    },
                    {
                        "name":   "3️⃣ MA Stack (SMA20 > SMA50)",
                        "pass":   _sma20 > _sma50 > 0,
                        "detail": f"SMA20 ₹{_sma20:.1f} {'>' if _sma20>_sma50 else '<'} SMA50 ₹{_sma50:.1f}",
                        "tip":    "Moving average alignment confirms short-term uptrend.",
                    },
                    {
                        "name":   "4️⃣ RSI Zone (30–70)",
                        "pass":   30 < _rsi < 72,
                        "detail": f"RSI = {_rsi:.1f} | Ideal entry: 40–60",
                        "tip":    "RSI in healthy range — not overbought (>72) or in freefall (<25).",
                    },
                    {
                        "name":   "5️⃣ ADX Trend Strength",
                        "pass":   _adx >= 20,
                        "detail": f"ADX = {_adx:.1f} | {'Trending ✅' if _adx>=25 else ('Weak trend' if _adx>=20 else 'Ranging ❌')}",
                        "tip":    "ADX ≥ 20 confirms trending environment. Below 20 = ranging/choppy.",
                    },
                    {
                        "name":   "6️⃣ Multi-Timeframe Alignment",
                        "pass":   _mtf_ok,
                        "detail": _mtf_str,
                        "tip":    "Both daily and weekly must be bullish for high-conviction swing entry.",
                    },
                    {
                        "name":   "7️⃣ Sector in Top-3",
                        "pass":   _sector_ok,
                        "detail": _sector_str,
                        "tip":    "Stocks in top-3 sectors by momentum score have higher win rates.",
                    },
                ]

                # Score
                _score = sum(1 for c in _checks if c["pass"])
                _score_color = "card-green" if _score >= 5 else ("card-yellow" if _score >= 3 else "card-red")
                _verdict = (
                    "✅ STRONG SETUP — All key factors aligned. Consider entry."
                    if _score >= 6 else
                    "🟡 MODERATE SETUP — Most factors align. Entry with smaller size."
                    if _score >= 4 else
                    "🔴 WEAK SETUP — Too many factors against. Wait for improvement."
                )

                st.markdown(f"""
                <div class="{_score_color}">
                <span class="score-big">{_score}/7</span> &nbsp;&nbsp;
                <span class="signal-big">{_verdict}</span><br>
                <b>{_sc_ticker}</b> at ₹{_price:.2f} | RSI {_rsi:.1f} | ADX {_adx:.1f}
                </div>
                """, unsafe_allow_html=True)

                st.markdown("---")
                st.markdown("### Checklist Details")
                for _chk in _checks:
                    _icon  = "✅" if _chk["pass"] else "❌"
                    _color = "#4caf50" if _chk["pass"] else "#ef5350"
                    st.markdown(
                        f"<div style='border-left:4px solid {_color}; padding:8px 12px; "
                        f"margin:6px 0; background:rgba(255,255,255,0.03); border-radius:4px;'>"
                        f"<b>{_icon} {_chk['name']}</b><br>"
                        f"<span style='color:#ccc'>{_chk['detail']}</span><br>"
                        f"<small style='color:#888'>{_chk['tip']}</small></div>",
                        unsafe_allow_html=True,
                    )

                # Trade plan if score ≥ 4
                if _score >= 4 and _atr > 0:
                    st.markdown("---")
                    st.markdown("### 📋 Suggested Trade Plan")
                    _sl_val = _price - 2 * _atr
                    _tp_val = _price + 3 * _atr
                    _rr_val = 3 * _atr / (2 * _atr)
                    st.markdown(f"""
                    <div class="card-blue">
                    <b>Entry:</b> ₹{_price:.2f} &nbsp;|&nbsp;
                    <b>SL:</b> ₹{_sl_val:.2f} (2× ATR) &nbsp;|&nbsp;
                    <b>TP:</b> ₹{_tp_val:.2f} (3× ATR) &nbsp;|&nbsp;
                    <b>R:R:</b> {_rr_val:.1f}x<br>
                    <small>ATR = ₹{_atr:.2f} | Fib Zone: {_fib_zone} | CPR: {_cpr_zone}</small>
                    </div>
                    """, unsafe_allow_html=True)

            except Exception as _sce:
                st.error(f"Checklist error: {_sce}")
                import traceback; st.code(traceback.format_exc())
    else:
        st.info("Enter a ticker and click **✅ Run Checklist** to see confluence analysis.")

    # Reference table
    st.markdown("---")
    st.markdown("### 📖 Checklist Reference — What Each Factor Means")
    st.dataframe(pd.DataFrame([
        {"Factor":    "VIX Regime",          "Pass When":  "India VIX ≤ 28",        "Why It Matters": "High VIX = market panic = stop-outs are more likely"},
        {"Factor":    "SMA200 Trend",         "Pass When":  "Price > SMA200",         "Why It Matters": "Stocks below SMA200 are in a downtrend — buying is fighting the tape"},
        {"Factor":    "MA Stack",             "Pass When":  "SMA20 > SMA50",          "Why It Matters": "Short-term uptrend confirmed when faster MA is above slower"},
        {"Factor":    "RSI Zone",             "Pass When":  "RSI 30–72",              "Why It Matters": "Outside this range = exhaustion (too hot or too cold)"},
        {"Factor":    "ADX Strength",         "Pass When":  "ADX ≥ 20",              "Why It Matters": "Trending stocks have higher momentum carry than ranging stocks"},
        {"Factor":    "MTF Alignment",        "Pass When":  "Daily+Weekly both bullish","Why It Matters": "Same direction on multiple timeframes = higher conviction"},
        {"Factor":    "Sector Rank",          "Pass When":  "Sector in Top 3",        "Why It Matters": "Rising sectors carry stocks — fight sector momentum rarely works"},
    ]), hide_index=True, use_container_width=True)


# ═══════════════════════════════════════════════════════════════════════════════
# PAGE 14 — MY WATCHLIST  [NEW]
# ═══════════════════════════════════════════════════════════════════════════════
elif page == "⭐ My Watchlist":
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
        except Exception:
            return False

    def _wl_remove(ticker: str):
        _wl_con.execute("DELETE FROM watchlist WHERE ticker=?", (ticker.upper(),))
        _wl_con.commit()

    def _wl_get_all():
        return pd.read_sql("SELECT * FROM watchlist ORDER BY added_at DESC", _wl_con)

    # Add to watchlist form
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
        if st.button("⭐ Add", key="wl_add_btn") and _new_tkr:
            _sym = _new_tkr if _new_tkr.endswith(".NS") else _new_tkr + ".NS"
            if _wl_add(_sym, _new_notes, _new_target, _new_sl):
                st.success(f"Added {_sym} to watchlist!")
                st.rerun()

    # Display watchlist with live scores
    _wl_data = _wl_get_all()
    if _wl_data.empty:
        st.info("Your watchlist is empty. Add stocks using the form above.")
    else:
        _refresh_btn = st.button("🔄 Refresh Scores", key="wl_refresh")

        @st.cache_data(ttl=600, show_spinner=False)
        def _wl_scores(tickers_tuple):
            rows = []
            for tkr in tickers_tuple:
                try:
                    cs = get_composite_score(tkr)
                    rows.append({
                        "ticker":    tkr,
                        "price":     cs.current_price,
                        "score":     cs.composite_score,
                        "signal":    cs.overall_signal,
                        "rsi":       round(cs.technical_indicators.get("rsi", 0), 1),
                        "change_1d": round(cs.technical_indicators.get("return_1d", 0) * 100, 2),
                    })
                except Exception:
                    rows.append({"ticker": tkr, "price": None, "score": None,
                                 "signal": "Error", "rsi": None, "change_1d": None})
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
                "⭐": "⭐",
                "Ticker":       tkr.replace(".NS",""),
                "Price ₹":      f"₹{sc.get('price',0):,.2f}" if sc.get("price") else "—",
                "1d %":         f"{sc.get('change_1d',0):+.2f}%" if sc.get("change_1d") is not None else "—",
                "Score":        sc.get("score", "—"),
                "Signal":       sc.get("signal", "—"),
                "RSI":          sc.get("rsi","—"),
                "Target ₹":     f"₹{row['target_price']:.1f}" if row["target_price"] else "—",
                "Alert SL ₹":   f"₹{row['alert_sl']:.1f}"   if row["alert_sl"]     else "—",
                "Notes":        row["notes"] or "",
                "Added":        str(row["added_at"])[:10],
            })

        _wl_display_df = pd.DataFrame(_merged)
        st.dataframe(_wl_display_df, hide_index=True, use_container_width=True, height=420)

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
elif page == "📖 Investor Guide":
    st.title("📖 Investor Guide — How to Read This Dashboard")
    st.markdown(
        "This guide explains every signal, score, and term used in the NSE Smart Investor platform.  \n"
        "Read this once and you will understand exactly what every number means and when to act."
    )

    tab_g1, tab_g2, tab_g3, tab_g4, tab_g5 = st.tabs([
        "🎯 Scores & Signals", "📊 Indicators", "🔴 Stop-Loss & Risk",
        "📰 News Signals", "📌 Paper Trading SOP"
    ])

    # ── TAB 1: SCORES & SIGNALS ───────────────────────────────────────────────
    with tab_g1:
        st.subheader("Composite Score (0 – 100)")
        st.markdown(
            "Every stock gets a **Composite Score from 0 to 100**. "
            "This combines five factors: Technical (40 pts) + Momentum (25 pts) + "
            "Volume (15 pts) + Candlestick Pattern (10 pts) + News Sentiment (10 pts)."
        )
        st.dataframe(pd.DataFrame([
            {"Score Range": "80 – 100", "Grade": "A+", "Signal": "STRONG BUY 🚀",   "What It Means": "Everything aligned — strong trend, good momentum, high volume. Ideal entry."},
            {"Score Range": "65 – 79",  "Grade": "A",  "Signal": "BUY 🟢",           "What It Means": "Positive trend with good momentum. Entry is favourable."},
            {"Score Range": "50 – 64",  "Grade": "B",  "Signal": "WATCHLIST 👀",     "What It Means": "Mixed signals. Worth watching but wait for clearer confirmation."},
            {"Score Range": "40 – 49",  "Grade": "C",  "Signal": "HOLD 🟡",          "What It Means": "Balanced picture — neither buy nor sell. Hold your existing position."},
            {"Score Range": "25 – 39",  "Grade": "D",  "Signal": "CAUTION ⚠️",       "What It Means": "Deteriorating momentum. Tighten stop-loss, don't add more."},
            {"Score Range": "0 – 24",   "Grade": "F",  "Signal": "EXIT 🔴",          "What It Means": "Technicals broken. Consider exiting to protect capital."},
        ]), hide_index=True)

        st.markdown("---")
        st.subheader("Score Sub-Components")
        st.dataframe(pd.DataFrame([
            {"Component":    "Technical (40 pts)",  "What It Measures": "RSI, MACD, Bollinger Bands, SMA trends — is the stock in a healthy uptrend?"},
            {"Component":    "Momentum (25 pts)",   "What It Measures": "Recent price performance vs moving averages. Is the stock accelerating?"},
            {"Component":    "Volume (15 pts)",     "What It Measures": "Is trading volume higher than normal? Big moves on high volume are more reliable."},
            {"Component":    "Candlestick (10 pts)","What It Measures": "Bullish/bearish candle patterns in last 3 days (Hammer, Engulfing, Doji, etc.)"},
            {"Component":    "Sentiment (10 pts)",  "What It Measures": "News tone: positive articles boost score, negative articles reduce it."},
        ]), hide_index=True)

        st.markdown("---")
        st.subheader("VIX Regime — Market Fear Gauge")
        st.markdown(
            "**India VIX** measures how much volatility the market expects over the next 30 days. "
            "High VIX = fear = caution. Low VIX = complacency = also caution (different reason)."
        )
        st.dataframe(pd.DataFrame([
            {"VIX Level": "< 12",   "Regime": "Complacency", "Meaning": "Market too relaxed — be careful, corrections start here"},
            {"VIX Level": "12–16",  "Regime": "Normal 🟢",   "Meaning": "Healthy range — good conditions for long trades"},
            {"VIX Level": "16–22",  "Regime": "Elevated 🟡", "Meaning": "Some fear — be selective, reduce position sizes"},
            {"VIX Level": "22–28",  "Regime": "Fear 🔴",     "Meaning": "Significant fear — prioritise stop-losses, be defensive"},
            {"VIX Level": "> 28",   "Regime": "PANIC 🔴",    "Meaning": "Market panic — avoid new long positions; can be contrarian buy at extremes"},
        ]), hide_index=True)

    # ── TAB 2: INDICATORS ─────────────────────────────────────────────────────
    with tab_g2:
        st.subheader("Technical Indicators — Plain English")
        st.dataframe(pd.DataFrame([
            {"Indicator": "RSI (14)",          "Range": "0 – 100",    "Normal": "30–70",     "Meaning": "Relative Strength Index. Below 30 = oversold (potential bounce). Above 70 = overbought (potential pullback). Not a standalone signal."},
            {"Indicator": "MACD",              "Range": "Positive/Neg","Normal": "Near zero", "Meaning": "Moving Average Convergence Divergence. MACD crossing above its signal line = bullish. Below = bearish."},
            {"Indicator": "Bollinger Bands",   "Range": "Price levels","Normal": "Within band","Meaning": "Upper/lower bands = 2 standard deviations from 20-day average. Price near upper = overbought. Near lower = oversold."},
            {"Indicator": "SMA 20 / 50 / 200","Range": "Price level", "Normal": "Price > SMA","Meaning": "Simple Moving Average. Price above SMA200 = in long-term uptrend. SMA20 > SMA50 > SMA200 = strong bull alignment."},
            {"Indicator": "ADX",               "Range": "0 – 100",    "Normal": "20–40",     "Meaning": "Average Directional Index. Above 25 = trending (directional trade OK). Below 20 = ranging (avoid breakout trades)."},
            {"Indicator": "ATR",               "Range": "₹ value",    "Normal": "Varies",    "Meaning": "Average True Range. Average daily price movement in rupees. Used to set stop-losses (typically 1.5–2× ATR below entry)."},
            {"Indicator": "Volume Ratio",      "Range": "> 0",        "Normal": "0.8–1.2",   "Meaning": "Today's volume ÷ 20-day average volume. Above 1.5 = above-average interest. Above 2.5 = institutional activity."},
            {"Indicator": "Stochastic K",      "Range": "0 – 100",    "Normal": "20–80",     "Meaning": "Momentum oscillator. Below 20 = oversold, above 80 = overbought. Best used with other signals."},
            {"Indicator": "VWAP %",            "Range": "% value",    "Normal": "±1%",       "Meaning": "Price vs Volume-Weighted Average Price. Positive = stock is above where most volume traded today (bullish intraday). Negative = below (bearish intraday)."},
        ]), hide_index=True)

        st.markdown("---")
        st.subheader("Candlestick Patterns")
        st.dataframe(pd.DataFrame([
            {"Pattern": "Hammer 🔨",          "Type": "Bullish Reversal", "Reliability": "★★★★", "What It Means": "Long lower wick at a low. Sellers tried to push lower but buyers stepped in. Bullish at support."},
            {"Pattern": "Shooting Star ⭐",   "Type": "Bearish Reversal", "Reliability": "★★★★", "What It Means": "Long upper wick at a high. Buyers tried to push higher but sellers overwhelmed them. Bearish at resistance."},
            {"Pattern": "Doji",               "Type": "Indecision",       "Reliability": "★★★",  "What It Means": "Open = Close. Neither buyers nor sellers in control. Watch for next candle's direction."},
            {"Pattern": "Bullish Engulfing",  "Type": "Bullish Reversal", "Reliability": "★★★★★","What It Means": "Large green candle engulfs prior red candle. Powerful reversal after a downtrend. High-probability on volume."},
            {"Pattern": "Bearish Engulfing",  "Type": "Bearish Reversal", "Reliability": "★★★★★","What It Means": "Large red candle engulfs prior green candle. Strong reversal signal after an uptrend."},
            {"Pattern": "Morning Star ☀️",   "Type": "Bullish Reversal", "Reliability": "★★★★★","What It Means": "3-candle: big red → small candle → big green. Classic bottom formation at support."},
            {"Pattern": "Evening Star 🌙",    "Type": "Bearish Reversal", "Reliability": "★★★★★","What It Means": "3-candle: big green → small candle → big red. Classic top formation at resistance."},
            {"Pattern": "Three White Soldiers","Type": "Bullish Continuation","Reliability": "★★★★","What It Means": "3 consecutive bullish candles. Signals strong uptrend resumption after a base."},
        ]), hide_index=True)

    # ── TAB 3: STOP-LOSS & RISK ───────────────────────────────────────────────
    with tab_g3:
        st.subheader("Stop-Loss — Protecting Your Capital")
        st.markdown(
            "A **stop-loss** is the price at which you exit a losing trade to prevent further losses.  \n"
            "**Never trade without a stop-loss.** It is not optional — it is your safety net."
        )
        st.dataframe(pd.DataFrame([
            {"Term": "Stop-Loss (SL)",    "Meaning": "The price at which you will exit if wrong. Set BEFORE you enter the trade."},
            {"Term": "ATR Stop",          "Meaning": "Stop set 1.5–2× the Average True Range (ATR) below entry. Adjusts for each stock's typical daily movement."},
            {"Term": "Structure Stop",    "Meaning": "Stop placed just below a key support level (previous swing low, major moving average)."},
            {"Term": "Trailing Stop",     "Meaning": "Stop that moves UP as the price rises — locks in profits while letting winners run."},
            {"Term": "Breakeven Stop",    "Meaning": "Once a trade gains 1R profit, move stop to entry price. You can no longer lose money on this trade."},
        ]), hide_index=True)

        st.markdown("---")
        st.subheader("Risk : Reward (R:R) — The Most Important Concept")
        st.markdown(
            "**Risk:Reward ratio** compares how much you could lose (risk) vs how much you could gain (reward).  \n"
            "**Always aim for at least 1.5:1**. This means for every ₹100 you risk, you aim to gain ₹150."
        )
        st.dataframe(pd.DataFrame([
            {"R:R Ratio": "3:1 or higher", "Meaning": "Excellent — even with only 35% win rate, you will be profitable long-term"},
            {"R:R Ratio": "2:1",           "Meaning": "Good — standard target. With 45% win rate you profit consistently"},
            {"R:R Ratio": "1.5:1",         "Meaning": "Minimum acceptable. Need >55% win rate to be consistently profitable"},
            {"R:R Ratio": "1:1",           "Meaning": "Break-even at best. Not recommended unless win rate is very high (>65%)"},
            {"R:R Ratio": "< 1:1",         "Meaning": "Avoid — risking more than potential reward. Mathematically losing strategy"},
        ]), hide_index=True)

        st.markdown("---")
        st.subheader("Position Sizing — How Much to Buy")
        st.markdown(
            "**Never risk more than 1–2% of your total capital on a single trade.**  \n\n"
            "**Formula:** Shares to buy = (Capital × Risk%) ÷ (Entry Price − Stop-Loss Price)  \n\n"
            "**Example:** ₹5,00,000 portfolio × 2% risk = ₹10,000 max loss.  \n"
            "If entry = ₹1,000 and stop = ₹950 → risk per share = ₹50  \n"
            "→ Buy 10,000 ÷ 50 = **200 shares** (₹2,00,000 invested, but max loss is ₹10,000)."
        )

        st.markdown("---")
        st.subheader("Common Mistakes — What to Avoid")
        st.dataframe(pd.DataFrame([
            {"Mistake": "No stop-loss",              "Consequence": "One bad trade can wipe out months of gains", "Fix": "Always set a stop before entering"},
            {"Mistake": "Moving stop-loss down",     "Consequence": "Turns a small loss into a disaster",         "Fix": "Only move stops UP (in the trade's favour), never down"},
            {"Mistake": "Averaging down losers",     "Consequence": "More capital trapped in a losing position",  "Fix": "If stop is hit, exit. Never add to a loser."},
            {"Mistake": "Holding losers, selling winners","Consequence": "Loss portfolio of bad trades",         "Fix": "Let winners run. Cut losers quickly at stop."},
            {"Mistake": "Trading on tips/news alone","Consequence": "No edge, random outcomes",                  "Fix": "Use the composite score + chart for confirmation"},
            {"Mistake": "Overtrading",               "Consequence": "Brokerage + taxes eat all profits",         "Fix": "Only trade high-conviction setups (score ≥ 65)"},
        ]), hide_index=True)

    # ── TAB 4: NEWS SIGNALS ───────────────────────────────────────────────────
    with tab_g4:
        st.subheader("How News Affects Stock Prices")
        st.markdown(
            "News is one of the **fastest-moving market catalysts**. The dashboard fetches "
            "real-time news for each stock and tags it with a sentiment: Positive, Negative, or Neutral."
        )
        st.dataframe(pd.DataFrame([
            {"News Type": "🟢 POSITIVE",              "Examples": "Strong quarterly results, big order wins, government policy support, rating upgrades, new product launches"},
            {"News Type": "🔴 NEGATIVE",              "Examples": "Profit warning, regulatory fine, management exit, debt downgrade, sector headwinds, fraud allegations"},
            {"News Type": "⚪ NEUTRAL",               "Examples": "AGM dates, routine management changes, product announcements without financials"},
        ]), hide_index=True)

        st.markdown("---")
        st.subheader("How to Use News Alongside Scores")
        st.dataframe(pd.DataFrame([
            {"Score Signal": "BUY 🟢", "News Sentiment": "Positive 🟢", "Combined Signal": "Strong BUY — fundamentals + technicals aligned",       "Action": "Enter with full position size"},
            {"Score Signal": "BUY 🟢", "News Sentiment": "Negative 🔴", "Combined Signal": "Conflict — technical buy but fundamental headwind",    "Action": "Wait or use half position"},
            {"Score Signal": "HOLD 🟡","News Sentiment": "Positive 🟢", "Combined Signal": "Potential upgrade — watch for score improvement",       "Action": "Set alert, review next day"},
            {"Score Signal": "HOLD 🟡","News Sentiment": "Negative 🔴", "Combined Signal": "Risk of breakdown — tighten stop-loss",                "Action": "Move stop to breakeven or exit"},
            {"Score Signal": "EXIT 🔴","News Sentiment": "Positive 🟢", "Combined Signal": "Technical bearish despite good news — mixed",          "Action": "If score < 30, exit anyway"},
            {"Score Signal": "EXIT 🔴","News Sentiment": "Negative 🔴", "Combined Signal": "Full sell signal — both technicals and news bearish",   "Action": "Exit immediately at stop"},
        ]), hide_index=True)

        st.markdown("---")
        st.subheader("Key News Events Calendar (Indian Markets)")
        st.dataframe(pd.DataFrame([
            {"Event": "Quarterly Results (Q1, Q2, Q3, Q4)", "When": "Apr/Jul/Oct/Jan", "Impact": "HIGH — stock can move 5–20% in one day. Avoid holding through results unless you understand the company well."},
            {"Event": "RBI Monetary Policy Committee (MPC)", "When": "Every 2 months",  "Impact": "HIGH — affects banking stocks, rate-sensitive sectors (real estate, auto, NBFCs)"},
            {"Event": "Union Budget",                        "When": "1 Feb each year", "Impact": "VERY HIGH — sector-specific impacts. VIX spikes before budget, often reverses same day."},
            {"Event": "FII/DII Buy/Sell Data",               "When": "Daily",            "Impact": "MEDIUM — sustained FII selling is bearish for Nifty. FII buying supports rally."},
            {"Event": "SEBI Circulars / Regulatory Actions", "When": "As they occur",   "Impact": "MEDIUM–HIGH — affects specific sectors (fintech, brokers, insurance)"},
        ]), hide_index=True)

    # ── TAB 5: PAPER TRADING SOP ──────────────────────────────────────────────
    with tab_g5:
        st.subheader("📌 How to Use Paper Trading — Step by Step")
        st.markdown(
            "**Paper trading** lets you practice decision-making with zero financial risk.  \n"
            "Think of it as a flight simulator before flying a real plane."
        )

        st.markdown("""
**Step 1 — Find a trade setup**
- Go to **🔍 Analyze Stock** and search for a stock
- If the Composite Score is **≥ 65** and the action is **BUY**, that is a potential entry
- Check the news — is the sentiment positive or neutral?

**Step 2 — Open a paper trade**
- Click **"📌 Paper Trade This Signal"** on the Analyze Stock page, OR
- Go to **📂 Paper Trades** and use the "Open New Paper Trade" form
- The entry price, stop-loss, and target are pre-filled from the model's analysis
- Check the **Risk:Reward ratio** shown — it should be ≥ 1.5:1 before entering

**Step 3 — Track your open position**
- Visit **📂 Paper Trades** daily
- You will see live P&L for every open position
- Green card = in profit. Red card = in loss.
- If the stock hits your stop-loss, click **"Close @ Stop"** — discipline is everything
- If the stock hits your target, click **"Close @ Target"** to book the profit

**Step 4 — Review your performance**
- After 10–20 paper trades, check the **Performance Statistics** section
- Key metrics to watch:
  - **Win Rate > 45%** — you are picking more winners than losers
  - **Payoff Ratio > 1.5** — your winners are bigger than your losers
  - **Expectancy > 0** — your strategy has a positive edge and is worth real money

**Step 5 — Graduate to real money (carefully)**
- Only consider real money after 30+ paper trades with positive expectancy
- Start with the smallest lot size / quantity possible
- Keep risking only 1–2% of capital per trade, just like in paper trading

---
""")

        st.subheader("📊 The 3 Numbers That Define Your Edge")
        _edge_col1, _edge_col2, _edge_col3 = st.columns(3)
        with _edge_col1:
            st.markdown(
                '<div class="card-green">'
                '<b>Win Rate</b><br>'
                'Target: > 45%<br>'
                'How to improve: Only take trades with score ≥ 65 and positive news'
                '</div>', unsafe_allow_html=True
            )
        with _edge_col2:
            st.markdown(
                '<div class="card-blue">'
                '<b>Payoff Ratio</b><br>'
                'Target: > 1.5:1<br>'
                'How to improve: Never enter a trade with R:R less than 1.5:1'
                '</div>', unsafe_allow_html=True
            )
        with _edge_col3:
            st.markdown(
                '<div class="card-yellow">'
                '<b>Expectancy</b><br>'
                'Target: Positive ₹/trade<br>'
                'How to improve: Cut losses quickly; let winners reach target'
                '</div>', unsafe_allow_html=True
            )

        st.markdown("---")
        st.info(
            "📖 **Remember:** The model gives signals based on historical patterns. "
            "No model is 100% accurate. Always use stop-losses. "
            "Paper trade first to verify the signals work for you before using real money."
        )


# ═══════════════════════════════════════════════════════════════════════════════
# PAGE — ANGEL ONE BROKER INTEGRATION
# ═══════════════════════════════════════════════════════════════════════════════
elif page == "🔗 Angel One":
    from data.angel_fetcher import (
        is_configured as _ao_is_configured,
        _get_session as _ao_get_session,
        get_profile as _ao_get_profile,
        get_funds as _ao_get_funds,
        get_holdings as _ao_get_holdings,
        get_positions as _ao_get_positions,
        get_order_book as _ao_get_orders,
        get_trade_book as _ao_get_trades,
        place_order as _ao_place_order,
        cancel_order as _ao_cancel_order,
        get_gtt_list as _ao_get_gtts,
        cancel_gtt as _ao_cancel_gtt,
        clear_session as _ao_clear_session,
    )

    st.title("🔗 Angel One — Broker Integration")
    st.markdown("Connect your Angel One SmartAPI account for live data, real holdings, and order placement.")

    _ao_ok = _ao_is_configured()

    # ── Credentials setup ────────────────────────────────────────────────────
    if not _ao_ok:
        st.warning(
            "**Angel One credentials not configured.**  \n"
            "Add them to `.streamlit/secrets.toml` or as environment variables to connect your account."
        )
        with st.expander("📋 Setup Instructions", expanded=True):
            st.markdown("""
**Step 1 — Get your SmartAPI key:**
1. Login to Angel One → My Profile → API Key (or visit [smartapi.angelone.in](https://smartapi.angelone.in))
2. Click **Generate API Key** → copy the key

**Step 2 — Get your TOTP secret:**
1. Angel One → Profile → Security Settings → Two-Factor Authentication → **Re-Setup**
2. Click **"Can't scan QR?"** → copy the **text key** (looks like `JBSWY3DPEHPK3PXP`)

**Step 3 — Add to `.streamlit/secrets.toml`:**
```toml
[angel_one]
api_key      = "C58Sb2tl..."        # SmartAPI key
client_id    = "AABM038127"         # Your Angel One client ID
password     = "yourpassword"       # Login password
totp_secret  = "JBSWY3DPEHPK3PXP"  # Base32 TOTP seed
```

**Or set environment variables:**
```bash
ANGEL_API_KEY=...  ANGEL_CLIENT_ID=...  ANGEL_PASSWORD=...  ANGEL_TOTP_SECRET=...
```

**Step 4 — Restart Streamlit** after adding credentials.
""")
        st.stop()

    # ── Connected — show tabs ────────────────────────────────────────────────
    st.success("Angel One connected", icon="🟢")

    tab_ao1, tab_ao2, tab_ao3, tab_ao4, tab_ao5 = st.tabs([
        "📊 Account Overview",
        "💼 Holdings",
        "⚡ Today's Positions",
        "📋 Orders & Trades",
        "🛒 Quick Order",
    ])

    # ── TAB 1: ACCOUNT OVERVIEW ───────────────────────────────────────────────
    with tab_ao1:
        st.subheader("Account Overview")
        col_p, col_f = st.columns(2)

        with col_p:
            try:
                _prof = _ao_get_profile()
                if _prof:
                    st.markdown(
                        f'<div class="card-blue"><b>{_prof["name"]}</b><br>'
                        f'Client ID: {_prof["client_id"]}<br>'
                        f'Email: {_prof["email"]}<br>'
                        f'Exchanges: {", ".join(_prof["exchanges"])}</div>',
                        unsafe_allow_html=True,
                    )
            except Exception:
                st.markdown("*Profile unavailable*")

        with col_f:
            try:
                _funds = _ao_get_funds()
                if _funds:
                    _cash = _funds["available_cash"]
                    _used = _funds["used_margin"]
                    _m2m  = _funds["m2m"]
                    _m2m_clr = "#26a69a" if _m2m >= 0 else "#ef5350"
                    st.markdown(
                        f'<div class="card-green">'
                        f'<div class="metric-lbl">Available Cash</div>'
                        f'<div class="metric-val">Rs {_cash:,.0f}</div>'
                        f'Used Margin: Rs {_used:,.0f}<br>'
                        f'Unrealised P&L: <span style="color:{_m2m_clr}">Rs {_m2m:+,.0f}</span>'
                        f'</div>',
                        unsafe_allow_html=True,
                    )
            except Exception:
                st.markdown("*Funds data unavailable*")

        if st.button("🔄 Refresh Session", key="ao_refresh"):
            _ao_clear_session()
            st.cache_data.clear()
            st.success("Session cleared — reconnecting on next request")
            st.rerun()

    # ── TAB 2: HOLDINGS ────────────────────────────────────────────────────────
    with tab_ao2:
        st.subheader("Demat Holdings")
        with st.spinner("Fetching holdings from Angel One…"):
            _holdings = _ao_get_holdings()

        if _holdings is None:
            st.error("Could not fetch holdings. Check credentials and try again.")
        elif len(_holdings) == 0:
            st.info("No holdings found in your demat account.")
        else:
            _total_invested = sum(h["avg_price"] * h["qty"] for h in _holdings)
            _total_value    = sum(h["value_rs"] for h in _holdings)
            _total_pnl      = _total_value - _total_invested
            _total_pnl_pct  = (_total_pnl / _total_invested * 100) if _total_invested > 0 else 0

            mh1, mh2, mh3, mh4 = st.columns(4)
            mh1.metric("Stocks", len(_holdings))
            mh2.metric("Portfolio Value", f"Rs {_total_value:,.0f}")
            mh3.metric("Total P&L",
                       f"Rs {_total_pnl:+,.0f}",
                       delta=f"{_total_pnl_pct:+.2f}%",
                       delta_color="normal")
            mh4.metric("Invested", f"Rs {_total_invested:,.0f}")

            st.markdown("---")

            _hdf = pd.DataFrame(_holdings)
            _hdf = _hdf[["symbol", "qty", "avg_price", "ltp", "pnl", "pnl_pct", "value_rs"]]
            _hdf.columns = ["Symbol", "Qty", "Avg Price", "LTP", "P&L (Rs)", "P&L %", "Value (Rs)"]

            def _color_pnl(val):
                if isinstance(val, (int, float)):
                    color = "#26a69a" if val >= 0 else "#ef5350"
                    return f"color: {color}; font-weight:600"
                return ""

            _hdf_styled = (
                _hdf.style
                .format({
                    "Avg Price": "Rs {:.2f}",
                    "LTP":       "Rs {:.2f}",
                    "P&L (Rs)":  "Rs {:.0f}",
                    "P&L %":     "{:.2f}%",
                    "Value (Rs)":"Rs {:.0f}",
                })
                .map(_color_pnl, subset=["P&L (Rs)", "P&L %"])
            )
            st.dataframe(_hdf_styled, hide_index=True, use_container_width=True)

            # Export
            _holdings_csv = _hdf.to_csv(index=False).encode("utf-8")
            st.download_button(
                "⬇ Export Holdings CSV",
                _holdings_csv,
                file_name="angel_one_holdings.csv",
                mime="text/csv",
            )

    # ── TAB 3: TODAY'S POSITIONS ───────────────────────────────────────────────
    with tab_ao3:
        st.subheader("Today's Positions")
        with st.spinner("Fetching positions…"):
            _positions = _ao_get_positions()

        if _positions is None:
            st.error("Could not fetch positions.")
        else:
            _net_pos = _positions.get("net", [])
            if not _net_pos:
                st.info("No open positions today.")
            else:
                _pos_df = pd.DataFrame(_net_pos)
                _pos_df = _pos_df[["symbol", "qty", "avg_price", "ltp", "pnl", "product", "side"]]
                _pos_df.columns = ["Symbol", "Qty", "Avg Price", "LTP", "P&L", "Product", "Side"]

                _total_pos_pnl = sum(p["pnl"] for p in _net_pos)
                pos_c1, pos_c2, pos_c3 = st.columns(3)
                pos_c1.metric("Open Positions", len(_net_pos))
                pos_c2.metric("Total P&L Today",
                              f"Rs {_total_pos_pnl:+,.0f}",
                              delta_color="normal")
                pos_c3.metric("Long / Short",
                              f"{sum(1 for p in _net_pos if p['qty']>0)} / "
                              f"{sum(1 for p in _net_pos if p['qty']<0)}")

                st.dataframe(
                    _pos_df.style
                    .format({
                        "Avg Price": "Rs {:.2f}",
                        "LTP":       "Rs {:.2f}",
                        "P&L":       "Rs {:.0f}",
                    })
                    .map(lambda v: "color:#26a69a;font-weight:600" if isinstance(v, (int,float)) and v >= 0
                         else ("color:#ef5350;font-weight:600" if isinstance(v, (int,float)) else ""),
                         subset=["P&L"]),
                    hide_index=True,
                    use_container_width=True,
                )

    # ── TAB 4: ORDERS & TRADES ─────────────────────────────────────────────────
    with tab_ao4:
        st.subheader("Today's Orders & Trades")
        ord_t1, ord_t2, ord_t3 = st.tabs(["📑 Order Book", "✅ Trade Book", "🎯 GTT Orders"])

        with ord_t1:
            with st.spinner("Fetching order book…"):
                _orders = _ao_get_orders()
            if _orders is None:
                st.error("Could not fetch orders.")
            elif not _orders:
                st.info("No orders today.")
            else:
                _odf = pd.DataFrame(_orders)[
                    ["order_id", "symbol", "side", "qty", "filled_qty",
                     "order_type", "price", "avg_price", "status", "time"]
                ]
                _odf.columns = ["Order ID", "Symbol", "Side", "Qty", "Filled",
                                 "Type", "Price", "Fill Price", "Status", "Time"]

                def _status_color(val):
                    colors = {
                        "complete": "#26a69a", "rejected": "#ef5350",
                        "cancelled": "#888",   "open": "#f9a825",
                        "pending": "#f9a825",
                    }
                    c = colors.get(str(val).lower(), "#aaa")
                    return f"color:{c}; font-weight:600"

                st.dataframe(
                    _odf.style.map(_status_color, subset=["Status"]),
                    hide_index=True,
                    use_container_width=True,
                )

                # Cancel pending order
                _pending = [o for o in _orders if o["status"].lower() in ("open", "pending", "trigger pending")]
                if _pending:
                    st.markdown("**Cancel Pending Order:**")
                    _cancel_opts = {f"{o['symbol']} — {o['side']} {o['qty']} @ {o['price']}": o["order_id"]
                                    for o in _pending}
                    _to_cancel = st.selectbox("Select order", list(_cancel_opts.keys()), key="ao_cancel_sel")
                    if st.button("Cancel Order", key="ao_cancel_btn", type="primary"):
                        if _ao_cancel_order(_cancel_opts[_to_cancel]):
                            st.success("Order cancelled")
                            st.rerun()
                        else:
                            st.error("Cancel failed — order may already be processed")

        with ord_t2:
            with st.spinner("Fetching trade book…"):
                _trades = _ao_get_trades()
            if _trades is None:
                st.error("Could not fetch trades.")
            elif not _trades:
                st.info("No executed trades today.")
            else:
                _tdf = pd.DataFrame(_trades)[
                    ["symbol", "side", "qty", "price", "product", "time"]
                ]
                _tdf.columns = ["Symbol", "Side", "Qty", "Price", "Product", "Time"]
                _total_traded = sum(
                    t["qty"] * t["price"]
                    for t in _trades
                    if isinstance(t.get("qty"), (int, float)) and isinstance(t.get("price"), (int, float))
                )
                st.metric("Total Turnover Today", f"Rs {_total_traded:,.0f}")
                st.dataframe(_tdf, hide_index=True, use_container_width=True)

        with ord_t3:
            with st.spinner("Fetching GTT rules…"):
                _gtts = _ao_get_gtts()
            if _gtts is None:
                st.error("Could not fetch GTT rules.")
            elif not _gtts:
                st.info("No active GTT orders.")
            else:
                _gdf = pd.DataFrame(_gtts)[
                    ["rule_id", "symbol", "side", "qty", "trigger", "limit_price", "status"]
                ]
                _gdf.columns = ["Rule ID", "Symbol", "Side", "Qty", "Trigger", "Limit", "Status"]
                st.dataframe(_gdf, hide_index=True, use_container_width=True)

                _active_gtts = [g for g in _gtts if g["status"].lower() in ("new", "active")]
                if _active_gtts:
                    st.markdown("**Cancel GTT:**")
                    _gtt_opts = {f"{g['symbol']} {g['side']} {g['qty']} @ trigger {g['trigger']}": g
                                 for g in _active_gtts}
                    _gtt_sel = st.selectbox("Select GTT", list(_gtt_opts.keys()), key="ao_gtt_sel")
                    if st.button("Cancel GTT", key="ao_gtt_cancel_btn"):
                        _g = _gtt_opts[_gtt_sel]
                        if _ao_cancel_gtt(_g["rule_id"], _g["symbol"]):
                            st.success("GTT cancelled")
                            st.rerun()
                        else:
                            st.error("Could not cancel GTT")

    # ── TAB 5: QUICK ORDER ─────────────────────────────────────────────────────
    with tab_ao5:
        st.subheader("Quick Order")
        st.warning(
            "This places a **real order** in your Angel One account using live funds. "
            "Double-check all details before confirming.",
            icon="⚠️",
        )

        qo_c1, qo_c2 = st.columns(2)
        with qo_c1:
            _qo_sym   = st.text_input("Stock Symbol (NSE)", value="", placeholder="e.g. RELIANCE", key="qo_sym").strip().upper()
            _qo_qty   = st.number_input("Quantity", min_value=1, value=1, step=1, key="qo_qty")
            _qo_side  = st.radio("Transaction", ["BUY", "SELL"], horizontal=True, key="qo_side")
            _qo_prod  = st.radio("Product", ["DELIVERY", "INTRADAY"], horizontal=True, key="qo_prod")

        with qo_c2:
            _qo_type  = st.selectbox("Order Type", ["MARKET", "LIMIT", "SL", "SL-M"], key="qo_type")
            _qo_price = st.number_input("Limit/Trigger Price (0 = market)",
                                         min_value=0.0, value=0.0, step=0.05, format="%.2f", key="qo_price")
            _qo_trig  = st.number_input("SL Trigger Price (only for SL orders)",
                                         min_value=0.0, value=0.0, step=0.05, format="%.2f", key="qo_trig")
            _qo_valid = st.radio("Validity", ["DAY", "IOC"], horizontal=True, key="qo_valid")

        if _qo_sym:
            _card_cls = "order-buy" if _qo_side == "BUY" else "order-sell"
            st.markdown(
                f'<div class="{_card_cls}">'
                f'<b>{_qo_side} {_qo_qty} × {_qo_sym}</b>  |  '
                f'{_qo_prod} · {_qo_type}'
                + (f'  |  Price: Rs {_qo_price:.2f}' if _qo_price > 0 else "  |  Market Order")
                + f'</div>',
                unsafe_allow_html=True,
            )

        _ao_confirm = st.checkbox(
            "I confirm this is a real order with real money", key="qo_confirm"
        )
        _place_col, _ = st.columns([1, 3])
        with _place_col:
            if st.button("Place Order", type="primary", key="qo_place",
                         disabled=not (_qo_sym and _ao_confirm)):
                with st.spinner("Placing order…"):
                    _result = _ao_place_order(
                        symbol=_qo_sym,
                        qty=int(_qo_qty),
                        side=_qo_side,
                        order_type=_qo_type,
                        price=float(_qo_price),
                        trigger_price=float(_qo_trig),
                        product=_qo_prod,
                        validity=_qo_valid,
                    )
                if _result and _result.get("status") == "placed":
                    st.success(f"Order placed! Order ID: {_result.get('order_id')}")
                elif _result:
                    st.error(f"Order failed: {_result.get('message', 'Unknown error')}")
                else:
                    st.error("Could not connect to Angel One — check session")
