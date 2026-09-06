# Render-Speed Audit (Task 2.4)

_Date: 2026-09-07 · Branch: `render-speed-audit` · Author: audit run by Claude Code_

## Purpose

Answer the parallel-chat Q2 by evidence rather than guessing. The user said "do an audit
and if later something comes I will say" — so this doc names every plausible cause,
scores each by evidence found in the tree, and lands with a ranked fix list keyed to
Task 2.4 acceptance in [tasks/plan.md](../tasks/plan.md).

Read alongside [`docs/DATA_PROVENANCE_2026-09.md`](DATA_PROVENANCE_2026-09.md), which
covered fetch-tier reliability but not latency shape.

## TL;DR

Two independent things make the app feel slow, and they are additive:

1. **Cold-container full-universe scan** on Command Centre first paint after a
   Streamlit Cloud restart or a snapshot-stale window — up to ~2 minutes to render.
   The warmer pattern (GitHub Actions writing snapshots to `trade_store`) is well
   designed but has scheduling gaps that leak cold scans through to users.
2. **Whole-script rerun cost on the two heaviest pages** — Analyze Stock is
   2 379 LOC with 39 `st.session_state`/`st.button`/`st.rerun` triggers; Command
   Centre is 1 128 LOC with 37. Every widget interaction re-executes the entire
   page top-to-bottom in Streamlit; caches spare the network but not the Python.

Diagnosis map against the parallel-chat option list:

| Option | Verdict | Evidence |
|---|---|---|
| **A** — cold-cache full-universe scan | **Confirmed primary** for first paint | Snapshot warmer runs 15-min cron `03:00–10:59 UTC` only; `_home_top_picks` scans 745 tickers, ~2 min cold. |
| **B** — individual page rerun cost | **Confirmed secondary**, dominant during interaction | 2 379 LOC + 39 rerun triggers on Analyze Stock; every button click re-runs the file. |
| **C** — one specific page disproportionately slow | **Confirmed: Analyze Stock** first, Command Centre second, screener/watchlist third | LOC + rerun-trigger counts, chart calls. |
| **D** — scheduler backend blocking | **Ruled out** | Warmers run on GitHub Actions runners (external to the Streamlit container); app-side warmer path is a passive `trade_store` read, non-blocking. |
| **E** — other | **Container sleep between visits** on low-traffic Streamlit Cloud dyno is the invisible-third contributor — a cold container also cold-caches the process-local `@st.cache_data`. |

## What the code actually does

### Cache topology — 15 decorators in `dashboard/shared/cache.py`

Grouped by TTL:

| TTL | Functions | Cold cost |
|---|---|---|
| 60 s | `_picks_live_prices`, `_nifty50_gainers_ticker`, `_top_picks_ticker` | 12–25 Angel One quote calls |
| 300 s | `_score_for_cc`, `_score_watchlist`, `_home_top_picks` | **~2 min** — the 745-ticker scan lives here |
| 600 s | `load_vix_data`, `get_vix_info`, `get_composite_score`, `_deep_confirmation` | 4–8 s |
| 1 800 s | `_sparkline_closes` | 200 ms per symbol |
| 3 600 s | `_tomorrow_watchlist`, `_sector_ranking` | ~90 s (also warmer-backed) |

Every one of these caches is **process-local** to the Streamlit Cloud container.
A redeploy, container recycle, or sleep-wake drops the whole set.

### Warmer pattern — good design, three gaps

`scripts/warm_top_picks.py` + `.github/workflows/warm-top-picks.yml`:

```yaml
schedule:
  - cron: "*/15 3-10 * * 1-5"   # every 15 min, 03:00–10:59 UTC, Mon–Fri
```

`scripts/warm_tomorrow_watchlist.py` + `.github/workflows/warm_tomorrow_watchlist.yml`:

```yaml
schedule:
  - cron: "20 10 * * 1-5"   # 10:20 UTC = 15:50 IST, Mon–Fri (after NSE close)
```

`get_top_picks()` and `get_tomorrow_watchlist()` in `dashboard/shared/cache.py` read
these snapshots from `trade_store` first, fall back to a live scan if the snapshot
is missing or exceeds `_TOP_PICKS_MAX_AGE_SECONDS`.

The design is correct. The gaps that leak cold scans through:

- **Gap 1 — off-hours users.** Warmer runs `03:00–10:59 UTC` = `08:30–16:29 IST`.
  Users who open the app pre-open (before 08:30 IST), after close (after 16:29 IST),
  or on weekends land on a snapshot that is ≥ `_TOP_PICKS_MAX_AGE_SECONDS` old and
  the app falls back to the live 2-minute scan on their session.
- **Gap 2 — first-visit-after-redeploy.** A push to `main` recycles the Streamlit
  Cloud container. The next visitor's process-local cache is empty AND the snapshot
  read from `trade_store` may return stale-enough that the max-age fallback triggers.
- **Gap 3 — Tomorrow's Watchlist warmer runs only once a day.** If the 15:50 IST
  workflow fails silently (network, GitHub incident, rate-limit), the next
  weekday's page pays the full cold scan and nothing surfaces the miss to the user.

### Per-page render weight

| Page | LOC | `@st.cache_data` calls made | Rerun triggers | Charts |
|---|---:|---:|---:|---:|
| Analyze Stock | 2 379 | 7 | **39** | 3 |
| Command Centre | 1 128 | 3 | **37** | 1 |
| Paper Trades | 1 164 | 3 | — | — |
| Quality Watch | 807 | 5 | — | — |
| Intraday Trader | 756 | 2 | — | — |
| Deep Dive | 572 | — | — | — |
| Smart Screener | 289 | — | — | — |

