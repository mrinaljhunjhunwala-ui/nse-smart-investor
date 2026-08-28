# Score Efficacy Report

**Question:** Does the production composite score have predictive power?
**Answer: No — not in the tested window, and marginally worse than three
naive baselines tested alongside it.** The score ranks forward returns
slightly worse than chance at every horizon, and the discrete action labels
users actually see are inverted — EXIT-labelled stocks outperformed BUY and
STRONG BUY. Important context: *every* ranking tested here — including plain
20-day momentum, RSI, and distance-from-SMA200 — was also negative in this
window, and the composite score was the **least negative of the four**. This
reads as a regime effect common to the whole trend-following factor family,
not a defect unique to this construction — see the companion 5-year regime
study (`REGIME_STUDY_REPORT.md`) for the full multi-cycle picture.

> Produced by `research/score_efficacy.py` (read-only replay of
> `analysis/score.py` — production weights/thresholds untouched).
> Regenerate anytime via the "Research Refresh" GitHub Actions workflow
> (`workflow_dispatch`), or locally: `py -m research.score_efficacy`

**This supersedes the 2026-06-10 report of the same name.** That report's
10,032 observations were a valid run *at the time* — but `analysis/score.py`
changed materially five times since (the pattern-removal migration landed
just hours later, on 2026-06-11, followed by four more updates through
2026-07-05), and the report was never regenerated against any of those
changes. Worse, once the pattern-removal migration removed
`CompositeScore.pattern_score` entirely, `research/score_efficacy.py`'s own
walk-forward loop started raising `AttributeError` on every single sample —
so from 2026-06-11 until `FIX EFF1` corrected it on 2026-07-07, the script
couldn't even be re-run to check whether the June report still held. This is
the first run since that fix, and the first that reflects the current
scoring logic at all — treat every number below as current, and the June
report as describing a superseded version of the model, not a data point to
average against these figures.

---

## 1. Methodology

| Design choice | Value |
|---|---|
| Universe | 478 usable of 504 current liquid NSE names (Nifty-500 set) |
| Sample dates | Every 5th trading day (weekly) — avoids overlapping-window bias |
| Window | 2025-05-06 → 2026-04-20 sample dates (60-day forward buffer beyond) |
| Observations | **22,584** (ticker × date) |
| Primary metric | **90-pt price-derived score** (technical+momentum+volume; pattern excluded from production, see `PATTERN_REMOVAL_MIGRATION.md`); sentiment held neutral and studied via regime *breakdowns* instead |
| Forward outcomes | 5/20/60-day returns; TP-first vs SL-first path walk on daily High/Low over 60 bars |
| Baselines | 20-day momentum rank, RSI rank, SMA200-distance rank on the same observations |

**Disclosed limitations**
1. **Survivorship bias** — universe is *current* constituents; conclusions are about ranking power *within surviving* liquid names.
2. **One regime** — the window is ~12 months. The companion 5-year regime study (86,589 observations, 2022-05 → 2026-04) is the multi-cycle check; read this report alongside it, not instead of it.
3. **TP/SL confound** — targets are conviction-scaled (higher score → farther target), so high-score TP-first rates are *mechanically* lower. Compare deciles on forward returns, not TP rates, for signal-quality conclusions.
4. Same-date observations share market moves (clustered errors); treat Spearman magnitudes as descriptive, not as t-stats.
5. No transaction costs included anywhere.

---

## 2. Decile results (score90; 1 = lowest, 10 = highest)

| Decile | n | Avg score | Fwd 5d % | Fwd 20d % | Fwd 60d % | Win20 % | TP-first % | SL-first % |
|---|---|---|---|---|---|---|---|---|
| 1 | 2259 | 14.7 | +0.20 | **+1.89** | **+2.49** | 54.9 | 44.5 | 54.4 |
| 2 | 2258 | 18.9 | +0.29 | +1.82 | +2.49 | 53.6 | 44.7 | 54.2 |
| 3 | 2258 | 22.5 | +0.40 | +1.48 | +2.34 | 52.8 | 46.3 | 52.9 |
| 4 | 2259 | 26.3 | +0.41 | +0.90 | +1.15 | 49.9 | 45.2 | 52.9 |
| 5 | 2258 | 30.3 | +0.19 | +0.12 | +0.57 | 47.4 | 42.5 | 54.8 |
| 6 | 2258 | 34.9 | +0.22 | +0.07 | +0.55 | 47.0 | 41.5 | 54.3 |
| 7 | 2259 | 40.0 | +0.45 | +0.66 | +0.29 | 50.8 | 39.5 | 53.7 |
| 8 | 2258 | 46.0 | +0.30 | +0.45 | +0.96 | 47.5 | 33.8 | 58.2 |
| 9 | 2258 | 52.8 | +0.06 | +0.23 | +0.53 | 46.9 | 27.5 | 60.5 |
| 10 | 2259 | 61.5 | +0.14 | **+0.04** | **+0.71** | 47.1 | **23.3** | **60.2** |

