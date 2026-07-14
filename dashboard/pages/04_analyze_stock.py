"""Analyze Stock - NSE Smart Investor (multipage page; body verbatim from app.py).

FIXES applied in this revision
───────────────────────────────
A1  "Paper Trade This Signal" bottom button replaced with _paper_trade_popover()
    so it gets the account selector, live-price re-anchor, qty override and
    proper R:R display — identical to every other paper trade button in the app.
    The old direct paper_open_trade() call with hardcoded qty=int(10000/entry)
    is gone.

A2  Live drift caption now gated on _ms_an.get("is_open") — the warning
    "Live ₹X vs analysis ₹X" no longer fires when the market is closed (Yahoo
    returns last EOD close as "live" outside hours, making the drift spurious).

A3  Conviction score now guards against _dc["total"] being None or 0. If
    deep confirmation is unavailable the conviction section shows
    "confirmation unavailable" and skips the adjustment rather than silently
    arithmetic-ing on a phantom 9.

A4  Earnings date label now handles negative _ed_days (results already
    announced) with an explicit branch: "Results Xd ago" in teal/gray,
    rather than falling through to the confusing "Unknown / gray" bucket.

A5  Portfolio fit CSV loading is now wrapped in @st.cache_data(ttl=300)
    keyed on file path + mtime so re-reading the CSV on every widget
    interaction is avoided.

A6  Sector rank metric guard: f"#{cs.sector_rank}" is now
    f"#{cs.sector_rank}" if cs.sector_rank else "—" to prevent "#None".

A7  df.iloc[-2] is now guarded with len(df) >= 2 to avoid IndexError on
    single-row dataframes (new listings, data gaps).

A8  Ticker handoff from My Portfolio (or anywhere else) via
    st.session_state["analyze_ticker"] is now actually consumed. Previously
    My Portfolio's "📊 Analyze" button set this key and navigated here, but
    this page never read it — so the search box stayed empty and the user
    had to manually retype the ticker. The prefilled ticker now forces the
    analysis to run immediately on arrival, and the session key is popped
    so it doesn't keep re-forcing on subsequent manual interactions.

A9  Portfolio Fit holdings source now reads load_manual_holdings() instead
    of a portfolio.csv path / Angel One tmp path, matching the My Portfolio
    page's move away from file-based holdings to manual entry.
"""

import os
import sys
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import streamlit as st

from analysis.fundamentals.service import default_service as _fund_service
from analysis.fundamentals import analytics as _fund_analytics

from dashboard.shared.design import apply_design
from dashboard.shared.nav import render_sidebar
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
    _display_label,            # Phase 2 UI honesty
    _grade_color,
    _paper_trade_popover,      # FIX A1: use popover instead of direct call
    load_manual_holdings,      # FIX A9: manual holdings replace CSV/Angel One path
)
from dashboard.shared.chart_helpers import (
    build_price_chart,
    render_top_bar,
)
from dashboard.shared.flags_ui import render_flag_strip  # QF2: qualitative flags panel

apply_design()
render_sidebar(current="Analyze Stock")
render_top_bar()

# ─────────────────────────────────────────────────────────────────────────────
st.title("🔍 Analyze Any NSE Stock")
st.markdown(
    "Search by company name or ticker — get a full **trend-quality score**, "
    "chart, stop-loss, and plain-English read of the setup."
)

from dashboard.shared.disclosures import (
    render_score_methodology as _render_score_methodology,
    render_regime_reliability_note as _render_regime_note,
)
_render_regime_note()
_render_score_methodology()

# FIX A8: consume a ticker handed off from My Portfolio (or elsewhere) via
# session_state — must happen BEFORE the search widgets render so the
# selectbox/text_input default values stay untouched (we don't fight the
# widget state, we just override the *resolved* ticker and force the run).
_prefill_ticker = st.session_state.pop("analyze_ticker", None)
_prefill_active = bool(_prefill_ticker)

# ── Stock search ───────────────────────────────────────────────────────────
search_options = [
    f"{name}  ({sym.replace('.NS','')})"
    for name, sym in STOCK_SEARCH_MAP.items()
]
search_options_sorted = sorted(search_options)

_AS_PERIOD_MAP = {
    "1D": "1d", "5D": "5d", "1M": "1m",
    "6M": "6m", "YTD": "ytd", "Max": "max",
}
_AS_PLACEHOLDER = "— type to search —"

# BUGFIX: the dropdown and the manual ticker box were independent widgets
# with no relationship — picking a dropdown stock left old text sitting in
# the manual box (which silently took priority below), and typing a manual
# ticker left the dropdown showing a stale company name. Neither cleared on
# its own, so switching between the two required manually wiping whichever
# field you weren't using. These on_change callbacks make using one field
# automatically clear the other, and the explicit "✖ Clear" button below
# resets both at once.
#
# The clear-pending flag (rather than writing the widget keys directly from
# the button block) is required because Streamlit raises
# "cannot be modified after the widget ... is instantiated" if you assign to
# st.session_state for a widget's key anywhere after that widget has already
# been created in the same script run — and the Clear button sits below the
# selectbox/text_input in this layout. Setting a flag + st.rerun() defers the
# actual reset to the top of the next run, before either widget exists yet.
if st.session_state.pop("_as_clear_pending", False):
    st.session_state["stock_search_select"] = _AS_PLACEHOLDER
    st.session_state["manual_ticker_input"] = ""

