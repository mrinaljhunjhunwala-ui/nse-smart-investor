---
name: nse-ticker-deepdive
description: |
  Deep-dive analysis for a single NSE/BSE (Indian equity) ticker — pulls
  price history via yfinance, computes the same composite score, momentum
  posture, and technical read the NSE Smart Investor dashboard produces,
  and writes a structured analysis card. Works in any Claude chat, no
  repo required — as long as yfinance is installable or WebFetch can
  reach Yahoo Finance.

  Use whenever the user names a single Indian stock and asks any of:
  "analyze RELIANCE", "should I look at TCS", "is HDFC a buy",
  "what's the setup on INFY", "deep dive on ITC", "check ONGC",
  "posture on ADANIENT", "is [ticker] worth entering", or drops a
  bare ticker with intent to know its status. Also triggers on a name
  from the NSE 500 followed by any of: "analysis", "posture", "score",
  "chart read", "verdict", "should I buy", "should I hold",
  "should I trim", "should I exit", "momentum", "trend", "levels".

  Do NOT invoke for: general market commentary (use market skills
  instead), portfolio-level questions (needs the full app), option
  chain / F&O questions (use options-fno-analysis), or non-Indian
  tickers. If the ticker isn't listed on NSE/BSE, say so and stop.
---

# NSE Ticker Deep-Dive

Portable single-ticker analysis matching the NSE Smart Investor dashboard's
methodology. This skill runs anywhere Claude Code runs — including a fresh
chat with no repo loaded — because it uses yfinance for daily bars and
computes every indicator inline. No dashboard, no persisted snapshot, no
database dependency.

Everything below is a workflow Claude follows when invoked. Do not run any
of these steps if the user is asking about something else — the description
above governs when this fires.

## Non-negotiable rules (same as the source repo's CLAUDE.md)

1. **No buy/sell/hold recommendation.** Output a *descriptive posture*
   ("Bullish momentum breakout on volume confirmation"), never an
   instruction ("buy this"). If the user asks "should I buy X", answer
   with the posture and the factors, not a directive.
2. **Sector-aware fundamentals.** Banks / NBFCs / insurers must be read on
   P/B + ROE, not "debt / leverage". If sector is unknown, say so rather
   than applying generic leverage math.
3. **Educational only.** End every card with the disclaimer stub in the
   template below. Never omit it.

## Step 1 — Resolve the ticker

The user's input is one of these forms — normalize to Yahoo Finance format:

| User typed | Resolve to |
|---|---|
| `RELIANCE`, `TCS`, `HDFCBANK` (bare NSE symbol) | `RELIANCE.NS`, `TCS.NS`, `HDFCBANK.NS` |
| `Reliance Industries`, `Tata Consultancy` (company name) | Look up the NSE symbol, then append `.NS` |
| `500325`, `532540` (BSE code) | Append `.BO` (only if NSE symbol unknown) |
| Already suffixed (`RELIANCE.NS`, `RELIANCE.BO`) | Use as-is |

If ambiguous (e.g. multiple entities after a demerger — Tata Motors PV vs
CV, Vedanta parent vs the four spin-offs), ask the user which they mean
before proceeding. Do not guess.

## Step 2 — Fetch data

Preferred path — Python with yfinance:

```python
import yfinance as yf
import pandas as pd
tk = yf.Ticker("RELIANCE.NS")
df = tk.history(period="2y", interval="1d")   # ~500 daily bars
info = tk.info                                 # sector, P/E, P/B, ROE, market cap
```

Fallback if yfinance not installed: WebFetch `https://query1.finance.yahoo.com/v8/finance/chart/RELIANCE.NS?range=2y&interval=1d`
and parse the JSON.

Also fetch the **Nifty 50** (`^NSEI`) history over the same 2y for
relative-strength ranking.

If the fetch returns fewer than 210 daily bars, say the stock is too
recently listed for the SMA200 filter to be meaningful and stop the
analysis there rather than producing a misleading number.

## Step 3 — Compute the indicators

All computed inline — do not depend on a repo module. Use these formulas
(they match the source repo bit-for-bit so cards produced here match
what the dashboard shows):

