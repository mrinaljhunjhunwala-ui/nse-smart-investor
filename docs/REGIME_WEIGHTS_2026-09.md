# Recommendation 5 – Regime-conditional weight dispatch (opt-in flag)

_2026-09-03 · Ships Task 3.6 from `tasks/plan.md` and Recommendation 5 from `docs/COMPOSITE_SCORE_SHAPE_REVIEW.md`._

## What this ships and what it does NOT ship

**Ships:** the code mechanism to dispatch the Momentum sub-score to an alternative bear-regime computation, gated behind an environment variable (`NSE_USE_REGIME_WEIGHTS`) that **defaults OFF**. With the flag off, production scoring is byte-identical to pre-Rec-5.

**Does NOT ship:** flipping the flag to default ON. Task 3.6 says explicitly: "Flip default only if the flag-on run beats flag-off on **both halves** of the SCORE_EFFICACY sample." That validation requires end-to-end runs of `research/score_variants_regime.py` on the 5-year universe (5–7 minutes each, needs network). Until you run it and the numbers survive, the default stays off.

## Design choice: Var M, not Var G or Var W

The regime variant study (`research/score_variants_regime.py`, ~373 lines, never yet run) proposed three variants:

| Variant | Bear-regime behavior | Shape | Guardrail §5 |
|---|---|---|---|
| Var G "Gate" | zero momentum, no reinvestment | 65-pt scale in bear only | **Violates** (pillar sums change) |
| Var W "Reweight" | momentum's 25 pts reinvested into technical (tech pays 65 in bear) | 40+25→65+0 in bear | **Ambiguous / likely violates** (per-pillar cap moves) |
| **Var M "Mean-reversion"** | replace absolute-momentum computation with self-normalised 5d reversal percentile | 4 pillars, 40+25+15+10 unchanged | **Preserved** |

Var M is the only one that ships within the guardrail. It replaces the *computation* of the absolute-momentum half of the pillar; the pillar total (25) and every other pillar are untouched. The RS component (Rec 1's 10 pts) stays too.

If you eventually want Var G or Var W's shape change, that would need explicit ratification like Rec 6's Positioning pillar decision.

## What Var M computes in bear regime

Absolute-momentum half is replaced by:

```
percentile of stock's trailing-5-day return within its own 252-day
distribution of 5-day returns, inverted, scaled to 0..15 pts
```

Low recent 5d return → high reversal score. Self-normalised so no cross-sectional lookahead. Direct implementation of Var M from the study, per `_score_momentum_mean_reversion()`.

RS component (10 pts) stays unchanged in both modes.

## Regime label sources

`analysis.regime.snapshot_live()` returns labels from `{trend_up, trend_down, range, risk_off}`. Rec 5 maps to bear when the label is `trend_down` or `risk_off`. Anything else runs the base path.

`score_stock()` loads the snapshot only when the flag is ON, so the network / DB hit is skipped in production entirely today.

## Guardrail check

- §5 shape unchanged: 4 pillars, 40+25+15+10, cap 90. ✅ (Var M keeps the pillar totals; only Momentum's internal computation branches on regime + flag.)
- §7 posture-monotonicity: within Var M, monotone in the reversal percentile — higher reversal signal pays more pts. Doesn't create a case where a stock's `.score` improves and posture flips negative. ✅
- §11 module purity: score.py still Streamlit-free; regime snapshot imported lazily under the flag guard. ✅
- **Default OFF** — production output is byte-identical to pre-Rec-5. No SCORE_EFFICACY-eroding surprise. ✅

## Verification (2026-09-03)

Bounds check on synthetic OHLCV (300 bars, sharp last-5-day drop, RS absent to force ad-hoc mode):

| Flag | Regime | Momentum / 25 | Variant chosen |
|---|---|---|---|
| OFF | (none) | 8.00 | legacy_abs_only |
| OFF | trend_down | 8.00 | legacy_abs_only |
| ON | trend_up | 8.00 | legacy_abs_only |
| ON | trend_down | 15.00 | **M_bear_mean_reversion** (r5d percentile 0.0 = worst) |
| ON | risk_off | 15.00 | **M_bear_mean_reversion** |

Default-off byte-equivalence to pre-Rec-5 confirmed on all three of {no regime, bull, bear}.

## Tests

- `tests/test_smoke_score_indicators.py`, `test_audit_fixes.py`, `test_regime.py`, `test_valuation_golden_snapshot.py`, `test_provenance_nse_delivery.py`: 64/64 in 6s
- `tests/test_pages_smoke.py -k "04_analyze_stock or 02_command_centre"`: 2/2 in 56s

## What you'll see on the app

**Today, with the flag off**: nothing changes. Every score matches pre-Rec-5 exactly.

**When you flip the flag on** (`set NSE_USE_REGIME_WEIGHTS=1` in the Streamlit Cloud secrets, or export it before `py -m streamlit run`):

- **In bull / range regimes** — still nothing changes. Base path only.
- **In bear regimes** — Momentum sub-scores shift meaningfully. Names down 4–8% in the last 5 sessions gain up to 15 pts of momentum (they were near-zero under the trend-following default). Names that held up in the sell-off lose points. The composite score moves in the same direction as the momentum sub-score.
- **`mom_detail.variant`** exposes which path fired (`legacy_abs_only`, `base_abs_plus_rs`, or `M_bear_mean_reversion`). Downstream surfaces can display it.

## How to run the validation (before flipping the default)

```bash
py -m research.score_variants_regime --limit 20        # pipeline check
py -m research.score_variants_regime                    # full 5-year universe
```

Outputs go to `research/output/variant_regime_*.csv`. Task 3.6 acceptance criterion: flag-on must beat flag-off on BOTH the 2020–22 train and 2023–25 holdout partitions. If it only wins on one half, keep the default off — that's overfitting to the trained window.

## Follow-ups (not in this landing)

- **Run the study.** Reserve an evening; 5–7 minute wall time per full pass.
- **Regime confidence gate**: `snapshot_live()` returns a `confidence` bucket. Consider only dispatching Var M when `confidence >= medium` so a shaky bear read doesn't over-torque scoring.
- **Narrative sentence** — when Var M fires, append "Bear regime detected; scored on 5-day mean-reversion, not trend-continuation." Small change; deferred until the flag is close to default-on.
- **UI badge** on Command Centre when the flag is on, so the user knows they're seeing v2 scoring.

Written under `nse-app-guardrails` house style §21 – no em-dashes.