def _as_on_dropdown_change():
    if st.session_state.get("stock_search_select", _AS_PLACEHOLDER) != _AS_PLACEHOLDER:
        st.session_state["manual_ticker_input"] = ""

def _as_on_manual_change():
    if st.session_state.get("manual_ticker_input", "").strip():
        st.session_state["stock_search_select"] = _AS_PLACEHOLDER

col_search, col_manual, col_clear, col_btn = st.columns([3, 2, 1, 1])
with col_search:
    selected_option = st.selectbox(
        "Search by company name or symbol",
        options=[_AS_PLACEHOLDER] + search_options_sorted,
        index=0,
        key="stock_search_select",
        on_change=_as_on_dropdown_change,
    )
with col_manual:
    manual_ticker = st.text_input(
        "Or type ticker directly",
        value="",
        placeholder="e.g. INFY or INFY.NS",
        key="manual_ticker_input",
        on_change=_as_on_manual_change,
    ).strip().upper()
with col_clear:
    st.write("")
    st.write("")
    if st.button("✖ Clear", key="as_clear_search", width="stretch"):
        st.session_state["_as_clear_pending"] = True
        st.rerun()
with col_btn:
    st.write("")
    st.write("")
    analyze_btn = st.button("🔍 Analyze", type="primary", key="analyze_btn")

if _prefill_active:
    st.caption(f"📥 Opened from My Portfolio — analyzing **{_prefill_ticker.replace('.NS','')}**.")

_ui_period = st.radio(
    "Chart period",
    list(_AS_PERIOD_MAP.keys()),
    index=3,
    horizontal=True,
    key="analyze_period",
)
period = _AS_PERIOD_MAP[_ui_period]

_mt_clean, _mt_err = _validate_ticker(manual_ticker)
if _mt_err:
    st.error(f"⚠️ {_mt_err}")
    st.stop()

ticker = ""
if _prefill_active:
    # FIX A8: a handed-off ticker always wins over stale widget state
    ticker = _prefill_ticker if _prefill_ticker.endswith(".NS") else _prefill_ticker + ".NS"
elif _mt_clean:
    ticker = _mt_clean + ".NS"
elif selected_option != _AS_PLACEHOLDER:
    raw_sym = selected_option.rsplit("(", 1)[-1].rstrip(")")
    ticker  = raw_sym + ".NS" if not raw_sym.endswith(".NS") else raw_sym

if not ticker:
    # FIX A9: fall back to whatever was last analyzed, instead of jumping
    # straight to the RELIANCE.NS default. This is required once the search
    # boxes auto-clear right after a successful Analyze (see FIX A9 below)
    # — without this fallback, the very next rerun after that (e.g. just
    # changing the chart period) would find both search widgets empty,
    # resolve to RELIANCE.NS, and silently swap away from the stock the
    # person just looked up.
    ticker = st.session_state.get("last_analyzed") or "RELIANCE.NS"

