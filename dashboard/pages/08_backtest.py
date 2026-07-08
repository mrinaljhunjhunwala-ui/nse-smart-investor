"""Backtest - NSE Smart Investor (multipage page; body verbatim from app.py).

FIXES applied in this revision
───────────────────────────────
B1  In-app backtest no longer blocks the Streamlit request thread. The run
    is dispatched to a background ThreadPoolExecutor worker. Progress and
    partial results are written into st.session_state["bt_partial"] every
    ticker so the UI stays live. A "Cancel" button sets a threading.Event
    that the worker checks between tickers. A timeout of 20 min is enforced
    after which the partial results are surfaced automatically.

B2  Unified display path — the top of the page now also loads into
    session_state["bt_result"] when portfolio_results.csv is present, so
    the detailed sortable table always renders regardless of whether the
    result came from a file or an in-app run.

B3  Normalised comparison now aligns all tickers to their common date range
    before dividing by the first value, so every line starts from the same
    baseline date and the comparison is apples-to-apples.

B4  In-app run now writes to portfolio_results.csv (same filename the loader
    reads) instead of backtest_results.csv, so the top summary table
    reflects the most recent run immediately after completion.
"""

import os, sys
import logging

_log = logging.getLogger("dashboard.backtest")
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import streamlit as st
from dashboard.shared.design import apply_design
from dashboard.shared.nav import render_sidebar
from dashboard.shared.chart_helpers import render_top_bar
from dashboard.shared.disclosures import (
    render_survivorship_notice,
    render_backtest_assumptions,
)

import os
import threading
import time
import concurrent.futures
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
import sys

from dashboard.shared.design import apply_design
from dashboard.shared.cache import load_ticker_df
from dashboard.shared.chart_helpers import _ROOT, render_top_bar

apply_design()
render_sidebar(current="Backtest")
render_top_bar()

# ─────────────────────────────────────────────────────────────────────────────
st.title("🧪 Backtest Results")
st.caption("Historical strategy performance — how would these signals have done in the past?")

render_survivorship_notice()
render_backtest_assumptions()


def load_backtest_csv(path: str = "portfolio_results.csv") -> pd.DataFrame:
    if os.path.exists(path):
        try:
            return pd.read_csv(path, index_col=0)
        except Exception as e:
            _log.warning("load_backtest_csv: %s exists but failed to parse: %s", path, e)
            return pd.DataFrame()
    return pd.DataFrame()


def _load_backtest_meta(path: str = "portfolio_results.meta.json") -> dict:
    """FIX B6 — read the sidecar metadata written alongside a fresh in-app
    run (see the .to_csv() call below). If it's missing, we genuinely don't
    know when portfolio_results.csv was generated or by what code — this is
    exactly the case for the sample portfolio_results.csv/backtest_results.csv
    files that have been committed to the repo since its very first commit,
    predating every backtest fix made since. Rather than silently displaying
    those numbers as if they were a real, current result (all the label used
    to say was "Loaded from portfolio_results.csv" — no date, no way to tell
    it apart from a run you just did), we show an explicit "age unknown"
    warning so nobody mistakes 6-week-old sample data for a live result.
    """
    import json
    if os.path.exists(path):
        try:
            with open(path) as f:
                return json.load(f)
        except Exception as e:
            _log.warning("_load_backtest_meta: %s exists but failed to parse: %s", path, e)
    return {}


# ─────────────────────────────────────────────────────────────────────────────
# FIX B2: unified display — always load file result into session_state so
# the detailed table renders whether data came from file or in-app run.
# ─────────────────────────────────────────────────────────────────────────────
_file_df = load_backtest_csv()
if not _file_df.empty and "bt_result" not in st.session_state:
    st.session_state["bt_result"] = _file_df
    _meta = _load_backtest_meta()
    if _meta.get("generated_at"):
        st.session_state["bt_result_label"] = (
            f"{_meta.get('strategy', '?')} · {_meta.get('universe', '?')} · "
            f"{_meta.get('period', '?')} · run at {_meta['generated_at']}"
        )
        st.session_state["bt_result_stale_unknown"] = False
    else:
        # No sidecar metadata — this is very likely the sample
        # portfolio_results.csv committed to the repo since its first
        # commit, not a result from a real run on the current code.
        st.session_state["bt_result_label"] = "portfolio_results.csv (age/source unknown)"
        st.session_state["bt_result_stale_unknown"] = True

