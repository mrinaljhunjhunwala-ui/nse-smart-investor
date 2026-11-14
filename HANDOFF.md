# Latest — 2026-11-07 · Actions unblocked, alerts widened, keep-awake (read this first)

This section is the running memory between sessions; older sections below are history.

## What happened
- **20-session catalyst replay, 15 Oct – 13 Nov (14 Nov, run 43610018434):** 1,009 universe names
  with classified filings; 184 positive calls. Same-day opening-range plan on 15-minute bars: 94
  entered, 49 profitable, 3 target / 8 stop, average +0.1R, entry→close +0.2% (about breakeven
  before the 0.25% round trip). Held from the open to the latest close: +3.1%, **3.3 pts behind the
  Nifty**, and no better than the 403 names the engine only watched (+3.4%). Strong year-on-year
  results +3.0% vs weak +4.2%: the results score did not predict the move. The one-week +1.3 pts
  was noise. **Decision:** positive reads are sent as `WATCH` (`catalyst_alerts.CALL_WORD`), not
  BUY, with a footer saying so; "why it moved" and the Friday-card record stay. Do not switch back
  to BUY until the weekly record shows an edge over a full results season (Jan–Feb 2027).
- **Follow-ups after #347 (14 Nov):** Friday card gains a "Results & news BUY calls" section
  (`catalyst_alerts.week_record` grades the week's stored BUY reads with `catalysts.grade_picks`
  on daily bars). `score._get_bench_cached` retries a failed `^NSEI` fetch after 30 s (was held for
  5 min, longer than a whole scan, so every stock scored without relative strength). Live
  re-anchoring of entry / stop / target is skipped when the quote is over 25% from the last close
  (`score.live_price_plausible`). Golden-snapshot tests unchanged. Still open from the audit: Yahoo
  live-quote age unchecked; stale Yahoo frame not patched from bhavcopy; `date.today()` in UTC in
  `_period_to_dates`; `_get_token` first-hit fallback; page copy (My Portfolio) still descriptive.
  **Owner, cron-job.org:** provider canary and universe refresh have only manual runs; weekly and
  momentum digests never fired. Replay on demand: Actions → Provider Canary → Run workflow →
  `replay_sessions` = 5 (or more).
- **Catalyst replay, 6–13 Nov (14 Nov; `scripts/catalyst_replay.py`, run from `provider_canary.yml`
  with input `replay_sessions`, stored in KV `catalyst_replay:<date>`):** 238 universe names with
  classified filings over 5 sessions. The engine flagged CUPID (12 Nov, +8.7% that day), KALYANKJIL
  (11 Nov), MSTCLTD (+20%), SYMBIOTEC, DIVISLAB, SAILIFE as BUY. BUY list (40): open→close −0.2%,
  open→latest +1.6% (+1.3 pts vs Nifty). On 15-minute bars the same-day opening-range plan lost:
  23 entered, 8 profitable, average −0.2R, entry→close −0.5%, held to latest +1.2%. Negative
  (SELL) reads (17) bounced +5.2% from the open. Strong year-on-year results alone did not predict
  the day (79 names, 33 up). **Changes made from this:** `catalysts.INTRADAY_PLANS = False` (plans
  are a 2–5 session hold, stop 1×ATR under the trigger and never tighter than the opening range,
  first target 2R); alerts print negative reads as `AVOID` with no trade levels. One week in one
  results season: do not tune further on it; re-run the replay monthly and add the catalyst record
  to the Friday card (`catalysts.grade_picks` exists, not yet shown anywhere).
- **Owner decisions (13–14 Nov):** direct BUY / SELL / HOLD wording (CLAUDE.md rule 1 rewritten;
  labels in `analysis/action_labels.py`); shorter Telegram messages; results / news driven calls;
  "why did the top movers move"; reliability over features.
- **Telegram format (14 Nov):** every builder in `alerts/check_alerts.py` = title + time, then
  `ACTION  SYMBOL  ₹price · stop · target` per stock, one footer, ≤15 lines (weekly card ≤20).
  Portfolio Posture groups SELL → STOP HIT → TRIM → ADD → HOLD (`POSTURE_DISPLAY`), no raw tags.
  `tests/test_alert_copy_no_advice.py` now guards THIS format (`_assert_descriptive` kept as alias).
  Not yet aligned: page copy such as `05_my_portfolio.py` "Weakening / Broken Trend".
- **Catalyst engine (14 Nov):** `analysis/catalysts.py` (pure; rule table in its docstring),
  `data/nse_announcements.py` (announcements / results filed / quarterly figures / pre-open; NSE →
  RSS → BSE; never raises), `alerts/catalyst_alerts.py`. Modes: `--mode=catalyst-preopen` (step in
  `warm-preopen-scan.yml`), live check inside the default 15-min run (`_catalyst_live`, cap 6/day),
  `--mode=why-moved` (step in `warm_tomorrow_watchlist.yml`). Reads go to KV `catalyst_picks:<date>`
  (`_system`), **never** to `verdict_log` (DECISION_RULE pools every ledger source). "Surprise" is
  this quarter vs the year-ago quarter (no consensus data). `grade_picks` exists but nothing shows
  the catalyst record yet — next: a Friday-card section and a page view.
- **Reliability (14 Nov):** Angel quote / batch / depth calls feed the shared breaker; `fetch_single`
  holds a short (first bar >40% of span late) or stale (≥2 sessions) Angel/Stooq frame and lets
  Yahoo win if better; scans log and persist `scan_health` (dropped count / reasons); warmers refuse
  to overwrite a snapshot when <50% of the universe scored; NaN / 0 live quotes fall through;
  Telegram / Gmail / scan timestamps are real IST. **Found, not fixed:** (1) a failed `^NSEI` fetch
  is cached 5 min so a whole scan scores without relative strength (touches scoring); (2) live
  re-anchor of entry / stop / target has no sanity bound and `_get_token` falls back to the first
  `searchScrip` hit; (3) Yahoo live quote age unchecked; (4) stale Yahoo frame not patched from
  bhavcopy; (5) `date.today()` in UTC in `_period_to_dates`. Not audited: `utils/indicators.py`
  short-frame maths, `trade_store.py` beyond `kv_set`, option-chain / delivery / FII loaders.
