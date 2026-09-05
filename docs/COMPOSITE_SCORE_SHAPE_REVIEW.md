# Composite Score — Shape Review

_2026-09-02 · Follow-up to the UI + market-analysis audit · Guardrail §5 opened for review at user request._

## Bottom line

The 4-pillar shape (40 technical + 25 momentum + 15 volume + 10 sentiment, cap 90) is defensible as v1 but leaks alpha in three specific, testable ways. The recommendation is **staged**: three internal re-partitions ship first inside the existing shape (Guardrail-safe, no ratification needed), one regime dispatcher ships next as an opt-in flag validated on the 5-year window, and only then does a proper shape change (add a Positioning pillar) go to `verdict-regression-reviewer` and you.

Do not do all seven at once. Each one moves the golden snapshot; each one wants its own reviewer writeup.

## Where the current shape leaks

Reading `analysis/score.py` against the SCORE_EFFICACY findings:

1. **Momentum treats absolute return as ability.** `_score_momentum()` scores `pct_change(5)`, `pct_change(20)`, `pct_change(60)` in isolation. A stock up 5% while Nifty is up 8% earns 7 of 10 pts in the 20-day bucket. In a bull tape this is systematic beta reward; in a bear tape it systematically penalises defensives that are outperforming on the way down. The single largest cheap fix in this document.
2. **Sentiment is thin.** 10 pts split across VIX regime (0–6 pts) and sector rank (0–4 pts). FII/DII 5-day sign is computed elsewhere in the app and shown to the user in the market-context strip — the score itself never sees it.
3. **Volume ignores the one signal India uniquely publishes free.** `_score_volume()` reads volume ratio and OBV slope. NSE bhavcopy carries per-stock delivery %; delivery-vs-price divergence is the closest thing retail India has to a Level-2 institutional print.
4. **Weights are fixed across regimes despite the 5-year study documenting they should not be.** SCORE_EFFICACY: 62–66% BUY hit rate on the 2020–22 trending half, 46–49% on the 2023–25 mean-reverting half. The score reads the same regardless.
5. **No positional information for F&O-eligible names.** Every professional NSE process weighs OI buildup, PCR, max-pain distance. The score ignores them entirely.
6. **RSI bucket geometry is non-monotonic without trend context.** RSI < 30 pays 10 of 12 pts (bounce candidate) regardless of whether the 200-DMA is rising or falling. In a downtrend, that's rewarding falling knives.
7. **MACD is scored with 4 flat buckets.** Rate-of-change of histogram is not read.

Items 1–5 are the ones worth fixing. Items 6–7 are polish that can wait.

## Ranked recommendations

Each recommendation lists cost, risk, whether it changes the shape as defined by Guardrail §5, and what artefact ships alongside it.

### 1. RS-vs-Nifty inside Momentum (25 pts unchanged)
Internal split: `abs_returns:15 + rs_vs_nifty:10`.

RS score = z-score of `(stock_ret_20d − nifty_ret_20d)` against its trailing 250-day distribution, plus RS-line slope sign.

- **Shape change:** No. Momentum stays at 25 of 90.
- **Cost:** Fetch Nifty once per scan (already done in Command Centre). Add `nifty_return_20d` to the scoring context object.
- **Risk:** Low. Momentum-heavy names in strong beta rallies will lose some points; leaders in flat / weak tapes will gain some. Direction of drift is the intended one.
- **Ships with:** `verdict-regression-reviewer` writeup explaining every ticker delta on the 62-ticker golden snapshot.
- **Expected impact:** Highest single-factor lift in this document. Textbook signal, free to compute.

### 2. FII/DII 5-day sign inside Sentiment (10 pts unchanged)
Internal split: `vix_regime:5 + sector_rank:3 + flows:2`.

Flow score reads from `analysis/fii_dii.load_history(days=5)`. Sign of `fii_net + dii_net` gates it; weight higher for large-caps where flows dominate.

- **Shape change:** No.
- **Cost:** Zero fetching (already cached).
- **Risk:** Very low. 2 pts of budget, effectively a tie-breaker.
- **Ships with:** Reviewer writeup.

### 3. NSE delivery % inside Volume (15 pts unchanged)
Internal split: `vol_ratio:8 + delivery_pct:4 + obv:3`.

Add `data/nse_delivery.py` reading the free NSE bhavcopy delivery file. Score `delivery_pct_5d_avg` against the stock's 60-day distribution. Divergence (price up, delivery down) becomes a caution flag surfaced in the narrative.

- **Shape change:** No.
- **Cost:** One new provider + one indicator column. Must follow Guardrail §14 (drift-warning discipline) and get a canary test per §16.
- **Risk:** Low, but data path is new. Blocked on Phase 2 canary pattern being live.
- **Ships with:** Reviewer writeup + provider canary test.

### 4. Regime-adaptive stop-loss bounds (not a scoring change)
`_compute_entry_levels()` uses fixed `[1.2, 3.0]` × ATR stop bounds. Scale by VIX percentile:
- low-VIX: `[1.0, 2.5]`
- normal-VIX: current
- high-VIX: `[1.5, 3.5]`

