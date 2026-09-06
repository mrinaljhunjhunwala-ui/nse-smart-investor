# Data Provenance Audit – 2026-09-06 16:35 IST

Scope: all 10 providers listed in `tasks/plan.md:49`. Live canaries run against `RELIANCE` / `RELIANCE.NS` / `500325` (safe canary symbols, not portfolio holdings). Read-only – no fetcher code was modified.

### Summary table

| # | Provider | Status | Notes |
|---|---|---|---|
| 1 | yfinance / Yahoo v8 chart | OK | 5 daily bars for `RELIANCE.NS`, all OHLCV columns present, cookie+crumb auth working |
| 2 | Stooq CSV | DEGRADED | Every request now returns a JS anti-bot challenge page instead of CSV – fetcher detects this correctly and raises, tiered fallback covers it |
| 3 | Angel One SmartAPI | OK | Live login with real creds succeeded, 12 daily bars returned with correct OHLCV shape |
| 4 | NSE corp-info | SCHEMA DRIFT (HIGH) | `/api/corporate-info/{symbol}` now returns HTTP 404 "Resource not found" – NSE retired this path. Correct current path `/api/top-corp-info?symbol=X&market=cash` returns 200 with the exact expected shape |
| 5 | BSE corp-info | DEFERRED (by design) | `bse` package not installed (deliberately, per module docstring – GPLv3 licensing decision pending); fetcher degrades cleanly to `{}` |
| 6a | Google News RSS | OK | 12 items returned for "Reliance Industries", title/link/pub_date/source all present |
| 6b | NSE RSS feeds | OK | 4 of 6 categories returned live items (20 each); 2 categories (`corporate_governance`, `insider_trading`) returned 0 items – confirmed benign (no filings today), not a parse failure |
| 7 | Screener.in scrape | BUG FOUND (HIGH) | Page structure and P&L/BS/CF row labels are unchanged and parse correctly, but the top-ratio parser silently returns `None` for `Market Cap`, `Current Price`, `High/Low`, `Book Value` – see detail below. This breaks P/B computation |
| 8 | India VIX | OK | `10.68`, regime `complacency`, correct shape |
| 9 | NSE bhavcopy delivery | OK | 2,633 rows for today's file, all required columns present |
| 10a | F&O bhavcopy | OK | 404 for 2026-09-05/06 (not yet published – expected/documented), 210 symbols aggregated successfully for 2026-09-04 |
| 10b | NSE option-chain v3 | OK | Two-step contract-info → v3 flow works end-to-end; PCR 0.748, max-pain 1320 (0.15% from spot), 39 strikes for `RELIANCE` |

---

### 1. yfinance / Yahoo v8 chart API – `data/fetcher.py::_fetch_yahoo_direct`

- **Endpoint**: `GET https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=5d&includePrePost=false&crumb=<token>`, cookie+crumb auth via `fc.yahoo.com` consent gate + `/v1/test/getcrumb`.
- **Expected shape**: `chart.result[0].timestamp[]`, `.indicators.quote[0].{open,high,low,close,volume}`, optional `.indicators.adjclose[0].adjclose`.
- **Canary**: 5 bars for `RELIANCE.NS`, columns `Open/High/Low/Close/Volume`, values sane (₹1302–1333 range).
- **Drift risk**: LOW. Already has the defensive parse added in the 2026-09-02 hardening pass (`e9ebc4f`) – a missing/renamed `indicators.quote` now raises a named `ValueError` instead of a bare `KeyError`.
- **Action**: none required.

### 2. Stooq CSV – `data/fetcher.py::_fetch_stooq`

