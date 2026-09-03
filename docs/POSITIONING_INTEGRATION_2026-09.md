# Recommendation 6 – Positioning pillar (design 6a, opt-in flag)

_2026-09-03 · Ships Task 3.7 (unlisted MVP) from `tasks/plan.md` and Recommendation 6 from `docs/COMPOSITE_SCORE_SHAPE_REVIEW.md`._

_**Shape change ratified by user 2026-09-03.** Guardrail §5 updated to reflect the ratified exception – see `.claude/skills/nse-app-guardrails/SKILL.md`._

## What this ships

**The mechanism, honestly gated.** Design 6a of the shape review says: F&O-eligible tickers with the opt-in flag on aggregate as `35 tech + 20 mom + 15 vol + 10 sent + 10 positioning = 90`. Non-F&O tickers and everything with the flag off keep the legacy `40 + 25 + 15 + 10 = 90`. The cap stays 90 in either case.

## What this does NOT ship

**Real data for any of the four positioning sub-inputs.** The codebase has zero existing options / OI / PCR / max-pain infrastructure – the intraday page has a manual PCR slider, nothing more. Each of the four sub-inputs is queued as its own follow-up commit with its own canary and drift discipline. Until they land the pillar sees `positioning_info=None` and gracefully does not activate, so no ticker's score changes even with the flag on.

## Activation rules (three-way AND gate)

The Positioning pillar is applied to a ticker's aggregated score only when **all three** are true:

1. `NSE_USE_POSITIONING_PILLAR` env var is truthy (`1`, `true`, `yes`, `on`)
2. `data.fno_universe.is_fno_eligible(ticker)` returns True (starter list of ~60 large-cap F&O names; see follow-ups)
3. At least one of `{oi_regime, pcr, max_pain_distance_pct, fii_deriv_net_cr}` is non-None on the `positioning_info` dict passed to `score_dataframe`

Rule 3 is deliberate: without it, flipping the flag on before the data pipelines are online would shave ~1.8 pts off every F&O name (rescaled tech + mom would lose 7-8 pts, replaced by only 5 pts of neutral-midpoint positioning). Requiring at least one real input means the flag flip is a **no-op until data arrives**, then activates per-ticker as data comes in.

## Sub-scores (10 pts total, all graceful when data absent)

| Sub-input | Points | Neutral default (when absent) | Best-case | Worst-case |
|---|---|---|---|---|
| OI regime | 3 | 1.5 | long_buildup 3.0 | short_buildup 0.0 |
| PCR | 2 | 1.0 | extreme fear 2.0 (contrarian bull) | extreme complacency 0.5 |
| Max-pain distance % | 2 | 1.0 | far from pin 1.5 | right at pin 0.5 |
| FII deriv net (Rs Cr) | 3 | 1.5 | > +5000 (heavy net long) 3.0 | < -5000 (heavy net short) 0.0 |
| **Total** | **10** | **5.0** | **9.5** | **1.0** |

Sub-inputs default to their neutral midpoints (not zero) so that a "some data, not all" state is honest: unknown reads no more penalise a name than they promote it.

## Aggregation

`score_dataframe` applies the rescale **only at aggregation time**. Sub-scorer outputs are unchanged: `_score_technical` still returns pts on its 40-pt scale, `_score_momentum` on its 25-pt scale. This is deliberate – tests and any caller reading `tech_pts / mom_pts` directly stay calibrated. The scale-down (`* 35/40` and `* 20/25`) is applied only in the aggregation branch when the three-way gate qualifies.

Verified end-to-end:

| Scenario | Score | Notes |
|---|---|---|
| Flag OFF, F&O ticker (RELIANCE) | 63.0 | Legacy path, `positioning_score=None` |
| Flag ON, F&O ticker, no positioning data | 63.0 | Byte-identical to baseline – no-bias gate holds |
| Flag ON, F&O ticker, bullish positioning inputs | 65.7 | 5-pillar path, `positioning_score=9.5` |
| Flag ON, F&O ticker, one input (`oi_regime` only) | 62.7 | Partial data activates, `positioning_score=6.5` |
| Flag ON, non-F&O ticker (IRCON) | 63.0 | Legacy path (rule 2 fails), `positioning_score=None` |

