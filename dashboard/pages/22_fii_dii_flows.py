"""
🏦 FII / DII Flows — page 19

Foreign Institutional Investors (FIIs) and Domestic Institutional
Investors (DIIs) drive Nifty direction more than any single technical
signal. This page shows their daily cash-market net-buy/sell numbers,
the 5-day and 20-day cumulative flow trend, and the classic
buy/sell-side combinations traders read as regime hints.

Data is FREE — pulled from NSE India's own JSON when possible, falls back
to a moneycontrol scrape if NSE blocks the cloud IP. Every successful
fetch is persisted, so the page renders even on a day when both sources
are unreachable (we just show a "last known" banner).
"""
from __future__ import annotations

import os
import sys
import pathlib

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

_ROOT = str(pathlib.Path(__file__).resolve().parents[2])
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from analysis import fii_dii as _fd     # noqa: E402
from dashboard.shared.design import apply_design  # noqa: E402
from dashboard.shared.nav import render_sidebar  # noqa: E402
from dashboard.shared.chart_helpers import render_top_bar  # noqa: E402

# FIX: this page previously called st.set_page_config, which violates the
# CLAUDE.md rule "only dashboard/app.py may call set_page_config; a second
# call is a Streamlit crash". In practice the page loaded standalone in
# smoke tests but crashed as soon as a user navigated to it AFTER visiting
# any other page (Streamlit raises StreamlitAPIException on the second
# set_page_config call in a session). Removed. The page-level page-icon
# and page-title now live only in the shared sidebar+topbar treatment.
#
# Also adding apply_design / render_sidebar / render_top_bar so this page
# picks up the same theme + nav chrome every other page has. Previously
# this page was rendering bare Streamlit, which is why it looked out of
# place next to every other page even when it worked.
apply_design()
render_sidebar(current="FII / DII Flows")
render_top_bar()

st.markdown('<h1 class="page-title-serif">FII / DII <em>Cash-Market Flows</em></h1>', unsafe_allow_html=True)

st.caption(
    "Institutional net-buy/sell in the cash segment. FIIs move the tape; "
    "DIIs often absorb their selling on quality names. Regime hints below."
)

# ── Refresh (lazy — skips network if today already stored) ────────────────────
_c1, _c2 = st.columns([1, 4])
with _c1:
    _do_force = st.button("🔄 Refresh from source", type="secondary",
                          help="Bypass the same-day cache and re-fetch from "
                               "NSE / moneycontrol. Usually not needed.")

with st.spinner("Fetching latest FII/DII data…"):
    _status = _fd.refresh(force=_do_force)

_src_labels = {
    "nse":          "NSE India (live)",
    "moneycontrol": "Moneycontrol (fallback)",
    "cache":        "Local cache (today already stored)",
    "unavailable":  "⚠️ Both sources unreachable — showing last known data",
}
with _c2:
    _msg = _src_labels.get(_status["source"], _status["source"])
    if _status["source"] == "unavailable":
        st.warning(f"{_msg}. Latest available: **{_status.get('latest_date') or '—'}**")
    else:
        st.caption(
            f"Source: **{_msg}** · Latest date: **{_status.get('latest_date') or '—'}** "
            f"· Rows written this refresh: **{_status['rows_written']}**"
        )

# ── History load ─────────────────────────────────────────────────────────────
_days_choice = st.select_slider(
    "History window",
    options=[10, 30, 60, 90, 180, 365],
    value=60, format_func=lambda d: f"{d}d",
)
_df = _fd.load_history(days=_days_choice)

if _df.empty:
    st.info(
        "No FII/DII history yet. Click **🔄 Refresh from source** to fetch. "
        "If both NSE and moneycontrol are blocked from Streamlit Cloud's IP "
        "range, the fetch will fail silently — the ledger will still populate "
        "on the days it succeeds."
    )
    st.stop()

_df["date"] = pd.to_datetime(_df["date"])
_df = _df.sort_values("date").reset_index(drop=True)

# ── Overview strip ────────────────────────────────────────────────────────────
_latest = _df.iloc[-1]
_5d = _df.tail(5)
_20d = _df.tail(20)

_o1, _o2, _o3, _o4 = st.columns(4)
_o1.metric("Latest FII net (₹ Cr)",
           f"{_latest.get('fii_net', 0):+,.0f}" if pd.notna(_latest.get("fii_net")) else "—",
           delta_color=("normal" if pd.isna(_latest.get("fii_net"))
                        else ("normal" if _latest["fii_net"] >= 0 else "inverse")))
_o2.metric("Latest DII net (₹ Cr)",
           f"{_latest.get('dii_net', 0):+,.0f}" if pd.notna(_latest.get("dii_net")) else "—")
_o3.metric("5-day FII cumulative", f"{_5d['fii_net'].sum():+,.0f}")
_o4.metric("20-day DII cumulative", f"{_20d['dii_net'].sum():+,.0f}")

# ── Regime interpretation ─────────────────────────────────────────────────────
# Restructured from a single ### heading into a proper regime card. Same
# 5-way logic as before, but now carries (title, sub-caption, tone) so the
# card can render a coloured rail matching the semantic meaning of the
# regime -- bull green for broad participation, bear red for distribution,
# amber for the two mixed regimes, neutral grey for undetermined.
_fii_5 = _5d["fii_net"].sum()
_dii_5 = _5d["dii_net"].sum()
if _fii_5 > 0 and _dii_5 > 0:
    _rg_icon, _rg_title, _rg_body, _rg_rail = (
        "🟢", "Broad participation",
        "Both FII and DII net buyers this week. Rallies tend to be persistent in this regime.",
        "var(--bull)",
    )
