# Phase C1 — Test Coverage Report

`tests/test_valuation_liquidity.py` — **28 deterministic tests**, no network, no AI. All inputs are
hand-built (synthetic price frames / `RatioSnapshot`s), so results are reproducible.

```
py -m pytest tests/test_valuation_liquidity.py -q   → 28 passed in ~1.2s
py -m pytest tests/ -q                               → 166 passed   (138 prior + 28)
```

## Coverage by requirement

### Valuation mapping & missing values (8)
| Test | Asserts |
|---|---|
| `test_valuation_all_present_high_confidence` | pe/pb/ev mapped; confidence high; source set |
| `test_valuation_two_present_medium` | 2 present → medium; missing lists EV/EBITDA |
| `test_valuation_one_present_low` | 1 present → low; two missing |
| `test_valuation_none_present_confidence_none` | all None → none; 3 missing |
| `test_valuation_negative_pe_is_not_fabricated` | **negative P/E & zero P/B → None** (never a number) |
| `test_valuation_nan_and_inf_rejected` | NaN/inf → None |
| `test_valuation_handles_missing_cf_and_ratios` | None cf / no ratios → none, no crash |
| `test_valuation_to_dict` | serialisable dict |

### Turnover calculation (2)
| Test | Asserts |
|---|---|
| `test_turnover_calculation_exact` | turnover = mean(Close×Volume); volume = mean(Volume) |
| `test_tier_high_boundary` | turnover at the High threshold → High |

### Liquidity tier logic (6)
| Test | Asserts |
|---|---|
| `test_tier_medium` / `test_tier_low` / `test_tier_illiquid` | each band maps correctly |
| `test_liquidity_insufficient_history_is_unknown` | < 30 days → Unknown, turnover None |
| `test_liquidity_missing_columns` | no Volume column → Unknown |
| `test_liquidity_none_frame` | None frame → Unknown |

### Volume trend (4)
| Test | Asserts |
|---|---|
| `test_volume_trend_rising` | 30d ≫ 90d → rising, ratio > 1.2 |
| `test_volume_trend_falling` | 30d ≪ 90d → falling, ratio < 0.8 |
| `test_volume_trend_none_when_short_history` | ≥30 but <90 days → no trend |
| `test_format_turnover` | ₹ cr / lakh / dash formatting |

### Thesis integration (5)
| Test | Asserts |
|---|---|
| `test_thesis_high_liquidity_bull_factor` | High tier → Liquidity **bull** with ₹cr evidence |
| `test_thesis_low_liquidity_risk_factor` | Illiquid → "execution risk" **risk** factor |
| `test_thesis_low_tier_also_triggers_risk` | Low tier also → risk |
| `test_thesis_medium_liquidity_no_factor` | Medium → no liquidity factor |
| `test_thesis_liquidity_in_provenance` | `Liquidity` in `inputs_present` |

### Portfolio-fit integration (3)
| Test | Asserts |
|---|---|
| `test_fit_illiquid_caps_position_to_small` | Illiquid → **Small** (capped), reason cites illiquidity |
| `test_fit_low_liquidity_is_a_pressure` | Low → one pressure → Moderate |
| `test_fit_high_liquidity_no_penalty` | High → Large (unaffected) |

## Properties exercised
- **Never-fabricate:** negative/zero/NaN/inf multiples → None (3 dedicated tests).
- **Graceful degradation:** short history, missing columns, None frame, missing cf/ratios.
- **Determinism:** pure functions over hand-built inputs; no network in any test.
- **Exact arithmetic:** turnover = mean(Close×Volume) and volume = mean(Volume) asserted against
  known synthetic values.

## Regression
Full suite **166 passed** — the 138 pre-existing tests (portfolio risk, fundamentals, thesis A1,
portfolio fit B) are untouched; the only schema change (`RatioSnapshot.ev_ebitda`, default None) is
backward-compatible.
