# Fundamentals data check: coverage, correctness, and why pages show blanks (2026-11-25)

Read-only audit. No code, DB or branch changes. Probe script and raw output:
`D:\Kashti Claude\_tmp\fund_check\` (`fund_check.py`, `results.json`, `summary.txt`, `nse.py`).
The probe calls the app's own providers and `FundamentalsService` exactly as `default_service()` wires them
(Yahoo → Screener → stored exchange filing → stored ROC filing). Two changes: `trade_store` was stubbed so
nothing was read from or written to the DB, and `NSE_AUTO_FILING_FETCH=0` was set. It ran 30 tickers in
sequence, with about 1.2 s between Screener requests.

## Headline

**The source data is fine. Our merge layer is what breaks it.** Yahoo answered for 30/30 tickers and
Screener's free public pages for 29/30. Between them every core field exists for every non-insurer.
Even so, the merged object the pages read is broken in three ways for almost every stock:

1. **Revenue YoY is "n/a" for 29/30 tickers.** Screener dates every column on the 28th of the month
   (`Mar 2026` → 2026-03-28). Yahoo uses the true period end (2026-03-31). `_merge_series` matches rows
   on the exact date, so the two never match. Every year then appears **twice**, 3 days apart, and the
   series alternates between providers (`2026-03-31 Yahoo, 2026-03-28 Screener, 2025-03-31 Yahoo, …`).
   `revenue_yoy` compares the last two points, finds them "3 days apart, not a year" and returns n/a.
2. **ROCE is "n/a" for 30/30 tickers.** Screener's page carries a **half-year `Sep 2026` balance-sheet
   column**. The parser keeps it as an annual period, so it becomes the "latest balance sheet". That
   Screener row has no current liabilities, so `analytics.roce()` returns "missing total assets or current
   liabilities" for every stock. ROE also mixes Yahoo FY26 net income with Screener Sep-26/Mar-26 equity.
3. **Some numbers are wrong rather than missing.**
   - INFY: Yahoo reports its statements in **USD** (financialCurrency = USD). We treat them as INR, so
     revenue reads as ₹2,016 cr instead of about ₹1,78,650 cr. Merged revenue CAGR shows −64%, ROE 0.66%
     and EV/EBITDA 912.
   - Banks and NBFCs: Yahoo "Total Revenue" is net revenue, while Screener "Revenue" is gross interest
     income. The interleaved series takes a CAGR across the two definitions: SBIN −2.7%, LICHSGFIN −19%,
     AXISBANK 6.3%.

Smaller issues also reach the pages:
- SBILIFE gets nothing from Screener. Its consolidated page exists but is empty, and we never try the
  standalone page.
- A Screener 429 or 403 response is negative-cached for 24 h as "unknown ticker".
- The pages swallow failures in several places and render "—" with no reason.
- Quality Watch shows ROCE and D/E for banks, which breaks CLAUDE.md rule 3.

**Paid Screener Premium (₹4,999/yr) would not fix any of this.** Every blank traced in this audit is our
own parsing, merging or page handling; the free public page already has the data. See the verdict near
the end.

## 1. Data path

| Layer | What | TTL / behaviour |
|---|---|---|
| `service.default_service()` (`analysis/fundamentals/service.py:381`) | providers `[Yahoo, Screener, Filing("exchange"), Filing("roc")]`. First provider is primary; later ones fill `None` fields only | merged result cached **24 h**; an all-empty result is cached **10 min** (`EMPTY_TTL_SECONDS`, l.39/68) |
| `_collect` (l.78-94) | each provider assembled; **any exception in one provider drops it entirely** (logged at WARNING only) | — |
| Auto filing fetch (l.136, 281-357) | if revenue / net income / equity are still missing: NSE annual XBRL, once per symbol per day, 15 s timeout, 30-min breaker | memo in KV `filing_autofetch:<SYM>` |
| `YahooFundamentalProvider` | `yf.Ticker` statements + `.info`; `.info` failure swallowed → `{}` (l.122-126) | raw **24 h** |
| `ScreenerFundamentalProvider` | GET `/company/<SYM>/consolidated/`, then `/company/<SYM>/` | raw **24 h**, *including* a negative `{}` for "not found" (l.144) |
| `FilingFundamentalProvider` | reads stored XBRL from KV `filing_fund:<SRC>:<SYM>` | — |
| Analyze Stock (05) | `_cached_valuation` / `_cached_fund_card` (`st.cache_data` **300 s**); the Fundamentals tab calls `service_for_source(picker)` | |
| Quality Watch (09) | `_assess_one` (`st.cache_data` **4 h**), 12 threads over the universe; deep dive **6 h** | |

**Fields each surface needs, by sector profile** (`analysis/sector_classification.py`):

| Surface | Operating companies | Lenders / insurers (`is_financial`) |
|---|---|---|
| 05 Overview card (`_cached_fund_card`, 05:282) | P/E, EV/EBITDA, P/B, ROE, ROCE, D/E, Rev CAGR 5y, EPS CAGR 5y | P/B, ROE, P/E, CAGRs |
| 05 banner and quality score | `compute_all` → roe, roce, revenue_cagr, eps_cagr; `revenue_yoy` in the provenance line (05:1314) | same, with ROCE dropped by `portfolio_fundamentals._is_lender` |
| 05 Fundamentals tab | Rev CAGR, EPS CAGR, ROE, D/E, ROCE, FCF, F-score (needs ≥2 full years of statements) | Rev/EPS CAGR, ROE |
| 09 ranking | `cf.ratios.roe/roce/debt_to_equity` (**vendor ratios, not statements**), P/B, P/E, posture, fund score | ROE, P/B (`quality_ratio_keys`) |
| 09 deep dive and peers | ROE, ROCE, D/E, net margin, P/E, P/B, current ratio (`ratios`) | **the same, with no gating (bug)** |

### Places where a failure is swallowed or blanked without a reason

| Where | What happens |
|---|---|
| `service.py:90-93` | One exception in any `get_*` drops the **whole** provider; the page only sees fewer sources. |
| `yahoo_fundamentals.py:122-126` | A Yahoo `.info` failure (429 / cookie) → `{}` → **all ratios None** (P/E, P/B, ROE, margins, mcap), logged at DEBUG. |
| `screener_fundamentals.py:124-134,144` | A non-200/404 response (429, 403, Cloudflare) is treated as "unknown ticker" → returns `None` → **negative-cached 24 h**. One throttled Quality Watch scan blanks Screener for a day. |
| `filing_fundamentals.py:171-172` | Returns an empty `RatioSnapshot()` when nothing is stored, and `has_any_data()` (`models.py:121`) counts a non-None ratios object. So every stock is labelled "YahooFinance + Screener.in + Exchange filing (NSE XBRL) + ROC filing (MCA upload)" (seen on 30/30) even though no filing exists. |
| `05_analyze_stock.py:735-738` | `_cached_valuation` exception → debug log only. `_fv_cf` stays None → quality score None, fundamental score skipped, and `_fv_fund_missing` (l.830) is **False**, so the banner never says "fundamentals missing". |
| `05:291-293` / `05:1408-1412, 1474-1480` | `_cached_fund_card` never returns None (the service always returns an object), so the "Fundamentals unavailable — the Fundamentals tab shows why" empty state **cannot appear**. An empty result renders as a card full of "—". |
| `05:1308-1319` | Revenue YoY is silently left out when n/a (it is n/a for 29/30 because of the date bug). |
| `05:2340` | The "Data coverage" note still says "years of history Yahoo Finance returned (~4–5)". Screener supplies 10. |
| `09:179-181` | Exception → `posture=None` → the ticker is moved to "fetch error" and **dropped from the ranking**. |
| `09:229` | 12 parallel workers over nifty500 → Yahoo 429s plus Screener throttling, which then hits the 24 h negative cache above. |

## 2. Coverage (30 tickers, live 2026-11-25)

Present (Y) or missing (.) per provider. Latest period, annual. `yrs` = annual revenue points.

| Ticker | Src | mcap | P/E | P/B | ROE | ROCE | D/E | NPM | Rev | NI | Equity | Debt | Cur.Liab | OCF | Capex | yrs |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 22 operating cos.¹ | Yahoo | Y | Y | Y | Y | . | Y | Y | Y | Y | Y | Y | Y | Y | Y | 4 |
| | Screener | .² | Y | Y | Y | Y | .³ | . | Y | Y | Y | Y | . | Y | . | 8–10 |
| HDFCBANK, ICICIBANK, SBIN, KOTAKBANK, AXISBANK | Yahoo | Y | Y | Y | Y | . | . | Y | Y | Y | Y | Y | . | Y | Y | 4 |
| | Screener | . | Y | Y | Y | Y⁴ | . | . | Y | Y | Y | .⁵ | . | Y | . | 10 |
| BAJFINANCE, LICHSGFIN, POONAWALLA | Yahoo | Y | Y | Y | Y | . | Y | Y | Y | Y | Y | Y | .(P: Y) | Y | Y | 4 |
| | Screener | . | Y | Y | Y | Y⁴ | . | . | Y | Y | Y | .⁵ | . | Y | . | 10 |
| SBILIFE | Yahoo | Y | Y | Y | Y | . | . | Y | Y | Y | Y | . | . | . | Y | 4 |
| | Screener | . | . | . | . | . | . | . | . | . | . | . | . | . | . | **0**⁶ |

¹ RELIANCE, TCS, INFY, HINDUNILVR, ITC, LT, MARUTI, SUNPHARMA, TITAN, ULTRACEMCO, PERSISTENT, COFORGE,
PHOENIXLTD, KALYANKJIL, SUNTV, WESTLIFE, GREAVESCOT, WELSPUNLIV, KPRMILL, EMCURE, NAVINFLUOR (identical
pattern; KALYANKJIL has 9 Screener years and EMCURE 8, since both listed recently).
² Screener *does* show Market Cap in `#top-ratios` (parsed into `top`), but `get_ratios` never maps it.
³ "Debt to equity" is not one of Screener's default free top ratios, so `top.get("Debt to equity")` is
always None.
⁴ Screener shows a ROCE (e.g. HDFCBANK 7.0%) that we copy into `ratios.roce` for banks.
⁵ Banks/NBFCs use the row label **`Borrowing`** (singular) and **`Deposits`**; `_BS_MAP` only knows
`Borrowings`.
⁶ The consolidated page returns 200 and contains "profit-loss", but every value is empty; the standalone
page is never tried.

