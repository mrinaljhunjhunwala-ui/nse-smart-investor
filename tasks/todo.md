# Task List – NSE Smart Investor Major Improvements

_Generated 2026-09-02 from `tasks/plan.md`. Update the checkboxes as each task lands._

## Phase 0 · Quarantine and land in-flight work

### Task 0.1: Audit and land in-flight data / fundamentals edits
**Description:** Working tree has uncommitted edits in `data/fetcher.py`, `data/bse_corp_info.py`, `analysis/fundamentals/providers/screener_fundamentals.py`, `utils/vix.py`, and `requirements.txt`. Confirm authorship, review the diff, land as one or more coherent commits before Sprint 1 continues.

**Acceptance criteria:**
- [ ] Every modified file's diff explained in the commit message (what and why)
- [ ] Guardrail 14–16 patterns applied where the diff touches provider parsing
- [ ] `requirements.txt` change matched to the code that needs the new pin

**Verification:**
- [ ] `py -m pytest -m "not slow" -q` passes
- [ ] `py -m pytest tests/test_pages_smoke.py -q` passes
- [ ] `ruff check .` clean on every touched file

**Dependencies:** None (must be done first)

**Files likely touched:** `data/fetcher.py`, `data/bse_corp_info.py`, `analysis/fundamentals/providers/screener_fundamentals.py`, `utils/vix.py`, `requirements.txt`

**Scope:** M (blocked on Q6 answer)

---

### Task 0.2: Audit and land in-flight Analyze Stock edit
**Description:** `dashboard/pages/04_analyze_stock.py` has uncommitted changes. Same pattern as 0.1.

**Acceptance criteria:**
- [ ] Diff explained in commit message
- [ ] No new em-dashes in comments or copy (house style §21)
- [ ] `page-smoke-check` on this page green

**Verification:**
- [ ] `py -m pytest tests/test_pages_smoke.py -k "04_analyze_stock" -q`

**Dependencies:** 0.1 (if the Analyze Stock edit touches fetcher output shape)

**Files likely touched:** `dashboard/pages/04_analyze_stock.py`

**Scope:** S

---

### Task 0.3: Land Sprint 1.1 design tokens
**Description:** The CSS custom-properties block already added to `dashboard/shared/design.py` (this branch) is safe and additive. Commit it as-is with a clear message and a docs entry.

**Acceptance criteria:**
- [ ] Commit references the audit and the guardrail's new "no raw hex in pages" rule
- [ ] No behavioural change (tokens are declared but nothing else consumes them yet)

**Verification:**
- [ ] `py -m pytest tests/test_pages_smoke.py -q` passes (shared/ edit means full run)

**Dependencies:** 0.1, 0.2 (clean tree first)

**Files likely touched:** `dashboard/shared/design.py`

**Scope:** XS

---

### ✅ Checkpoint 0
- [ ] `git status` clean
- [ ] All page-smoke green
- [ ] Any user-visible change has a `docs/` entry

---

## Phase 1 · UI foundation

### Task 1.2: Migrate Command Centre + Analyze Stock off inline hex
**Description:** Two loudest pages. Replace every raw hex literal with `var(--token)`. Where a page uses `#26a69a` / `#00d4aa` etc. the mapping goes to `--bull`; `#ff4757` / `#ef5350` to `--bear`; `#FFC107` / `#f9a825` to `--amber`; `#5b8def` / `#0d1526` etc. re-evaluated case by case.

**Acceptance criteria:**
- [ ] Zero raw hex under those two files (grep-verified)
- [ ] Visual diff before/after is intentional only

**Verification:**
- [ ] `py -m pytest tests/test_pages_smoke.py -k "02_command_centre or 04_analyze_stock" -q`
- [ ] Manual before/after screenshot pair in `docs/UI_AUDIT_2026-09_SPRINT1.md`

**Dependencies:** 0.3

**Files likely touched:** `dashboard/pages/02_command_centre.py`, `dashboard/pages/04_analyze_stock.py`

**Scope:** M

---

### Task 1.3: `panel()` and `stat()` shared components  ✅ SHIPPED 2026-09-04 · commit pending

_Both added to `dashboard/shared/ui_components.py`; Command Centre paper-trades overview refactored as the first consumer. Sources every color from CSS custom-property tokens (Task 1.6 lint enforced)._