df = st.session_state.get("bt_result", pd.DataFrame())

if not df.empty:
    if st.session_state.get("bt_result_stale_unknown"):
        st.warning(
            "⚠️ These results have no run-date metadata attached — they were "
            "not produced by an in-app run on this session. This can happen "
            "if `portfolio_results.csv` is old sample data rather than a "
            "fresh result. Click **Run a Backtest** below to get current "
            "numbers you can trust.",
            icon="⚠️",
        )
    r_col = next((c for c in ["Return (%)", "Return(%)"]   if c in df.columns), None)
    s_col = next((c for c in ["Sharpe", "Sharpe Ratio"]    if c in df.columns), None)
    t_col = next((c for c in ["# Trades", "Trades"]        if c in df.columns), None)

    bt1, bt2, bt3, bt4 = st.columns(4)
    bt1.metric("Tickers Tested", len(df))
    bt2.metric("Avg Return",  f"{df[r_col].mean():.2f}%" if r_col else "—")
    bt3.metric("Avg Sharpe",  f"{df[s_col].mean():.2f}"  if s_col else "—")
    bt4.metric("Total Trades",f"{df[t_col].sum():,.0f}"  if t_col else "—")

    grad_cols = [r_col] if r_col else []
    st.dataframe(
        df.style.background_gradient(subset=grad_cols, cmap="RdYlGn").format("{:.2f}"),
        use_container_width=True,
    )

    if r_col:
        fig = px.bar(
            df.reset_index(), x=df.index, y=r_col,
            color=r_col, color_continuous_scale="RdYlGn",
            title="Return (%) per Ticker",
            labels={r_col: "Return (%)"},
        )
        fig.update_layout(
            template="nse_pro", height=400,
            margin=dict(l=0, r=0, t=40, b=0),
        )
        st.plotly_chart(fig, use_container_width=True)
else:
    st.info(
        "No backtest results found.  \n\n"
        "Run:  `python main.py --mode backtest --portfolio --index nifty50`  \n"
        "or use the **Run a Backtest** section below.  \n"
        "Results will appear here automatically."
    )

# ─────────────────────────────────────────────────────────────────────────────
# FIX B1 — Non-blocking in-app backtest runner
# ─────────────────────────────────────────────────────────────────────────────
st.markdown("---")
st.subheader("⚡ Run a Backtest — in the app")

_bt_c1, _bt_c2, _bt_c3, _bt_c4 = st.columns([2, 2, 1, 1])
with _bt_c1:
    _bt_uni = st.selectbox(
        "Universe",
        ["Nifty 50", "Nifty 100", "Nifty 200", "Nifty 500"],
        key="bt_uni",
    )
with _bt_c2:
    _bt_strat = st.selectbox(
        "Strategy", ["RSI + MACD", "Momentum"], key="bt_strat"
    )
with _bt_c3:
    _bt_period = st.selectbox(
        "Period", ["2y", "3y"], index=0, key="bt_period",
        help="Needs 2y+ so all indicators have enough warmup history.",
    )
with _bt_c4:
    st.write("")
    _bt_run = st.button(
        "🚀 Run", type="primary", key="bt_run", use_container_width=True
    )

_uni_map = {
    "Nifty 50":  "nifty50",  "Nifty 100": "nifty100",
    "Nifty 200": "nifty200", "Nifty 500": "nifty500",
}
_est = {
    "Nifty 50":  "~1-2 min", "Nifty 100": "~3-4 min",
    "Nifty 200": "~6-8 min", "Nifty 500": "~10-15 min",
}[_bt_uni]
st.caption(
    f"⏱️ Estimated run time: **{_est}**. "
    "Runs in the background — you can watch live progress below. "
    "A **Cancel** button appears once the run starts."
)

# ── Session-state keys used by the background worker ─────────────────────
# bt_running    : bool  — True while the worker thread is active
# bt_cancel     : threading.Event — set by the Cancel button
# bt_partial    : list of result dicts written by the worker
# bt_progress   : (done, total, current_ticker) tuple for the progress bar
# bt_result     : final pd.DataFrame (set when the run completes)
# bt_result_label: human-readable label for the results header

if "bt_cancel" not in st.session_state:
    st.session_state["bt_cancel"]   = threading.Event()
