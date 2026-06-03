"""Investor Guide - NSE Smart Investor (multipage page; body verbatim from app.py)."""
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
render_sidebar(current="Investor Guide")
render_top_bar()

# ───────────────────────── page body (de-indented from app.py) ─────────────────────────
st.title("📖 Investor Guide — How to Read This Dashboard")
st.markdown(
    "This guide explains every signal, score, and term used in the NSE Smart Investor platform.  \n"
    "Read this once and you will understand exactly what every number means and when to act."
)

tab_g1, tab_g2, tab_g3, tab_g4, tab_g5 = st.tabs([
    "🎯 Scores & Signals", "📊 Indicators", "🔴 Stop-Loss & Risk",
    "📰 News Signals", "📌 Paper Trading SOP"
])

# ── TAB 1: SCORES & SIGNALS ───────────────────────────────────────────────
with tab_g1:
    st.subheader("Composite Score (0 – 100)")
    st.markdown(
        "Every stock gets a **Composite Score from 0 to 100**. "
        "This combines five factors: Technical (40 pts) + Momentum (25 pts) + "
        "Volume (15 pts) + Candlestick Pattern (10 pts) + News Sentiment (10 pts)."
    )
    st.dataframe(pd.DataFrame([
        {"Score Range": "80 – 100", "Grade": "A+", "Signal": "STRONG BUY 🚀",   "What It Means": "Everything aligned — strong trend, good momentum, high volume. Ideal entry."},
        {"Score Range": "65 – 79",  "Grade": "A",  "Signal": "BUY 🟢",           "What It Means": "Positive trend with good momentum. Entry is favourable."},
        {"Score Range": "50 – 64",  "Grade": "B",  "Signal": "WATCHLIST 👀",     "What It Means": "Mixed signals. Worth watching but wait for clearer confirmation."},
        {"Score Range": "40 – 49",  "Grade": "C",  "Signal": "HOLD 🟡",          "What It Means": "Balanced picture — neither buy nor sell. Hold your existing position."},
        {"Score Range": "25 – 39",  "Grade": "D",  "Signal": "CAUTION ⚠️",       "What It Means": "Deteriorating momentum. Tighten stop-loss, don't add more."},
        {"Score Range": "0 – 24",   "Grade": "F",  "Signal": "EXIT 🔴",          "What It Means": "Technicals broken. Consider exiting to protect capital."},
    ]), hide_index=True)

    st.markdown("---")
    st.subheader("Score Sub-Components")
    st.dataframe(pd.DataFrame([
        {"Component":    "Technical (40 pts)",  "What It Measures": "RSI, MACD, Bollinger Bands, SMA trends — is the stock in a healthy uptrend?"},
        {"Component":    "Momentum (25 pts)",   "What It Measures": "Recent price performance vs moving averages. Is the stock accelerating?"},
        {"Component":    "Volume (15 pts)",     "What It Measures": "Is trading volume higher than normal? Big moves on high volume are more reliable."},
        {"Component":    "Candlestick (10 pts)","What It Measures": "Bullish/bearish candle patterns in last 3 days (Hammer, Engulfing, Doji, etc.)"},
        {"Component":    "Sentiment (10 pts)",  "What It Measures": "News tone: positive articles boost score, negative articles reduce it."},
    ]), hide_index=True)

    st.markdown("---")
    st.subheader("VIX Regime — Market Fear Gauge")
    st.markdown(
        "**India VIX** measures how much volatility the market expects over the next 30 days. "
        "High VIX = fear = caution. Low VIX = complacency = also caution (different reason)."
    )
    st.dataframe(pd.DataFrame([
        {"VIX Level": "< 12",   "Regime": "Complacency", "Meaning": "Market too relaxed — be careful, corrections start here"},
        {"VIX Level": "12–16",  "Regime": "Normal 🟢",   "Meaning": "Healthy range — good conditions for long trades"},
        {"VIX Level": "16–22",  "Regime": "Elevated 🟡", "Meaning": "Some fear — be selective, reduce position sizes"},
        {"VIX Level": "22–28",  "Regime": "Fear 🔴",     "Meaning": "Significant fear — prioritise stop-losses, be defensive"},
        {"VIX Level": "> 28",   "Regime": "PANIC 🔴",    "Meaning": "Market panic — avoid new long positions; can be contrarian buy at extremes"},
    ]), hide_index=True)

