"""dashboard/shared/design.py - NSE Pro CSS theme, Plotly template, UI helpers."""
from __future__ import annotations
import os, sys, sqlite3, warnings, io, json, math, datetime
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
import plotly.io as pio
from plotly.subplots import make_subplots
import streamlit as st
warnings.filterwarnings('ignore')
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


def apply_design():
    """Register Plotly template + inject CSS. Idempotent across pages."""
    if "nse_pro" not in pio.templates:
        pio.templates["nse_pro"] = go.layout.Template(
            layout=dict(
                paper_bgcolor="#070c18",
                plot_bgcolor="#0a1020",
                font=dict(family="Inter, -apple-system, sans-serif", color="#8899bb", size=12),
                title=dict(font=dict(size=15, color="#f0f4ff")),
                xaxis=dict(gridcolor="rgba(255,255,255,0.04)", linecolor="rgba(255,255,255,0.06)",
                           tickfont=dict(color="#4a5568", size=11), zeroline=False),
                yaxis=dict(gridcolor="rgba(255,255,255,0.04)", linecolor="rgba(255,255,255,0.06)",
                           tickfont=dict(color="#4a5568", size=11), zeroline=False),
                legend=dict(bgcolor="rgba(10,16,32,0.85)", bordercolor="rgba(255,255,255,0.06)",
                            borderwidth=1, font=dict(color="#8899bb", size=11)),
                hoverlabel=dict(bgcolor="#0d1526", bordercolor="rgba(255,255,255,0.12)",
                                font=dict(color="#f0f4ff", family="Inter", size=12)),
                colorway=["#5b8def", "#00d4aa", "#ff9500", "#a78bfa", "#ff4757", "#FFC107",
                          "#26a69a", "#64b5f6"],
            )
        )
        pio.templates.default = "nse_pro"

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


