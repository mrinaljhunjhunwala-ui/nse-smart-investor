# Pre-Open Scan (Task 4.3)

_Date: 2026-09-07 · Branch: `preopen-scan-task-4-3`_

## What ships

A single new GitHub Actions workflow,
[`.github/workflows/warm-preopen-scan.yml`](../.github/workflows/warm-preopen-scan.yml),
that fires the existing Top Picks and Tomorrow's Watchlist warmer scripts
one extra time per day at **03:20 UTC = 08:50 IST, Mon-Fri**, roughly ten
minutes before NSE's pre-open session opens at 09:00 IST.

No new code, no new engine, no page changes in this PR. The app already
reads whichever snapshot in `trade_store` is freshest; this workflow
guarantees a snapshot generated within the last ~30 minutes is available
for every user visit between 09:00 IST and the next Top Picks warmer run
at 03:30 UTC.

## Why option A (extra run of existing engine)

The parallel-chat Q4 offered two shapes:

- **A**: extra 09:20 IST run of the existing scoring engine.
- **B**: dedicated opening-picture engine.

Option A picked because:

1. **Composite score is frozen at four pillars per Guardrail 5**. A dedicated
   opening-picture engine would either duplicate the existing scoring
   verbatim (no new information) or introduce a second scoring shape and its
   own regression surface, either of which is wasted effort for the pre-open
   use case. The value of a pre-open scan is _freshness_, not a new signal.
2. **The composite score is deterministic on close prices.** The last
   completed close before the market opens is yesterday's 15:30 IST close.
   Any scan run between then and 09:15 IST reads the same input. What
   changes across the overnight window is provider-side data availability:
   corp-actions posted overnight, delivery-% updates, sector-strength ranks
   that depend on FII/DII flow data settled late in the evening. Re-running
   the warmer picks those up automatically without any new engine code.
3. **The existing warmer scripts already handle this correctly.** Each
   writes idempotently to a well-known `trade_store` KV key. Firing them
   one more time in a distinct workflow does not risk data corruption or
   overlapping compute.

## Schedule reasoning

NSE session windows in UTC:

| Session | IST | UTC |
|---|---|---|
| Pre-open | 09:00-09:15 | 03:30-03:45 |
| Regular | 09:15-15:30 | 03:45-10:00 |
| Close | 15:30 | 10:00 |

Chosen cron: `20 3 * * 1-5` = **03:20 UTC = 08:50 IST**.

- Gives the ~2 min Top Picks scan and the ~2 min Tomorrow's Watchlist scan
  comfortable room to finish before pre-open user traffic starts hitting
  the page.
- Sits far enough after the previous night's US market close (typically
  01:00 UTC = 06:30 IST winter, 02:00 UTC in summer) that overnight
  provider updates for corp-actions, delivery, and FII/DII flows have had
  time to settle.
- Does not overlap the existing Top Picks warmer cadence: that one fires
  `*/15 3-10 * * 1-5`, whose earliest hit is 03:00 UTC and next is 03:15
  UTC. Pre-open workflow's 03:20 slot is a distinct concurrency group so
  the two never contend.

## Why not extend the existing warmer's cron instead

We considered adding `20 3 * * 1-5` directly to `warm_tomorrow_watchlist.yml`
rather than a new workflow. Rejected because:

1. **Separation of concerns**: Tomorrow's Watchlist warmer was designed for
   a single post-close daily run (see its long file docstring). Piling
   another cron onto it dilutes the intent. Pre-open freshness is a
   distinct requirement and deserves a distinct workflow file with its own
   docstring, timeout budget, and continue-on-error policy.
2. **Failure isolation**: the pre-open workflow runs BOTH warmers back to
   back and marks the second `continue-on-error: true` so a Tomorrow's
   Watchlist failure does not mask the Top Picks refresh. The existing
   workflow can not express this without conflating its own semantics.
3. **Ops visibility**: a distinct workflow appears as its own row in the
   Actions tab, so a pre-open failure is visible next to (not tangled
   with) the post-close warm. Diagnosis stays cheap.

## What this PR deliberately does NOT do

- **No new "Pre-Open Watch" page or panel.** The value ships the moment the
  snapshot is fresh; the existing Command Centre and Tomorrow's Watchlist
  pages already read `get_top_picks()` / `get_tomorrow_watchlist()` and
  will pick up the pre-open snapshot on the next visit. Adding a UI
  indicator ("last refreshed at 08:50 IST · pre-open scan") is a good
  follow-up and belongs in the `data_health` panel or as a caption; kept
  out of this PR so it stays workflow-only and needs no page-smoke run.
- **No changes to `scripts/warm_top_picks.py` or
  `scripts/warm_tomorrow_watchlist.py`.** They already work headlessly and
  are re-runnable idempotently. The workflow calls them verbatim.
- **No new dedicated pre-open KV key.** Both warmers write to their
  existing KV keys and the app reads whichever snapshot is freshest. A
  distinct pre-open snapshot only makes sense if the pre-open scan runs a
  DIFFERENT scoring engine, which option A explicitly does not.

## Follow-up worth doing (out of scope here)

- **UI freshness pill on the Command Centre `data_health` panel** showing
  "Pre-open warm: HH:MM IST" alongside the existing per-provider rows, so
  the user has a visible signal that the pre-open workflow ran (or an
  amber badge when it did not). One-liner change; keeps this PR
  workflow-only.
- **Consider a second pre-open slot at 03:35 UTC (09:05 IST)** if
  observations show the 08:50 IST run occasionally races the pre-open
  session open. Defer until we have evidence.

## Verification

- **Static**: workflow YAML validates as GitHub Actions syntax.
- **Runtime**: after merge, trigger `workflow_dispatch` manually from the
  Actions tab once to confirm both warmers complete and both KV keys
  update. Real cron takes effect on the next 03:20 UTC weekday after the
  PR merges.
- **Deployed effect**: on the first weekday after merge, verify that the
  `get_top_picks()` snapshot's `generated_at` is within ~30 min of 08:50
  IST on the Command Centre page loaded at 09:00 IST or later.

## Guardrail check

- §5 (composite score shape): unchanged - no new engine, no new pillar.
- §11 (module purity): no code changes to `analysis/` or `strategies/`.
- §21 (no em-dashes): workflow YAML and this doc use ASCII hyphens only.
- Page smoke: not required - no `dashboard/` changes.

## See also

- [`.github/workflows/warm-top-picks.yml`](../.github/workflows/warm-top-picks.yml) - existing every-15-min warmer.
- [`.github/workflows/warm_tomorrow_watchlist.yml`](../.github/workflows/warm_tomorrow_watchlist.yml) - existing daily post-close warmer.
- [`scripts/warm_top_picks.py`](../scripts/warm_top_picks.py) - warmer script (unchanged).
- [`scripts/warm_tomorrow_watchlist.py`](../scripts/warm_tomorrow_watchlist.py) - warmer script (unchanged).
- [`docs/RENDER_SPEED_AUDIT_2026-09.md`](RENDER_SPEED_AUDIT_2026-09.md) - Q2 audit, F1 finding about warmer schedule gaps that this workflow partially closes.
- [`tasks/plan.md`](../tasks/plan.md) - Task 4.3 in Phase 4.