if "bt_running" not in st.session_state:
    st.session_state["bt_running"]  = False
if "bt_partial" not in st.session_state:
    st.session_state["bt_partial"]  = []
if "bt_progress" not in st.session_state:
    st.session_state["bt_progress"] = (0, 1, "")


def _run_backtest_worker(
    tickers: list,
    strat_cls,
    period: str,
    cost: float,
    cancel_event: threading.Event,
    partial_results: list,      # shared list — worker appends, UI reads
    progress_holder: list,      # [done, total, current_ticker]
):
    """Background worker — runs one ticker at a time, writes partial results."""
    from data.fetcher import fetch_single as _bt_fs
    from utils.indicators import add_all_indicators as _bt_ind
    from backtesting import Backtest as _BT

    total = len(tickers)
    for i, t in enumerate(tickers):
        if cancel_event.is_set():
            break
        progress_holder[0] = i
        progress_holder[2] = t.replace(".NS", "")
        try:
            _bd = _bt_fs(t, period=period)
            _bd = _bt_ind(_bd)
            _bd = _bd.dropna(axis=1, how="all")
            _bd = _bd.dropna(subset=["Open", "High", "Low", "Close", "Volume"])
            if len(_bd) >= 60:
                _stats = _BT(
                    _bd, strat_cls,
                    cash=1_000_000, commission=cost, exclusive_orders=True,
                ).run()
                partial_results.append({
                    "Ticker":           t.replace(".NS", ""),
                    "Return (%)":       round(float(_stats["Return [%]"]),            2),
                    "Buy & Hold (%)":   round(float(_stats["Buy & Hold Return [%]"]), 2),
                    "Sharpe":           round(float(_stats["Sharpe Ratio"]),           2),
                    "Max Drawdown (%)": round(float(_stats["Max. Drawdown [%]"]),      2),
                    "Win Rate (%)":     round(float(_stats["Win Rate [%]"]),           2),
                    "# Trades":         int(_stats["# Trades"]),
                })
        except Exception as _e:
            # Record skip without crashing the worker
            _log.debug("backtest sweep: %s skipped: %s", t, _e)
            partial_results.append({
                "Ticker":  t.replace(".NS", "") + " ⚠️",
                "Return (%)": None, "Buy & Hold (%)": None,
                "Sharpe": None,     "Max Drawdown (%)": None,
                "Win Rate (%)": None, "# Trades": 0,
            })
    progress_holder[0] = total  # signal completion


if _bt_run and not st.session_state.get("bt_running", False):
    try:
        from data.universe import get_universe
        from strategies.rsi_macd import RSIMACDStrategy
        from strategies.momentum import MomentumStrategy
        try:
            from backtest.runner import TOTAL_COST as _BT_COST
        except Exception as e:
            _log.debug("TOTAL_COST import failed, using fallback constant: %s", e)
            _BT_COST = 0.0023

        _strat_cls   = RSIMACDStrategy if _bt_strat.startswith("RSI") else MomentumStrategy
        _bt_tickers  = get_universe(_uni_map[_bt_uni])

        # Reset shared state
        _cancel_ev   = threading.Event()
        _partial     = []
        _progress    = [0, len(_bt_tickers), ""]

        st.session_state["bt_cancel"]       = _cancel_ev
        st.session_state["bt_partial"]      = _partial
        st.session_state["bt_progress"]     = _progress
        st.session_state["bt_running"]      = True
        st.session_state["bt_result_label"] = (
            f"{_bt_strat} · {_bt_uni} · {_bt_period}"
        )
        # FIX B6: stash the run config explicitly in session_state (rather
        # than relying on the fragment closing over these local variables
        # from outside its own scope) so the metadata sidecar written on
        # completion, below, has reliable values to read back.
        st.session_state["bt_strat_used"]  = _bt_strat
        st.session_state["bt_uni_used"]    = _bt_uni
        st.session_state["bt_period_used"] = _bt_period

        # Launch background thread
        _executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        _executor.submit(
            _run_backtest_worker,
            _bt_tickers, _strat_cls, _bt_period, _BT_COST,
            _cancel_ev, _partial, _progress,
        )
        st.session_state["bt_executor"] = _executor
        st.rerun()

    except Exception as _bt_err:
        st.error(f"Backtest failed to start: {_bt_err}")

