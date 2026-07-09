"""Market Live - NSE Smart Investor (multipage page; body verbatim from app.py)."""
import os, sys
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
import streamlit as st
from dashboard.shared.design import apply_design
from dashboard.shared.nav import render_sidebar
from dashboard.shared.chart_helpers import render_top_bar
# P3: explicit imports (was a dynamic shared-namespace injection)
import math
import os
import pandas as pd
import streamlit as st
import sys
from dashboard.shared.design import (
    apply_design,
)
from dashboard.shared.cache import (
    get_display_name,
)
from dashboard.shared.chart_helpers import (
    _ROOT,
    render_top_bar,
)

apply_design()
render_sidebar(current="Market Live")
render_top_bar()

# ───────────────────────── page body (de-indented from app.py) ─────────────────────────
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
    # FIX MKT1: was a blanket st.cache_data.clear() — wiped every other
    # page's cached data (Top Picks, watchlist scans, etc.) along with this
    # page's own snapshot. "Refresh Now" only means this page's data.
    # _load_nifty_snapshot is defined further down this script (Streamlit
    # pages run top-to-bottom on every interaction), so the click is just
    # captured here and the actual .clear() happens right before the
    # function is first called below, once it actually exists.
    _mkt_refresh_clicked = st.button("🔄 Refresh Now")

st.markdown(f"*{_ms['day']} — {_ms['detail']}*")
st.markdown("---")

# ── Fetch broad NSE prices — Angel One (priority) → Yahoo → NSE fallback ──
@st.cache_data(ttl=60 if _ms["is_open"] else 3600, show_spinner=False)
def _load_nifty_snapshot():
    """
    Cloud-safe NSE broad snapshot (Nifty Total Market ~750 stocks).
    Priority: Angel One batch quotes → Yahoo Finance JSON API.
    """
    from data.universe import get_universe as _gu

    tickers_list = _gu("niftytotalmarket")   # ~750 liquid NSE stocks
    raw: dict = {}
    _source = "Yahoo Finance"

    # Tier 1: Angel One (real-time, preferred)
    import logging as _ml_log
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
    except Exception as _ao_e:
        _ml_log.getLogger("dashboard.market_live").debug("Angel One batch fetch failed: %s", _ao_e)

    # Tier 2: Yahoo Finance JSON
    if not raw:
        from utils.live_price import get_live_prices_batch
        raw     = get_live_prices_batch(tickers_list, max_workers=20)
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
        except Exception as _row_e:
            _ml_log.getLogger("dashboard.market_live").debug("Skipping ticker %s in snapshot: %s", t, _row_e)
            continue

    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows).sort_values("chg_pct", ascending=False)
    return df

# Now that _load_nifty_snapshot exists, honor an earlier "Refresh Now"
# click (captured before this point in the script, since the button is
# rendered above the function definition).
if _mkt_refresh_clicked:
    _load_nifty_snapshot.clear()
    st.rerun()

with st.spinner("Loading NSE market snapshot (~750 stocks)…"):
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

        except Exception as _expl_e:
            import logging as _expl_log
            _expl_log.getLogger("dashboard.market_live").debug("_explain_mover(%s) failed: %s", ticker, _expl_e)
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
                # FIX NAV1: canonical analyze_ticker hand-off (see
                # 04_analyze_stock.py FIX A8) instead of manual_ticker_input +
                # last_analyzed — traced through and confirmed the old path
                # did work here, but standardizing every "Analyze" button in
                # the app on one tested contract removes a whole class of
                # future navigation bugs rather than leaving three parallel
                # mechanisms doing the same job.
                st.session_state["analyze_ticker"] = _dt_full
                st.session_state["_goto_page"] = "🔍 Analyze Stock"
                st.rerun()
            if _db.button("📝 Paper Trade", key=f"ml_pt_{_dt_full}", use_container_width=True):
                st.session_state["_goto_page"] ="📂 Paper Trades"
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

# ── Market News (multi-source, with source badges) ─────────────────────────
st.markdown("---")
st.subheader("📰 Latest Market News")
with st.spinner("Aggregating news from multiple sources…"):
    mkt_news = get_market_news(max_articles=14)

if mkt_news:
    _srcs = sorted({a.get("publisher", "") for a in mkt_news if a.get("publisher")})
    st.caption(f"🗞️ Aggregated from **{len(_srcs)} sources**: {', '.join(_srcs)}")
    _src_palette = ["#5b8def", "#00d4aa", "#ff9500", "#a78bfa", "#FFC107",
                    "#26a69a", "#64b5f6", "#ff6b9d", "#ffd700"]
    _src_color = {s: _src_palette[i % len(_src_palette)] for i, s in enumerate(_srcs)}
    for article in mkt_news:
        _s   = article["sentiment"]
        _sc  = "#00d4aa" if _s == "positive" else "#ff4757" if _s == "negative" else "#8899bb"
        _si  = "▲" if _s == "positive" else "▼" if _s == "negative" else "•"
        _pub = article.get("publisher", "—")
        _pc  = _src_color.get(_pub, "#8899bb")
        st.markdown(
            f'<div style="background:#0d1526;border:1px solid rgba(255,255,255,.05);'
            f'border-left:3px solid {_sc};border-radius:8px;padding:10px 14px;margin-bottom:6px">'
            f'<span style="background:{_pc}22;color:{_pc};border:1px solid {_pc};border-radius:5px;'
            f'padding:1px 8px;font-size:10px;font-weight:700">{_pub}</span>'
            f'<span style="font-size:10px;color:#4a5568">&nbsp; · {article["time"]} · '
            f'<span style="color:{_sc};font-weight:600">{_si} {_s}</span></span><br>'
            f'<a href="{article["link"]}" target="_blank" style="color:#e0e0e0;'
            f'text-decoration:none;font-size:14px;font-weight:600">{article["title"]}</a></div>',
            unsafe_allow_html=True,
        )
else:
    st.info("News temporarily unavailable — refresh in a moment.")

if ri > 0:
    st.caption(f"Auto-refreshes every {ri//60} minutes while market is open.")


# ═══════════════════════════════════════════════════════════════════════════════
# PAGE 0 — COMMAND CENTRE
# ═══════════════════════════════════════════════════════════════════════════════
