"""
📏 Verdict Calibration & Shadow Trades — page 18

The single most important page in the app for a long-term investor: it
answers "is the model actually right?" and "what would you have made if
you'd taken every BUY it emitted?"

Two views, one ledger:

  1. CALIBRATION — for every FinalVerdict the app has ever emitted (from
     the Analyze Stock page + every pick card on Command Centre and
     Watchlist), fetch the forward return at 1d / 5d / 20d / 60d / 250d
     and pair it with the same-day NIFTY return so we compute alpha (excess
     over the index). Then group by verdict / conviction bucket / subsystem
     labels to show a real hit-rate table with Wilson lower bounds — no
     credit for market moves, no fine-print-hiding of small samples.

  2. SHADOW TRADES — every STRONG BUY / BUY the model emitted appears here
     with the P&L you'd have realised holding to the horizon. This is the
     "winners you skipped" list. There's nothing to configure — a shadow
     trade is created automatically the moment a pick card renders or you
     open Analyze Stock. Failure modes are honest: shadow with return -8%
     is a bad call the model made; you don't get to unlog it.

Design notes
────────────
* Everything is FREE data. Forward prices come via data.fetcher.fetch_single
  (Stooq → Yahoo fallback). No new dependency, no API key.
* Backfill runs on page load, at most 200 log rows per call, so a cold
  page comes up in a second or two even after months of accumulation.
* Persistence follows the paper-trades pattern: SQLite by default (ephemeral
  on Streamlit Cloud), Postgres if DATABASE_URL is set (survives redeploys).
  The warning banner from paper trades applies here too — an ephemeral DB
  means every redeploy resets the calibration history. For this feature to
  be worth anything long-term, set DATABASE_URL. See dashboard/DB_SETUP.md.
"""
from __future__ import annotations

import os
import sys
import pathlib

import pandas as pd
import streamlit as st

# ── Path bootstrap (matches the rest of dashboard/pages/*.py) ────────────────
_ROOT = str(pathlib.Path(__file__).resolve().parents[2])
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from analysis import verdict_ledger as _vl        # noqa: E402
import trade_store as _store                       # noqa: E402
from dashboard.shared.design import apply_design   # noqa: E402
from dashboard.shared.nav import render_sidebar    # noqa: E402
from dashboard.shared.chart_helpers import render_top_bar  # noqa: E402
from dashboard.shared.tokens import COLORS as _TK  # noqa: E402


# FIX: this page previously called st.set_page_config, violating the
# "only dashboard/app.py may call set_page_config" rule. In practice this
# crashed the page whenever a user navigated to it after visiting any
# other page in the same session. Removed, and adding the shared
# apply_design / render_sidebar / render_top_bar so this internal-facing
# calibration page picks up the same chrome as every other page.
apply_design()
render_sidebar(current="Verdict Calibration")
render_top_bar()

st.markdown('<h1 class="page-title-serif">Verdict <em>Calibration &amp; Shadow Trades</em></h1>', unsafe_allow_html=True)

st.caption(
    "How accurate is the model, really? Every FinalVerdict this app has "
    "emitted is logged silently. This page fetches the forward return for "
    "every one that's had enough time to play out and shows the honest "
    "score — win rate, mean return, alpha vs NIFTY, Wilson lower bound."
)

# ── Backend + freshness banner ────────────────────────────────────────────────
_backend = _store.backend_name()
if _backend == "sqlite":
    st.warning(
        "🗄 Storage is **SQLite** (ephemeral on Streamlit Cloud). Every redeploy "
        "resets the verdict ledger — a 20-day calibration needs 20 days of "
        "uninterrupted deploy. For durable calibration set **DATABASE_URL** "
        "(Neon/Supabase free tier). See `dashboard/DB_SETUP.md`.",
        icon="⚠️",
    )

# ── Backfill (lazy, capped, silent) ───────────────────────────────────────────
with st.spinner("Fetching forward returns for eligible verdicts…"):
    _stats = _vl.backfill_returns(max_rows=200)

_col1, _col2, _col3, _col4 = st.columns(4)
_col1.metric("Backend", _backend.upper())
_col2.metric("Rows scanned this load", _stats.get("scanned", 0))
_col3.metric("Rows updated", _stats.get("updated", 0))
_col4.metric("Tickers fetched", _stats.get("tickers_fetched", 0))

_ledger = _vl.load_ledger(limit=5000)
if _ledger.empty:
    st.info(
        "No verdicts logged yet. Open the **🔍 Analyze Stock** page for any "
        "ticker, or visit **🎯 Command Centre** / **⭐ My Watchlist** — every "
        "verdict rendered there is captured here automatically. Come back in "
        "a few days once the first 5-day forward returns have played out."
    )
    st.stop()

