# 5-Year Regime Study — What the Score Actually Measures

**Headline answer: the composite score is a trend-quality gauge, not a return
predictor.** Its correlation with *staying in an uptrend* over the next month is
**+0.41** — strong and consistent. Its correlation with *future returns* is
**+0.04** — economically negligible. The score does exactly what its
construction implies: it identifies stocks that are trending and likely to keep
trending, but trending ≠ outperforming.

> Produced by `research/regime_study.py` (read-only replay of the production
> scorer — no weights, thresholds, grades or actions altered).
> Regenerate: `py -m research.regime_study`

---

## Sample

| | |
|---|---|
| Observations | **40,667** (ticker × weekly sample date) |
| Tickers | 209 current liquid NSE names (survivorship disclosed) |
| Dates | 2022-03-29 → 2026-03-11 (~4 years of sample points, 5y data) |
| Regimes covered | bear 4,967 · bull 28,642 · sideways 7,058 obs (^NSEI SMA50/200 rule) |
| Sentiment | held neutral (90-pt price-derived score studied) |

The window includes the 2022 correction, the 2023–24 rally, and the 2025 chop —
the multi-regime coverage the 1-year efficacy study lacked.

---

## Q3 first — what is the score measuring? (the key table)

| Outcome | Spearman vs score |
|---|---|
| **Trend quality** (share of next 20 days above SMA-20) | **+0.411** |
| Future 20-day return | +0.042 |
| Future 60-day return | +0.034 |
| Future risk (20-day realized vol) | +0.047 |
| Risk-adjusted return (20d return / vol) | +0.035 |

The score is **10× more correlated with trend persistence than with returns**.
It is a well-functioning *trend-state descriptor*: high-score stocks really do
stay in uptrends. But uptrend persistence carried almost no return premium in
this period — extended stocks drifted, not surged. The score is *not* mismeasuring;
it is measuring something that doesn't pay (in this window, on a 20–60d horizon).

It is also essentially **risk-blind** (+0.05 vs future volatility): a high score
says nothing about how bumpy the ride will be.

## Q1 — predictive power by VIX regime

| VIX regime | n | fwd5 | fwd20 | fwd60 |
|---|---|---|---|---|
| complacency (<13) | 14,781 | +0.006 | **+0.069** | **+0.116** |
| normal (13–17) | 17,429 | −0.002 | +0.047 | +0.015 |
| elevated (17–22) | 7,244 | +0.010 | −0.010 | −0.056 |
| fear (22–28) | 1,213 | −0.092 | −0.063 | **−0.110** |

Clean monotone pattern: **the calmer the market, the better the score works;
in fear it inverts.** During VIX spikes, the market buys beaten-down
(low-score) names and sells extended (high-score) ones. The 1-year study's
negative result is now explained — it sampled mostly the regimes where the
score is weakest, plus elevated periods.

## Q2 — predictive power by market regime

| Market regime | n | fwd5 | fwd20 | fwd60 | avg fwd20 |
|---|---|---|---|---|---|
| bull | 28,642 | 0.000 | +0.056 | +0.082 | +1.12% |
| sideways | 7,058 | +0.022 | **+0.079** | +0.079 | +2.08% |
| bear | 4,967 | −0.043 | −0.010 | −0.056 | +2.14% |

Mild positive ranking power in bull and sideways markets; **none in bear
markets** (where, notably, average forward returns were high — the rebound —
but the score couldn't rank who would rebound).

## Q4 — which component works in each regime? (Spearman vs fwd20)

| Regime | technical | momentum | volume | pattern | composite |
|---|---|---|---|---|---|
| bull | +0.054 | **+0.068** | +0.013 | −0.020 | +0.056 |
| sideways | **+0.073** | +0.064 | +0.061 | −0.014 | +0.079 |
| bear | −0.012 | −0.003 | +0.005 | −0.016 | −0.010 |

- **Momentum** is the best component in bulls; **technical** in sideways.
- **Volume** only contributes in sideways markets.
- **Pattern (candlesticks) is negative in every regime.** Across 40,667
  observations the 10-point pattern component never helps — the clearest
  single finding for any future redesign discussion.

## Q5 — trend-following vs mean-reversion edge

| Regime | Trend edge (mom-20 rank) | Reversal edge (−5d-return rank) | Score |
|---|---|---|---|
| bear | **+0.099** | +0.065 | −0.010 |
| bull | +0.038 | −0.006 | +0.056 |
| sideways | +0.051 | **−0.072** | +0.079 |

- There **is** a modest trend-following edge in every regime — strongest, ironically,
  in bears (relative strength: what falls least keeps falling least).
- Mean reversion only "works" in bears; in sideways markets it's **anti-signal**
  (5-day losers keep losing: −0.072).
- The composite **beats naive momentum in bull and sideways** markets (+0.056/+0.079
  vs +0.038/+0.051) but is **beaten badly in bears** (−0.010 vs +0.099) — the
  composite's extra factors (especially pattern, and oversold-RSI credit) dilute
  pure relative strength exactly when relative strength matters most.

---

## Conclusions

1. **The score is a trend-quality instrument (+0.41) with marginal return
   predictivity (+0.04).** Present it as "trend health", not expected
   outperformance. The UI language should match this reality.
2. **It is regime-conditional in a coherent way:** works mildly in calm/bull/
   sideways conditions; inverts in fear/bear. The 2025-26 efficacy result was
   the regime, not randomness.
3. **Pattern (candles) is dead weight in every regime** — the strongest
   candidate for removal *if* a redesign is ever undertaken.
4. **A real but modest trend edge exists** (+0.04…+0.10 Spearman). The composite
   captures it in bull/sideways but destroys it in bears.
5. **Mean reversion is not a general edge** — it only appears in bear/fear
   regimes. The earlier 1-year "mean-reversion tilt" was a regime artifact.

## What this licenses (and doesn't)

Per the study's mandate, **no model changes were made**. The evidence now
supports a specific, narrow discussion — in order of confidence:
1. Relabel the score in the UI as trend quality (cosmetic, zero model risk).
2. Consider regime-gating *advice text* (e.g., during fear/bear regimes, note
   that score ranking is unreliable) — uses existing VIX plumbing.
3. Only then, and with a forward holdout: evaluate dropping the pattern
   component and the oversold-RSI bonus. Re-run both research harnesses as the
   regression gate.

*Generated 2026-06-10 · 40,667 observations · 209 tickers · weekly sampling ·
survivorship-biased universe (disclosed) · production scorer untouched.*
