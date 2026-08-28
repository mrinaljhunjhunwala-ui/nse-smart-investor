# Finance-Feature Audit & Roadmap — NSE Smart Investor

**Goal:** identify the highest-impact *missing investment analytics* and sequence them by
**impact vs engineering effort**. No code in this pass — this is the plan.

**One-line framing:** the platform today is a strong **technical / trading** tool (price,
momentum, signals, paper trades, backtests). The biggest gaps are the **portfolio-risk** and
**fundamental** layers that turn it into an **investor** platform. Notably, one cheap enabler —
a *portfolio equity (NAV) curve* — unlocks four of the six requested risk metrics at once, and
**Beta is already implemented but not surfaced**.

---

## Current state — present vs missing

### 1. Portfolio Risk
| Metric | Status | Note |
|---|---|---|
| Sharpe | ❌ Missing (portfolio) | per-ticker only, inside the backtest (`backtesting.py`) |
| Sortino | ❌ Missing | — |
| Calmar | ❌ Missing | — |
| Max Drawdown | ❌ Missing (portfolio) | per-ticker only in backtest |
| **Beta** | 🟡 **Built, not surfaced** | `analysis/hedging.py` computes stock + portfolio beta vs Nifty (+ contribution) — **no UI** |
| Correlation matrix | ❌ Missing (holdings) | a *macro-asset* correlation heatmap exists on the Macro page; not the user's holdings |

> **Keystone gap:** there is **no portfolio NAV/equity time-series** (mark-to-market is point-in-time). Reconstruct it (holdings × historical prices — the fetcher already serves these) and Sharpe, Sortino, Calmar, Max Drawdown **all** follow from one build.

### 2. Fundamental Analysis — ❌ entirely absent
Revenue CAGR, EPS CAGR, ROE, ROCE, Debt/Equity, Free-Cash-Flow trends: **none present.** Only earnings *dates* exist (`data/events.py`, for buy-timing). This is the single largest *category* gap for an "investor" product.

### 3. Position Analytics
| Capability | Status |
|---|---|
| Sector exposure | ✅ Present (`PortfolioDiversification.sector_weights`) |
| Concentration risk | 🟡 Present but **qualitative/heuristic** (top-sector % + sector count) — no HHI, no stock-level |
| Position contribution | 🟡 Partial (per-holding P&L shown; weighted *contribution-to-return* not explicit) |
| Risk contribution | ❌ Missing (beta-contribution computed in `hedging.py` but unused; no volatility/marginal risk contribution) |

### 4. Investor Reporting
| Item | Status |
|---|---|
| Thesis summary | 🟡 Partial — the score `narrative`/`headline` is an *implicit* thesis blob |
| Bull case | ❌ Missing (no structured output) |
| Bear case | ❌ Missing |
| Risk factors | ❌ Missing |

---

## Per-capability assessment

Effort: **S** ≈ ≤1 day · **M** ≈ 2–4 days · **L** ≈ 1–2+ weeks (incl. data plumbing). Value for a retail Indian-equity investor.

| # | Capability | Why it matters | Effort | Value |
|---|---|---|---|---|
| A | **Surface Beta** (already computed) | Market sensitivity + hedge sizing; the work is done — only wiring `hedging.py` into the Portfolio page. | **S** | Med-High |
| B | **Portfolio NAV curve → Sharpe / Sortino / Calmar / Max DD** | The core "how risky is my portfolio, and is the return worth it?" answer. Sortino (downside-only) and Calmar (return ÷ max-DD) are what serious investors actually track. One enabler → four metrics. | **M** | **High** |
| C | **Holdings correlation matrix** | Reveals *false* diversification (10 stocks that move together). Heatmap component already exists on the Macro page — reuse it on real holdings. | **S-M** | Med-High |
| D | **HHI + stock-level concentration** | Upgrades the qualitative sector label to a rigorous Herfindahl index incl. single-name concentration ("38% in 2 names"). | **S** | Medium |
| E | **Position contribution to return** | Which holdings actually drove P&L (weight × return), not just absolute ₹. Standard attribution. | **S** | Medium |
| F | **Risk contribution (component)** | Which holding contributes most *risk* (not capital) — marginal contribution to portfolio volatility / beta. Reuses beta-contrib in `hedging.py`. | **M** | Medium |
| G | **Structured thesis / Bull / Bear / Risk factors** | Turns the score blob into a decision-grade brief: 3 bull points, 3 bear points, explicit risks. Rules-based from existing score components + technicals now; far richer once fundamentals (H) land. | **M** | **High** |
| H | **Fundamental engine** (Revenue/EPS CAGR, ROE, ROCE, D/E, FCF) | The defining gap between a *trading* tool and an *investing* tool — quality, profitability, leverage, cash generation. **Complexity is dominated by data acquisition**: free NSE fundamentals are sparse/inconsistent (yfinance `.financials` is patchy for `.NS`; reliable = screener.in scrape or a paid API). | **L** | **High (strategic)** |

---

## Roadmap — prioritised by impact ÷ effort

```
            HIGH VALUE
                │  B  Portfolio Sharpe/Sortino/Calmar/MaxDD
        G ──────┤  A  Surface Beta (already built)
   Bull/Bear/   │  C  Holdings correlation
   Risk         │
   ─────────────┼───────────────────────────────  H  Fundamentals
        E,F,D   │                                  (high value, high effort,
   Contribution │                                   data-source dependent)
   & HHI        │
            LOW EFFORT ──────────────────► HIGH EFFORT
```

### Phase 1 — Quick wins (highest impact ÷ effort) — ~1 week
1. **A · Surface Beta** — it's already computed; just expose stock + portfolio beta on the Portfolio page. *Near-zero effort, immediate credibility.*
2. **B · Portfolio risk metrics** — build the NAV reconstruction once, then render **Sharpe, Sortino, Calmar, Max Drawdown**. *Single highest-leverage build.*
3. **C · Holdings correlation matrix** — reuse the existing heatmap on real holdings' returns.

### Phase 2 — Position-analytics depth — ~0.5 week
4. **D · HHI + stock-level concentration**, **E · contribution-to-return**, **F · risk contribution** — all build on Phase-1's NAV/returns + the existing beta-contribution; ship together.

### Phase 3 — Investor reporting — ~0.5 week
5. **G · Structured Thesis / Bull / Bear / Risk factors** — rules-based, assembled from the existing composite-score components, technicals, beta and concentration. Ships value immediately; auto-enriches when Phase 4 lands.

### Phase 4 — Fundamentals (strategic, biggest lift) — ~2+ weeks
6. **H · Fundamental engine** — *first decision is the data source* (yfinance financials vs screener.in scrape vs paid API), consistent with the platform's tiered-data philosophy. Then ROE, ROCE, Revenue/EPS CAGR, D/E, FCF, surfaced on Analyze Stock + folded into the Bull/Bear brief (G).

---

## Recommendation

Do **Phase 1 first** — it's the best return on effort and answers the questions investors ask most ("is my risk-adjusted return any good?"), and **A is essentially free**. Treat **H (fundamentals)** as the headline *strategic* investment: highest absolute value but gated on a data-source decision, so sequence it last and de-risk the data layer before building UI on top. Phases 2–3 are cheap depth that make the platform feel complete and set up the fundamental layer to shine.

*No features implemented in this pass — this document is the plan. Say which phase to start and I'll break it into tickets.*