# ── Overview strip ────────────────────────────────────────────────────────────
_total = len(_ledger)
_by_source = _ledger.groupby("source").size().to_dict()
_by_verdict = _ledger.groupby("verdict").size().to_dict()
_played_20d = int(_ledger.get("ret_20d", pd.Series()).notna().sum())
_played_60d = int(_ledger.get("ret_60d", pd.Series()).notna().sum())

_o1, _o2, _o3, _o4 = st.columns(4)
_o1.metric("Verdicts logged", f"{_total:,}")
_o2.metric("Shadow trades", f"{_by_source.get('shadow_auto', 0):,}")
_o3.metric("Played out ≥20d", f"{_played_20d:,}")
_o4.metric("Played out ≥60d", f"{_played_60d:,}")

st.markdown("---")

# ── Section A — Calibration by verdict × horizon ─────────────────────────────
st.markdown(
    '<div class="t-h2" style="margin:14px 0 6px 0">'
    '📊 Hit rate by verdict</div>',
    unsafe_allow_html=True,
)
st.caption(
    "For each verdict, what percent of calls closed positive, and what did "
    "the average call earn vs NIFTY? **Win % (raw)** = forward return > 0; "
    "**Win vs NIFTY %** = beat the index (α > 0), counted only over rows "
    "where the NIFTY return is available (**N α**) — α is shown as blank, "
    "not the raw return, when NIFTY is missing. Wilson lower-bound is the "
    "floor on win rate given the sample size — a 100% win rate on 3 trades "
    "is a Wilson lower of ~44%, not 100%. Horizons are **trading sessions** "
    "after the verdict date."
)
st.caption(
    "⚠️ **Overlap caveat:** a ticker viewed on several consecutive days "
    "contributes several rows whose forward windows overlap, so the samples "
    "are not independent. The Wilson bounds treat them as independent and "
    "are therefore **optimistic** (too narrow), especially at 20/60/250 "
    "sessions."
)

# Shared column labels: raw win vs win-vs-NIFTY are labelled distinctly.
_WIN_COLS = {
    "mean_alpha": "α vs NIFTY %",
    "n_alpha": "N α",
    "win_rate": "Win % (raw)",
    "wilson_lower_win": "Wilson lower % (raw)",
    "win_vs_nifty": "Win vs NIFTY %",
    "wilson_lower_vs_nifty": "Wilson lower vs NIFTY %",
    "wins": "Wins (raw)",
}

_horizon_choice = st.radio(
    "Horizon",
    options=[1, 5, 20, 60, 250],
    format_func=lambda h: {1: "1 session", 5: "5 sessions", 20: "20 sessions (~1 mo)",
                            60: "60 sessions (~1 qtr)", 250: "250 sessions (~1 yr)"}[h],
    index=2,
    horizontal=True,
    key="_cal_horizon",
)

_cal = _vl.calibration_by(group_col="verdict", horizon_days=_horizon_choice)
if _cal.empty:
    st.info(
        f"No verdicts have played out for the **{_horizon_choice}-session** horizon "
        f"yet. Try a shorter horizon (1/5 sessions), or wait a few sessions."
    )
else:
    _cal = _cal.rename(columns={
        "n": "N",
        "mean_ret": f"Mean {_horizon_choice}-session %",
        "median_ret": f"Median {_horizon_choice}-session %",
        **_WIN_COLS,
    })
    st.dataframe(_cal, hide_index=True, width="stretch")

    # A brief interpretation line so the user doesn't have to squint.
    _buy_row = _cal[_cal["verdict"].isin(["BUY", "STRONG BUY"])]
    if not _buy_row.empty:
        _bw = _buy_row["Wilson lower % (raw)"].max()
        _bwn = _buy_row["Wilson lower vs NIFTY %"].max()
        _ba = _buy_row["α vs NIFTY %"].max()
        _ba_txt = "unavailable" if pd.isna(_ba) else f"{_ba:+.2f}%"
        _bwn_txt = "unavailable" if pd.isna(_bwn) else f"{_bwn:.1f}%"
        st.caption(
            f"👀 BUY/STRONG BUY at {_horizon_choice} sessions: Wilson-lower raw win "
            f"rate **{_bw:.1f}%**, Wilson-lower win vs NIFTY **{_bwn_txt}**, best "
            f"mean α **{_ba_txt}**. Below 50% Wilson lower means not yet reliably "
            "better than a coin flip (and the overlap caveat above makes these bounds optimistic)."
        )