elif _fii_5 < 0 and _dii_5 > 0:
    _rg_icon, _rg_title, _rg_body, _rg_rail = (
        "🟠", "Domestic-supported dip",
        "FIIs selling, DIIs buying. Classic pullback profile — often a buy-on-dip "
        "regime for quality names but not for high-beta.",
        "var(--amber)",
    )
elif _fii_5 < 0 and _dii_5 < 0:
    _rg_icon, _rg_title, _rg_body, _rg_rail = (
        "🔴", "Distribution",
        "Both selling. Historically precedes weakness. Trim marginal positions; "
        "avoid new BUYs on high-beta names.",
        "var(--bear)",
    )
elif _fii_5 > 0 and _dii_5 < 0:
    _rg_icon, _rg_title, _rg_body, _rg_rail = (
        "🟡", "DII profit-taking rally",
        "FIIs buying, DIIs selling. Rallies tend to be shallower; keep stops tight.",
        "var(--amber)",
    )
else:
    _rg_icon, _rg_title, _rg_body, _rg_rail = (
        "⚪", "Mixed",
        "No clear directional signal from institutional flows.",
        "var(--dim)",
    )

st.markdown("---")
st.markdown(
    f'<div style="background:var(--surface);border-left:4px solid {_rg_rail};'
    f'border-radius:var(--r-base);padding:14px 18px;margin:8px 0 12px 0">'
    f'<div style="font-size:11px;font-weight:700;color:var(--dim);'
    f'letter-spacing:.1em;text-transform:uppercase">'
    f'5-Day Regime Read</div>'
    f'<div style="font-family:var(--font-serif);font-size:22px;color:var(--ink);'
    f'font-weight:400;letter-spacing:-.005em;margin:2px 0 6px 0;line-height:1.2">'
    f'<span style="margin-right:8px">{_rg_icon}</span>'
    f'<em style="font-style:italic;color:{_rg_rail}">{_rg_title}</em></div>'
    f'<div style="font-size:13.5px;color:var(--ink-mid);line-height:1.55;max-width:70ch">'
    f'{_rg_body}</div>'
    f'<div style="font-family:var(--font-mono);font-size:11px;color:var(--faint);'
    f'margin-top:8px">FII 5d net {_fii_5:+,.0f} Cr · DII 5d net {_dii_5:+,.0f} Cr</div>'
    f'</div>',
    unsafe_allow_html=True,
)

# ── Chart 1 — daily bars + cumulative line ────────────────────────────────────
st.markdown("---")
st.subheader("📊 Daily net flows (₹ Cr)")

# F1 audit note: Plotly colour params don't parse CSS custom properties,
# so these hex are raw. They ARE the current token values from design.py --
# --bull #16c784, --bear #ff4d4d, --azure #5a8fd6, --amber #f2a93b, --faint
# #55575e -- so a palette swap needs a matching update here.
_fig = go.Figure()
_fig.add_bar(x=_df["date"], y=_df["fii_net"], name="FII net",
             marker_color=["#16c784" if v >= 0 else "#ff4d4d"
                           for v in _df["fii_net"].fillna(0)])
_fig.add_bar(x=_df["date"], y=_df["dii_net"], name="DII net",
             marker_color=["#5a8fd6" if v >= 0 else "#f2a93b"
                           for v in _df["dii_net"].fillna(0)])
_fig.add_hline(y=0, line_dash="dash", line_color="#55575e")
_fig.update_layout(
    barmode="group",
    xaxis_title="", yaxis_title="₹ Crore",
    height=380, margin=dict(l=40, r=20, t=20, b=40),
    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
    legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
)
st.plotly_chart(_fig, width="stretch")

# ── Chart 2 — cumulative ──────────────────────────────────────────────────────
st.markdown("---")
st.subheader("📈 Cumulative flow (running sum over window)")
_cum = _df.copy()
_cum["fii_cum"] = _cum["fii_net"].fillna(0).cumsum()
_cum["dii_cum"] = _cum["dii_net"].fillna(0).cumsum()
# F1 audit note: Plotly hex mirrors the daily-bars chart above (design.py
# tokens --bull #16c784, --azure #5a8fd6, --faint #55575e).
_fig2 = go.Figure()
_fig2.add_trace(go.Scatter(x=_cum["date"], y=_cum["fii_cum"], mode="lines",
                            line=dict(color="#16c784", width=2), name="FII cumulative"))
_fig2.add_trace(go.Scatter(x=_cum["date"], y=_cum["dii_cum"], mode="lines",
                            line=dict(color="#5a8fd6", width=2), name="DII cumulative"))
_fig2.add_hline(y=0, line_dash="dash", line_color="#55575e")
_fig2.update_layout(
    xaxis_title="", yaxis_title="₹ Crore (cumulative)",
    height=340, margin=dict(l=40, r=20, t=20, b=40),
    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
    legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
)
st.plotly_chart(_fig2, width="stretch")

# ── Table ─────────────────────────────────────────────────────────────────────
st.markdown("---")
with st.expander("🗄 Full data table", expanded=False):
    _tbl = _df.copy().sort_values("date", ascending=False)
    _tbl["date"] = _tbl["date"].dt.strftime("%Y-%m-%d")
    for c in ("fii_buy", "fii_sell", "fii_net", "dii_buy", "dii_sell", "dii_net"):
        if c in _tbl.columns:
            _tbl[c] = _tbl[c].apply(lambda v: f"{v:+,.0f}" if pd.notna(v) else "—")
    st.dataframe(_tbl, hide_index=True, width="stretch")

st.caption(
    "**Sources:** NSE India `/api/fiidiiTradeReact` (primary), moneycontrol.com "
    "`fii_dii_activity` (fallback). All values in ₹ Crore, cash segment only. "
    "F&O positioning not included in this view."
)
