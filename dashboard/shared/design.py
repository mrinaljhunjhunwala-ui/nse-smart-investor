"""dashboard/shared/design.py - NSE Pro CSS theme, Plotly template, UI helpers.

── DESIGN TOKENS (NSE Pro v2 — "Dealing Room") ───────────────────────────────
Reference point: the black-and-phosphor heritage of Bloomberg/Reuters terminals
rather than a generic dark-mode SaaS dashboard. One accent (signal cyan) carries
all interactive/brand chrome; green and red are reserved strictly for
buy/sell semantics so they never compete with the UI for attention.

  Surface   ink #09090b · surface #131316 · sunken #0e0e10 · hairline rgba(255,255,255,.08)
  Text      primary #edeef0 · dim #8b8d93 · faint #55575e
  Signal    bull #16c784 · bear #ff4d4d · caution #f2a93b · accent #2fd1e0
  Type      display/UI: IBM Plex Sans · data/numeric: IBM Plex Mono
  Radius    sharp 6px (tables/inputs/tape) · base 10px (cards/metrics) · soft 18px (hero panels)

Public API (function names + CSS class names) is unchanged from v1 — 13 page
files reference these directly. Only the tokens/values inside change.
────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations
import os, sys, sqlite3, warnings, io, json, math, datetime
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
import plotly.io as pio
from plotly.subplots import make_subplots
import streamlit as st
# FIX WARN1 — narrowed from a blanket `filterwarnings("ignore")` so numpy's
# RuntimeWarnings (invalid value / divide by zero / all-NaN slice) stay visible.
warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=DeprecationWarning)
warnings.filterwarnings("ignore", category=PendingDeprecationWarning)
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


def apply_design():
    """Register Plotly template + inject CSS. Idempotent across pages."""
    if "nse_pro" not in pio.templates:
        pio.templates["nse_pro"] = go.layout.Template(
            layout=dict(
                paper_bgcolor="#09090b",
                plot_bgcolor="#0c0c0f",
                font=dict(family="IBM Plex Sans, -apple-system, sans-serif", color="#8b8d93", size=12),
                title=dict(font=dict(size=15, color="#edeef0")),
                xaxis=dict(gridcolor="rgba(255,255,255,0.05)", linecolor="rgba(255,255,255,0.07)",
                           tickfont=dict(color="#55575e", size=11), zeroline=False),
                yaxis=dict(gridcolor="rgba(255,255,255,0.05)", linecolor="rgba(255,255,255,0.07)",
                           tickfont=dict(color="#55575e", size=11), zeroline=False),
                legend=dict(bgcolor="rgba(14,14,16,0.9)", bordercolor="rgba(255,255,255,0.07)",
                            borderwidth=1, font=dict(color="#8b8d93", size=11)),
                hoverlabel=dict(bgcolor="#131316", bordercolor="rgba(255,255,255,0.14)",
                                font=dict(color="#edeef0", family="IBM Plex Mono", size=12)),
                colorway=["#2fd1e0", "#16c784", "#f2a93b", "#ff4d4d", "#8b8d93", "#5a8fd6",
                          "#c77dff", "#edeef0"],
            )
        )
        pio.templates.default = "nse_pro"

    # ── NSE Pro Design System v2 — "Dealing Room" ──────────────────────────────
    st.markdown(
        """<style>
    @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600;700;800&family=IBM+Plex+Mono:wght@400;500;600;700&display=swap');

    /* ── Hide Streamlit's auto-generated pages/ nav (custom nav lives in
          render_sidebar). Belt-and-suspenders with showSidebarNavigation=false. ── */
    [data-testid="stSidebarNav"] { display: none !important; }

    /* ── Global ──────────────────────────────────────────────────────────────── */
    html, body, [class*="css"] {
        font-family: 'IBM Plex Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif !important;
        -webkit-font-smoothing: antialiased;
    }
    .stApp {
        background: #09090b;
        background-image: radial-gradient(ellipse 90% 40% at 50% -10%, rgba(47,209,224,0.05) 0%, transparent 60%);
        background-attachment: fixed;
    }
    .mono { font-family:'IBM Plex Mono','Courier New',monospace !important; font-variant-numeric: tabular-nums; }

    /* ── Cards ───────────────────────────────────────────────────────────────
       Flat tinted surface + solid left rail, not a diagonal two-stop gradient —
       calmer and denser at a glance, closer to a real order-flow ticket. ─────── */
    .card-green, .card-yellow, .card-red, .card-blue, .card-purple, .card-orange {
        border-radius:10px; padding:14px 18px; margin:6px 0;
        transition: border-color .15s ease, background .15s ease;
    }
    .card-green:hover, .card-yellow:hover, .card-red:hover,
    .card-blue:hover, .card-purple:hover, .card-orange:hover {
        background-position: right center;
    }
    .card-green  { background:rgba(22,199,132,.07);  border-left:3px solid #16c784; }
    .card-yellow { background:rgba(242,169,59,.07);  border-left:3px solid #f2a93b; }
    .card-red    { background:rgba(255,77,77,.07);   border-left:3px solid #ff4d4d; }
    .card-blue   { background:rgba(47,209,224,.06);  border-left:3px solid #2fd1e0; }
    .card-purple { background:rgba(199,125,255,.06); border-left:3px solid #c77dff; }
    .card-orange { background:rgba(242,169,59,.07);  border-left:3px solid #f2a93b; }

    /* ── Score & typography ───────────────────────────────────────────────────── */
    .score-big    { font-family:'IBM Plex Mono',monospace; font-size:54px; font-weight:700; letter-spacing:-1px; font-variant-numeric: tabular-nums; }
    .signal-big   { font-size:21px; font-weight:700; letter-spacing:.6px; text-transform:uppercase; }
    .narrative    { font-size:14px; line-height:1.75; color:#8b8d93; }
    .ticker-label { font-size:23px; font-weight:700; color:#edeef0; letter-spacing:-.2px; }

    /* ── Pills ───────────────────────────────────────────────────────────────── */
    .pill-green  { display:inline-block; background:rgba(22,199,132,.12); color:#16c784; border:1px solid rgba(22,199,132,.4); border-radius:20px; padding:3px 14px; font-size:12px; font-weight:600; }
    .pill-red    { display:inline-block; background:rgba(255,77,77,.12);  color:#ff4d4d; border:1px solid rgba(255,77,77,.4);  border-radius:20px; padding:3px 14px; font-size:12px; font-weight:600; }
    .pill-yellow { display:inline-block; background:rgba(242,169,59,.12); color:#f2a93b; border:1px solid rgba(242,169,59,.4); border-radius:20px; padding:3px 14px; font-size:12px; font-weight:600; }
    .pill-gray   { display:inline-block; background:rgba(255,255,255,.06); color:#8b8d93; border:1px solid rgba(255,255,255,.14); border-radius:20px; padding:3px 14px; font-size:12px; }
    .pill-blue   { display:inline-block; background:rgba(47,209,224,.12);  color:#2fd1e0; border:1px solid rgba(47,209,224,.4);  border-radius:20px; padding:3px 14px; font-size:12px; font-weight:600; }

    /* ── Signal badges ───────────────────────────────────────────────────────── */
    .badge-buy   { background:rgba(22,199,132,.14); color:#16c784; border:1px solid #16c784; border-radius:6px; padding:4px 14px; font-size:13px; font-weight:700; letter-spacing:.5px; display:inline-block; }
    .badge-sell  { background:rgba(255,77,77,.14);  color:#ff4d4d; border:1px solid #ff4d4d; border-radius:6px; padding:4px 14px; font-size:13px; font-weight:700; letter-spacing:.5px; display:inline-block; }
    .badge-hold  { background:rgba(242,169,59,.14); color:#f2a93b; border:1px solid #f2a93b; border-radius:6px; padding:4px 14px; font-size:13px; font-weight:700; letter-spacing:.5px; display:inline-block; }
    .badge-watch { background:rgba(47,209,224,.14); color:#2fd1e0; border:1px solid #2fd1e0; border-radius:6px; padding:4px 14px; font-size:13px; font-weight:700; letter-spacing:.5px; display:inline-block; }

    /* ── Angel One badges ────────────────────────────────────────────────────── */
    .ao-badge-on  { background:rgba(22,199,132,.08); border:1px solid rgba(22,199,132,.4); border-radius:8px; padding:10px 14px; font-size:12px; color:#16c784; margin:4px 0; display:flex; align-items:center; gap:8px; }
    .ao-badge-off { background:rgba(255,255,255,.02); border:1px solid rgba(255,255,255,.08); border-radius:8px; padding:10px 14px; font-size:12px; color:#55575e; margin:4px 0; display:block; }

    /* ── Streamlit metric override ───────────────────────────────────────────── */
    [data-testid="stMetric"] {
        background: #131316;
        border: 1px solid rgba(255,255,255,.07);
        border-radius: 10px; padding: 14px 18px;
    }
    [data-testid="stMetricValue"] { font-family:'IBM Plex Mono',monospace; font-weight:700; letter-spacing:-.3px; font-size:20px; }
    [data-testid="stMetricLabel"] { font-size:11px; color:#55575e; text-transform:uppercase; letter-spacing:1px; font-weight:600; }
    /* Never clip/ellipsis metric text — always show the full value, label and delta */
    [data-testid="stMetric"] { overflow: visible !important; }
    [data-testid="stMetricValue"], [data-testid="stMetricValue"] *,
    [data-testid="stMetricLabel"], [data-testid="stMetricLabel"] *,
    [data-testid="stMetricDelta"], [data-testid="stMetricDelta"] * {
        white-space: normal !important; overflow: visible !important;
        text-overflow: clip !important; max-width: none !important;
    }

    /* ── Buttons ─────────────────────────────────────────────────────────────── */
    .stButton > button {
        border-radius:6px; font-weight:600; letter-spacing:.2px;
        border: 1px solid rgba(255,255,255,.1); transition: all .15s ease;
        background: rgba(255,255,255,.04);
    }
    .stButton > button:hover { border-color: rgba(47,209,224,.5); color:#2fd1e0; }
    .stButton > button[kind="primary"] {
        background: #2fd1e0; border:none; color:#09090b; font-weight:700;
    }
    .stButton > button[kind="primary"]:hover { background:#5cdce8; color:#09090b; }

    /* ── Tabs ────────────────────────────────────────────────────────────────── */
    .stTabs [data-baseweb="tab-list"] {
        gap: 4px; background: rgba(255,255,255,.02);
        border-radius: 8px; padding: 4px;
        border: 1px solid rgba(255,255,255,.05);
    }
    .stTabs [data-baseweb="tab"] {
        border-radius: 6px; padding: 8px 18px; font-weight: 500;
        color: #55575e; transition: all .15s;
    }
    .stTabs [aria-selected="true"] {
        background: #131316; font-weight: 700; color: #2fd1e0;
    }

    /* ── Sidebar ─────────────────────────────────────────────────────────────── */
    [data-testid="stSidebar"] {
        background: #0a0a0c;
        border-right: 1px solid rgba(255,255,255,.06);
    }
    [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p {
        font-size: 13px; color: #8b8d93;
    }

    /* ── Selectbox / inputs ──────────────────────────────────────────────────── */
    [data-baseweb="select"] > div:first-child {
        background: #0e0e10; border-color: rgba(255,255,255,.1) !important;
        border-radius: 6px;
    }
    .stTextInput > div > div > input {
        background: #0e0e10; border-color: rgba(255,255,255,.1);
        border-radius: 6px; color: #edeef0; font-family:'IBM Plex Mono',monospace;
    }
    .stNumberInput > div > div > input {
        background: #0e0e10; border-color: rgba(255,255,255,.1);
        border-radius: 6px; color: #edeef0; font-family:'IBM Plex Mono',monospace;
    }

    /* ── Expanders ───────────────────────────────────────────────────────────── */
    [data-testid="stExpander"] {
        background: rgba(255,255,255,.015);
        border: 1px solid rgba(255,255,255,.06) !important;
        border-radius: 8px;
    }

    /* ── DataFrames ──────────────────────────────────────────────────────────── */
    [data-testid="stDataFrame"] { border-radius: 6px; overflow: hidden; }
    [data-testid="stDataFrame"] thead th {
        background: #0e0e10 !important; color: #55575e !important;
        font-size: 11px; text-transform: uppercase; letter-spacing: .8px;
        font-weight: 600; border-bottom: 1px solid rgba(255,255,255,.07) !important;
    }
    [data-testid="stDataFrame"] tbody td { color: #c8cad0 !important; font-family:'IBM Plex Mono',monospace; font-size:13px; }
    [data-testid="stDataFrame"] tbody tr:hover td { background: rgba(47,209,224,.05) !important; }

    /* ── Order form ──────────────────────────────────────────────────────────── */
    .order-buy  { background:rgba(22,199,132,.06); border:1px solid rgba(22,199,132,.3); border-radius:10px; padding:18px; }
    .order-sell { background:rgba(255,77,77,.06);  border:1px solid rgba(255,77,77,.3);  border-radius:10px; padding:18px; }

    /* ── Custom metric box ───────────────────────────────────────────────────── */
    .metric-box       { background:#131316; border-radius:10px; padding:16px; text-align:center; border:1px solid rgba(255,255,255,.06); }
    .metric-val       { font-family:'IBM Plex Mono',monospace; font-size:27px; font-weight:700; margin:4px 0; letter-spacing:-.3px; }
    .metric-lbl       { font-size:11px; color:#55575e; text-transform:uppercase; letter-spacing:1px; font-weight:600; }
    .metric-delta-pos { color:#16c784; font-size:13px; font-weight:600; font-family:'IBM Plex Mono',monospace; }
    .metric-delta-neg { color:#ff4d4d; font-size:13px; font-weight:600; font-family:'IBM Plex Mono',monospace; }

    /* ── Section divider ─────────────────────────────────────────────────────── */
    .sec-div { display:flex; align-items:center; gap:12px; margin:28px 0 18px; }
    .sec-div-label { font-size:11px; font-weight:700; color:#55575e; text-transform:uppercase; letter-spacing:1.5px; white-space:nowrap; }
    .sec-div-line  { flex:1; height:1px; background:linear-gradient(90deg,rgba(255,255,255,.09),transparent); }

    /* ── Glass panel — reserved for hero/summary panels only (soft radius tier) ── */
    .glass-panel {
        background: #131316;
        border: 1px solid rgba(255,255,255,.08);
        border-radius: 18px; padding: 20px;
    }

    /* ── Scrollbars ──────────────────────────────────────────────────────────── */
    ::-webkit-scrollbar { width:6px; height:6px; }
    ::-webkit-scrollbar-thumb { background:#1c1c20; border-radius:3px; }
    ::-webkit-scrollbar-thumb:hover { background:#2a2a30; }
    ::-webkit-scrollbar-track { background:transparent; }

    /* ── Alerts & info boxes ─────────────────────────────────────────────────── */
    [data-testid="stAlert"] { border-radius: 8px; }

    /* ── Animations — functional only (live-signal pulse), not decorative ──────── */
    @keyframes pulse-green { 0%,100%{box-shadow:0 0 0 0 rgba(22,199,132,.35)} 50%{box-shadow:0 0 0 8px rgba(22,199,132,0)} }
    @keyframes pulse-red   { 0%,100%{box-shadow:0 0 0 0 rgba(255,77,77,.35)}  50%{box-shadow:0 0 0 8px rgba(255,77,77,0)}  }
    .pulse-green { animation:pulse-green 2s infinite; }
    .pulse-red   { animation:pulse-red 2s infinite; }

    /* ── Ticker tape — the one signature element: a lit "dealing room" strip ──── */
    @keyframes ticker-scroll { 0%{transform:translateX(0)} 100%{transform:translateX(-50%)} }
    .ticker-wrap {
        overflow:hidden; padding:9px 0; margin:8px 0;
        border-top:1px solid rgba(47,209,224,.3);
        border-bottom:1px solid rgba(255,255,255,.05);
        background:linear-gradient(180deg, rgba(47,209,224,.04), transparent);
    }
    .ticker-content {
        display:inline-block; white-space:nowrap; animation:ticker-scroll 80s linear infinite;
        font-size:13px; font-family:'IBM Plex Mono','Courier New',monospace; letter-spacing:.2px;
    }
    .ticker-wrap:hover .ticker-content { animation-play-state:paused; }
    </style>""",
        unsafe_allow_html=True,
    )




# ── Design helper functions (NSE Pro — from trading-dashboard-design skill) ───
def _glass_metric(label: str, value: str, delta: str = "", delta_pos: bool = True) -> str:
    d_color = "#16c784" if delta_pos else "#ff4d4d"
    d_sym   = "▲" if delta_pos else "▼"
    d_html  = (f'<div style="font-size:12px;color:{d_color};margin-top:4px;font-weight:600;font-family:\'IBM Plex Mono\',monospace">'
               f'{d_sym} {delta}</div>') if delta else ""
    return (
        f'<div class="glass-panel" style="text-align:center;min-height:80px">'
        f'<div style="font-size:11px;color:#55575e;text-transform:uppercase;letter-spacing:1.2px;font-weight:600">{label}</div>'
        f'<div style="font-family:\'IBM Plex Mono\',monospace;font-size:23px;font-weight:700;color:#edeef0;margin-top:6px;letter-spacing:-.3px">{value}</div>'
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
        "BUY":  ("#16c784", "rgba(22,199,132,.12)"),
        "SELL": ("#ff4d4d", "rgba(255,77,77,.12)"),
        "HOLD": ("#f2a93b", "rgba(242,169,59,.12)"),
        "WATCH":("#2fd1e0", "rgba(47,209,224,.12)"),
    }
    tc, bc = COLORS.get(action, COLORS["HOLD"])
    rr = (target - entry) / (entry - stop) if (entry - stop) > 0.01 else 0
    sc_html = (f'<div style="font-family:\'IBM Plex Mono\',monospace;font-size:28px;font-weight:700;color:{tc}">{score}</div>'
               f'<div style="font-size:10px;color:#55575e">SCORE</div>') if score is not None else ""
    sect_html = (f'<span style="font-size:11px;color:#55575e;font-weight:400;margin-left:8px">{sector}</span>'
                 if sector else "")
    return (
        f'<div style="background:{bc};border:1px solid {tc}44;'
        f'border-left:3px solid {tc};border-radius:10px;padding:16px 20px;margin:8px 0;'
        f'display:flex;align-items:flex-start;gap:16px">'
        f'<div style="min-width:60px;text-align:center">{sc_html}'
        f'<div style="background:{bc};color:{tc};border:1px solid {tc};border-radius:6px;'
        f'padding:4px 10px;font-size:13px;font-weight:700;letter-spacing:1px;margin-top:4px">{action}</div></div>'
        f'<div style="flex:1">'
        f'<div style="font-size:18px;font-weight:700;color:#edeef0">{ticker}{sect_html}</div>'
        f'<div style="font-size:12px;color:#55575e;margin:4px 0">{reason}</div>'
        f'<div style="display:flex;gap:20px;margin-top:10px;font-size:13px;font-family:\'IBM Plex Mono\',monospace">'
        f'<div><span style="color:#55575e;font-size:11px;font-family:\'IBM Plex Sans\'">LTP</span><br><b style="color:#c8cad0">₹{price:.2f}</b></div>'
        f'<div><span style="color:#55575e;font-size:11px;font-family:\'IBM Plex Sans\'">ENTRY</span><br><b style="color:#c8cad0">₹{entry:.2f}</b></div>'
        f'<div><span style="color:#55575e;font-size:11px;font-family:\'IBM Plex Sans\'">STOP</span><br><b style="color:#ff4d4d">₹{stop:.2f}</b></div>'
        f'<div><span style="color:#55575e;font-size:11px;font-family:\'IBM Plex Sans\'">TARGET</span><br><b style="color:#16c784">₹{target:.2f}</b></div>'
        f'<div><span style="color:#55575e;font-size:11px;font-family:\'IBM Plex Sans\'">R:R</span><br><b style="color:{tc}">{rr:.1f}x</b></div>'
        f'</div></div></div>'
    )
