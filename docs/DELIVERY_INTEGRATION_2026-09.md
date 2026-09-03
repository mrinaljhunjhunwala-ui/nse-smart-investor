# Recommendation 4 – NSE delivery % inside Volume pillar

_2026-09-03 · Ships Task 3.4 from `tasks/plan.md` and Recommendation 4 from `docs/COMPOSITE_SCORE_SHAPE_REVIEW.md`._

## Shape

Volume pillar total unchanged at **15 pts**. Guardrail §5 shape (4 pillars, 40+25+15+10, cap 90) unchanged.

Internal split, gated on delivery-snapshot availability:

| Mode | When | Split |
|---|---|---|
| **Legacy (backwards-compat)** | `delivery_info=None` – DB empty, cron hasn't run, DB unreachable | `vol_ratio:10 + obv:5` |
| **With delivery** | `delivery_info` present – returned by `data.nse_delivery.get_snapshot(symbol)` | `vol_ratio:8 + obv:3 + delivery:4` |

The vol_ratio bucketing shape and OBV logic are preserved; when delivery is available the two are rescaled by `0.8` and `0.6` respectively to make room for the new 4-pt sub-score.

## Delivery sub-score (0-4 pts)

Additive: `abs_level (0-2.5) + direction (0-1.5)`, capped at 4.

**Absolute level** – what fraction of today's traded qty actually went to demat:

| Today's DELIV_PER | Points |
|---|---|
| ≥ 60% | 2.5 (heavy institutional footprint) |
| ≥ 45% | 2.0 |
| ≥ 30% | 1.0 |
| ≥ 20% | 0.5 |
| < 20% | 0.0 (pure intraday churn) |

**Direction vs the stock's own 60-day mean** – separates accumulation from distribution:

| z-score | Points |
|---|---|
| z > +1.0 | 1.5 (sharply above own mean) |
| z > +0.25 | 1.0 |
| −0.25 ≤ z ≤ +0.25 | 0.75 |
| z > −1.0 | 0.25 |
| z ≤ −1.0 | 0.0 (sharp under-delivery) |

**Divergence flag** – set when `up_day AND vol_ratio > 1.5 AND z < −1.0`. Surfaced in the narrative as *"the volume surge is largely intraday, not institutional accumulation"*. Doesn't further penalise the score (already 0-1 pts from the direction bucket) – acts as a visible caution.

## New provider – `data/nse_delivery.py`

Follows the `analysis/fii_dii.py` pattern exactly:

- Fetches `sec_bhavdata_full_DDMMYYYY.csv` from `nsearchives.nseindia.com`. One call per trading day, ~2500 rows covering every equity.
- Parses with Guardrail §14 discipline – required columns (`SYMBOL, SERIES, DATE1, CLOSE_PRICE, TTL_TRD_QNTY, DELIV_QTY, DELIV_PER`) are asserted at the top of the parse; a missing one raises `ValueError("NSE bhavcopy schema drift: ...")` so operators notice.
- DATE1 format is checked explicitly – `DD-MMM-YYYY` drift also raises named ValueError.
- Guardrail §15 fallthrough: parser produces 0 rows despite header shape being fine → logged WARNING with sample column names, not silent-empty.
- Persists to `nse_delivery_daily` in the shared `trade_store` (SQLite locally, Postgres in prod). PK is `(symbol, date)` – re-running the fetch upserts, never duplicates.
- Read API: `load_symbol_history(symbol, days=60)` returns a per-symbol DataFrame; `get_snapshot(symbol)` returns `{today, mean, std, n, zscore}` or `None` when the row count is under 5.

Purity preserved: no `import streamlit`. Only `trade_store` and `requests` (Guardrail §11 holds).

## Canary tests – `tests/test_provenance_nse_delivery.py`

Ships six offline fixture-based tests per Guardrail §16:

- Happy-path row (INFY, EQ) parses to the expected float shape
- Blank / `-` DELIV_PER rows are skipped
- Series filter defaults to `{EQ, BE}`
- Dropping `CLOSE_PRICE` from the header raises `ValueError("schema drift...CLOSE_PRICE")`
- Changing DATE1 format to ISO raises `ValueError("schema drift...DATE1")`
- Empty body raises `ValueError("empty response body")`
- The `_REQUIRED_COLS` contract is asserted as a lockdown against silent removal

