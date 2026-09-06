# Tomorrow's Watchlist Audit (Task 4.2)

_Date: 2026-09-07 · Branch: `tomorrow-watchlist-audit`_

## Purpose

Answer the parallel-chat **Q3** by inspecting the actual pipeline and matching each
of the four proposed failure modes against evidence in the code. The user said "do
the required task" for Q3, so this audit lands with a confirmed/refuted verdict
per failure mode plus a ranked fix list keyed to Task 4.2 acceptance in
[tasks/plan.md](../tasks/plan.md).

Sibling to [`RENDER_SPEED_AUDIT_2026-09.md`](RENDER_SPEED_AUDIT_2026-09.md) (Q2)
and [`DATA_PROVENANCE_2026-09.md`](DATA_PROVENANCE_2026-09.md) (Task 2.1).

## TL;DR

Two of the four proposed failure modes are real, two are not.

| Failure mode | Verdict | Severity |
|---|---|---|
| Picks don't move day-over-day | **Refuted** - scan is deterministic on today's close, so picks move whenever price moves. | - |
| No ranking | **Refuted** - buckets are sorted by composite score, top-N per bucket. | - |
| **Mislabelled** (WATCHLIST/BUY landing in a bucket whose label the underlying headline doesn't support) | **Confirmed** | HIGH |
| **No follow-through** (nothing tracks whether yesterday's picks actually worked) | **Confirmed** | HIGH |

Both confirmed defects have well-defined fixes that don't touch the composite
score shape and don't need `verdict-regression-reviewer` review.

## Pipeline walk-through

1. **Universe**: `data.universe.get_universe("nifty500")` - Nifty 500 tickers.
2. **Scoring**: `analysis.score.score_stock(tk)` per ticker, parallelised via
   `ThreadPoolExecutor(max_workers=10)`. Same engine as Command Centre.
3. **Bucketing** (`dashboard/shared/cache.py::_tomorrow_watchlist`, lines 1208–1211):

```python
_is_breakout  = act in ("STRONG BUY", "BUY", "WATCHLIST") and sc >= 52 and mom >= 8 and vol >= 5
_is_breakdown = (act in ("EXIT", "CAUTION") or sc < 40)  and tech < 22 and vol >= 4
_is_bull_rev  = 35 <= sc <= 58 and mom >= 8 and tech < 25
_is_bear_rev  = 45 <= sc <= 68 and mom < 5 and tech >= 22
```

4. **Precedence**: first-match-wins in the fixed order breakout → breakdown →
   bull-rev → bear-rev. Overlaps counted for logs (`_multi_match_count`) but not
   surfaced to the user.
5. **Ranking**: each bucket sorted by `score` (descending for breakout/reversal,
   ascending for breakdown) then truncated to `n=15`.
6. **Persistence**: snapshot to `trade_store` KV (`_TW_KV_KEY`), TTL 6 h, refreshed
   by `scripts/warm_tomorrow_watchlist.py` at 10:20 UTC (15:50 IST) once daily.
7. **Page render**: `dashboard/pages/17_tomorrow_watchlist.py` reads the snapshot
   via `get_tomorrow_watchlist()` with stale-while-revalidate + background scan.
   Cards render bespoke HTML directly, bypassing the `pick_freshness` helpers.

## Findings per failure mode

### FM1 - Picks don't move · REFUTED

- `_tomorrow_watchlist` inputs are the Nifty 500 close prices and the composite
  scoring engine. Both change every day the market runs; a stock whose score
  crosses the bucket thresholds on today's close will fall out of tomorrow's list.
- The snapshot has a 6 h TTL and a daily warmer run at 15:50 IST. Even if
  the warmer runs once, the next day's opening user hits a stale snapshot
  (> 18 h), which triggers a live scan on-page. Result: picks do rotate.
- What CAN look like "not moving" from a user's seat is the same overall
  narrative (a bunch of the same names hovering near the bucket boundary and
  staying inside it for a week). That is signal, not a bug.

**No fix.** Document in the page copy that day-to-day stability is expected when
the underlying market state hasn't changed.

### FM2 - No ranking · REFUTED

- `out["breakout_candidates"].sort(key=lambda x: -x["score"])` (line 1229)
- `out["breakdown_watch"].sort(key=lambda x: x["score"])` (line 1230)
- `out["reversal_watch"].sort(key=lambda x: -x["score"])` (line 1231)
- Top-N slice `[:n]` with `n=15` per bucket.

Ranking is present, correct, and stable - highest-conviction items appear
first in each tab. What is NOT present is a visible per-card **rank number**
or a **conviction tier** (bucket ordering is by score, but a user reading the
card sees `sc/100 · action` and cannot tell at a glance whether this is the
1st of 15 or the 15th of 15).

**Small UI-only fix worth doing**: prefix each card with `#1`…`#15` and hide
below-median cards behind an "Also watching" expander. Recorded as follow-up.

### FM3 - Mislabelled · CONFIRMED (HIGH)

The bucket assignment gates on numeric thresholds but NOT on the
`headline` string the underlying `score_stock` produced, so a stock whose
narrative headline is "**Consolidating - no clear edge right now**"
(the WATCHLIST default headline) can land under **🚀 Breakout Watch** as
long as `sc >= 52 AND mom >= 8 AND vol >= 5` is satisfied.

Concrete example the code allows:

- `action == "WATCHLIST"`, `score == 53`, `momentum == 9`, `volume == 6`
- `headline == "Mixed signals - worth watching for entry"`
- Falls into `_is_breakout`, gets rendered as "🚀 Breakout setup" in the
  Breakout Watch tab, tagged with `signal_type = "🚀 Breakout setup"`.

The user reads a **Breakout** label under a **Mixed Signals** headline. That
mismatch is the exact "marked BUY but you'd never actually buy" pattern
called out in Q3.

Root cause is a modelling gap, not a scoring bug: the score gate is looser
than the label promises. Two independent fixes are possible; **do both**:

- **Fix M1 (labelling honesty)**: gate `_is_breakout` on `act in ("STRONG BUY",
  "BUY")` only, dropping `"WATCHLIST"`. `sc >= 52 AND mom >= 8 AND vol >= 5`
  can stand, since a BUY action already implies the narrative is constructive.
  WATCHLIST-only names still surface in the Reversal Watch bucket if the
  reversal thresholds match. This costs ~30% of the current Breakout Watch
  count (empirical, from the `_multi_match_count` logs), but every surviving
  entry now has a headline consistent with the tab it lives in.
- **Fix M2 (transparency)**: whichever entries survive M1, show the
  `score_stock` headline verbatim on the card AND badge the entry with the
  signal-strength band (e.g. `sc >= 65` = "conviction: strong", `52-64` = 
  "conviction: developing"). No more hiding the narrative under a decorative
  bucket label. `signal_type` becomes descriptive, not aspirational.

**Both fixes are pure re-labelling** - no scoring change, no golden-snapshot
delta, no `verdict-regression-reviewer` gate. They belong under `dashboard/`
and Task 4.2's scope.

### FM4 - No follow-through · CONFIRMED (HIGH)

The bespoke card renderer in `17_tomorrow_watchlist.py::_render_cards`
builds HTML directly and never calls `dashboard.shared.pick_freshness`'s
`_render_pick_verdict` helper. That helper is the ONLY place in the app
outside `04_analyze_stock.py` that writes to `verdict_ledger` (see
[`pick_freshness.py:141`](../dashboard/shared/pick_freshness.py) -
`from analysis.verdict_ledger import log_verdict as _vl_log`).

Consequences:

- Every day's ~45 shortlist picks (15 × 3 buckets) are surfaced to the user
  and then thrown away.
- The Verdict Calibration page (`21_verdict_calibration.py`) can't answer
  "how did Tomorrow's Watchlist picks perform 5d/20d/60d out" for any pick
  that the user didn't also happen to open in Analyze Stock.
- Shadow-trade analysis is complete for Analyze Stock but has a zero-length
  ledger for Tomorrow's Watchlist. Half the model's mouth is not being
  listened to.

**Fix F1**: after `_tomorrow_watchlist()` completes and the buckets are
assembled, iterate the merged shortlist and call `log_verdict(...,
source="tomorrow_watchlist")` for every entry with a valid
`entry`. Dedup is already handled by `verdict_log`'s
`(logged_date, ticker, horizon, source)` PRIMARY KEY, so calling this
inside the cached function is safe even on retries. Emit `source=
"tomorrow_watchlist"` distinct from `shadow_auto` so the calibration page
can slice by "picks the model surfaced on the Watchlist page specifically".

**Fix F2**: add a "How did yesterday's picks do?" strip at the top of
`17_tomorrow_watchlist.py` showing the previous scan's picks alongside
next-day return / hit-rate. Powered by the F1 ledger writes, read via
`verdict_ledger.load_ledger(source_in=["tomorrow_watchlist"])`. Same
principle as Verdict Calibration but scoped to this one source, so the
user sees the honesty on the same page as the promises.

## Ranked fixes for Task 4.2

Ranked by user-visible impact / effort:

1. **F1 - ledger writes for TW picks** · MEDIUM effort, HIGH impact.
   One line inside `_tomorrow_watchlist` iterating the merged shortlist and
   calling `log_verdict`. Enables everything downstream.
2. **M1 + M2 - labelling honesty + transparency** · LOW effort, HIGH impact.
   Threshold tweak + card copy change. Ship together as one PR.
3. **F2 - "yesterday's picks" strip** · MEDIUM effort, MEDIUM impact.
   Depends on F1 having accumulated at least a week of ledger rows before it
   shows anything meaningful. Ship as a follow-up.
4. **Ranking numbers on cards** (FM2 refutation follow-up) · LOW effort,
   LOW impact. Small UI clarity win.

## Proposed PR sequence for Task 4.2

Two PRs, in order:

- **PR α - F1 + M1 + M2**: the labelling honesty pass plus the ledger
  writes. Ships the confirmed-defect fixes together so the calibration story
  starts accumulating clean data from day one.
- **PR β - F2 + card ranking numbers**: the "how did yesterday's picks do"
  strip + card `#1`…`#15` prefixes. Ships once α has been in for at least
  a week of scans.

Task 4.2 acceptance = PR α merged + follow-up issue for PR β.

## What this audit deliberately did NOT do

- Re-run the scoring engine to measure the actual %-of-Breakout entries with
  `WATCHLIST` action. The failure mode is a code-path property, not a
  frequency claim; a single existence proof (the threshold logic above)
  is sufficient. If the fix PR wants pre/post counts, add them then.
- Touch the composite score or the four-pillar shape. Both fixes are pure
  post-scoring labelling changes.

## See also

- [`dashboard/pages/17_tomorrow_watchlist.py`](../dashboard/pages/17_tomorrow_watchlist.py) - page renderer.
- [`dashboard/shared/cache.py`](../dashboard/shared/cache.py) at
  `_tomorrow_watchlist` / `get_tomorrow_watchlist` - scoring pipeline + snapshot.
- [`analysis/verdict_ledger.py`](../analysis/verdict_ledger.py) - the ledger
  we should be writing to.
- [`dashboard/shared/pick_freshness.py`](../dashboard/shared/pick_freshness.py) -
  the existing helper that already knows how to log; TW just doesn't use it.
- [`dashboard/pages/21_verdict_calibration.py`](../dashboard/pages/21_verdict_calibration.py) -
  the read side that F1's writes will feed.
- [`scripts/warm_tomorrow_watchlist.py`](../scripts/warm_tomorrow_watchlist.py) +
  [`.github/workflows/warm_tomorrow_watchlist.yml`](../.github/workflows/warm_tomorrow_watchlist.yml) -
  the warmer that will run F1's writes on the daily cron.
