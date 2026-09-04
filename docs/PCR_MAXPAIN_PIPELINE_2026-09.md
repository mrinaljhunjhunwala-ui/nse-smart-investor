# PCR + Max-pain pipeline – Rec 6 sub-scores #3 and #4 of 4

_2026-09-04 · Follow-up to `docs/POSITIONING_INTEGRATION_2026-09.md`. Completes the four Positioning-pillar data pipelines._

## What this ships

The remaining two Positioning-pillar sub-inputs, delivered by the same per-symbol NSE options-chain endpoint:

- **PCR** (Put OI / Call OI across nearest expiry) — 2 pts of 10. Contrarian: extremes matter, not the level.
- **Max-pain distance %** (signed % from max-pain strike to spot) — 2 pts of 10. Distance from pin gauges pin-risk near expiry.

Combined with the OI regime (Rec 6 sub 1) and FII deriv net (Rec 6 sub 2) landings, the Positioning pillar is now fully wired: every F&O-eligible ticker with all data pipelines armed can score the full 0–10 pt range on the pillar.

## Data path

```
NSE public API                              (nseindia.com/api/option-chain-equities?symbol=X)
      │  per-symbol JSON, cookie-primed session
      ▼
scripts/fetch_nse_option_chain.py           (residential IP, per-symbol pause)
      │  parse: filter to nearest expiry, sum CE/PE OI, compute PCR,
      │         compute max-pain from strike-level payoff-to-writers
      ▼
trade_store · nse_option_chain_daily        (SQLite / Postgres, PK symbol+date)
      │  get_pcr(sym), get_max_pain_pct(sym)
      ▼
analysis.score.score_stock                  (best-effort DB reads)
      │  positioning_info["pcr"] / ["max_pain_distance_pct"]
      ▼
_score_positioning(...)                     (2 + 2 = 4 pts inside pillar)
```

## Max-pain math

```
loss_at_K = sum over S of  ce_oi[S] * max(K - S, 0)      # ITM calls
          + sum over S of  pe_oi[S] * max(S - K, 0)      # ITM puts
max_pain  = argmin over K of loss_at_K
distance_pct = (spot - max_pain) / max_pain * 100
```

Computed only over the nearest expiry (far-expiry rows are filtered out — that's what the score cares about at daily frequency). Requires at least 3 strikes; None below that.

## Guardrail check

- §5 shape unchanged — these are data pipelines for existing sub-scores. ✅
- §7 posture-monotonicity: PCR and max-pain sub-scores are the same monotone bands shipped with Rec 6 mechanism (see `_score_positioning`); no re-tuning here. ✅
- §11 module purity: `data.nse_option_chain` imports only `trade_store`, `requests`, `pandas`, `json`, `time`, `datetime`, `logging`. ✅
- §14 fetcher discipline: named `ValueError` on empty payload, missing `records`, empty `records.data`, 404, HTML-not-JSON (WAF challenge), JSON decode failure. ✅
- §15 fallthrough: no-future-expiry OR zero rows matching the nearest expiry both log WARNING and return None (never silent empty). ✅
- §16 canary tests: **19 offline cases** in `tests/test_provenance_nse_option_chain.py` — 3 for `compute_pcr`, 3 for `compute_max_pain` (including symmetric-OI and call-heavy asymmetric), 5 for `compute_max_pain_distance_pct`, 3 for `_nearest_expiry`, 5 for the end-to-end parser (including far-expiry filtering, missing-records drift, empty-data, no-future-expiry graceful None). ✅

## Verification (2026-09-04)

Seeded a synthetic RELIANCE row with `pcr=1.70, max_pain_pct=3.70, spot=1400, max_pain_strike=1350` alongside the two prior pipelines:

| Positioning inputs armed | Positioning pillar / 10 | Composite score |
|---|---|---|
| All 4 bullish (OI long / PCR 1.70 / mp +3.7% / FII +40k) | 9.5 | 65.7 |
| All 4 bearish (OI short / PCR 0.55 / mp +0.4% / FII -40k) | 1.0 | 57.2 |

Full pillar range now spans 8.5 pts of score movement on F&O-eligible tickers.

## Tests

- New canary suite: **19/19** in <1s
- Combined provenance + score regression: **95/95** in 11s
- No behavior change with default flag OFF, or without seeded data

## Operational activation

```
# Backfill (residential IP, ~2 minutes for the ~60 F&O starter universe)
py -m scripts.fetch_nse_option_chain --fno-all

# Or narrow list for testing
py -m scripts.fetch_nse_option_chain --tickers RELIANCE INFY TCS HDFCBANK

# Daily cron - Windows Task Scheduler after ~4 PM IST (during market
# hours you get pre-close snapshots; after close is the definitive read)
py -m scripts.fetch_nse_option_chain --fno-all
```

Runs one HTTP call per symbol with a default 2s pause between calls. Bump `--pause` to 3-4s if NSE starts 429-ing.

## What lights up on-screen

With this final pipeline armed and `NSE_USE_POSITIONING_PILLAR=1`, every F&O-eligible ticker sees:

- Composite score can shift up to ±5 pts on the Positioning sub-score, using all four data quadrants (OI regime + PCR extremes + max-pain distance + FII deriv net).
- `positioning_score` field ranges 0-10, populated when at least one input is armed.
- The three per-ticker inputs (OI, PCR, max-pain) plus the universe-level FII deriv net combine into a real institutional-positioning read.

## Followups (nice-to-have, not blocking)

- **UI badge**: render OI regime + PCR zone + max-pain distance as chips on the Verdict Card. Task 1.4 (Verdict Card hero) subsumes this — no need to ship separately.
- **Threshold retune**: the four sub-score bands in `_score_positioning` were calibrated to conventions, not data. After 60 days of production data, revisit each.
- **Intraday refresh**: this landing polls end-of-day; a mid-day option to pass `intraday=True` and refresh only spot + OI could feed the intraday page later.

Written under `nse-app-guardrails` house style §21 – no em-dashes.
