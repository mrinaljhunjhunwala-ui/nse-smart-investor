"""Analyze Stock - NSE Smart Investor (multipage page; body verbatim from app.py)."""
import os, sys
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
import streamlit as st
from dashboard.shared.design import apply_design
from dashboard.shared.nav import render_sidebar
from dashboard.shared.chart_helpers import render_top_bar
# Fundamentals (Phase 0): UI depends ONLY on the service facade + the schema/analytics.
from analysis.fundamentals.service import default_service as _fund_service
from analysis.fundamentals import analytics as _fund_analytics
# P3: explicit imports (was a dynamic shared-namespace injection)
import os
import streamlit as st
import sys
from dashboard.shared.design import (
    apply_design,
)
from dashboard.shared.cache import (
    STOCK_SEARCH_MAP,
    _deep_confirmation,
    _plain_english,
    _trim_to_period,
    _validate_ticker,
    get_composite_score,
    get_display_name,
    load_ticker_df,
)
from dashboard.shared.trade_utils import (
    _action_color,
    _action_emoji,
    _grade_color,
    paper_open_trade,
)
from dashboard.shared.chart_helpers import (
    _ROOT,
    build_price_chart,
    render_top_bar,
)

apply_design()
render_sidebar(current="Analyze Stock")
render_top_bar()

# ───────────────────────── page body (de-indented from app.py) ─────────────────────────
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

# Validate the manually-typed symbol before any API call
_mt_clean, _mt_err = _validate_ticker(manual_ticker)
if _mt_err:
    st.error(f"⚠️ {_mt_err}")
    st.stop()