**Description:** Introduce two components in `dashboard/shared/ui_components.py`:
- `panel(kind, tone, title, body_html)` – replaces the three ad-hoc card variants (`.card-*`, inline glass-panel divs, `_pto_cell` helper).
- `stat(label, value, delta=None, spark_series=None)` – replaces the Streamlit `st.metric` / `.metric-box` / `_pto_cell` triple.

Refactor Command Centre paper-trades overview (`dashboard/pages/02_command_centre.py:128-141`) as the first consumer to prove the API.

**Acceptance criteria:**
- [ ] Two public functions with docstrings and type hints
- [ ] One page migrated end-to-end
- [ ] Both accept tokens by name, not by hex

**Verification:**
- [ ] `py -m pytest tests/test_pages_smoke.py -q` full run (shared/ edit)
- [ ] Screenshot delta shows same or better density

**Dependencies:** 0.3

**Files likely touched:** `dashboard/shared/ui_components.py`, `dashboard/pages/02_command_centre.py`

**Scope:** M

---

### Task 1.4: Verdict Card hero on Analyze Stock  ✅ SHIPPED 2026-09-04 · commit pending

_`verdict_card()` in `dashboard/shared/ui_components.py`; wired at the top of Analyze Stock right after the UNAVAILABLE-sentinel guard. Renders action + conviction (0/90) + entry/stop/target/R:R + suggested share count (from 1% risk budget) + optional secondary row for RS score, positioning, and the user's existing position._

**Description:** New component `verdict_card(cs, portfolio_ctx)` shown at the top of Analyze Stock. Displays action, conviction (0-100), horizon, size in ₹ (from Position Sizer defaults), R multiple. Push disclosures behind an ⓘ affordance next to the score.

**Acceptance criteria:**
- [ ] Verdict card renders above every other on-page section for a scored ticker
- [ ] Uses `panel()` and `stat()` from Task 1.3
- [ ] Copy passes SEBI-language check: no "buy X" / "sell X" imperatives; posture only

**Verification:**
- [ ] `py -m pytest tests/test_pages_smoke.py -k "04_analyze_stock" -q`
- [ ] Manual: search a ticker, verdict card is the largest thing on the page

**Dependencies:** 1.2, 1.3

**Files likely touched:** `dashboard/shared/ui_components.py`, `dashboard/pages/04_analyze_stock.py`

**Scope:** M

---

### Task 1.5: Emoji cleanup in headings
**Description:** Retire decorative emoji from H1/H2 across all 20 pages. Keep semantic emoji (▲ ▼ for direction; regime dots) untouched.

**Acceptance criteria:**
- [ ] No emoji in `st.title()` or `st.header()` calls
- [ ] Section labels use `_section_div()` from `design.py` where a divider is needed

**Verification:**
- [ ] `py -m pytest tests/test_pages_smoke.py -q` full run
- [ ] Grep confirms zero emoji in the two call sites

**Dependencies:** None; can parallelise with 1.4

**Files likely touched:** `dashboard/pages/*.py`

**Scope:** M

---

### Task 1.6: Pre-commit CSS-hex lint  ✅ SHIPPED 2026-09-04 · commit pending

_.claude/hooks/block_page_hex.py + settings.json wiring. Surfaces 96 raw hex literals in Command Centre alone — matches the audit; Task 1.2 (hex→tokens migration) can now proceed with drift protection._

**Description:** Add a pre-commit hook (or extend the existing `.claude/hooks/`) that fails when a raw hex literal appears in a file under `dashboard/pages/`. Comments allowed via `# noqa: hex` suffix.

**Acceptance criteria:**
- [ ] Hook fails on a synthetic offending file
- [ ] Hook passes on the current tree post-1.2

**Verification:**
- [ ] Add a failing test case, confirm block; remove and confirm pass

**Dependencies:** 1.2

**Files likely touched:** `.claude/hooks/*.py` or `pyproject.toml`

**Scope:** S

---

### ✅ Checkpoint 1
- [ ] Every touched page green under page-smoke
- [ ] Before/after screenshots archived in `docs/UI_AUDIT_2026-09_SPRINT1.md`
- [ ] No raw hex in `dashboard/pages/` (grep-verified)

---

## Phase 2 · Data reliability and provenance

### Task 2.1: Full data-provenance audit
**Description:** Spawn the `data-provenance-auditor` subagent across every external provider. Land the report as `docs/DATA_PROVENANCE_2026-09.md`.

**Acceptance criteria:**
- [ ] Report covers each provider with request shape, response shape, drift indicators
- [ ] Every drift finding has a proposed fix or an accepted deferral

