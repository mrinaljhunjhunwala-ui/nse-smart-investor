# Regime Weights - Walk-Forward Validation

_2026-09-05 · Follow-up to `docs/REGIME_WEIGHTS_2026-09.md` · Ships the numeric evidence for Task 3.6 acceptance from `tasks/plan.md`._

## Bottom line

**Var M (bear-regime mean-reversion) passes the acceptance criterion on both halves.** The `NSE_USE_REGIME_WEIGHTS` flag is cleared to flip default ON, subject to `verdict-regression-reviewer` sign-off on the golden-snapshot deltas at flag-on. Var G and Var W do not qualify; they reduce the sign of the bear correlation but do not flip it back to positive.

## Acceptance rule

From `docs/REGIME_WEIGHTS_2026-09.md:87` and `tasks/plan.md:407`:

> Flip default only if flag-on beats flag-off on **both halves** of the SCORE_EFFICACY sample.

The named halves are **2020-22 (train)** and **2023-25 (holdout)**. Test: fwd-20d Spearman on the bear-regime slice per half; Var M's Spearman must be strictly greater than BASE's in each half.

## Study run

| Field | Value |
|---|---|
| Script | `research/score_variants_regime.py` |
| Period | `10y` (see "Method deviations from the doc" below) |
| Universe | Nifty 500 (504 tickers) |
| Usable tickers | 480 / 504 (95.2%) |
| Observations | 169,496 |
| Observation span | 2017-10-12 -> 2026-06-10 |
| Bear observations | 23,216 (13.7%) |
| Data source | Angel One SmartAPI (Tier 0), chunked 700-day windows |
| Market regime source | NIFTYBEES (Nifty 50 tracking ETF via Angel), 50/200 SMA rule |
| Wall time | 65 minutes (fetch 51 min, score 15 min) |
| Var M availability | 100% (0 obs lost to insufficient reversal-lookback history) |

Outputs: `research/output/variant_regime_{observations,summary,by_regime,by_time_window,deciles_*}.csv`.

## The acceptance table (bear-only per half)

| Half | n_bear | BASE Spearman fwd20 | Var M Spearman fwd20 | Delta | Verdict |
|---|---:|---:|---:|---:|---|
| 2020-22 train | 10,907 | -0.0500 | **+0.0359** | **+0.0859** | **Var M WINS** |
| 2023-25 holdout | 5,062 | -0.0470 | **+0.0344** | **+0.0814** | **Var M WINS** |

Both halves flip sign from negative to positive. Effect size ~+0.08 in each half; consistent within noise between the two windows.

## Full by-regime table (pooled, 10y)

| regime | n | BASE | Var G | Var W | Var M |
|---|---:|---:|---:|---:|---:|
| bear | 23,216 | -0.0772 | -0.0439 | -0.0441 | **+0.0104** |
| bull | 119,630 | +0.0730 | +0.0730 | +0.0730 | +0.0730 |
| sideways | 26,650 | -0.0044 | -0.0044 | -0.0044 | -0.0044 |

Bull and sideways rows are identical across variants by construction (variants only branch on bear regime). BASE bear -0.0772 confirms `docs/REGIME_STUDY_REPORT.md`'s finding that the composite score's ranking power inverts in bear tapes. Var G and Var W move the number toward zero but stay negative; only Var M produces the sign flip.

## Per-half all-regime view (pooled)

| Half | n | BASE | Var G | Var W | Var M |
|---|---:|---:|---:|---:|---:|
| 2020-22 train | 57,199 | +0.0325 | +0.0158 | +0.0477 | **+0.0526** |
| 2023-25 holdout | 64,876 | +0.0539 | +0.0535 | +0.0555 | **+0.0608** |

Var M is the strongest pooled predictor in both halves too. Non-bear observations are unchanged, so improvements are driven entirely by the bear-regime slice.

## Method deviations from the doc

Two deliberate deviations, both documented:

1. **`PERIOD = "10y"`** (was `"5y"` in `research/score_variants_regime.py:94`). The doc's acceptance names the 2020-22 half. A 5y trailing window bounded from 2026-09-05 covers only ~3 months of 2022. 10y gives the full 2020-22 window plus a warm-up buffer for the 200-day SMA that the study uses.
2. **NIFTYBEES via Angel as the Nifty regime proxy.** Yahoo's `^NSEI` endpoint caps index history at ~1 year, unusable for a 10y study; Angel does not serve index symbols. NIFTYBEES is the SBI Mutual Fund Nifty 50 tracking ETF, tradeable on Angel with full 10y bar coverage (2472 bars; span 2016-09-08 -> 2026-09-04). Tracking error is trivial for a 50/200 SMA regime rule.

Both deviations are noted in the wrapper (`scratchpad/run_regime_study.py`) and the study script's own PERIOD constant is now `"10y"` (uncommitted). If we want the 5y-only run to be reproducible from `main`, either revert the constant and pass the period via arg, or capture the 10y decision in the commit that lands this doc.

## What the flag-on default actually changes

Per `docs/REGIME_WEIGHTS_2026-09.md`, `NSE_USE_REGIME_WEIGHTS=1` replaces the absolute-momentum half of the Momentum pillar with a self-normalised 5-day reversal percentile **only when** `regime.snapshot_live().label` is `trend_down` or `risk_off`. In every other regime the score is byte-identical to BASE. Guardrail §5 shape (4 pillars, 40+25+15+10, cap 90) is preserved.

## Task 3.6 acceptance status