No provider has **NIM, GNPA/NNPA, CASA, capital adequacy, AUM, or the insurer metrics (VNB, embedded
value, solvency)** as structured fields. Screener mentions NPA/CASA only in free-text pros/cons.

### What the pages actually get (merged `compute_all` + `revenue_yoy`)

| Ticker | Rev CAGR 5y | EPS CAGR | ROE % | D/E | ROCE | YoY | Note |
|---|---|---|---|---|---|---|---|
| RELIANCE | 11.1 | 7.4 | 8.7 | 0.43 | n/a | n/a | |
| TCS | 8.6 | 6.7 | 43.5 | 0.10 | n/a | n/a | Screener ROCE 63% exists, unused |
| **INFY** | **−64.1** | **−64.8** | **0.66** | 0.09 | n/a | n/a | **Yahoo USD treated as INR** |
| HINDUNILVR | 5.0 | 14.1 | 30.8 | 0.03 | n/a | n/a | |
| ITC | 6.6 | 7.5 | 28.8 | 0.01 | n/a | n/a | |
| LT | 16.1 | 17.3 | 14.5 | 1.24 | n/a | n/a | |
| MARUTI | 19.0 | 38.0 | 13.6 | 0.00 | n/a | n/a | |
| SUNPHARMA | 10.8 | 36.7 | 13.3 | 0.04 | n/a | n/a | |
| TITAN | 31.9 | 23.6 | 29.9 | 1.51 | n/a | n/a | sector map says "Conglomerate" |
| ULTRACEMCO | 13.5 | 2.2 | 10.9 | 0.40 | n/a | n/a | |
| HDFCBANK | 16.4 | 7.4 | 9.9 | (hidden) | (hidden) | n/a | rev def. mix (Y 2.50L cr vs S 3.49L cr) |
| ICICIBANK | 23.7 | 19.9 | 14.4 | | | n/a | |
| **SBIN** | **−2.7** | 23.1 | 13.1 | | | n/a | **Y 2.60L vs S 5.15L cr, wrong CAGR** |
| KOTAKBANK | 18.6 | 12.3 | 10.3 | | | n/a | |
| AXISBANK | 6.3 | 16.4 | 11.9 | | | n/a | rev def. mix |
| BAJFINANCE | 11.9 | 27.3 | 16.0 | | | n/a | Y 49.7k vs S 82.0k cr |
| **LICHSGFIN** | **−19.1** | 25.1 | 13.1 | | | n/a | Y 8.6k vs S 28.8k cr |
| SBILIFE | 11.1 | 12.7 | 13.7 | | | −4.3 | Yahoo only, so YoY works |
| PERSISTENT | 26.7 | 27.3 | 22.7 | 0.07 | n/a | n/a | |
| COFORGE | 26.3 | 20.5 | 9.8 | 0.27 | n/a | n/a | |
| PHOENIXLTD | 31.1 | 50.5 | 12.2 | 0.67 | n/a | n/a | |
| KALYANKJIL | 34.6 | 56.3 | 20.9 | 0.92 | n/a | n/a | |
| SUNTV | 4.9 | −3.2 | 11.0 | 0.01 | n/a | n/a | |
| POONAWALLA | 43.2 | 8.6 | 4.5 | (hidden) | | n/a | |
| WESTLIFE | 13.3 | n/a (neg. start) | 5.3 | 3.14 | n/a | n/a | P/E 5020 (Y) / 2891 (S): near-zero EPS, real |
| GREAVESCOT | 18.9 | n/a (neg. start) | 7.7 | 0.42 | n/a | n/a | |
| WELSPUNLIV | −2.4 | −22.6 | 4.1 | 0.47 | n/a | n/a | sector map says "CapitalGoods" (it is textiles) |
| KPRMILL | 7.2 | 0.9 | 14.6 | 0.05 | n/a | n/a | |
| EMCURE | 11.7 | 7.5 | 18.0 | 0.34 | n/a | n/a | |
| NAVINFLUOR | 22.4 | 25.2 | 15.7 | 0.28 | n/a | n/a | |