**Verification:**
- [ ] Subagent run archived; report reviewed

**Dependencies:** Phase 0 complete

**Files likely touched:** `docs/DATA_PROVENANCE_2026-09.md` (new)

**Scope:** M

---

### Task 2.2: Harden fetcher parsing per Guardrail 14
**Description:** Convert every `.get(k) or []` and bare `[0]` on external JSON to `.get()` chains + explicit `ValueError("provider schema drift: <field>")`. Warn-log the moment a known-required key is missing from a truthy response.

**Acceptance criteria:**
- [ ] Grep shows zero bare `[0]` on JSON dicts under `data/`
- [ ] Silent-empty fallthroughs (Guardrail 15) replaced with logged drift warnings

**Verification:**
- [ ] `py -m pytest -m "not slow" -q`
- [ ] Manual: kill one provider's response mid-canary and confirm the warning fires

**Dependencies:** 2.1

**Files likely touched:** `data/fetcher.py`, `data/nse_corp_info.py`, `data/bse_corp_info.py`, `data/news_feed.py`, `data/nse_rss_feeds.py`

**Scope:** L (may need to split by file)

---

### Task 2.3: `data_health` panel on Command Centre
**Description:** New panel showing per-provider last-success-timestamp, drift-warning count, and next scheduled refresh. Two rows: providers up / providers stale.

**Acceptance criteria:**
- [ ] Reads timestamps written by 2.2's fetchers
- [ ] Uses `panel()` from Task 1.3

**Verification:**
- [ ] `page-smoke-check` on Command Centre

**Dependencies:** 1.3, 2.2

**Files likely touched:** `dashboard/pages/02_command_centre.py`, `dashboard/shared/data_health.py` (new)

**Scope:** M

---

### Task 2.4: Render-speed root cause (blocked on Q2)
**Description:** Depends on user's letter answer to Q2 (A/B/C/D/E). Reproduce, fix root cause, add smoke test.

**Acceptance criteria:** – filled in after Q2 answered

**Dependencies:** Q2 answered

**Scope:** – TBD

---

### Task 2.5: Canary tests per Guardrail 16
**Description:** One canary test per provider that asserts the response shape hasn't drifted.

**Acceptance criteria:**
- [ ] One `tests/test_provenance_<provider>.py` per provider
- [ ] Marked `slow` so they don't block the fast suite

**Verification:**
- [ ] `py -m pytest -m slow -q` all pass with network

**Dependencies:** 2.2

**Files likely touched:** `tests/test_provenance_*.py` (new)

**Scope:** M

---

### ✅ Checkpoint 2
- [ ] Provenance report committed
- [ ] `data_health` panel live
- [ ] Render-speed complaint reproducible in a test, then fixed
- [ ] Canaries added, `slow` suite green with network

---

## Phase 3 · Signal integration (guardrail-safe)

### Task 3.1: Relative Strength vs Nifty, inside Momentum pillar  ✅ SHIPPED 2026-09-03 · commit pending

_See `docs/RS_INTEGRATION_2026-09.md` for the reviewer writeup._

**Description:** Momentum stays 25 pts. Internal split becomes `abs_returns:15 + rs_vs_nifty:10`. RS scored as `(stock_return_20d − nifty_return_20d)` z-score against the 250-day distribution + RS-line slope sign.

**Acceptance criteria:**
- [ ] `_score_momentum()` returns same 25-pt max
- [ ] Composite score shape unchanged (Guardrail 5)
- [ ] `verdict-regression-reviewer` writeup landed for every ticker delta on the golden snapshot

**Verification:**
- [ ] `py -m pytest tests/test_valuation_golden_snapshot.py -q` deltas explained
- [ ] Reviewer subagent output committed to `docs/`

**Dependencies:** Phase 0

**Files likely touched:** `analysis/score.py`, `data/composite_golden_snapshot.json`, `docs/RS_INTEGRATION_2026-09.md` (new)

**Scope:** L

---

### Task 3.2: FII/DII 5d flow sign, inside Sentiment pillar  ✅ SHIPPED 2026-09-03 · commit pending

_See `docs/FLOWS_INTEGRATION_2026-09.md` for the reviewer writeup._

**Description:** Sentiment stays 10 pts. Internal split becomes `vix_regime:5 + sector_rank:3 + flows:2`. Flow score reads from `analysis/fii_dii.load_history(days=5)`.

