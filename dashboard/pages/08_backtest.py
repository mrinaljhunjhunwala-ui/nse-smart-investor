"""Backtest - NSE Smart Investor (multipage page; body verbatim from app.py)."""
import os, sys
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
import streamlit as st
from dashboard.shared.design import apply_design
from dashboard.shared.nav import render_sidebar
from dashboard.shared.chart_helpers import render_top_bar
from dashboard.shared.disclosures import render_survivorship_notice, render_backtest_assumptions
# P3: explicit imports (was a dynamic shared-namespace injection)
import os
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
import sys
from dashboard.shared.design import (
    apply_design,
)
from dashboard.shared.cache import (
    load_ticker_df,
)
from dashboard.shared.chart_helpers import (
    _ROOT,
    render_top_bar,
)

apply_design()
render_sidebar(current="Backtest")
render_top_bar()

# ───────────────────────── page body (de-indented from app.py) ─────────────────────────
st.title("🧪 Backtest Results")
st.caption("Historical strategy performance — how would these signals have done in the past?")

# Transparency: survivorship-bias notice + the full assumptions/limitations section.
render_survivorship_notice()
render_backtest_assumptions()

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
        fig.update_layout(template="nse_pro", height=400,
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
                # Only require OHLCV to be present. Dropping every row with ANY indicator
                # NaN (e.g. a sparse pattern/Fib column) could punch holes mid-series and
                # silently distort bar timing in the backtest. OHLCV is never NaN, so the
                # bar sequence stays contiguous; strategies compute/skip their own warm-up.
                _bd = _bd.dropna(subset=["Open", "High", "Low", "Close", "Volume"])
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
            except Exception as _e:
                st.caption(f"⚠️ Backtest skipped {_bt_t.replace('.NS','')}: {_e}")
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
            except Exception as _e:
                st.caption(f"⚠️ Couldn't add {t.replace('.NS','')} to comparison: {_e}")
    if fig_comp.data:
        fig_comp.add_hline(y=100, line_dash="dot", line_color="gray")
        fig_comp.update_layout(
            title="Normalised Price Performance (Base = 100)",
            template="nse_pro", height=400, yaxis_title="% of Start Price",
            margin=dict(l=0, r=0, t=40, b=0),
        )
        st.plotly_chart(fig_comp, width="stretch")


# ═══════════════════════════════════════════════════════════════════════════════
# PAGE 7 — MACRO DASHBOARD  [NEW]  (commodity-currency-correlations skill)
# ═══════════════════════════════════════════════════════════════════════════════