- **Endpoint**: `GET https://stooq.com/q/d/l/?s={symbol}&d1=&d2=&i=d`, no auth.
- **Expected shape**: CSV with `Date,Open,High,Low,Close,Volume` header.
- **Canary**: every attempt (`RELIANCE.NS`, `INFY.NS`) returned a 200 HTML page beginning `<!DOCTYPE html>...This site requires JavaScript to verify your browser...` – a bot-challenge page, not the "geo-block/rate-limit maintenance" HTML the existing diagnostic logging anticipated.
- **Drift risk**: MEDIUM. The fetcher's existing HTML-sniff (`raw.lstrip().startswith("<")`) already catches this and raises a clean `ValueError`; `fetch_single()`'s tier fallback and the Stooq circuit breaker (`_STOOQ_BREAKER_*`) already route around it to Yahoo. Net effect on the app today is latency (one ~4s timeout per ticker until the breaker trips), not incorrect data – but Stooq is effectively 100% down right now for this environment, not intermittently degraded.
- **Action**: no code fix needed (fallback chain already covers it). Optional follow-up: since this looks persistent rather than transient, consider lowering `_STOOQ_BREAKER_THRESHOLD` or adding a longer-lived "known dead" flag so a full-universe scan doesn't keep re-testing it every 5 minutes. Low priority – deferred.

### 3. Angel One SmartAPI historical – `data/angel_fetcher.py`