Sanity checks that passed: Screener ₹-crore values are scaled ×1e7 correctly. Yahoo and Screener revenue
for the same INR company agree within about 1–4%. Yahoo D/E is converted from percent correctly
(RELIANCE 0.44). Screener `%` values become fractions correctly. Yahoo ROE vs Screener ROE differ by up to
about 10 pts for some names (HINDUNILVR 21.6% vs 31.0%, TITAN 45% vs 38%) because they define it
differently. Yahoo is primary, so its figure wins in `ratios`.

## 3. Root causes of blanks

| Symptom | Category | Cause |
|---|---|---|
| Revenue YoY n/a (29/30) | **our bug: merge/parse** | `screener_fundamentals.py:96` `.replace(day=28)` vs Yahoo month-end; `service.py:207-219` exact-date merge → duplicate years |
| ROCE n/a (30/30) | **our bug: parse + analytics** | half-year `Sep 2026` BS column kept as annual (`_extract_series`, ~l.288); Screener BS has no current liabilities; `analytics.roce` (l.374) has no fallback to Screener's ROCE or to equity+borrowings |
| INFY garbage figures | **our bug: units** | `yahoo_fundamentals.py:115-127,228`: `financialCurrency` read, never checked or converted |
| Bank revenue CAGR wrong | **our bug: mapping** | Yahoo net revenue vs Screener gross "Revenue" merged into one series |
| SBILIFE: no Screener | **our bug: fetch** | `screener_fundamentals.py:124-134` accepts an empty consolidated page |
| Blank for 24 h after a throttle | **cache** | `screener_fundamentals.py:144` negative cache for any non-200; Yahoo `.info` `{}` cached 24 h inside raw |
| "—" card with no reason | **page swallows** | `05:282-293`, `05:735-738`, `05:830` |
| ROCE/D/E shown for banks in QW | **page bug (rule 3)** | `09:531-534`, `09:577-578` |
| Market cap missing when Yahoo `.info` fails | **our mapping** | Screener `top["Market Cap"]` not mapped (`screener get_ratios` ~l.394-413) |
| NIM/NPA/CASA/CAR | **missing at source** (Yahoo, Screener free) | only available in the NSE banking XBRL (below) |
| Exchange-filing auto fetch | **source gap** | NSE `corporates-financial-results` lists Annual/Quarterly XBRL only up to **FY2024** (HDFCBANK, WESTLIFE checked). Filings since 2025 moved to SEBI "Integrated Filing (Financials)", so the auto fetch can only store 2-year-old data |