# ── TAB 2: INDICATORS ─────────────────────────────────────────────────────
with tab_g2:
    st.subheader("Technical Indicators — Plain English")
    st.dataframe(pd.DataFrame([
        {"Indicator": "RSI (14)",          "Range": "0 – 100",    "Normal": "30–70",     "Meaning": "Relative Strength Index. Below 30 = oversold (potential bounce). Above 70 = overbought (potential pullback). Not a standalone signal."},
        {"Indicator": "MACD",              "Range": "Positive/Neg","Normal": "Near zero", "Meaning": "Moving Average Convergence Divergence. MACD crossing above its signal line = bullish. Below = bearish."},
        {"Indicator": "Bollinger Bands",   "Range": "Price levels","Normal": "Within band","Meaning": "Upper/lower bands = 2 standard deviations from 20-day average. Price near upper = overbought. Near lower = oversold."},
        {"Indicator": "SMA 20 / 50 / 200","Range": "Price level", "Normal": "Price > SMA","Meaning": "Simple Moving Average. Price above SMA200 = in long-term uptrend. SMA20 > SMA50 > SMA200 = strong bull alignment."},
        {"Indicator": "ADX",               "Range": "0 – 100",    "Normal": "20–40",     "Meaning": "Average Directional Index. Above 25 = trending (directional trade OK). Below 20 = ranging (avoid breakout trades)."},
        {"Indicator": "ATR",               "Range": "₹ value",    "Normal": "Varies",    "Meaning": "Average True Range. Average daily price movement in rupees. Used to set stop-losses (typically 1.5–2× ATR below entry)."},
        {"Indicator": "Volume Ratio",      "Range": "> 0",        "Normal": "0.8–1.2",   "Meaning": "Today's volume ÷ 20-day average volume. Above 1.5 = above-average interest. Above 2.5 = institutional activity."},
        {"Indicator": "Stochastic K",      "Range": "0 – 100",    "Normal": "20–80",     "Meaning": "Momentum oscillator. Below 20 = oversold, above 80 = overbought. Best used with other signals."},
        {"Indicator": "VWAP %",            "Range": "% value",    "Normal": "±1%",       "Meaning": "Price vs Volume-Weighted Average Price. Positive = stock is above where most volume traded today (bullish intraday). Negative = below (bearish intraday)."},
    ]), hide_index=True)

    st.markdown("---")
    st.subheader("Candlestick Patterns")
    st.dataframe(pd.DataFrame([
        {"Pattern": "Hammer 🔨",          "Type": "Bullish Reversal", "Reliability": "★★★★", "What It Means": "Long lower wick at a low. Sellers tried to push lower but buyers stepped in. Bullish at support."},
        {"Pattern": "Shooting Star ⭐",   "Type": "Bearish Reversal", "Reliability": "★★★★", "What It Means": "Long upper wick at a high. Buyers tried to push higher but sellers overwhelmed them. Bearish at resistance."},
        {"Pattern": "Doji",               "Type": "Indecision",       "Reliability": "★★★",  "What It Means": "Open = Close. Neither buyers nor sellers in control. Watch for next candle's direction."},
        {"Pattern": "Bullish Engulfing",  "Type": "Bullish Reversal", "Reliability": "★★★★★","What It Means": "Large green candle engulfs prior red candle. Powerful reversal after a downtrend. High-probability on volume."},
        {"Pattern": "Bearish Engulfing",  "Type": "Bearish Reversal", "Reliability": "★★★★★","What It Means": "Large red candle engulfs prior green candle. Strong reversal signal after an uptrend."},
        {"Pattern": "Morning Star ☀️",   "Type": "Bullish Reversal", "Reliability": "★★★★★","What It Means": "3-candle: big red → small candle → big green. Classic bottom formation at support."},
        {"Pattern": "Evening Star 🌙",    "Type": "Bearish Reversal", "Reliability": "★★★★★","What It Means": "3-candle: big green → small candle → big red. Classic top formation at resistance."},
        {"Pattern": "Three White Soldiers","Type": "Bullish Continuation","Reliability": "★★★★","What It Means": "3 consecutive bullish candles. Signals strong uptrend resumption after a base."},
    ]), hide_index=True)

