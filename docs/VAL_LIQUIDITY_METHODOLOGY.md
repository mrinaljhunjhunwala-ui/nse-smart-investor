# Valuation & Liquidity Context — Methodology (Phase C1)

How Phase C1 surfaces valuation multiples and liquidity signals that already exist in the
fundamentals + price infrastructure. **No new data providers. No peer comparison. No valuation
bands. No cheap/expensive judgment** — factual context only.

## 1. Valuation Context (`analysis/fundamentals/valuation.py`)

`ValuationContext` — `pe`, `pb`, `ev_ebitda`, `confidence`, `missing_fields`, `source`.

**Source.** All three multiples already exist in the fundamentals schema:
- `RatioSnapshot.pe` ← Yahoo `info["trailingPE"]`
- `RatioSnapshot.pb` ← Yahoo `info["priceToBook"]`
- `RatioSnapshot.ev_ebitda` ← Yahoo `info["enterpriseToEbitda"]` — **the only new mapping in C1**
  (the field was already in the `info` dict we fetch; it just wasn't captured). No new network.

**Validity rule — never fabricate.** A multiple is accepted only if it is a **positive, finite**
number. A non-positive P/E (loss-making) or a NaN/inf is reported as **unavailable (None)**, not as a
misleading value. This matches the platform's existing "None, never 0" analytics contract.

**Confidence** is a coverage signal (how many of the three are present): 3 → high · 2 → medium ·
1 → low · 0 → none. `missing_fields` lists the absent multiples by label.

**Deliberately excluded (later phases):** historical bands (C2), sector-relative percentiles (C3),
any cheap/expensive verdict.

## 2. Liquidity Context (`analysis/liquidity.py`)

`LiquidityContext` — `avg_daily_volume_30d`, `avg_daily_turnover_30d`, `volume_trend_ratio`,
`volume_trend`, `liquidity_tier`, `n_days`, `reason`.

**Source.** Existing OHLCV only — `data.fetcher.fetch_single` returns a `Volume` column on every tier
(Angel → Stooq → Yahoo). `compute_liquidity(df)` is pure; `liquidity_for_ticker` is the fetch seam.

**Computations** (last 30 trading days):
```
avg_daily_volume_30d  = mean(Volume[-30:])
avg_daily_turnover_30d = mean(Close[-30:] × Volume[-30:])      # ₹
volume_trend_ratio    = mean(Volume[-30:]) / mean(Volume[-90:])  (needs ≥90 days)
```
`volume_trend` = rising (ratio ≥ 1.20) · falling (≤ 0.80) · stable otherwise.

**Liquidity tiers** (NSE ₹ daily turnover):
| Tier | Avg daily turnover |
|---|---|
| **High** | ≥ ₹25 cr |
| **Medium** | ≥ ₹5 cr |
| **Low** | ≥ ₹50 lakh |
| **Illiquid** | < ₹50 lakh |

With < 30 days of volume the tier is **Unknown** and turnover is None (degrades gracefully).

## 3. Thesis integration (`analysis/thesis`)
Two new **factual** liquidity factors (no valuation judgment):
- **Bull** — tier High → *"High liquidity supports easy entry and exit"* · Liquidity ·
  `Avg daily turnover ₹X cr (High tier)`.
- **Risk** — tier Low/Illiquid → *"Low liquidity may increase execution risk"* · Liquidity ·
  `Avg daily turnover ₹X (… tier)`.

Medium contributes nothing. `ThesisInputs` gains `liquidity_tier` + `avg_daily_turnover`; the engine
adds `Liquidity` to provenance when present. **No valuation factors are generated** in C1.

## 4. Portfolio Fit integration (`analysis/thesis/portfolio_fit.py`)
The candidate's liquidity tier feeds **position-size guidance**:
- **Illiquid → capped at Small** regardless of other factors ("a large position would be hard to
  exit").
- **Low → counts as one risk pressure** (alongside high correlation / beta / volatility / sector
  concentration).
- High / Medium → no penalty.

## Honesty & scope
- **None when unavailable; never fabricated** — applies to every multiple and liquidity figure.
- **No cheap/expensive labels, no peer comparison, no bands** — C1 is pure surfacing. The judgment
  layer is C2 (own-history bands) / C3 (sector-relative), per `VAL_LIQUIDITY_AUDIT.md`.
- **No new providers** — EV/EBITDA is a field already present in the Yahoo response; liquidity is
  derived from price data already fetched.
