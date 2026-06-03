"""Swing Checklist - NSE Smart Investor (multipage page; body verbatim from app.py)."""
import os, sys
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
import streamlit as st
from dashboard.shared.design import apply_design
from dashboard.shared.nav import render_sidebar
from dashboard.shared.chart_helpers import render_top_bar
from dashboard.shared import design as _dz, cache as _cache, trade_utils as _tu, chart_helpers as _ch
# Inject every shared module-level name so the verbatim body runs unchanged.
for _m in (_dz, _cache, _tu, _ch):
    globals().update({k: v for k, v in vars(_m).items() if not k.startswith('__')})

apply_design()
render_sidebar(current="Swing Checklist")
render_top_bar()

# ───────────────────────── page body (de-indented from app.py) ─────────────────────────
st.title("✅ Swing Trade Confluence Checklist")
st.markdown(
    "Run all 7 go/no-go factors for a delivery swing trade in one click.  \n"
    "Green = factor confirms the trade. Red = caution. Need ≥ 5/7 green to enter."
)

_sc_c1, _sc_c2 = st.columns([3, 1])
with _sc_c1:
    _sc_ticker = st.text_input("NSE Ticker", value="RELIANCE",
                               placeholder="RELIANCE / TCS / INFY",
                               key="sc_ticker").strip().upper()
with _sc_c2:
    st.write("")
    st.write("")
    _sc_btn = st.button("✅ Run Checklist", type="primary", key="sc_btn")

if _sc_btn and _sc_ticker:
    _sc_sym = _sc_ticker if _sc_ticker.endswith(".NS") else _sc_ticker + ".NS"
    with st.spinner(f"Running confluence checklist for {_sc_ticker}…"):
        try:
            from data.fetcher import fetch_single
            from utils.indicators import add_all_indicators
            from trading.signals import (get_india_vix_regime, check_oversold_bounce,
                                          check_momentum_leader, check_fibonacci_pullback,
                                          check_pullback_to_sma)
            from strategies.sector_rotation import compute_sector_scores, SECTORS

            _sc_df = fetch_single(_sc_sym, period="1y")
            _sc_df = add_all_indicators(_sc_df)
            _sc_df.dropna(subset=["RSI","ATR"], inplace=True)

            _sc_cur = _sc_df.iloc[-1]
            _price  = float(_sc_cur["Close"])
            _rsi    = float(_sc_cur.get("RSI", 50))
            _adx    = float(_sc_cur.get("ADX", 0)) if not pd.isna(_sc_cur.get("ADX",0)) else 0
            _sma20  = float(_sc_cur.get("SMA_20", 0))
            _sma50  = float(_sc_cur.get("SMA_50", 0))
            _sma200 = float(_sc_cur.get("SMA_200", 0))
            _atr    = float(_sc_cur.get("ATR", 0))
            _vol_r  = float(_sc_cur.get("Volume_Ratio", 1))
            _st_dir = int(_sc_cur.get("ST_Direction", 0))
            _fib_zone = str(_sc_cur.get("Fib_Zone", "unknown"))
            _cpr_zone = str(_sc_cur.get("Price_vs_CPR", "unknown"))

            # VIX check
            _vix_r = get_india_vix_regime()
            _vix_ok = _vix_r["allow_buy"]
            _vix_val = _vix_r.get("vix") or 0

            # Sector rank check
            try:
                _sec_scores = compute_sector_scores(period="1y")
                _top3 = set(_sec_scores.head(3).index.tolist()) if not _sec_scores.empty else set()
                _ticker_sector = {t: s for s, ts in SECTORS.items() for t in ts}
                _stock_sector = _ticker_sector.get(_sc_sym, "Unknown")
                _sector_ok = _stock_sector in _top3
                _sector_str = f"{_stock_sector} ({('Top 3' if _sector_ok else 'Not top 3')})"
            except Exception:
                _sector_ok, _sector_str = True, "Unknown (not filtered)"

            # MTF check (weekly trend)
            try:
                from analysis.mtf import check_daily_weekly_alignment
                _mtf = check_daily_weekly_alignment(_sc_df)
                _mtf_ok = _mtf["alignment"] == "bullish"
                _mtf_str = _mtf["confirmation"]
            except Exception:
                _mtf_ok, _mtf_str = True, "MTF check skipped"

            # Build checklist items
            _checks = [
                {
                    "name":   "1️⃣ VIX Regime",
                    "pass":   _vix_ok,
                    "detail": f"India VIX = {_vix_val:.1f} | Regime: {_vix_r.get('regime','?').upper()}",
                    "tip":    "VIX must be ≤ 28. High VIX = panic = avoid new longs.",
                },
                {
                    "name":   "2️⃣ Long-Term Trend (SMA200)",
                    "pass":   _price > _sma200 > 0,
                    "detail": f"Price ₹{_price:.1f} {'>' if _price > _sma200 else '<'} SMA200 ₹{_sma200:.1f}",
                    "tip":    "Price must be above 200-day SMA to confirm long-term uptrend.",
                },
                {
                    "name":   "3️⃣ MA Stack (SMA20 > SMA50)",
                    "pass":   _sma20 > _sma50 > 0,
                    "detail": f"SMA20 ₹{_sma20:.1f} {'>' if _sma20>_sma50 else '<'} SMA50 ₹{_sma50:.1f}",
                    "tip":    "Moving average alignment confirms short-term uptrend.",
                },
                {
                    "name":   "4️⃣ RSI Zone (30–70)",
                    "pass":   30 < _rsi < 72,
                    "detail": f"RSI = {_rsi:.1f} | Ideal entry: 40–60",
                    "tip":    "RSI in healthy range — not overbought (>72) or in freefall (<25).",
                },
                {
                    "name":   "5️⃣ ADX Trend Strength",
                    "pass":   _adx >= 20,
                    "detail": f"ADX = {_adx:.1f} | {'Trending ✅' if _adx>=25 else ('Weak trend' if _adx>=20 else 'Ranging ❌')}",
                    "tip":    "ADX ≥ 20 confirms trending environment. Below 20 = ranging/choppy.",
                },
                {
                    "name":   "6️⃣ Multi-Timeframe Alignment",
                    "pass":   _mtf_ok,
                    "detail": _mtf_str,
                    "tip":    "Both daily and weekly must be bullish for high-conviction swing entry.",
                },
                {
                    "name":   "7️⃣ Sector in Top-3",
                    "pass":   _sector_ok,
                    "detail": _sector_str,
                    "tip":    "Stocks in top-3 sectors by momentum score have higher win rates.",
                },
            ]

            # Score
            _score = sum(1 for c in _checks if c["pass"])
            _score_color = "card-green" if _score >= 5 else ("card-yellow" if _score >= 3 else "card-red")
            _verdict = (
                "✅ STRONG SETUP — All key factors aligned. Consider entry."
                if _score >= 6 else
                "🟡 MODERATE SETUP — Most factors align. Entry with smaller size."
                if _score >= 4 else
                "🔴 WEAK SETUP — Too many factors against. Wait for improvement."
            )

            st.markdown(f"""
            <div class="{_score_color}">
            <span class="score-big">{_score}/7</span> &nbsp;&nbsp;
            <span class="signal-big">{_verdict}</span><br>
            <b>{_sc_ticker}</b> at ₹{_price:.2f} | RSI {_rsi:.1f} | ADX {_adx:.1f}
            </div>
            """, unsafe_allow_html=True)

            st.markdown("---")
            st.markdown("### Checklist Details")
            for _chk in _checks:
                _icon  = "✅" if _chk["pass"] else "❌"
                _color = "#4caf50" if _chk["pass"] else "#ef5350"
                st.markdown(
                    f"<div style='border-left:4px solid {_color}; padding:8px 12px; "
                    f"margin:6px 0; background:rgba(255,255,255,0.03); border-radius:4px;'>"
                    f"<b>{_icon} {_chk['name']}</b><br>"
                    f"<span style='color:#ccc'>{_chk['detail']}</span><br>"
                    f"<small style='color:#888'>{_chk['tip']}</small></div>",
                    unsafe_allow_html=True,
                )

            # Trade plan if score ≥ 4
            if _score >= 4 and _atr > 0:
                st.markdown("---")
                st.markdown("### 📋 Suggested Trade Plan")
                _sl_val = _price - 2 * _atr
                _tp_val = _price + 3 * _atr
                _rr_val = 3 * _atr / (2 * _atr)
                st.markdown(f"""
                <div class="card-blue">
                <b>Entry:</b> ₹{_price:.2f} &nbsp;|&nbsp;
                <b>SL:</b> ₹{_sl_val:.2f} (2× ATR) &nbsp;|&nbsp;
                <b>TP:</b> ₹{_tp_val:.2f} (3× ATR) &nbsp;|&nbsp;
                <b>R:R:</b> {_rr_val:.1f}x<br>
                <small>ATR = ₹{_atr:.2f} | Fib Zone: {_fib_zone} | CPR: {_cpr_zone}</small>
                </div>
                """, unsafe_allow_html=True)

        except Exception as _sce:
            st.error(f"Checklist error: {_sce}")
            import traceback; st.code(traceback.format_exc())