**Monotonicity:** inverted. Spearman(score90, fwd20) = **−0.061**, fwd60 =
**−0.046**, fwd5 = **−0.017**. Decile-10-minus-decile-1 spread: **−1.85%**
(20d), **−1.78%** (60d). The lowest-score decile modestly *outperformed* the
highest-score decile at every horizon tested.

## 3. Action bands (the labels users see)

| Action | n | Fwd 20d % | Fwd 60d % | TP-first % | SL-first % |
|---|---|---|---|---|---|
| STRONG BUY | 27 | **+3.78** | +0.81 | 18.5 | 55.6 |
| BUY | 2190 | −0.01 | +0.77 | 23.6 | 60.1 |
| WATCHLIST | 4246 | +0.26 | +0.63 | 30.0 | 59.8 |
| HOLD | 5296 | +0.50 | +0.56 | 40.4 | 54.1 |
| CAUTION | 8740 | +1.04 | +1.62 | 44.8 | 53.7 |
| EXIT | 2085 | **+2.08** | **+2.79** | 44.7 | 54.2 |

The ordering is inverted: **EXIT-labelled stocks outperformed BUY at both
horizons**, and CAUTION (the single largest bucket, 8,740 of 22,584
observations) beat BUY too. Note (a) STRONG BUY n = 27 — far too small to be
conclusive on its own, and its fwd60 collapse (+3.78% → +0.81%) versus its
fwd20 number is itself a small-sample artifact, not a real reversal; (b) the
TP/SL columns carry the conviction-target confound (§1.3); (c) the
forward-return inversion is target-independent and is the finding that
matters here.

## 4. Factor attribution (Spearman vs forward returns)

| Component | fwd 5d | fwd 20d | fwd 60d |
|---|---|---|---|
| technical (40 pts) | −0.005 | −0.055 | −0.036 |
| momentum (25 pts) | −0.015 | −0.058 | −0.045 |
| volume (15 pts) | −0.001 | −0.024 | −0.033 |
| **composite (90)** | **−0.017** | **−0.061** | **−0.046** |

No component carries positive signal in this window at 20d/60d. Volume is
consistently the *weakest-magnitude* factor at every horizon (closest to
zero) rather than the most negative — worth reading alongside the 5-year
regime study's identical finding (volume near-zero-to-negative in every
regime breakdown) before concluding anything about its production weight;
see `research/score_variants_volume.py`, a variant study built to test that
question properly rather than off this correlation number alone.

## 5. Baseline comparison — the brutal test

| Ranking | Spearman fwd20 | D10−D1 fwd20 | D10−D1 fwd60 |
|---|---|---|---|
| **Composite score90** | **−0.061** | **−1.85%** | **−1.78%** |
| Naive 20-day momentum | −0.070 | −4.15% | −4.97% |
| RSI rank | −0.062 | −2.11% | −2.46% |
| SMA200-distance rank | −0.063 | −4.44% | −4.95% |

Every ranking tested was negative — the composite score was the **least
negative of the four**, with the smallest decile spread in both directions.
This is the strongest evidence in this report that the finding is a
regime effect hitting the whole trend/momentum factor family in this
specific 12-month window, not a defect unique to this score's construction.

## 6. Regime breakdown (India-VIX labels)

| Regime | n | Spearman fwd20 | Avg fwd20 % |
|---|---|---|---|
| complacency (VIX<13) | 14098 | −0.019 | −1.12 |
| normal (13–17) | 3784 | −0.018 | −0.35 |
| elevated (17–22) | 3280 | −0.047 | +5.45 |
| fear (22–28) | 1422 | **−0.116** | **+11.63** |

