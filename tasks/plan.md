# Implementation Plan: NSE Smart Investor - Major Improvements

_Last updated: 2026-09-08 · Refreshed against merged PRs from the 2026-09-06 through 2026-09-08 sessions._

## Overview

Follow-on plan from the 2026-09-01 UI + market-analysis audit (Artifact:
[Dealing Room Audit](https://claude.ai/code/artifact/ec24b844-f044-425e-ab3a-606051b69421)),
revised against constraints that surfaced after the audit was written:

1. **`nse-app-guardrails` §5** forbids adding a 5th component to the composite
   score. The audit's Sprint 2 recommendation is re-shaped as an overlay or
   routed through golden-snapshot review + human ratification.
2. **`page-smoke-check`** is a mandatory tail step of every `dashboard/` edit.
3. Two subagents exist (`verdict-regression-reviewer`, `data-provenance-auditor`)
   and are prerequisites for scoring / fetcher work.
4. Guardrails §14-16 reference a "post 2026-09-02 data-provenance audit" and
   reliability work is on the critical path.
5. **`ai-copilot-context`** describes an AI panel being built under
   `dashboard/shared/ai/` and the plan integrates it.
6. House style §21: no em-dashes anywhere in code, docs, or plan. This
   document uses en-dash and hyphen only.

## Architecture Decisions

- **Composite score shape is frozen at 4 pillars, 40+25+15+10, 0-90.** Any new
  factor lands as one of: (a) a narrative-only append, (b) a sidecar
  `overlay_score` that never rewrites `CompositeScore.score`, or (c) a
  proposed shape change that goes to `verdict-regression-reviewer` + human
  ratification before merge. No exceptions.
- **Design tokens live in `dashboard/shared/design.py` as CSS custom
  properties.** Rule enforced by lint: no raw hex in files under
  `dashboard/pages/`.
- **AI co-pilot work follows `ai-copilot-context` exactly.** The three-layer
  context assembly (persona + live state + conversation) is the contract; the
  panel is wired into pages one at a time.
- **Data-provenance and page-smoke run before every commit** to `main`.

## Task Status

### Phase 0 · Quarantine and land in-flight work · **COMPLETE**
- Task 0.1: Audit + land in-flight `data/` and `analysis/fundamentals/`
  edits - shipped
- Task 0.2: Audit + land in-flight `dashboard/pages/04_analyze_stock.py`
  edit - shipped
- Task 0.3: Commit design-tokens block - shipped

### Phase 1 · UI foundation (Sprint 1) · **COMPLETE**
- Task 1.1: Design-token block shipped
- Task 1.2: Command Centre + Analyze Stock migrated off inline hex
- Task 1.3: `panel()` + `stat()` shipped in `ui_components.py`
- Task 1.4: Verdict Card hero on Analyze Stock shipped
- Task 1.5: Emoji cleanup across all 20 pages shipped
- Task 1.6: Pre-commit CSS-hex lint hook shipped
- **Checkpoint 1**: closed by PR #60 (docs/UI_AUDIT_2026-09_SPRINT1.md)

### Phase 2 · Data reliability and provenance · **COMPLETE**
- Task 2.1: `data-provenance-auditor` run - shipped (PR #55,
  docs/DATA_PROVENANCE_2026-09.md); found + fixed 2 HIGH bugs (PR #56:
  NSE corp-info URL retirement, Screener P/B silent-None)
- Task 2.2: Bare `[0]` / `.get(k) or []` fetcher patterns converted -
  shipped as part of #56
- Task 2.3: `data_health` panel on Command Centre - shipped PR #58, extended
  6->9 providers PR #59, warmer-health probes added PR #64
- Task 2.4: **Render-speed root cause and fixes - COMPLETE**. Answers to Q2
  and full fix set:
  * Audit doc: PR #61 (docs/RENDER_SPEED_AUDIT_2026-09.md)
  * F1 warmer schedule extensions + F5 sparkline TTL + warmer-health
    probes: PR #64
  * F2 on-import cache prime: PR #66
  * F3 Analyze Stock tab shell: PR #68; F3 lazy tabs via @st.fragment: PR #69
  * F4 Command Centre Market Pulse in @st.fragment: PR #70
- Task 2.5: Canary tests for uncovered providers - shipped PR #57
- **Checkpoint 2**: closed. All Task 2.x work landed.

### Phase 3 · Signal integration · **COMPLETE**
- Task 3.1: Relative Strength vs Nifty inside Momentum pillar - shipped,
  passed verdict-regression-reviewer
- Task 3.2: FII/DII 5d sign inside Sentiment pillar - shipped
- Task 3.3: TQS x valuation overlay sidecar - shipped PR #49
- Task 3.4: NSE delivery % as Volume-pillar sub-signal - shipped
- Task 3.5: Regime-adaptive stop-loss bounds - shipped
- Task 3.6: Regime-conditional weight dispatch (Rec 5) - shipped PR #46,
  default-on via NSE_USE_REGIME_WEIGHTS env flag
- Positioning pillar (Rec 6) 6b additive shipped PR #50,
  default-on via NSE_USE_POSITIONING_PILLAR env flag
- **Checkpoint 3**: closed.

### Phase 4 · Operations · **MOSTLY BLOCKED**
- Task 4.1: **Alerts channel - BLOCKED on user**. Q1 was paused
  mid-session. Gmail SMTP was the recommended path (Discord MCP not
  wireable in this environment). No PRs opened; awaiting go / no-go / new
  channel choice.
- Task 4.2: Tomorrow's Watchlist failure-mode audit and fixes:
  * Audit doc + verdicts: PR #62
    (docs/TOMORROW_WATCHLIST_AUDIT_2026-09.md). FM3 mislabelled + FM4 no
    follow-through both CONFIRMED HIGH.
  * PR alpha (F1 ledger writes + M1 tighten gate + M2 conviction chip):
    shipped PR #65
  * PR beta (F2 "yesterday's picks" strip + rank number chip): rank
    chip shipped PR #67. Yesterday's picks strip is **DATA-BLOCKED**
    until ~2026-09-14 (needs ~1 week of ledger accumulation from #65's
    `source="tomorrow_watchlist"` writes).
- Task 4.3: Pre-open scan - shipped PR #63 (Q4 option A: extra 08:50 IST
  run of existing engine, warm-preopen-scan.yml workflow +
  docs/PREOPEN_SCAN.md).
- Task 4.4: Data reliability follow-through from Phase 2 findings -
  absorbed into Task 2.4 fixes; nothing separate to ship.

### Phase 5 · AI co-pilot MVP · **COMPLETE**
- Task 5.1: Gap analysis doc - shipped PR #51 (docs/AI_COPILOT_STATUS.md)
- Task 5.2: Layer 1 persona + rules + SEBI regex post-filter - shipped
- Task 5.3: Layer 2 live state collector - shipped PR #52, fills 15 of ~20
  skill-spec fields
- Task 5.4: Panel wiring cleanup + portfolio wiring - shipped PR #53
- Task 5.5: 100-prompt SEBI compliance test suite - shipped PR #54
- **Checkpoint 5**: closed.

### Checkpoint: Overall
- [x] All Phase 1 acceptance met, screenshots archived (PR #60)
- [x] `data-provenance-auditor` and `verdict-regression-reviewer` runs
      recorded
- [x] Composite score shape unchanged (4 pillars, 40+25+15+10, 0-90)
- [x] House style §21 (no em-dashes) enforced on all changed files this cycle
- [x] All 20 pages green under `page-smoke-check` on every touched PR
- [x] Guardrail review checklist passed on every changed file

## Open Questions (what actually needs a decision from the user)

Only two items still block work. Every other Q from the previous plan
revision has been answered and shipped.

- **Q1 (still open): Alerts channel for Task 4.1.**
  Was paused mid-session on 2026-09-07. Options:
  * **Gmail SMTP** (recommended - app password in Streamlit secrets,
    digest email on signal changes / VIX spikes / watchlist upgrades,
    searchable paper trail, no extra client).
  * **Some other easy-to-acknowledge channel** you have in mind.
  * **Cancel Task 4.1** - if alerts are not a real need right now, mark
    the task dropped and remove it from the plan.

- **Q7 (new): The two working-tree files.**
  `.streamlit/claude mcp add github.txt` and `docs/UI_UX_BACKLOG.md` have
  been sitting untracked across ~15 PRs this session. I have not touched
  them. Options:
  * **Keep + commit** - if they are yours in progress, tell me to land
    them.
  * **Delete** - if they were scratch, tell me to remove them.
  * **Leave alone** - if you plan to handle them yourself.

## What's already been decided (do not re-litigate)

- **Q2 (render-speed)**: A + B + C all confirmed as simultaneous causes;
  D ruled out. All fixes shipped in PRs #64, #66, #68, #69, #70.
- **Q3 (Tomorrow's Watchlist)**: FM3 mislabelled + FM4 no follow-through
  both confirmed. Fixes shipped in PRs #65, #67. Data-blocked strip
  auto-unblocks ~2026-09-14.
- **Q4 (pre-open scan)**: Option A (extra 08:50 IST warmer run) shipped
  in PR #63.
- **Q5 (composite-score shape)**: Frozen at 4 pillars per Guardrail 5;
  Phase 3 all shipped inside that shape.
- **Q6 (in-flight edits)**: Landed via Phase 0 earlier in the cycle.

## Data-blocked items (auto-unblock on a date, no action required)

- **Task 4.2 PR beta yesterday's-picks strip**: needs at least a week of
  `verdict_ledger` rows with `source="tomorrow_watchlist"` (PR #65 started
  writing 2026-09-07). Ship on or after 2026-09-14.

## Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Fragment closures on Analyze Stock silently drop a parent-scope variable on a Streamlit rerun | Medium | Page-smoke passed on PR #69; monitor for `NameError` surfacing in Streamlit Cloud logs the first week |
| Warmer cron extensions on off-hour slots occasionally race the Streamlit Cloud container's sleep-wake cycle | Low | Data-blocked observation; the `data_health` panel's warmer-health probes (PR #64) surface any stale snapshot within 30 min |
| Task 4.2 alpha's per-scan `log_verdict` calls fail silently and the yesterday-picks strip has empty data on 2026-09-14 | Medium | `log_verdict` writes are dedup'd + swallowed at debug; check `verdict_log` counts around 2026-09-11 to catch this early |
| Composite score shape drift via ad-hoc reweighting | High | Guardrail 5 + verdict-regression-reviewer gate stays enforced |
| House style em-dash violations creep back into commits from copy-paste | Low | Kept catching in-session; consider a pre-commit grep for the em-dash character (U+2014) if it becomes recurring |

## See Also

- Sprint 1 UI audit: `docs/UI_AUDIT_2026-09_SPRINT1.md`
- Data provenance audit (Task 2.1): `docs/DATA_PROVENANCE_2026-09.md`
- Render-speed audit (Task 2.4): `docs/RENDER_SPEED_AUDIT_2026-09.md`
- Tomorrow's Watchlist audit (Task 4.2):
  `docs/TOMORROW_WATCHLIST_AUDIT_2026-09.md`
- Pre-open scan design (Task 4.3): `docs/PREOPEN_SCAN.md`
- AI co-pilot status (Phase 5): `docs/AI_COPILOT_STATUS.md`
- Guardrails: `.claude/skills/nse-app-guardrails/SKILL.md`
- Page smoke: `.claude/skills/page-smoke-check/SKILL.md`
- AI co-pilot: `.claude/skills/ai-copilot-context/SKILL.md`
- Subagents: `.claude/agents/verdict-regression-reviewer.md`,
  `.claude/agents/data-provenance-auditor.md`
