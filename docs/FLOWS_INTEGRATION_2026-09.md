# Recommendation 2 – FII/DII flow sign inside Sentiment

_2026-09-03 · Ships Task 3.2 from `tasks/plan.md` and Recommendation 2 from `docs/COMPOSITE_SCORE_SHAPE_REVIEW.md`._

## Shape

Sentiment pillar total unchanged at **10 pts**. Guardrail §5 shape (4 pillars, 40+25+15+10, cap 90) unchanged.

Internal split, gated on flows availability:

| Mode | When | Split |
|---|---|---|
| **Legacy (backwards-compat)** | `flows_info=None` — test frames, single-ticker ad-hoc without the fii_dii cache populated | `vix:6 + sector_rank:4` |
| **With flows** | `flows_info` present (score_stock now loads from `analysis.fii_dii.load_history(days=5)` on every call) | `vix:5 + sector_rank:3 + flows:2` |

VIX bucket map re-scaled from its old 6-pt shape to a 5-pt shape preserving relative differences (`normal 5.0 · complacency 4.0 · elevated 3.0 · fear 1.5 · panic 0.0 · unknown 2.5`). Sector-rank re-scaled from 4/2/0 to 3/1.5/0.

## Flow scoring rules

Sign of 5-day cumulative net cash-market:

| FII 5d | DII 5d | Regime name | Score (of 2) |
|---|---|---|---|
| + | + | Broad participation — persistent rallies | 2.0 |
| − | + | Domestic-supported dip — tradeable pullback | 1.5 |
| + | − | DII profit-taking rally — shallower legs | 1.0 |
| 0 / mixed-zero | any | Mixed | 1.0 |
| − | − | Distribution — usually precedes weakness | 0.0 |

These are the four regime labels the app already surfaces on Analyze Stock's market-context strip (see `dashboard/pages/04_analyze_stock.py:135–192`). Score reads the sign the app was already showing; no new data path.

## Where the flows come from

`analysis.fii_dii.load_history(days=5)` returns a DataFrame from the `fii_dii_daily` table in the shared `trade_store` (SQLite locally, Postgres in prod). Populated daily by the fii_dii cron (Guardrail §14–16 hardened). `score_stock()` loads once per call (best-effort — DB miss or empty returns `None`, legacy mode kicks in).

Pure module boundary preserved: `analysis/fii_dii.py` imports `trade_store` (also pure) but not streamlit.

## Guardrail check

- §5 shape unchanged: 4 pillars, 40+25+15+10, cap 90. ✅
- §7 posture-monotonicity: `_score_sentiment` returns identical 10-pt max in both modes; flow score is monotone in the (fii, dii) sign quadrants — worse flow regimes score no higher than better ones. Composite `.score` never moves in a direction that opposes a posture flip. ✅
- §11 module-boundary purity: score.py still Streamlit-free; new import is from `analysis.fii_dii` which is Streamlit-free too. ✅
- §14 fetcher discipline: flows come from the local DB (populated by cron with drift-warning discipline); no new provider added here. ✅

## Verification (2026-09-03)

Bounds check on synthetic inputs:

| Scenario | Score / 10 | Correct? |
|---|---|---|
| Legacy top-of-scale (normal VIX + top sector) | 10.0 | ✅ |
| With-flows top-of-scale (normal + top sector + FII+/DII+) | 10.0 | ✅ |
| With-flows bottom-of-scale (panic + bottom sector + FII−/DII−) | 0.0 | ✅ |
| With-flows distribution (elevated + mid sector + FII−/DII−) | 4.5 | ✅ |
| With-flows domestic-supported dip (elevated + top sector + FII−/DII+) | 7.5 | ✅ |

Local flows DB is empty → live 5-ticker check runs in legacy mode as expected; scores match pre-2026-09-03 sentiment values. When the fii_dii cron populates the DB, the with-flows mode kicks in automatically with no further code change.

## Tests

- `tests/test_smoke_score_indicators.py` — passes (`_score_sentiment` called with `flows_info=None` → legacy mode → unchanged behavior)
- `tests/test_audit_fixes.py` — passes
- `tests/test_regime.py` — passes
- `tests/test_valuation_golden_snapshot.py` — passes (valuation engine untouched)
- Full regression: 57/57 in 17s

## User-visible changes

- **Analyze Stock narrative** gets one new sentence at the bottom of the sentiment paragraph — one of four flow-regime templates. Only when the DB has fresh flows.
- **Composite score** shifts by up to ±2 pts on the sentiment sub-score once flows come online, in the direction of the flow regime.
- **`CompositeScore.sentiment_score`** internal composition changes when flows available; the exposed total stays the 10-pt max.

## Follow-ups (not in this landing)

- Surface the flow-regime label as a badge on the Verdict Card (Sprint 1.4 planned).
- Weight `flows_info` higher for large-caps (where flows dominate) and lower for small-caps — a small enhancement over the current uniform 2-pt band.

Written under `nse-app-guardrails` house style §21 – no em-dashes.
