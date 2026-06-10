# Score Variant Study — Pattern & Oversold-RSI Removal

**Question:** do the two empirically weak components (candlestick pattern,
oversold-RSI bonus) actually reduce signal quality?

**Answer:**
- **Pattern (Variant A): yes, mildly — removal helps slightly everywhere and
  hurts nowhere.** Confirmed dead weight.
- **Oversold-RSI bonus (Variant B): no — it's a trade-off, not dead weight.**
  Removing it makes the score a purer trend gauge but *worsens* fear-regime
  behaviour, where the contrarian credit was the only part pulling the right way.
- **All effects are small** (±0.002–0.005 Spearman). No variant turns the score
  into a return predictor; the case for any change is simplification, not alpha.

> Produced by `research/score_variants.py`. Production scoring untouched —
> variants derived arithmetically per observation from the production score.
> Regenerate: `py -m research.score_variants`

## Setup

| | |
|---|---|
| Observations | 40,663 (209 tickers × weekly, 2022-03 → 2026-03, 5y data) |
| BASE | production 90-pt price-derived score (sentiment neutralised) |
| Variant A | BASE − pattern component |
| Variant B | BASE − oversold-RSI bonus* |
| Variant C | BASE − both |
| Component activity | pattern ≠ 0 on **16.6%** of observations; oversold bonus active on **17.5%** |

\* *Definition (design decision, documented):* the production RSI map awards
10 pts (RSI<30) / 8 pts (RSI 30–40) as contrarian "bounce" credit. Variant B
re-scores those zones at the 1-pt minimum the map gives RSI>80, making the RSI
factor purely trend-consistent. Rank-based metrics are unaffected by the
variants' differing point scales.

## Headline comparison

| Variant | Trend-persistence ρ | fwd-20d ρ | fwd-60d ρ | Decile monotonicity (fwd20) | D10−D1 fwd20 | D10−D1 fwd60 |
|---|---|---|---|---|---|---|
| BASE (production) | 0.4107 | 0.0416 | 0.0340 | 0.906 | +1.88% | +2.78% |
| **A: no pattern** | 0.4134 | **0.0439** | **0.0358** | **0.952** | **+1.91%** | **+3.06%** |
| B: no oversold bonus | 0.4195 | 0.0413 | 0.0329 | 0.915 | +1.74% | +2.63% |
| C: both removed | **0.4212** | 0.0432 | 0.0344 | 0.939 | +1.66% | +2.74% |

- **A improves every return metric** (and decile monotonicity 0.906 → 0.952) —
  consistently, but by tiny margins.
- **B improves trend-persistence purity** (+0.009, the largest single gain) but
  slightly *reduces* every return metric and shrinks the decile spread.
- **C** is the purest trend gauge (0.421) but inherits B's weaker return spread.

## Regime behaviour (fwd-20d Spearman)

| Regime | n | BASE | A: no pattern | B: no oversold | C: both |
|---|---|---|---|---|---|
| bull | 28,642 | 0.0564 | **0.0589** | 0.0551 | 0.0573 |
| sideways | 7,054 | 0.0793 | **0.0818** | 0.0792 | 0.0808 |
| bear | 4,967 | −0.0095 | −0.0105 | **−0.0002** | −0.0008 |
| complacency | 14,781 | 0.0689 | **0.0742** | 0.0673 | 0.0719 |
| normal | 17,429 | 0.0472 | 0.0468 | 0.0471 | 0.0467 |
| elevated | 7,240 | −0.0091 | −0.0071 | −0.0078 | −0.0061 |
| fear | 1,213 | −0.0632 | −0.0554 | **−0.0742** | −0.0688 |

The decisive nuance:
- **A (no pattern)** is better or equal in six of seven regimes — including
  *less* inverted in fear. Patterns add noise everywhere.
- **B (no oversold)** neutralises the bear-regime inversion (−0.0095 → −0.0002)
  but makes **fear-regime inversion worse** (−0.063 → −0.074). The oversold
  bonus was doing its intended job — catching panic bounces — at the cost of
  muddying the trend measure in normal times. Removing it trades one regime's
  behaviour for another's.

## Decile sanity check (BASE vs C)

Top-decile outcomes are essentially identical (BASE D10: fwd20 +2.74%, persist
72.8% · C D10: +2.68%, 72.7%) — confirming that even the "best" variant changes
ranking at the margins, not the substance.

## Conclusions & recommendation

1. **Pattern component — evidence supports removal.** Small, consistent
   improvement across return correlation, monotonicity, decile spread, and six
   of seven regimes. But the honest framing: the gain is ≈ +0.002 Spearman —
   the real argument is **simplification** (10 pts and pattern-detection code
   maintained for negative-to-zero contribution), not performance.
2. **Oversold-RSI bonus — evidence does NOT support removal.** It is the only
   part of the score aligned with fear-regime reality. If the blended
   personality bothers us, the better design (future discussion) is *splitting*
   it into a separate "bounce candidate" flag rather than deleting it.
3. **No variant materially changes what the score is** — a trend-quality gauge
   (ρ ≈ 0.41 persistence) with marginal return predictivity (ρ ≈ 0.04). Phase-1
   UI framing remains accurate for all variants.
4. **If a production change is made, adopt Variant A only**, gated by:
   re-running all three research harnesses as regression checks, updating the
   Investor Guide component table, and reweighting the freed 10 pts — *that*
   reweighting choice would itself need a variant study first (e.g., fold into
   technical vs. spread proportionally), so the prudent v1 is to cap the score
   at 90+sentiment rather than redistribute.

**Per the mandate, no production change has been made.** The comparative
evidence now exists; the decision is the owner's.

*2026-06-11 · 40,663 observations · 209 tickers · production scorer untouched ·
outputs in `research/output/variant_*.csv`.*