## Guardrail check

- **§5 shape change** ratified 2026-09-03 in the session that landed this. Updated in the guardrails file to reflect design 6a. F&O-eligible + flag-on + data-present = 5 pillars, 35+20+15+10+10=90. Everything else = legacy 4 pillars, 40+25+15+10=90. Cap always 90. ✅
- §7 posture-monotonicity: every sub-score is monotone in its input; rescale factors are constants; positioning pts only add to total. No case where an input improvement reduces `.score`. ✅
- §11 module purity: `analysis/score.py` still Streamlit-free; new import `data.fno_universe` is pure (frozenset + normaliser only). ✅
- §14 fetcher discipline: N/A this landing – no new fetcher. Each of the four data-pipeline follow-ups will add its own with canary tests.
- **Golden snapshot** (`data/valuation_golden_snapshot.json`) untouched – it exercises the valuation engine, not `score_stock` / `score_dataframe`. `tests/test_valuation_golden_snapshot.py` passes green.

## Tests

- Full score regression (57 in the existing suite + 6 in `test_provenance_nse_delivery.py`): **64/64 pass in 5s**
- Bounds check on `_score_positioning`: all-neutral 5.0/10, best 9.5/10, worst 1.0/10 – all as designed
- End-to-end via `score_dataframe`: all five scenarios above return the expected scores

## User-visible changes on the app

**Today: none.** The flag defaults OFF; even with it on, no ticker sees a change until at least one positioning data pipeline ships.

**When the flag flips + at least one positioning input arrives for an F&O ticker:**
- Composite score shifts by up to ±5 pts on that ticker, in the direction of the positioning quadrant.
- `CompositeScore.positioning_score` field populates (0-10 or None).
- `CompositeScore.is_fno` field is populated on every ticker regardless of flag (informational).

## Follow-up data pipelines (queued as their own commits)

Each of these is a separate commit, each lights up one sub-score:

1. **OI regime** – `data/nse_fno_bhavcopy.py` fetches `fo_bhavdata_DDMMYYYY.csv`; delta OI + sign of price change gives the four-way classification. Same shape as `data/nse_delivery.py`, same DB persistence pattern, same canary discipline.
2. **PCR + max-pain** – NSE options-chain snapshot (`/api/option-chain-equities?symbol=X`). Rate-limited from cloud IPs, needs residential-IP scheduler like `refresh_qualitative_flags.py`.
3. **FII deriv net** – NSE F&O participants-wise stats file (`fao_participant_oi_DDMMYYYY.csv`). One file per day, universe-level (single Nifty/BankNifty read applies to all F&O tickers).
4. **F&O universe refresh** – `data/fno_universe.py` starter list is ~60 names. Monthly refresh from the NSE F&O eligibility circular is a Task Scheduler entry, not code.

Each follow-up ships:
- Fetcher + parser with Guardrail §14 discipline (named `ValueError` on drift, WARN on silent-empty)
- Persistence into shared `trade_store` (SQLite + Postgres both)
- Read API returning the score-consumer's expected input shape
- Offline canary tests per Guardrail §16
- Reviewer writeup crediting the follow-up commit

## Recommended sequence

1. **Land this commit** (mechanism only – zero user-visible change)
2. **Ship OI regime pipeline** – highest-leverage, cheapest (bhavcopy is same pattern as delivery), 3 pts of the 10
3. **Ship FII deriv pipeline** – one file per day, 3 pts of the 10
4. **Ship PCR + max-pain from options-chain** – biggest data engineering, 4 pts of the 10 combined
5. **Run validation study** analogous to `research/score_variants_regime.py` for the full pillar
6. **Refresh F&O universe** as an operational task, not a code change

At any point during 2-4 the flag can be flipped for testing; the three-way gate means it only activates on tickers where data has actually arrived.

Written under `nse-app-guardrails` house style §21 – no em-dashes.
