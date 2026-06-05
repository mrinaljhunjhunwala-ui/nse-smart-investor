# Portfolio Risk Analytics — Implementation Report (Phase 1)

**Objective:** implement portfolio risk & performance analytics, reusing existing portfolio,
holdings, price and beta infrastructure. No paid fundamentals providers (Yahoo remains the
price feed via the existing tiered fetcher).

**Result: ✅ all 8 deliverables implemented, tested, and validated on real holdings.**

## What was built
- **`analysis/portfolio_risk.py`** — the risk engine:
  - `compute_portfolio_risk(holdings, period, rf_annual, price_loader)` → `PortfolioRiskResult`.
  - Standalone, unit-testable metric functions: `max_drawdown`, `sharpe_ratio`, `sortino_ratio`,
    `calmar_ratio`, `correlation_matrix`, `risk_contributions`.
- **`dashboard/pages/03_my_portfolio.py`** — a "📉 Portfolio Risk & Performance" section:
  NAV/equity area chart, 8 metric cards, correlation heatmap, risk-contribution table, a
  lookback selector, a confidence warning, and a Methodology & assumptions expander.
- **`tests/test_portfolio_risk.py`** — 21 tests (suite now **67 passing**).
- Methodology + test-coverage docs (this report's siblings).

## Deliverable checklist
| # | Deliverable | Status | Note |
|---|---|---|---|
| 1 | Portfolio NAV / Equity Curve | ✅ | `NAV_t = Σ qty_i × close_i,t`, aligned on common dates |
| 2 | Maximum Drawdown | ✅ | peak→trough %, with dates |
| 3 | Sharpe Ratio | ✅ | annualised, rf-adjusted |
| 4 | Sortino Ratio | ✅ | downside-deviation denominator |
| 5 | Calmar Ratio | ✅ | annualised return ÷ |MaxDD| |
| 6 | Portfolio Beta | ✅ | **reuses `analysis/hedging`** (no re-implementation) |
| 7 | Holdings Correlation Matrix | ✅ | Pearson on daily returns → heatmap |
| 8 | Risk Contribution by Position | ✅ | Euler variance decomposition, % to 100 |

## Reuse (as required)
- **Prices:** `data.fetcher.fetch_single` (tiered Angel→Stooq→Yahoo, cached) — no new data path.
- **Beta:** `analysis.hedging.calculate_portfolio_beta` / `calculate_stock_beta` — delegated, not
  rebuilt; the structured fetch-fallback logging from the audit is reused too.
- **Holdings:** the My Portfolio page feeds `summary.holdings` (ticker + quantity) straight in — no
  new holdings model.
- **Theme/UI:** existing `nse_pro` Plotly template + the metric-truncation CSS fix.

## Validation on real holdings (portfolio.csv, 7 names, 1y)
```
used=7 dropped=0 | n_days=249 | confidence=high
Total return -6.44% | Ann return -6.54% | Ann vol 20.2%
MaxDD -23.4% | Sharpe -0.55 | Sortino -0.75 | Calmar -0.28 | Beta 0.627
Risk contribution: BALRAMCHIN weight 37.3% -> risk 45.6% (risk-concentrated);
                   ONGC weight 16.7% -> risk 5.3% (defensive); corr matrix 7x7
```
The **risk ≠ weight** result is the headline value: ONGC is a sixth of the capital but a twentieth
of the risk, while BALRAMCHIN's risk share (46%) exceeds its weight (37%).

## Confidence & limitations surfaced (as required)
- Confidence label (low/medium/high) on lookback length, with a UI warning at low/medium.
- A methodology expander lists: the **constant-holdings NAV** caveat, the 252-day annualisation,
  the assumed risk-free rate, the Nifty-50 beta basis, and any **dropped holdings** (insufficient
  history). Failures surface (`error`, dropped list) — never silent zeros.

## Validation
- `py -m pytest tests/ -q` → **67 passed** (21 new + 46 prior).
- Real-data end-to-end run (above) + My Portfolio page loads clean via AppTest (no exception).

## Out of scope (per instruction)
No paid fundamentals providers. Yahoo (via the existing fetcher) remains the price source; the
fundamentals stack from Phase 0 is untouched.