## 4. Bank- and insurer-specific gaps

- The bank path shows P/B, ROE and P/E, which are present for every bank tested. But **ROE comes from the
  mixed series**, the **revenue CAGR is wrong**, and there are **no lender KPIs** (NIM, GNPA/NNPA,
  credit cost, CASA, CAR/CET1, loan/deposit growth).
- `Borrowing` / `Deposits` / `Financing Profit` are unmapped. That is harmless for D/E, which stays
  hidden, but it means no deposit growth and no PPOP.
- Screener's ROCE (HDFCBANK 7.0%, BAJFINANCE 10.9%) leaks into `cf.ratios.roce`, and Quality Watch shows
  it alongside Yahoo D/E for NBFCs on the deep-dive and peer tables. **This breaks CLAUDE.md rule 3.**
- The insurer SBILIFE has Yahoo data only. Revenue for insurers (gross premium plus investment income)
  is not a meaningful growth base, and no VNB / EV / solvency data exists in any source.
- **Feasibility of official filings.** `nseindia.com/api/corporates-financial-results` answered with HTTP
  200 without a login, even though the home page returned 403. The banking XBRL
  (`nsearchives.nseindia.in/corporate/xbrl/BANKING_*.xml`) downloaded and contains `InterestEarned`,
  `Deposits`, `OperatingProfitBeforeProvisionAndContingencies`, `PercentageOfGrossNpa`,
  `PercentageOfNpa`, `CET`, `AdditionalTier`, and `ProvisionsOtherThanTaxAndContingencies`. That is
  enough for GNPA/NNPA, CET1, PPOP, credit cost and deposit growth. NIM would have to be derived.
  - **Blocker:** that endpoint's newest filing is FY2024. Current data needs NSE's Integrated Filing
    endpoint (or the BSE equivalent). This was **not verified** here and needs a follow-up probe.
  - `xbrl_filing.py` maps only Ind-AS corporate tags today, not banking ones.

