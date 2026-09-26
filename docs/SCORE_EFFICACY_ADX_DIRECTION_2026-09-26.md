# Score Efficacy — ADX direction check (2026-09-26)

**Question:** the ADX sub-score awards 8/6/3/1 technical points for trend
strength whatever the trend's direction. A candidate change (commit `f41725e`, PR #172) awarded those
tiers only when +DI > −DI. A downtrend (−DI ≥ +DI) gets 1.0, and so does missing DI.
Does this make the composite score rank forward returns better?

**Answer: no. It makes ranking slightly worse.**
- **Overall:** 20-day IC fell from +0.0205 to +0.0188. The paired difference is
  −0.0016, t −1.9. At 60 days the drop is −0.0034, t −3.5.
- **By regime:** the loss comes from trend_down and range. trend_up is unchanged.
  risk_off improves, but that is 5 weeks of data.
- **Outcome: not merged.** PR #172 shipped this write-up only. The rule is more intuitive but hurts
  ranking on this 5-year sample.

## Method

- **Study:** `research/score_efficacy.py` over 5 years with regime weights on: 504
  tickers, 484 usable, 87,612 weekly observations from 2022-07-14 to 2026-07-02.
- **Paired replay:** the universe was fetched once. `_walk_forward` then ran twice on
  the same frames:
  - **Before:** `origin/main` at 3c4792d. Its tree is identical to 68b97c4, which
    already includes #170 and #171.
  - **After:** `f41725e` (the direction-aware rule, on top of 3c4792d).
  - The only difference between the two runs is the ADX rule, so data drift cannot
    account for any gap.
- **Check against the CLI:** the "after" replay matches the official CLI run on
  `f41725e` exactly (`py -m research.score_efficacy --period 5y --regime-weights`, 87,612
  rows, 100% identical `score90`).
- **Metric:** cross-sectional Spearman IC of `score90` against forward return.
  - It is computed per ISO week, which lines up each ticker's staggered sample dates.
    Weeks need at least 50 names; 198 weeks qualify.
  - The t-stat is mean / (sd / √n).
  - "Diff" is the paired per-week difference (after − before) with its own t.
  - Grouping by ISO week reproduces the 2026-09-24 baseline: +0.0205 (t 2.62) here vs
    +0.020 (t ≈ 2.6) there, and trend_up +0.046 vs +0.047.
- **Regime:** the modal `live_regime` label for the week, from
  `analysis.regime.classify_history`.

## Results

| Slice | IC 20d before | IC 20d after | Δ 20d (t) | IC 60d before | IC 60d after | Δ 60d (t) |
|---|---|---|---|---|---|---|
| **All (198 wk)** | +0.0205 (t 2.62) | +0.0188 (t 2.39) | −0.0016 (−1.94) | +0.0335 (t 4.65) | +0.0301 (t 4.08) | **−0.0034 (−3.53)** |
| trend_up (120) | +0.0460 | +0.0456 | −0.0004 (−0.74) | +0.0568 | +0.0558 | −0.0010 (−2.14) |
| range (52) | −0.0123 | −0.0158 | −0.0035 (−1.79) | +0.0078 | +0.0016 | −0.0062 (−2.80) |
| trend_down (21) | −0.0118 | −0.0209 | **−0.0091 (−2.25)** | −0.0067 | −0.0222 | **−0.0155 (−2.98)** |
| risk_off (5) | −0.1151 | −0.0952 | +0.0199 (+1.82) | −0.0910 | −0.0698 | +0.0211 (+3.65) |
| Technical pillar alone | +0.0165 (t 2.46) | +0.0125 (t 1.79) | — | +0.0311 (t 4.97) | +0.0252 (t 3.83) | — |

**Other measures on the same observations:**
- **Pooled Spearman at 20 days:** +0.049 before, +0.046 after.
- **Top-minus-bottom decile gap:** the 20-day gap went from +1.12 to +1.04 pts. The
  60-day gap went from +2.76 to +2.72.
- **Robustness:** grouping by exact sample date (243 dates with at least 20 names)
  gives the same direction. 20-day IC went from +0.0293 to +0.0265, with the paired
  difference at −0.0028 (t −2.3).

**What the change moved:**
- **Scope:** 25.1% of observations changed. Only the technical score moved, always
  downward (−7 to 0, mean −0.88). 7.1% of labels changed.
- **Label counts:** EXIT grew from 4,098 to 6,508 and HOLD shrank from 23,907 to 21,182.
- **Forward returns of the moved names:** the observations that lost points returned
  +2.07% over 20 days, against +2.09% for the unchanged ones. The names the rule
  demotes did not go on to underperform.
- **The EXIT label:** its 20-day return barely moved (+0.75% to +0.79%), so it became
  less selective. The newly demoted names came mostly out of HOLD and CAUTION, which
  returned 2.2% and 1.5% over 20 days.

## Verdict

**Revert. Keep the direction-agnostic ADX.**
- **Why:** strong NSE downtrends have tended to mean-revert over 20–60 days in this
  sample. Removing their trend-strength points pushes them down the ranking just
  before they recover, which is the same effect behind the bear-regime inversion in
  `SCORE_EFFICACY_2026-09-24.md`.
- **Where it hurts:** the 60-day degradation is significant (t −3.5), and it is
  concentrated in trend_down and range.
- **risk_off:** it improves there, but on only 5 weeks. That is too few to justify
  the change.

## Caveats

- **Survivorship:** the universe is today's Nifty-500, as in the baseline study.
- **Overlapping windows:** 20-day and 60-day returns overlap across weekly samples,
  so the t-stats are optimistic. The paired differences share that bias.
- **Neutral inputs:** sector rank, flows, delivery % and positioning are held neutral
  in the replay.
- **Reproducibility:** the paired driver is a scratch script, not committed. It
  swaps in the `origin/main` ADX rule and reuses `_prepare_ticker`, `_walk_forward`
  and `classify_history`. Run the CLI once on each version (3c4792d and f41725e) to reproduce the results.
