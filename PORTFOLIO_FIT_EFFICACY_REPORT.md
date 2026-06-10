# Portfolio Fit Efficacy Report

**Success question:** if two stocks have similar Trend Quality, does Portfolio
Fit help identify which one belongs in the portfolio?

**Answer: not for returns — modestly for risk, and at a cost.** Among
similar-TQ candidates, fit ratings did not identify better forward performers
(the small "Poor Fit" group actually outperformed). A mechanical fit filter on
portfolio construction reduced volatility (−0.6pp) and max drawdown (−0.7pp)
but cost ~1pp CAGR — a *lower* Sharpe. Portfolio Fit's empirically grounded
value is **risk description, not stock selection** — which is consistent with
what it was designed to be.

> Produced by `research/portfolio_fit_efficacy.py`, which replays the
> PRODUCTION `assess_fit()` verbatim (it is pure/deterministic) over historical
> trailing inputs. No production, fit, thesis, scoring or threshold changes.
> Regenerate: `py -m research.portfolio_fit_efficacy`

## Design (and its disclosed limits)

| | |
|---|---|
| Sample | **5,880 candidate observations**, 196 weekly dates, 2022-03 → 2026-03 |
| Reference book | synthetic: **top-10 Trend-Quality names, equal weight**, rebuilt each week (the user's real historical book does not exist as data) |
| Candidates | TQ ranks 11–40 each week — the "similar trend quality" cohort |
| Fit inputs | trailing-only: 120d pairwise correlations vs the book, 252d beta vs ^NSEI, 60d annualised vol, sector weights, portfolio beta. No look-ahead |
| Dimensions replayed | correlation, sector, beta, volatility — **verbatim production rules** |
| Dimensions NOT replayed | thesis verdict (needs fundamentals history → held None); concentration (constant LOW in an equal-weight 10-name book) |
| Caveats | survivorship (current constituents); no transaction costs in the simulation; clustered same-date observations; **rating distribution heavily skewed** — 79% of candidates rated Strong Fit, so negative ratings have small n (Poor Fit 166, Strong Conflict 8) |

## Q1/Q2 — outcomes by fit rating (similar-TQ cohort)

| Fit rating | n | avg TQ | fwd 20d % | fwd 60d % | fwd vol % | max DD 20d % | Sharpe-like |
|---|---|---|---|---|---|---|---|
| Strong Fit | 4,643 | 54.1 | +1.61 | +5.50 | 30.4 | −4.81 | 0.05 |
| Fit | 930 | 54.8 | +1.72 | +5.56 | 32.1 | −5.38 | 0.05 |
| Neutral | 133 | 54.2 | +1.17 | +4.55 | 31.0 | −5.30 | 0.04 |
| **Poor Fit** | 166 | 52.3 | **+3.96** | **+7.57** | 31.3 | −4.17 | **0.12** |
| Strong Conflict | 8 | 60.9 | +5.40 | +1.45 | 43.5 | −9.28 | 0.02 |

- **Returns:** no positive ordering — the Poor Fit group (typically redundant/
  sector-heavy names) *outperformed* on every return metric. (n = 166; treat as
  "no evidence fit selects returns", not "buy poor-fit stocks".)
- **Risk:** Strong Fit names had the lowest forward volatility (30.4%) — a real
  but small effect (fit_score vs fwd vol ρ = **−0.063**).

## Q3 — which dimensions carry information?

| Dimension (raw input) | vs fwd 20d ret | vs fwd vol | vs fwd drawdown | vs Sharpe |
|---|---|---|---|---|
| candidate volatility | +0.048 | **+0.582** | **−0.152** | +0.024 |
| candidate beta | +0.011 | **+0.239** | −0.075 | +0.006 |
| avg correlation to book | −0.047 | +0.038 | −0.064 | −0.044 |
| sector post-add weight | +0.041 | +0.062 | −0.001 | +0.037 |
| **fit_score (composite)** | −0.017 | −0.063 | +0.024 | −0.016 |

The informative dimensions are **risk predictors, not return predictors**:
trailing volatility strongly predicts realized volatility (ρ 0.58) and deeper
drawdowns; beta likewise. Correlation adds a faint diversification/drawdown
signal. The composite fit score *dilutes* these continuous signals into coarse
rule flags — it captures only a sliver (−0.06 vs vol) of what its own inputs
know (+0.58).

## Q4 — portfolio construction simulation (weekly, no costs)

| | Portfolio A: top-10 TQ | Portfolio B: TQ + fit filter |
|---|---|---|
| CAGR | **2.73%** | 1.72% |
| Volatility (ann.) | 13.38% | **12.82%** |
| Max drawdown | −21.6% | **−20.9%** |
| Sharpe | **0.27** | 0.20 |
| Avg pairwise correlation | 0.235 | **0.221** |
| Avg name overlap | — | 8.6 / 10 |

The fit filter did what its rules promise — slightly less correlated, less
volatile, shallower drawdown — but gave up more return than risk, for a lower
Sharpe. With 8.6/10 average overlap, it mostly re-selected the same book and
swapped 1–2 names, and those swaps cost performance in this window.

## Q5 — regimes

Fit_score vs forward return is ≈ zero-to-negative in **every** regime (bear
−0.052, elevated VIX −0.063, others ≈ 0). The mild vol-reduction effect is
present in every regime (−0.02 … −0.11). There is no regime where fit selects
returns.

## Conclusions

1. **Portfolio Fit does not contain return-predictive information independent
   of Trend Quality.** Within similar-TQ cohorts, ratings don't order forward
   returns (point estimates mildly invert).
2. **It does contain real risk information — mostly inherited from trailing
   volatility and beta**, whose persistence is strong (ρ 0.58). The fit
   composite passes through only a fraction of that signal.
3. **As a portfolio constructor, the mechanical filter lowered risk slightly
   but Sharpe net-negatively** in 2022–2026.
4. **Its honest product role is the one it already plays:** a transparent
   *explainer* of marginal book impact ("raises Financials to 41%", "0.85
   correlated with what you own") — those statements are factually grounded.
   It should not be presented or used as a return-improving selector.
5. Possible future research (not a product change): the vol/beta dimension is
   the only strongly predictive ingredient — a "forward volatility" indicator
   would be better surfaced directly than via fit rules.

**Per the mandate, findings only — no production changes made or proposed.**

*2026-06-11 · 5,880 observations · production assess_fit() replayed verbatim ·
outputs in `research/output/portfolio_fit_*.csv`, `fit_*.csv`.*
