# Portfolio Fit Assessment — Methodology (Phase B)

How `analysis/thesis/portfolio_fit.py` answers **"Is this stock a good addition to my current
portfolio?"** by computing the **marginal impact** of adding a candidate to the existing book.
Rules-based and deterministic — **no AI, no new data providers**. Every effect is traceable to a
source subsystem and a supporting metric.

## Design (mirrors Phase A1)
- **`assess_fit(inputs)`** — PURE, deterministic; what the tests target. No network.
- **`build_fit_inputs(candidate, holdings, …)`** — integration seam that assembles inputs from
  existing subsystems (portfolio beta, sector weights, candidate-vs-holdings correlation, candidate
  beta/vol, thesis verdict). Each piece optional + wrapped; a failure degrades that field to None.

## The marginal-weight assumption
The candidate is assumed to be added at an **equal-weight slice** — `c = 1/(n+1)` of the new book —
unless an explicit `assumed_weight_pct` is supplied. This yields concrete before→after numbers
(e.g. *"Increases Banks exposure from 50% to 60%"*). Existing holdings scale to `(1−c)`.

## Inputs (existing systems only)
| Input | Source |
|---|---|
| Candidate thesis verdict + score | Phase A1 `generate_thesis` |
| Candidate beta, volatility | `analysis.hedging.calculate_stock_beta` + return std |
| Candidate sector | `data.universe.get_sector` |
| Portfolio beta | `analysis.hedging.calculate_portfolio_beta` |
| Sector exposure + concentration | computed like `portfolio_manager._analyse_diversification` |
| Candidate↔holdings correlation | holdings' price panel vs candidate returns |

## The five outputs
1. **Fit Rating** — Strong Conflict · Poor Fit · Neutral · Fit · Strong Fit.
2. **Diversification Impact** — from average correlation to your holdings.
3. **Sector Impact** — before→after sector weight.
4. **Beta Impact** — before→after portfolio beta.
5. **Concentration Impact** — effect on your largest sector / concentration risk.
Plus **Position Size Guidance** (Small/Moderate/Large) and **Supporting Evidence** (the union of
positive + negative effects, each `text · source · evidence`).

## Scoring (deterministic)
Each dimension contributes points; the sum is clamped to [−3, +3] → a rating.

| Dimension | Rule → points |
|---|---|
| **Correlation** | avg < 0.30 → **+2** · < 0.60 → **+1** · < 0.80 → 0 · ≥ 0.80 → **−1** (redundant) |
| **Sector** | post-add sector ≥ 45% → **−2** · ≥ 40% → **−1** · new sector → **+1** · else 0 |
| **Beta** | reduces portfolio beta → **+1** · raises it above 1.2 → **−1** · trivial move → 0 |
| **Concentration** | adds to top sector at HIGH/VERY-HIGH risk → **−2** · adds to top sector → **−1** · outside top sector → **+1** |
| **Thesis gate** | verdict ≥ Positive → **+1** · Negative → **−2** · Strong Negative → **−3** |

| Clamped total | Rating |
|---|---|
| +3 | **Strong Fit** |
| +1, +2 | **Fit** |
| 0 | **Neutral** |
| −1, −2 | **Poor Fit** |
| −3 | **Strong Conflict** |

The **thesis gate** ensures a fundamentally weak stock cannot earn a good fit on diversification
alone ("great diversifier, but a poor stock").

## Position size guidance
Counts independent **risk pressures**: avg correlation > 0.70, candidate beta > 1.30, candidate
volatility > 40%, post-add sector ≥ 40%.
- A **weak thesis** (verdict ≤ Negative) → **Small** (size conservatively regardless).
- ≥ 2 pressures → **Small** · 1 pressure → **Moderate** · 0 pressures → **Large**.

The reason string lists exactly which pressures fired.

## Traceability
Every effect is a `FitFactor(text, source, evidence, polarity)`, e.g.:
> Negative: "Heavily over-concentrates Banks" · **Sector Exposure** · Banks 50% → 60%
>
> Positive: "Lowers portfolio market sensitivity" · **Portfolio Beta** · Portfolio beta 1.05 → 0.97

## Edge cases
- **Empty book** — fit is based on the candidate's own thesis + risk only; portfolio-relative
  effects (correlation, sector, concentration) are skipped and noted.
- **Missing subsystem data** — the corresponding dimension simply does not contribute (degrades
  gracefully rather than erroring).

## Explicitly out of scope
- **No AI / LLM / narrative.** Output is structured lists; the UI renders lists, not prose.
- **No buy/sell recommendation. No target prices.** Sizing is qualitative (Small/Moderate/Large).
