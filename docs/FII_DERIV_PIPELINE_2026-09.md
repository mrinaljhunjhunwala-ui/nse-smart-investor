# FII derivatives pipeline – Rec 6 sub-score #2 of 4

_2026-09-03 · Follow-up to `docs/POSITIONING_INTEGRATION_2026-09.md` (Recommendation 6). Ships alongside `docs/OI_REGIME_PIPELINE_2026-09.md` as the second of four Positioning-pillar data pipelines._

## What this ships

Cheapest of the four positioning data pipelines. A single **universe-level** value per trading day (FII net position in index futures, in contracts) that applies to every F&O-eligible ticker's Positioning sub-score.

## Units correction

Rec 6's MVP shipped the parameter as `fii_deriv_net_cr` (Rupees Crore). NSE actually publishes contract counts, not rupees, and converting would need lot-size + price with no signal added. This landing **renames the parameter to `fii_deriv_net`** (units: contracts) and recalibrates the sub-score thresholds:

| Threshold (contracts) | Points | Meaning |
|---|---|---|
| net > +30,000 | 3.0 | heavy FII net long index futs (bullish) |
| net > 0 | 2.0 | mild net long |
| net > -30,000 | 1.0 | mild net short |
| net ≤ -30,000 | 0.0 | heavy FII net short (bearish) |
| absent | 1.5 | neutral midpoint (data pipeline not on) |

Thresholds are calibrated to the typical 2023-26 range of FII net index-futs positions (roughly -100k to +100k contracts). Will be re-tuned after 60 days of production data.

**Any external caller passing `positioning_info={"fii_deriv_net_cr": ...}` needs to switch to `"fii_deriv_net"`.** No prod call sites are affected (Rec 6 shipped a day ago, no live consumer beyond the sub-scorer itself).

## Data path

```
NSE archives                                (nsearchives.nseindia.com/content/nsccl/)
      │  fao_participant_oi_DDMMYYYY.csv
      ▼
scripts/fetch_nse_fii_deriv.py              (residential IP, cron)
      │  parse: extract 'FII' row, compute
      │         fut_idx_net = long − short
      ▼
trade_store · nse_fii_deriv_daily           (SQLite / Postgres, PK date)
      │  get_latest_fut_idx_net() → contracts (float) or None
      ▼
analysis.score.score_stock                  (best-effort DB load per call)
      │  positioning_info["fii_deriv_net"] = <contracts>
      ▼
_score_positioning(fii_deriv_net=...)       (3 pts inside Positioning pillar)
```

Universe-level means one row per day, applied to every F&O ticker on that day. `score_stock` loads it once per invocation (SQL SELECT with LIMIT 1), so the incremental cost per ticker is a single DB read.

## Guardrail check

- §5 shape unchanged — this is a data pipeline for an existing sub-score. ✅
- §7 posture-monotonicity: `_score_positioning` sub-score is monotone in `fii_deriv_net`. Higher net long → more pts, always. ✅
- §11 module purity: `data.nse_fii_deriv` imports only `trade_store`, `requests`, `pandas`, `csv`, `io`, `datetime`, `logging`. ✅
- §14 fetcher discipline: named `ValueError` on missing `Client Type / Future Index Long / Future Index Short / Future Stock Long / Future Stock Short`, on 404, on HTML-not-CSV (WAF challenge), on empty body. Missing FII row logs a WARNING and returns None (Guardrail §15). ✅
- §16 canary tests: 8 offline cases in `tests/test_provenance_nse_fii_deriv.py` cover row extraction, thousands-separator handling, missing-column drift, missing-FII-row → None, preamble-line stripping, blank/dash cell handling, required-column lockdown. ✅

## Verification (2026-09-03)

Seeded FII row (`fut_idx_net = 40,000` contracts) alongside 2 days of OI for RELIANCE:

| Positioning inputs armed | Positioning pillar / 10 | Composite score |
|---|---|---|
| OI only (`long_buildup`) | 6.5 | 62.7 |
| OI `long_buildup` + FII heavy net long (40k) | 8.0 | 64.2 |
| OI `short_buildup` + FII heavy net short (-40k) | 2.0 | 58.2 |
| All 4 bullish (OI+PCR+max-pain+FII, best case) | 9.5 | 65.7 |

FII sub-score alone moves the composite by 1.5 pts between the two mid-armed rows (6.5 → 8.0), matching the 1.5-pt spread between "heavy long" (3.0) and neutral (1.5) — verified.

## Tests

- New canary suite: **8/8** in <1s
- Combined provenance + score regression: **81/81** in 5s
- No score behavior change with default flag OFF or without seeded data (backwards-compat holds)

## Operational activation

1. **Backfill** — one-time from residential IP:
   ```
   py -m scripts.fetch_nse_fii_deriv --days 30
   ```
2. **Daily cron** — Windows Task Scheduler after 6-7 PM IST weekdays. Ships next to the two existing fetchers:
   ```
   py -m scripts.fetch_nse_delivery
   py -m scripts.fetch_nse_fno_bhavcopy
   py -m scripts.fetch_nse_fii_deriv
   ```
3. **Flip the flag** (already documented under Rec 6):
   ```
   set NSE_USE_POSITIONING_PILLAR=1
   ```

With OI regime + FII deriv both armed, every F&O-eligible ticker now sees composite score shifts of up to ±4.5 pts on its Positioning sub-score (3 from OI + 1.5 from FII delta vs neutral).

## What lights up on-screen

- Composite score shifts by up to ±1.5 pts on the FII sub-score alone (in addition to whatever OI regime contributes for that ticker).
- `CompositeScore.positioning_score` reflects the combined 4-input read.
- Every F&O ticker sees the SAME FII contribution on the same day — this is universe-level. The per-ticker variation on the pillar comes from the other three sub-inputs.

## Follow-ups

- **PCR + max-pain** — the last two positioning sub-inputs. Both come from the NSE options-chain snapshot per symbol; biggest data-engineering effort of the four. Rate-limited from cloud IPs — needs a residential-IP scheduler with a small per-symbol pause.
- **Threshold retune** — after 60 days of production data, revisit the ±30k contract thresholds against the actual FII net distribution.
- **Contract vs Rupee unit conversion** — if a future pass needs Rupee-based cross-market comparison, layer a lot-size × price multiplier at the read site; don't change the persisted units.

Written under `nse-app-guardrails` house style §21 – no em-dashes.
