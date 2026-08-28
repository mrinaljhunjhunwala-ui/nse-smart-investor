# Revenue Growth Visibility — Phase 1 Implementation Report

Implements **R2 + R3 + R4 only** from REVENUE_GROWTH_VISIBILITY_AUDIT.md.
Display-only: no Trend Quality / Portfolio Fit changes, no new score, no
ranking or Top-Picks ordering change, no buy/sell recommendation, no research
harness changes.

## What changed

| Task | Change | File |
|---|---|---|
| 1 · Hero visibility (R2) | The Analyze Stock headline metric row is now **5 chips**: Price · Sector · VIX Regime · Sector Rank · **Rev Growth /yr** — same `st.metric` hierarchy as the others, visible without scrolling. Value from the existing fundamentals engine (service-cached, reused by the section below); shows **"—"** when unavailable (never a fabricated 0). Tooltip carries the confidence level and the evidence framing. | [04_analyze_stock.py](dashboard/pages/04_analyze_stock.py) |
| 2 · "(beta)" removed (R3) | "📊 Fundamentals (beta)" → "📊 Fundamentals". No other wording in the section changed. | same |
| 3 · Evidence disclosure (R4) | New reusable `render_revenue_growth_evidence()` — *"Revenue growth has been the strongest return-predictive signal identified in platform research (2022–2025 validation). Historical relationships may not persist in future market environments — a measured observation, not a buy signal."* Rendered under the hero chip (when a value exists) and under the Fundamentals metric row. No recommendation, no forecast, no certainty. | [disclosures.py](dashboard/shared/disclosures.py) |
| 4 · Documentation (R4) | Investor Guide gains a **"Fundamentals — and the Revenue Growth signal"** section: fundamentals are deliberately separate from the Trend Quality Score (blending reduced signal quality), revenue growth is a research-backed *measured observation*, not a recommendation, and high growth says nothing about valuation/risk/timing. | [15_investor_guide.py](dashboard/pages/15_investor_guide.py) |
| Consistency fix (in scope: display-only honesty) | The hero score-breakdown still showed a dead **"Pattern (10): 0"** bar left over from the pattern removal — removed; breakdown now lists the four scored components only. | 04_analyze_stock.py |

## Verification (deliverables 3 & 4)

- **No scoring logic changed:** `git diff analysis/ trading/ backtest/ research/ strategies/` → **empty**. Changed files are exactly the three UI files above.
- **No ranking / action-label / recommendation changes:** no page computes or sorts on revenue growth; the chip and captions are pure display.
- **Full test suite: 300 passed** · **page smoke: 18 passed** (all pages render).
- **Screenshots:** not capturable from this environment (CLI); the table above is
  the authoritative before/after record — the chip appears in the Analyze Stock
  headline row after deploy.

## Success criteria check

A user opening Analyze Stock now sees Revenue Growth **immediately** (hero
chip), understands **it matters** (evidence caption + tooltip), and that it is
**not a buy signal by itself** (explicit in the caption, tooltip, and the
Investor Guide section).

---

# R1 Addendum — Smart Screener Column + Filter

Implements **R1 only**, following REVENUE_GROWTH_DISCOVERY_AUDIT.md exactly.

## What changed ([06_smart_screener.py](dashboard/pages/06_smart_screener.py))

| Task | Implementation |
|---|---|
| 1 · Column | Result cards gain a 6th metric, **"Rev Growth /yr"** (existing fundamentals engine; "—" when unavailable; tooltip carries the not-a-buy-signal framing). The value also flows into the CSV export automatically. **Sorting is untouched** — results remain ordered by trend-quality score only. |
| 2 · Filter | Selectbox **Any / >0% / >5% / >10% / >15%**, default **Any**. **No >20% option** (the audit showed it concentrates results 34% into one sector and removes 19/21 top-TQ names) — the help text says why. |
| 3 · Missing data | Stocks without growth data **remain visible by default** and show "—". Explicit toggle "Exclude stocks without growth data", default **OFF**. When a filter is active, a caption reports "X of Y kept (incl. N without growth data)". |
| 4 · Evidence | Reuses `render_revenue_growth_evidence()` above the results — research-backed observation, not a recommendation, may not persist. |
| 5 · Performance | Growth fetched only for the (small) result set, 8 parallel workers with a **hard 30s budget** — anything not back in time degrades gracefully to "—". Never blocks the scan itself. |

## Verification

- **Ranking unchanged when filter disabled:** with "Any" + toggle off, the
  signals list is never subset or reordered — the filter block is a pure
  pass-through. With a filter active, it *subsets only* (order preserved), and
  the caption states this.
- **Top Picks, watchlists, Trend Quality, Portfolio Fit, Thesis: untouched** —
  `git diff analysis/ trading/ backtest/ research/ strategies/` is empty; the
  only changed file is the screener page.
- **Full suite: 300 passed · page smoke: 18 passed.**
- Screenshots: not capturable from this CLI environment; this table is the
  before/after record.

## Success criteria

Users can now see Revenue Growth on every screener result, filter by the
audit-approved moderate thresholds, keep missing-data stocks by default, and
explore the strongest evidence-backed signal — with zero change to how the
platform ranks stocks.

*2026-06-11 · R5/R6 (cached chips on picks/watchlists, portfolio button
caption) remain open per the audit's priority order.*
