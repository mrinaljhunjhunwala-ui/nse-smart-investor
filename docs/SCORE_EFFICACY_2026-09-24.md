# Score Efficacy — 2026-09-24 re-run

**Question:** after the audit fixes (#162–#166), does the production composite
score rank NSE stocks by forward return?

**Answer: weakly yes. It depends on the regime, and it's too small to act on
alone.**
- **Headline:** across 5 years (484 stocks, 87,594 weekly samples, Jul 2022 → Jul 2026),
  higher-scored stocks slightly outperformed lower-scored ones on the same date. The
  per-date rank correlation (IC) was **+0.020 at 20 days (t ≈ 2.6)** and **+0.029 at
  60 days (t ≈ 4.0)**.
- **Deciles:** the top decile beat the bottom by **+2.2 pts over 20 days** and **+5.5
  pts over 60 days**, and the rise is broadly monotonic.
- **By regime:** the edge is concentrated in trending-up markets. In bear and fear
  regimes it inverts.

This supersedes the conclusion of `SCORE_EFFICACY_REPORT.md` that the score has "no
predictive power, labels inverted". The reasons are in §3.

> Produced by `research/score_efficacy.py` (read-only replay of `analysis/score.py`).
> Raw outputs: `research/output/run_{A_rs_off,B_rs_regime,C_nors}/` (not committed).
> Reproduce: `py -m research.score_efficacy --period 5y [--regime-weights | --no-rs]`.

---

## 1. What changed in the study

| Input | Old study | This run |
|---|---|---|
| Relative strength vs Nifty (10 of 25 momentum pts) | **never computed**, so it scored the RS-less fallback | replayed causally (rolling 252-bar percentile, same call as `score_stock`) |
| VIX part of Sentiment | held at "normal" | replayed from `^INDIAVIX` per date (`sent_vix_hist`) |
| Market regime | none | production `analysis.regime.classify_history` (no breadth, same inputs as `snapshot_live`) |
| Window | ~12 months | 5 years (includes the 2025 drawdown and the 2026 risk-off spell) |
| Headline metric | pooled Spearman | **per-date cross-sectional IC** with t-stat (pooled kept for comparison) |

These inputs have no point-in-time history, so they stay neutral: sector rank, FII/DII
flows, delivery %, positioning.

## 2. Results (run A: live scorer, bear option off)

| Decile | Avg score | Fwd 20d % | Fwd 60d % | Win 20d % |
|---|---|---|---|---|
| 1 | 17.2 | 1.24 | 3.77 | 51.6 |
| 5 | 35.8 | 2.02 | 6.03 | 55.4 |
| 9 | 58.8 | 2.80 | 7.98 | 57.9 |
| 10 | 65.8 | 3.41 | 9.23 | 58.1 |

**Labels by forward 20-day return** (they now run the right way):

| Label | 20d return |
|---|---|
| BUY | +3.2% |
| WATCHLIST | +2.2% |
| HOLD | +2.0% |
| CAUTION | +1.6% |
| EXIT | +1.2% |

STRONG BUY is +3.1%, but on n = 368 only.

**Per-date IC by component (20d / 60d):**

| Component | IC 20d | IC 60d |
|---|---|---|
| RS vs Nifty | **+0.027** (t 3.0) | **+0.037** (t 4.5) |
| Momentum | +0.024 | +0.031 |
| Technical | +0.019 | +0.028 |
| Volume | +0.003 | +0.005 |

- Volume and candlestick patterns carry no signal.
- The composite beats all three naive baselines on decile spread. It is roughly tied
  with SMA-200 distance on IC.

**Year by year, IC at 20 days:**

| Year | IC 20d |
|---|---|
| 2022 | +0.052 |
| 2023 | +0.047 |
| 2024 | +0.018 |
| 2025 | **−0.015** |
| 2026 | +0.015 |

The edge is not stable.

**By live regime, IC at 20 days:**

| Regime | IC 20d | t |
|---|---|---|
| trend_up | **+0.047** | 5.6 |
| range | +0.002 | — |
| trend_down | −0.020 | — |
| risk_off | **−0.122** | −4.7 (7 dates) |

## 3. Why the old report said "inverted"

1. **Pooling across dates.** Pooled correlations mix in market-wide moves between
   dates, and those swamp the ranking signal.
   - Over the last 12 months (the old report's window), the pooled correlation is
     **−0.035**, but the per-date IC is **+0.024**.
   - The score was ranking correctly within each date. The market as a whole moved
     against the pooled comparison.
2. **Missing RS.** Run C replays the scorer without RS:

   | | IC 20d | Top–bottom decile gap | EXIT 20d return |
   |---|---|---|---|
   | Without RS (run C) | +0.017 | +1.9 pts | +1.9% |
   | With RS (run A) | +0.020 | +2.2 pts | +1.2% |

   RS helps modestly, and it is what puts EXIT below BUY.

## 4. Decision 1: bear-regime momentum ON (run B vs A)

In trend_down and risk_off regimes, run B swaps the absolute-returns half of Momentum
for a 5-day reversal percentile. RS stays, and the 40+25+15+10 shape is unchanged.

| Slice (20d) | Off | On |
|---|---|---|
| All, per-date IC | +0.020 | **+0.022** |
| All, pooled | +0.042 | **+0.057** |
| Bear, 2022–23 half | −0.126 | **−0.101** |
| Bear, 2024–26 half | −0.089 | **−0.036** |
| trend_up / range | — | identical |

- **Why ship it:** it improves bear ranking in both halves, which meets the acceptance
  rule in `REGIME_WEIGHTS_VALIDATION.md`, and it leaves every other regime untouched.
- **Default:** now ON (`NSE_USE_REGIME_WEIGHTS=0` disables it).
- **Caveat:** bear rankings are *less wrong*, not good.
- **risk_off (7 dates only):** it helps slightly at 20 days and hurts slightly at 60
  days. That is too few dates to tune further.

## 5. Decision 2: VIX sub-component neutralised

- **Why it can't rank anything:** VIX is the same for every stock on a given date. Its
  per-date IC is undefined.
- **Why it hurt:** pooled over time it ran **against** forward returns (−0.12 at 20
  days). Fear days had the best forward returns (+11.6% at 20 days) but gave every stock
  the fewest points. Adding it lowered the pooled correlation (0.042 → 0.033).
- **What changed:** the VIX points are now held at the "normal" value in both sentiment
  modes, so the pillar max and calm-market scores are unchanged.
- **What stays:** VIX still sets stop width and horizon, and is shown as context.
- **Why not invert it:** that would fit one fear episode of 1,865 observations.

## 6. Caveats

- **Survivorship:** the universe is today's Nifty-500, which likely flatters
  momentum-type scores.
- **Costs:** the 0.30% round trip is modelled in the accuracy table. A 2-point decile
  spread survives costs; single-name predictions do not.
- **Replay gaps:** sector rank, flows, delivery % and positioning are neutral in the
  replay, so the live score is not fully validated.
- **What the score is:** an IC of 0.02 is weak. It describes trend quality, with a small
  and regime-dependent tendency to rank forward returns. It is not a forecast.