**Acceptance criteria:**
- [ ] `_score_sentiment()` returns same 10-pt max
- [ ] `verdict-regression-reviewer` writeup for every delta

**Verification:**
- [ ] Same as 3.1

**Dependencies:** 3.1 (to sequence the golden-snapshot updates)

**Files likely touched:** `analysis/score.py`, `data/composite_golden_snapshot.json`

**Scope:** M

---

### Task 3.3: TQS × valuation sidecar `overlay_score`
**Description:** New field `CompositeScore.overlay_score: Optional[int]` computed from existing TQS + valuation posture. Displayed adjacent to composite on Verdict Card, never blended into `.score`. This is where the audit's "Quality & Valuation" idea lands within guardrail bounds.

**Acceptance criteria:**
- [ ] `CompositeScore.score` unchanged for every ticker in the golden snapshot
- [ ] `overlay_score` renders on Verdict Card as a secondary read

**Verification:**
- [ ] `py -m pytest tests/test_valuation_golden_snapshot.py -q` zero deltas on `.score`
- [ ] Manual: verdict card shows both scores clearly labelled

**Dependencies:** 1.4

**Files likely touched:** `analysis/score.py`, `dashboard/shared/ui_components.py`

**Scope:** M

---

### Task 3.4: NSE delivery % as Volume pillar input  ✅ SHIPPED 2026-09-03 · commit pending

_See `docs/DELIVERY_INTEGRATION_2026-09.md` for the reviewer writeup. Follow-ups: bhavcopy cron + backfill script + UI column (queued)._

**Description:** Volume stays 15 pts. Add `data/nse_delivery.py` (bhavcopy delivery file). Internal split becomes `vol_ratio:8 + delivery_pct:4 + obv:3`.

**Acceptance criteria:**
- [ ] Delivery % fetched with drift-warning discipline per Guardrail 14
- [ ] `_score_volume()` returns same 15-pt max
- [ ] `verdict-regression-reviewer` writeup for deltas

**Verification:**
- [ ] `py -m pytest -m "not slow" -q`
- [ ] Canary test for the bhavcopy provider

**Dependencies:** 2.2 (fetcher discipline), 2.5 (canary pattern established)

**Files likely touched:** `data/nse_delivery.py` (new), `analysis/score.py`, `utils/indicators.py`

**Scope:** L

---

### Task 3.5: Regime-adaptive stop-loss bounds  ✅ SHIPPED 2026-09-03 · commit pending

_See `docs/SL_REGIME_2026-09.md` for the reviewer writeup._

**Description:** `_compute_entry_levels()` currently uses fixed 1.2–3.0×ATR stop bounds. Scale by VIX percentile: low-VIX 1.0–2.5×, high-VIX 1.5–3.5×.

