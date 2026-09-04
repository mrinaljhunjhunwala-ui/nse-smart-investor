---
name: nse-app-guardrails
description: The non-negotiable rules of the NSE Smart Investor project — SEBI-compliance boundaries, scoring invariants, sector-aware fundamentals, module-boundary purity. Applies to every change. Use whenever writing, reviewing, or refactoring any file under analysis/, strategies/, dashboard/, data/, or the AI co-pilot. Complements CLAUDE.md — that's the map, this is the fence.
---

# NSE Smart Investor Guardrails

Every edit runs against these. They're not style preferences — they're the compliance and correctness bar the project ships to real users under.

## The compliance bar (SEBI + user-safety)

1. **No buy / sell / hold instruction, ever.** The Valuation Decision Layer emits a *descriptive posture* (Bullish / Neutral / Bearish / etc.). UI copy that reads as advice is a bug — "this looks strong", "I would trim", "worth accumulating" are all forbidden. The AI co-pilot has an additional regex post-filter ([safety.py](../../../dashboard/shared/ai/safety.py)) but the primary defence is the wording you choose in the code you write.
2. **No price-target-as-recommendation.** Targets are computed and displayed — they are *scenarios*, never *calls*. "Suggested entry / stop / target" wording is fine; "buy at X, sell at Y" is not.
3. **The educational disclaimer must survive.** Do not strip "Educational analysis only — not SEBI-registered investment advice" or its variants from any user-facing output. The AI co-pilot ends every reply with it; the app README carries the same line.
4. **No insider-info / manipulation / front-run helpers.** The co-pilot refuses these prompts and so should any new feature. If someone asks the app to signal news moves *before* the market has priced them, that's not a feature request — it's a red flag.

Violating any of the above is a **release-blocking bug**, not a warning.

## Scoring invariants (do not touch without a golden-snapshot review)

5. **Composite score is 0–90 with a bounded set of pillars — cap always 90.** The baseline shape is four components: technical 40 + momentum 25 + volume 15 + sentiment 10, and every non-F&O ticker (and every F&O ticker with the `NSE_USE_POSITIONING_PILLAR` flag OFF) runs on that shape unchanged. **Ratified exception (2026-09-03):** F&O-eligible tickers with the flag ON and at least one real positioning input run on the 5-pillar shape technical 35 + momentum 20 + volume 15 + sentiment 10 + positioning 10 = 90 (design 6a of `docs/COMPOSITE_SCORE_SHAPE_REVIEW.md`, ratified by the user in the session that landed Rec 6). Any further shape change needs the same explicit user ratification, plus capturing a new `data/composite_golden_snapshot.json` and running the [verdict-regression-reviewer](../../agents/verdict-regression-reviewer.md) subagent to explain every ticker delta.
6. **No candlestick pattern in the composite score.** The 40k-observation variant study (`docs/PATTERN_REMOVAL_MIGRATION.md`) proved the old 10-point pattern component had zero-to-negative ranking power in every regime. Patterns are *detected and shown in narrative* (`analysis.score.CompositeScore.patterns_detected`) — that field must stay list-typed, and it must stay unused in the score computation.
7. **Posture-monotonicity.** If composite score goes up, posture must not go from Bullish → Bearish, and vice versa. Any edit that breaks this invariant is a ❌ regardless of the author's intent.
8. **The 62-ticker valuation golden snapshot ([data/valuation_golden_snapshot.json](../../../data/valuation_golden_snapshot.json)) is a contract, not a suggestion.** Never regenerate it to make a failing test pass. If a snapshot must move, capture *why* in the diff summary and let a human ratify.

## Sector-aware fundamentals

9. **Banks / NBFCs / insurers are assessed on P/B + ROE, not "leverage".** Route every metric selection through [analysis/sector_classification.py](../../../analysis/sector_classification.py). If a page hard-codes "if debt-to-equity > X flag it" without checking sector, it's wrong for the financial sector where deposits look like debt on the balance sheet.
10. **Utilities and PSUs need their own guard branches.** POWERGRID / SBILIFE / SAIL each surfaced regressions in earlier scoring iterations. The golden snapshot includes them precisely to keep those branches honest — never delete those tickers from the fixture.

