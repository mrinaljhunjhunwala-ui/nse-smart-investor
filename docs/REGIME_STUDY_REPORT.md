# 5-Year Regime Study — What the Score Actually Measures

**Headline answer: the composite score is a trend-quality gauge, not a return
predictor.** Its correlation with *staying in an uptrend* over the next month
is **+0.40** — strong and consistent. Its correlation with *future returns*
is **+0.02 to +0.03** — economically negligible. The score does exactly what
its construction implies: it identifies stocks that are trending and likely
to keep trending, but trending ≠ outperforming.

> Produced by `research/regime_study.py` (read-only replay of the production
> scorer — no weights, thresholds, grades or actions altered).
> Regenerate anytime via the "Research Refresh" GitHub Actions workflow
> (`workflow_dispatch`), or locally: `py -m research.regime_study`

**This supersedes the 2026-06-10 report of the same name.** That report
claimed 40,667 completed observations, but — same root cause as
`SCORE_EFFICACY_REPORT.md` — the walk-forward loop crashed on
`cs.pattern_score` (removed by the pattern-removal migration) on every
sample, silently, until `FIX EFF1` (2026-07-07) corrected it. This is the
first valid run since that fix, and the sample is larger this time:
86,589 observations, because the universe's sector-mapping gap (see §7 of
`SCORE_EFFICACY_REPORT.md`) has also been fixed, allowing more tickers to
resolve cleanly through the full pipeline.

---

## Sample

| | |
|---|---|
| Observations | **86,589** (ticker × weekly sample date) |
| Tickers | 478 usable of 504 current liquid NSE names (survivorship disclosed) |
| Dates | 2022-05-05 → 2026-04-20 (~4 years of sample points, 5y data) |
| Regimes covered | bear 12,681 · bull 61,545 · sideways 12,363 obs (^NSEI SMA50/200 rule) |
| Sentiment | held neutral (90-pt price-derived score studied) |

The window includes the 2022 correction, the 2023–24 rally, and the 2025
chop — the multi-regime coverage the 1-year efficacy study lacks by design.

---

## Q3 first — what is the score measuring? (the key table)

| Outcome | Spearman vs score |
|---|---|
| **Trend quality** (share of next 20 days above SMA-20) | **+0.4012** |
| Future 20-day return | +0.0244 |
| Future 60-day return | +0.0336 |
| Future risk (20-day realized vol) | +0.0732 |
| Risk-adjusted return (20d return / vol) | +0.0194 |

The score is **~16× more correlated with trend persistence than with 20-day
returns**. It is a well-functioning *trend-state descriptor*: high-score
stocks really do stay in uptrends. But uptrend persistence carries almost no
return premium across the full cycle — extended stocks drift more than they
surge. The score is *not* mismeasuring; it is measuring something that
mostly doesn't pay, on a 20–60d horizon, averaged across regimes.

It is also close to **risk-blind** (+0.07 vs future volatility, +0.02 on a
risk-adjusted basis): a high score says relatively little about how bumpy
the ride will be, or whether the return is worth the risk taken to get it.

## Q1 — predictive power by VIX regime

| VIX regime | n | fwd5 | fwd20 | fwd60 | avg fwd20 % |
|---|---|---|---|---|---|
| complacency (<13) | 33,584 | +0.026 | **+0.095** | **+0.150** | +2.27 |
| normal (13–17) | 35,361 | −0.020 | +0.006 | −0.027 | +0.84 |
| elevated (17–22) | 14,165 | −0.012 | −0.000 | −0.013 | +3.97 |
| fear (22–28) | 3,479 | −0.022 | −0.057 | **−0.062** | **+6.38** |

The score works best in complacency, is essentially flat in normal and
elevated regimes, and inverts in fear — while average forward returns are
*highest* exactly where the score is weakest (fear: +6.38% average, −0.062
correlation). **"Normal" VIX is not a reliably informative regime for this
score** despite sitting between two calm-sounding labels — its fwd60
correlation (−0.027) is close to elevated's, not to complacency's. The
1-year efficacy study's negative result is now explained in full: that
12-month window happened to land mostly in complacency (63% of its sample)
during a period when even complacency-regime average returns were negative
— a below-average year for Indian equities generally, not a representative
one.

## Q2 — predictive power by market regime

| Market regime | n | fwd5 | fwd20 | fwd60 | avg fwd20 % |
|---|---|---|---|---|---|
| bull | 61,545 | −0.001 | **+0.061** | +0.088 | +1.55 |
| sideways | 12,363 | +0.042 | +0.014 | +0.077 | +4.04 |
| bear | 12,681 | −0.076 | **−0.062** | **−0.104** | +3.07 |

Genuine, if modest, positive ranking power in bull markets — which is also
where 71% of this 5-year sample sits. **None in bear markets — the score is
actively inverted there** (−0.062 at 20d, worsening to −0.104 at 60d), while
average forward returns during bear regimes were the second-highest of the
three buckets (+3.07%, the rebound the score can't identify who'll lead).

