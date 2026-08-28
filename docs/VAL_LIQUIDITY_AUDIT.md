# Phase C Capability Audit — Valuation & Liquidity Context

What's the **minimum data + analytics** to add (1) Valuation Context and (2) Liquidity Context to
the "explain this stock" flow? Capability mapping + gap analysis only — **no implementation**.

## Headline
Most of Phase C is **closer than it looks**. Two facts drive everything:
1. **Every price fetch already carries `Volume`** (`data.fetcher.fetch_single` → OHLC**V**, all three
   tiers) — so average daily turnover and volume trends need **zero new data**.
2. **Yahoo's `info` dict is already fetched** (`yahoo_fundamentals._raw(...)["info"]`) but only a
   *subset* is mapped into the schema. EV/EBITDA, market cap, shares outstanding, float shares and
   average volume are **already in the response we pull** — they just aren't captured. Surfacing them
   is field-mapping, not new network.

The genuinely missing pieces are the *context* layers — **own-history valuation bands** (medium) and
**sector-relative valuation** + **true free float** + **live spread** (advanced, data-gated).

---

## 1. Valuation Context

| Metric | Current availability | Missing | Data-source requirement | Complexity | User value |
|---|---|---|---|---|---|
| **P/E** | ✅ In schema — `RatioSnapshot.pe` (Yahoo `trailingPE`); not surfaced in UI/analytics | A *baseline* (own-history / sector) to judge cheap-vs-rich; raw multiple alone is not "context" | None — already fetched | **Low** (display + crude absolute flag) | **High** |
| **P/B** | ✅ In schema — `RatioSnapshot.pb` (Yahoo `priceToBook`); not surfaced | Same baseline gap | None — already fetched | **Low** | **High** (esp. financials/asset-heavy) |
| **EV/EBITDA** | 🟡 Partial — `IncomeStatement.ebitda` present; **`info["enterpriseToEbitda"]` is fetched but not mapped**; no EV/EBITDA ratio field | A `RatioSnapshot.ev_ebitda` field + mapping (or compute EV = mktcap + debt − cash, ÷ EBITDA) | None — already in `info`; fallback uses existing balance sheet | **Low–Medium** | **High** (capital-light vs levered comparability) |
| **Historical valuation bands** | ❌ Not available | A historical P/E (and P/B) **time series** + percentile bands | Price history (✅ have) ÷ **TTM EPS** series (derive from quarterly income statements ✅ have) / BVPS | **Medium** (build TTM EPS, align to prices, percentile bands, handle gaps) | **High** — this is the real "context" (cheap vs its *own* history) |
| **Sector-relative valuation** | ❌ Not available | Cross-sectional peer multiples (sector median / percentile) | Fetch P/E·P/B·EV-EBITDA for the **whole sector peer set** + a peer-universe map + caching | **High** (batch fetch; Yahoo per-ticker is slow + small-cap gaps → ideally a bulk feed e.g. EODHD) | **High** but **data-gated** |

**Honesty caveat:** a raw P/E with no baseline can mislead (a "low" P/E is often a value trap). So the
*point multiples* (C1) are easy, but the genuine cheap/expensive **judgment** depends on the
bands/peers (C2/C3). C1 should show the numbers + EV/EBITDA and reserve the verdict for later.

---

## 2. Liquidity Context

| Metric | Current availability | Missing | Data-source requirement | Complexity | User value |
|---|---|---|---|---|---|
| **Average daily turnover** | ✅ **Computable now** — `mean(Close × Volume)` over N days from existing OHLCV | Nothing — just not computed/surfaced | None | **Low** (trivial) | **High** — the core tradability signal; flags illiquid small-caps |
| **Volume trends** | ✅ **Computable now** — recent vs longer-window average volume (the score's volume component already uses a 20-day ratio) | Nothing | None | **Low** | **Medium–High** (accumulation/distribution, dry-up) |
| **Free-float proxies** | 🟡 Partial — **`info` has `floatShares`, `sharesOutstanding`, `heldPercentInsiders/Institutions`** but none are captured | Map those fields; true promoter/pledge float not in Yahoo | Existing Yahoo `info` for the proxy; **NSE/BSE shareholding pattern** for true float | **Low–Medium** (map fields; coverage spotty for Indian small-caps) | **Medium** (float-adjusted turnover; manipulation risk) |
| **Execution risk** | ❌ Derived metric, not present | A composite (turnover + float-adj turnover + volatility, optional bid-ask spread) | Turnover/vol (✅ have); **bid-ask spread / depth needs live quotes** (Angel One depth — optional) | **Medium** (composite; spread optional) | **High** — actionable ("hard to exit at size") |

---

## Recommended phasing

### Phase C1 — high value / low effort  *(surface what already exists)*
- **Display P/E and P/B** (already in `RatioSnapshot`) with a *crude* absolute band flag only.
- **Average daily turnover + volume trend** from existing OHLCV → a **liquidity tier**
  (High / Medium / Low / Illiquid) with a small-cap tradability caveat.
- **Map the already-fetched Yahoo `info` extras** into the schema (one provider change, zero new
  network): `enterpriseToEbitda` → **EV/EBITDA**, plus `marketCap`, `sharesOutstanding`,
  `floatShares`, `averageVolume` → enables a **free-float proxy** and float-adjusted turnover.
- **Effort: Small. Value: High.** Delivers point-multiples + EV/EBITDA + a real turnover/liquidity
  signal + a float proxy with essentially no new data. Must degrade gracefully (None, never fabricate)
  given Yahoo's small-cap gaps.

### Phase C2 — medium effort  *(the genuine "context" layer)*
- **Own-history valuation bands** — TTM-EPS-derived P/E (and P/B) percentile bands: *"18x vs its own
  12–22x 5-yr range (62nd percentile)."* Price history ÷ TTM EPS from existing quarterly statements.
- **Execution-risk tier** — composite of turnover + float-adjusted turnover + volatility (spread
  optional). Turns raw turnover into an actionable "can I exit at size?" flag.
- **Effort: Medium. Value: High.** This is what makes valuation/liquidity *context* rather than just
  numbers.

### Phase C3 — advanced  *(cross-sectional + true float + live cost)*
- **Sector-relative valuation** — peer-set median/percentile for P/E·P/B·EV-EBITDA. Needs a peer
  universe + batch fundamentals + caching; Yahoo per-ticker is slow and gappy for small-caps → best
  paired with a **bulk fundamentals feed (EODHD)**.
- **True free float** — promoter/pledge from **NSE/BSE shareholding pattern** (a new source).
- **Live execution cost** — bid-ask spread / market depth via **Angel One depth** for a real slippage
  estimate.
- **Effort: Large. Value: High but data-gated** (new providers / cost).

---

## Net recommendation
Do **C1 first** — it's mostly *surfacing data we already fetch* (Volume for turnover; the unmapped
Yahoo `info` valuation/float fields) and gives outsized value for small effort. **C2** adds the
own-history bands + execution-risk tier that turn numbers into judgment. **C3** is gated on new data
sources (peer fundamentals, NSE/BSE shareholding, live depth) and should wait until a bulk
fundamentals feed lands. Throughout, follow the platform's existing rule: **None when unavailable,
never a fabricated value** — Yahoo's coverage of Indian small/mid-caps is the main risk.

*Audit only — no features implemented.*
