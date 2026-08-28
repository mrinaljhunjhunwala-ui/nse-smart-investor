# Phase 1 — UI Honesty & Interpretation Alignment (Change Log)

Aligns product language with the research findings of
[SCORE_EFFICACY_REPORT.md](SCORE_EFFICACY_REPORT.md) and
[REGIME_STUDY_REPORT.md](REGIME_STUDY_REPORT.md):
the composite score measures **trend quality** (+0.41 Spearman vs trend
persistence), **not future returns** (+0.04), and its rankings degrade/invert
in elevated-fear regimes.

**Scope guarantee:** wording, interpretation and disclosure only. No change to
score calculations, weights, thresholds, grades, actions, backtests, portfolio
logic, or research harnesses. (Verified: full suite 300 passed; the scoring
engine `analysis/score.py` has zero diff.)

## Label taxonomy decision

The spec proposed renaming action chips ("STRONG BUY" → "Very Strong Trend
Quality"). **Deliberately not done in Phase 1**: the action strings are engine
*values* used in sort orders, paper-trade audit trails and tests across 17
pages — renaming them is a Phase-2 (display-mapping) decision once the
taxonomy is agreed. Instead, Phase 1 keeps the familiar chips and **redefines
what they mean** at every definition point ("STRONG BUY = very strong trend
quality, not a return guarantee"), renames the score itself, and adds regime +
methodology context next to every live score surface. This achieves the
success criteria with near-zero regression risk.

## New reusable components — `dashboard/shared/disclosures.py`

| Component | What it shows |
|---|---|
| `render_score_methodology()` | Expander "ℹ️ What this score measures": trend strength / persistence / momentum quality / technical confirmation, plus the explicit line **"the score is not a direct forecast of future returns"** with the study's numbers |
| `render_regime_reliability_note()` | Live VIX-aware note: **warning** in elevated/fear/panic regimes ("rankings become less reliable — and can invert — during elevated-fear regimes"), lighter caption in normal/complacent regimes. Degrades silently if VIX is unavailable |

## Wording changes by surface

| Location | Before | After | Justification |
|---|---|---|---|
| Analyze Stock — subtitle | "get a full **AI score** … and plain-English recommendation" | "get a full **trend-quality score** … plain-English read of the setup" | Score is a trend gauge, not an AI return forecast (Q3, regime study) |
| Analyze Stock — top of page | — | regime note + methodology expander | Score is this page's primary element |
| Command Centre — Top Picks caption | "Best buy & sell setups scored…" | "Strongest and weakest **trend-quality** setups… Scores rank trend health — they are **not a forecast of returns**" | STRONG BUY band underperformed EXIT in the efficacy study; caption must not imply expected outperformance |
| Command Centre — below scan info | — | regime note + methodology expander | Live scores surface |
| Smart Screener — subtitle + checkbox | "enriched with a composite score" / "Enrich with composite score" | "enriched with a **trend-quality score** (trend health, not a return forecast)" / "Enrich with trend-quality score" | Consistent naming |
| Smart Screener — top of page | — | regime note + methodology expander | Live scores surface |
| Tomorrow's Watchlist — below scan caption | — | regime note | Scored candidates surface; fear-regime inversion most relevant for next-session setups |
| Investor Guide — section header | "Composite Score (0 – 100)" | "Trend Quality Score (0 – 100)" | Canonical definition point |
| Investor Guide — new info box | — | "What this score is — and isn't" citing the 5-year study (+0.41 trend persistence vs +0.04 returns; fear-regime unreliability) | Methodology transparency at the definition source |
| Investor Guide — signal table "What It Means" | "Ideal entry", "Entry is favourable", … | "Very strong trend quality — … Not a return guarantee", "Strong trend quality — …", … (all six rows reframed as trend statements) | Removes implied return forecasts from the canonical legend |
| Investor Guide — sub-components table | "Sentiment (10 pts): **News tone** …" | "Sentiment (10 pts): **India-VIX regime (6) + sector strength rank (4)**" | Fixed a factual UI/engine mismatch — the engine never used news tone in the composite |
| My Portfolio — empty-state help | "Composite score (0–100) … higher is better" | "Trend-quality score (0–100) … higher = stronger, more persistent trend (not a return forecast)" | Consistent naming + honest framing |

## Success criteria check

- *High score = stronger trend quality* → stated in the score name, the guide
  legend, and the methodology expander on every score surface. ✅
- *High score ≠ guaranteed higher future return* → explicit on every surface
  ("not a forecast of returns") with the study's numbers in the expander. ✅
- *High-VIX regimes reduce reliability* → live regime-aware warning on Analyze
  Stock, Command Centre, Smart Screener, Tomorrow's Watchlist. ✅
- *No model change* → engine untouched; suite 300 passed; page smoke 18 passed. ✅

**Screenshots:** not capturable from this environment; the table above is the
authoritative before/after record. The components are visible at the top of the
four score surfaces after deploy.

*2026-06-11 · Phase 1 of the score-research action plan. Phase 2 (action-label
display mapping) and Phase 3 (evidence-gated component changes: pattern,
oversold-RSI) remain open, pending review.*