- **Why winners were missed (week of 9 Nov):** PNB was sent as STRONG BUY on 9 Nov at ₹127.29 (buried
  in jargon); KMEW on 12 Nov; DHANBANK was flagged TRIM on 10 Nov before rising; KALYANKJIL / ANURAS
  were on in-app lists but not found in the Telegram runs checked (daily cap of 10).
- **Week of 9–13 Nov review (13 Nov, `claude/festive-fermi-150awb`):** Friday card: Top Picks 86
  names, average +1.1% / +1.1 pts vs Nifty but only 44 of 86 ahead; watchlist bullish 53 of 111
  ahead; bearish setups rose +0.5% on average (20 of 45 lagged). Averages were carried by a few
  bank / jewellery names. Shipped: (1) **AO-PARTIAL** — `angel_fetcher._fetch_historical_windows`
  returned only the windows that answered, so "older window 403 + recent 200" gave ~27 bars of a 2y
  request as if complete (Yahoo never tried; scans dropped the stock as DATA_UNAVAILABLE; Portfolio
  Posture said "very recent listing" for PFC / VEDL / XCHANGING). An HTTP error on any window now
  fails the fetch, and the breaker count is no longer reset by the later 200. (2) Friday card: Top
  Picks gets a median line and a "By sector, vs the Nifty" split (`week_scorecard(sector_of=...)`,
  sectors with ≥3 names). Still open: `get_full_quote` has no breaker / failure count, so every
  scored stock pays one failing Angel quote call from GitHub runners; `provider_canary.yml` and
  `refresh_universe.yml` have **zero runs** although the cron-job.org to-dos below are ticked;
  `market-digest.yml` only ever ran `intraday-watchlist` this week (no weekly-digest / momentum).
  `tests/test_angel_one_layout.py::test_posture_codes_render_as_descriptive_labels` fails offline
  on `main` too (3-min network wait) — not caused by this change.
- **Fundamental score (10 Nov, `feat/fundamental-score`):** `analysis/fundamental_score.py`
  (pure) — Piotroski F-score 60 pts (scaled to tests that ran; ≥ ⅔ of applicable tests needed) +
  growth recency 20 + valuation sanity 20 (PEG/PE; lenders P/B × ROE), Altman Z with original
  1968 coefficients (distress caps at 35; lenders skip Z and LT-debt / current-ratio / gross-margin
  tests via `sector_classification`). Feeds `business_gate.assess_business(fundamental_score=...)`
  in place of the quality score (None → old path). Analyze Stock hero shows "Fundamentals NN/100 ·
  F-score · Z" beside the Trend score; Fundamentals tab has the check table. `combine()` / verdict
  ledger still get the old quality score (unchanged); Quality Watch keeps `compute_quality_score`.
  New schema fields `BalanceSheet.retained_earnings` + `RatioSnapshot.market_cap` are mapped from
  Yahoo only — Screener / filing providers don't fill them, so Z is "n/a" on those sources.
- **Business gate on the Analyze Stock headline (10 Nov, `feat/business-gate-headline`):** the hero now
  reads **Business** first (`analysis/business_gate.py: assess_business` → PASS / CAUTION / FAIL /
  INSUFFICIENT_DATA, rule table in its docstring, lender routing via `sector_classification`), then
  **Trend** (score band); tone = worse of the two, FAIL demotes trend to "timing only". Same inputs as
  `final_verdict.combine`. Fixed: quality score 0 was dropped; flag sentiment mapping (`negative`/`neutral`
  never matched `red`/`amber`, so every flag read green); cold render now reads stored flags (KV, no
  scrape) or says "not yet checked"; `growth-lens-off` is a not-applicable guard with its own explanation.
- **9 Oct → 3 Nov:** every scheduled job failed in ~3 s with no runner (GitHub Actions minutes /
  billing lock). The owner made the repo public (free Actions minutes); jobs run again since 4 Nov.
  The verdict ledger has a **~3½-week logging gap** (no warm Top Picks runs in that window).
- **Merged this session:** #321 data reliability (yfinance 1.x pin, holiday/placeholder bar cleaning,
  NSE FII/DII fallback, F&O list from NSE) · #322 after-close **Tomorrow's Watchlist on Telegram**
  (`check_alerts --mode=tomorrow-watchlist`, sent by `warm_tomorrow_watchlist.yml`), BUY/STRONG BUY
  alerts read the full `all_scored_snapshot` (max 8 new per run), `^` index symbols skip Angel One ·
  #323 `no_recent_bars` (>3 sessions without a bar) joins the list exclusions, so suspended names stay
  off Top Picks / Tomorrow's Watchlist / Momentum Leaders · #324/#325 `keep-streamlit-awake.yml`
  (Playwright visit every 4 h; app made public 7 Nov; first run green).
