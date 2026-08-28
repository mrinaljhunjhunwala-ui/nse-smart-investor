# Revenue Growth Discovery Impact Audit

**Question:** what would a Revenue-Growth column + filter actually do to Smart
Screener discovery?

**Recommendation: PROCEED WITH CONSTRAINTS.** Current coverage is near-complete
(96.3%), missing-data risk is small (8 stocks) and sector-neutral, and moderate
filters preserve the Trend-Quality profile. The constraints exist because
aggressive thresholds (>15–20%) concentrate discovery into Finance and silently
discard most top-Trend-Quality names.

> Produced by `research/revenue_growth_discovery.py` (read-only; uses the same
> fundamentals engine call the screener column would use). No UI or screener
> changes made. Regenerate anytime — data: `research/output/rg_discovery.csv`.

## Q1 — Coverage (current universe, 217 liquid NSE names)

- **96.3% have Revenue CAGR today** (209/217). Note this is *current* coverage —
  the historical efficacy study's 42% reflected point-in-time replay limits,
  not what screener users would see now.
- **All values carry "medium" confidence** (Yahoo's ~4–5y statement depth) —
  the existing confidence-caption convention must ship with the column.
- **By sector:** no hole — worst is Chemicals at 89%; ten sectors at 100%.
- **By cap bucket (mcap proxy = last close × shares; disclosed approximation):**
  Large 100%, Mid 100%, Small 100% — the 8 missing names are also the ones
  without a cap proxy (statement-sparse tickers, spread across 6 sectors).

## Q2/Q4 — Filter impact (simulated on today's universe)

| Filter | Stocks kept | % of universe | Avg TQ | Top-decile TQ retained | Top sector share | Sector HHI | Large % / Small % |
|---|---|---|---|---|---|---|---|
| > 0% | 194 | 89% | 25.4 | 20/21 | Finance 12% | 738 | 24 / 28 |
| > 5% | 154 | 71% | 25.9 | 19/21 | Finance 15% | 804 | 25 / 27 |
| > 10% | 119 | 55% | 26.2 | 16/21 | Finance 18% | 883 | 27 / 22 |
| > 15% | 71 | 33% | 25.5 | 8/21 | Finance 25% | 1,168 | 28 / 20 |
| > 20% | 32 | 15% | 23.3 | **2/21** | **Finance 34%** | 1,660 | 25 / 19 |

Readings:
- **Up to >10%, the filter is well-behaved:** keeps half the universe, average
  Trend Quality is *unchanged or slightly better*, sector mix stays diversified
  (HHI < 900), cap mix stays balanced.
- **At >15% it starts distorting; at >20% it breaks discovery:** only 32 names
  survive, Finance becomes a third of all results (HHI 1,660 = concentrated),
  and **19 of the 21 top-decile Trend-Quality stocks disappear** — the user
  would believe "nothing is trending" when in fact the filter removed them.

## Q3 — Missing data vs negative growth

| Outcome a user would see | Count | % |
|---|---|---|
| "—" (no data) | 8 | 3.7% |
| Negative growth (real) | 15 | 6.9% |
| Positive growth | 194 | 89.4% |

Missing data is small and **not sector-concentrated** (spread 1–2 per sector).
Accidental-exclusion risk from a naive filter is bounded at 3.7% — real but
easily neutralised by an explicit missing-data rule (below).

## Q5 — Product risk assessment

| Risk | Verdict |
|---|---|
| Improve discovery? | **Yes** at moderate thresholds — surfaces the strongest evidence-backed signal with no TQ distortion (avg TQ stable, ≥76% top-decile retention up to >10%) |
| Distort discovery? | **Yes at high thresholds** — >15–20% concentrates into Finance and silently removes most top-TQ names |
| Survivorship bias? | No *new* bias — the universe is already current constituents (existing platform-wide caveat); the filter doesn't add to it |
| Data-availability bias? | **Small (3.7%) but real** if missing is treated as "fails the filter" — must be handled explicitly |

## Recommendation — Proceed with constraints

1. **Filter default = OFF ("Any")** — the column informs by default; filtering
   is the user's explicit choice.
2. **Offer thresholds 0 / 5 / 10 / 15 only.** Do not offer >20% (or show a
   concentration warning if a free-input field is used): at that level the
   result set is 32 names, 34% one sector, and 19/21 top-TQ names are gone.
3. **Missing-data rule:** stocks without data show "—" and are **included by
   default** when a filter is active, with a toggle "exclude stocks without
   growth data" (default off). Never silently drop the 8 names.
4. **Ship the confidence convention with the column** (all values are
   currently "medium" confidence) and the existing evidence caption
   (`render_revenue_growth_evidence`) — data with context, not advice.
5. **Re-run this audit when FY2026 statements land** (coverage and confidence
   improve mechanically each year).

*2026-06-11 · 217-name universe · current-data audit (not point-in-time) ·
no implementation performed.*
