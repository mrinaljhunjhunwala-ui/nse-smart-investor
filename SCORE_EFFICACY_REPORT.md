# Score Efficacy Report

**Question:** Does the production composite score have predictive power?
**Answer: No — not in the tested window.** The score ranks forward returns no
better than chance (slightly worse), its TP-before-SL odds *fall* as the score
rises, and it does not beat naive 20-day momentum. Important context: *nothing*
beat chance in this window — the naive baselines were also ≈ zero — so this is
evidence of "no edge demonstrated", not "inverted edge proven".

> Produced by `research/score_efficacy.py` (read-only replay of
> `analysis/score.py` — production weights/thresholds untouched).
> Regenerate anytime: `py -m research.score_efficacy`

---

## 1. Methodology

| Design choice | Value |
|---|---|
| Universe | 209 usable of 217 current liquid NSE names (Nifty-500 set) |
| Sample dates | Every 5th trading day (weekly) — avoids overlapping-window bias |
| Window | 2025-03-26 → 2026-03-10 sample dates (60-day forward buffer beyond) |
| Observations | **10,032** (ticker × date) |
| Primary metric | **90-pt price-derived score** (technical+momentum+volume+pattern); sentiment held neutral and studied via regime *breakdowns* instead |
| Forward outcomes | 5/20/60-day returns; TP-first vs SL-first path walk on daily High/Low over 60 bars |
| Ambiguity rule | Bar touches both TP and SL → counted SL-first (conservative). Occurred **9 / 10,032** times — negligible |
| Baselines | 20-day momentum rank, RSI rank, SMA200-distance rank on the same observations |

**Disclosed limitations**
1. **Survivorship bias** — universe is *current* constituents; conclusions are about ranking power *within surviving* liquid names.
2. **One regime** — the window is ~12 months of mostly low-VIX, sideways-to-mildly-positive market (avg 20-day fwd ≈ +0.2%). A 5-year study is needed before any re-weighting decision.
3. **TP/SL confound** — targets are conviction-scaled (score ≥72 → 3R, <48 → 1.5R), so high-score TP-first rates are *mechanically* lower (farther targets). Compare deciles on forward returns, not TP rates.
4. Same-date observations share market moves (clustered errors); treat Spearman magnitudes as descriptive, not as t-stats.
5. No transaction costs included anywhere.

---

## 2. Decile results (score90; 1 = lowest, 10 = highest)

| Decile | n | Avg score | Fwd 5d % | Fwd 20d % | Fwd 60d % | Win20 % | TP-first % | SL-first % |
|---|---|---|---|---|---|---|---|---|
| 1 | 1004 | 15.5 | **+0.43** | +0.55 | +0.98 | 52.5 | 48.4 | 49.1 |
| 2 | 1003 | 20.3 | +0.14 | +0.63 | +0.56 | 52.8 | 46.4 | 51.5 |
| 3 | 1003 | 24.4 | +0.22 | −0.02 | +1.36 | 48.4 | 47.6 | 50.3 |
| 4 | 1003 | 28.4 | +0.22 | −0.01 | +0.96 | 47.5 | 43.2 | 54.7 |
| 5 | 1003 | 32.5 | +0.02 | +0.01 | +0.97 | 48.6 | 43.4 | 53.0 |
| 6 | 1003 | 36.9 | −0.06 | +0.23 | +1.50 | 50.1 | 42.3 | 52.0 |
| 7 | 1003 | 42.0 | 0.00 | +0.33 | +0.77 | 50.1 | 31.9 | 59.0 |
| 8 | 1003 | 47.4 | +0.12 | +0.20 | +1.10 | 49.8 | 30.9 | 57.3 |
| 9 | 1003 | 53.6 | −0.07 | +0.36 | +1.27 | 48.2 | 24.4 | 61.0 |
| 10 | 1004 | 62.2 | **−0.17** | −0.05 | +0.15 | 47.7 | **21.9** | **62.0** |

**Monotonicity:** none in the desired direction. Spearman(score90, fwd20) =
**−0.014**, fwd60 = **−0.000**, fwd5 = **−0.031**. Decile-10-minus-decile-1
spread: **−0.60%** (20d), **−0.83%** (60d). At the 5-day horizon there is a mild
*mean-reversion* tilt — the lowest-score (most beaten-down) decile did best.

## 3. Action bands (the labels users see)

| Action | n | Fwd 20d % | Fwd 60d % | TP-first % | SL-first % |
|---|---|---|---|---|---|
| STRONG BUY | 27 | **−2.07** | −0.73 | 11.1 | **74.1** |
| BUY | 1037 | +0.03 | +0.17 | 22.2 | 61.7 |
| WATCHLIST | 2126 | +0.36 | +1.23 | 28.4 | 58.7 |
| HOLD | 2504 | +0.14 | +1.14 | 39.1 | 54.8 |
| CAUTION | 3642 | +0.14 | +0.86 | 45.1 | 52.8 |
| EXIT | 696 | **+0.94** | +1.27 | 51.3 | 45.7 |