else:
    st.info("Enter a ticker and click **✅ Run Checklist** to see confluence analysis.")

# Reference table
st.markdown("---")
st.markdown("### 📖 Checklist Reference — What Each Factor Means")
st.dataframe(pd.DataFrame([
    {"Factor":    "VIX Regime",          "Pass When":  "India VIX ≤ 28",        "Why It Matters": "High VIX = market panic = stop-outs are more likely"},
    {"Factor":    "SMA200 Trend",         "Pass When":  "Price > SMA200",         "Why It Matters": "Stocks below SMA200 are in a downtrend — buying is fighting the tape"},
    {"Factor":    "MA Stack",             "Pass When":  "SMA20 > SMA50",          "Why It Matters": "Short-term uptrend confirmed when faster MA is above slower"},
    {"Factor":    "RSI Zone",             "Pass When":  "RSI 30–72",              "Why It Matters": "Outside this range = exhaustion (too hot or too cold)"},
    {"Factor":    "ADX Strength",         "Pass When":  "ADX ≥ 20",              "Why It Matters": "Trending stocks have higher momentum carry than ranging stocks"},
    {"Factor":    "MTF Alignment",        "Pass When":  "Daily+Weekly both bullish","Why It Matters": "Same direction on multiple timeframes = higher conviction"},
    {"Factor":    "Sector Rank",          "Pass When":  "Sector in Top 3",        "Why It Matters": "Rising sectors carry stocks — fight sector momentum rarely works"},
]), hide_index=True, use_container_width=True)


# ═══════════════════════════════════════════════════════════════════════════════
# PAGE 14 — MY WATCHLIST  [NEW]
# ═══════════════════════════════════════════════════════════════════════════════
