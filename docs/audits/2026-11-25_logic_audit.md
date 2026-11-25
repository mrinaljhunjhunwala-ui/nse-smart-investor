# Logic & structure audit — 2026-11-25 (main @ dfa71cc)

## Executive summary
1. The hard rules hold: no `streamlit` import in `analysis/` or `strategies/`, no extra `set_page_config` call, the composite score stays 40+25+15+10 = 90 with no candlestick points, and no copy promises an outcome.
2. Paper Trades **does persist to Postgres**: the page goes through `trade_utils` → `trade_store` and ignores its `path="trades.db"` argument. `trading/paper_trader.py` (local SQLite) is only used by the `main.py` command line, and it shares the `trades.db` file and `trades` table name with trade_store's SQLite fallback.
3. Top-severity logic issues: Quality Watch shows ROCE and D/E for banks (breaks rule 3); the same stock reads **BUY** on the dashboard but **WATCH** in Telegram when it scores 65–69; per-tag calibration ranks tags by raw "return > 0" without the call's direction.
4. The biggest reliability and cost risk: each rerun of the Calibration page runs a network backfill and reads the full ledger (`SELECT v.*`, up to 1M rows) about 8 times with no cache. That is the traffic pattern that used up Neon's transfer quota, and it now hits the Oracle VM.
5. Fast test suite: see "Test run" at the bottom. Ledger, backfill, holiday and alert-dedupe logic were checked and are sound (session-aware horizons, IST last closed session, a direction-aware live scorecard, alert state merged in KV).

## Findings (by severity)

### P0 — wrong call or data loss
None confirmed. One case comes close (F6): it is latent today because no UI path opens a short trade.

### P1 — misleading

**F1. Quality Watch shows ROCE and Debt/Equity for banks, NBFCs and insurers (breaks rule 3).**
`dashboard/pages/09_quality_watch.py:531-534` (Key Ratios metrics) and `:575-578` (Peers table) render `r.roce` and `r.debt_to_equity` with no check on `is_financial`. The score at `:193-201` is sector-aware, but the display is not. Example: HDFCBANK.NS shows a "ROCE" and a high "Debt/Equity", and the Banks peer table lists ROCE and D/E for every lender. Compare `06_my_portfolio.py:1540-1546`, which blanks both for lenders, and `05_analyze_stock.py:311-312`, which uses `roce_meaningful` / `leverage_warning_applies`.

**F2. The same stock reads BUY on the dashboard and WATCH in alerts when it scores 65–69.**
`analysis/score.py:1451-1453` maps a score of 65 or more to "BUY". `alerts/check_alerts.py:1397,1410` (`_WATCH_FLOOR = 70`, `_floor_word`) relabels BUY / STRONG BUY under 70 as WATCH in every Telegram and Gmail message (owner decision, 15 Nov). The dashboard cards do not apply that floor: `01_command_centre.py:816-817` and `04_tomorrow_watchlist.py:712` print `_display_label(action)`. A stock at 67/90 therefore shows "BUY" on Command Centre and "WATCH" in the digest. Move the floor into `analysis/action_labels.py` so both surfaces share one rule.

**F3. Per-tag and per-subsystem calibration ignore which way the call pointed.**
`analysis/verdict_ledger.py:1218-1243` (`_aggregate`) defines a win as `ret > 0` or `alpha > 0` for every row. `tag_calibration` (`:1261-1298`) pools rows of every verdict and sorts by `wilson_lower_win`. A tag that fires mostly on AVOID calls whose stocks then rallied (wrong calls) ranks as a winning tag. `calibration_by(group_col=<subsystem>)` (`:1100`, used at `10_verdict_calibration.py:654`) mixes BUY and AVOID rows the same way. Only `live_scorecard` and `results_by_list` apply `_VERDICT_DIRECTION`. The per-verdict table is less affected because each row is a single verdict, but its AVOID row's "Win %" means the call was wrong, and the caption at `10_verdict_calibration.py:457-465` does not say so.

