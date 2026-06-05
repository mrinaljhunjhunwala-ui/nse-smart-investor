# Phase D1 — Sector-Aware Fundamentals — Implementation Report

Primary goal: **eliminate incorrect analysis of financial companies** and establish the sector-aware
framework future metrics depend on. Secondary: add **ROCE + FCF** where economically meaningful.
**No historical bands, no cheap/expensive labels, no peer comparison, no new providers, no DCF.**

**Result: ✅ done.** **196 passing** (166 prior + 30 new). The bank-leverage false-negative is gone.

## 1. Architecture changes
- **New single source of truth:** `analysis/sector_classification.py` → `classify_sector(raw, name)`
  returns a `SectorProfile` whose booleans encode **per-metric applicability**
  (`leverage_warning_applies`, `ev_ebitda_meaningful`, `roce_meaningful`, `fcf_meaningful`,
  `fcf_capex_caveat`) plus `preferred_valuation` and an explanatory `note`. **No applicability logic
  is hardcoded anywhere else** — Thesis, Valuation and (future) analytics all read this profile.
- **Financials guard** is enforced through that profile, not scattered `if sector == "bank"` checks.
- **Explanatory context replaces suppressed outputs:** `ThesisResult.notes` and
  `ValuationContext.notes` carry *why* a metric was withheld.

## 2. Files modified / added
| File | Change |
|---|---|
| `analysis/sector_classification.py` | **NEW** — SectorProfile + classify_sector (the SoT) |
| `analysis/fundamentals/analytics.py` | **NEW** `roce()`, `free_cash_flow()`; added to `compute_all` |
| `analysis/fundamentals/valuation.py` | sector-aware: suppress EV/EBITDA for financials + notes/preferred |
| `analysis/thesis/thesis_models.py` | `ThesisInputs.{roce,fcf,sector_profile}`; `ThesisResult.notes` |
| `analysis/thesis/thesis_rules.py` | leverage rules gated; ROCE/FCF factors; `sector_notes()` |
| `analysis/thesis/thesis_engine.py` | classify sector in `build_inputs`; ROCE/FCF + notes wired |
| `dashboard/pages/04_analyze_stock.py` | sector note, ROCE/FCF (gated), EV/EBITDA n/a + preferred lens |
| `tests/test_sector_aware.py` | **NEW** — 30 deterministic tests |

## 3. New metrics added
- **ROCE** = `EBIT / (Total Assets − Current Liabilities)`. Source: existing normalized statements
  (`operating_income`, `total_assets`, `current_liabilities`). Edge cases: any input missing →
  unavailable (None); non-positive capital employed → unavailable. **No estimation, no new network.**
- **Free Cash Flow** (₹ cr) = `CashFlow.free_cash_flow` (already populated / derived as OCF − capex).
  Missing → unavailable; sign preserved (never zeroed).
- Both are **suppressed for financials** and **carry a capex caveat** for capital-intensive sectors.

## 4. Test counts
| Group | Tests |
|---|---|
| Sector routing (banks/NBFC/insurance/IT/consumer/capex/unknown/None) | 9 |
| Financials guard in thesis (bank/NBFC/insurance/non-fin/legacy/suppression) | 7 |
| ROCE calculation + edges | 4 |
| FCF calculation + edges | 3 |
| ROCE/FCF thesis integration + capex note | 5 |
| Valuation guard | 2 |
| **Total new** | **30** |
| **Full suite** | **196 passed** (166 prior, untouched) |

## 5. Example outputs (before → after)

**Bank — D/E = 9.0** (the headline fix)
- **Before:** Risk — *"High leverage — sensitive to rates and earnings shocks" (D/E = 9.00x)* ❌ false negative on every bank.
- **After:** no leverage risk; **note:** *"Banks fund operations with customer deposits, so debt/equity, EV/EBITDA, ROCE and free cash flow are not economically meaningful… assessed on P/B, ROE and asset quality."* Valuation EV/EBITDA → **n/a**, preferred lens **P/B + ROE**.

**NBFC / Insurance** — same suppression; insurer flagged via name hint (P/EV preferred).

**Capital goods (L&T) — D/E = 2.0, ROCE 18%, FCF −₹1,500 cr**
- Leverage risk **still fires** (non-financial); **Bull:** *"High return on capital employed (ROCE = 18.0%)"*; negative FCF → **note** *"reflects an ongoing capex cycle… not necessarily a red flag"* — **not** a bear.

**IT (TCS) — ROCE 45%, FCF +₹40,000 cr** → **Bull:** *"High return on capital employed"*, *"Generates positive free cash flow"*.

**Consumer (HUL) — FCF +₹8,000 cr** → **Bull:** *"Generates positive free cash flow"*.

## Part E verification — factors remain economically meaningful
| Sector | Leverage warning | EV/EBITDA | ROCE | FCF | Correct? |
|---|---|---|---|---|---|
| Banks / NBFC / Insurance | **suppressed** + note | **n/a** + note | suppressed | suppressed | ✅ no false leverage flag |
| Manufacturing / Auto | applies | shown | bull/bear | bull/bear | ✅ |
| Capital goods / Power / Metals / Infra | applies | shown | bull/bear | bull + **capex caveat** on negative | ✅ no false "cash burn" |
| Consumer / IT | applies | shown | bull/bear | bull/bear | ✅ quality surfaced |

## Scope honoured (NOT implemented)
Historical valuation bands · cheap/expensive labels · peer comparison · new providers · DCF.
Backward-compatible: with no `sector_profile`, behaviour is unchanged (legacy leverage warning still
fires — covered by `test_no_profile_preserves_legacy_leverage_warning`).

## Net effect
The platform no longer mislabels India's largest sector. Banks/NBFCs/insurers are analysed on the
right lens with explanatory context instead of a spurious leverage red flag, ROCE and FCF now surface
quality for the real economy (with capex-aware wording), and every future metric can route through one
`SectorProfile` instead of re-deriving "is this a financial?".