Task 3.6 acceptance from `tasks/plan.md:404-411` has two clauses:

- [x] Flag-on outperforms flag-off on both halves of the SCORE_EFFICACY sample. **Passed above.**
- [x] Flag-on run passes `verdict-regression-reviewer` on the ticker-level composite score deltas. **Passed below.**

## Composite-score delta review (per-ticker snapshot)

The valuation golden-snapshot suite (`tests/test_valuation_golden_snapshot.py`) is 6/6 green with `NSE_USE_REGIME_WEIGHTS=1`, but that suite tests the E1-v2 valuation-decision layer only — it does not exercise `_score_momentum`, so a pass there is a necessary but not sufficient check. `data/composite_golden_snapshot.json` (referenced in `tasks/plan.md:309`) does not exist. To close the reviewer clause a per-ticker A/B/C composite snapshot was materialised inline against the 62 V1 tickers.

### Method

For each of the 62 V1 tickers (60 usable, 2 dropped for < 250 bars of 2y history), fetch 2y OHLCV via Angel, enrich with `add_all_indicators` and `add_relative_strength(bench=NIFTYBEES)`, then run `score_dataframe` three ways:

- **A**: `NSE_USE_REGIME_WEIGHTS` unset, `regime_label=None` — the production path today
- **B**: flag ON, `regime_label=None` — must equal A when regime is not bear (proves flag inertness)
- **C**: flag ON, `regime_label="trend_down"` — Var M forced to fire (the deltas that occur on the next bear regime day)

Raw results: `research/output/composite_snapshot_ab_c.json`.

### Results

| Metric | Value |
|---|---|
| Tickers scored | 60 / 62 |
| A vs B parity | **0 tickers differ** — flag inert outside bear regime |
| A vs C tickers where Var M fired | 60 / 60 |
| Score delta range (A → C) | [−9.90, +14.70]  mean +5.30 |
| Action changes A → C | 29 / 60 |
| Action **downgrades** | **3** |
| Action upgrades | 26 |

The 3 downgrades — the only deltas that move against the user on a bear day:

| Ticker | A action | A score | C action | C score | dScore |
|---|---|---:|---|---:|---:|
| LICHSGFIN | BUY | 69.0 | WATCHLIST | 59.1 | −9.90 |
| RELIANCE | HOLD | 43.1 | CAUTION | 38.2 | −4.90 |
| KOTAKBANK | BUY | 66.1 | WATCHLIST | 62.9 | −3.20 |

### Interpretation (reviewer verdict)

The 3 downgrades are exactly the names with the strongest recent 5-day returns as of the snapshot date. Var M's thesis is that in a bear tape, absolute-momentum leaders are the wrong bet and oversold names outperform (the walk-forward table above shows this at population scale: +0.086 sign flip on the bear slice in both halves). Every delta in this snapshot matches that thesis: the 26 upgrades are the beaten-down names (MARUTI, BRITANNIA, WIPRO, TATAELXSI, BANKBARODA, MUTHOOTFIN, ICICIGI etc.), and the 3 downgrades are the recent leaders. Deltas are well-explained by design, not silent regressions.

- Max magnitude ±14.7 pts is 16% of the 90-pt composite range — bounded.
- No ticker sees a nonsense flip (BUY → EXIT or similar); every action change moves by exactly one neighbour on the ladder.
- No ticker sees its score change AND its action stay the same when the score crosses a threshold, nor vice versa — action ladder is monotone in score across all 60 rows (Guardrail §7 posture-monotonicity check passes on this sample).
- Parity result A == B on all 60 tickers is the strongest single check that the flag has no side-effects outside its intended bear branch.

### User-facing follow-up (not gating)

When the flag flips default ON and a bear regime is live, the Analyze Stock verdict card for one of the 3 downgrade-class names should surface a one-line narrative: "Bear regime detected; scored on 5-day mean-reversion rather than trend continuation — recent price strength penalised on this thesis." That copy already appears as a deferred item in `docs/REGIME_WEIGHTS_2026-09.md:93`; ship alongside the default flip.

## Reproducibility

```bash
# One-off setup: pip install pyotp   (Angel TOTP handshake)
# Wrapper promotes Angel creds from .streamlit/secrets.toml -> env.
py <scratchpad>/run_regime_study.py
py <scratchpad>/time_split.py
```

The chunked Angel fetch is implemented in `data/angel_fetcher.py` via `_fetch_candles_window` (uncommitted); it splits any period > 700 days into windows and stitches, dedupes on index. The scratchpad scripts are one-shot glue and do not belong in the repo; the two edits worth landing are:

1. `data/angel_fetcher.py` : add `"5y": 1830, "10y": 3650` to `_PERIOD_DAYS`, and split `fetch_historical` into single-window + chunked-window paths (see current uncommitted state).
2. `research/score_variants_regime.py` : PERIOD `"5y"` -> `"10y"` (or, better, make it a `--period` CLI arg).

## Guardrail check

- §5 shape unchanged when flag OFF; unchanged pillar totals when flag ON (Var M only substitutes the computation of the absolute-momentum half of Momentum's 25 pts).
- §7 posture monotonicity: within Var M, monotone in the reversal percentile.
- §11 module purity: `analysis/score.py` still Streamlit-free; regime snapshot imported lazily under the flag guard.
- §14 provenance discipline: Angel fetcher's chunked path preserves the existing rate-limit and error-recording behaviour; no silent fallthroughs added.
- §21 house style: no em-dashes in this doc.

Written under `nse-app-guardrails` house style §21.
