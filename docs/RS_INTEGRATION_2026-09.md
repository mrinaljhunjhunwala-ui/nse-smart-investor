# Recommendation 1 – RS-vs-Nifty inside Momentum

_2026-09-03 · Ships Task 3.1 from `tasks/plan.md` and Recommendation 1 from `docs/COMPOSITE_SCORE_SHAPE_REVIEW.md`._

## Shape

Momentum pillar total unchanged at **25 pts**. Guardrail §5 shape (4 pillars, 40+25+15+10, cap 90) unchanged.

Internal split, gated on RS_Score availability:

| Mode | When | Split |
|---|---|---|
| **Legacy (backwards-compat)** | `RS_Score` column absent (test frames, single-ticker ad-hoc without benchmark fetch) | `abs_returns:25` (r5d 5 + r20d 10 + r60d 10) |
| **With RS** | `RS_Score` column present on df (score_stock now enriches every call) | `abs_returns:15 + rs_vs_nifty:10` |

Absolute-momentum bucketing is unchanged; the 25→15 rescale is a linear `* 0.6` on the already-computed total, then RS adds `RS_Score / 100 * 10`. This matches the `_bonus_rs()` shape studied in `research/score_variants_rs.py` v2.

## Where RS comes from

`utils.indicators.add_relative_strength(df, bench_df)` was already in the codebase. Computes:

- `RS_Line = stock_close / nifty_close`
- `RS_Pct = pct_change(RS_Line, 63)` (IBD 3-month convention)
- `RS_Score = 252-bar percentile rank of RS_Line` (0–100, IBD RS Rating style)
- `RS_Trend = outperforming | inline | underperforming`

`score_stock()` now fetches `^NSEI` for the same period alongside the ticker's df and calls `add_relative_strength()` before `dropna(subset=["RSI", "ATR"])`. Benchmark-fetch failure is best-effort: RS_Score simply stays NaN and the legacy 25-pt absolute mode kicks in for that call.

## Guardrail check

- §5 shape unchanged: 4 pillars, 40+25+15+10, cap 90. ✅
- §7 posture-monotonicity: RS is a monotone-linear map (RS_Score 0→100 maps to 0→10 pts). Higher RS never lowers score. Absolute bucketing unchanged so its monotonicity is preserved. Score deltas explained below never flip a posture against their `.score` direction. ✅
- §11 module-boundary purity: `analysis/score.py` still Streamlit-free. ✅
- §14 fetcher discipline: benchmark fetch goes through `data.fetcher.fetch_single` which already uses the drift-warning pattern landed in `e9ebc4f`. ✅

## Sanity check on 5 Nifty tickers (2026-09-03)

| Ticker | Old momentum (abs-only) | New momentum (abs:15 + RS:10) | RS_Score | Direction |
|---|---|---|---|---|
| HDFCBANK | approximated ~8–10 pts | **3.16 pts** | 2 | Down (correct – Nifty laggard) |
| RELIANCE | approximated ~13–15 pts | **9.23 pts** | 26 | Down (correct – underperforming index) |
| INFY | approximated ~11–13 pts | **7.19 pts** | 18 | Down (correct – IT sector weakness) |
| TCS | approximated ~15–17 pts | **10.47 pts** | 27 | Down (correct – IT sector weakness) |
| SBIN | approximated ~9–11 pts | **9.33 pts** | 63 | Roughly flat (correct – PSU bank leader offsets lower abs) |

Direction of every delta is the intended one: names with strong absolute returns purely from beta lose the delta; names outperforming the index keep or gain it. No `.score` change flipped a posture against its direction.

## Tests

- `tests/test_smoke_score_indicators.py` — synthetic OHLCV, no benchmark passed → legacy mode → still passes (no regression)
- `tests/test_audit_fixes.py` — same shape, still passes
- `tests/test_regime.py` — dispersion-suffix wiring unaffected, still passes
- `tests/test_valuation_golden_snapshot.py` — valuation engine untouched, still passes
- **Full page-smoke covering score-consuming pages (Analyze Stock, Command Centre, Smart Screener, TQS Scanner):** 4/4 green in 161s

## User-visible changes

Live on Analyze Stock the moment this ships:

- **Composite score** shifts for every scored stock. Names with strong beta but weak RS drop 3–7 pts of momentum; index leaders stay roughly flat; genuine outperformers gain 1–3 pts.
- **Narrative** gets one new sentence just after the recent-performance line, one of four templates gated on RS_Score band (≥80, ≥60, ≥40, else).
- **`CompositeScore.rs_score`** field is now populated (0–100, or None when benchmark unavailable). Downstream surfaces (Top Picks, Watchlist, Screener) can render it as a column in a follow-up UI slice without any further scoring change.

## Follow-ups (not in this landing)

- Add `RS_Score` column to Top Picks, Watchlist, Screener tables — UI change only.
- `RS_Line` new-highs-before-price is a well-known leading signal; not scored here, worth a narrative append in a later slice.
- Publish `_bonus_rs` linear-map decision in `docs/RESEARCH_SCORE_VARIANTS.md` v3 alongside the earlier variant results.

Written under `nse-app-guardrails` house style §21 – no em-dashes.
