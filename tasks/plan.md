# Implementation Plan: NSE Smart Investor – Major Improvements

_Last updated: 2026-09-02 · Branch: `sprint1-ui-foundation` (in-flight)_

## Overview

Follow-on plan from the 2026-09-01 UI + market-analysis audit (Artifact: [Dealing Room Audit](https://claude.ai/code/artifact/ec24b844-f044-425e-ab3a-606051b69421)), **revised** against constraints that surfaced after the audit was written:

1. **`nse-app-guardrails` §5** forbids adding a 5th component to the composite score. The audit's Sprint 2 recommendation is invalid as written and must be re-shaped as an overlay or route through golden-snapshot review + human ratification.
2. **`page-smoke-check`** is now a mandatory tail step of every `dashboard/` edit.
3. Two new subagents exist (`verdict-regression-reviewer`, `data-provenance-auditor`) and are prerequisites for scoring / fetcher work.
4. Guardrails §14–16 reference a "post 2026-09-02 data-provenance audit" — reliability work belongs on the critical path.
5. **`ai-copilot-context`** describes an AI panel already being built under `dashboard/shared/ai/` — plan must integrate it, not ignore it.
6. Four decisions from the parallel chat (alerts channel, render-speed root cause, Tomorrow's Watchlist failure mode, pre-open scan mode) still need answers before their tasks can start.
7. House style §21: no em-dashes anywhere in code, docs, or plan. This document uses en-dash and hyphen only.

## Architecture Decisions

- **Composite score shape is frozen at 4 pillars, 40+25+15+10, 0–90.** Any new factor lands as one of: (a) a narrative-only append, (b) a sidecar `overlay_score` that never rewrites `CompositeScore.score`, or (c) a proposed shape change that goes to `verdict-regression-reviewer` + human ratification before merge. No exceptions.
- **Design tokens live in `dashboard/shared/design.py` as CSS custom properties.** New rule enforced by lint: no raw hex in files under `dashboard/pages/`.
- **Each Sprint 1 slice ships as its own commit** so page-smoke can catch regressions per slice, not per sprint.
- **In-flight uncommitted edits** on `sprint1-ui-foundation` (fetcher, vix, screener_fundamentals, bse_corp_info, analyze_stock) are quarantined: they get their own audit + commit before Sprint 1 continues. Rebasing new UI work on top of them keeps blame legible.
- **AI co-pilot work follows `ai-copilot-context` exactly.** The three-layer context assembly (persona + live state + conversation) is the contract; the panel wires it into pages one at a time.
- **Data-provenance and page-smoke run before every commit** to `main`. Encode as a hook if not already; otherwise a checklist in each PR body.

## Task List

Every task carries acceptance criteria + verification in `tasks/todo.md`. This section is the index.

### Phase 0 · Quarantine and land in-flight work
Get the working tree back to a green, committed state so Sprint 1 has a clean base.
- Task 0.1: Audit and land the in-flight `data/` and `analysis/fundamentals/providers/` edits
- Task 0.2: Audit and land the in-flight `dashboard/pages/04_analyze_stock.py` edit
- Task 0.3: Commit the design-tokens block already added to `dashboard/shared/design.py` (Sprint 1.1 head-start)
- **Checkpoint 0:** working tree clean, all pages green under `page-smoke-check`, changelog entries in `docs/` for anything user-visible

### Phase 1 · UI foundation (Sprint 1, revised)
Same shape as the audit's Sprint 1 but with page-smoke gating between slices and Emil's animation-decision framework applied to any motion.
- Task 1.1: **Ship** design-token block (finish what's on the branch)
- Task 1.2: Migrate `dashboard/pages/02_command_centre.py` and `dashboard/pages/04_analyze_stock.py` off inline hex to tokens
- Task 1.3: Introduce `panel()` and `stat()` in `dashboard/shared/ui_components.py`; refactor Command Centre paper-trades overview as the first consumer
- Task 1.4: **Verdict Card** hero on Analyze Stock (action, conviction, size in ₹, R multiple)
- Task 1.5: Emoji cleanup in headings across all 20 pages
- Task 1.6: Add pre-commit CSS-hex lint (`dashboard/pages/**/*.py` no bare `#[0-9a-fA-F]{3,8}` outside comments)
- **Checkpoint 1:** every touched page green under page-smoke; screenshot before/after in `docs/UI_AUDIT_2026-09_SPRINT1.md`

### Phase 2 · Data reliability and provenance
Prompted by the "post 2026-09-02 data-provenance audit" reference in guardrails, plus the "unreliable / slow render" open question from the parallel chat.
- Task 2.1: Run `data-provenance-auditor` subagent across every provider (yfinance, NSE corp-info, BSE corp-info, Google News RSS, NSE RSS, Screener.in)
- Task 2.2: Convert bare `[0]` / `.get(k) or []` fetcher patterns to `.get()` chains with `ValueError("provider schema drift: <field>")` per Guardrail 14
- Task 2.3: Add a `data_health` panel to Command Centre showing per-provider last-success-timestamp and drift-warning count
- Task 2.4: **Root-cause the render-speed report** – needs the user's letter answer (A/B/C/D/E) from the parallel chat before starting
- Task 2.5: Add canary tests for every provider per Guardrail 16
- **Checkpoint 2:** `data-provenance-auditor` clean run committed to `docs/`; render-speed complaint reproducible in a smoke test then fixed

### Phase 3 · Signal integration (audit's Sprint 2, re-shaped to respect guardrails)
The audit proposed a fifth composite pillar. Guardrail 5 forbids that. Re-shape:
- Task 3.1: Ship **Relative Strength vs Nifty** as a new sub-signal inside the existing Momentum pillar (25 pts unchanged; internal split becomes `abs_returns:15 + rs_vs_nifty:10`); pass through `verdict-regression-reviewer`
- Task 3.2: Ship **FII/DII 5d sign** as a modifier inside the existing Sentiment pillar (10 pts unchanged; internal split becomes `vix_regime:5 + sector_rank:3 + flows:2`); pass through `verdict-regression-reviewer`
- Task 3.3: Ship **TQS × valuation** as a sidecar `overlay_score` (0-100) displayed adjacent to the composite, never blended into it – this is the guardrail-safe home for the audit's Quality & Valuation idea
- Task 3.4: Ship **NSE delivery %** as a new indicator column consumed by Volume pillar's internal 15-pt split
- Task 3.5: Ship **regime-adaptive stop-loss bounds** in `analysis/score._compute_entry_levels()` (scale ATR bounds by VIX percentile)
- Task 3.6: Ship **regime-conditional weight dispatch** as a v2 opt-in flag; validate on the 5-year window in `research/score_variants_regime.py` before making default
- **Checkpoint 3:** every scoring change has a `verdict-regression-reviewer` writeup; golden snapshot re-captured only where deltas were explained and ratified

### Phase 4 · Operations (from parallel chat)
Blocked on user decisions; queued so they land coherently once answered.
- Task 4.1: **Alerts channel** – blocked on user pick (ntfy.sh recommended)
- Task 4.2: **Tomorrow's Watchlist** failure-mode audit – blocked on user pick (which of four modes)
- Task 4.3: **Pre-open / opening-picture scan** – blocked on user pick (a: extra 9:20 run, b: dedicated engine)
- Task 4.4: Data reliability follow-through from Phase 2 findings

### Phase 5 · AI co-pilot MVP
Follows `ai-copilot-context` exactly – the panel already exists under `dashboard/shared/ai/`, so this phase is about finishing it, not designing it.
- Task 5.1: Audit current `dashboard/shared/ai/` state; write a gap-analysis note in `docs/AI_COPILOT_STATUS.md`
- Task 5.2: Complete Layer 1 (persona + rules) with SEBI-compliance regex post-filter per `ai-copilot-context`
- Task 5.3: Complete Layer 2 (live dashboard state) with the full JSON shape from the skill (composite score breakdown, VIX regime, portfolio position, scan health, user risk rules)
- Task 5.4: Wire the panel into Analyze Stock as the first page
- Task 5.5: Add `tests/test_ai_copilot.py` cases for the compliance filter (already present, extend)
- **Checkpoint 5:** end-to-end conversation on a live Analyze Stock page passes SEBI-language regex on 100 synthetic prompts

### Checkpoint: Complete
- [ ] All Phase 1 acceptance met, screenshots archived
- [ ] `data-provenance-auditor` and `verdict-regression-reviewer` runs recorded
- [ ] Composite score shape unchanged (4 pillars, 40+25+15+10, 0–90) OR shape change signed off by user
- [ ] House style §21 (no em-dashes) enforced on all changed files
- [ ] All 20 pages green under `page-smoke-check`
- [ ] Guardrail review checklist passes on every changed file

## Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| A Sprint 1 CSS refactor breaks a page silently on Streamlit Cloud | High | Page-smoke as tail step on every slice; visual diff via `chrome-devtools-mcp` after deploy |
| Phase 3 scoring changes drift the 62-ticker golden snapshot | High | Mandatory `verdict-regression-reviewer` on every Phase 3 task; snapshot regeneration blocked by hook |
| Data-provider drift lands mid-sprint and blocks a page | Medium | Phase 2 runs first; canary tests in place before Phase 3 depends on them |
| AI co-pilot leaks buy/sell language past the regex filter | High (SEBI) | Layer 1 persona rules + regex post-filter + 100-prompt compliance test in Phase 5 |
| In-flight edits on the branch mask a regression the new work introduces | Medium | Phase 0 quarantines them before Sprint 1 continues |
| Emoji cleanup mangles a page's headline / breaks a selector-in-CSS that targeted the emoji character | Low | Task 1.5 runs page-smoke per page, not batch |
| I violate house style §21 (em-dashes) again out of habit | Low | Every doc/comment I write from now on ships through a pre-commit grep for `—` |

## Open Questions

- **Q1** (parallel chat): Alerts channel – ntfy.sh + Gmail digest, Discord webhook, or something else?
- **Q2** (parallel chat): Render-speed root cause – which of A/B/C/D/E matches what you see?
- **Q3** (parallel chat): Tomorrow's Watchlist failure mode – picks don't move / no ranking / mislabelled / no follow-through?
- **Q4** (parallel chat): Pre-open scan – extra 9:20 IST run of existing engine, or a dedicated opening-picture engine?
- **Q5** (this plan): Am I authorised to open the composite-score shape (add a fifth pillar with `verdict-regression-reviewer` review + your ratification), or is the shape absolutely frozen and Phase 3 must stay inside the four existing pillars? Current plan assumes frozen.
- **Q6** (this plan): The uncommitted in-flight edits (fetcher, vix, screener_fundamentals, bse_corp_info, analyze_stock) — are these yours in progress, or safe to review and commit as Phase 0?

## See Also

- Original audit: `docs/UI_AUDIT_2026-09.md` (to be created from the published Artifact for durable reference)
- Guardrails: `.claude/skills/nse-app-guardrails/SKILL.md`
- Page smoke: `.claude/skills/page-smoke-check/SKILL.md`
- AI co-pilot: `.claude/skills/ai-copilot-context/SKILL.md`
- Subagents: `.claude/agents/verdict-regression-reviewer.md`, `.claude/agents/data-provenance-auditor.md`