## Q4 — which component works in each regime? (Spearman vs fwd20)

| Regime | technical | momentum | volume | pattern | composite |
|---|---|---|---|---|---|
| bear | −0.030 | **−0.095** | +0.004 | +0.004 | −0.062 |
| bull | +0.059 | **+0.068** | +0.011 | −0.015 | +0.061 |
| sideways | +0.019 | +0.012 | −0.006 | −0.016 | +0.014 |

- **Momentum swings the hardest of any component by regime**: the best
  performer in bull (+0.068) and the single worst in bear (−0.095) — a
  trend-following factor behaving exactly as trend-following factors should
  across a bull/bear cycle.
- **Volume is near-zero in every regime** (+0.004 to +0.011, one slightly
  negative in sideways) — the same shape of evidence (near-zero-to-negative
  across every regime) that motivated pattern's removal from production.
  Unlike pattern, this hasn't been acted on yet — see
  `research/score_variants_volume.py`, added alongside this report to test
  it properly.
- **Pattern remains dead weight** (−0.015 to +0.004 across all three
  regimes) — already excluded from production
  (`PATTERN_REMOVAL_MIGRATION.md`); this run simply reconfirms that decision
  was correct on a larger, fresher sample.

## Q5 — trend-following vs mean-reversion edge

| Regime | Trend edge (mom-20 rank) | Reversal edge (−5d-return rank) | Score |
|---|---|---|---|
| bear | −0.020 | **+0.106** | −0.062 |
| bull | +0.037 | −0.006 | **+0.061** |
| sideways | +0.017 | −0.018 | +0.014 |

- In **bear markets, plain trend-following doesn't work either** (mom20:
  −0.020) — but a pure 5-day-reversal signal shows a real edge (+0.106) that
  the score, built as a trend detector, structurally cannot access.
- In **bull markets the composite actually beats naive momentum**
  (+0.061 vs +0.037) — the extra factors add real value specifically in the
  regime where trend-following is supposed to work, and where 71% of this
  sample sits.
- Mean reversion is not a general-purpose edge — it's a bear/fear-specific
  phenomenon. Applying it outside those regimes (e.g. sideways, where
  5-day-reversal is actively anti-signal at −0.018) would be its own mistake.

---

## Conclusions

1. **The score is a trend-quality instrument (+0.40) with marginal return
   predictivity (+0.02 to +0.03).** Present it as "trend health", not
   expected outperformance — the UI language now reflects this (see
   `dashboard/shared/disclosures.py`, `dashboard/pages/15_investor_guide.py`).
2. **It is regime-conditional in a coherent, now precisely-quantified way:**
   works in bull (71% of history, and beats naive momentum there); inverts
   in bear (15% of history); near-flat in sideways (14%). The 1-year
   efficacy study's negative result was a regime-and-window artifact, not
   randomness — now shown with a larger, cleaner sample than the June run
   that never actually completed.
3. **Pattern is confirmed dead weight in every regime** — already removed
   from production; this reconfirms it.
4. **Volume shows the same near-zero-in-every-regime shape that justified
   pattern's removal, and hasn't been acted on yet.** A dedicated variant
   study (`research/score_variants_volume.py`) now exists to test it with
   the same rigor, before any production change.
5. **A real trend edge exists in bull markets specifically**
   (composite +0.061, beating naive momentum's +0.037) — the composite's
   extra structure earns its keep exactly where trend-following is supposed
   to work.
6. **Mean reversion is real but regime-specific** (bear: +0.106 reversal
   edge) — not a general property of the market, and not something this
   trend-following score can access without a fundamentally different
   construction.

## What this licenses (and doesn't)

Per this study's own mandate, **no model changes were made.** The evidence
now supports:
1. ✅ **Done** — relabel the score in the UI as trend quality, with the
   precise current numbers (`disclosures.py`, `15_investor_guide.py`).
2. ✅ **Done** — regime-gated advisory text using existing VIX plumbing
   (`render_regime_reliability_note()`), corrected to not overstate
   reliability during "normal" VIX (see that function's docstring for why).
3. **Not yet done, now has tooling** — evaluate the volume component the
   same way pattern was evaluated: `research/score_variants_volume.py` tests
   both dropping it and reinvesting its 15 points into technical+momentum
   (the two components with demonstrated regime-dependent signal). Run via
   the same "Research Refresh" workflow used to produce this report, then
   decide — not before.
4. **Still open** — nothing here licenses building or shipping a
   bear-regime mean-reversion variant. The 5-day-reversal edge in bear
   markets (+0.106) is a real, interesting finding, but a production
   feature built on it would need its own dedicated variant study first,
   matching this codebase's established discipline.

*Generated 2026-07-15 · 86,589 observations · 478 tickers · weekly sampling ·
survivorship-biased universe (disclosed) · production scorer untouched ·
first valid run since FIX EFF1 (2026-07-07).*