## 5. Prioritised fixes

| # | Fix | File:line | Effort |
|---|---|---|---|
| 1 | Date Screener columns at **month-end** (`calendar.monthrange`), and/or merge rows by fiscal year (same year-month ±15 days) instead of the exact date | `analysis/fundamentals/providers/screener_fundamentals.py:96`; `analysis/fundamentals/service.py:207-219` | S |
| 2 | Drop non-annual columns (any month ≠ the company's FY-end month, e.g. `Sep 2026` half-year) from annual P&L/BS/CF | `screener_fundamentals.py` `_extract_series` (~l.280-309) | S |
| 3 | Currency guard: if Yahoo `financialCurrency != "INR"`, convert statements with an FX rate or drop them so Screener fills in; warn on the page | `yahoo_fundamentals.py:115-127, 144-202, 228` | S–M |
| 4 | ROCE fallback: use Screener `top["ROCE"]` (or EBIT ÷ (equity + borrowings)) when current liabilities are absent; keep it hidden for financials | `analytics.py:374-399`; `screener get_ratios` ~l.394-413 | S |
| 5 | Quality Watch: sector-gate ROCE/D/E on the deep-dive metrics and the peer table (rule 3), and don't copy Screener ROCE into `ratios.roce` for financials | `dashboard/pages/09_quality_watch.py:531-534, 577-578, 160-165` | S |
| 6 | Don't mix revenue definitions: for financials, take the revenue series from a single provider (Screener's 10y gross revenue), or skip CAGR across providers whose overlapping year differs by more than 10% | `service.py` `_merge`/`_merge_series` (l.206-246) | M |
| 7 | Screener fetch: fall back to standalone when the consolidated page has no numbers; treat 429/403/5xx as a transport error (raise, no 24 h negative cache); throttle (≥1 s, ≤2 concurrent) | `screener_fundamentals.py:124-134, 144` | S |
| 8 | Make empty data visible on Analyze Stock: return None from `_cached_fund_card` when `not cf.has_any_data()`; set `_fv_fund_missing=True` when `_cached_valuation` raises; show `missing_fields` and the reason | `05_analyze_stock.py:291-293, 735-738, 830` | S |
| 9 | Filing provider: return `None` ratios when nothing is stored, so the "Sources" label stops listing filings that don't exist | `providers/filing_fundamentals.py:171-172` | S |
| 10 | Map Screener `Market Cap` (×1e7), `Borrowing`, `Deposits`, `Financing Profit`; correct the Yahoo-only data note | `screener_fundamentals.py:50-61, 394-413`; `05:2340` | S |
| 11 | Quality Watch scan: fewer workers (4–6) so nifty500 doesn't trip Yahoo/Screener rate limits | `09_quality_watch.py:229` | S |
| 12 | Bank and insurer KPIs from NSE banking XBRL, after confirming the post-2024 Integrated Filing endpoint (GNPA, NNPA, CET1, PPOP, deposits, credit cost) | `data/nse_filings_xbrl.py`, `analysis/fundamentals/xbrl_filing.py` | L |
| 13 | Sector-map errors seen here (WELSPUNLIV → CapitalGoods, TITAN → Conglomerate) | `data/universe.py` SECTOR_MAP | S |

