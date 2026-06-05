# Phase B — Portfolio Fit Assessment — Implementation Report

Implements **Phase B** from `THESIS_CAPABILITY_AUDIT.md`: answer *"Is this stock a good addition to
my current portfolio?"* by computing the **marginal impact** of adding a candidate to the existing
book. **Existing systems only — no AI, no new data providers.**

**Result: ✅ done.** New `analysis/thesis/portfolio_fit.py` + 28 deterministic tests
(**138 passing** total) + a "🧩 Portfolio Fit Assessment" section on the Analyze Stock page + two docs.

## Deliverables
| Deliverable | Status | Location |
|---|---|---|
| `PortfolioFitResult` engine | ✅ | `analysis/thesis/portfolio_fit.py` (exported via `analysis/thesis/__init__.py`) |
| Test suite (20+ target) | ✅ **28 tests** | `tests/test_portfolio_fit.py` |
| Methodology document | ✅ | `PORTFOLIO_FIT_METHODOLOGY.md` |
| Implementation report | ✅ | this file |
| UI section | ✅ | `dashboard/pages/04_analyze_stock.py` — "🧩 Portfolio Fit Assessment" |

## Inputs — existing systems only
**Candidate:** thesis verdict (Phase A1 `generate_thesis`), beta (`analysis.hedging`), sector
(`data.universe.get_sector`), volatility (return std), fundamentals (via the thesis).
**Current portfolio:** sector exposure + concentration (computed as in `portfolio_manager`),
portfolio beta (`analysis.hedging.calculate_portfolio_beta`), candidate↔holdings correlation (the
holdings' price panel vs the candidate's returns). No new providers introduced.

## Outputs — `PortfolioFitResult`
Fit Rating · Diversification Impact · Sector Impact · Beta Impact · Concentration Impact ·
Position Size Guidance · Supporting Evidence (= positive ∪ negative effects). Each effect is a
traceable `FitFactor(text, source, evidence, polarity)`.

**Fit ratings:** Strong Conflict · Poor Fit · Neutral · Fit · Strong Fit.

## Rules (deterministic, fully traceable)
Marginal weight `c = 1/(n+1)` (equal-weight) unless `assumed_weight_pct` given, producing concrete
before→after numbers exactly as specified:
> Positive: "Lowers portfolio market sensitivity" · Portfolio Beta · Portfolio beta 0.92 → 0.87
>
> Negative: "Heavily over-concentrates Banks" · Sector Exposure · Banks 50% → 60%

Each dimension contributes points (correlation, sector, beta, concentration, thesis gate); the sum
clamps to [−3, +3] → rating. The **thesis gate** prevents a weak stock earning a good fit on
diversification alone.

## Position guidance — Small / Moderate / Large
Based on concentration, volatility, beta and correlation pressures (per spec): a weak thesis forces
**Small**; ≥ 2 pressures → **Small**; 1 → **Moderate**; 0 → **Large**. The reason lists which
pressures fired. **No target prices, no buy/sell calls** — sizing is qualitative only.

## Testing — 28 deterministic tests (target 20+)
All hand-build a `PortfolioFitInputs` → no network, reproducible.
- **Fit rating** (5): strong fit, strong conflict, neutral (cancelling), always-valid-label, poor fit.
- **Diversification** (3): low-corr positive, high-corr redundant, evidence names most-correlated.
- **Sector** (3): before→after string, over-concentration negative, new-sector positive.
- **Beta** (3): reduction positive, increase>1.2 negative, impact string present.
- **Concentration** (2): worsens-top-sector negative, improves-balance positive.
- **Position size** (4): Large (no pressure), Small (multi-pressure), Moderate (one), weak-thesis→Small.
- **Traceability** (5): every effect traceable, supporting-evidence union, provenance list,
  `to_dict`, determinism.
- **Edges** (2): empty book → Neutral first-position; explicit weight overrides equal-weight.
- **Integration seam** (1): `build_fit_inputs` with an injected price loader computes vol +
  correlation + sector weights offline.

```
py -m pytest tests/test_portfolio_fit.py -q   → 28 passed
py -m pytest tests/ -q                         → 138 passed
```

## UI
The Analyze Stock page gains "🧩 Portfolio Fit Assessment": loads the user's `portfolio.csv` (or the
uploaded book), assesses the analysed stock against it, and shows the **Fit Rating** badge, the four
**impact** lines, **Positive effects** / **Negative effects** as two structured-list columns, and
**Position size guidance** with its reason. Reuses the thesis already computed on the page. Wrapped
in try/except; shows a friendly prompt when no portfolio exists. **No prose, no AI.**

## Explicitly NOT done (per scope)
- **No AI / LLM / narrative generation.** Structured lists only.
- **No buy/sell recommendations, no target prices.**
- **No new data providers** — Phase C (valuation context, liquidity) remains separate.

## Net effect
The platform now closes the **5th** "explain this stock" output: a buyer can see, with full
traceability, whether a candidate *strengthens or strains* their actual book — diversification,
sector, beta and concentration — and how large a position is prudent, built entirely from existing
signals with zero AI.