```python
# RSI(14) — Wilder smoothing
delta = close.diff()
gain  = delta.clip(lower=0)
loss  = -delta.clip(upper=0)
avg_gain = gain.ewm(alpha=1/14, adjust=False, min_periods=14).mean()
avg_loss = loss.ewm(alpha=1/14, adjust=False, min_periods=14).mean()
rs = avg_gain / avg_loss.where(avg_loss > 0)
rsi = (100 - 100/(1+rs)).where(avg_loss > 0, 100)

# SMA stack
sma20  = close.rolling(20).mean()
sma50  = close.rolling(50).mean()
sma200 = close.rolling(200).mean()

# ATR(20) — Wilder
tr = pd.concat([
    (high - low),
    (high - close.shift(1)).abs(),
    (low  - close.shift(1)).abs(),
], axis=1).max(axis=1)
atr = tr.ewm(alpha=1/20, adjust=False, min_periods=20).mean()

# MACD (12, 26, 9)
ema12 = close.ewm(span=12, adjust=False).mean()
ema26 = close.ewm(span=26, adjust=False).mean()
macd_line   = ema12 - ema26
macd_signal = macd_line.ewm(span=9, adjust=False).mean()
macd_hist   = macd_line - macd_signal

# 20-session rolling VWAP (daily-bar proxy for session VWAP)
typical = (high + low + close) / 3
vwap = (typical * volume).rolling(20).sum() / volume.rolling(20).sum()

# 63-day relative strength vs Nifty
rs_63d = (close.iloc[-1]/close.iloc[-64] - 1)*100 - \
         (nifty_close.iloc[-1]/nifty_close.iloc[-64] - 1)*100
```

## Step 4 — Check the six momentum filters (dashboard's recipe)

Apply the exact same filter set the dashboard's momentum scanner uses:

| Filter | Pass condition |
|---|---|
| Trend | Close > SMA50 AND SMA50 > SMA200 |
| 55-day breakout | Close > highest close of prior 55 sessions |
| Volume surge | today's volume > 1.5 × 20-day avg |
| RSI band | 55 ≤ RSI(14) ≤ 75 |
| Above VWAP | last close > 20-session rolling VWAP |
| Not exhausted | today's true range < 2.5 × ATR(20) |

Report each filter as ✅ pass / ❌ fail / — n/a in the output card. The
composite momentum posture derives from how many pass:

- **6/6**: "Strong momentum breakout, all filters aligned"
- **4–5/6**: "Momentum building, some confirmation missing"
- **2–3/6**: "Mixed — momentum questionable"
- **0–1/6**: "No momentum edge here"

## Step 5 — Compute the composite score (0–90)

Match the source repo's four-component split (see [`analysis/score.py`](../../../code/nse-smart-investor/analysis/score.py) if the repo is loaded):

| Component | Weight | Rough scoring |
|---|---|---|
| Technical | 40 pts | 10 for RSI in trend band (40–70), 10 for MACD > signal, 10 for SMA stack aligned (20>50>200), 10 for ADX > 20 (if you can compute it — else skip and cap at 30) |
| Momentum | 25 pts | 5d / 20d / 60d returns positive and increasing; 10 for 60d > 15 %, 8 for 5–15 %, 5 for 0–5 %, 0 for negative |
| Volume | 15 pts | 10 for today's vol > 1.5× 20d avg, 5 for OBV rising over 20d |
| Sentiment | 10 pts | 5 for VIX < 20 (calm regime, use approximate India VIX from `^INDIAVIX` on yfinance), 5 for sector context if known — else neutral 3 |

Then grade: A+ (≥ 79), A (≥ 68), B (≥ 55), C (≥ 43), D (≥ 29), F (< 29).
Report the score AND the component breakdown so the user sees why.

**Do not translate the grade into an action verb.** "A grade" is a
descriptive quality tier, not "BUY".

## Step 6 — Sector-aware fundamental posture

Use `tk.info` fields (yfinance):

- Sector: `info["sector"]` — normalize with the classification table below
- P/E: `info["trailingPE"]`, `info["forwardPE"]`
- P/B: `info["priceToBook"]`
- ROE: `info["returnOnEquity"]`
- Debt: `info["debtToEquity"]`

**Sector classification** for metric picking:

| yfinance sector | Metric priority |
|---|---|
| Financial Services (banks, NBFCs) | P/B, ROE, NIM if surfaced. Ignore "debt / leverage" — banks ARE the debt. |
| Insurance | Embedded value if you can find it, P/B, ROE |
| Utilities, Real Estate | Yield, P/B, debt-to-EBITDA |
| Technology, Consumer, Healthcare | P/E, ROE, revenue growth 5y |
| Energy, Materials, Industrials | P/E, EV/EBITDA, debt/EBITDA |
| Communication Services | P/E, subscriber growth if surfaced, capex/revenue |