Fixes 1–4 together restore Revenue YoY and ROCE for about 29/30 tickers and remove the INFY and bank
CAGR errors. Re-run `fund_check.py` before and after to confirm. Changes to `analytics.py` and
`service.py` move valuation postures, so the `verdict-regression-reviewer` must run.

## 6. Screener.in Premium (₹4,999/yr): verdict

**It would not materially help. Free public pages plus NSE/BSE filings are enough.**

- Every gap in this audit is on our side: dates, half-year columns, currency, label mapping, empty
  consolidated pages, caching and page handling. The free page already carries 10 years of P&L, balance
  sheet, cash flow, the ratios section, Market Cap, ROCE and ROE.
- Premium's Excel export holds essentially the same statements. Screens and custom ratios are a UI
  convenience and add no source the app lacks.
- The one real data gap is the lender and insurer KPIs (NPA, CAR, CASA, NIM). As far as I know, Premium's
  export does not provide these as structured fields either; I did not verify this. The official NSE
  banking XBRL does provide them.
- A Premium export would also need a logged-in session. That conflicts with the current anonymous-scrape
  design and adds credential handling.
- Spend the effort on fixes 1–9 first.

---
*Probe limits: one live pass on 2026-11-25. Stored filings were not read (DB stubbed) and the auto fetch
was disabled, so on the live app the "Exchange/ROC filing" labels depend on what is stored. Quarterly
(`period="quarterly"`) paths were not probed.*