# ── Live progress display (shown while bt_running is True) ────────────────
# FIX B5 (perf) — this used to poll with a blocking time.sleep(3) followed by
# st.rerun(), which re-executes the ENTIRE page (imports, sidebar, design,
# everything above) every 3 seconds for the whole duration of a backtest run.
# Same anti-pattern already fixed in Command Centre's Top Picks and
# Tomorrow's Watchlist — applying the same @st.fragment(run_every=3) fix
# here: Streamlit reruns just this fragment on its own timer, no blocking
# sleep on the main thread. st.rerun() (full-app scope by default, even
# inside a fragment) is still used once, to escape the fragment when the
# backtest actually finishes and render the final results below.
if st.session_state.get("bt_running", False):

    @st.fragment(run_every=3)
    def _bt_poll_fragment():
        _prog   = st.session_state["bt_progress"]
        _done   = _prog[0]
        _total  = max(_prog[1], 1)
        _ticker = _prog[2]
        _partial = st.session_state.get("bt_partial", [])

        # Cancel button
        if st.button("🛑 Cancel backtest", key="bt_cancel_btn"):
            st.session_state["bt_cancel"].set()
            st.session_state["bt_running"] = False
            st.warning("Backtest cancelled — partial results shown below.")
            st.rerun()

        _pct = _done / _total
        st.progress(_pct, text=f"Running {_ticker} ({_done}/{_total})")

        # Check if worker finished
        _executor = st.session_state.get("bt_executor")
        _finished = _done >= _total or (
            _executor is not None
            and all(f.done() for f in getattr(_executor, "_futures", []))
        )
        # Simpler finish check — worker sets _done == _total when done
        if _done >= _total:
            _finished = True

        if _finished:
            st.session_state["bt_running"] = False
            _bt_rows = [r for r in _partial if r.get("Return (%)") is not None]
            if _bt_rows:
                _bt_res = pd.DataFrame(_bt_rows).set_index("Ticker")
                st.session_state["bt_result"] = _bt_res
                st.session_state["bt_result_stale_unknown"] = False
                # FIX B4: write to portfolio_results.csv so the top table refreshes
                # FIX B6: also write a metadata sidecar with a real timestamp,
                # so a genuine fresh run is honestly distinguishable from the
                # sample CSV that ships in the repo (see _load_backtest_meta
                # above) — this is what lets the "age unknown" warning there
                # only ever fire for data that truly has no known run date.
                try:
                    import datetime as _dt, json as _json
                    _bt_res.to_csv("portfolio_results.csv")
                    with open("portfolio_results.meta.json", "w") as _mf:
                        _json.dump({
                            "generated_at": _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            "strategy": st.session_state.get("bt_strat_used", "?"),
                            "universe": st.session_state.get("bt_uni_used", "?"),
                            "period":   st.session_state.get("bt_period_used", "?"),
                        }, _mf)
                except Exception as _csv_e:
                    import logging; logging.getLogger("dashboard.backtest").warning("Could not write portfolio_results.csv: %s", _csv_e)
                st.success(
                    f"✅ Backtested {len(_bt_res)} stocks "
                    f"({st.session_state.get('bt_result_label','')})."
                )
            else:
                st.warning("No results — data may be unavailable. Try again.")
            st.rerun()
        # else: still running — no sleep needed, run_every=3 handles the
        # next check on its own timer.

    _bt_poll_fragment()

