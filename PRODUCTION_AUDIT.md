# Production-Readiness Audit — NSE Smart Investor

**Scope:** correctness, reliability, testing, and finance-engine integrity. No new features.
**Method:** static review of the finance core (`analysis/`, `utils/indicators.py`, `strategies/`,
`backtest/`, `trade_store.py`, `data/`) + a new regression test suite, including a
**property-based anti-look-ahead test** that empirically validates the leakage findings.

## Headline

| Area | Verdict |
|---|---|
| **Look-ahead / data leakage in indicators & strategies** | ✅ **None found** — proven by `test_no_lookahead_in_indicators` (historical indicator values are byte-identical when 50 future bars are added/removed). |
| **Backtest execution timing** | ✅ Correct — `backtesting.py`, signals on bar *T* close → fill at bar *T+1* open. |
| **Biggest real risks** | ⚠️ Survivorship bias (static universe), no slippage model, and **silent failures** that mask bad/missing data (48 `except: pass` blocks). |

Fixes applied in this pass are marked **[FIXED]**; the rest are documented with a recommended fix and confidence.

---

## Priority 1 — Exception Handling

**Inventory:** 95 `except Exception` + 48 silent `except: …: pass` blocks across 24 files (0 bare `except:`).

Most dashboard-layer silent passes are *intentional, graceful UI fallbacks* (cosmetic features that should degrade quietly). The audit focused on the **finance/data core**, where a swallowed error means **wrong or missing numbers presented as fact**.