- Two tests had fixed dates that aged out (`test_edge_flags` renderer, `test_momentum_leaders`
  frames); both now build frames ending today. Watch for more date-pinned fixtures.
  **DECISION_RULE sample cutover (2026-11-10):** only Analyze Stock rows (`source="analyze_page"`) carry quality score + flags into `combine()`; from this merge those rows can drop a tier or be vetoed (quality 0, red/amber flag) where before they could not. DECISION_RULE / DECISION_RULE_RISING pool every source and are NOT changed; treat this date as a declared process change when reading the December verdict (Top Picks / Tomorrow's Watchlist logging is unaffected, so WATCHLIST_RULE is clean).

- **Added 7 Nov:** a plain-language "Is the model working?" card with two progress bars at the top of
  Verdict Calibration (`verdict_ledger.plain_summary`), and a Friday 🧾 weekly report card on
  Telegram (`check_alerts --mode=weekly-scorecard`, sent from `warm_tomorrow_watchlist.yml`).

- **PIN on holdings (8 Nov):** My Portfolio uses the same owner PIN as Angel One (`[angel_one] page_pin`
  or `ANGEL_PAGE_PIN`; fails closed). The sidebar Portfolio Quick View and Analyze Stock's position /
  Portfolio Fit only read holdings after that unlock (`pin_gate.holdings_unlocked`). Paper Trades,
  Watchlist and Journal stay open by the owner's choice.

- **Official-filing fundamentals (9 Nov):** Analyze Stock → Fundamentals has a source picker:
  Auto (Yahoo + Screener) · Exchange filing (NSE annual-results XBRL, fetched on demand by
  `data/nse_filings_xbrl.py`) · ROC filing (owner uploads the MCA AOC-4 XBRL; MCA21 needs login +
  fee, so no auto-fetch). Parsed by `analysis/fundamentals/xbrl_filing.py`, stored in KV
  `filing_fund:<source>:<SYM>`, served by `providers/filing_fundamentals.py` as the primary provider
  with Yahoo/Screener filling gaps. Only that tab uses the picker; scoring/valuation stay on Auto.

- **Fundamentals cascade + long-lens data gate (10 Nov, `feat/fundamentals-cascade`):** Auto
  (`default_service`) is now Yahoo → Screener → stored exchange filing → stored ROC filing, later
  ones filling only gaps, so a fetched/uploaded filing helps Valuation and Final Verdict too. If latest
  revenue / net income / total equity are still missing (`missing_core_fields`), the NSE XBRL is
  fetched once per symbol per day (KV `filing_autofetch:<SYM>`, 15 s cap, 30-min breaker when NSE is
  unreachable, never raises); `NSE_AUTO_FILING_FETCH=0` turns it off (tests run with it off). Analyze
  Stock shows "Sources: revenue — Yahoo · equity — NSE filing · P/B — not found in any source" on the
  Fundamentals tab and under the Valuation card. The LONG lens returns `INSUFFICIENT_DATA` ("Not
  enough fundamental data for a long-term read") when fundamentals are missing (valuation guard H3 or
  no statements at all) and there is no quality score; not logged to the verdict ledger. BSE skipped
  (no XBRL list endpoint could be pinned offline).

- **Pages simplified, 19 → 14 (10 Nov, owner-approved):** sidebar is Home (01 Command Centre ·
  02 Markets · 03 Tomorrow's Watchlist · 04 Analyze Stock) · Portfolio (05 My Portfolio · 06 Paper
  Trades · 07 Watchlist & Journal · 08 Long-Term Quality) · Advanced, collapsed (09 Verdict Calibration ·
  10 Backtest · 11 Angel One) · Tools (12 Trading Tools · 13 Find Ideas · 14 Investor Guide).
  Merged pages render the old page bodies from `dashboard/views/*.py` (`render()`): Markets = Live
  Ticker / Breadth & Macro / FII-DII (view switch), Find Ideas = Smart Screener / TQS (switch),
  Trading Tools = Intraday / Position Sizer (switch), Watchlist & Journal = tabs. Old names resolve via
  `nav._LEGACY_PAGES` (`_goto_page`, command bar); `nav.request_view(page, label)` opens a view.
  URLs changed only for merged pages (`markets`, `find_ideas`, `watchlist_journal`, `trading_tools`);
  Quality Watch kept its file slug. Command Centre now shows a one-line breadth/sector summary + "Open
  Markets" (full bhavcopy breadth panel moved to Markets → Breadth & Macro → Breadth). Verdict
  Calibration + Backtest merge is still to come. `test_page_numbers_follow_sidebar_order` still guards
  file numbers vs `nav._NAV_GROUPS`.

- **Watchlist study (9 Nov):** `verdict_ledger.results_by_list` grades each list on its own (Top
  Picks, Momentum Leaders, each Tomorrow's Watchlist bucket; Analyze Stock ad-hoc views last):
  day-clustered hit rate vs the Nifty with its Wilson bound, average vs Nifty before/after a 0.25%
  round trip, breakdown / bearish-reversal judged as down-calls, "too early" under 10 scored days.
  Shown as "Results by list" under the "Is the model working?" card on Verdict Calibration, with the
  new pre-registered **`WATCHLIST_RULE`** (registered 2026-11-09; separate from DECISION_RULE, which is
  unchanged). The Friday report card now has a Top Picks section and a Tomorrow's Watchlist section
  (up-setups and down-setups apart). Returns stay close-to-close from the logging session's close:
  the ledger stores no next-day opens, so next-open entry for the after-close list isn't measured.
  The calibration page now shows "Uptrend / Strong trend" labels instead of BUY/STRONG BUY.

- **VIX fail-closed + weekly provider canary (10 Nov, `feat/data-reliability-vix-canaries`):**
  `utils/vix.py` tries NSE `allIndices` (INDIA VIX row, `nse_corp_info` session) then Yahoo ^INDIAVIX
  and records `source`; Angel is skipped (EQ-only token map, `^` skips Angel by design). All down →
  regime "unknown", `allow_buy=False`, `reason="VIX unavailable from NSE / Yahoo"`, shown as a caption
  on Command Centre / sidebar / top bar / checklist / My Portfolio and a once-a-day Telegram notice;
  `trading.signals` now delegates here. `scripts/provider_canary.py` + `provider_canary.yml` probe 8
  providers with the slow tests' shared `check_*` functions; exit 1 only if Yahoo / bhavcopy / VIX
  FAILED. Not yet run live (written offline, all mocked).

- **Sunday universe refresh (10 Nov, `feat/universe-sunday-refresh`):** `refresh_universe.yml`
  (dispatch-only) runs `tools/refresh_universe.py --ci`: it fetches NSE's index CSVs and diffs them
  against `data/nse_index_constituents.csv` (added / removed / renamed = same normalised company name
  with a new symbol / re-tiered). If anything changed, it opens an `automerge` PR on
  `auto/universe-YYYY-MM-DD` and sends a Telegram summary. If a fetch fails or the list is under 90%
  of the current size, the job exits non-zero and writes nothing. The sidecar
  `nse_index_constituents.meta.json` holds `refreshed`/`checked` dates. Command Centre shows a
  caption under the Top Picks chip when the list is >45 days old (`universe.stale_universe_warning`).
  If nothing changes for 28 days, a PR that only updates the meta file keeps that caption quiet.
  Not yet run live: the sandbox had no network.

- **Angel One price store (10 Nov, `feat/angel-price-store`, not run live):** new `daily_bars`
  table (`data/price_store.py`, same DB as trade_store, SQLite/Postgres DDL) filled nightly by
  `scripts/warm_price_store.py` via `warm_price_store.yml` (cron-job.org job #11, 18:30 IST): every
  `niftytotalmarket` name + ^NSEI/^INDIAVIX, Angel `getCandleData` ONE_DAY at `ANGEL_BULK_RPS` (default
  1.4/s), first run backfills `ANGEL_BACKFILL_DAYS` (2000 = one call), then only last stored date+1 →
  today; "exceeding access rate" → sleep 65 s, retry once, skip (3 in a row stop the run); optional
  `ANGEL_HIST_API_KEY` for this job only; one-line Telegram summary. `fetch_single` tier order is now
  AngelOne → **PriceStore** (daily; the store serves only when the market is closed, and only once
  it holds the last completed session and reaches the period start) → Stooq (off) → Yahoo
  → NSE-bhavcopy; `NSE_PRICE_STORE=0` turns it off (tests run with it off). Angel candles are assumed
  UNADJUSTED: the job trims rows before any >30% close-to-close jump and a Yahoo fallthrough drops the
  symbol on a >30% close mismatch. Command Centre shows "Prices: store (as of …, N names) · Yahoo
  fallback" under the Top Picks chip. Market hours (09:15–15:30 IST) and the 15:30→18:30 gap before
  the fill stay on Yahoo, so intraday alerts, Top Picks, score.py's volume projection and the 15:50
  Tomorrow's Watchlist see the same bars as before. `ANGEL_BULK_RPS` defaults to 1.4 (~84/min,
  under the ~90/min ceiling).

## Owner to-dos (cron-job.org; every scheduled workflow is dispatched from there)
- [x] **Universe refresh (job #9, new):** URL
  `https://api.github.com/repos/mrinaljhunjhunwala-ui/nse-smart-investor/actions/workflows/refresh_universe.yml/dispatches`,
  POST, the usual four headers, body `{"ref":"main"}`, crontab `0 10 * * 0` (Asia/Kolkata, Sunday
  10:00). For the auto PR to get CI + automerge, the `AUTOMERGE_TOKEN` secret must be set (PRs opened
  with `GITHUB_TOKEN` trigger no workflows). Also enable Settings → Actions → "Allow GitHub Actions to
  create and approve pull requests". Do one manual "Run workflow" first and check the log.
- [x] **Provider canary (job #10):** `provider_canary.yml`, body `{"ref":"main"}`, crontab
  `0 9 * * 0` IST (Sunday 09:00), same four headers. First run: check the table in the Actions log
  and the 🟢/🔴 Telegram line; a red job means Yahoo, bhavcopy or VIX FAILED.
- [ ] **Price store (job #11):** add GitHub secret `ANGEL_HIST_API_KEY` (optional, a second SmartAPI
  app key) and the cron-job.org job: `warm_price_store.yml`, body `{"ref":"main"}`, crontab
  `30 18 * * 1-5` IST. Dispatch once by hand first and read the final `price_store: N ok, M skipped,
  K new rows` line: check the index symbols were served (Angel index tokens are unverified) and how
  many 403 pauses the backfill hit; if any, lower `ANGEL_BULK_RPS` (default 1.4) in the workflow.
- [ ] **Market Alerts (job #3):** showed "Successful" but no GitHub run from 4–6 Nov. Settings
  checked on 7 Nov (URL ok). Confirm a run appears **Mon 9 Nov 09:00 IST**; a real dispatch answers
  **204**. "Treat 3xx as success" must stay OFF. This job also carries the 15:15 picks recap and the
  intraday BUY alerts.
- [ ] **Weekly digest:** failed with an HTTP error on 1 Nov. Body
  `{"ref":"main","inputs":{"mode":"weekly-digest","force":"false"}}` plus `Content-Type: application/json`.
- [ ] **Momentum digest (job #5):** not created yet. `market-digest.yml`, body
  `{"ref":"main","inputs":{"mode":"momentum","force":"false"}}`, crontab `0,30 10-14 * * 1-5` IST.

## Open decisions (owner)
- ~~Tomorrow's Watchlist in bear regimes~~ **Decided 7 Nov: option (b)**: keep the gates and say why
  the list is empty (page already did; the 🌙 Telegram message now does too). Don't add rank-based gates.
- **Live checks during market hours:** Live Ticker 30 s refresh and the Angel One connected panel
  have only been verified by stubbed tests.

## Research clock
- **Verdict Calibration decision rule** (registered 2026-09-29: 20 sessions, ≥150 bullish verdicts
  over ≥30 days, day-clustered Wilson lower bound vs NIFTY > 50%, plus a Rising-NIFTY-only copy):
  earliest verdict ~mid-December 2026 because of the logging gap. Do not retune it.
- **Tomorrow's Watchlist rule** (`WATCHLIST_RULE`, registered 2026-11-09: picks logged from 4 Nov, all
  buckets pooled direction-aware, 5 sessions, ≥100 picks over ≥30 days, 0.25% round-trip cost,
  day-clustered Wilson lower bound > 50%): the 30th session from 4 Nov is 17 Dec, so the earliest
  verdict is **~24 Dec 2026** (after the nightly backfill), later for every session with no list.
  Do not retune it.
- Shadow breadth label re-test ~April 2027; range-regime sector-neutral reversal re-test late 2027;
  point-in-time index membership would remove survivorship bias from every study.

## Verified closed (don't re-open)
- Index symbols and Angel One: every candle path goes through `data.fetcher.fetch_single`, which
  skips Angel for `^` symbols (#322); Angel is only used for stock live quotes and holdings.
- "~9 silent swallows" in `analysis/hedging.py`, `portfolio_risk.py`, `portfolio_manager.py`:
  every handler there logs or re-raises (checked by AST scan on 7 Nov).
- Persistence on the live deploy: the warm jobs write snapshots to Postgres
  (`backend=postgres` in their logs).

---

# Handoff — 2026-09-28 · Bear-regime fix, warmers working, Stooq off, EOD pipeline

## Repo state
- **`main` at `686364c`**: CI passing. Local `main` is synced, and the only untracked item is `archive/`.
- **Canonical checkout:** `D:\Kashti Claude\nse-smart-investor`.
  - `E:\code\nse-smart-investor` is an **empty folder**. Nothing should point at it.
- **Open PRs:** none from this work.
- **Remote branches:** `main` only.
  - `alerts/consolidate-fresh-workflow`: PR #93 closed 2026-09-30; branch deleted.
  - `design/mockup-06-smart-screener` deleted 2026-10-02: PR #176 was stacked under #178 and its commit landed in that
    squash-merge; the branch was identical to `main`.
  - Deleted on 2026-09-28: `ux2-ticker-hover-preview` (its feature shipped in #150 and #153) and 8 fully merged branches.
- **Worktrees:** `sweet-cannon-bc10b5` belongs to another live session. `quizzical-faraday-f467bc` is no longer
  registered with git, but its folder was locked by a running process; delete it by hand once that process exits.
- **Other work merged in parallel** (not from this session):
  - #174: wide layout is re-asserted on every page.
  - #175 and #178–#182: pages moved onto the mockup layout.
  - The trade_store pool now waits instead of raising `PoolError`.
  - The test suite is blocked from writing to production Postgres, and there's a purge tool for leaked rows.
  - Page-smoke background threads are joined.
  - The verdict_log dedup behaviour is pinned by tests.
  - Also in parallel, 09-27 → 09-28: #188 (Claude may run `gh pr merge`), #190 (pyotp for Angel One),
    #192 (morning digest from the pre-open scan), #195 (bulk scans skip Angel One), #196 (every
    scheduled job has an external trigger), and verdict-ledger fixes (IST session dates, NSE holidays,
    backfill no longer starved).

## Alerts pipeline — state as of 2026-09-29 (#190 #192 #195 #196 #200 #206 #207)

- **GitHub cron is effectively dead for this repo.** On Mon 2026-09-28 it ran 1 warm-up and **zero**
  Market Alerts, digest or pre-open runs during market hours. Every scheduled workflow now takes an
  external `workflow_dispatch` trigger. The 8 targets (URL, body, IST schedule) are in a table in
  `alerts/README.md`.
  - **cron-job.org is live for #1 (pre-open, 08:40) and #3 (Market Alerts, every 15 min)** since
    2026-09-29. Both were checked that night: HTTP 204, and the `workflow_dispatch` runs passed. They use a
    fine-grained token (this repo only, Actions read/write) that lives only in cron-job.org. Jobs #2 and
    #4–#8 are not created yet. The README lists the gotchas: the Content-Type header is required, clones
    start inactive, and ad blockers break the test-run button.
  - **Windows Task Scheduler stopgap: retired 2026-09-30.** Both tasks are deleted. First full market
    morning on cron-job.org alone (30 Sep): the pre-open ran at 08:40 and sent the Morning Digest, and Market
    Alerts ran every slot from 09:00. The 09:15 run sent the Nifty-downtrend alert, and later runs were
    deduped. Both messages reached Telegram. `C:\Users\ASUS\nse-triggers\dispatch.ps1` is kept for manual
    dispatches.
  - **Every alert also goes to Gmail** (`ALERT_GMAIL_*` secrets). The user is thinking about dropping email;
    to do that, delete the three secrets and revoke the app password. No code change is needed.
  - `market-digest.yml` dispatches must send `"force":"false"`. Otherwise they act as manual tests and skip
    the market-hours guard and dedup.
- **Angel One candle API:** it works from GitHub runners and isn't IP-blocked. It returns 403 "exceeding
  access rate" at about 90 calls/min, and a longer-window quota cuts off at about 700 calls.
  - Since #195, one thread at a time fetches candles, within 60/min.
  - Any other thread gets `AngelBusy` and falls through to Yahoo silently.
  - Bulk scans never need Angel.
- **Morning Delivery Digest:** `warm-preopen-scan.yml` sends it right after writing the fresh snapshot
  (#192). Snapshots older than 16h are skipped. First delivered 2026-09-29, late because the PC was off at
  08:40.
- **Portfolio alerts (#206):** built from the My Portfolio holdings (KV `manual_portfolio_holdings`) on every
  Market Alerts run.
  - A ±10% step alert from a stored reference price, which re-anchors on each alert.
  - An alert when the price crosses the average cost.
  - References live in KV `portfolio_alert_anchors` (user `_system`), seeded from the 28-Sep closes.
  - `data/alerts.csv` is back to disabled examples, for custom one-off levels only.
- **Run logs name what fired (#207):** `[sent] <headline>` for each alert, and
  `[main] per-check: price= portfolio= vix= nifty=` per run. The recurring daily alert is the
  **Nifty 50 downtrend** check.
- **CI hygiene (#207):** actions are on their Node-24 majors (checkout v5, setup-python v6, cache v5,
  upload-artifact v6). Runners are pinned to `ubuntu-24.04`, because `ubuntu-latest` moves to Ubuntu 26 on
  2026-10-19.
- **Open decision: Tomorrow's Watchlist in bear regimes.** #168 (25 Sep) and #198 (28 Sep) compress
  bear-regime scores (Technical held at 20/40, RS at 5/10).
  - No stock reaches BUY ≥ 65; the top score on 29 Sep was 62.6.
  - The breakout funnel's first gate is `BUY/STRONG BUY`, so the list is empty by construction.
  - Breakdown fell from 15 to 1–4.
  - Options: rank-based gates in bear regimes, or show the lists as regime-suppressed. Needs a user call.

## Mockup layout rollout — complete 2026-09-30 (#210 #212 #214 #216 #218)

All 11 artboards of the 2026-09-12 "proposed layout" mockup
(https://claude.ai/artifact/TT3yhxsvDHvg4CorKC9Hv4) are on `main`, plus its palette. Earlier pages:
#175, #178–#182.
- **Analyze Stock (#210):** ticker head with actions (Size Position opens the Position Sizer prefilled),
  Overview tab first, posture hero with pillar bars, one combined-read strip (3 horizons + TQS), chart +
  thesis grid, sector-aware fundamentals card, overlay-signals and reference-levels cards. The old
  `verdict_card` (it printed the raw action, e.g. "BUY") is gone.
  - Bugs fixed on the way: Portfolio Fit always failed with holdings (`_th` NameError across fragments);
    the Fundamentals tab showed Debt/Equity for banks; the "your position" lookup never matched.
- **Live Ticker (#212):** dense price table (day high/low + VWAP) and index rail in one
  `@st.fragment(run_every=30s)` while NSE is open; rows flash on a tick. This replaced the whole-page
  `<meta refresh>`. Quote tiers now pass optional `high` / `low` / `vwap`.
  **Not yet seen live during market hours.**
- **Angel One (#214):** status panel, masked credentials, activity log, from new
  `angel_fetcher.status()` / `credential_summary()` and an in-process event log (no network). The posture
  tab shows descriptive labels ("Trend broken", not `EXIT_WATCH`). **The connected state has only been
  checked by the stubbed test** (no credentials on the dev PC).
- **Investor Guide (#216):** each tab is a chapter in a 760px reading column (contents, drop cap, callouts,
  document tables).
- **Palette (#218), dark only (the owner doesn't want light mode):** rust accent `#c88a3f`, muted
  bull / bear / amber, blue-black ground `#0e1116`, and Inter + JetBrains Mono instead of IBM Plex. It's
  driven by `dashboard/shared/tokens.py`; hard-coded copies were mapped in 13 files. A few legacy one-offs
  remain (e.g. `trade_utils._grade_color`).
- **Kit to reuse** (`ui_components.py`, CSS in `design.py`): `stock_head`, `kv_list`, `kit_card`,
  `thesis_grid`, `hero_verdict(pillars=)`, `ticker_table`, `mini_index`, `sparkline`, `fmt_volume`,
  `status_panel`, `activity_log`, plus the earlier `section_header`, `gate_strip`, `level_strip`,
  `signal_table`, etc. Mockup numbers the app doesn't compute are left out, never invented.

## What shipped 2026-09-28, later (#200 → #204)

- **Bear follow-up (#202, docs only):** on the same 10y data, #198 improves every risk_off cell and 3 of 4
  trend_down cells. The exception rests on 5 weeks, so both regimes keep one rule.
  - "Volume neutral in trend_down only" is recorded as a **pre-registered candidate**: judge it on bear weeks
    after 2026-07 before adopting it.
  - Flipping Technical stays rejected.
- **Regime notes (#204):** the badge notes now quote the current 10y per-week 20d IC: trend_up +0.044,
  trend_down +0.069, risk_off +0.035, range ≈ 0. They used to say bear rankings were "weak" or "backwards".
- **Hand checks done:**
  - **Page 04 drift banner:** checked live at 15:00 IST with RELIANCE (down 2.2%). It works as designed. It
    didn't fire because Yahoo's daily data includes today's partial bar during market hours, so entry already
    equals the live price. It only fires when the daily data is a stale close.
  - **Page 18 grade shades:** measured, not eyeballed. Adjacent grades are ΔE ≥ 20 apart, and contrast is at
    least 5.7:1 on the dark background. The letter grade is always shown, so colour isn't the only cue.
- **Parallel work:** #200 added price alerts for the 12 portfolio holdings (±10% and an avg-cost cross).

## What shipped 2026-09-28 (#189 → #198)

**Bear-regime ranking fixed (#198):** full write-up in `docs/SCORE_EFFICACY_BEAR_2026-09-28.md`.
- **Finding:** in trend_down and risk_off, Technical and RS rank backwards (recent strength predicts
  worse returns). Evidence: 10-year study, 484 tickers, 178k weekly observations, 2017-07 → 2026-07.
- **Change:** in bear regimes, Technical is held at 20/40 and RS at 5/10. It uses the same opt-out as
  #168 (`NSE_USE_REGIME_WEIGHTS=0`).
- **Result:** bear-week IC improves in both halves, at both 20 and 60 days (20d 2017–20 −0.024 →
  +0.026, 2021–26 −0.005 → +0.061). Overall 20d IC goes from +0.0209 to +0.0329.
- **Selection:** the variant was chosen on 2022–26 data before the 10y run existed, so 2017–20 is
  out of sample. Variants found after seeing the 10y data (also neutralising Volume, flipping
  Technical) were not adopted.
- **`CompositeScore.technical_raw`:** keeps the raw points. The thesis engine and page 04's ledger tags
  read it (flagged by the verdict-regression review).
- **Fetcher:** new `10y` period. `10y` used to silently return 1y, and Yahoo's `max` is **monthly**
  bars.
- Bear rankings are now mildly right, not strong.

**Warmers finally reach Postgres (#191, #193):**
- **Top Picks warmer:** it had not completed a scan since 2026-09-08. Once the ANGEL_* secrets were
  added, Angel One returned 403 for every candle call from GitHub's runners, and each ticker paid two
  failing calls. The result was 52 cancelled runs; the "successes" were weekend skips.
- **Fix:** Angel credentials were removed from the Top Picks and pre-open warmers, and the Top Picks
  timeout went from 8 to 20 min, with a per-minute heartbeat.
- **Verified:** the scan took 213 s and 744/745 stocks scored. `top_picks_snapshot` and
  `tomorrow_watchlist_snapshot` are both in Postgres.

**Angel One breaker (#194):** candle-API HTTP errors now count as breaker failures, and
`fetch_historical` checks the breaker before making calls. Before, it tripped once in 333 rejections.

**Stooq off by default (#189):** stooq.com now serves a JavaScript browser check, so a script can
never get data. The tier is skipped unless `NSE_ENABLE_STOOQ=1`, and the Data health panel shows it
as disabled.

**Earlier on 09-27 (after #186):** HANDOFF refresh (#187).

## What shipped 2026-09-27 (#170 → #186)

**Composite golden snapshot (#170):**
- `tools/composite_golden.py` generates `data/composite_golden_snapshot.json`: 20 seeded synthetic cases replayed through `score_dataframe()`.
- They cover:
  - trend shapes and short history;
  - running without a benchmark (no RS);
  - bear-regime momentum on and off;
  - high VIX;
  - sector rank and flows;
  - delivery;
  - the positioning add-on on and off.
- `tests/test_composite_golden_snapshot.py` fails on any drift in score, grade, action, pillar points or entry levels. It also asserts that VIX doesn't move points, the bear option is on by default, and the 90/100 caps hold.
- **After an intentional scoring change:** run `py tools/composite_golden.py --update` and review the JSON diff in the PR.

**Technical pillar +1 bug (#171):**
- `_score_technical` summed `pts.values()`, which included the bool `sma_available` (from #163). That gave every stock with a 200-day SMA a free +1.
- It now sums `rsi + macd + sma + adx` explicitly.
- Also fixed: `test_signal_parity.py` failed on weekends because `bdate_range(end=Saturday)` returned n−1 dates.

**Direction-aware ADX: tested, not adopted (#172, docs only):**
- The rule tested: a downtrend (−DI ≥ +DI) is capped at the 1-point ADX tier.
- The result was worse, on the same data scored twice: 20-day IC went from +0.0205 to +0.0188, and the 60-day paired difference was −0.0034 (t −3.5).
- The losses sit in trend_down and range; trend_up was unchanged. Strong downtrends in this sample tended to rebound.
- Write-up: `docs/SCORE_EFFICACY_ADX_DIRECTION_2026-09-26.md`. **Don't retry this without a new angle.**

**Data-health freshness (#173):**
- `probe_stored_datasets()` in `dashboard/shared/data_health.py` reads `MAX(date)` from each of five tables: `fii_dii_daily`, `nse_fii_deriv_daily`, `nse_fno_oi_daily`, `nse_option_chain_daily` and `nse_delivery_daily`.
- It counts NSE sessions behind the latest completed session. That session is today after 20:00 IST, otherwise the previous one, and holidays come from `market_hours`.
- More than one session behind shows as **stale** under "needs attention", together with the refresh command.
- Results are cached for 10 minutes, over one pooled connection with a rollback after any failed query.

**EOD data pipeline moved to GitHub Actions (#177):**
- `.github/workflows/refresh-eod-data.yml` runs at 19:45 and 22:00 IST, Monday to Friday. It covers FII/DII, FII index futures, F&O OI, delivery and the option chain.
  - `--days 3` lets a missed evening heal on the next run.
  - Each step runs even if an earlier one failed.
  - The job fails fast if `DATABASE_URL` is missing.
- **Background:** before this, four Windows scheduled tasks pointed at the empty `E:\` folder and were refused (`0x800710E0`). The data had been stale since about Sep 18.
  - Those tasks are now **disabled**, not deleted, in case one fetch ever has to run locally again.
- **Repo secret `DATABASE_URL`:** it didn't exist before this session. That means the existing warm-top-picks and tomorrow-watchlist workflows had been writing to throwaway SQLite on the runner while reporting success. The user has since added it.
  - The value must be **only** the `postgres://…` URL, not the `url = "…"` line from `secrets.toml`.
- **First run:** every step passed, including the option chain, so NSE did not block the runner.
- **Option-chain cookie:** it can now also come from an `NSE_COOKIE` env var or secret. It isn't set, and wasn't needed on the first run.
- **Local catch-up:** Sep 18–25 filled for delivery, F&O OI and FII index futures. All five datasets are current.

**F&O universe drift (#184):**
- Removed 15 names that are absent from the 2026-09-25 F&O bhavcopy: ABFRL, ACC, BALKRISIND, DALBHARAT, DEEPAKNTR, IGL, IPCALAB, IRCTC, LTTS, NAVINFLUOR, PEL, SUNTV, SYNGENE, TATACHEM and TATACOMM. The list goes from 137 to 122.
- **LTIMindtree now trades as `LTM`** in both cash and F&O. `LTIM.NS` fetches had been failing, so it's renamed everywhere: `fno_universe`, the IT sector list in `data/fetcher.py`, `data/universe.py` and the name map in `dashboard/shared/cache.py`.
- #186 did the same for the valuation golden snapshot and `tools/validate_valuation.py`. It re-captured only that one ticker live: REASONABLE / low confidence, with every input present.

**FII index-futures sub-score (#185):**
- The fixed ±30,000-contract bands pinned the sub-score at 0, because live values sit near −300,000.
- It now uses the latest value's **percentile within the trailing ~250 stored sessions** (`data.nse_fii_deriv.get_latest_fut_idx_pct`): ≥80th → 3, ≥50th → 2, ≥20th → 1, else 0. With fewer than 60 sessions it scores the neutral 1.5.
- History was backfilled to 2024-09-06 (398 sessions). Today's value is at the 0.4th percentile (the most net-short in a year), so it scores 0.
- **The positioning add-on is opt-in** (`NSE_USE_POSITIONING_PILLAR`), so default live scores are unaffected.

**Page 02 speed:** no change needed.
- Its smoke-test call now takes 6.6 s under CI conditions, down from 103 s earlier in the session and about 200 s in the old handoff.
- The gain came from the parallel pool and thread fixes, not from this session.
- The old ~200 s figure was measured with the user-level `DATABASE_URL` set, so tests hit remote Postgres.

## Guard tests (they fail CI, so don't work around them)
- **Advice language:** `test_no_advice_copy.py` bans buy/sell/hold instruction copy in the UI and in `analysis/`.
- **Colours:** `test_tokens.py` allows no raw hex in pages.
- **Pages:** `test_pages_smoke.py` compiles and renders each page with the network blocked.
- **Scoring snapshot:** `test_composite_golden_snapshot.py` is new. When it fails, regenerate the snapshot on purpose rather than loosening the test.
- **Scoring behaviour:**
  - `test_bear_regime_vix_neutral.py`
  - `test_engine_audit_fixes.py`
  - `test_audit_fixes.py`, which includes the TECH-BOOL regression
  - `test_fii_deriv_percentile.py`
- **Valuation:** `test_valuation_golden_snapshot.py` (E1-v2).

## Open / next
1. **Watch scheduled runs** of `refresh-eod-data` (19:45 IST) and the warmers in the Data health
   panel. If NSE blocks the runner, set the `NSE_COOKIE` secret, or re-enable the relevant (disabled)
   Windows task after pointing it at the `D:\` checkout.
2. **Bear regimes:**
   - Keep an eye on the verdict ledger's bear-regime rows.
   - Evaluate the pre-registered "Volume neutral in trend_down" candidate once there are enough bear weeks
     after 2026-07.
3. **Validation gaps:** sector rank, flows, delivery % and positioning can't be replayed
   historically, and survivorship bias is not corrected. The positioning add-on stays opt-in until
   it's validated.
4. **Mockup follow-ups: closed 2026-10-02.** The owner checked mobile, Live Ticker's live refresh and Angel One
   connected. `FinalVerdict.primary_reason` now uses descriptive action labels.
5. **Data sources:** NSE corp-info times out intermittently. Re-check the F&O list against NSE's
   monthly circular; the drift warning in `fetch_nse_fno_bhavcopy` names the candidates.

## Gotchas
- **Running the app for a live check:** the Browser pane's `preview_start` by name looks in the session's
  original scratch folder, not the repo. Start Streamlit yourself on a spare port (e.g. 8511, with the env vars
  from `.claude/launch.json`) and open it with `preview_start url=http://localhost:8511/<page>`.
  - Page slugs drop the number: `/analyze_stock`, `/tqs_scanner`.
  - A `launch.json` entry's `cwd` must be a relative path **inside** the repo, so to preview a worktree,
    keep the worktree under `.claude/worktrees/`.
  - Dataframes render to a canvas, so read table colours from the code and tokens, not screenshots.
- **Several Claude sessions work in this repo at once.** One ran `git reset --hard` in the main
  checkout and wiped another session's uncommitted edits. **Work in `.claude/worktrees/<name>` on
  your own branch and commit early.**
- **The laptop idle-sleeps overnight.** A long study (the 10y efficacy run takes about 45 min of
  compute) was paused for 11 hours. Hold the machine awake (keep-awake, `until: turn_end`) and wait
  in the turn.
- **Research runs on long periods:** use `--period 10y`, not `max` (monthly bars). Copy
  `research/output/observations.csv` elsewhere before starting the next run. Per-pillar variants
  can be evaluated exactly from the observation columns (pillars add up; RS pts = `RS_Score / 10`).
- **GitHub Actions "success" can mean "skipped".** The warmers exit 0 on weekends and holidays.
  Check the log for `scan done` / `persisted`.
- **Local tests reach production Postgres unless you unset `DATABASE_URL`.** The user-level `DATABASE_URL` points at the production database; the suite now blocks writes, but reads and timings still go remote. To match CI, run `env -u DATABASE_URL py -m pytest ...`, then delete any `trades.db` it creates.
- **Stacked PRs and `--delete-branch`:** squash-merging the base PR deletes its branch, and that **closes** the stacked PR. Merge without deleting, or retarget the stacked PR to `main` first. Afterwards, rebase the stacked branch onto `main` to drop the pre-squash commits.
- **pytest summary grep:** the summary line reads `N passed, M deselected in …`, so grepping for `passed in` misses it. Use `tail`.
- **Profiling page 02:** `cProfile` under AppTest effectively hangs. A `sys._current_frames()` sampler thread works.
- **Background agents:** `isolation: remote` on the Agent tool ran **locally**, in `.claude/worktrees/`, not in the cloud. Verify where it ran, and clean up the worktree (`git worktree remove -f -f` if it's locked).
- **Don't switch branches in the main checkout while tests or agents are running.**
- **Research runs** take about 11 minutes and overwrite `research/output/`, so copy each run to `run_*/` first.
- **`gh pr checks N --watch`** before merging. `gh` sometimes drops the connection ("forcibly closed"); just retry.

## Conventions
- **No buy/sell/hold instruction copy, ever** (CLAUDE.md rule 1).
- **Composite is 0–90, as four pillars (40+25+15+10).** It goes up to 100 only with the opt-in positioning add-on. No candlestick component.
- **`analysis/` stays pure:** no Streamlit imports.
- **Scoring changes:** regenerate the composite snapshot on purpose, run the `verdict-regression-reviewer` agent, and for anything that re-ranks broadly, run a same-data efficacy A/B (`research.score_efficacy`).
- **Windows shell:** use `py`, with `PYTHONUTF8=1`.
- **Merging:** squash-merge after CI passes, when the user has asked for the merge.
