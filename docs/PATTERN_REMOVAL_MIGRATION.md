# Pattern Removal Migration — Variant A in Production

**Change:** the 10-pt candlestick-pattern component no longer contributes to the
composite (Trend Quality) score. Patterns are still detected and shown in the
narrative — they are informational only. No other factor was modified; the
oversold-RSI bonus is untouched; freed points are **not** redistributed (that
reweighting would need its own evidence), so the composite now tops out at
**90** while grade/action thresholds stay unchanged — a deliberate, slightly
stricter calibration.

**Evidence basis:** RESEARCH_SCORE_VARIANTS.md (40,663 obs, 5y) — the pattern
component had zero-to-negative ranking power in every market regime; removal
improved return correlation, decile monotonicity and 6-of-7 regime behaviours.

---

## 1. Pre-implementation impact quantification

Measured on the 40,663 walk-forward observations (BEFORE = with pattern,
AFTER = Variant A; both mapped through the unchanged grade/action thresholds):

**Score movement** — 16.6% of observations change, **always downward**
(pattern only ever added points): mean −4.0 pts when changed, max −10.

**Grade distribution (%):**

| Grade | Before | After |
|---|---|---|
| A+ | 0.0 (rare) | **0.0 (now ~unreachable: needs 88/90)** |
| A | 1.9 | 1.2 |
| B | 17.6 | 17.4 |
| C | 24.5 | 24.3 |
| D | 35.5 | 34.7 |
| F | 20.5 | 22.4 |

**Action distribution (%):**

| Action | Before | After |
|---|---|---|
| STRONG BUY | 0.4 | 0.2 |
| BUY | 14.2 | 13.6 |
| WATCHLIST | 22.2 | 22.1 |
| HOLD | 23.9 | 23.5 |
| CAUTION | 33.7 | 34.2 |
| EXIT | 5.5 | 6.5 |

**Label transitions** — 4.45% of observations move, all exactly one band down:
STRONG BUY→BUY 106 · BUY→WATCHLIST 352 · WATCHLIST→HOLD 403 · HOLD→CAUTION 575
· CAUTION→EXIT 372 (of 40,663).

**User-visible effects:** Top Picks buy lists will be slightly thinner /
lower-scored on days when picks carried pattern points (~1 in 6 scores affected);
watchlist scores likewise. EXIT labels become ~18% more frequent. Direction of
drift is uniformly conservative — no stock scores *higher* than before.

## 2. What changed in code

| File | Change |
|---|---|
| `analysis/score.py` | `total = tech + mom + vol + sent` (pattern excluded); `pattern_score` field now always `0.0`; `_score_pattern` retained for narrative pattern detection; module docstring updated (90-pt max, rationale + references) |
| `dashboard/pages/15_investor_guide.py` | Score header "0 – 90"; four-factor description; component table marks Candlestick as "0 pts — info only" with the study rationale |
| `dashboard/shared/disclosures.py` | "What this score measures" updated (max 90; patterns shown for context, not scored) |

Not changed: weights of remaining factors, all thresholds, grades, actions,
oversold-RSI bonus, entry/SL/TP logic, backtests, portfolio logic, research
harnesses.

## 3. Post-implementation regression — production matches research

All three research harnesses re-run against the changed production scorer
(2026-06-11). Predicted = the Variant A row from RESEARCH_SCORE_VARIANTS.md;
Measured = the new production score replayed over the same 5y window:

| Metric | Predicted (Variant A) | Measured (production, post-change) |
|---|---|---|
| Trend-persistence ρ | 0.4134 | **0.4133** |
| fwd-20d return ρ | 0.0439 | **0.0439** |
| fwd-60d return ρ | 0.0358 | **0.0358** |
| Regime ρ — bull | 0.0589 | **0.0589** |
| Regime ρ — sideways | 0.0818 | **0.0818** |
| Regime ρ — bear | −0.0105 | **−0.0104** |

Exact agreement (≤0.0001) — the production implementation reproduces the
researched variant. The variant harness's BASE now equals the old Variant A,
and the component-attribution pattern row is NaN (constant zero), both as
expected.

**Test suite:** 300 passed (unchanged count — `0 ≤ pattern_score ≤ 10`
assertions hold for the constant 0.0). Page smoke: all pages load.

## 4. Rollback

Single-commit revert (`git revert` of this change) restores the previous
behaviour exactly; no data migrations were involved. The research harnesses
serve as the regression gate in either direction.

*2026-06-11 · Evidence chain: SCORE_EFFICACY_REPORT.md → REGIME_STUDY_REPORT.md
→ RESEARCH_SCORE_VARIANTS.md → this migration.*