**F4. Calibration page: a network backfill plus about 8 full-ledger reads on every rerun, with no cache.**
`10_verdict_calibration.py:177-180` runs `backfill_returns(max_rows=200)`, which fetches price history over the network, on every script rerun, including every slider or select change. After that the page calls `load_ledger(limit=1_000_000)` (`:204`), `evaluate_decision_rule` (twice, `:221`, `:408`), `live_scorecard` (`:366`), `calibration_by` (twice, `:516`, `:654`), `regime_calibration` (`:565`) and `shadow_pnl` (`:727`). Each of these calls `load_ledger(limit=_FULL_LEDGER_LIMIT)` itself (`verdict_ledger.py:1061,1110,1310,1356`), running `SELECT v.* … LEFT JOIN verdict_forward_returns` with no `st.cache_data`. As the ledger grows (about 100–130 rows a day), every interaction moves the whole table several times over the public internet to the VM. That is the transfer pattern that locked Neon, and it slows the page. Fix: read the ledger once per rerun (or `st.cache_data(ttl=300)` in `dashboard/shared/cache.py`), pass the frame into the functions, and gate the backfill behind a button or a once-per-session flag, since the nightly `tools/backfill_ledger.py` already does the work.

**F5. A BUY alert can go out with no stop.**
`alerts/check_alerts.py:95-103` (`_stock_line`) silently drops `stop` when it is None, `""` or 0. `_verdict_pick_lines` (`:897-906`) passes `b.get("sl")` straight through. A snapshot row missing `sl`, or one from an old snapshot schema, sends "BUY SYM ₹x · target ₹y" with no stop, which breaks rule 1 ("a stop on every BUY"). Nothing asserts that a BUY has a stop. Skip or downgrade such rows instead.

**F6. Auto-close treats every open paper trade as a long position (latent).**
`dashboard/shared/trade_utils.py:1139-1145` closes at the target when `cur >= tp` and at the stop when `cur <= sl`, whatever `action` says. `trade_store.open_trade` accepts SELL/SHORT (`trade_store.py:394-409`), and `paper_exits.find_exit` handles shorts. For a short (tp below entry), `cur >= tp` is true on the first tick, so the trade closes at once as "target reached" at `tp` and books a fictitious profit. Today `paper_open_trade` (`trade_utils.py:285-291`) never passes `action`, so the app only opens longs. Shorts only arrive through merged or old rows or the API, which keeps this P1 instead of P0. Read `r["action"]` and mirror the comparisons.

**F7. Calibration and Paper Trades copy still tells the owner to use Neon.**
`10_verdict_calibration.py:168-173` and `07_paper_trades.py:106` say "Neon/Supabase free tier". Neon is retired and the owner's rule is Oracle Always Free only. The text could send a future fix back to the provider that locked the database.

### P2 — quality

**F8. `trading/paper_trader.py` is a second paper-trade engine on the same file.**
`paper_trader.py:28` uses `DB_FILE = "trades.db"` with its own `CREATE TABLE trades` (no `account` column). `trade_store.py:42` uses `_SQLITE_PATH = "trades.db"` for local and fallback runs. Run locally, whichever process creates the table first fixes its schema. `PaperTrader._load_state` (`:112-131`) then counts the app's "My Account" trades against CLI capital, and CLI trades never reach Postgres. Its only caller is `main.py:248-302`. Point it at `trade_store`, or retire it.

**F9. A second, network-fetching NSE holiday calendar.**
`dashboard/shared/trade_utils.py:125-188` (`_nse_holidays`) calls `nseindia.com/api/holiday-master` (NSE returns 403 to cloud runners, so this is a 5 s timeout once per process per day). It keys its cache on `datetime.date.today()`, which is UTC on Streamlit Cloud, so between 00:00 and 05:30 IST it reads the previous day's entry. It then writes the result to KV `nse_holidays` (under the default user, not `_system`). `utils/nse_holidays.py` is the canonical calendar and already covers 2027 provisionally. Use `is_trading_day` instead.

**F10. `valid_until` is stamped with server-local time.**
`analysis/score.py:1865` uses `datetime.now()` (UTC on Cloud and Actions), and `CompositeScore.timestamp` at `:353` does the same. A score computed between 00:00 and 05:30 IST gets a "fresh until" date one day early, and timestamps shown as "as of" are 5.5 h behind IST unless converted. Use the IST helper that `verdict_ledger._now_ist` and `score._now_ist_naive` already provide.

**F11. The target window doesn't match the horizon label.**
`score.py:1344` sizes every target from a fixed 10-session expected move (`_HOLD_DAYS = 10`). `_pick_horizon` (`:1412-1418`) can label the same pick "Trend hold (4–8 weeks)" with a 56-day `valid_until`. For trend-hold picks the target is about a two-week move shown against an eight-week window, so the R:R is understated and the target is reached early.

**F12. `_find_bar` takes the first close on or after the target date.**
`analysis/verdict_ledger.py:559-575`: when the provider is missing the exact target session (a gap in Yahoo history), the return silently uses a later session's close. The horizon stretches and nothing records it. Rare, but it biases 1-day and 5-day returns. Require `idx_date == target`, or allow at most one session of slip.