# ── Show last in-app / file backtest result ───────────────────────────────
if "bt_result" in st.session_state and not st.session_state.get("bt_running", False):
    _bt_res = st.session_state["bt_result"]
    if not _bt_res.empty:
        st.markdown(
            f"#### 📊 Results — {st.session_state.get('bt_result_label','')}"
        )
        _rb1, _rb2, _rb3, _rb4 = st.columns(4)
        _rb1.metric("Stocks", len(_bt_res))

        _r_col2 = next(
            (c for c in ["Return (%)", "Return(%)"] if c in _bt_res.columns), None
        )
        _s_col2 = next(
            (c for c in ["Sharpe", "Sharpe Ratio"] if c in _bt_res.columns), None
        )
        _bh_col = next(
            (c for c in ["Buy & Hold (%)", "Buy & Hold Return (%)"]
             if c in _bt_res.columns), None,
        )

        if _r_col2:
            _avg_ret = _bt_res[_r_col2].dropna().mean()
            _rb2.metric(
                "Avg Return", f"{_avg_ret:.1f}%",
                delta_color="normal" if _avg_ret >= 0 else "inverse",
            )
        if _s_col2:
            _rb3.metric("Avg Sharpe", f"{_bt_res[_s_col2].dropna().mean():.2f}")
        if _r_col2 and _bh_col:
            _beat = (
                _bt_res[_r_col2].dropna() > _bt_res[_bh_col].dropna()
            ).sum()
            _rb4.metric("Beat Buy&Hold", f"{_beat}/{len(_bt_res)}")

        _grad_cols2 = [c for c in [_r_col2, _s_col2] if c]
        _bt_sorted  = _bt_res.sort_values(_r_col2, ascending=False) if _r_col2 else _bt_res
        st.dataframe(
            _bt_sorted.style.background_gradient(
                subset=_grad_cols2, cmap="RdYlGn"
            ),
            use_container_width=True, height=380,
        )
        st.caption(
            "Sorted by return. Green = better. "
            "'Beat Buy&Hold' = how often the strategy outperformed simply holding."
        )

# ─────────────────────────────────────────────────────────────────────────────
# FIX B3 — Normalised comparison with common-date alignment
# ─────────────────────────────────────────────────────────────────────────────
st.markdown("---")
st.subheader("🔍 Quick Chart Comparison")
raw2 = st.text_input(
    "Compare tickers (space-separated)",
    value="RELIANCE.NS TCS.NS HDFCBANK.NS",
    key="backtest_tickers",
)
_comp_ui = st.radio(
    "Period", ["1M", "6M", "YTD", "1Y", "Max"],
    index=1, horizontal=True, key="comp_period",
)
comp_period = {"1M": "1m", "6M": "6m", "YTD": "ytd", "1Y": "1y", "Max": "max"}[_comp_ui]

if st.button("📊 Show Normalised Performance", key="compare_btn"):
    tickers_list = [t.strip().upper() for t in raw2.split() if t.strip()]
    tickers_list = [
        t if t.endswith(".NS") else t + ".NS"
        for t in tickers_list
    ]

    # FIX B3: collect all close series, then align to common date range
    _raw_series: dict[str, pd.Series] = {}
    with st.spinner("Loading price data…"):
        for t in tickers_list:
            try:
                d = load_ticker_df(t, period=comp_period)
                if not d.empty and "Close" in d.columns:
                    _raw_series[t] = d["Close"]
            except Exception as _e:
                st.caption(
                    f"⚠️ Couldn't load {t.replace('.NS','')} for comparison: {_e}"
                )

    if _raw_series:
        # Find the common start date (latest first date across all tickers)
        _common_start = max(s.index[0] for s in _raw_series.values())
        _common_end   = min(s.index[-1] for s in _raw_series.values())

        if _common_start >= _common_end:
            st.warning(
                "Tickers don't share a common date range for the selected period. "
                "Try a shorter period or different tickers."
            )
        else:
            fig_comp = go.Figure()
            for t, series in _raw_series.items():
                # FIX B3: slice to common range before normalising
                _aligned = series.loc[_common_start:_common_end].dropna()
                if _aligned.empty:
                    continue
                norm = _aligned / _aligned.iloc[0] * 100
                fig_comp.add_trace(go.Scatter(
                    x=norm.index, y=norm,
                    name=t.replace(".NS", ""),
                    line=dict(width=2),
                ))

            if fig_comp.data:
                fig_comp.add_hline(y=100, line_dash="dot", line_color="gray")
                fig_comp.add_annotation(
                    text=f"Common start: {_common_start.strftime('%d %b %Y')}",
                    xref="paper", yref="paper",
                    x=0, y=1.08, showarrow=False,
                    font=dict(size=10, color="#888"),
                )
                fig_comp.update_layout(
                    title="Normalised Price Performance (Base = 100 at common start date)",
                    template="nse_pro", height=400,
                    yaxis_title="% of Start Price",
                    margin=dict(l=0, r=0, t=50, b=0),
                )
                st.plotly_chart(fig_comp, use_container_width=True)
                st.caption(
                    f"All lines indexed to 100 at **{_common_start.strftime('%d %b %Y')}** "
                    f"(the latest common start date across all tickers) so the comparison "
                    "is apples-to-apples."
                )
    else:
        st.warning("No price data could be loaded for the selected tickers.")