| File:line | Original risk | Status / fix |
|---|---|---|
| `trade_store.load_by_account` | `except: return DataFrame()` — a broken DB looked identical to "no trades", so the user could unknowingly re-open closed positions. | **[FIXED]** logs `_log.warning(...)` before returning empty; UI still degrades instead of crashing. |
| `analysis/portfolio_manager.py:291` | Parallel holding-score failure swallowed → a holding can drop out of the portfolio **total value / P&L** with no trace. | **[FIXED]** logs the failed ticker (it's retried by the sequential pass; logging makes a double-failure diagnosable). |
| `data/fetcher.py` (×2), `utils/live_price.py` (×4) | Per-source fetch failures swallowed. **Acceptable** as tier fallbacks (Angel→Stooq→Yahoo) but currently invisible. | **Recommend:** `logging.warning` per failed tier (no UX change). Confidence: High. |
| `analysis/macro.py:146` | A failed macro symbol is dropped from the macro dashboard. | Low impact (informational page). Recommend logging. |
| `analysis/score.py:24` | `except AttributeError: pass` on `sys.stdout.reconfigure`. | **Benign** — encoding setup only. Leave. |

**Recommendation:** add a one-line `logging.getLogger(__name__)` to each data-layer module and replace the remaining silent data-fetch passes with `log.warning`. Do **not** convert the dashboard UI fallbacks to visible errors — those are deliberate (a blank cosmetic panel is better than a red crash box); the earlier UX pass already surfaced the ones that hide *data* problems.

---

## Priority 2 — Backtest Integrity

### ✅ Verified clean
- **Indicators only use historical data.** Every indicator in `add_all_indicators` is backward-looking:
  RSI/MACD via `ewm`, SMAs/ATR/Bollinger via trailing `rolling`, **Fibonacci via `rolling(252).max/min`
  (not full-series extremes)**, RSI-divergence over a strict backward window `prices[i-lookback:i]`.
  *Proven* by `test_no_lookahead_in_indicators`.
- **Entries occur after signals.** `RSIMACDStrategy`/`MomentumStrategy` decide on `self.data.Close[-1]`
  (bar *T* close) and `self.buy()` fills at bar *T+1* open (`backtesting.py` default). No same-bar fills.
- **No future info in simulation.** `self.I()` reveals indicator arrays progressively; `crossover()` uses
  only `[-1]`/`[-2]`.
- **Costs modeled.** Round-trip `TOTAL_COST = STT + 2×brokerage + 2×exchange ≈ 0.23%` (tested for realism).

### ⚠️ Findings
| # | Finding | Impact | Status |
|---|---|---|---|
| B1 | **Survivorship bias** — backtests run on `get_universe("nifty500")`, a *current* static membership list. Stocks delisted/removed/that went to zero are absent, so historical returns are optimistically biased. | High (inflates backtested edge) | **Documented.** Inherent without point-in-time constituents; flag in UI as a known limitation. Confidence: High. |
| B2 | **No slippage / liquidity model** — fills at exact OHLC prices. Indian mid/small-caps have real spread + impact. | Medium (overstates returns, esp. small-caps) | **Recommend** adding a slippage bps to `commission` or a fill-price haircut. Confidence: High. |
| B3 | **`dropna(inplace=True)` after `add_all_indicators`** dropped every row with a NaN in *any* of ~40 indicator columns; a sparse/flat-stock column could punch a **mid-series gap**, silently distorting bar timing. | Medium | **[FIXED]** now `dropna(subset=OHLCV)` (08_backtest.py + backtest/runner.py) — bars stay contiguous; strategies handle their own warm-up. `test_indicators_no_scattered_midseries_nan` guards core columns. |
| B4 | **SL/TP anchored to signal-bar close, not fill price** — `stop/tp` computed from bar *T* close but entry fills at bar *T+1* open. | Low (minor R:R mismatch) | Documented. |
| B5 | **Buy&Hold baseline** now spans the warm-up prefix (side-effect of B3 fix) — slightly different denominator, arguably more correct. | Low | Documented. |

---

## Priority 3 — Test Coverage (regression prevention)

**Added** `tests/test_production_audit.py` (5 tests) + existing `tests/test_smoke_score_indicators.py` (6) → **11 passing**.

| Test | Guards against |
|---|---|
| `test_no_lookahead_in_indicators` | **Any** future indicator re-leaking (the core finance-integrity invariant). |
| `test_indicators_no_scattered_midseries_nan` | A new indicator introducing mid-series NaNs that re-open the backtest-gap risk (B3). |
| `test_backtest_costs_realistic` | Cost constants drifting to unrealistic values. |
| `test_paper_trade_pnl_roundtrip` | P&L math regressions in `trade_store` (open→close→pnl, isolated temp DB). |
| `test_close_nonexistent_trade_is_safe` | Closing an invalid id raising. |
| `test_*` (smoke) | RSI bounds, MACD sign, score component caps, uptrend>downtrend. |

**Still uncovered (recommended next):** signal-generation thresholds in `analysis/score.py` (action banding), `PortfolioManager.mark_to_market` aggregate math end-to-end, and a one-ticker `Backtest(...).run()` smoke (slow — gate behind a marker).

---

## Priority 4 — Reliability

| Surface | State |
|---|---|
| **API / data-source failures** | Tiered fallback (Angel→Stooq→Yahoo) with per-tier timeouts (Stooq now 4 s). **Failures are swallowed** — see P1; add `log.warning` per tier. |
| **Missing data / empty frames** | `score_stock` returns an explicit `DATA_UNAVAILABLE` sentinel (good — surfaced, not silent). Indicator fns guard `len(df) < N`. |
| **Malformed responses** | Stooq HTML-vs-CSV guard present; Yahoo cookie/crumb path is the **most fragile** (recommend routing through Angel One when configured — already Tier 0). |
| **Invalid user input** | `_validate_ticker()` exists; portfolio CSV parsing guards per-row. |

---

## Priority 5 — Categorized Findings

| Sev | ID | File | Root cause | Impact | Fix | Confidence |
|---|---|---|---|---|---|---|
| **High** | B1 | `data/universe.py` (used by `backtest/`) | Static current membership = survivorship bias | Backtested returns optimistically biased | Use point-in-time constituents, or label results "survivors-only" in UI | High |
| **High** | P1-a | `analysis/portfolio_manager.py:291` | Swallowed parallel-score failure | Holding can vanish from portfolio total/P&L | **[FIXED]** logging; consider surfacing an explicit "N holdings failed to score" caption | High |
| **Medium** | B2 | `strategies/*`, `backtest/runner.py` | No slippage model | Overstates backtest returns (small-caps) | Add slippage bps to commission / fill haircut | High |
| **Medium** | B3 | `dashboard/pages/08_backtest.py`, `backtest/runner.py` | `dropna(any)` → possible mid-series gap | Distorted bar timing | **[FIXED]** `dropna(subset=OHLCV)` | High |
| **Medium** | P1-b | `data/fetcher.py`, `utils/live_price.py` | Swallowed per-tier fetch failures | Bad/stale data path invisible | Add `log.warning` per tier | High |
| **Medium** | P4-a | `data/fetcher.py` (Yahoo) | Cookie/crumb scraping is fragile | Live data can break silently | Prefer Angel One (Tier 0) when configured | Medium |
| **Low** | B4 | `strategies/*` | SL/TP off signal-bar close | Minor R:R mismatch | Anchor to fill price | High |
| **Low** | P1-c | `analysis/macro.py:146` | Dropped macro symbol | Incomplete macro page | Log it | High |
| **Low** | P1-d | `analysis/score.py:24` | `except AttributeError: pass` (stdout) | None (benign) | Leave | High |

### What was changed in this audit
1. **[FIXED]** Backtest data-prep gap risk → `dropna(subset=OHLCV)` (08_backtest.py, backtest/runner.py).
2. **[FIXED]** `trade_store.load_by_account` + `portfolio_manager` parallel-score → structured `logging.warning`.
3. **[ADDED]** `tests/test_production_audit.py` — anti-look-ahead + paper-trade + cost + NaN-invariant tests.

### Bottom line
The finance engine's **integrity is sound** — no look-ahead, correct execution timing, modeled costs, verified by a regression test. The production gaps are **operational**: silent data failures (now partly surfaced) and **survivorship + slippage** realism in the backtest, which inflate historical edge and should be labeled or modeled before any results are treated as live-tradeable.
