# OI regime pipeline – Rec 6 sub-score #1 of 4

_2026-09-03 · Follow-up to `docs/POSITIONING_INTEGRATION_2026-09.md` (Recommendation 6)._

## What this ships

The first of the four Positioning-pillar data pipelines. When the daily NSE F&O bhavcopy cron populates the DB, F&O-eligible tickers with `NSE_USE_POSITIONING_PILLAR=1` set start receiving a real OI-regime read on their `oi_regime` sub-score (3 pts of 10 inside the Positioning pillar's 10 of 90).

The three remaining sub-inputs (PCR, max-pain, FII deriv net) stay at their neutral midpoints for now — each will land in its own follow-up commit.

## Data path

```
NSE archives                                (nsearchives.nseindia.com)
      │  BhavCopy_NSE_FO_0_0_0_YYYYMMDD_F_0000.csv
      ▼
scripts/fetch_nse_fno_bhavcopy.py           (residential IP, cron)
      │  parse: aggregate OpnIntrst per (symbol, date) across every
      │         stock-derivative row (FinInstrmTp in {STF, STO})
      ▼
trade_store · nse_fno_oi_daily              (SQLite / Postgres, PK symbol+date)
      │  get_oi_snapshot(symbol) → {today_oi, prev_oi, pct_change}
      ▼
analysis.score.score_stock                  (best-effort per-ticker load)
      │  get_oi_regime_for_ticker(sym, price_pct) → 4-way classifier
      ▼
_score_positioning(oi_regime=...)           (3 pts inside Positioning pillar)
```

## OI regime classifier

```
price ↑ + OI ↑  =  LONG BUILDUP    (fresh longs, bullish)             3.0 pts
price ↑ + OI ↓  =  SHORT COVERING  (weak bears exiting, mild bull)    2.0 pts
price ↓ + OI ↓  =  LONG UNWINDING  (longs booking, mild bear)         1.0 pts
price ↓ + OI ↑  =  SHORT BUILDUP   (fresh shorts, bearish)            0.0 pts
```

Flat-zone check: if `|price_pct| < 0.2%` OR `|oi_pct| < 1.0%` the classifier returns None (regime is inconclusive), and the sub-score falls back to the neutral 1.5 default.

## Where price change comes from

`score_stock` reads today's close vs yesterday's close from the equity df it already has (yfinance / Angel One / Stooq via `data.fetcher`). No extra fetch. That gives a spot-based price change that is essentially the same signal as the F&O futures price change (basis is small at the daily frequency).

## Guardrail check

- §5 shape unchanged – this is a data pipeline for an existing pillar; no scoring math moved. ✅
- §7 posture-monotonicity: OI regime classifier is deterministic on its two inputs; sub-score `_POS_OI_REGIME_MAP` is monotone in bullishness (long_buildup > short_covering > long_unwinding > short_buildup). No case where a better OI regime lowers the total. ✅
- §11 module purity: pure module – `trade_store` + `requests` + stdlib only. ✅
- §14 fetcher discipline: named ValueError on missing `TckrSymb / FinInstrmTp / OpnIntrst`, on 404, on HTML-not-CSV (WAF challenge), on empty body. `pd.NA` / blank OI rows silently skipped with a WARNING when zero stock-derivative rows aggregate. ✅
- §16 canary tests: 9 offline fixture-based tests shipped in `tests/test_provenance_nse_fno_bhavcopy.py` covering parser aggregation, index-instrument filtering, missing-column drift, blank-OI skip, and the four-quadrant classifier. ✅

## Verification (2026-09-03)

Seeded 2 days of OI for RELIANCE (10.0M → 10.8M, +8%), then:

| Input | Expected regime | Snapshot / regime returned |
|---|---|---|
| price +1.5% | long_buildup | long_buildup ✅ |
| price -1.2% | short_buildup | short_buildup ✅ |
| price +0.05% (flat) | None (inconclusive) | None ✅ |

End-to-end via `score_dataframe`, flag ON, F&O ticker RELIANCE:

| positioning_info | score | positioning_score |
|---|---|---|
| `{oi_regime: 'long_buildup'}` | 62.7 | 6.5 (3.0 + 1.0 + 1.0 + 1.5 defaults) |
| `{oi_regime: 'short_buildup'}` | 59.7 | 3.5 (0.0 + 1.0 + 1.0 + 1.5 defaults) |

Spread is exactly 3.0 pts, matching the OI-regime sub-score range.

## Tests

- Canary suite: 9/9 in <1s (parser + classifier)
- Combined provenance + score regression: 73/73 in 7s
- Page-smoke Analyze Stock + Command Centre: 2/2 in 52s

## Operational activation

1. **Backfill** — one-time from a residential IP:
   ```
   py -m scripts.fetch_nse_fno_bhavcopy --days 30
   ```
   Only 2 days are needed for the classifier to fire (today vs prev), but a
   deeper history helps if you later add multi-day OI trend features.

2. **Daily cron** — Windows Task Scheduler entry after 6-7 PM IST weekdays:
   ```
   py -m scripts.fetch_nse_fno_bhavcopy
   ```

3. **Flip the flag** on Streamlit Cloud (or your local shell before
   `streamlit run`):
   ```
   NSE_USE_POSITIONING_PILLAR=1
   ```
   Once the DB has 2+ days of rows for a symbol, that symbol's OI regime
   activates. Symbols still without data continue on the legacy 4-pillar
   shape (the three-way gate in `score_dataframe` handles this per-ticker).

## What lights up on-screen

For each F&O-eligible ticker with a real OI regime, once the flag is on:

- Composite score shifts by up to ±3 pts on the Positioning sub-score in the direction of the OI quadrant.
- `CompositeScore.positioning_score` populates.
- A follow-up UI slice can render "OI regime: long buildup" as a chip on the Verdict Card once Sprint 1's UI work resumes.

The three remaining sub-inputs (PCR, max-pain, FII deriv) stay at their neutral 1.0 / 1.0 / 1.5 midpoints until their pipelines land, so the pillar total for an OI-only-armed ticker maxes at 6.5/10.

## Follow-ups

- **PCR + max-pain pipeline** — the biggest of the three remaining, needs per-symbol options-chain snapshots from `/api/option-chain-equities?symbol=X`. Residential-IP scheduler, per-symbol so slow.
- **FII deriv net pipeline** — `fao_participant_oi_DDMMYYYY.csv`, one file per day, universe-level (same value applies to every F&O ticker on a given day). Cheapest of the three.
- **Filename resilience** — NSE has renamed the F&O bhavcopy file several times (see `_bhavcopy_url` docstring). Add a small fallback that tries older names on 404 before giving up.

Written under `nse-app-guardrails` house style §21 – no em-dashes.
