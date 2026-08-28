# Decision Memo — Fundamentals Data Source for NSE Smart Investor

> **Superseded:** the EODHD recommendation below was revisited in `EODHD_DECISION_AUDIT.md`,
> which reached a **NO-GO** on any paid provider. Production stays on the free
> Yahoo-backed `YahooFundamentalProvider`. This memo is kept for its evaluation-matrix
> research, not as the current decision.

**Question:** which data source should be the production foundation for fundamental analytics
(ROE, ROCE, Revenue CAGR, EPS CAGR, Debt/Equity, Free-Cash-Flow trends) on NSE/BSE stocks?

**Recommendation (TL;DR):** adopt a **licensed REST fundamentals API as the production primary —
EODHD (EOD Historical Data) is the lead candidate (~$50–60/mo)** — with **yfinance as a free
gap-fill fallback**, mirroring the app's existing tiered-data philosophy (Angel → Stooq → Yahoo).
**Do not scrape Screener.in or NSE for production** (ToS + reliability). Gate the final pick behind
a **2-day coverage pilot** on the live ~217-stock universe, because Indian *small-cap* depth is the
one thing every vendor's marketing under-specifies.

---

## Evaluation matrix

Metrics legend — ✅ provided / pre-computed · 🟡 derivable from statements · ❌ absent.

| Source | NSE coverage | Revenue | EPS | ROE | ROCE | D/E | Cash Flow / FCF | Hist. depth | Quality | Rate limits | Legal/compliance | Reliability | Cost |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| **yfinance** (Yahoo) | Most large/mid `.NS`; sparse small-cap | ✅ | ✅ | ✅ (`info`) | 🟡 derive | ✅ (`info`) | 🟡 (OCF−CapEx) | ~4 yr annual, patchy qtr | **Inconsistent** (gaps, unit quirks) | Unofficial; throttles / IP-bans on bulk; cookie/crumb auth fragile | Yahoo ToS forbids commercial use/redistribution — **gray** | **Low–Med** (breaks on Yahoo changes) | Free |
| **NSE direct** (nseindia.com) | All NSE (source of truth) | 🟡 (XBRL/PDF) | 🟡 | ❌ compute | ❌ compute | 🟡 | 🟡 | Years of filings (unaggregated) | Authoritative but **unstructured** | Aggressive anti-bot; ToS restricts automated access | **Restricted** (scraping discouraged) | **Low** (anti-bot + XBRL parsing) | Free data / high eng cost |
| **Screener.in** | **4,000+ NSE/BSE incl. small-cap** | ✅ | ✅ | ✅ | ✅ **pre-computed** | ✅ | ✅ + CAGRs | **10+ yr** | **Best-in-class** for India | **No official API** → HTML scrape | **Scraping violates ToS — production legal/compliance risk** | Med data / Low if scraping (HTML + anti-bot) | "Free" to scrape (not licensable) |
| **EODHD** ⭐ | 70+ exchanges incl. NSE/BSE *(verify depth)* | ✅ | ✅ | ✅ (Highlights) | 🟡 derive (EBIT ÷ cap-employed) | ✅ (Balance Sheet) | ✅ statements | Non-US from 2000 (**21 yr major / 6 yr minor**) | Good, structured JSON | **100k calls/day, 1,000/min** | **Licensed commercial REST** | **Med–High** | **$49.99–59.99/mo** ($599.90/yr) |
| **FMP** | NSE supported (e.g. Reliance), 25k+ stocks | ✅ | ✅ | ✅ | ✅ (ratios endpoint) | ✅ | ✅ statements | 30+ yr (US-centric) | Good; India small-cap depth less proven | Bandwidth-tiered (20 GB+/mo) | Licensed commercial REST | Med–High | ~$99/mo Premium (cheaper Starter tiers exist) |
| **Trendlyne** | 4,000+ NSE/BSE | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | 10+ yr | High (consumer-grade) | Excel-Connect / downloads, **not a clean app-backend REST API** | Per-account licence; redistribution limited | Med | ₹5,900/yr (StratQ) |
| **Tijori** | Broad NSE/BSE + alt-data | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | 10+ yr | High; alt/operational focus | B2B/opaque API access | Licensed (enterprise) | Med | Premium / quote-based |
| **FinEdge API** | India-native NSE/BSE *(unverified depth)* | ✅ | ✅ | ✅ | ✅ (ratios) | ✅ | ✅ | n/a (verify) | Unverified | Unverified | REST, India-native | **Vendor-risk: small/new** | Unverified |

> **ROCE note:** only Screener / FMP / Trendlyne / Tijori / FinEdge expose ROCE *pre-computed*. With
> EODHD/yfinance you compute it from statements — `ROCE = EBIT ÷ (Total Assets − Current Liabilities)`
> — a one-line formula, so this is **not** a differentiator.