**Acceptance criteria:**
- [ ] Target multiplier logic unchanged (it's already vol-anchored)
- [ ] `verdict-regression-reviewer` writeup for SL / R:R deltas

**Verification:**
- [ ] Golden snapshot deltas explained

**Dependencies:** 3.1 (sequencing)

**Files likely touched:** `analysis/score.py`

**Scope:** S

---

### Task 3.6: Regime-conditional weight dispatch (opt-in flag)  ✅ MECHANISM SHIPPED 2026-09-03 · commit pending

_Flag defaults OFF. Flipping the default blocked on running `py -m research.score_variants_regime` end-to-end and confirming flag-on beats flag-off on both halves of the SCORE_EFFICACY sample. See `docs/REGIME_WEIGHTS_2026-09.md` for the reviewer writeup._

**Description:** Two weight sets: trending (current) and mean-reverting. Dispatch by `regime.snapshot_live().label`. Ship as opt-in flag `USE_REGIME_WEIGHTS=True` first, validate on the 5-year window in `research/score_variants_regime.py`, only then flip default.

**Acceptance criteria:**
- [ ] Default behaviour unchanged with flag off
- [ ] Flag-on run passes `verdict-regression-reviewer` and outperforms flag-off on both halves of the SCORE_EFFICACY sample
- [ ] Guardrail 5 still holds (4 pillars, 40+25+15+10, 0–90)

**Verification:**
- [ ] Research script writeup in `docs/REGIME_WEIGHTS_VALIDATION.md`

**Dependencies:** 3.1, 3.2

**Files likely touched:** `analysis/score.py`, `research/score_variants_regime.py`, `docs/REGIME_WEIGHTS_VALIDATION.md` (new)

**Scope:** L

---

### ✅ Checkpoint 3
- [ ] Every Phase 3 task has a reviewer writeup
- [ ] Composite shape unchanged (4 pillars, weights sum unchanged)
- [ ] Golden snapshot regenerated only where deltas were explained and ratified

---

## Phase 4 · Operations (blocked on user Q1–Q4)

### Task 4.1: Alerts channel wiring – **blocked on Q1**
### Task 4.2: Tomorrow's Watchlist audit – **blocked on Q3**
### Task 4.3: Pre-open / opening-picture scan – **blocked on Q4**
### Task 4.4: Data reliability follow-through – rolled from Phase 2 findings

---

## Phase 5 · AI co-pilot MVP

### Task 5.1: Gap analysis of `dashboard/shared/ai/`
**Description:** Enumerate current state (files present, tests present, wiring status). Write `docs/AI_COPILOT_STATUS.md` mapping present → needed against `ai-copilot-context` skill.

**Acceptance criteria:**
- [ ] Every file under `dashboard/shared/ai/` catalogued
- [ ] Every `ai-copilot-context` requirement marked done / partial / missing

**Verification:**
- [ ] Doc committed

**Dependencies:** None; can run in parallel with Phase 1

**Scope:** S

---

### Task 5.2: Layer 1 persona + rules + SEBI regex filter
**Description:** Complete `dashboard/shared/ai/persona.py` and `safety.py` per skill spec. Include the "no buy/sell/hold" regex post-filter.

**Acceptance criteria:**
- [ ] Persona constant covers identity, compliance, voice, framework awareness, refusals, style
- [ ] `safety.py` filter blocks a 20-prompt adversarial suite

**Verification:**
- [ ] Extend `tests/test_ai_copilot.py` for the 20-prompt suite

**Dependencies:** 5.1

**Files likely touched:** `dashboard/shared/ai/persona.py`, `dashboard/shared/ai/safety.py`, `tests/test_ai_copilot.py`

**Scope:** M

---

### Task 5.3: Layer 2 live-state builder
**Description:** `build_context(page, ticker=None)` returns the JSON block described in `ai-copilot-context`. Must include composite-score breakdown, technicals, regime, portfolio position (if any), scan health.

**Acceptance criteria:**
- [ ] Every field in the skill's example JSON is populated or explicitly null
- [ ] Function pure (no `import streamlit`) per Guardrail 13

**Verification:**
- [ ] `tests/test_ai_copilot.py` snapshot of the JSON shape

**Dependencies:** 5.1

**Files likely touched:** `dashboard/shared/ai/context_builder.py`, `tests/test_ai_copilot.py`

**Scope:** M

---

### Task 5.4: Panel wiring in Analyze Stock (first page)
**Description:** Wire the panel into `dashboard/pages/04_analyze_stock.py`. Only `panel.py` may `import streamlit` per Guardrail 13.

**Acceptance criteria:**
- [ ] Panel opens, sends, receives, ends every reply with the educational disclaimer
- [ ] `page-smoke-check` green

**Verification:**
- [ ] Manual: 5 conversation turns, disclaimer present in every assistant reply

**Dependencies:** 5.2, 5.3, 1.4

**Files likely touched:** `dashboard/shared/ai/panel.py`, `dashboard/pages/04_analyze_stock.py`

**Scope:** M

---

### Task 5.5: 100-prompt SEBI compliance suite
**Description:** Extend `tests/test_ai_copilot.py` with 100 synthetic prompts (mix of benign, adversarial, edge). Assert every response passes the regex filter and ends with the disclaimer.

**Acceptance criteria:**
- [ ] Suite runs in under 2 min against a mocked model
- [ ] 100% pass

**Verification:**
- [ ] `py -m pytest tests/test_ai_copilot.py -q`

**Dependencies:** 5.2, 5.4

**Files likely touched:** `tests/test_ai_copilot.py`

**Scope:** M

---

### ✅ Checkpoint 5
- [ ] AI panel live on Analyze Stock
- [ ] 100-prompt compliance suite green
- [ ] `docs/AI_COPILOT_STATUS.md` marks every requirement done

---

## Final Checkpoint
- [ ] All acceptance criteria met across phases 1, 2, 3, 5 (Phase 4 gated on user answers)
- [ ] Guardrails review checklist passes on every changed file
- [ ] `main` merged, deployed, screenshots and reviewer writeups archived in `docs/`
