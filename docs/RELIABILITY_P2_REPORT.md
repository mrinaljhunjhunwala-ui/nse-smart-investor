# P2 — Reliability Cleanup Report (silent failures)

Repository-wide audit of silent failures — bare `except`, `except: pass`, and swallows that
`return None/[]/{}/continue` without a trace. Fixed by the four rules: **UI → caption · data
fetch → log warning · persistence → never silent · analytics → preserve traceability.**

## Counts
| | Silent swallows | Files |
|---|---|---|
| **Before** | **85** | 32 |
| **After** | **68** | 27 |
| **Fixed this pass** | **17** | persistence + live market-data path (the highest-risk "masks bad/missing data" category) |

## Fixed — by category & rule

### Persistence (rule: never silent) — DONE
| Site | Before | After |
|---|---|---|
| `trade_store.kv_set` | silent no-op on failure | returns `bool`, **logs ERROR** ("setting not persisted") |
| `trade_store.kv_get` | silent default | **logs warning**, returns default |
| `trade_store.fetch_open` | silent empty frame | **logs warning**, degrades to empty |
| `trade_store.load_by_account` | (already logged) | logs warning |
| `nav._persist_user_state` | `except: pass` | logs warning, sets `_persist_failed`, only advances snapshot on success |

Plus `validate_persistence()` + a sidebar status badge (P1) so storage failures are visible.

### Data fetch (rule: log warnings) — core market-data path DONE
| File | Sites | Change |
|---|---|---|
| `utils/live_price.py` | 6 | per-tier failures → `debug`; **all-tiers-failed → `warning`** ("no quote available") |
| `utils/vix.py` | 2 | per-URL gateway/crumb retries → `debug` |
| `utils/news.py` | 4 | RSS/fetch failures → `warning`; per-symbol fallback → `debug` |
| `data/fetcher.py` | 4 | YF consent/crumb retries + batch-worker + intraday filter → `debug` |

Failures are now diagnosable: a normal tier-fallback logs at `debug` (no noise), while a genuine
data-loss event (all sources exhausted) logs at `warning`.

## Remaining (68) — classified, with the applicable rule (tracked follow-up)
| Category | Count | Files | Rule / rationale |
|---|---|---|---|
| **Broker (optional)** | 13 | `data/angel_fetcher.py` | data → log. Failures already surface as `None`/`is_configured()` (the integration is optional); a module-logger pass is a low-risk follow-up. 1,200-line broker file — deferred from this pass to avoid unreviewed churn. |
| **UI display fallbacks** | ~23 | `chart_helpers.py` (10), pages (8), `nav.py` (7 remaining), `01_market_live.py` (3) | UI → caption. Cosmetic render fallbacks; most already render a caption/placeholder. |
| **Cache wrappers** | 6 | `dashboard/shared/cache.py` | data → log. `st.cache_*` wrappers around fetches. |
| **Benign parsers** | ~11 | `portfolio_risk` (2 date parsers), `events`, `valuation._clean`, `score`, `sector_strength`, `service`, `yahoo_fundamentals` (2), `portfolio_fit`, `macro` | analytics → traceability **already preserved**: these return `None`/`AnalyticResult(available=False, reason=…)` by contract — `None` is the correct, documented result of a bad parse, not a masked failure. |
| **Misc / scripts** | ~15 | `alerts/check_alerts` (3), `trading/*` (4), `strategies`, `optimizer`, `main` | offline/CLI paths; lower risk. |

## Validation
- Full suite **245 passing** (unchanged) after all P2 edits.
- The persistence and live market-data paths — the two places a silent failure would mislead an
  investor (lost trades, stale prices shown as live) — are no longer silent.

## Net
The **dangerous** silent failures (persistence data-loss, market-data masking) are fixed and
diagnosable. The remaining 68 are classified by category and rule: optional-broker catches, cosmetic
UI fallbacks, and benign parsers where `None` is the correct contract (analytics traceability is
preserved via `AnalyticResult.reason`). These are a documented, low-risk follow-up rather than blind
mass edits to a live app.