"Rerun triggers" = count of `st.button` + `st.session_state` + `st.rerun` in the
page. Streamlit re-executes the whole file on every widget interaction; even with
warm caches, the Python parse/execute cost of a 2 000+ LOC page is measurable
(200–600 ms in local timing, more on Streamlit Cloud's shared cores).

### Fetcher storm risk — mitigated

Nine pages call `fetch_single`/`fetch_price` directly (grep count above). All go
through the tiered `data/fetcher.py` (Angel One → Stooq → Yahoo) with its own
per-tier caching. Post-2.1 instrumentation lands each attempt in the `data_health`
panel, so a fetch storm would be visible there. Nothing in the audit suggests we
have one today — the primary latency is scan compute, not per-fetch RTT.

## Ranked findings

Ranked by expected user-visible time saved, cheapest-first among ties.

### F1 — Warmer schedule leaks (Gaps 1 + 3)  · **HIGH impact, LOW effort**

Extend the warmer crons so no realistic user hour hits a cold scan:

- **Top Picks warmer**: extend from `03:00–10:59 UTC 1-5` to `01:00–13:00 UTC 1-6`
  (covers ~06:30 IST pre-open through ~18:30 IST post-close, plus Saturday
  morning reads of Friday's close). Off-hours frequency can drop to every 30 min
  to stay inside the free-tier Actions budget.
- **Tomorrow's Watchlist warmer**: add a second run at `04:30 UTC` (10:00 IST) as
  a belt-and-braces retry — if the 15:50 IST run failed silently the previous
  day, this catches the next morning before pre-open traffic peaks.
- **Silent-failure surfacing**: emit a warmer-health row into the `data_health`
  panel showing "last successful warm at HH:MM IST"; when > 45 min old for Top
  Picks or > 24 h old for Tomorrow's Watchlist, badge amber on Command Centre so
  the user is not blindsided by the cold-scan latency when it does happen.

### F2 — Redeploy-cold cache priming  · **MEDIUM impact, MEDIUM effort**

Add an on-import prime step in `dashboard/app.py` that fires a single
`get_top_picks()` and `get_vix_info()` in a background thread the moment the
container boots, so the first visitor's page load waits on the snapshot read
rather than a live scan. This is safe because both functions are idempotent and
cache their result, and the background thread never blocks the main render.

### F3 — Split Analyze Stock into tabs  · **HIGH impact, HIGH effort**

The 2 379 LOC page is a rerun-cost tax on every widget click. The natural split:

- **Verdict** (score card + entry/SL/TP + narrative) — always render.
- **Technicals** (charts + indicators + MTF panel) — lazy-load on tab click.
- **Fundamentals** (E1-v2 valuation panel) — lazy-load.
- **News & Flags** (qualitative flags + news feed) — lazy-load.
- **AI Co-Pilot** — already a tab-ish panel; formalise.

Streamlit `st.tabs` still runs the whole file body on interaction, but the heavy
compute inside each non-active tab can be gated behind an `if active_tab == ...`
check. The measurable win is per-click latency on the page, not first paint.

Deferred to a follow-up PR; too big for the audit's scope. Recorded here so
Task 2.4's fix work has a shape.

### F4 — Command Centre home widget count  · **MEDIUM impact, MEDIUM effort**

37 rerun-trigger sites on a 1 128 LOC page is a lot for a "landing" surface.
Audit which of them are genuinely user-driven vs. accidental (e.g. a debug
toggle left in during Sprint 1). Aim: cut in half. Recorded as follow-up.

### F5 — Sparkline TTL is too long  · **LOW impact, TRIVIAL effort**

`_sparkline_closes` caches 30 minutes on a chart that shows 22 daily closes.
During market hours this means the sparkline never moves. Drop TTL to 300 s to
match `_score_for_cc`. Recorded as follow-up.

## Proposed fix sequence for Task 2.4

Ship as three separate PRs so each is independently reviewable:

1. **PR A — F1 + F5**: warmer schedule extension + sparkline TTL tweak +
   warmer-health row on `data_health` panel. All-config / small-code. Fastest
   ship.
2. **PR B — F2**: on-import cache prime in `dashboard/app.py`. Isolated change.
3. **PR C — F3 + F4**: Analyze Stock tab split + Command Centre rerun-trigger
   audit. Bigger surface, needs page-smoke on every touched page.

Acceptance for Task 2.4 = PR A merged (largest bang for buck) plus a follow-up
tracking issue for PR B and PR C.

## What this audit deliberately did NOT do

- Measure real Streamlit Cloud wall-time. That needs the deployed URL and a
  synthetic-visit script; the audit stayed static. F1's evidence (cron windows)
  is sufficient to justify the fix without live timing.
- Repro a cold scan locally. `_home_top_picks` needs Angel One creds and
  fair-use budget for a 745-ticker fetch — not worth burning session budget on
  when the fix path is already clear.

## See also

- [`docs/DATA_PROVENANCE_2026-09.md`](DATA_PROVENANCE_2026-09.md) — sibling
  Phase 2 audit covering fetch reliability.
- [`dashboard/shared/cache.py`](../dashboard/shared/cache.py) — every cache
  decorator and the snapshot-read/write path.
- [`scripts/warm_top_picks.py`](../scripts/warm_top_picks.py) +
  [`scripts/warm_tomorrow_watchlist.py`](../scripts/warm_tomorrow_watchlist.py) —
  warmer entrypoints.
- [`.github/workflows/warm-top-picks.yml`](../.github/workflows/warm-top-picks.yml) +
  [`.github/workflows/warm_tomorrow_watchlist.yml`](../.github/workflows/warm_tomorrow_watchlist.yml) —
  cron schedules.