# ── Section B — Conviction calibration ────────────────────────────────────────
st.markdown("---")
st.markdown(
    '<div class="t-h2" style="margin:14px 0 6px 0">'
    '📈 Conviction calibration</div>',
    unsafe_allow_html=True,
)
st.caption(
    "Does higher conviction actually correlate with higher forward return? "
    "A well-calibrated model shows a clear upward slope. A flat line means "
    "conviction is noise."
)

_ret_col = f"ret_{_horizon_choice}d"
if _ret_col not in _ledger.columns or _ledger[_ret_col].notna().sum() == 0:
    st.info(f"No {_horizon_choice}-day returns computed yet.")
else:
    _cal_df = _ledger[_ledger[_ret_col].notna()].copy()
    if len(_cal_df) < 5:
        st.info(f"Only {len(_cal_df)} data points at {_horizon_choice}d — need at "
                f"least 5 for a meaningful chart.")
    else:
        # Bucket conviction 0-100 in 10-point bins; show mean return per bucket.
        _cal_df["bucket"] = (_cal_df["conviction"] // 10 * 10).astype(int)
        _agg = _cal_df.groupby("bucket").agg(
            mean_ret=(_ret_col, "mean"),
            n=(_ret_col, "count"),
        ).reset_index()
        _agg["mean_ret"] = _agg["mean_ret"].round(2)
        import plotly.graph_objects as go
        from dashboard.shared.chart_helpers import PLOT_COLORS as _PC
        # P2 · adopt the shared `nse_pro` template explicitly + token colours
        _fig = go.Figure()
        _fig.add_bar(x=_agg["bucket"], y=_agg["mean_ret"],
                     text=[f"n={n}" for n in _agg["n"]], textposition="outside",
                     marker_color=[_PC["bear"] if v < 0 else _PC["bull"]
                                   for v in _agg["mean_ret"]])
        _fig.add_hline(y=0, line_dash="dash", line_color=_PC["faint"])
        _fig.update_layout(
            template="nse_pro",
            xaxis_title="Conviction bucket (0-100)",
            yaxis_title=f"Mean {_horizon_choice}-day return %",
            height=360, margin=dict(l=40, r=20, t=20, b=40),
        )
        st.plotly_chart(_fig, width="stretch")

# ── Section C — Per-subsystem hit rate ────────────────────────────────────────
st.markdown("---")
st.markdown(
    '<div class="t-h2" style="margin:14px 0 6px 0">'
    '🧪 Which subsystem is right most often?</div>',
    unsafe_allow_html=True,
)
st.caption(
    "The composite verdict is a decision tree over subsystems. If Technical "
    "BUY has a great hit rate but Thesis Positive has a poor one, that tells "
    "you where to lean — and where to improve."
)

_sub_choice = st.selectbox(
    "Subsystem",
    options=["composite_action", "valuation_posture", "thesis_verdict",
             "quality_flags"],
    format_func=lambda k: {
        "composite_action":  "Technical (composite_action)",
        "valuation_posture": "Valuation posture",
        "thesis_verdict":    "Thesis verdict",
        "quality_flags":     "Quality flag severity",
    }[k],
    key="_cal_subsystem",
)
_sub_tbl = _vl.calibration_by(group_col=_sub_choice, horizon_days=_horizon_choice)
if _sub_tbl.empty:
    st.info("Not enough data with this subsystem populated yet.")
else:
    _sub_tbl = _sub_tbl.rename(columns={
        "n": "N",
        "mean_ret":         f"Mean {_horizon_choice}-session %",
        "median_ret":       f"Median {_horizon_choice}-session %",
        **_WIN_COLS,
    })
    st.dataframe(_sub_tbl, hide_index=True, width="stretch")

# ── Section C-bis — Per-signal-tag hit rate (Tier 1 #3) ──────────────────────
st.markdown("---")
st.markdown(
    '<div class="t-h2" style="margin:14px 0 6px 0">'
    '🔬 Per-signal-tag calibration</div>',
    unsafe_allow_html=True,
)
st.caption(
    "Every verdict is a bundle of individual rules that fired — RSI oversold, "
    "volume surge, a BullEngulfing pattern, a valuation posture, etc. This "
    "table grades **each rule independently** by its own forward return. "
    "Tags with < 5 firings are hidden — they're statistical noise. Sort by "
    "Wilson lower to see which rules are the most reliable regardless of "
    "sample size."
)
_min_n = st.slider("Minimum firings per tag", 3, 30, 5, 1,
                    key="_cal_tag_minn")
_tag_tbl = _vl.tag_calibration(horizon_days=_horizon_choice, min_n=_min_n)
if _tag_tbl.empty:
    st.info(
        "No signal tags with enough firings yet. Every time you open Analyze "
        "Stock, the sub-signals that contributed are recorded — after ~20-30 "
        "verdicts this table becomes meaningful."
    )
else:
    _tag_tbl = _tag_tbl.rename(columns={
        "n": "N", "tag": "Signal tag",
        "mean_ret":         f"Mean {_horizon_choice}-session %",
        "median_ret":       f"Median {_horizon_choice}-session %",
        **_WIN_COLS,
    })
    st.dataframe(_tag_tbl, hide_index=True, width="stretch")

# ── Section D — Shadow trades P&L ─────────────────────────────────────────────
st.markdown("---")
st.markdown(
    '<div class="t-h2" style="margin:14px 0 6px 0">'
    '👥 Shadow trades — the winners you skipped</div>',
    unsafe_allow_html=True,
)
st.caption(
    "Every STRONG BUY / BUY the model surfaced (whether or not you paper-"
    "traded it), with the actual return had you held to the horizon."
)
_sh_horizon = st.select_slider(
    "Hold horizon",
    options=[1, 5, 20, 60, 250],
    value=20,
    format_func=lambda h: f"{h} sessions",
    key="_sh_horizon",
)
_sh = _vl.shadow_pnl(horizon_days=_sh_horizon)
if _sh.empty:
    st.info(
        "No shadow trades have played out for this horizon yet. Once you "
        "visit **🎯 Command Centre** or **⭐ My Watchlist** a few times, "
        "every BUY / STRONG BUY card will start showing up here."
    )
else:
    _c1, _c2, _c3, _c4 = st.columns(4)
    _c1.metric("Shadow trades", f"{len(_sh):,}")
    _c2.metric(f"Mean {_sh_horizon}-session return",
               f"{_sh[f'return_{_sh_horizon}d_pct'].mean():+.2f}%")
    if "alpha" in _sh.columns:
        _alpha_ok = _sh["alpha"].dropna()
        _c3.metric("Mean α vs NIFTY",
                   f"{_alpha_ok.mean():+.2f}%" if len(_alpha_ok) else "unavailable",
                   f"n={len(_alpha_ok)}" if len(_alpha_ok) else None)
    _wins = int((_sh[f'return_{_sh_horizon}d_pct'] > 0).sum())
    _c4.metric("Win rate (raw, return > 0)", f"{(_wins/len(_sh)*100):.1f}%",
               f"{_wins}/{len(_sh)}")

    # Colour-code the return column
    def _colour_ret(v):
        try:
            v = float(v)
        except (TypeError, ValueError):
            return ""
        if v > 0:
            return f"color: {_TK['bull']}; font-weight: 600;"
        if v < 0:
            return f"color: {_TK['bear']}; font-weight: 600;"
        return ""
    _sty = _sh.style.applymap(
        _colour_ret,
        subset=[c for c in [f"return_{_sh_horizon}d_pct", "alpha"]
                if c in _sh.columns],
    ).format({
        "entry_price":              "{:,.2f}",
        f"exit_{_sh_horizon}d":     "{:,.2f}",
        f"return_{_sh_horizon}d_pct": "{:+.2f}%",
        f"nifty_{_sh_horizon}d_pct":  "{:+.2f}%",
        "alpha":                    "{:+.2f}%",
        "conviction":               "{:.0f}",
    }, na_rep="—")
    st.dataframe(_sty, hide_index=True, width="stretch")

# ── Section E — Full ledger drilldown ─────────────────────────────────────────
st.markdown("---")
with st.expander("🗄 Full verdict ledger — last 200 entries", expanded=False):
    _keep = ["logged_date", "ticker", "verdict", "conviction", "confidence",
             "horizon", "composite_action", "tqs", "valuation_posture",
             "thesis_verdict", "quality_flags", "source",
             "ret_1d", "ret_5d", "ret_20d", "ret_60d", "ret_250d"]
    _keep = [c for c in _keep if c in _ledger.columns]
    st.dataframe(_ledger[_keep].head(200), hide_index=True, width="stretch")

st.caption(
    "**Sampling caveat:** this ledger reflects tickers you *actually looked at* "
    "or that surfaced in Top Picks / Watchlist — not a uniform sample of the "
    "NSE universe. Use it to judge whether the model was right on the calls "
    "it made to you, not as a market-wide backtest. Note the **🧪 Backtest** "
    "page is not a substitute either: it replays the separate rule-based "
    "RSI-MACD / Momentum strategies, not the composite score or these verdicts."
)
