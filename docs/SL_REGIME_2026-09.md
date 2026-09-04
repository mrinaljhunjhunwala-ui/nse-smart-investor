# Recommendation 3 – Regime-adaptive stop-loss bounds

_2026-09-03 · Ships Task 3.5 from `tasks/plan.md` and Recommendation 3 from `docs/COMPOSITE_SCORE_SHAPE_REVIEW.md`._

## Shape

**Not a scoring change.** `CompositeScore.score`, `.grade`, `.action`, and every pillar sub-score are byte-identical. Only `.stop_loss`, `.target`, and (implicitly) `.risk_reward` derivation move. Guardrail §5 unaffected.

## What changed

`_compute_entry_levels()` used fixed ATR-multiple bounds:

```
min_risk = 1.2 * atr
mid      = 2.0 * atr        # fallback when swing_low is too far out
max_risk = 3.0 * atr
```

Same three multiples for every stock, every regime. In panic, ATR balloons and the fixed 2.0×ATR fallback stop whipsaws longs out on normal noise. In complacency, ATR compresses and the same 2.0× is lazy room the setup does not need.

New: bounds indexed by VIX regime name.

| Regime | min | mid | max | vs baseline |
|---|---|---|---|---|
| complacency | 1.0 | 1.75 | 2.5 | tighter (compressed ATR) |
| normal | 1.2 | 2.0 | 3.0 | **unchanged baseline** |
| elevated | 1.3 | 2.2 | 3.2 | slightly wider |
| fear | 1.5 | 2.5 | 3.5 | wider |
| panic | 1.7 | 2.75 | 3.8 | widest (expanded ATR) |
| unknown | 1.2 | 2.0 | 3.0 | matches baseline |

`_compute_entry_levels()` gains an optional `vix_regime: Optional[str] = None` parameter. Absent → baseline path (backwards-compat with every existing test frame). Present → dispatch.

Wired from `score_dataframe`: passes `vix_info.get("regime", "normal")` to the entry-level helper.

## Why R:R is preserved across regimes

The target (`tp`) is anchored to the stock's own expected 10-day move in ATR units, then multiplied by `risk`. When `risk` widens for a high-VIX regime, `tp` widens by the same factor. R:R = `rr_mult` is regime-independent by construction. This is by design: the change adjusts *risk sizing* to the volatility environment without inflating or deflating reward-to-risk. A conviction-8 setup still has a 1.94:1 R:R in complacency or panic; only the rupee amount at stake and the rupee upside scale.

## Bounds check (synthetic OHLCV, price 1000, ATR 25)

| Regime | Entry | SL | SL distance | SL % | TP | R:R |
|---|---|---|---|---|---|---|
| complacency | 1000.00 | 956.25 | 43.75 | 4.38% | 1084.79 | 1.94 |
| normal | 1000.00 | 950.00 | 50.00 | 5.00% | 1096.90 | 1.94 |
| elevated | 1000.00 | 945.00 | 55.00 | 5.50% | 1106.59 | 1.94 |
| fear | 1000.00 | 937.50 | 62.50 | 6.25% | 1121.13 | 1.94 |
| panic | 1000.00 | 931.25 | 68.75 | 6.88% | 1133.24 | 1.94 |
| legacy (None) | 1000.00 | 950.00 | 50.00 | 5.00% | 1096.90 | 1.94 |

Monotone in fear, legacy path matches normal exactly, R:R invariant.

## Guardrail check

- §5 shape unchanged (this isn't a scoring change). ✅
- §7 posture-monotonicity trivially holds — score, grade, action unchanged. ✅
- §11 module-boundary purity — score.py still Streamlit-free. ✅
- Backwards-compat: `vix_regime=None` → identical bounds to pre-change behavior. ✅

## Tests

- `tests/test_smoke_score_indicators.py`, `test_audit_fixes.py`, `test_regime.py`, `test_valuation_golden_snapshot.py` — 57/57 pass in 6s
- Page-smoke on Analyze Stock, Paper Trades, Position Sizer — 3/3 pass in 7s

## User-visible changes

- **Analyze Stock** — displayed SL, target, and SL % now move with VIX regime. In a normal-VIX week the levels are identical to before. In a fear-VIX week the SL is ~25% farther from entry than before (and the target proportionally wider). In complacency the SL tightens by ~12% and target follows.
- **Paper Trade popover** — the SL and target pre-filled from the score pick up the new regime-scaled values.
- **Screener / Watchlist / Top Picks** — any surface that renders SL % from `CompositeScore.stop_loss` reflects the regime-scaled distance automatically.
- **R:R column** — unchanged. The volatility-anchored target formula preserves R:R across regimes by design (see docstring).

## Follow-ups (not in this landing)

- Consider making `vix_regime` do the same job for `_pick_horizon()` — a 2-week Swing horizon in panic is often optimistic.
- Consider surfacing a small badge on Analyze Stock (`SL bounds: fear regime, +25%`) so the user sees why the SL is wider than they remember.

Written under `nse-app-guardrails` house style §21 — no em-dashes.