In fear regimes the score was *strongly inverted* (−0.116) while average
forward returns were the highest of any regime (+11.63%) — classic
oversold-bounce behavior the score, built as a trend/momentum detector,
structurally cannot capture. 63% of the sample sat in the complacency
regime, where the average forward return itself was negative (−1.12%) —
this specific 12-month window was not a strong period for Indian equities
generally, which is the most likely explanation for why even "calm-regime"
correlation is weakly negative here, unlike the positive complacency-regime
correlation (+0.095 fwd20 / +0.15 fwd60) found across the full 5-year cycle
in the companion regime study.

## 7. Sector breakdown

| Sector | n | Spearman fwd20 |
|---|---|---|
| Cement | 292 | +0.064 |
| IT | 1926 | +0.034 |
| Textiles | 245 | −0.014 |
| Media | 174 | −0.021 |
| Telecom | 63 | −0.052 |
| CapitalGoods | 2597 | −0.059 |
| Consumer | 428 | −0.061 |
| **Other** | 10251 | −0.060 |
| Banking | 977 | −0.062 |
| FMCG | 907 | −0.078 |
| Energy | 1332 | −0.089 |
| Finance | 1622 | −0.098 |
| Healthcare | 380 | −0.120 |
| Retail | 618 | −0.121 |
| RealEstate | 405 | −0.124 |
| Chemicals | 1090 | −0.123 |
| Auto | 1257 | −0.124 |
| Conglomerate | 111 | −0.149 |
| Metal | 906 | −0.164 |

Only Cement and IT (of 19 sectors) show a positive fwd20 correlation; Metal
is the worst. **"Other" carried 10,251 of 22,584 observations (45%) at the
time of this run** — a real data-quality gap (243 of 504 nifty500 tickers
had no sector mapping at all) that has since been fixed (see
`data/universe.py` / `tests/test_universe_sectors.py`); a re-run will
redistribute most of "Other" into real sectors and should sharpen this
table considerably.

---

## 8. Conclusions

1. **The composite score has no demonstrated predictive power for forward
   returns** in the tested year, and is mildly inverted (Spearman −0.02 to
   −0.06 across horizons).
2. **It was not uniquely broken** — three naive single-factor baselines
   tested alongside it were also negative, and more negative than the
   composite in every case. This is evidence for a regime effect on the
   whole momentum/trend factor family in this window, not a construction
   defect specific to this score.
3. **The action-band labels are inverted independent of the regime
   question**: EXIT beat BUY at both 20d and 60d horizons. This is worth
   tracking across future runs to see if it persists once the sector-mapping
   fix and a multi-regime window are both in the sample.
4. **Sector coverage was incomplete for this run** (45% "Other") — fixed
   since; re-run recommended to get a cleaner sector table.
5. **Volume shows the weakest-magnitude signal of the three components at
   every horizon** — consistent with the same finding in the 5-year regime
   study. A dedicated variant study now exists
   (`research/score_variants_volume.py`) to test this properly before any
   production weight change.

## 9. Recommendations

1. **Read this report together with `REGIME_STUDY_REPORT.md`**, not in
   isolation — the 5-year, multi-cycle study is what explains *why* this
   specific 12-month window came out negative (it wasn't a strong period
   for Indian equities generally, and it happened to land more in the
   regime where trend-following signals structurally underperform).
2. **Run `research/score_variants_volume.py`** (added alongside this
   report) before making any decision about the volume component's weight —
   same discipline `RESEARCH_SCORE_VARIANTS.md` already established for
   pattern and the oversold-RSI bonus: test a variant, don't reweight off a
   correlation number alone.
3. **Re-run this study periodically** (now a one-click GitHub Actions
   workflow: "Research Refresh") rather than treating any single 12-month
   window as final — this report's own history is the cautionary example.
4. **Investigate the action-band inversion specifically** on a future
   re-run with the sector-mapping fix in place, to see if it's purely a
   regime artifact or something in the score→action threshold mapping
   itself.

*Generated 2026-07-15 · 22,584 observations · 478 tickers · weekly sampling ·
sentiment neutralised · survivorship-biased universe (disclosed) · first
valid run since FIX EFF1 (2026-07-07).*
