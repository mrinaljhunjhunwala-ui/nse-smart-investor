# Portfolio Risk Analytics — Methodology (Phase 1)

How each metric in `analysis/portfolio_risk.py` is computed, the assumptions, and how to
read it. All metrics are derived from one keystone: the reconstructed **NAV / equity curve**.

## 0. NAV / Equity Curve (the keystone)
```
NAV_t = Σ_i  quantity_i × close_i,t      (aligned on common trading dates)
```
- Prices come from the existing tiered fetcher (`data.fetcher.fetch_single`: Angel→Stooq→Yahoo, cached).
- **Constant-quantity reconstruction:** today's holdings are assumed held unchanged over the
  lookback. It answers *"what would this exact book have done over the past N days?"* — it is **not**
  your realised history. It ignores past buys/sells, dividends, and transaction costs.
- Names with < 30 days of history (or no overlap) are **dropped and listed** (a survivorship caveat).
- Daily returns: `r_t = NAV_t / NAV_{t-1} − 1`.

## 1. Maximum Drawdown
`MaxDD = min_t ( NAV_t / running_max(NAV)_t − 1 )` — worst peak-to-trough fall (a negative %),
with the peak and trough dates reported. Pure path statistic; no assumptions.

## 2. Sharpe Ratio (annualised)
```
Sharpe = (mean(r) − rf_daily) / std(r) × √252
rf_daily = (1 + rf_annual)^(1/252) − 1     (rf_annual default 6.5% p.a.)
```
Excess return per unit of **total** volatility. `None` if volatility is 0.

## 3. Sortino Ratio (annualised)
```
Sortino = (mean(r) − rf_daily) / downside_dev × √252
downside_dev = √( mean( min(0, r − rf_daily)² ) )
```
Like Sharpe but penalises only **downside** volatility — upside swings don't count as "risk".
`None` when there is no downside (degenerate).

## 4. Calmar Ratio
```
Calmar = annualised_return / |MaxDD|
```
Return earned per unit of worst-case loss. `None` when MaxDD ≈ 0. Sensitive to the lookback
(a longer window usually contains a deeper drawdown).

## 5. Portfolio Beta (reused engine)
Delegated to `analysis/hedging.calculate_portfolio_beta` — `β_p = Σ_i w_i β_i`, where each
`β_i = Cov(r_i, r_Nifty) / Var(r_Nifty)` and `w_i` is the **current value weight**. Benchmark = Nifty 50.
β < 1 → defensive; β ≈ 1 → tracks market; β > 1.2 → amplifies market moves.

## 6. Holdings Correlation Matrix
Pearson correlation of the holdings' **daily returns** (`returns.corr()`). Reveals *false*
diversification — names that move together. Requires ≥ 2 holdings and ≥ 5 shared days.

## 7. Risk Contribution by Position
Component contribution to portfolio **variance** (Euler decomposition), as a % summing to 100:
```
σ²_p = wᵀ Σ w                     (Σ = covariance of holdings' daily returns; w = value weights)
RC_i = w_i · (Σ w)_i / σ²_p × 100
```
**Risk %** ≠ capital weight: a low-volatility / low-correlation name contributes *less* risk than
its weight (e.g. a defensive stock), while a volatile, correlated name contributes *more*. This is
the headline insight — it shows where your *risk*, not your capital, is concentrated.

## Assumptions & confidence
- **Annualisation:** 252 trading days.
- **Risk-free rate:** 6.5% p.a. by default (≈ India 10Y G-Sec), configurable per call.
- **Confidence gating** (on lookback length): `< 90` trading days → **low**, `90–180` → **medium**,
  `≥ 180` → **high**. Short windows make ratios noisy; the UI surfaces a warning at low/medium.
- **Not advice:** these are descriptive analytics on a reconstructed curve, not forward-looking
  guarantees. Survivorship and the constant-holdings approximation both flatter results.

## How to read it (quick guide)
| Metric | Good | Caution |
|---|---|---|
| Sharpe | > 1 | < 0 means below the risk-free rate |
| Sortino | > Sharpe | very low → frequent/deep down days |
| Calmar | > 1 | < 0.5 → returns small vs worst drawdown |
| Max Drawdown | shallower | deep DD = painful peak-to-trough |
| Beta | matches your risk appetite | > 1.2 → consider a hedge |
| Risk % vs Weight % | aligned | Risk % ≫ Weight % → hidden risk concentration |