# ── TAB 3: STOP-LOSS & RISK ───────────────────────────────────────────────
with tab_g3:
    st.subheader("Stop-Loss — Protecting Your Capital")
    st.markdown(
        "A **stop-loss** is the price at which you exit a losing trade to prevent further losses.  \n"
        "**Never trade without a stop-loss.** It is not optional — it is your safety net."
    )
    st.dataframe(pd.DataFrame([
        {"Term": "Stop-Loss (SL)",    "Meaning": "The price at which you will exit if wrong. Set BEFORE you enter the trade."},
        {"Term": "ATR Stop",          "Meaning": "Stop set 1.5–2× the Average True Range (ATR) below entry. Adjusts for each stock's typical daily movement."},
        {"Term": "Structure Stop",    "Meaning": "Stop placed just below a key support level (previous swing low, major moving average)."},
        {"Term": "Trailing Stop",     "Meaning": "Stop that moves UP as the price rises — locks in profits while letting winners run."},
        {"Term": "Breakeven Stop",    "Meaning": "Once a trade gains 1R profit, move stop to entry price. You can no longer lose money on this trade."},
    ]), hide_index=True)

    st.markdown("---")
    st.subheader("Risk : Reward (R:R) — The Most Important Concept")
    st.markdown(
        "**Risk:Reward ratio** compares how much you could lose (risk) vs how much you could gain (reward).  \n"
        "**Always aim for at least 1.5:1**. This means for every ₹100 you risk, you aim to gain ₹150."
    )
    st.dataframe(pd.DataFrame([
        {"R:R Ratio": "3:1 or higher", "Meaning": "Excellent — even with only 35% win rate, you will be profitable long-term"},
        {"R:R Ratio": "2:1",           "Meaning": "Good — standard target. With 45% win rate you profit consistently"},
        {"R:R Ratio": "1.5:1",         "Meaning": "Minimum acceptable. Need >55% win rate to be consistently profitable"},
        {"R:R Ratio": "1:1",           "Meaning": "Break-even at best. Not recommended unless win rate is very high (>65%)"},
        {"R:R Ratio": "< 1:1",         "Meaning": "Avoid — risking more than potential reward. Mathematically losing strategy"},
    ]), hide_index=True)

    st.markdown("---")
    st.subheader("Position Sizing — How Much to Buy")
    st.markdown(
        "**Never risk more than 1–2% of your total capital on a single trade.**  \n\n"
        "**Formula:** Shares to buy = (Capital × Risk%) ÷ (Entry Price − Stop-Loss Price)  \n\n"
        "**Example:** ₹5,00,000 portfolio × 2% risk = ₹10,000 max loss.  \n"
        "If entry = ₹1,000 and stop = ₹950 → risk per share = ₹50  \n"
        "→ Buy 10,000 ÷ 50 = **200 shares** (₹2,00,000 invested, but max loss is ₹10,000)."
    )

    st.markdown("---")
    st.subheader("Common Mistakes — What to Avoid")
    st.dataframe(pd.DataFrame([
        {"Mistake": "No stop-loss",              "Consequence": "One bad trade can wipe out months of gains", "Fix": "Always set a stop before entering"},
        {"Mistake": "Moving stop-loss down",     "Consequence": "Turns a small loss into a disaster",         "Fix": "Only move stops UP (in the trade's favour), never down"},
        {"Mistake": "Averaging down losers",     "Consequence": "More capital trapped in a losing position",  "Fix": "If stop is hit, exit. Never add to a loser."},
        {"Mistake": "Holding losers, selling winners","Consequence": "Loss portfolio of bad trades",         "Fix": "Let winners run. Cut losers quickly at stop."},
        {"Mistake": "Trading on tips/news alone","Consequence": "No edge, random outcomes",                  "Fix": "Use the composite score + chart for confirmation"},
        {"Mistake": "Overtrading",               "Consequence": "Brokerage + taxes eat all profits",         "Fix": "Only trade high-conviction setups (score ≥ 65)"},
    ]), hide_index=True)

# ── TAB 4: NEWS SIGNALS ───────────────────────────────────────────────────
with tab_g4:
    st.subheader("How News Affects Stock Prices")
    st.markdown(
        "News is one of the **fastest-moving market catalysts**. The dashboard fetches "
        "real-time news for each stock and tags it with a sentiment: Positive, Negative, or Neutral."
    )
    st.dataframe(pd.DataFrame([
        {"News Type": "🟢 POSITIVE",              "Examples": "Strong quarterly results, big order wins, government policy support, rating upgrades, new product launches"},
        {"News Type": "🔴 NEGATIVE",              "Examples": "Profit warning, regulatory fine, management exit, debt downgrade, sector headwinds, fraud allegations"},
        {"News Type": "⚪ NEUTRAL",               "Examples": "AGM dates, routine management changes, product announcements without financials"},
    ]), hide_index=True)

    st.markdown("---")
    st.subheader("How to Use News Alongside Scores")
    st.dataframe(pd.DataFrame([
        {"Score Signal": "BUY 🟢", "News Sentiment": "Positive 🟢", "Combined Signal": "Strong BUY — fundamentals + technicals aligned",       "Action": "Enter with full position size"},
        {"Score Signal": "BUY 🟢", "News Sentiment": "Negative 🔴", "Combined Signal": "Conflict — technical buy but fundamental headwind",    "Action": "Wait or use half position"},
        {"Score Signal": "HOLD 🟡","News Sentiment": "Positive 🟢", "Combined Signal": "Potential upgrade — watch for score improvement",       "Action": "Set alert, review next day"},
        {"Score Signal": "HOLD 🟡","News Sentiment": "Negative 🔴", "Combined Signal": "Risk of breakdown — tighten stop-loss",                "Action": "Move stop to breakeven or exit"},
        {"Score Signal": "EXIT 🔴","News Sentiment": "Positive 🟢", "Combined Signal": "Technical bearish despite good news — mixed",          "Action": "If score < 30, exit anyway"},
        {"Score Signal": "EXIT 🔴","News Sentiment": "Negative 🔴", "Combined Signal": "Full sell signal — both technicals and news bearish",   "Action": "Exit immediately at stop"},
    ]), hide_index=True)

    st.markdown("---")
    st.subheader("Key News Events Calendar (Indian Markets)")
    st.dataframe(pd.DataFrame([
        {"Event": "Quarterly Results (Q1, Q2, Q3, Q4)", "When": "Apr/Jul/Oct/Jan", "Impact": "HIGH — stock can move 5–20% in one day. Avoid holding through results unless you understand the company well."},
        {"Event": "RBI Monetary Policy Committee (MPC)", "When": "Every 2 months",  "Impact": "HIGH — affects banking stocks, rate-sensitive sectors (real estate, auto, NBFCs)"},
        {"Event": "Union Budget",                        "When": "1 Feb each year", "Impact": "VERY HIGH — sector-specific impacts. VIX spikes before budget, often reverses same day."},
        {"Event": "FII/DII Buy/Sell Data",               "When": "Daily",            "Impact": "MEDIUM — sustained FII selling is bearish for Nifty. FII buying supports rally."},
        {"Event": "SEBI Circulars / Regulatory Actions", "When": "As they occur",   "Impact": "MEDIUM–HIGH — affects specific sectors (fintech, brokers, insurance)"},
    ]), hide_index=True)

