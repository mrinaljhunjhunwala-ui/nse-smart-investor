# Portfolio NAV IMPROVE — Implementation Report

Implements the **IMPROVE** recommendation from `PORTFOLIO_NAV_ASSUMPTION_AUDIT.md`: reduce
interpretation risk for the reward metrics **without rebuilding the engine or changing the NAV
methodology**. Detection + classification + disclosure only.

**Result: ✅ done.** The NAV reconstruction is byte-for-byte unchanged; everything added is an
interpretation layer. Suite: **79 passing** (12 new).

## Requirement-by-requirement

### 1. Metric classification ✅
The result now exposes two fixed groups (`ROBUST_RISK_METRICS`, `HYPOTHETICAL_PERF_METRICS`) and
helper methods `risk_metrics()` / `performance_metrics()`. The My Portfolio UI renders them in two
clearly-labelled blocks:
- **📈 Hypothetical Performance** — CAGR, Total Return, Sharpe, Sortino, Calmar, Max Drawdown.
- **🛡️ Risk Profile (current book)** — Beta, Volatility, + the correlation heatmap and
  risk-contribution table.

### 2. Holding-age detection ✅
`detect_recent_purchases(holdings_dates, window_start, weights)` uses the existing **`date_bought`**
(read from `pm.holdings_raw`) to find holdings purchased **inside** the selected lookback
(`date_bought > NAV start`), for any of the 1Y/2Y/3Y (and 6mo) windows. It returns the
**% of portfolio weight affected** and the **count + names**. Verified on real data: the sample
portfolio (all bought 2016) → **0% affected** for 1Y and 3Y → "predate / reliable".

### 3. Confidence adjustment ✅
`adjust_confidence(base, affected_weight_pct)` downgrades the lookback-based confidence:
≥ 50% of weight bought in-window → **low**; ≥ 25% → one notch down; otherwise unchanged. When
`date_bought` is unavailable it stays on lookback length only. **Each adjustment carries an explicit
reason** surfaced in the UI (`confidence_reason`).

### 4. User disclosure ✅
`build_disclosure(period, rec)` produces a specific, weight-aware string, e.g.:
> "34% of portfolio weight (2 holdings) was purchased within the selected 1-year lookback period.
> Performance ratios should be interpreted as hypothetical current-book analytics rather than
> realized portfolio performance. Risk metrics … remain valid."

Distinct messages for the all-predate case ("reliable") and the unknown-dates case. The UI shows it
as a **warning** when ≥ 25% (or dates unknown), else an **info** banner — replacing the old generic
"short lookbacks are noisy" caption.

### 5. Reporting / methodology ✅
`PORTFOLIO_RISK_METHODOLOGY.md` gains an **Interpretation layer** section: current-book
reconstruction, the two-group classification table, holding-age detection + confidence, **why the
risk metrics remain robust**, and the (unchanged) limitations.

### 6. Testing ✅ (12 new → 33 in the file, 79 in the suite)
- **Recent-purchase detection** (3): in-window vs predate vs no-dates → correct affected weight/count.
- **Confidence adjustment** (4): ≥50% → low, 25–50% → one notch, <25% unchanged, unknown unchanged.
- **Disclosure generation** (3): specific %-warning, all-predate, unknown-dates.
- **End-to-end** (1): a synthetic recent purchase → `affected_weight_pct` set, disclosure mentions
  "hypothetical".
- **Classification** (1): `performance_metrics()` / `risk_metrics()` return the right labels.

## What was deliberately NOT changed
- **NAV methodology** — unchanged (no clamping, no entry-date trimming).
- **No transaction-history reconstruction** — out of scope; would need full buy/sell events.
- Engine remains backward-compatible: holdings without `date_bought` work (→ "dates unavailable"
  disclosure), so the existing 21 risk tests pass untouched.

## Validation
- `py -m pytest tests/ -q` → **79 passed**.
- Real data (portfolio.csv): 0% affected, "predate/reliable", high confidence (correct — a true
  buy-and-hold since 2016).
- My Portfolio page renders both metric groups + the disclosure with no exception (AppTest).

## Net effect
The reward ratios are now unambiguously framed as *hypothetical current-book* analytics with a
specific, data-driven warning about how much of the book is recent, while the robust risk metrics
are visually separated and labelled as trustworthy — closing the interpretation-risk gap the audit
identified, with zero change to the underlying methodology.