The ordering is inverted: EXIT-labelled stocks outperformed STRONG BUY ones.
Note (a) STRONG BUY n = 27 — too small to be conclusive on its own; (b) the
TP/SL columns carry the conviction-target confound (§1.3); but the forward-return
inversion is target-independent.

## 4. Factor attribution (Spearman vs forward returns)

| Component | fwd 5d | fwd 20d | fwd 60d |
|---|---|---|---|
| technical (40 pts) | −0.030 | −0.017 | +0.012 |
| momentum (25 pts) | −0.012 | −0.009 | −0.013 |
| volume (15 pts) | −0.032 | +0.004 | +0.005 |
| pattern (10 pts) | −0.023 | −0.004 | +0.011 |
| **composite (90)** | **−0.031** | **−0.014** | **−0.000** |

No component carries positive signal in this window. None is dramatically
worse than the others either — the composite isn't being dragged down by one
bad factor; the whole trend-following construct had no edge in this market.

## 5. Baseline comparison — the brutal test

| Ranking | Spearman fwd20 | D10−D1 fwd20 | D10−D1 fwd60 |
|---|---|---|---|
| Composite score90 | −0.014 | −0.60% | −0.83% |
| Naive 20-day momentum | +0.016 | +0.90% | +0.82% |
| RSI rank | +0.009 | +0.07% | 0.00% |
| SMA200-distance rank | −0.035 | −2.03% | −3.88% |

The composite **does not beat naive momentum** — and naive momentum itself was
≈ zero. The 5-factor construction added complexity without adding ranking power
in this window. (Distance-above-SMA200 was the *worst* ranker — extended stocks
mean-reverted.)

## 6. Regime breakdown (historical India-VIX labels)

| Regime | n | Spearman fwd20 | Avg fwd20 % |
|---|---|---|---|
| complacency (VIX<13) | 6270 | −0.008 | −0.46 |
| normal (13–17) | 2281 | +0.003 | −0.61 |
| elevated (17–22) | 1290 | **−0.135** | +4.91 |
| fear (22–28) | 191 | +0.013 | +1.01 |

In elevated-VIX periods the score was *meaningfully inverted* (−0.135): the
market rewarded buying low-score (oversold) names during volatility spikes —
classic mean reversion. 76% of the sample sat in complacency/normal regimes,
underlining the single-regime limitation.

## 7. Sector breakdown (selected; full CSV in `research/output/`)

Mostly negative or ≈ zero: Metal −0.218, Energy −0.117, Pharma −0.107,
Chemicals −0.106, Auto −0.097. Mildly positive: Cement +0.075, Finance +0.047,
IT +0.024. No sector shows the score working strongly.

---

## 8. Conclusions

1. **The composite score has no demonstrated predictive power for forward
   returns** in the tested year (Spearman ≈ −0.01 to −0.03 at all horizons).
2. **It is currently a *descriptive* dashboard, not an alpha signal.** It
   accurately summarises trend state — but trend state did not predict returns
   in this window.
3. **The conviction-scaled targets fail empirically as configured:** top-decile
   setups hit TP first only 21.9% vs SL first 62.0%. Even at 3R payoff:
   0.219×3R − 0.620×1R ≈ **+0.04R before costs** → negative after costs.
4. **The strongest hypothesis the data offers is short-horizon mean reversion**
   (low deciles best at 5 days; score inverted in elevated VIX) — a *test
   candidate*, not a conclusion.
5. **The window itself was edge-less for momentum-style signals** — naive
   baselines were also ≈ zero — so the score isn't "proven broken"; it's
   "unproven, with mild evidence of inversion, in one regime".

## 9. Recommendations (evidence first — still no model change)

1. **Do not re-weight or re-threshold based on this single year.** The honest
   next step is a **5-year replay** (Angel One provides 5y daily) covering at
   least one full bull/bear cycle. Only re-weight on multi-regime evidence.
2. **Soften UI confidence language** for STRONG BUY/BUY until validated —
   present the score as "trend quality", not an expectation of outperformance.
3. **Re-examine the target/stop geometry** regardless of signal work: 3R
   targets within a 60-day horizon hit ~22% of the time. Either extend the
   horizon, scale targets down, or trail instead of fixed-TP.
4. **Test (don't ship) a mean-reversion variant** — oversold + elevated-VIX
   conditions showed the only consistent tilt in the data.
5. **Re-run this framework after any change** — it's now a 2-minute,
   one-command regression harness for signal quality.

*Generated 2026-06-10 · 10,032 observations · 209 tickers · weekly sampling ·
sentiment neutralised · survivorship-biased universe (disclosed).*