# ── TAB 5: PAPER TRADING SOP ──────────────────────────────────────────────
with tab_g5:
    st.subheader("📌 How to Use Paper Trading — Step by Step")
    st.markdown(
        "**Paper trading** lets you practice decision-making with zero financial risk.  \n"
        "Think of it as a flight simulator before flying a real plane."
    )

    st.markdown("""
**Step 1 — Find a trade setup**
- Go to **🔍 Analyze Stock** and search for a stock
- If the Composite Score is **≥ 65** and the action is **BUY**, that is a potential entry
- Check the news — is the sentiment positive or neutral?

**Step 2 — Open a paper trade**
- Click **"📌 Paper Trade This Signal"** on the Analyze Stock page, OR
- Go to **📂 Paper Trades** and use the "Open New Paper Trade" form
- The entry price, stop-loss, and target are pre-filled from the model's analysis
- Check the **Risk:Reward ratio** shown — it should be ≥ 1.5:1 before entering

**Step 3 — Track your open position**
- Visit **📂 Paper Trades** daily
- You will see live P&L for every open position
- Green card = in profit. Red card = in loss.
- If the stock hits your stop-loss, click **"Close @ Stop"** — discipline is everything
- If the stock hits your target, click **"Close @ Target"** to book the profit

**Step 4 — Review your performance**
- After 10–20 paper trades, check the **Performance Statistics** section
- Key metrics to watch:
  - **Win Rate > 45%** — you are picking more winners than losers
  - **Payoff Ratio > 1.5** — your winners are bigger than your losers
  - **Expectancy > 0** — your strategy has a positive edge and is worth real money

**Step 5 — Graduate to real money (carefully)**
- Only consider real money after 30+ paper trades with positive expectancy
- Start with the smallest lot size / quantity possible
- Keep risking only 1–2% of capital per trade, just like in paper trading

---
""")

    st.subheader("📊 The 3 Numbers That Define Your Edge")
    _edge_col1, _edge_col2, _edge_col3 = st.columns(3)
    with _edge_col1:
        st.markdown(
            '<div class="card-green">'
            '<b>Win Rate</b><br>'
            'Target: > 45%<br>'
            'How to improve: Only take trades with score ≥ 65 and positive news'
            '</div>', unsafe_allow_html=True
        )
    with _edge_col2:
        st.markdown(
            '<div class="card-blue">'
            '<b>Payoff Ratio</b><br>'
            'Target: > 1.5:1<br>'
            'How to improve: Never enter a trade with R:R less than 1.5:1'
            '</div>', unsafe_allow_html=True
        )
    with _edge_col3:
        st.markdown(
            '<div class="card-yellow">'
            '<b>Expectancy</b><br>'
            'Target: Positive ₹/trade<br>'
            'How to improve: Cut losses quickly; let winners reach target'
            '</div>', unsafe_allow_html=True
        )

    st.markdown("---")
    st.info(
        "📖 **Remember:** The model gives signals based on historical patterns. "
        "No model is 100% accurate. Always use stop-losses. "
        "Paper trade first to verify the signals work for you before using real money."
    )


# ═══════════════════════════════════════════════════════════════════════════════
# PAGE — ANGEL ONE BROKER INTEGRATION
# ═══════════════════════════════════════════════════════════════════════════════