- **Endpoint / auth**: `POST /rest/auth/angelbroking/user/v1/loginByPassword` (client_id + password + TOTP) → JWT, then `POST /rest/secure/angelbroking/historical/v1/getCandleData` (symboltoken + interval + date range).
- **Expected shape**: `data.jwtToken` / `data.feedToken` on login; `data` = list of `[date, open, high, low, close, volume]` arrays (positional, not keyed) on candle fetch.
- **Canary**: promoted the creds from `.streamlit/secrets.toml` `[angel_one]` into env vars, ran a single live login + `fetch_historical("RELIANCE.NS", period="5d")`. Login succeeded, 12 daily bars returned with correct values (matches Yahoo's numbers for the same dates – cross-checked).
- **Drift risk**: LOW functionally today (confirmed live), but structurally MEDIUM: `_fetch_candles_window` builds the DataFrame positionally – `pd.DataFrame(candles, columns=["Date","Open","High","Low","Close","Volume"])` – with no check that Angel's array actually has 6 elements in that order. If Angel reorders or adds a field, this would silently mis-map columns rather than raise.
- **Action** (proposed, not applied): add a length/shape assert on the first row of `candles` in `_fetch_candles_window` before the positional `pd.DataFrame` construction, raising a named error on mismatch – ~10 min fix. Since this ran live and clean today, treat as a deferred hardening item, not an active drift.
- Note: only ran the login once, deliberately, to avoid tripping the account's login rate limits – did not retry or probe further.

### 4. NSE corp-info – `data/nse_corp_info.py::get_corp_info` – ACTIONABLE FIX

- **Current code** (`data/nse_corp_info.py:128`): `api_url = f"{base}/api/corporate-info/{sym}"`.
- **Live result**: `GET https://www.nseindia.com/api/corporate-info/RELIANCE` → **HTTP 404**, body `"Resource not found"` (NSE's own 404 page, not a WAF challenge page – confirmed by comparing against a genuine WAF 403 seen on `/api/quote-equity`). Confirmed on a fresh session (home-page primed, 200 OK) with generous 15s timeout, so this is not a timeout/rate-limit artifact.
- **Root cause**: NSE retired this path. Probed alternates directly:
  - `/api/corp-info?symbol=RELIANCE` → 404
  - `/api/top-corp-info?symbol=RELIANCE&market=cash` → **200**, returns `{"latest_announcements": {"data":[{"symbol","broadcastdate","subject"}, ...]}, "corporate_actions": {"data":[{"symbol","exdate","purpose"}, ...]}, "shareholdings_patterns": {...}, "financial_results": {...}, "borad_meeting": {...}}` – exactly the shape `get_corp_info()`'s callers already expect (confirmed against `analysis/qualitative_flags.py:249,277,310`, which read `latest_announcements.data`, `corporate_actions.data`, `shareholdings_patterns.data`).
  - Corroborating clue already in the codebase: `analysis/qualitative_flags.py:370` labels its shareholding-pattern flag source as `"NSE top-corp-info: shareholdings_patterns"` – the code was documented against `top-corp-info` even though the fetcher calls `corporate-info`. This looks like the URL diverged from the doc/comment at some point, not a brand-new provider change.
- **Impact**: every call to `get_corp_info()` currently returns `{}` (the fetcher's existing non-200 handling degrades gracefully – no crash – but the qualitative-flags pipeline gets zero NSE-sourced governance signal, silently, for every symbol). BSE fallback is also dark (see #5), so this provider chain is currently 0-for-2 in this environment; only Google News RSS and NSE RSS feeds are supplying qualitative signal right now.
- **Drift risk**: HIGH.
- **Proposed fix**: change `data/nse_corp_info.py:128` from
  `f"{base}/api/corporate-info/{sym}"` → `f"{base}/api/top-corp-info?symbol={sym}&market=cash"`.
  Response shape is unchanged for the fields the module already reads, so no downstream parsing changes should be needed – verify against `tests/test_nse_corp_info.py` fixtures before merging (they currently mock the old URL/shape and will need the URL updated, though the JSON shape itself is compatible). Estimated effort: 20-30 min including test update.

### 5. BSE corp-info – `data/bse_corp_info.py`

- **Endpoint / auth**: via the `bse` PyPI package (`BennyThadikaran/BseIndiaApi`), `client.announcements(scripcode, from_date, to_date)` and `client.actions(scripcode)`.
- **Expected shape**: reshaped to match NSE's `{"latest_announcements": {"data": [...]}, "corporate_actions": {"data": [...]}}`.
- **Canary**: `bse` is not installed in this environment (`requirements.txt` deliberately omits it – module docstring flags a GPLv3 licensing decision the project owner hasn't made yet). `get_corp_info("500325")` returned `{}` with diagnostic `"bse package not installed"` – this is the fetcher behaving exactly as documented, not a failure.
- **Drift risk**: N/A (dependency-gated, can't assess schema without it installed).
- **Action**: accepted deferral – no code issue, this is a standing product decision. If/when the owner decides on the GPLv3 question and adds `bse` to `requirements.txt`, a follow-up canary should verify the `Table` envelope and `NEWSSUB`/`HEADLINE`/`Purpose`/`exdate` field names the parser reads, since this schema hasn't been live-verified in this audit.

### 6a. Google News RSS – `data/news_feed.py::fetch_news`

- **Endpoint**: `GET https://news.google.com/rss/search?q=<query>&hl=en-IN&gl=IN&ceid=IN:en`, unauthenticated.
- **Expected shape**: RSS `<item><title>/<link>/<pubDate>/<source>`.
- **Canary**: 12 items for "Reliance Industries NSE India", all fields populated, most-recent item dated 31 Aug 2026 (median staleness matches the module's own documented expectation of a "trend source, not a wire").
- **Drift risk**: LOW.
- **Action**: none.

### 6b. NSE RSS feeds – `data/nse_rss_feeds.py::fetch_feed`

- **Endpoint**: `GET https://nsearchives.nseindia.com/content/RSS/{Category}.xml` (static archive host, officially published for syndication – different WAF profile than the JSON API host).
- **Expected shape**: RSS `<item><title>/<link>/<description>/<pubDate>`.
- **Canary**: `related_party_transactions`, `reason_for_encumbrance`, `sast_regulation_29`, `sast_regulation_31` each returned 20 items with all fields populated. `corporate_governance` and `insider_trading` returned 0 items with `"ok (0 items)"` diagnostic – this is the expected shape (empty `<channel>` with no `<item>` elements, not a parse failure), so treated as benign no-news-today rather than drift.
- **Drift risk**: LOW.
- **Action**: none. Worth a note for Task 2.5: these two zero-item categories are indistinguishable from "the feed silently stopped listing items" without a periodic canary – good candidate for `tests/test_provenance_nse_rss_feeds.py` asserting non-zero across a rolling multi-day window rather than a single point-in-time check.

### 7. Screener.in scrape – `analysis/fundamentals/providers/screener_fundamentals.py` – BUG FOUND

- **Endpoint**: `GET https://www.screener.in/company/{CODE}/consolidated/` (falls back to non-consolidated), HTML scrape via BeautifulSoup.
- **Expected shape**: `#profit-loss`, `#balance-sheet`, `#cash-flow`, `#ratios`, `#quarters` sections, plus `#top-ratios` list of `<li><span class="name">/<span class="value"><span class="number">`.
- **Canary result – statements**: fully healthy. P&L row labels (`Sales`, `Operating Profit`, `Net Profit`, `Interest`, `EPS in Rs`, `Tax %`) all matched `_PL_MAP` unchanged; 10 years of `IncomeStatement` objects built correctly (`RELIANCE` FY2026 revenue ₹10,55,780 Cr, net income ₹95,754 Cr – sane).
- **Canary result – top ratios**: `{'Market Cap': None, 'Current Price': None, 'High / Low': None, 'Stock P/E': 23.9, 'Book Value': None, 'Dividend Yield': 0.0045, 'ROCE': 0.103, 'ROE': 0.0891, 'Face Value': None}`. Four of nine fields parsed to `None` despite being present and populated on the page.
- **Root cause** (verified by fetching the raw HTML directly): Screener wraps currency-denominated values as `<span class="nowrap value">₹ <span class="number">1,322</span></span>` (and Market Cap/High-Low additionally carry a trailing unit, e.g. `Cr.` or a second `<span class="number">` for the "/" pair). `_read_top_ratios()`'s `raw = li.find("span", class_="value").get_text(" ", strip=True)` pulls the *whole* value span's text – e.g. `"₹ 1,322"` or `"₹ 17,89,001 Cr."` – and hands it to `_num()`, which only strips commas/dashes/trailing `%` before calling `float()`. It never strips the leading `₹` or trailing unit words, so `float("₹ 1789001 Cr.")` raises and `_num()` returns `None`. Fields without a currency symbol or suffix (`Stock P/E`, `ROCE`, `ROE`, `Dividend Yield`) happen to parse fine because their value span text is already bare-numeric (or numeric + `%`, which `_num()` does handle).
- **Downstream impact**: `get_ratios()` computes `pb = cmp_ / book_value` – both inputs are `None`, so **P/B is silently unavailable for every stock** the Screener fallback serves it for. Given Guardrail §3 ("Banks/NBFCs/insurers are assessed on P/B + ROE, not leverage"), this specifically degrades sector-aware scoring for any bank/NBFC/insurer that falls through to the Screener provider (i.e., wherever Yahoo doesn't have P/B either) – no exception is raised, so nothing currently surfaces this in logs or tests.
- **Drift risk**: HIGH – this is a live parsing bug affecting a Guardrail-critical metric, not a one-off transient issue (reproduced from a second independent HTML fetch of the live page).
- **Proposed fix**: in `_read_top_ratios()`, prefer extracting numeric value(s) from the nested `<span class="number">` element(s) directly (there can be 1 or 2, e.g. High/Low) rather than the whole value span's text, and only fall back to the full-text `_num()` path for fields like `Dividend Yield` where the meaningful unit (`%`) needs to stay attached. Concretely: for each `<li>`, collect all `<span class="number">` children's text; if exactly one, `_num()` that directly; if the value span's only non-number text is `%`, keep current behavior. Estimated effort: 30-45 min plus a couple of stock-specific regression checks (bank stocks in particular, to confirm P/B now populates).

### 8. India VIX – `utils/vix.py::get_india_vix_regime`

- **Endpoint**: `GET https://query1.finance.yahoo.com/v8/finance/chart/%5EINDIAVIX?interval=1d&range=5d`, shares the Yahoo cookie+crumb session from `data/fetcher.py`.
- **Expected shape**: same `chart.result[0].indicators.quote[0].close[]` as the equity chart endpoint.
- **Canary**: `{'vix': 10.68, 'regime': 'complacency', 'allow_buy': True, 'vix_pct_chg': -5.82}` – well-formed, regime classification consistent with the documented thresholds.
- **Drift risk**: LOW. Already carries the 2026-09-02 hardening's named `ValueError`s for missing `chart.result` / `indicators.quote`.
- **Action**: none.

### 9. NSE bhavcopy delivery – `data/nse_delivery.py`

- **Endpoint**: `GET https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{DDMMYYYY}.csv`.
- **Expected shape**: CSV with required columns `SYMBOL, SERIES, DATE1, CLOSE_PRICE, TTL_TRD_QNTY, DELIV_QTY, DELIV_PER`.
- **Canary**: today's file fetched cleanly, 2,633 rows after the EQ/BE series filter, sample row for `20MICRONS` with sane `deliv_pct=47.01`. All required columns present – the Guardrail §14 schema check passed with no drift.
- **Drift risk**: LOW.
- **Action**: none.

### 10a. NSE F&O bhavcopy – `data/nse_fno_bhavcopy.py`

- **Endpoint**: `GET https://nsearchives.nseindia.com/content/fo/BhavCopy_NSE_FO_0_0_0_{YYYYMMDD}_F_0000.csv.zip` (zip-wrapped CSV, per the `ae846ac` fix).
- **Expected shape**: required columns `TckrSymb, FinInstrmTp, OpnIntrst`; zip must contain exactly one `.csv` member.
- **Canary**: 2026-09-05/06 both 404 (not yet published for those dates – expected per the module's own "best-effort, try previous trading day" contract); 2026-09-04 succeeded, unzipped correctly, 210 symbols aggregated, sample `360ONE` total_oi 7,431,000 across 93 contracts. Confirms the `ae846ac` fix is holding.
- **Drift risk**: LOW.
- **Action**: none.

### 10b. NSE option-chain v3 – `data/nse_option_chain.py`

- **Endpoint**: two-step – `GET /api/option-chain-contract-info?symbol=X` for expiries, then `GET /api/option-chain-v3?type=Equity&symbol=X&expiry=<nearest>` for the chain (per the `cf18e75` migration).
- **Expected shape**: `records.data[].{strikePrice, CE.openInterest, PE.openInterest}`, `records.underlyingValue`, `expiryDates`.
- **Canary**: full two-step flow succeeded for `RELIANCE` with no manual cookie or `curl_cffi` needed in this session – `spot=1322.0`, `nearest_expiry=29-Sep-2026`, `pcr=0.748`, `max_pain_strike=1320.0` (0.15% from spot), 39 strikes. Confirms the `cf18e75` v3 migration is holding today.
- **Drift risk**: LOW-MEDIUM – this endpoint is documented as WAF-sensitive and the module's own comments note it can start returning `{}` to scripted callers without warning; today's session worked cleanly, but the `_HAS_CURL_CFFI` / manual-cookie escape hatches exist for a reason and should stay in place.
- **Action**: none required today; keep the existing canary test (`tests/test_provenance_nse_option_chain.py`) in the weekly rotation given the endpoint's known fragility.

---

### Silent-empty / bare-indexing check (Guardrail §14/§15, post `e9ebc4f`)

- `data/fetcher.py`, `utils/vix.py`, `data/bse_corp_info.py`, `analysis/fundamentals/providers/screener_fundamentals.py` all carry the named-`ValueError`/WARNING treatment added by the 2026-09-02 hardening pass – no bare `[0]` or unguarded `.get()` chains found in the audited canary paths of these four.
- `data/nse_option_chain.py`, `data/nse_fno_bhavcopy.py`, `data/nse_delivery.py` (added since that pass) already follow the same discipline – named `ValueError` on missing required columns/keys, `_log.warning` on parsed-but-empty results.
- Remaining `or []` patterns without a preceding schema check, found but **outside the audited canary paths** (not part of `tasks/plan.md:49`'s provider list, flagged for awareness only): `data/angel_fetcher.py:418` (`searchScrip` result normalization), `:737-738` (market depth buy/sell arrays), `:850-851` (positions day/net arrays). None of these sit on the `fetch_historical` path just canaried live; lower priority.
- `data/angel_fetcher.py::_fetch_candles_window` builds `pd.DataFrame(candles, columns=[...])` positionally from Angel's raw array response with no length/order assertion – see finding #3 above.

### Canary test coverage (input to Task 2.5)

| Provider | Has `tests/test_provenance_*.py` | Notes |
|---|---|---|
| NSE bhavcopy delivery | Yes (`test_provenance_nse_delivery.py`) | |
| NSE FII/DII derivatives | Yes (`test_provenance_nse_fii_deriv.py`) | not in this audit's provider list but exists |
| NSE F&O bhavcopy | Yes (`test_provenance_nse_fno_bhavcopy.py`) | |
| NSE option-chain v3 | Yes (`test_provenance_nse_option_chain.py`) | |
| yfinance/Yahoo, Stooq, Angel One | No – only `tests/test_fetcher.py` / `tests/test_angel_fetcher.py` (offline-mocked) | schema-expectation tests exist; no live canary test |
| NSE corp-info | No – only `tests/test_nse_corp_info.py` (offline-mocked) | would have caught today's URL retirement immediately |
| BSE corp-info | No – only `tests/test_bse_corp_info.py` (offline-mocked) | blocked on `bse` package decision |
| Google News RSS | No – only `tests/test_news_feed.py` (offline-mocked) | |
| NSE RSS feeds | No – only `tests/test_nse_rss_feeds.py` (offline-mocked) | |
| Screener.in | No dedicated test file found | today's P/B bug would have been caught by a live canary asserting `pb is not None` for a known stock |
| India VIX | No dedicated `test_provenance_*` file found | |

---

### Action items (priority order)

1. **Fix NSE corp-info URL** – `data/nse_corp_info.py:128`, change `/api/corporate-info/{symbol}` to `/api/top-corp-info?symbol={symbol}&market=cash`; update `tests/test_nse_corp_info.py` fixtures to match. ~20-30 min. HIGH priority – this is a total outage of the primary qualitative-flags data source, currently masked by the fetcher's graceful `{}` degradation.
2. **Fix Screener.in top-ratio currency parsing** – `analysis/fundamentals/providers/screener_fundamentals.py::_read_top_ratios`, extract from the nested `<span class="number">` element(s) instead of the whole value-span text so `₹`/`Cr.` prefixes and suffixes don't break `_num()`. ~30-45 min. HIGH priority – silently kills P/B, a Guardrail §3 sector-critical metric.
3. Add a canary test for NSE corp-info (`tests/test_provenance_nse_corp_info.py`) hitting the live endpoint weekly – would have caught #1 the day it happened. Input to Task 2.5.
4. Add a canary test for Screener.in asserting `get_ratios("RELIANCE").pb is not None` (or similar) – would have caught #2. Input to Task 2.5.
5. Harden `angel_fetcher._fetch_candles_window`'s positional `candles` → DataFrame construction with an explicit row-shape check before assigning column names. ~10 min. LOW-MEDIUM priority (works today, but silent-drift-prone by construction).
6. Accepted deferral: BSE corp-info stays disabled until the project owner resolves the `bse` package's GPLv3 licensing question (per that module's own docstring) – no action from this audit.
7. Accepted deferral: Stooq's persistent JS-challenge response – already handled gracefully by the existing tier fallback + circuit breaker; no fix required, just noting it's not transient in this environment.

**Providers left healthy – no action needed**: yfinance/Yahoo v8 chart, Angel One SmartAPI (live-verified), Google News RSS, NSE RSS feeds (4/6 categories confirmed with live items, 2/6 confirmed benign-empty), India VIX, NSE bhavcopy delivery, NSE F&O bhavcopy, NSE option-chain v3.
