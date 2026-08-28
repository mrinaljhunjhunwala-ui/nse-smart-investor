# Operational Hardening — Final Report (CI, regression, reliability tail, deployment proof)

Converts the platform from *production-ready* to *production-proven*: automated CI, offline
valuation-regression protection, completion of the reliability tail, a gated backtest smoke, and a
deployment acceptance runbook. **No new investor features.** Default suite **275 passing** (+1 gated
slow); CI-equivalent (`-m "not slow"`) is the green bar.

## 1. Files modified
| File | Change |
|---|---|
| `pytest.ini` | **NEW** — markers (`smoke`, `slow`, `network`); `addopts = -m "not slow"` (gates the backtest by default) |
| `.github/workflows/ci.yml` | **NEW** — runs `pytest -m "not slow"` on push/PR to main |
| `tests/test_pages_smoke.py` | **NEW** — 17-page AppTest smoke (network-blocked) |
| `tests/test_backtest_smoke.py` | **NEW** — gated end-to-end backtest smoke (`slow`) |
| `tests/test_valuation_golden_snapshot.py` | rewritten — **offline replay regression** |
| `tools/validate_valuation.py` | captures `ValuationInputs` per ticker for offline replay |
| `data/valuation_golden_snapshot.json` | regenerated with captured inputs |
| `analysis/fundamentals/valuation_decision.py` | minimal refactor: `build_valuation_inputs()` split out (testability) |
| `dashboard/pages/02_command_centre.py` | **bug fix** — restored 2 module imports the P3 transform dropped |
| `data/angel_fetcher.py` | logger + 17 swallows tagged |
| `dashboard/shared/cache.py` | logger + 13 swallows tagged |
| `dashboard/shared/trade_utils.py` | logger + 5 swallows tagged (persistence read → warning) |
| `PERSISTENCE_ACCEPTANCE.md` | **NEW** — acceptance runbook + operator checklist |

## 2. Tests added
- **Page smoke (Part 1):** 17 parametrized page-load tests + a "17 pages present" guard. Network-blocked (fail-fast sockets) so pages take their graceful degraded path → deterministic & CI-safe. **Runtime ≈ 34 s** for all 17.
- **Valuation regression (Part 2):** the snapshot now stores each ticker's captured `ValuationInputs`; the offline test **replays them through the pure `assess()`** and fails on any posture/confidence/branch/guard drift — no network. Plus structure + V1 spot-checks (6 tests).
- **Cyclical-split (Part 1):** 6 tests (POWERGRID before/after, commodity still trough-refused, peak still fires on commodity, regulated utility at peak not refused, low-growth utility → Reasonable, detection).
- **Backtest smoke (Part 4):** 1 `slow` test — full path on one ticker, validates engine import → runner executes → output schema. **Runtime ≈ 15 s**, excluded from CI.

> **The page smoke immediately earned its keep:** it caught a real **P3 regression** — `02_command_centre.py` referenced `get_universe` and `_ao_is_configured`, two module-level imports that sat *inside* the old `globals().update()` block and were dropped by the P3 transform (they aren't shared-module names, so the AST pass didn't re-add them). Both restored.

## 3. CI additions
- `.github/workflows/ci.yml`: checkout → Python 3.11 (pip cache) → `pip install -r requirements.txt` → **`pytest -m "not slow"`** on every push/PR to `main`. Covers the offline unit/analytics tests, the 17-page smoke (network-blocked), and the valuation replay regression. The slow backtest and the live valuation diagnostic are excluded.
- Intentional-update workflow preserved: regenerate the golden snapshot with `python tools/validate_valuation.py --update` and review the diff; CI then enforces it.

## 4. Reliability counts (silent swallows)
| Stage | Count | Files |
|---|---|---|
| Original (pre-P2) | 85 | 32 |
| After P2 | 68 | 27 |
| **After P3 (this pass)** | **46** | 23 |

This pass de-silenced **angel_fetcher (17), cache (13), trade_utils (5)** — adding module loggers and
tagging each swallow with its enclosing function (reviewed, line-targeted; intended fallback behaviour
preserved, every failure path now diagnosable). The remaining 46 are **UI render fallbacks**
(`chart_helpers` 10, `nav` 7, pages — most already show captions/placeholders) and **benign parsers**
(date/number parsers where `None` is the correct contract; analytics traceability preserved via
`AnalyticResult.reason`).

## 5. Updated production-readiness assessment
| Dimension | Prior | Now |
|---|---|---|
| Persistence robustness | 8/10 | 8/10 (+ acceptance runbook → *provable*) |
| Reliability / observability | 7/10 | **8.5/10** (angel/cache/trade_utils de-silenced; tail classified) |
| Regression protection | 5/10 | **9/10** (offline replay regression + CI) |
| Page/runtime safety | 6/10 | **9/10** (17-page CI smoke; caught a live P3 bug) |
| Deployment confidence | 6/10 | **8/10** (CI gate + acceptance checklist) |
| **Overall** | **~8/10** | **~8.7/10** |

## 6. Remaining known gaps
- **Persistence is provable but not yet proven on a live deploy** — the acceptance test in
  `PERSISTENCE_ACCEPTANCE.md` requires the operator to set `DATABASE_URL` and run the redeploy check
  (no infra provisioned here, by instruction).
- **Reliability tail (46):** UI render fallbacks (best converted to explicit captions, page-by-page)
  and benign parsers (correct as-is). Low risk; tracked.
- **CI network tests:** one integration test (`test_build_fit_inputs_with_injected_loader`) attempts a
  Nifty beta fetch and degrades gracefully — adds ~30 s in CI but is deterministic in outcome. Could be
  marked `network` later if runner Yahoo access proves flaky.
- **Page smoke covers load-time only** — it asserts no uncaught exception on render with data blocked;
  it does not exercise interactive widget callbacks.

## Net
The platform now has an automated CI gate, deterministic offline regression protection for the
valuation engine, a de-silenced broker/cache/persistence layer, a gated end-to-end backtest smoke, and
a concrete deployment-acceptance runbook — and the new page smoke already caught and fixed a real
regression on its first run.