If the sector is missing from `info`, say **"sector not identified — using
generic P/E + ROE read only"** and skip the sector-specific metrics.

## Step 7 — Corp events / news check (best effort)

If WebFetch is available, hit:
- NSE announcements: `https://www.nseindia.com/api/corporate-announcements?index=equities&symbol=<TICKER>`
- Yahoo Finance news: use `tk.news` from yfinance

Surface any of these in the card:
- Earnings date in the next 14 days (raises event risk)
- Board meeting, dividend, rights, split, bonus in the next 14 days
- Regulatory or governance flag in the last 30 days (SEBI, exchange notice, auditor change, promoter pledge > 10 %)

If both feeds fail, note "corp events unavailable — verify manually before
any action". Do not invent events.

## Step 8 — Render the analysis card

Use exactly this structure (Markdown, copy-friendly). Replace every
`<placeholder>` with real data. Skip a section only if the underlying
data was unavailable and say why.

```markdown
# <TICKER> — Deep Dive (<date IST>)

**Current price:** ₹<last_close>  · **Sector:** <sector> · **Mkt cap:** ₹<mktcap>cr

## Composite score: <NN>/90 — Grade <X>
Technical <n>/40 · Momentum <n>/25 · Volume <n>/15 · Sentiment <n>/10

## Momentum posture: <one-line summary from Step 4>
| Filter | State |
|---|---|
| Trend (Close > SMA50 > SMA200) | ✅ / ❌ |
| Donchian-55 breakout | ✅ / ❌ |
| Volume > 1.5× 20d avg | ✅ / ❌ (today <ratio>×) |
| RSI(14) in 55–75 band | ✅ / ❌ (now <value>) |
| Above 20-session VWAP | ✅ / ❌ (VWAP ₹<value>) |
| Not exhausted (TR < 2.5× ATR) | ✅ / ❌ |

## Technical read
- Price vs SMA20 / SMA50 / SMA200: <above / below / crossing>, describe alignment
- MACD: <bullish / bearish / crossing>, hist <positive / negative>
- Relative strength vs Nifty (63d): <±NN>%

## Key levels
- 55-day high: ₹<n>  · 55-day low: ₹<n>
- Suggested entry (if momentum posture is favourable): ₹<last_close>
- 2-ATR stop: ₹<n>  (ATR(20) is ₹<n>, so stop is <n> % below entry)
- 2R target: ₹<n>  (risk-reward 1:2)

## Fundamental posture (sector-aware)
- <metric per sector table in Step 6, with values>
- Verdict: <one line — Bullish valuation / Fair / Stretched / Expensive / Cheap-for-a-reason>

## Events / news watch (14-day)
- <list from Step 7 or "none surfaced">

## Composite verdict
<2–3 sentences describing the posture in plain English — what
the technical, momentum, valuation, and event pictures collectively
say. Descriptive, not directive.>

---
*Educational analysis only — not SEBI-registered investment advice. Past
data cannot predict future outcomes. Position sizing and stop-loss
placement are your responsibility. Verify every number independently.*
```

## Step 9 — After the card

If the user asked a specific question ("should I buy", "should I hold",
"is the entry good"), answer it separately in one paragraph AFTER the
card, in terms of the posture the card produced. Never contradict the
card. Never add new data that isn't in the card.

If the user asks for a follow-up ("what if RSI drops below 50", "what if
Nifty breaks 24000"), answer scenario-style — do not re-run the whole
card, just address the branch.

## When to say "not enough data"

- Fewer than 210 daily bars available (fresh listing) → say so, stop.
- yfinance `info` returns almost empty (some micro-caps) → skip the
  fundamental section entirely, say why.
- Data pull fails altogether → say the fetch failed and what to try
  (check ticker suffix, retry in a minute, use `.BO` instead of `.NS`).
  Do NOT fabricate a card from memory.

## Dependencies

- `yfinance` (preferred). If not installed: `pip install yfinance`.
- `pandas` — required for the indicator math.
- WebFetch — for the fallback path and corp events.

None of these depend on the NSE Smart Investor repo — this skill is
deliberately standalone so the user can invoke it from any chat, any
machine, any working directory.