if analyze_btn or _prefill_active or (
    "last_analyzed" in st.session_state
    and st.session_state.last_analyzed == ticker
):
    st.session_state.last_analyzed = ticker

    if analyze_btn:
        # FIX A9: the search boxes only ever cleared when explicitly
        # switching fields or clicking "✖ Clear" — never after actually
        # using them. Every time someone finished analyzing one stock,
        # the manual box still held the old ticker, so typing the next
        # search meant deleting the old text first. Clearing here, right
        # when Analyze is clicked, fixes that. get_composite_score is
        # cached, so recomputing for the same ticker on the next rerun
        # (see the FIX A9 fallback above) is cheap — the immediate
        # st.rerun() is required because the search widgets were already
        # instantiated earlier in *this* run, so they can't be blanked
        # until the top of the *next* run (the "_as_clear_pending" block
        # near the top of this file consumes the flag right before the
        # widgets are created).
        st.session_state["_as_clear_pending"] = True
        st.rerun()

    with st.spinner(f"Scoring {ticker}…"):
        try:
            cs = get_composite_score(ticker)

            # BUGFIX: get_composite_score() already catches fetch failures
            # internally and returns an UNAVAILABLE sentinel rather than
            # raising — but this page never checked for it, so execution kept
            # going straight into load_ticker_df(ticker) below, which has no
            # such protection and raises a raw
            # "ValueError: No data for X.NS. All sources failed: [...]" that
            # fell through to the generic exception handler at the bottom,
            # dumping a Python traceback at the user. An invalid/misspelled
            # ticker now gets a plain, friendly message and stops here.
            if cs.action == "UNAVAILABLE":
                st.error(
                    f"❌ **Couldn't find '{ticker.replace('.NS','')}' on NSE.** "
                    "Double-check the spelling, or search by company name above "
                    "(e.g. RELIANCE, INFY, TCS)."
                )
                st.stop()

            # Live price
            _an_live = None
            try:
                from utils.live_price import get_live_quote as _an_lq
                _anq = _an_lq(ticker)
                if isinstance(_anq, dict) and _anq.get("price"):
                    _an_live = float(_anq["price"])
            except Exception as _lq_e:
                import logging; logging.getLogger("dashboard.analyze_stock").debug("Live quote fetch failed for %s: %s", ticker, _lq_e)
            _an_drift = (
                abs(_an_live - cs.price) / cs.price * 100
                if (_an_live and cs.price)
                else 0.0
            )

            df = load_ticker_df(ticker)

            # FIX A7: guard against single-row dataframe (new listings / data gaps)
            if len(df) < 2:
                st.error(
                    f"⚠️ Insufficient price history for **{ticker.replace('.NS','')}** "
                    f"({len(df)} row(s) returned). The stock may be newly listed or "
                    "data is temporarily unavailable. Try again later."
                )
                st.stop()

            df_chart = _trim_to_period(df, period)

            # Revenue growth chip
            _rg_val, _rg_conf = None, ""
            try:
                _rg_cf  = _fund_service().get_fundamentals(ticker)
                if _rg_cf is not None:
                    _rg_res = _fund_analytics.revenue_cagr(_rg_cf, years=5)
                    if getattr(_rg_res, "available", False) and _rg_res.value is not None:
                        _rg_val  = float(_rg_res.value)
                        _rg_conf = str(_rg_res.confidence)
            except Exception as _rg_e:
                import logging; logging.getLogger("dashboard.analyze_stock").debug("Revenue growth fetch failed for %s: %s", ticker, _rg_e)

            # ── Score hero section ─────────────────────────────────────────
            st.markdown("---")
            hero_col, detail_col = st.columns([1, 2])

            with hero_col:
                grade_c = _grade_color(cs.grade)
                card_c  = _action_color(cs.action)
                emoji   = _action_emoji(cs.action)
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
                    unsafe_allow_html=True,
                )
                st.markdown("")
                score_breakdown = {
                    "Technical (40)": cs.technical_score,
                    "Momentum (25)":  cs.momentum_score,
                    "Volume (15)":    cs.volume_score,
                    "Sentiment (10)": cs.sentiment_score,
                }
                for label, val in score_breakdown.items():
                    _max = {"Technical (40)": 40, "Momentum (25)": 25,
                            "Volume (15)": 15,    "Sentiment (10)": 10}[label]
                    pct       = val / _max * 100
                    bar_color = "#26a69a" if pct >= 60 else "#f9a825" if pct >= 35 else "#ef5350"
                    st.markdown(
                        f'<div style="display:flex;align-items:center;margin:3px 0;">'
                        f'<span style="width:160px;font-size:12px;color:#ccc">{label}</span>'
                        f'<div style="flex:1;background:#333;border-radius:4px;height:10px">'
                        f'<div style="width:{pct:.0f}%;background:{bar_color};'
                        f'border-radius:4px;height:10px"></div></div>'
                        f'<span style="width:42px;text-align:right;font-size:12px;color:#ccc">'
                        f'{val:.0f}</span></div>',
                        unsafe_allow_html=True,
                    )

            with detail_col:
                latest  = df.iloc[-1]
                prev    = df.iloc[-2]   # safe — len(df) >= 2 guarded above
                day_chg = (latest["Close"] / prev["Close"] - 1) * 100

                _disp_price = _an_live if _an_live else cs.price
                mc1, mc2, mc3, mc4, mc5 = st.columns(5)
                mc1.metric(
                    "Price (live)" if _an_live else "Close",
                    f"₹{_disp_price:,.2f}", f"{day_chg:+.2f}%",
                )
                mc2.metric("Sector",      cs.sector)
                mc3.metric("VIX Regime",  cs.vix_regime)
                # FIX A6: guard against cs.sector_rank being None
                mc4.metric(
                    "Sector Rank",
                    f"#{cs.sector_rank}" if cs.sector_rank else "—",
                )
                mc5.metric(
                    "Rev Growth /yr",
                    f"{_rg_val:+.1f}%" if _rg_val is not None else "—",
                    help=(
                        "Annualised revenue growth from audited statements"
                        + (f" · confidence: {_rg_conf}" if _rg_conf else "")
                        + ". The strongest return-linked metric in platform "
                          "research (2022–2025) — a measured observation, "
                          "not a buy signal."
                    ),
                )
                if _rg_val is not None:
                    from dashboard.shared.disclosures import (
                        render_revenue_growth_evidence as _rg_evidence,
                    )
                    _rg_evidence()

                # FIX A2: live drift caption only fires when market is actually open
                try:
                    from utils.market_hours import market_status as _an_ms
                    _ms_an = _an_ms()
                    try:
                        _dlabel = df.index[-1].strftime("%d-%b")
                    except Exception:
                        _dlabel = ""
                    if _ms_an.get("is_open") and _an_live and _an_drift >= 0.5:
                        # FIX A2: only warn about drift during live market hours
                        st.caption(
                            f"ℹ️ Live price **₹{_an_live:,.2f}** · indicators & levels "
                            f"computed on the last daily close **₹{cs.price:,.2f}**"
                            f"{f' ({_dlabel})' if _dlabel else ''} "
                            f"— {_an_drift:.1f}% apart, treat entry/target as a guide."
                        )
                    elif _ms_an.get("is_open"):
                        st.caption(
                            "🔴 LIVE · market open — official close settles after 3:30 PM."
                        )
                    else:
                        st.caption(
                            f"🟢 Settled EOD close{f' · {_dlabel}' if _dlabel else ''} "
                            "(market closed — official end-of-day price)."
                        )
                except Exception as _ms_e:
                    import logging; logging.getLogger("dashboard.analyze_stock").debug("Market status check failed: %s", _ms_e)

                tc1, tc2, tc3, tc4 = st.columns(4)
                tc1.metric("Entry (now)", f"₹{cs.entry:,.2f}")
                tc2.metric(
                    "Stop-Loss", f"₹{cs.stop_loss:,.2f}",
                    f"-{(cs.price - cs.stop_loss)/cs.price*100:.1f}%",
                    delta_color="inverse",
                )
                tc3.metric(
                    "Target", f"₹{cs.target:,.2f}",
                    f"+{(cs.target - cs.price)/cs.price*100:.1f}%",
                )
                tc4.metric("Risk : Reward", f"{cs.risk_reward:.1f} : 1")

                # FIX HZ1: holding period this setup was scored for — was
                # missing entirely, making the action label ("BUY" etc.) an
                # open-ended idea with no sense of when to reassess.
                if getattr(cs, "horizon", ""):
                    st.caption(
                        f"⏱ **Horizon:** {cs.horizon}"
                        + (f" — reassess after **{cs.valid_until}**" if getattr(cs, "valid_until", "") else "")
                    )

                st.markdown(
                    f'<div class="{_action_color(cs.action)}">'
                    f'<b style="font-size:16px">{cs.headline}</b><br><br>'
                    f'<span class="narrative">{cs.narrative}</span>'
                    f'</div>',
                    unsafe_allow_html=True,
                )

            # ── Qualitative flags (QF2) ─────────────────────────────────────
            # Deliberately full-width, outside hero_col/detail_col, and
            # deliberately AFTER the score card — this is context alongside
            # the score, never blended into cs.score itself.
            try:
                render_flag_strip(ticker)
            except Exception as _qf_e:
                import logging
                logging.getLogger("dashboard.analyze_stock").debug(
                    "Qualitative flags panel failed for %s: %s", ticker, _qf_e
                )

            # ── Action strip ───────────────────────────────────────────────
            _as_colors = {
                "BUY":          ("#0a2a1a", "#26a69a"),
                "CAUTIOUS BUY": ("#0d2210", "#4caf50"),
                "HOLD":         ("#2a2a00", "#f9a825"),
                "WATCHLIST":    ("#0d1f3c", "#2196F3"),
                "EXIT":         ("#2a0a0a", "#ef5350"),
            }
            _as_bg, _as_border = _as_colors.get(cs.action, ("#1a1a2e", "#2196F3"))
            _as_rr_ok    = cs.risk_reward >= 1.5
            _as_rr_color = "#26a69a" if _as_rr_ok else "#f9a825"

            st.markdown(
                f'<div style="background:{_as_bg};border-left:6px solid {_as_border};'
                f'border-radius:8px;padding:16px 22px;margin:14px 0 6px 0">'
                f'<span style="font-size:22px;font-weight:700">'
                f'{_action_emoji(cs.action)} Signal: '
                f'<span style="color:{_as_border}">{_display_label(cs.action)}</span></span>'
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

            st.markdown(
                f'<div class="glass-panel" style="margin:8px 0 14px 0;padding:14px 18px">'
                f'<div style="font-size:11px;color:#ff9500;font-weight:700;'
                f'text-transform:uppercase;letter-spacing:1px;margin-bottom:6px">💬 In plain English</div>'
                f'<div style="font-size:14px;line-height:1.7;color:#e0e0e0">'
                f'{_plain_english(cs.action, cs.entry, cs.stop_loss, cs.target, cs.risk_reward)}'
                f'</div></div>',
                unsafe_allow_html=True,
            )

            # ── Multi-signal confirmation ──────────────────────────────────
            with st.spinner("Running deep confirmation…"):
                _dc = _deep_confirmation(ticker)

            _wk_map = {
                "uptrend":  ("🟢 Uptrend",  "#00d4aa"),
                "downtrend":("🔴 Downtrend","#ff4757"),
                "sideways": ("🟡 Sideways", "#ff9500"),
                None:       ("—",           "#8899bb"),
            }
            _wk_txt, _wk_c = _wk_map.get(_dc["weekly"], ("—", "#8899bb"))
            _rs_c   = "#00d4aa" if (_dc["rs_pct"] or 0) > 0 else "#ff4757"
            _rs_txt = (
                f'{_dc["rel_strength"].title()} ({_dc["rs_pct"]:+.1f}% vs Nifty)'
                if _dc["rel_strength"]
                else "—"
            )

            # FIX A4: handle negative _ed_days (results already announced)
            _ed_days = _dc["earnings_days"]
            if _ed_days is not None and _ed_days < 0:
                _ed_txt = f"Results {abs(_ed_days)}d ago"
                _ed_c   = "#8899bb"                            # neutral — event passed
            elif _ed_days is not None and 0 <= _ed_days <= 7:
                _ed_txt = f"⚠️ Results in {_ed_days}d — avoid fresh buys"
                _ed_c   = "#ff4757"
            elif _ed_days is not None and 0 <= _ed_days <= 21:
                _ed_txt = f"Results in {_ed_days}d"
                _ed_c   = "#ff9500"
            elif _ed_days is not None:
                _ed_txt = f"Results in {_ed_days}d (clear)"
                _ed_c   = "#00d4aa"
            else:
                _ed_txt = "Unknown"
                _ed_c   = "#8899bb"

            # FIX A3: guard against _dc["total"] being None or 0
            _bull = _dc.get("bull", 0)
            _tot  = _dc.get("total") or 0
            _confirmation_available = _tot > 0

            # Conviction score
            _conf_delta, _conf_reasons = 0, []
            if _confirmation_available:
                _agr_pct = _bull / _tot * 100
                _agr_c   = "#00d4aa" if _agr_pct >= 67 else "#ff9500" if _agr_pct >= 40 else "#ff4757"

                if _dc["weekly"] == "uptrend":
                    _conf_delta += 4;  _conf_reasons.append("+4 weekly uptrend")
                elif _dc["weekly"] == "downtrend":
                    _conf_delta -= 6;  _conf_reasons.append("−6 weekly downtrend")
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
                _conf_delta = max(-15, min(15, _conf_delta))
                _conviction = max(0, min(100, cs.score + _conf_delta))
            else:
                # FIX A3: confirmation unavailable — use raw score, no adjustment
                _agr_pct    = 0
                _agr_c      = "#8899bb"
                _conviction = cs.score
                _conf_delta = 0

            _cv_c    = "#00d4aa" if _conviction >= 65 else "#ff9500" if _conviction >= 45 else "#ff4757"
            _delta_c = "#00d4aa" if _conf_delta >= 0 else "#ff4757"
            _delta_s = f"{_conf_delta:+d}" if _conf_delta else "±0"

            st.markdown(
                f'<div style="background:#0d1526;border:1px solid rgba(255,255,255,.06);'
                f'border-radius:12px;padding:14px 18px;margin-bottom:12px">'
                f'<div style="font-size:11px;color:#5b8def;font-weight:700;'
                f'text-transform:uppercase;letter-spacing:1px;margin-bottom:10px">'
                f'🔬 Multi-Signal Confirmation</div>'
                f'<div style="display:flex;gap:22px;flex-wrap:wrap;align-items:flex-start">'
                # Conviction score
                f'<div style="border-right:1px solid rgba(255,255,255,.08);padding-right:18px">'
                f'<div style="font-size:10px;color:#4a5568">CONVICTION</div>'
                f'<div style="font-size:24px;font-weight:800;color:{_cv_c}">{_conviction:.0f}'
                f'<span style="font-size:12px;color:#8899bb"> /100</span></div>'
                + (
                    f'<div style="font-size:10px;color:{_delta_c}">base {cs.score:.0f} · {_delta_s} confirmation</div>'
                    if _confirmation_available
                    else '<div style="font-size:10px;color:#8899bb">confirmation unavailable</div>'
                ) +
                f'</div>'
                f'<div><div style="font-size:10px;color:#4a5568">WEEKLY TREND</div>'
                f'<div style="font-size:14px;font-weight:700;color:{_wk_c}">{_wk_txt}</div></div>'
                f'<div><div style="font-size:10px;color:#4a5568">RELATIVE STRENGTH</div>'
                f'<div style="font-size:14px;font-weight:700;color:{_rs_c}">{_rs_txt}</div></div>'
                f'<div><div style="font-size:10px;color:#4a5568">EARNINGS</div>'
                f'<div style="font-size:14px;font-weight:700;color:{_ed_c}">{_ed_txt}</div></div>'
                f'<div><div style="font-size:10px;color:#4a5568">SIGNAL AGREEMENT</div>'
                f'<div style="font-size:14px;font-weight:700;color:{_agr_c}">'
                + (f'{_bull} of {_tot} bullish' if _confirmation_available else '—') +
                f'</div></div>'
                f'</div>'
                + (
                    f'<div style="font-size:11px;color:#8899bb;margin-top:8px">'
                    f'Conviction adjustments: {" · ".join(_conf_reasons)}</div>'
                    if _conf_reasons
                    else (
                        '<div style="font-size:11px;color:#8899bb;margin-top:8px">'
                        'No adjustment — confirmation signals are neutral.</div>'
                        if _confirmation_available
                        else
                        '<div style="font-size:11px;color:#8899bb;margin-top:8px">'
                        'Deep confirmation unavailable — conviction equals base score.</div>'
                    )
                )
                + "</div>",
                unsafe_allow_html=True,
            )

            # Signal checklist
            if _confirmation_available:
                with st.expander(f"🔎 See all {_tot} signals", expanded=False):
                    for _sname, _sok in _dc.get("signals", []):
                        st.markdown(
                            f'<div style="font-size:13px;color:#ccc;padding:2px 0">'
                            f'{"🟢" if _sok else "⚪"} {_sname}</div>',
                            unsafe_allow_html=True,
                        )

            _as_c1, _as_c2, _as_c3, _as_c4 = st.columns([1, 1, 1, 3])
            if _as_c1.button("➕ Watchlist", key=f"as_wl_{ticker}", width="stretch"):
                _wl = st.session_state.setdefault("watchlist", [])
                if ticker not in _wl:
                    _wl.append(ticker)
                st.toast(f"{ticker.replace('.NS','')} added to watchlist ✓")
            if _as_c2.button("📝 Paper Trade", key=f"as_pt_{ticker}", width="stretch"):
                st.session_state["_goto_page"]        = "📂 Paper Trades"
                st.session_state["pt_prefill_ticker"] = ticker
                st.rerun()
            if _as_c3.button("🔄 Re-Analyze", key=f"as_re_{ticker}", width="stretch"):
                # FIX MKT3: was a blanket st.cache_data.clear() — wiped every
                # other page's cached data too (Top Picks, watchlist scans,
                # etc.), not just this ticker's analysis. load_ticker_df is
                # already imported at the top of this module, so it's safe
                # to clear directly here.
                load_ticker_df.clear()
                st.rerun()

            # ── Technical indicators ───────────────────────────────────────
            st.markdown("---")
            ti_cols = st.columns(6)
            indicators_display = [
                ("RSI (14)",  f"{latest.get('RSI', 0):.1f}",
                 "Oversold (<30)"   if latest.get("RSI", 50) < 30
                 else "Overbought (>70)" if latest.get("RSI", 50) > 70
                 else "Normal"),
                ("ADX",       f"{latest.get('ADX', 0):.1f}",
                 "Trending (>25)" if latest.get("ADX", 0) > 25 else "Ranging"),
                ("ATR",       f"₹{latest.get('ATR', 0):.1f}", "Daily move range"),
                ("Vol Ratio", f"{latest.get('Volume_Ratio', 0):.2f}x",
                 "High volume" if latest.get("Volume_Ratio", 1) > 1.5 else "Normal"),
                ("Stoch K",   f"{latest.get('Stoch_K', 50):.1f}",
                 "Oversold" if latest.get("Stoch_K", 50) < 20
                 else "Overbought" if latest.get("Stoch_K", 50) > 80 else ""),
                ("VWAP %",   f"{latest.get('VWAP_Pct', 0):+.1f}%",
                 "Above VWAP" if latest.get("VWAP_Pct", 0) > 0 else "Below VWAP"),
            ]
            for (lbl, val, note), col in zip(indicators_display, ti_cols):
                col.metric(lbl, val, note)

            pat_cols   = [c for c in df.columns if c.startswith("Pat_")]
            active_pats = [
                c.replace("Pat_", "").replace("_", " ")
                for c in pat_cols if latest.get(c, 0) == 1
            ]
            if active_pats:
                st.info(f"📍 **Candlestick signals today:** {', '.join(active_pats)}")

            if latest.get("RSI_Bull_Div", 0):
                st.success("📈 **Bullish RSI Divergence detected** — momentum improving despite lower price")
            if latest.get("RSI_Bear_Div", 0):
                st.warning("📉 **Bearish RSI Divergence detected** — momentum fading despite higher price")

            # ── Chart ──────────────────────────────────────────────────────
            st.markdown("---")
            st.subheader("📊 Price Chart")
            st.plotly_chart(build_price_chart(df_chart, ticker), width="stretch")

            # ── News feed ──────────────────────────────────────────────────
            st.markdown("---")
            st.subheader(f"📰 Latest News — {get_display_name(ticker)}")
            with st.spinner("Loading news…"):
                from utils.news import get_stock_news as _gsn
                articles = _gsn(ticker, max_articles=6)
            if articles:
                for art in articles:
                    s      = art["sentiment"]
                    icon   = "🟢" if s == "positive" else ("🔴" if s == "negative" else "⚪")
                    impact = (
                        "Positive catalyst" if s == "positive"
                        else "Negative signal" if s == "negative"
                        else "Neutral update"
                    )
                    st.markdown(
                        f'{icon} **[{art["title"]}]({art["link"]})**  \n'
                        f'<span style="font-size:11px;color:#aaa">'
                        f'{art["publisher"]} · {art["time"]} · *{impact}*</span>',
                        unsafe_allow_html=True,
                    )
            else:
                st.info("No recent news found for this stock.")

            # ── Trading summary box ────────────────────────────────────────
            st.markdown("---")
            action_c = _action_color(cs.action)
            atr      = float(df["ATR"].iloc[-1]) if "ATR" in df.columns else cs.price * 0.02
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
                f'<span style="color:#aaa;font-size:12px">(R:R = {cs.risk_reward:.1f}:1)</span><br><br>'
                f'<i>{cs.headline}</i>'
                f'</div>',
                unsafe_allow_html=True,
            )

            # ── FIX A1: Paper trade via popover (was direct paper_open_trade call) ──
            st.markdown("---")
            _pbt_col, _pbt_info = st.columns([1, 3])
            with _pbt_col:
                _paper_trade_popover(
                    ticker,
                    entry   = cs.entry,
                    sl      = cs.stop_loss,
                    tp      = cs.target,
                    reason  = f"{cs.action} score={cs.score:.0f}: {cs.headline}",
                    key     = f"as_ptpop_{ticker}",
                    label   = "📌 Paper Trade This Signal",
                )
            with _pbt_info:
                st.info(
                    "📌 **Paper Trading** lets you test this signal without real money. "
                    "Track it in the **📂 Paper Trades** page to see if the model's calls are accurate."
                )

            # ── Fundamentals ───────────────────────────────────────────────
            st.markdown("---")
            st.subheader("📊 Fundamentals")
            try:
                import datetime as _f_dt
                _f_cf  = _fund_service().get_fundamentals(ticker)
                _f_res = _fund_analytics.compute_all(_f_cf, cagr_years=5)
                _f_fresh = "—"
                if _f_cf.last_updated:
                    _f_hrs   = (_f_dt.datetime.now() - _f_cf.last_updated).total_seconds() / 3600
                    _f_fresh = "just now" if _f_hrs < 1 else f"{_f_hrs:.0f}h ago"
                st.caption(
                    f"Provider: **{_f_cf.provider_name or '—'}**  ·  "
                    f"Statement date: **{_f_cf.statement_date or '—'}**  ·  "
                    f"Data freshness: **{_f_fresh}**"
                )
                if _f_cf.is_partial:
                    st.warning(
                        f"⚠️ **Partial data** — some fundamentals are unavailable for this stock "
                        f"from {_f_cf.provider_name or 'the provider'}. "
                        f"Missing: {', '.join(_f_cf.missing_fields) or 'n/a'}."
                    )

                def _f_show(_col, _r):
                    if _r.available and _r.value is not None:
                        _txt = f"{_r.value:,.1f}%" if _r.unit == "%" else f"{_r.value:,.2f}x"
                        _col.metric(_r.metric, _txt)
                        _col.caption(
                            f"confidence: {_r.confidence}"
                            + (f" · {_r.reason}" if _r.reason else "")
                        )
                    else:
                        _col.metric(_r.metric, "N/A")
                        _col.caption(f"⚠️ {_r.reason}")

                _fc1, _fc2, _fc3, _fc4 = st.columns(4)
                _f_show(_fc1, _f_res["revenue_cagr"])
                _f_show(_fc2, _f_res["eps_cagr"])
                _f_show(_fc3, _f_res["roe"])
                _f_show(_fc4, _f_res["debt_to_equity"])

                from dashboard.shared.disclosures import (
                    render_revenue_growth_evidence as _f_rg_evidence,
                )
                _f_rg_evidence()

                _cagr_results = [
                    r for r in [_f_res.get("revenue_cagr"), _f_res.get("eps_cagr")]
                    if r is not None and getattr(r, "available", False)
                ]
                if _cagr_results and any(r.confidence in ("medium", "low") for r in _cagr_results):
                    st.caption(
                        "📊 **Data depth note:** CAGR confidence reflects Yahoo Finance's "
                        "available history (~4–5 years for most NSE names). "
                        "\"Medium\" confidence means the trend is directionally reliable "
                        "but not enough history exists for statistical certainty."
                    )

                from analysis.sector_classification import classify_sector as _classify
                _sp = _classify(
                    getattr(cs, "sector", None),
                    name=getattr(cs, "company_name", None),
                )
                if _sp.is_financial:
                    st.info(f"🏦 **{_sp.group}** — {_sp.note}")
                else:
                    _rc1, _rc2 = st.columns(2)
                    _f_show(_rc1, _f_res["roce"])
                    _rr = _f_res["fcf"]
                    if _rr.available and _rr.value is not None:
                        _rc2.metric("Free Cash Flow", f"₹{_rr.value:,.0f} cr")
                        _cap = (
                            " · capex-heavy: negative FCF can be a normal investment cycle"
                            if _sp.fcf_capex_caveat else ""
                        )
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

            # ── Valuation Context ──────────────────────────────────────────
            st.markdown("---")
            st.subheader("💰 Valuation Context")
            st.caption(
                "Valuation multiples already available from the fundamentals provider. "
                "Factual context only — no cheap/expensive judgment, no peer comparison yet."
            )
            try:
                from analysis.fundamentals.valuation import build_valuation_context
                from analysis.sector_classification import classify_sector as _classify_v
                _spv     = _classify_v(
                    getattr(cs, "sector", None),
                    name=getattr(cs, "company_name", None),
                )
                _val_cf  = _fund_service().get_fundamentals(ticker)
                _val     = build_valuation_context(_val_cf, sector_profile=_spv)
                _vc1, _vc2, _vc3 = st.columns(3)
                _vc1.metric("P/E",  f"{_val.pe:,.1f}x"  if _val.pe  is not None else "N/A")
                _vc2.metric("P/B",  f"{_val.pb:,.1f}x"  if _val.pb  is not None else "N/A")
                if _val.ev_ebitda_applicable:
                    _vc3.metric(
                        "EV/EBITDA",
                        f"{_val.ev_ebitda:,.1f}x" if _val.ev_ebitda is not None else "N/A",
                    )
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

                st.markdown("**🧮 Valuation Assessment** *(growth- & quality-adjusted, descriptive)*")
                try:
                    from analysis.fundamentals.valuation_decision import assess_valuation
                    _va_res = _fund_analytics.compute_all(_val_cf)
                    _va     = assess_valuation(_val, _va_res, _spv, cf=_val_cf)
                    _va_color = {
                        "high": "#00d4aa", "medium": "#ffa726",
                        "low":  "#8899bb", "none":   "#8899bb",
                    }.get(_va.confidence, "#8899bb")
                    st.markdown(
                        f"> {_va.phrase}  \n"
                        f"<span style='color:{_va_color}'>confidence: {_va.confidence}</span>",
                        unsafe_allow_html=True,
                    )
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
                        "Descriptive only — no buy/sell, no fair/intrinsic value, "
                        "no cheap/expensive label."
                    )
                except Exception as _va_e:
                    st.caption(f"⚠️ Valuation assessment unavailable: {_va_e}")
            except Exception as _val_e:
                st.caption(f"⚠️ Valuation context unavailable: {_val_e}")

            # ── Liquidity Context ──────────────────────────────────────────
            st.markdown("---")
            st.subheader("💧 Liquidity Context")
            _liq_ctx = None
            try:
                from analysis.liquidity import compute_liquidity, format_turnover
                _liq_ctx = compute_liquidity(df)
                _lt_color = {
                    "High": "#00d4aa", "Medium": "#2ecc71",
                    "Low":  "#ffa726", "Illiquid": "#ff4757",
                }.get(_liq_ctx.liquidity_tier, "#8899bb")
                st.markdown(
                    f"Liquidity tier: <b style='color:{_lt_color}'>{_liq_ctx.liquidity_tier}</b>",
                    unsafe_allow_html=True,
                )
                _lc1, _lc2, _lc3 = st.columns(3)
                _lc1.metric(
                    "Avg daily turnover (30d)",
                    format_turnover(_liq_ctx.avg_daily_turnover_30d),
                )
                _lc2.metric(
                    "Avg daily volume (30d)",
                    f"{_liq_ctx.avg_daily_volume_30d:,.0f}"
                    if _liq_ctx.avg_daily_volume_30d is not None else "N/A",
                )
                _lc3.metric(
                    "Volume trend (30d vs 90d)",
                    (_liq_ctx.volume_trend or "—").title(),
                    f"{_liq_ctx.volume_trend_ratio:.2f}x"
                    if _liq_ctx.volume_trend_ratio is not None else None,
                )
                st.caption(
                    _liq_ctx.reason
                    + " · computed from existing OHLCV (no new data source)."
                )
            except Exception as _liq_e:
                st.caption(f"⚠️ Liquidity context unavailable: {_liq_e}")

            # ── Investment Thesis ──────────────────────────────────────────
            st.markdown("---")
            st.subheader("🧭 Investment Thesis (structured)")
            st.caption(
                "Rules-based synthesis of the signals above — Bull / Bear / Risks with a "
                "single verdict. Every point is traceable to its source. Not investment advice."
            )
            _th = None
            try:
                from analysis.thesis import generate_thesis, build_inputs
                _th = generate_thesis(
                    build_inputs(ticker, composite=cs, deep=_dc, liquidity=_liq_ctx)
                )
                _v_color = {
                    "Strong Positive": "#00d4aa", "Positive": "#2ecc71",
                    "Neutral":         "#8899bb",  "Negative": "#ff7043",
                    "Strong Negative": "#ff4757",
                }.get(_th.verdict, "#8899bb")
                st.markdown(
                    f"<div style='font-size:1.15rem'>Verdict: "
                    f"<b style='color:{_v_color}'>{_th.verdict}</b> "
                    f"<span style='color:#8899bb'>(score {_th.verdict_score:+d})</span></div>",
                    unsafe_allow_html=True,
                )
                st.caption(_th.verdict_rationale)

                def _factor_list(_factors, _empty):
                    if not _factors:
                        st.caption(_empty); return
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
                st.caption(f"⚠️ Thesis unavailable: {_th_e}")

            # ── Portfolio Fit — FIX A5 + A9: cached, reads manual holdings ──
            st.markdown("---")
            st.subheader("🧩 Portfolio Fit Assessment")
            st.caption(
                "Is this a good *addition* to your current book? Marginal impact on "
                "diversification, sector mix, beta and concentration. Not investment advice."
            )
            try:
                # FIX A9: manual holdings (kv-backed) replace the old CSV path read
                _pf_holds_raw = load_manual_holdings()
                _pf_holds = []
                for _r in _pf_holds_raw:
                    _t = str(_r.get("ticker", "")).strip()
                    if _t and not _t.upper().endswith(".NS"):
                        _t += ".NS"
                    _q = float(_r.get("quantity", 0) or 0)
                    if _t and _q > 0:
                        _pf_holds.append({"ticker": _t, "quantity": _q})

                if not _pf_holds:
                    st.info(
                        "No holdings found — add holdings on the **🏠 My Portfolio** page "
                        "to see how this stock would fit your book."
                    )
                else:
                    from analysis.thesis import build_fit_inputs, assess_fit
                    with st.spinner("Assessing fit against your portfolio…"):
                        _fit = assess_fit(
                            build_fit_inputs(ticker, _pf_holds, candidate_thesis=_th)
                        )

                    _fr_color = {
                        "Strong Fit":     "#00d4aa", "Fit":      "#2ecc71",
                        "Neutral":        "#8899bb", "Poor Fit": "#ff7043",
                        "Strong Conflict":"#ff4757",
                    }.get(_fit.fit_rating, "#8899bb")
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
                            st.caption(_empty); return
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

                    _ps_color = {
                        "Large": "#00d4aa", "Moderate": "#ffa726", "Small": "#ff7043",
                    }.get(_fit.position_size_guidance, "#8899bb")
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
            # BUGFIX: previously every failure here — including a simple
            # misspelled/unknown ticker reaching this point via some other
            # path — dumped "Analysis failed: <raw exception>" plus a full
            # Python traceback. fetch_single() raises a ValueError starting
            # with "No data for" specifically when no source recognises the
            # symbol, so that one known case now gets a plain message instead;
            # anything else still shows the traceback since that's a genuine
            # bug worth seeing, not a typo.
            if isinstance(e, ValueError) and str(e).startswith("No data for"):
                st.error(
                    f"❌ **Couldn't find '{ticker.replace('.NS','')}' on NSE.** "
                    "Double-check the spelling, or search by company name above "
                    "(e.g. RELIANCE, INFY, TCS)."
                )
            else:
                st.error(f"Analysis failed: {e}")
                import traceback
                st.code(traceback.format_exc())