**F13. Score text says "/90" even when the score can reach 100.**
With `NSE_USE_POSITIONING_PILLAR` on, F&O names can score up to 100 (`score.py:1848`), but alerts (`check_alerts.py:903-905`) and cards (`01_command_centre.py:816`, `04_tomorrow_watchlist.py:712`) print `/90`, and grades and actions stay calibrated on 0–90. The flag is off by default, so this is latent; note it before turning the flag on.

**F14. Dead `path=` arguments.**
Every paper helper in `trade_utils.py:202-300` (`load_trades_by_account`, `paper_open_trade`, `paper_close_trade`, `_auto_close_breached`, …) takes `path: str = "trades.db"` and ignores it. A reader assumes the page writes to SQLite (this audit's own question). Remove the arguments.

**F15. Oversized modules with unclear ownership.**
`analysis/score.py` (2,194 lines), `alerts/check_alerts.py` (2,497), `analysis/verdict_ledger.py` (1,878), `dashboard/pages/05_analyze_stock.py` (2,825) and `06_my_portfolio.py` (1,821). `dashboard/shared/cache.py` holds business logic (snapshots, momentum ranking, the TW fallback scan) well beyond caching. `trade_utils.py` mixes persistence wrappers, market hours, holidays, auto-close and display labels (`_display_label` re-exports `action_labels`). Suggested splits: `alerts/verdicts.py`, `alerts/state.py`; `dashboard/shared/paper.py`, separate from labels and market hours.

**F16. The positioning-pillar code path ships but is never exercised in production.**
`score.py:1172-1267,1824-1848` is about 120 lines behind an env flag that is off by default, and the "neutral midpoint" placeholders mean it would score F&O names on assumed data. Keep it but mark it experimental, or remove it until its data feed exists.

## Checked and found sound (no finding)
- Rule greps: no `import streamlit` in `analysis/` or `strategies/`; the only `set_page_config` mentions outside app.py and design.py are comments; no hard-coded sector strings in pages; no candlestick points in the composite (patterns appear only in the narrative, `score.py:1633-1649`); no outcome-promising copy.
- Composite caps: each pillar is capped at 40, 25, 15 and 10, and the total is clamped to 0–90 (`score.py:519,755,1011,1164,1850`). When live-price re-anchoring moves the entry, it shifts SL and TP by the same distances and rejects live prices more than `MAX_LIVE_GAP` away (`score.py:2159-2187`).
- Ledger: horizons are counted in NSE sessions (`horizon_target_date` with the holiday CustomBusinessDay); `last_closed_session` in IST avoids reading an intraday bar as a settled return; `_session_close` refuses to use a later close for the entry; inserts are idempotent through UNIQUE plus ON CONFLICT; the Wilson bound is correct; the live scorecard is direction-aware and grouped in non-overlapping blocks.
- Paper Trades → `trade_store` → Postgres. In-app SQLite is used only when DATABASE_URL is absent, and then the app warns; the `STORE_FALLBACK_PATH` fallback is enabled only for GitHub jobs.
- Alerts: dedupe state is unioned in KV across overlapping runs (`check_alerts.py:233-289`); `--force` doesn't stamp; caps apply per run and per day, with a separate allowance for names new since the open.
- Tomorrow's Watchlist: the snapshot is used only when `_tw_snapshot_current` holds, otherwise a live scan runs; stale-while-revalidate is labelled on the page (`04_tomorrow_watchlist.py:381`).
- The holiday calendar covers 2025, 2026 and 2027 (2027 provisional) and logs a warning for any year it doesn't cover.

## Test run
`py -m pytest -m "not slow" -q -x --basetemp "D:\Kashti Claude\_tmp\audit_logic"`: **918 passed, 6 deselected, 1 error** (6 min 52 s; `-x` stopped there, so tests after it did not run).
The error, `tests/test_merge_databases.py::test_dry_run_writes_nothing_but_counts_exactly`, is environmental, not a code regression. The laptop's `TEST_DATABASE_URL` still points at the retired Neon project (`ep-spring-fog-…neon.tech`), which answers "exceeded the quota". The real-Postgres tests skip only when the variable is *unset*. Fix: unset `TEST_DATABASE_URL` locally, or point it at a scratch database. Never point it at the Oracle production database: these tests create and drop schemas. Tests that come after this one alphabetically were not run under `-x`.
