# Production Hardening — Final Report (P1 · P2 · P3 · V1)

Moved the platform from *analytically strong* to *production-ready and validated*. **No new investor
features.** Four phases executed and pushed; full suite **245 passing** throughout.

## 1. What was fixed

### P1 — Production persistence
- `trade_store.validate_persistence()` — startup check of DATABASE_URL present / DB reachable / schema valid (`trades` + `user_kv`); never raises.
- **De-silenced the data-loss paths:** `kv_set` returns a bool + logs **ERROR** on failure (was a silent no-op that could lose the watchlist); `kv_get` / `fetch_open` / `load_by_account` log warnings.
- Sidebar now shows a live persistence badge: 🟢 persistent · 🟡 ephemeral (SQLite resets on redeploy) · 🔴 unreachable · ⚠️ last save failed. `_persist_user_state` only advances its snapshot on a successful write.
- **`DEPLOYMENT_CHECKLIST.md`** — what persists (trades/watchlist → Postgres; `portfolio.csv` committed; uploads session-only), 5-min Neon/Supabase setup, pre-deploy checklist.

### P2 — Reliability cleanup
- Silent swallows **85 → 68**. Fixed the highest-risk categories by rule: **persistence never silent** (P1) and **data fetch logs** — `utils/live_price` (debug per-tier, **warning when all tiers fail**), `utils/vix`, `utils/news`, `data/fetcher` now log instead of swallowing.
- Remaining 68 classified by category + rule (broker-optional, cosmetic UI that already captions, cache wrappers, benign parsers where `None` is the documented contract) in `RELIABILITY_P2_REPORT.md`.

### P3 — `globals().update()` removal
- Removed the dynamic shared-namespace injection from **all 17 pages**, replaced with **explicit imports** (AST-derived, only the 6–24 names each page actually uses). Verified: generator `missing=[]`, an independent AST recheck found **0 unresolved shared names**, all pages compile, AppTest of transformed pages → `exception=None`, **0** `globals().update()` calls remain. `GLOBALS_REMOVAL_P3_REPORT.md`.

### V1 — NSE universe validation
- Ran E1-v2 over **62 real NSE stocks** (0 fetch errors). Guards fire appropriately (insurers, cyclicals, no-growth, data gaps), financials are sensible and differentiated with **zero false leverage flags**, supportive postures are conservative (15%) and well-targeted, and the engine discriminates meaningfully (8 distinct postures, sensible within-sector spread). `V1_NSE_VALIDATION_REPORT.md`.

## 2. What remains
- **P2 tail (68 swallows):** optional-broker `angel_fetcher` (13 — a module-logger pass), cosmetic UI fallbacks (~23, most already caption), cache wrappers (6), and benign parsers (~11 where `None` is correct). Low risk; tracked.
- **Persistence depends on the operator** setting `DATABASE_URL` — the app now *surfaces* SQLite ephemerality loudly, but cannot persist without a Postgres URL. User-uploaded portfolios remain session-only by design.
- **Valuation refinement candidate (V1):** split regulated utilities (POWERGRID-type) from commodity-energy in the cyclical set to avoid a (conservative) over-refusal. Minor; not a correctness bug.
- **Yahoo coverage** still gaps on some renamed/SME tickers (LTIM, DEEPAKNITR 404 → correctly refused) — a data-source limit, not an engine fault.

## 3. Updated score
| Dimension | Before this pass | After |
|---|---|---|
| Analytics correctness | 9/10 | 9/10 (unchanged — validated in the wild) |
| Persistence robustness | 4/10 (silent SQLite, lossy kv) | **8/10** (validated, surfaced, de-silenced) |
| Reliability / observability | 5/10 (85 silent swallows) | **7/10** (critical paths log; rest classified) |
| Code hygiene | 5/10 (globals() pollution ×17) | **8/10** (explicit imports, greppable deps) |
| Production validation | 3/10 (untested on universe) | **8/10** (62-stock live validation) |
| **Overall production-readiness** | **~5.5/10** | **~8/10** |

## 4. Top 5 highest-ROI next steps (reliability/validation, not features)
1. **Finish the P2 tail with a logging pass** — add a module logger to `angel_fetcher` (13) + the cache wrappers (6) so broker/cache failures are diagnosable. Small, completes the "no silent failures" goal. *(High ROI, low effort.)*
2. **Provision a managed Postgres + run the persistence acceptance test** from `DEPLOYMENT_CHECKLIST.md` (open trade → redeploy → still present; add watchlist → redeploy → still present). Turns "persistence-capable" into "persistence-proven". *(High ROI.)*
3. **Add a tiny CI smoke test** that AppTest-runs each of the 17 pages headless and asserts `exception is None` (offline-safe pages first) — locks in the P3 win and catches future page regressions. *(Medium effort, high durability.)*
4. **Promote V1 into a repeatable regression harness** (a committed `tools/validate_valuation.py` + a golden snapshot of the 62-stock posture distribution) so valuation drift is caught automatically. *(Medium ROI.)*
5. **Refine the cyclical set** (utilities vs commodity-energy) flagged by V1, with 2–3 targeted tests — removes the only observed conservative over-refusal. *(Low effort, sharpens accuracy.)*

## STOP
Per the stop condition, NOT implemented: NIM, GNPA, CASA, EODHD, historical valuation bands,
prediction tracking, or any new analytics feature. This pass was reliability, persistence and
validation only.