## Module-boundary purity

11. **`analysis/` and `strategies/` must be Streamlit-free.** No `import streamlit`, no `st.cache_*`, no `st.session_state`. That's what makes them unit-testable and reusable outside the app. Cache at the `dashboard/shared/cache.py` layer instead.
12. **`data/` fetchers may raise, but must not print to `st.*`.** They log via `logging` (`_log.warning(...)`); the caller decides UI presentation.
13. **The AI co-pilot's brain is pure.** Only `dashboard/shared/ai/panel.py` may `import streamlit`. `persona.py`, `safety.py`, `client.py`, `context_builder.py` stay pure so they can be tested with mocks.

## Fetcher discipline (post 2026-09-02 data-provenance audit)

14. **No bare `[0]` indexing on external JSON.** Yahoo, NSE, BSE all reshape without notice. Use `.get()` chains + explicit `ValueError("provider schema drift: <field>")` so a rename gets surfaced, not swallowed. See the [data/fetcher.py:369+ pattern](../../../data/fetcher.py) as the canonical example.
15. **Silent fallthroughs are worse than crashes.** A `.get("Table") or []` pattern that returns empty on drift makes the app show "no announcements" indefinitely — nobody notices. Add a WARNING log the moment a known-required key is missing from a truthy response.
16. **When adding a new provider, add a canary test at the same time.** The [data-provenance-auditor](../../agents/data-provenance-auditor.md) subagent finds drift; the tests document intent.

## Test discipline

17. **Every page must survive `test_pages_smoke.py` with network blocked.** Graceful degraded rendering is a hard requirement, not a nice-to-have. The [page-smoke-check](../page-smoke-check/SKILL.md) skill enforces this after every dashboard edit.
18. **Scoring / valuation changes need golden-snapshot review before merge.** Spawn the `verdict-regression-reviewer` subagent; do not merge on green tests alone if the diff touches `analysis/score.py`, `analysis/final_verdict.py`, `analysis/trend_quality_score.py`, or anything under `analysis/fundamentals/`.

## Persistence and secrets

19. **`.streamlit/secrets.toml`, `.env*`, `.credentials*`, `*.db`, `portfolio.csv` are hook-blocked from Edit/Write.** Do not disable the [block_sensitive.py](../../hooks/block_sensitive.py) hook to slip an edit past — if you truly need one of those files modified, do it by hand outside the agent and log why. The hook is the last line of defence for user data.
20. **`DATABASE_URL` is optional and can be absent.** Every persistence path must fall back to local SQLite (ephemeral on Streamlit Cloud / HF Spaces). Do not raise on missing `DATABASE_URL` — degrade gracefully with a caption that points to `docs/DB_SETUP.md`.

## Style / house voice

21. **No em-dashes.** Project house style uses en-dash (–) or plain hyphen (-). The AI co-pilot's persona enforces the same rule for chat output.
22. **Terse. Bullet-first. Numbers first, prose second.** Long paragraphs of prose in analysis pages are a signal to compress into a table or bullet list.
23. **Windows-first shell in docs.** Commands use `py`, not `python`; paths use backslashes when referring to Windows-native files. WSL / Bash paths are fine inside code fences that are explicitly labelled `bash`.

## Review checklist before declaring a change done

- [ ] No new buy/sell/hold language anywhere in user-facing output
- [ ] Composite-score shape unchanged (4 components, 40+25+15+10, 0–90)
- [ ] Sector-aware code paths go through `analysis/sector_classification.py`
- [ ] No `import streamlit` in `analysis/` or `strategies/` or `dashboard/shared/ai/{persona,safety,client,context_builder}.py`
- [ ] New external-data reads use `.get()` chains + drift warnings, not bare indexing
- [ ] Page-smoke test passes for every touched page
- [ ] If scoring/valuation touched: golden snapshots re-run and every delta explained
- [ ] Ruff clean on every touched Python file
