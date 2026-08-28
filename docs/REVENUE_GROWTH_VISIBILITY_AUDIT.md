# Revenue Growth Visibility Audit

**Question:** is the platform's strongest evidence-backed return signal
(revenue growth, ρ ≈ +0.14, monotone quintiles, survives bull & bear —
FUNDAMENTAL_QUALITY_REPORT.md) receiving visibility proportional to its value?

**Answer: no — it has inverse prominence.** The strongest signal in five
studies is *secondary* on one page, *hidden behind a button* on another, and
**absent from every discovery surface** (screener, top picks, watchlists),
while weaker-or-non-return signals (Trend Quality ρ +0.04, Portfolio Fit
ρ ≈ 0, beta/correlation) are primary across the app.

*Audit only — no production changes made. Code references verified 2026-06-11.*

## 1. Surface inventory

| Surface | Where | Prominence | Detail |
|---|---|---|---|
| Analyze Stock | "📊 Fundamentals **(beta)**" section ([04_analyze_stock.py:486-521](dashboard/pages/04_analyze_stock.py)) | **Secondary** | One `st.metric` of four (Revenue CAGR, EPS CAGR, ROE, D/E), positioned below the score hero, chart and news; section still labelled "(beta)"; honest confidence captions already present |
| Analyze Stock | Thesis section (via `thesis_rules.py:82-85`) | **Tertiary** | Appears only as a bull-factor sentence when CAGR crosses the "strong" threshold; otherwise invisible |
| My Portfolio | Fundamental Quality table ([03_my_portfolio.py:601](dashboard/pages/03_my_portfolio.py)) | **Hidden** | "Rev CAGR %" column exists but only after clicking the opt-in "Score my holdings on fundamentals" button (network-gated by design) |
| Smart Screener | — | **Not surfaced** | No growth column, no growth filter — you cannot screen by the best signal |
| Command Centre / Top Picks | — | **Not surfaced** | Cards show TQ score, entry/SL/TP, sector, live price — no fundamentals |
| Tomorrow's Watchlist | — | **Not surfaced** | |
| My Watchlist | — | **Not surfaced** | |
| Market Live / Overview / Breadth | — | **Not surfaced** | (appropriate — these are market-level pages) |

## 2. Prominence vs evidence (the gap)

| Signal | Return evidence | Current prominence |
|---|---|---|
| **Revenue growth** | **ρ +0.14**, monotone, both regimes | Secondary ×1, hidden ×1, absent from all discovery surfaces |
| Trend Quality score | ρ +0.04 (persistence gauge) | **Primary on 6+ surfaces** (hero numbers, cards, sorting) |
| Portfolio Fit | ρ ≈ 0 returns (risk explainer) | Own titled section on Analyze Stock |
| Beta / correlation | risk-only | Primary on Portfolio risk section |
| Candlestick patterns | zero-to-negative (now unscored) | Still narrated on every analysis |

**Q3 answer:** the strongest evidence-backed signal is currently the *hardest*
to discover. A user can complete every core workflow (scan → pick → trade)
without ever seeing revenue growth.

## 3. UX recommendations (display-only; no new scores, composites, weights, or buy/sell advice)

| # | Change | Surface | Effort | Risk & mitigation |
|---|---|---|---|---|
| R1 | Add **"Rev Growth %" column** to screener results + an optional "min revenue growth" filter (plain data filter, not a recommendation) | Smart Screener | **M** (2–4h) | yfinance latency for N results → reuse the existing enrich-checkbox pattern + the engine's 5-day cache; show "—" when unavailable |
| R2 | **Promote Revenue CAGR to the score hero strip** on Analyze Stock as a chip/metric beside the TQ score (value + confidence, e.g. "Rev growth 19%/yr · high confidence") | Analyze Stock | **S** (<1h) | None — data already fetched on this page |
| R3 | Drop the "**(beta)**" label; rename section "Fundamentals"; keep Revenue CAGR first | Analyze Stock | **S** (minutes) | None |
| R4 | Add an **evidence tooltip/caption**: "5-year validation: the strongest return-linked metric tested (see FUNDAMENTAL_QUALITY_REPORT)" — honest framing, mirrors the Phase-1 disclosure pattern | Analyze Stock + wherever shown | **S** | Must keep neutral wording — link evidence, never imply "buy high growth" |
| R5 | Optional **growth chip on Top Picks / watchlist cards** when the value is already cached (never block card render on a fundamentals fetch) | Command Centre, watchlists | **M** (2–3h) | Latency → cached-only display; blank chip otherwise |
| R6 | My Portfolio: keep the opt-in gate (network cost is real) but mention revenue growth in the button caption so users know it's there | My Portfolio | **S** | None |

Priority order: **R2 + R3 + R4 first** (zero-risk, single page), then R1 (the
discovery gap), then R5/R6.

## 4. Risks (general)

- **Data honesty:** coverage is ~42% historically and confidence varies — every
  surface must keep the existing None/"—" convention and confidence captions
  (never a fabricated 0).
- **Advice creep:** revenue growth must be presented as *data with evidence
  context*, never as a buy signal — same discipline as the Phase-1 trend-quality
  relabel.
- **Latency:** fundamentals are network-fetched (≈3s/ticker cold, 5-day cache).
  Any multi-stock surface must be cached-only or opt-in.
- **Out-of-window risk:** the +0.14 finding comes from ~3–4 independent forward
  periods; the evidence captions should say "validated 2022-25" rather than
  implying permanence.

*Deliverable of the Revenue Growth Visibility Audit — product audit only; no
code changed. Implementation, if approved, starts with R2/R3/R4.*