All six pass locally. A live-network variant is intentionally not shipped – the daily provenance sweep already handles that pattern separately.

## Guardrail check

- §5 shape unchanged: 4 pillars, 40+25+15+10, cap 90. ✅
- §7 posture-monotonicity: `_score_volume` returns identical 15-pt max in both modes; delivery sub-score is monotone in both `today %` and `z`; better delivery quadrants score no lower than worse ones. Score never moves in a direction that opposes a posture flip. ✅
- §11 module purity: `analysis/score.py` still Streamlit-free; `data/nse_delivery.py` imports only `trade_store`, `requests`, `pandas`, `csv`, `io`, `datetime`, `logging`. ✅
- §14 fetcher discipline: named ValueErrors on schema drift, DATE1 format drift, and empty body. Silent-empty parse logged as WARNING. HTML-instead-of-CSV (WAF challenge) also raises a named ValueError. ✅
- §16 canary tests: shipped alongside the provider, six offline cases. ✅

## Bounds check

Synthetic OHLCV, price 102, vol_ratio 2.0, up-day:

| Scenario | Score / 15 | Breakdown |
|---|---|---|
| Legacy (no delivery) | 13.00 | vol 8.0 + obv 5.0 |
| With-delivery, high accumulation (today 72, z +2.1) | 13.40 | vol 6.4 + obv 3.0 + deliv 4.0 |
| With-delivery, divergence (today 22, z −2.5) + up-day + vol surge | 9.90 | vol 6.4 + obv 3.0 + deliv 0.5, divergence flag True |
| With-delivery, top-of-scale (today 90, z +12) | 13.40 | vol 6.4 + obv 3.0 + deliv 4.0 |

Live call: HDFCBANK score=34.2 unchanged from the pre-Rec-4 baseline (local DB is empty → legacy mode kicks in → volume sub-score identical to before).

## Tests

- Canary suite: 6/6 pass in <1s
- Full score regression (`test_smoke_score_indicators`, `test_audit_fixes`, `test_regime`, `test_valuation_golden_snapshot`): 64/64 in 14s
- Page-smoke on Analyze Stock + Command Centre + TQS Scanner: 3/3 in 153s

## User-visible changes

Nothing changes on-screen until the daily bhavcopy cron runs against the production DB. Once it has 5+ days of rows for a symbol:

- **Composite score** shifts by up to ±3 pts on the Volume sub-score, in the direction of the delivery quadrant.
- **Analyze Stock narrative** picks up one of four new sentences:
  - Divergence: *"Delivery % is only 22% today vs the 60-day mean of 45% (−2.5σ) — the volume surge is largely intraday, not institutional accumulation…"*
  - Sharp accumulation: *"Delivery % is 72% today, sharply above the 60-day mean of 55% (+2.1σ) — institutional accumulation footprint."*
  - Above-normal: *"Delivery % is 52% today vs the 60-day mean of 45% — above-normal institutional participation."*
  - Weak / intraday-dominated: *"Delivery % is 18% today (−0.8σ below the 60-day mean) — dominated by intraday traders, thin real conviction."*
- **Screener / Watchlist / Top Picks** – the Verdict Card and any UI that surfaces the volume sub-score reflect the new split automatically.

## Follow-ups (not in this landing)

1. **Bhavcopy cron** – a small `scripts/fetch_nse_delivery.py` runner that calls `fetch_and_persist_today()` on a schedule, plus a backfill script `scripts/backfill_nse_delivery.py --days 90` for one-time historical population. Guardrail-safe pattern; queued as its own task.
2. **UI column** – add a `Delivery %` column to Top Picks, Watchlist, and Smart Screener tables sourced from the new snapshot. Display-only, no scoring impact. Queued as UI Sprint task.
3. **Rescale review** – after ~60 days of production data, revisit the `abs_level` thresholds (30 / 45 / 60) against actual NSE distributions. Current values are convention-based, not data-tuned.
4. **F&O ban / ASM tags** – same provider (bhavcopy) publishes SERIES that flags T2T / ASM / GSM. Could ride the same fetcher for tradability gates. Separate task.

Written under `nse-app-guardrails` house style §21 – no em-dashes.