# Resolve final ticker
ticker = ""
if _mt_clean:
    ticker = _mt_clean + ".NS"
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

            # ── Fold confirmation into a CONVICTION score (#7) ─────────────
            _conf_delta, _conf_reasons = 0, []
            if _dc["weekly"] == "uptrend":
                _conf_delta += 4; _conf_reasons.append("+4 weekly uptrend")
            elif _dc["weekly"] == "downtrend":
                _conf_delta -= 6; _conf_reasons.append("−6 weekly downtrend")
            if _dc["rs_pct"] is not None:
                if _dc["rs_pct"] > 3:
                    _conf_delta += 4; _conf_reasons.append(f"+4 leads Nifty ({_dc['rs_pct']:+.1f}%)")
                elif _dc["rs_pct"] < -3:
                    _conf_delta -= 4; _conf_reasons.append(f"−4 lags Nifty ({_dc['rs_pct']:+.1f}%)")
            if _ed_days is not None and 0 <= _ed_days <= 7:
                _conf_delta -= 6; _conf_reasons.append(f"−6 earnings in {_ed_days}d")
            if _agr_pct >= 80:
                _conf_delta += 5; _conf_reasons.append(f"+5 strong agreement ({_bull}/{_tot})")
            elif _agr_pct <= 40:
                _conf_delta -= 5; _conf_reasons.append(f"−5 weak agreement ({_bull}/{_tot})")
            _conf_delta  = max(-15, min(15, _conf_delta))
            _conviction  = max(0, min(100, cs.score + _conf_delta))
            _cv_c    = "#00d4aa" if _conviction >= 65 else "#ff9500" if _conviction >= 45 else "#ff4757"
            _delta_c = "#00d4aa" if _conf_delta >= 0 else "#ff4757"
            _delta_s = f"{_conf_delta:+d}" if _conf_delta else "±0"

            st.markdown(
                f'<div style="background:#0d1526;border:1px solid rgba(255,255,255,.06);border-radius:12px;'
                f'padding:14px 18px;margin-bottom:12px">'
                f'<div style="font-size:11px;color:#5b8def;font-weight:700;text-transform:uppercase;'
                f'letter-spacing:1px;margin-bottom:10px">🔬 Multi-Signal Confirmation</div>'
                f'<div style="display:flex;gap:22px;flex-wrap:wrap;align-items:flex-start">'
                # Conviction score — base folded with confirmation
                f'<div style="border-right:1px solid rgba(255,255,255,.08);padding-right:18px">'
                f'<div style="font-size:10px;color:#4a5568">CONVICTION</div>'
                f'<div style="font-size:24px;font-weight:800;color:{_cv_c}">{_conviction:.0f}'
                f'<span style="font-size:12px;color:#8899bb"> /100</span></div>'
                f'<div style="font-size:10px;color:{_delta_c}">base {cs.score:.0f} · {_delta_s} confirmation</div></div>'
                f'<div><div style="font-size:10px;color:#4a5568">WEEKLY TREND</div>'
                f'<div style="font-size:14px;font-weight:700;color:{_wk_c}">{_wk_txt}</div></div>'
                f'<div><div style="font-size:10px;color:#4a5568">RELATIVE STRENGTH</div>'
                f'<div style="font-size:14px;font-weight:700;color:{_rs_c}">{_rs_txt}</div></div>'
                f'<div><div style="font-size:10px;color:#4a5568">EARNINGS</div>'
                f'<div style="font-size:14px;font-weight:700;color:{_ed_c}">{_ed_txt}</div></div>'
                f'<div><div style="font-size:10px;color:#4a5568">SIGNAL AGREEMENT</div>'
                f'<div style="font-size:14px;font-weight:700;color:{_agr_c}">{_bull} of {_tot} bullish</div></div>'
                f'</div>'
                + (f'<div style="font-size:11px;color:#8899bb;margin-top:8px">Conviction adjustments: '
                   f'{" · ".join(_conf_reasons)}</div>' if _conf_reasons else
                   '<div style="font-size:11px;color:#8899bb;margin-top:8px">No adjustment — '
                   'confirmation signals are neutral.</div>')
                + '</div>',
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
                st.session_state["_goto_page"] ="📂 Paper Trades"
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

            # ── 📊 Fundamentals (Phase 0 — Yahoo-backed, provider-agnostic) ──────
            st.markdown("---")
            st.subheader("📊 Fundamentals (beta)")
            try:
                import datetime as _f_dt
                _f_cf = _fund_service().get_fundamentals(ticker)          # facade only
                _f_res = _fund_analytics.compute_all(_f_cf, cagr_years=5)
                _f_fresh = "—"
                if _f_cf.last_updated:
                    _f_hrs = (_f_dt.datetime.now() - _f_cf.last_updated).total_seconds() / 3600
                    _f_fresh = "just now" if _f_hrs < 1 else f"{_f_hrs:.0f}h ago"
                st.caption(
                    f"Provider: **{_f_cf.provider_name or '—'}**  ·  "
                    f"Statement date: **{_f_cf.statement_date or '—'}**  ·  "
                    f"Data freshness: **{_f_fresh}**"
                )
                if _f_cf.is_partial:
                    st.warning(
                        "⚠️ **Partial data** — some fundamentals are unavailable for this stock "
                        f"from {_f_cf.provider_name or 'the provider'}. "
                        f"Missing: {', '.join(_f_cf.missing_fields) or 'n/a'}."
                    )

                def _f_show(_col, _r):
                    if _r.available and _r.value is not None:
                        _txt = f"{_r.value:,.1f}%" if _r.unit == "%" else f"{_r.value:,.2f}x"
                        _col.metric(_r.metric, _txt)
                        _col.caption(f"confidence: {_r.confidence}"
                                     + (f" · {_r.reason}" if _r.reason else ""))
                    else:
                        _col.metric(_r.metric, "N/A")          # never a fabricated 0
                        _col.caption(f"⚠️ {_r.reason}")

                _fc1, _fc2, _fc3, _fc4 = st.columns(4)
                _f_show(_fc1, _f_res["revenue_cagr"])
                _f_show(_fc2, _f_res["eps_cagr"])
                _f_show(_fc3, _f_res["roe"])
                _f_show(_fc4, _f_res["debt_to_equity"])

                # Option A — honest CAGR confidence disclosure (only when not all "high")
                _cagr_results = [r for r in [_f_res.get("revenue_cagr"), _f_res.get("eps_cagr")]
                                 if r is not None and getattr(r, "available", False)]
                if _cagr_results and any(r.confidence in ("medium", "low") for r in _cagr_results):
                    st.caption(
                        "📊 **Data depth note:** CAGR confidence reflects Yahoo Finance's "
                        "available history (~4–5 years for most NSE names). "
                        "\"Medium\" confidence means the trend is directionally reliable "
                        "but not enough history exists for statistical certainty. "
                        "Interpretation: treat Medium-confidence CAGR as a directional signal, "
                        "not a precise forecast."
                    )

                # ── Sector-aware ROCE / FCF (Phase D1) — only where meaningful ──
                from analysis.sector_classification import classify_sector as _classify
                _sp = _classify(getattr(cs, "sector", None),
                                name=getattr(cs, "company_name", None))
                if _sp.is_financial:
                    st.info(f"🏦 **{_sp.group}** — {_sp.note}")
                else:
                    _rc1, _rc2 = st.columns(2)
                    _f_show(_rc1, _f_res["roce"])
                    _rr = _f_res["fcf"]
                    if _rr.available and _rr.value is not None:
                        _rc2.metric("Free Cash Flow", f"₹{_rr.value:,.0f} cr")
                        _cap = (" · capex-heavy: negative FCF can be a normal investment cycle"
                                if _sp.fcf_capex_caveat else "")
                        _rc2.caption(f"confidence: {_rr.confidence}{_cap}")
                    else:
                        _rc2.metric("Free Cash Flow", "N/A")
                        _rc2.caption(f"⚠️ {_rr.reason}")
                st.caption(
                    "Phase 0/D1: Yahoo Finance data only (~4-yr depth), no paid provider. "
                    "ROCE/FCF shown only where economically meaningful. Not investment advice."
                )
            except Exception as _f_e:
                st.caption(f"⚠️ Fundamentals unavailable: {_f_e}")

            # ── 💰 Valuation Context (Phase C1 — surface existing multiples, NO judgment) ──
            st.markdown("---")
            st.subheader("💰 Valuation Context")
            st.caption(
                "Valuation multiples already available from the fundamentals provider. "
                "Factual context only — no cheap/expensive judgment, no peer comparison yet."
            )
            try:
                from analysis.fundamentals.valuation import build_valuation_context
                from analysis.sector_classification import classify_sector as _classify_v
                _spv = _classify_v(getattr(cs, "sector", None),
                                   name=getattr(cs, "company_name", None))
                _val_cf = _fund_service().get_fundamentals(ticker)
                _val = build_valuation_context(_val_cf, sector_profile=_spv)
                _vc1, _vc2, _vc3 = st.columns(3)
                _vc1.metric("P/E", f"{_val.pe:,.1f}x" if _val.pe is not None else "N/A")
                _vc2.metric("P/B", f"{_val.pb:,.1f}x" if _val.pb is not None else "N/A")
                if _val.ev_ebitda_applicable:
                    _vc3.metric("EV/EBITDA",
                                f"{_val.ev_ebitda:,.1f}x" if _val.ev_ebitda is not None else "N/A")
                else:
                    _vc3.metric("EV/EBITDA", "n/a")
                    _vc3.caption("not meaningful for financials")
                if _val.preferred_valuation:
                    st.caption(f"📐 Right lens for this sector: **{_val.preferred_valuation}**")
                for _vn in _val.notes:
                    st.caption("ℹ️ " + _vn)
                st.caption(
                    f"Coverage: **{_val.confidence}**"
                    + (f" · missing: {', '.join(_val.missing_fields)}" if _val.missing_fields else "")
                    + (f" · source: {_val.source}" if _val.source else "")
                    + ". Values are None when unavailable — never fabricated."
                )

                # ── Valuation Assessment (Phase E1-v2 — descriptive posture, NO judgment) ──
                st.markdown("**🧮 Valuation Assessment** *(growth- & quality-adjusted, descriptive)*")
                try:
                    from analysis.fundamentals.valuation_decision import assess_valuation
                    _va_res = _fund_analytics.compute_all(_val_cf)
                    _va = assess_valuation(_val, _va_res, _spv, cf=_val_cf)
                    _va_color = {"high": "#00d4aa", "medium": "#ffa726",
                                 "low": "#8899bb", "none": "#8899bb"}.get(_va.confidence, "#8899bb")
                    st.markdown(
                        f"> {_va.phrase}  \n"
                        f"<span style='color:{_va_color}'>confidence: {_va.confidence}</span>",
                        unsafe_allow_html=True)
                    if _va.justification and _va.posture != "INSUFFICIENT_EVIDENCE":
                        st.caption("Basis: " + _va.justification)
                    if _va.triggered_guard:
                        st.caption(f"Guard: {_va.triggered_guard}")
                    for _rz in _va.reasons:
                        st.caption("• " + _rz)
                    for _cv in _va.caveats:
                        st.caption("⚠️ " + _cv)
                    if _va.confidence_factors:
                        st.caption("Confidence factors: " + " · ".join(_va.confidence_factors))
                    st.caption(
                        "Descriptive only — relates the multiple to growth & quality. No buy/sell, "
                        "no fair/intrinsic value, no cheap/expensive label."
                    )
                except Exception as _va_e:
                    st.caption(f"⚠️ Valuation assessment unavailable: {_va_e}")
            except Exception as _val_e:
                st.caption(f"⚠️ Valuation context unavailable: {_val_e}")

            # ── 💧 Liquidity Context (Phase C1 — from existing OHLCV) ──
            st.markdown("---")
            st.subheader("💧 Liquidity Context")
            _liq_ctx = None
            try:
                from analysis.liquidity import compute_liquidity, format_turnover
                _liq_ctx = compute_liquidity(df)
                _lt_color = {"High": "#00d4aa", "Medium": "#2ecc71",
                             "Low": "#ffa726", "Illiquid": "#ff4757"}.get(
                                 _liq_ctx.liquidity_tier, "#8899bb")
                st.markdown(
                    f"Liquidity tier: <b style='color:{_lt_color}'>{_liq_ctx.liquidity_tier}</b>",
                    unsafe_allow_html=True)
                _lc1, _lc2, _lc3 = st.columns(3)
                _lc1.metric("Avg daily turnover (30d)",
                            format_turnover(_liq_ctx.avg_daily_turnover_30d))
                _lc2.metric("Avg daily volume (30d)",
                            f"{_liq_ctx.avg_daily_volume_30d:,.0f}"
                            if _liq_ctx.avg_daily_volume_30d is not None else "N/A")
                _lc3.metric("Volume trend (30d vs 90d)",
                            (_liq_ctx.volume_trend or "—").title(),
                            f"{_liq_ctx.volume_trend_ratio:.2f}x"
                            if _liq_ctx.volume_trend_ratio is not None else None)
                st.caption(_liq_ctx.reason + " · computed from existing OHLCV (no new data source).")
            except Exception as _liq_e:
                st.caption(f"⚠️ Liquidity context unavailable: {_liq_e}")

            # ── 🧭 Investment Thesis (Phase A1 — structured, rules-based, NO AI) ──
            st.markdown("---")
            st.subheader("🧭 Investment Thesis (structured)")
            st.caption(
                "Rules-based synthesis of the signals above — Bull / Bear / Risks with a "
                "single verdict. Every point is traceable to its source. Not investment advice."
            )
            try:
                from analysis.thesis import generate_thesis, build_inputs
                _th = generate_thesis(build_inputs(ticker, composite=cs, deep=_dc,
                                                   liquidity=_liq_ctx))

                _v_color = {"Strong Positive": "#00d4aa", "Positive": "#2ecc71",
                            "Neutral": "#8899bb", "Negative": "#ff7043",
                            "Strong Negative": "#ff4757"}.get(_th.verdict, "#8899bb")
                st.markdown(
                    f"<div style='font-size:1.15rem'>Verdict: "
                    f"<b style='color:{_v_color}'>{_th.verdict}</b> "
                    f"<span style='color:#8899bb'>(score {_th.verdict_score:+d})</span></div>",
                    unsafe_allow_html=True,
                )
                st.caption(_th.verdict_rationale)

                def _factor_list(_factors, _empty):
                    if not _factors:
                        st.caption(_empty)
                        return
                    for _f in _factors:
                        st.markdown(
                            f"- {_f.text}  \n"
                            f"  <span style='color:#8899bb;font-size:0.85rem'>"
                            f"· {_f.source}: {_f.evidence}</span>",
                            unsafe_allow_html=True,
                        )

                _tc1, _tc2 = st.columns(2)
                with _tc1:
                    st.markdown("**🟢 Bull case**")
                    _factor_list(_th.bull_factors, "No bull factors triggered.")
                with _tc2:
                    st.markdown("**🔴 Bear case**")
                    _factor_list(_th.bear_factors, "No bear factors triggered.")

                st.markdown("**⚠️ Key risks**")
                _factor_list(_th.key_risks, "No specific risks flagged by the rules.")

                for _tn in getattr(_th, "notes", []) or []:
                    st.info("ℹ️ " + _tn)

                st.caption(
                    "Contributing subsystems: "
                    + (", ".join(_th.inputs_present) or "none available")
                    + ". Phase A1/D1 — explainable, sector-aware rules; no AI/LLM narration."
                )
            except Exception as _th_e:
                _th = None
                st.caption(f"⚠️ Thesis unavailable: {_th_e}")

            # ── 🧩 Portfolio Fit Assessment (Phase B — rules-based, NO AI) ──────
            st.markdown("---")
            st.subheader("🧩 Portfolio Fit Assessment")
            st.caption(
                "Is this a good *addition* to your current book? Marginal impact on "
                "diversification, sector mix, beta and concentration. Not investment advice."
            )
            try:
                import pandas as _pf_pd, pathlib as _pf_pl
                _pf_csv = st.session_state.get("_ao_portfolio_path") \
                    or (_pf_pl.Path(_ROOT) / "portfolio.csv")
                _pf_holds = []
                if _pf_csv and _pf_pl.Path(_pf_csv).exists():
                    _pf_df = _pf_pd.read_csv(_pf_csv)
                    for _, _r in _pf_df.iterrows():
                        _t = str(_r.get("ticker", "")).strip()
                        if _t and not _t.upper().endswith(".NS"):
                            _t = _t + ".NS"
                        _q = float(_r.get("quantity", 0) or 0)
                        if _t and _q > 0:
                            _pf_holds.append({"ticker": _t, "quantity": _q})

                if not _pf_holds:
                    st.info("No portfolio found — add holdings on the **📂 My Portfolio** page "
                            "to see how this stock would fit your book.")
                else:
                    from analysis.thesis import build_fit_inputs, assess_fit
                    with st.spinner("Assessing fit against your portfolio…"):
                        _fit = assess_fit(build_fit_inputs(
                            ticker, _pf_holds, candidate_thesis=_th))

                    _fr_color = {"Strong Fit": "#00d4aa", "Fit": "#2ecc71",
                                 "Neutral": "#8899bb", "Poor Fit": "#ff7043",
                                 "Strong Conflict": "#ff4757"}.get(_fit.fit_rating, "#8899bb")
                    st.markdown(
                        f"<div style='font-size:1.15rem'>Fit rating: "
                        f"<b style='color:{_fr_color}'>{_fit.fit_rating}</b> "
                        f"<span style='color:#8899bb'>(score {_fit.fit_score:+d})</span></div>",
                        unsafe_allow_html=True,
                    )
                    _im1, _im2 = st.columns(2)
                    _im1.caption("📊 " + _fit.diversification_impact)
                    _im1.caption("🏭 " + _fit.sector_impact)
                    _im2.caption("📈 " + _fit.beta_impact)
                    _im2.caption("⚖️ " + _fit.concentration_impact)

                    def _fit_list(_factors, _empty):
                        if not _factors:
                            st.caption(_empty)
                            return
                        for _f in _factors:
                            st.markdown(
                                f"- {_f.text}  \n"
                                f"  <span style='color:#8899bb;font-size:0.85rem'>"
                                f"· {_f.source}: {_f.evidence}</span>",
                                unsafe_allow_html=True,
                            )

                    _fp, _fn = st.columns(2)
                    with _fp:
                        st.markdown("**✅ Positive effects**")
                        _fit_list(_fit.positive_effects, "No positive effects flagged.")
                    with _fn:
                        st.markdown("**❌ Negative effects**")
                        _fit_list(_fit.negative_effects, "No negative effects flagged.")

                    _ps_color = {"Large": "#00d4aa", "Moderate": "#ffa726",
                                 "Small": "#ff7043"}.get(_fit.position_size_guidance, "#8899bb")
                    st.markdown(
                        f"**Position size guidance:** "
                        f"<b style='color:{_ps_color}'>{_fit.position_size_guidance}</b>",
                        unsafe_allow_html=True,
                    )
                    st.caption(_fit.position_size_reason)
                    st.caption(
                        "Contributing subsystems: "
                        + (", ".join(_fit.inputs_present) or "none")
                        + ". Phase B — rules only, no buy/sell recommendation, no target price."
                    )
            except Exception as _pf_e:
                st.caption(f"⚠️ Portfolio fit unavailable: {_pf_e}")

        except Exception as e:
            st.error(f"Analysis failed: {e}")
            import traceback
            st.code(traceback.format_exc())


# ═══════════════════════════════════════════════════════════════════════════════
# PAGE 3 — MARKET OVERVIEW
# ═══════════════════════════════════════════════════════════════════════════════
