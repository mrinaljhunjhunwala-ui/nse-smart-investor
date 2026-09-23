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
    PLOT_COLORS,
    diverging_colors,
    finite_abs_peak,
    render_top_bar,
    tick_pulse_tracker,
)
from dashboard.shared.ui_components import ticker_hover_wrap
import logging


def _sector_of(ticker: str) -> str:
    try:
        from data.universe import get_sector
        return get_sector(ticker)
    except Exception:
        return "Other"

apply_design()
render_sidebar(current="Live Ticker")
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
    st.markdown('<h1 class="page-title-serif">Live <em>Ticker</em></h1>', unsafe_allow_html=True)

    st.markdown("Real-time NSE prices · Top movers · News signals")
with col_h2:
    st.markdown(f"""
    <div style='text-align:right;margin-top:12px'>
    <span style='font-size:22px'>{_ms['color']}</span><br>
    <b style='font-size:16px'>{_ms['status']}</b><br>
    <span style='font-size:11px;color:var(--ink-mid)'>{_ms['time_ist']}</span>
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

    # ── P2 · terminal-grade tape — fixed height, monospaced, edge-masked ──
    _tape_rows = pd.concat([snap.head(10), snap.tail(10).iloc[::-1]]).drop_duplicates(subset=["ticker"])
    _tape_items = "".join(
        f'<span class="ml-tape-item"><b>{_tr["ticker"].replace(".NS", "")}</b> '
        f'{_tr["price"]:,.2f} '
        f'<span class="{"ml-tape-up" if _tr["chg_pct"] >= 0 else "ml-tape-dn"}">'
        f'{"▲" if _tr["chg_pct"] >= 0 else "▼"}{abs(_tr["chg_pct"]):.2f}%</span></span>'
        for _, _tr in _tape_rows.iterrows()
    )
    st.markdown(
        f'<div class="ml-tape" aria-label="Top movers tape"><div class="ml-tape-track">'
        f'{_tape_items}{_tape_items}</div></div>',
        unsafe_allow_html=True,
    )

    st.markdown("---")

    # ── Today's Trade Ideas (from live % change + market breadth) ──────────
    # NOTE: intraday volume isn't available in the batch feed, so ideas are
    # ranked on live price change + breadth, not volume.
    st.markdown("##### 💡 Today's Trade Ideas")
    _sg_items = []
    _top_gain = snap.iloc[0]   if len(snap) else None       # sorted desc
    _top_lose = snap.iloc[-1]  if len(snap) else None
    # F1 audit -- semantic-idea cards now source their accent + tint background
    # from design.py tokens (bull/bear/amber) so the palette is one source of
    # truth. Tint backgrounds are subtler than the previous hand-mixed near-
    # black hexes; the border-left rail keeps the semantic intent legible.
    if _top_gain is not None and _top_gain["chg_pct"] >= 1.0:
        _sg_items.append(("🟢 STRONGEST TODAY", "var(--bull)", "var(--tint-bull)",
                          _top_gain["ticker"].replace(".NS",""),
                          f"₹{_top_gain['price']:,.2f}  ·  {_top_gain['chg_pct']:+.2f}%",
                          "Leading the market higher — strongest momentum in the universe today"))
    if _top_lose is not None and _top_lose["chg_pct"] <= -1.0:
        _sg_items.append(("🔴 WEAKEST TODAY", "var(--bear)", "var(--tint-bear)",
                          _top_lose["ticker"].replace(".NS",""),
                          f"₹{_top_lose['price']:,.2f}  ·  {_top_lose['chg_pct']:+.2f}%",
                          "Under the heaviest selling pressure in the universe today"))
    # Market-regime idea from breadth
    if _breadth_pct >= 65:
        _sg_items.append(("📈 BROAD STRENGTH", "var(--bull)", "var(--tint-bull)", "Market-wide",
                          f"{_breadth_pct:.0f}% of stocks up · avg {avg_chg:+.2f}%",
                          "Risk-on breadth — most stocks advancing"))
    elif _breadth_pct <= 35:
        _sg_items.append(("📉 BROAD WEAKNESS", "var(--bear)", "var(--tint-bear)", "Market-wide",
                          f"{100-_breadth_pct:.0f}% of stocks down · avg {avg_chg:+.2f}%",
                          "Risk-off breadth — most stocks declining"))
    else:
        _sg_items.append(("↔️ MIXED MARKET", "var(--amber)", "var(--tint-amber)", "Market-wide",
                          f"{_breadth_pct:.0f}% up · avg {avg_chg:+.2f}%",
                          "No clear breadth tilt — moves are stock-specific"))

    _sg_html = '<div style="display:flex;gap:10px;margin-bottom:4px;flex-wrap:wrap">'
    for _lbl, _c, _bg, _tk, _sub, _why in _sg_items:
        _sg_html += (
            f'<div style="flex:1;min-width:200px;background:{_bg};border-left:5px solid {_c};'
            f'border-radius:10px;padding:12px 15px">'
            f'<div style="font-size:10px;color:{_c};text-transform:uppercase;'
            f'letter-spacing:1px;font-weight:700;margin-bottom:2px">{_lbl}</div>'
            f'<div style="font-size:20px;font-weight:700;color:var(--ink)">{_tk}</div>'
            f'<div style="font-size:12px;color:var(--ink-mid);margin:2px 0">{_sub}</div>'
            f'<div style="font-size:11px;color:var(--dim)">{_why}</div></div>'
        )
    _sg_html += '</div>'
    st.markdown(_sg_html, unsafe_allow_html=True)
    st.caption("Ideas ranked on live price change + market breadth (intraday volume not in feed). "
               "Not financial advice — confirm with the Analyze page before trading.")

    st.markdown("---")

    # ── Gainers and Losers — clean HTML cards (robust, no nested expanders) ─
    top5 = snap.head(5)
    bot5 = snap.tail(5).iloc[::-1]

    # UX3 · live-tick pulse — one shared tracker across gainers + losers so a
    # stock that flips from gainer to loser (or back) still compares against
    # its own last-seen price rather than starting fresh. commit() at the end
    # of the render prunes symbols that dropped out of both top-5 lists.
    _mv_pulse, _mv_pulse_commit = tick_pulse_tracker("_ml_movers_prev")

    def _movers_block(rows, is_gainer):
        _acc = "var(--bull)" if is_gainer else "var(--bear)"
        _html = ""
        for _i, (_, _row) in enumerate(rows.iterrows(), 1):
            _ch = _row["chg_pct"]
            _cc2 = "var(--bull)" if _ch >= 0 else "var(--bear)"
            _ar = "▲" if _ch >= 0 else "▼"
            _nm = str(_row.get("name", ""))[:26]
            _tick_cls = _mv_pulse(_row["ticker"], _row["price"])
            _mv_price = pd.to_numeric(_row["price"], errors="coerce")
            _mv_chg = pd.to_numeric(_ch, errors="coerce")
            _mv_label = ticker_hover_wrap(
                _row["ticker"].replace(".NS", ""),
                price=float(_mv_price) if math.isfinite(_mv_price) else None,
                chg_pct=float(_mv_chg) if math.isfinite(_mv_chg) else None,
                sector=_sector_of(_row["ticker"]),
            )
            _html += (
                f'<div class="mover-card{_tick_cls}" '
                f'style="background:var(--sunken);border-left:4px solid {_acc};'
                f'border-radius:9px;padding:9px 13px;margin-bottom:6px;'
                f'display:flex;justify-content:space-between;align-items:center">'
                f'<div><span style="color:var(--faint);font-size:11px;margin-right:6px">#{_i}</span>'
                f'<span style="font-size:15px;font-weight:700;color:var(--ink)">{_mv_label}</span>'
                f'<div style="font-size:11px;color:var(--dim)">{_nm}</div></div>'
                f'<div style="text-align:right">'
                f'<div style="font-size:15px;font-weight:700;color:var(--ink)">₹{_row["price"]:,.2f}</div>'
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
    _mv_pulse_commit()

    # ── P2 · Sector heatmap — diverging palette (hue = sign, alpha = size) ──
    try:
        _sec = snap.assign(sector=snap["ticker"].map(_sector_of))
        _sec = _sec[_sec["sector"] != "Other"]
        _sec_agg = (_sec.groupby("sector")
                        .agg(chg=("chg_pct", "mean"), n=("ticker", "count"))
                        .reset_index())
        if not _sec_agg.empty:
            import plotly.graph_objects as _go
            from dashboard.shared.tokens import COLORS as _TOK
            _sec_agg["chg"] = pd.to_numeric(_sec_agg["chg"], errors="coerce")
            _peak = max(finite_abs_peak(_sec_agg["chg"]) or 0.0, 1.0)
            _fig = _go.Figure(_go.Treemap(
                labels=_sec_agg["sector"],
                parents=[""] * len(_sec_agg),
                values=_sec_agg["n"],
                customdata=_sec_agg[["chg", "n"]].values,
                marker=dict(colors=diverging_colors(_sec_agg["chg"], full_at=_peak),
                            line=dict(width=2, color=_TOK["ground"])),
                # Light ink on every tile: the alpha-scaled fills sit on the
                # dark ground, so even the strongest tile is dark enough for
                # --ink text (Plotly's auto-contrast picked near-black labels
                # that vanished on the darker, low-magnitude tiles).
                texttemplate="%{label}",
                textfont=dict(color=_TOK["ink"], size=12),
                textposition="middle center",
                hovertemplate="<b>%{label}</b><br>%{customdata[0]:+.2f}% avg"
                              " · %{customdata[1]} stocks<extra></extra>",
            ))
            _fig.update_layout(height=320, margin=dict(l=0, r=0, t=0, b=0),
                               paper_bgcolor="rgba(0,0,0,0)")
            st.markdown('<div class="t-h2" style="margin:14px 0 6px 0">'
                        '🗺️ Sector Heatmap</div>', unsafe_allow_html=True)
            st.plotly_chart(_fig, use_container_width=True)
            st.caption("Tile size = stocks tracked · colour hue = direction, "
                       "intensity = size of the average move. Hover for %.")
    except Exception as _hm_e:
        logging.getLogger("dashboard.market_live").debug("sector heatmap failed: %s", _hm_e)

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
        # DT1 + DT2 · movers table attribution.
        try:
            from dashboard.shared.ui_components import data_as_of as _ml_asof
            import datetime as _ml_dt
            _ml_when = _ml_dt.datetime.now().strftime("%H:%M IST")
            st.markdown(
                _ml_asof(_ml_when, source="yfinance",
                         ttl_hint="live-price cache 60 s"),
                unsafe_allow_html=True,
            )
        except Exception:
            pass

# ── Market News (multi-source, with source badges) ─────────────────────────
st.markdown("---")
st.markdown(
    '<div class="t-h2" style="margin:14px 0 6px 0">'
    '📰 Latest Market News</div>',
    unsafe_allow_html=True,
)
with st.spinner("Aggregating news from multiple sources…"):
    mkt_news = get_market_news(max_articles=14)

if mkt_news:
    _srcs = sorted({a.get("publisher", "") for a in mkt_news if a.get("publisher")})
    st.caption(f"🗞️ Aggregated from **{len(_srcs)} sources**: {', '.join(_srcs)}")
    # P2 · publisher identity chips cycle through PLOT_COLORS tokens
    # (no raw hex in pages).
    _src_palette = [PLOT_COLORS[k] for k in ("azure", "accent", "bull", "amber", "bear", "dim")]
    _src_color = {s: _src_palette[i % len(_src_palette)] for i, s in enumerate(_srcs)}
    for article in mkt_news:
        _s   = article["sentiment"]
        _sc  = ("var(--bull)" if _s == "positive"
                else "var(--bear)" if _s == "negative" else "var(--dim)")
        _si  = "▲" if _s == "positive" else "▼" if _s == "negative" else "•"
        _pub = article.get("publisher", "—")
        _pc  = _src_color.get(_pub, PLOT_COLORS["dim"])
        st.markdown(
            f'<div style="background:var(--surface);border:1px solid var(--hairline-soft);'
            f'border-left:3px solid {_sc};border-radius:8px;padding:10px 14px;margin-bottom:6px">'
            f'<span style="background:{_pc}22;color:{_pc};border:1px solid {_pc};border-radius:5px;'
            f'padding:1px 8px;font-size:10px;font-weight:700">{_pub}</span>'
            f'<span style="font-size:10px;color:var(--faint)">&nbsp; · {article["time"]} · '
            f'<span style="color:{_sc};font-weight:600">{_si} {_s}</span></span><br>'
            f'<a href="{article["link"]}" target="_blank" style="color:var(--ink);'
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
