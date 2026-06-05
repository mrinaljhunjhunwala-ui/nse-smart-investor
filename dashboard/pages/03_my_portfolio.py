"""My Portfolio - NSE Smart Investor (multipage page; body verbatim from app.py)."""
import os, sys
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
import streamlit as st
from dashboard.shared.design import apply_design
from dashboard.shared.nav import render_sidebar
from dashboard.shared.chart_helpers import render_top_bar
# P3: explicit imports (was a dynamic shared-namespace injection)
import os
import pandas as pd
import plotly.express as px
import streamlit as st
import sys
from dashboard.shared.design import (
    apply_design,
)
from dashboard.shared.trade_utils import (
    _action_emoji,
    _paper_trade_popover,
    _portfolio_live_prices,
)
from dashboard.shared.chart_helpers import (
    _ROOT,
    render_top_bar,
)

apply_design()
render_sidebar(current="My Portfolio")
render_top_bar()

# ───────────────────────── page body (de-indented from app.py) ─────────────────────────
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
                    template="nse_pro", height=300,
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

            # ── 🔔 Auto-Signal Monitor — flag holdings that flipped to BUY/SELL ──
            # Recommendations only. The app NEVER auto-executes real trades.
            _PF_BUY  = {"STRONG BUY", "BUY"}
            _PF_SELL = {"CAUTION", "EXIT", "SELL", "REDUCE"}
            _pf_cur  = {h.ticker: h.action for h in summary.holdings}
            _pf_prev = st.session_state.get("_pf_prev_actions", {})
            _pf_flips = []
            for _tk, _ac in _pf_cur.items():
                _pv = _pf_prev.get(_tk)
                if _pv and _pv != _ac and (_ac in _PF_BUY or _ac in _PF_SELL):
                    _pf_flips.append((_tk.replace(".NS", ""), _pv, _ac,
                                      "buy" if _ac in _PF_BUY else "sell"))
            st.session_state["_pf_prev_actions"] = _pf_cur

            _sg1, _sg2 = st.columns([5, 2])
            _sg1.markdown("### 🔔 Auto-Signal Monitor")
            _pf_auto = _sg2.toggle("Auto-refresh (5 min)", key="pf_auto_signal")

            _pf_buys  = [h for h in summary.holdings if h.action in _PF_BUY]
            _pf_sells = [h for h in summary.holdings if h.action in _PF_SELL]

            if _pf_flips:
                _fl_rows = "".join(
                    f'<div style="font-size:12.5px;color:#fff;margin:2px 0">'
                    f'{"🟢" if _d == "buy" else "🔴"} <b>{_t}</b> '
                    f'<span style="color:#9aa">{_p}</span> → '
                    f'<b style="color:{"#26a69a" if _d == "buy" else "#ef5350"}">{_a}</b></div>'
                    for _t, _p, _a, _d in _pf_flips)
                st.markdown(
                    f'<div style="background:linear-gradient(135deg,#2a1c05,#332208);'
                    f'border-left:4px solid #ff9500;border-radius:10px;padding:10px 14px;'
                    f'margin:4px 0 8px">'
                    f'<div style="font-size:12px;font-weight:700;color:#ff9500;margin-bottom:3px">'
                    f'⚡ {len(_pf_flips)} signal change(s) since your last check</div>'
                    f'{_fl_rows}</div>', unsafe_allow_html=True)
                for _t, _p, _a, _d in _pf_flips:
                    st.toast(f"{'🟢' if _d == 'buy' else '🔴'} {_t}: {_p} → {_a}", icon="⚡")

            st.caption(
                f"📡 **{len(_pf_buys)}** holding(s) signalling **BUY**, "
                f"**{len(_pf_sells)}** signalling **SELL/EXIT** right now — see the cards below. "
                "Recommendations only; the app never auto-executes real trades. "
                "Toggle **Auto-refresh** to keep this live while the page is open.")

            if _pf_auto:
                @st.fragment(run_every="300s")
                def _pf_signal_tick():
                    # a full rerun every 5 min re-scores holdings & re-checks flips
                    st.rerun()
                _pf_signal_tick()

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
                            template="nse_pro", height=300,
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

            # ── 📉 Portfolio Risk & Performance (Phase 1) ─────────────────
            st.markdown("---")
            _rh1, _rh2 = st.columns([5, 2])
            _rh1.subheader("📉 Portfolio Risk & Performance")
            with _rh2:
                _risk_period = st.selectbox(
                    "Lookback", ["6mo", "1y", "2y", "3y"], index=1,
                    key="pf_risk_period", label_visibility="collapsed")
            # purchase dates (from the raw holdings) feed the recency/interpretation layer
            _db_map = {}
            for _hr in getattr(pm, "holdings_raw", []) or []:
                _rt = str(_hr.get("ticker", "")).strip().upper()
                if _rt and not _rt.endswith(".NS"):
                    _rt += ".NS"
                if _rt:
                    _db_map[_rt] = _hr.get("date_bought")
            _risk_holds = tuple(
                (h.ticker, float(getattr(h, "quantity", 0) or 0),
                 _db_map.get(str(h.ticker).upper()))
                for h in summary.holdings if getattr(h, "quantity", 0))

            @st.cache_data(ttl=900, show_spinner=False)
            def _pf_risk(_holds, _period):
                from analysis.portfolio_risk import compute_portfolio_risk
                return compute_portfolio_risk(
                    [{"ticker": t, "quantity": q, "date_bought": db}
                     for t, q, db in _holds], period=_period)

            def _rm(_col, _label, _val, _unit=""):
                if _val is None:
                    _col.metric(_label, "N/A")
                elif _unit == "%":
                    _col.metric(_label, f"{_val:.1f}%")
                else:
                    _col.metric(_label, f"{_val:.2f}")

            if not _risk_holds:
                st.caption("No holdings with quantity to analyze.")
            else:
                with st.spinner("Reconstructing NAV & computing risk metrics…"):
                    _rr = _pf_risk(_risk_holds, _risk_period)
                if _rr.error:
                    st.warning(f"⚠️ Risk analytics unavailable: {_rr.error}")
                else:
                    # specific, weight-aware disclosure (severe → warning, else info)
                    if (_rr.affected_weight_pct or 0) >= 25 or not _rr.purchase_dates_known:
                        st.warning(f"⚠️ {_rr.disclosure}")
                    else:
                        st.info(f"ℹ️ {_rr.disclosure}")
                    st.caption(f"Confidence: **{_rr.confidence}** — {_rr.confidence_reason}")

                    # ── Group 1: HYPOTHETICAL performance (biased by the assumption) ──
                    st.markdown("##### 📈 Hypothetical Performance — *if you'd held today's exact book*")
                    _perf = _rr.performance_metrics()
                    _p1 = st.columns(3)
                    for _i, (_l, _v, _u) in enumerate(_perf[:3]):
                        _rm(_p1[_i], _l, _v, _u)
                    _p2 = st.columns(3)
                    for _i, (_l, _v, _u) in enumerate(_perf[3:]):
                        _rm(_p2[_i], _l, _v, _u)
                    if _rr.nav_curve is not None:
                        _nav_df = _rr.nav_curve.rename("NAV").reset_index()
                        _nav_df.columns = ["Date", "NAV"]
                        _fig_nav = px.area(_nav_df, x="Date", y="NAV",
                                           title="Portfolio NAV / Equity Curve (reconstructed)")
                        _fig_nav.update_layout(template="nse_pro", height=280,
                                               margin=dict(l=0, r=0, t=40, b=0))
                        st.plotly_chart(_fig_nav, width="stretch")

                    # ── Group 2: ROBUST risk profile (unaffected by the assumption) ──
                    st.markdown("##### 🛡️ Risk Profile (current book) — *robust to the holdings assumption*")
                    _rk = _rr.risk_metrics()
                    _rcols = st.columns(4)
                    _rm(_rcols[0], _rk[0][0], _rk[0][1], _rk[0][2])    # Portfolio Beta
                    _rm(_rcols[1], _rk[1][0], _rk[1][1], _rk[1][2])    # Annualised Volatility
                    _rcols[2].metric("Holdings analysed", len(_rr.holdings_used))
                    _rcols[3].metric("Lookback (days)", _rr.n_days)
                    _rcL, _rcR = st.columns([1, 1])
                    with _rcL:
                        if _rr.correlation_matrix is not None:
                            _figc = px.imshow(_rr.correlation_matrix, text_auto=True,
                                              color_continuous_scale="RdBu_r",
                                              zmin=-1, zmax=1, aspect="auto",
                                              title="Holdings Correlation")
                            _figc.update_layout(template="nse_pro", height=360,
                                                margin=dict(l=0, r=0, t=40, b=0))
                            st.plotly_chart(_figc, width="stretch")
                        else:
                            st.caption("Correlation needs ≥2 holdings with shared history.")
                    with _rcR:
                        st.markdown("**Risk contribution by position**")
                        _rc_df = pd.DataFrame(
                            [{"Stock": p.ticker, "Weight %": p.weight_pct,
                              "Beta": p.beta, "Risk %": p.risk_contribution_pct}
                             for p in _rr.risk_contributions])
                        st.dataframe(_rc_df, width="stretch", hide_index=True)
                        st.caption("**Risk %** = share of portfolio *variance* from each "
                                   "position — concentration of risk, which can differ from "
                                   "capital weight.")

                    with st.expander("ℹ️ Methodology & assumptions", expanded=False):
                        st.markdown("**Two metric groups, two interpretations:**")
                        st.markdown("- **Hypothetical Performance** (Sharpe, Sortino, Calmar, CAGR, "
                                    "Total Return, Max Drawdown) assumes today's holdings were held "
                                    "over the whole lookback — read as *current-book hypothetical*, "
                                    "not realised returns. Optimistically biased when names were "
                                    "bought recently (see the notice above).")
                        st.markdown("- **Risk Profile** (Beta, Volatility, Correlation, Risk "
                                    "Contribution) are current-book snapshots — **unaffected** by the "
                                    "holdings assumption and safe to trust.")
                        for _n in _rr.notes:
                            st.markdown(f"- {_n}")
                        st.caption("Informational analytics — not investment advice.")

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
                            st.session_state["_goto_page"] ="🔍 Analyze Stock"
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