- **Shape change:** No.
- **Cost:** Trivial. Target multiplier logic already vol-anchored.
- **Risk:** Very low. Only SL / R:R deltas, not `.score`.

### 5. Regime-conditional weight dispatch (opt-in flag)
Two weight sets:
- **Trending** (current default): `40 tech + 25 mom + 15 vol + 10 sent`
- **Mean-reverting** (proposed): `30 tech + 30 mom + 20 vol + 10 sent`, with an oversold-bounce bonus inside momentum reading RSI + distance below 20-DMA

Dispatch by `regime.snapshot_live().label`. Ship as `USE_REGIME_WEIGHTS=False` first. Validate on the 5-year window in `research/score_variants_regime.py`. Flip default only if the flag-on run beats flag-off on **both halves** of the SCORE_EFFICACY sample.

- **Shape change:** Ambiguous. Trending mode is unchanged. Mean-reverting mode has different weights and a new bonus, so `verdict-regression-reviewer` review is mandatory.
- **Cost:** Medium. Bulk of the work is validation, not implementation.
- **Risk:** Real — regime is itself a noisy classifier. Guard by keeping fixed weights as the fallback path and requiring the walk-forward win before making the flag default.

### 6. Add Positioning pillar (proper shape change, needs your ratification)
Two designs to pick from:

**Design 6a — Re-balance to 90:** `35 tech + 20 mom + 15 vol + 10 sent + 10 positioning`. Preserves the 90 cap and Guardrail §5's spirit (still 4 → now 5 pillars). Requires walking back tech and mom by 5 each.

**Design 6b — Extend cap to 100:** Keep 40/25/15/10 as-is, add positioning as pure 10-pt overlay, cap becomes 100. Breaks Guardrail §5 more literally but preserves every current sub-score's calibration.

Positioning content (for F&O-eligible names only; graceful-degrade to 0 and re-scale for non-F&O):
- OI regime: long buildup / short buildup / long unwinding / short covering (3 pts)
- PCR zone (extreme reads only): 2 pts
- Distance from max pain (this expiry): 2 pts
- FII index-futures net position sign: 3 pts

- **Shape change:** Yes, unambiguously. Blocked on your explicit ratification.
- **Cost:** High. Needs an options-chain fetcher with drift discipline, expiry-aware indexing, and non-trivial fallback logic for non-F&O names.
- **Risk:** Medium. Real evidence that positional info is where informed flow shows first on NSE F&O names, but implementation surface is large.
- **Recommendation:** Do only after 1–5 have shipped and you have a track record of successful reviewer-writeup cycles.

### 7 and 8. RSI trend-context and MACD histogram slope (polish)
Both are internal to `_score_technical()` and change no shape. Ship whenever, low leverage.

## What I am *not* recommending

- **Reintroducing candlestick pattern scoring** — Guardrail §6, decided by 40k-observation study, closed.
- **Adding an ML meta-model on top of sub-scores** — no data ops discipline in place yet to keep training / production in sync; premature.
- **Adding a Quality × Valuation *pillar*** — Guardrail-safe path is a **sidecar `overlay_score`** displayed next to the composite, never blended into it. Already Task 3.3 in the plan.

## Sequenced landing plan

| Order | Task | Ships with | Blocks |
|---|---|---|---|
| 1 | Recommendation 1 (RS inside Momentum) | Reviewer writeup, golden-snapshot re-capture | Nothing |
| 2 | Recommendation 2 (Flows inside Sentiment) | Reviewer writeup, snapshot re-capture | 1 |
| 3 | Recommendation 4 (Regime stop-loss) | Reviewer writeup on SL / R:R deltas only | Nothing |
| 4 | Recommendation 3 (Delivery % in Volume) | Provider canary + reviewer writeup | Phase 2 canary pattern live |
| 5 | Recommendation 5 (Regime weights, opt-in flag) | Walk-forward validation report | 1, 2 |
| 6 | Recommendation 6 (Positioning pillar) | Your written ratification of 6a vs 6b, then reviewer writeup | 5 shipped and default |

Recommendations 7 and 8 slot anywhere.

## Success criteria for each Phase 3 landing

Before merging any of the above:

- [ ] `py -m pytest tests/test_valuation_golden_snapshot.py -q` passes, or every failing ticker is explained in the reviewer writeup
- [ ] Guardrail §5 shape unchanged (recommendations 1–5) OR change is explicit in the commit message and cross-referenced to this doc (recommendation 6)
- [ ] Guardrail §7 posture-monotonicity holds — no ticker's posture flips against the direction of its `.score` change
- [ ] Ruff clean on every touched file
- [ ] `page-smoke-check` green on every page that renders `CompositeScore`

## Open decision for you

- **D1.** Approve the sequenced order above, or re-order?
- **D2.** For Recommendation 6 (Positioning pillar), which design — 6a (re-balance to 90) or 6b (extend cap to 100)? Not needed yet; needed before 6 starts.

Written under `nse-app-guardrails` house style §21 — no em-dashes.