---

## Why not the "obvious" free options

- **Screener.in has the best Indian data, but it is disqualified for production.** It offers **no
  public API**; the only access is HTML scraping, which **violates its Terms of Service**, exposes the
  business to legal/compliance risk, and is operationally fragile (markup changes, anti-bot). It
  remains excellent for **manual analyst spot-checks**, not as an automated backend.
- **NSE direct** is the source of truth but ships **filings/XBRL, not computed ratios**, behind
  aggressive anti-bot defences and a restrictive ToS — high effort, low reliability as a primary feed.
- **yfinance** is fine for a **prototype** and as a **free fallback**, but Yahoo's NSE fundamentals are
  inconsistent (gaps, unit quirks, ~4-yr depth), the endpoint is unofficial (the app already fights
  Yahoo's cookie/crumb fragility), and the ToS doesn't license commercial use. Not a production primary.

## Why EODHD as the production primary

1. **Licensed commercial REST API** — removes the ToS/legal cloud that kills Screener/NSE/yfinance.
2. **Covers the six target analytics** — Highlights (EPS, ROE, ROA, margins, valuation) + full annual
   & quarterly **income / balance / cash-flow** statements → Revenue & EPS **CAGR**, **D/E**, and **FCF**
   trends fall straight out; **ROCE** is a trivial derivation.
3. **Production-grade limits** — 100k calls/day, 1,000/min comfortably covers a 217-stock universe
   refreshed daily, with headroom to expand.
4. **Predictable cost** — **~$50–60/mo** flat; no per-call surprises.
5. **Fits the existing architecture** — slots in as a new tier exactly like Angel/Stooq/Yahoo, with
   **yfinance as the free fallback** for any field EODHD lacks on a given symbol.

**Runner-up: FMP** — comparable API quality and an explicit ratios endpoint (incl. ROCE), but pricier
at the production tier and its **Indian small-cap depth is less proven**. Keep as the alternate if the
pilot shows EODHD gaps. **FinEdge** (India-native, possibly cheaper) is worth a look but carries
**small-vendor longevity/SLA risk** — acceptable only as a secondary, not the sole dependency.

---

## The one real risk → a mandatory pre-commit pilot (2 days, ~$60)

Every vendor advertises "global coverage"; the failure mode for India is **small/micro-cap gaps and
stale quarterly updates**. Before committing UI work:

1. Buy one month of EODHD Fundamentals; pull all **~217 universe tickers** (`RELIANCE.NSE`, etc.).
2. For each, check the **six metrics resolve** (Revenue, EPS, ROE, D/E, OCF & CapEx for FCF) and that
   **≥8 years** of annual statements exist (needed for credible CAGR).
3. Record **coverage % and freshness** (days since latest filing). **Accept if ≥90% of the universe
   resolves all six with ≥8-yr depth**; otherwise re-run the same probe on FMP/FinEdge and pick the
   winner. Spot-check 10 names against Screener.in (manual) for accuracy.

## Compliance guardrails (apply to whichever wins)
- Display **derived analytics** to your own users (allowed); **do not** re-expose the vendor's raw
  feed as a competing data product (redistribution is restricted in every licence here).
- Cache vendor responses server-side (cuts calls + cost); attribute the data source in the UI.
- Keep credentials in secrets (same pattern as Angel One); never client-side.

## Recommended foundation
**Primary:** EODHD Fundamentals API (licensed, REST, ~$50–60/mo) → **Fallback:** yfinance (free, gap-fill,
clearly flagged) → **Validation only:** Screener.in (manual). Decision is **pilot-gated**: ship the
data layer only after the 217-stock coverage probe clears the ≥90% / ≥8-yr bar.

---

### Sources
- EODHD — [pricing](https://eodhd.com/pricing) · [fundamentals feed](https://eodhd.com/financial-apis/stock-etfs-fundamental-data-feeds) · [financial APIs](https://eodhd.com/financial-apis/)
- Financial Modeling Prep — [site](https://site.financialmodelingprep.com/) · [pricing](https://site.financialmodelingprep.com/pricing-plans)
- Screener.in coverage & history — [Winvesta 2026 guide](https://www.winvesta.in/blog/investors/fundamental-analysis-tools-and-screeners-2026-guide) · scraping context — [Apify Screener.in](https://apify.com/shashwattrivedi/screener-in/api)
- Trendlyne — [screeners (ROE/ROCE)](https://trendlyne.com/stock-screeners/fundamentals/) · Tijori — [markets](https://www.tijorifinance.com/in/markets)
- FinEdge API (India-native NSE/BSE fundamentals) — [finedgeapi.com](https://www.finedgeapi.com/)
- Comparison context — [Best Free Finance APIs: EODHD vs FMP vs Alpha Vantage vs Yahoo](https://noteapiconnector.com/best-free-finance-apis)
