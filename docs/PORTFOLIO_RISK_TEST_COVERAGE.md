# Portfolio Risk Analytics — Test Coverage Report (Phase 1)

**File:** `tests/test_portfolio_risk.py` — **21 tests**. Full repo suite: **67 passing**.
Strategy: each metric function tested in isolation on synthetic series; the orchestrator tested
end-to-end with an **injected price loader** and a **mocked beta engine** → fully offline, deterministic.

## Coverage by component

| Area | Tests | What they guard |
|---|--:|---|
| **Max Drawdown** | 3 | known peak→trough (−25%), monotonic-up = 0, too-short → None |
| **Sharpe** | 2 | positive on positive drift; zero-volatility → None (no div-by-zero) |
| **Sortino** | 2 | computed on noisy returns; no-downside → None |
| **Calmar** | 2 | return ÷ |DD|; None when DD≈0 or return missing |
| **Correlation matrix** | 2 | 3×3 shape + unit diagonal; single holding → None |
| **Risk contribution** | 3 | components **sum to 100%**; single holding = 100%; higher vol/weight dominates |
| **Orchestrator (end-to-end)** | 7 | full result (NAV, Sharpe, Sortino, MaxDD, vol, **reused beta**, RC sums 100, high confidence); drops insufficient-history names; no-holdings error; all-dropped error; known total return (+21%); low-confidence on short window; methodology notes present |

## Edge cases explicitly covered
- Zero volatility (Sharpe) and zero downside (Sortino) → `None`, never a crash or fake number.
- Missing drawdown → Calmar `None`.
- Single-holding portfolio → correlation `None`, risk contribution `{only: 100%}`.
- Holding with < 30 days history → **dropped + listed**, rest still computed.
- Empty / fully-unusable portfolio → explicit `error`, no silent blank.
- Beta engine delegated and **mocked** in tests (no network); real reuse verified live.

## What "no silent failure" looks like here
Every metric returns `None` (not 0) when it cannot be computed, and the orchestrator sets
`error` + `holdings_dropped` rather than fabricating a curve — asserted by
`test_compute_no_holdings_errors`, `test_compute_all_dropped_errors`, and the `None`-returning
metric tests.

## Determinism / no network
- Metric tests use seeded `numpy` random or fixed arrays.
- `compute_portfolio_risk` accepts a `price_loader` injection; tests pass a fake loader, so no
  yfinance/Angel calls occur. `analysis.hedging.calculate_portfolio_beta` is monkeypatched.
- Live real-data validation (portfolio.csv, 7 holdings) was run separately and is recorded in the
  implementation report — not part of the offline suite.

## Gaps / future tests (not blocking)
- Dividend-adjusted NAV (currently price-only) — when/if dividends are modelled.
- Benchmark-relative metrics (tracking error, information ratio) — future phase.
- Property test: NAV invariance to row order / duplicate dates.

## Run
```
py -m pytest tests/test_portfolio_risk.py -q     # 21 passed
py -m pytest tests/ -q                            # 67 passed
```
