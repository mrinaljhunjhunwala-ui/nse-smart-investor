# Provider-Agnostic Fundamentals Architecture (Design)

**Status:** design only — no data collection, no API keys, no implementation. This document
defines the *contracts* (interface + normalized schema + analytics mapping) so a later build is
a mechanical fill-in, and so the **UI and analytics never touch a vendor field**.

## Goals & principles
1. **Vendor independence** — UI/analytics depend only on the normalized schema + a facade. Swapping or
   adding a provider is configuration, not a UI change.
2. **Tiering, like the price layer** — an ordered provider list (e.g. EODHD primary → yfinance fallback),
   mirroring the existing `Angel → Stooq → Yahoo` pattern, with **per-field gap-fill** and **provenance**.
3. **Gaps are first-class** — every normalized field is `Optional`; analytics return `None` + a reason
   (surfaced, never silently wrong — consistent with the production-audit policy).
4. **Units normalized at the edge** — each adapter converts vendor units (crores, %, sign conventions)
   to a single canonical unit (**INR absolute**) so cross-vendor merge is safe.
5. **Pure analytics** — the six analytics are pure functions of the schema; no I/O, fully unit-testable.

---

## 1. Normalized internal schema (the contract)

Design (dataclasses shown for the contract; **all values INR absolute unless noted; every field `Optional`**):

```python
PeriodType = Literal["annual", "quarterly"]

@dataclass(frozen=True)
class FiscalPeriod:
    period_end: date          # canonical key for cross-vendor period alignment
    fiscal_year: int
    period_type: PeriodType
    currency: str = "INR"

@dataclass
class IncomeStatementPeriod:
    period: FiscalPeriod
    revenue: Optional[float]
    cost_of_revenue: Optional[float]
    gross_profit: Optional[float]
    operating_income: Optional[float]     # EBIT  (drives ROCE)
    ebitda: Optional[float]
    interest_expense: Optional[float]
    pretax_income: Optional[float]
    tax_expense: Optional[float]
    net_income: Optional[float]           # drives ROE
    eps_basic: Optional[float]
    eps_diluted: Optional[float]          # drives EPS CAGR
    shares_diluted: Optional[float]

@dataclass
class BalanceSheetPeriod:
    period: FiscalPeriod
    total_assets: Optional[float]         # drives ROCE
    current_assets: Optional[float]
    current_liabilities: Optional[float]  # drives ROCE
    total_liabilities: Optional[float]
    short_term_debt: Optional[float]
    long_term_debt: Optional[float]
    total_debt: Optional[float]           # = short+long if vendor gives only parts; drives D/E
    cash_and_equivalents: Optional[float]
    total_equity: Optional[float]         # shareholders' equity, ex-minority; drives ROE & D/E

@dataclass
class CashFlowPeriod:
    period: FiscalPeriod
    operating_cash_flow: Optional[float]  # drives FCF
    capital_expenditure: Optional[float]  # normalized to POSITIVE outflow; drives FCF
    free_cash_flow: Optional[float]       # = OCF − capex (derived if vendor omits)
    investing_cash_flow: Optional[float]
    financing_cash_flow: Optional[float]
    dividends_paid: Optional[float]

@dataclass
class RatioSnapshot:                      # latest snapshot; vendor-supplied OR derived
    as_of: date
    roe: Optional[float]
    roce: Optional[float]
    roa: Optional[float]
    debt_to_equity: Optional[float]
    current_ratio: Optional[float]
    gross_margin: Optional[float]
    operating_margin: Optional[float]
    net_margin: Optional[float]
    pe: Optional[float]
    pb: Optional[float]

@dataclass
class CompanyFundamentals:                # the ONLY object UI/analytics consume
    ticker: str                           # normalized e.g. "RELIANCE.NS"
    name: Optional[str]
    sector: Optional[str]
    currency: str
    income:   list[IncomeStatementPeriod] # newest-first, aligned by FiscalPeriod
    balance:  list[BalanceSheetPeriod]
    cashflow: list[CashFlowPeriod]
    ratios:   Optional[RatioSnapshot]
    provenance: dict[str, str]            # "income.revenue" -> "EODHD" (per-field source)
    is_partial: bool                      # any required field unresolved
    missing: list[str]                    # human-readable list of gaps (for the UI caption)
```

---

## 2. The abstraction layer — `FundamentalProvider`

```python
class FundamentalProvider(ABC):
    name: str                                  # "EODHD" | "YahooFinance" | "FinEdge"

    def is_available(self) -> bool: ...        # configured + healthy (cheap probe)

    @abstractmethod
    def get_income_statement(self, ticker: str, period: PeriodType = "annual",
                             limit: int = 10) -> list[IncomeStatementPeriod]: ...
    @abstractmethod
    def get_balance_sheet(self, ticker: str, period: PeriodType = "annual",
                          limit: int = 10) -> list[BalanceSheetPeriod]: ...
    @abstractmethod
    def get_cash_flow(self, ticker: str, period: PeriodType = "annual",
                      limit: int = 10) -> list[CashFlowPeriod]: ...
    @abstractmethod
    def get_ratios(self, ticker: str) -> RatioSnapshot: ...   # vendor ratios OR derived
```

**Contract rules every adapter obeys** — return **normalized objects only** (never raw vendor JSON);
normalize units/signs at the edge; return `[]` / `None` fields on gaps (don't raise for missing data,
raise only on transport failure); key every period by `FiscalPeriod.period_end`.

### Orchestration facade — `FundamentalsService` (where tiering lives)

```python
class FundamentalsService:
    def __init__(self, providers: list[FundamentalProvider], cache): ...
    def get_fundamentals(self, ticker, period="annual", years=10) -> CompanyFundamentals:
        # 1. cache hit?  (server-side, ~24 h TTL — fundamentals change quarterly)
        # 2. primary = first provider where is_available(); fetch the 4 statements
        # 3. per-field / per-period GAP-FILL from the next available provider
        # 4. derive missing (total_debt, free_cash_flow, ratios) from statements
        # 5. stamp provenance + is_partial + missing; cache; return
```

UI/analytics call **only** `FundamentalsService` and read **only** `CompanyFundamentals`.

---

## 3. Adapter designs (mapping only — no fetch code)

Each adapter = *fetch (out of scope) → map vendor field → normalize unit/sign → schema*. The mapping is
the design deliverable.

### 3a. YahooFinanceAdapter (yfinance) — free fallback
| Normalized | yfinance source | Unit/sign note |
|---|---|---|
| `revenue` | `income_stmt.loc["Total Revenue"]` | INR absolute |
| `net_income` | `income_stmt.loc["Net Income"]` | |
| `operating_income` (EBIT) | `income_stmt.loc["Operating Income"/"EBIT"]` | |
| `eps_diluted` | `income_stmt.loc["Diluted EPS"]` or `info["trailingEps"]` | |
| `total_assets / current_liabilities / total_equity` | `balance_sheet.loc[...]` | |
| `total_debt` | `balance_sheet.loc["Total Debt"]` else short+long | |
| `operating_cash_flow / capital_expenditure` | `cashflow.loc[...]` | capex sign → abs |
| `ratios.roe` | `info["returnOnEquity"]` | already a fraction |
| `ratios.debt_to_equity` | `info["debtToEquity"]` | **vendor gives %, ÷100** |
| `ratios.roce` | — | **derive** (yfinance has no ROCE) |
**Limits:** ~4 yr annual / patchy quarterly; gaps common on small-caps → mark `is_partial`.

### 3b. EODHDAdapter — recommended primary
| Normalized | EODHD source (`/fundamentals/{TICKER}.NSE`) | Note |
|---|---|---|
| income lines | `Financials.Income_Statement.yearly[FY]` | revenue/EBIT/netIncome/eps |
| balance lines | `Financials.Balance_Sheet.yearly[FY]` | assets/curLiab/equity/debt |
| cash-flow lines | `Financials.Cash_Flow.yearly[FY]` | OCF/capex → FCF derive |
| `ratios.roe / roa / margins / pe / pb` | `Highlights`, `Valuation` | vendor-supplied |
| `ratios.roce` | — | **derive** (not pre-computed) |
**Strengths:** 21-yr depth, 100k calls/day, licensed REST. India small-cap depth = pilot-gated.

### 3c. FinEdgeAdapter — India-native alternate
| Normalized | FinEdge source (NSE/BSE endpoints) | Note |
|---|---|---|
| P&L / BS / CF lines | `/pnl`, `/balance-sheet`, `/cash-flow` | India naming; likely **INR crore → ×1e7** |
| `ratios.roe / roce / debt_to_equity` | `/ratios` | **ROCE pre-computed** |
**Strengths:** India-native, ROCE pre-computed. **Risk:** small/new vendor → secondary, never sole.

> Adding a provider = one new subclass + one mapping table. **Nothing upstream changes.**

---

## 4. Analytics → normalized-schema mapping

Pure functions over `CompanyFundamentals`; each prefers statements, falls back to vendor `RatioSnapshot`.

| Analytic | Normalized fields used | Formula | Fallback |
|---|---|---|---|
| **Revenue CAGR** | `income[].revenue`, `period_end` | `(rev_end / rev_start) ** (1/yrs) − 1` | — (needs ≥2 periods) |
| **EPS CAGR** | `income[].eps_diluted` (or `net_income/shares_diluted`) | `(eps_end / eps_start) ** (1/yrs) − 1` | net_income CAGR if EPS absent |
| **ROE** | `income[0].net_income`, `balance[0].total_equity` | `net_income / avg(total_equity)` | `ratios.roe` |
| **ROCE** | `income[0].operating_income`, `balance[0].total_assets`, `current_liabilities` | `EBIT / (total_assets − current_liabilities)` | `ratios.roce` |
| **Debt/Equity** | `balance[0].total_debt`, `total_equity` | `total_debt / total_equity` | `ratios.debt_to_equity` |
| **Free Cash Flow (trend)** | `cashflow[].operating_cash_flow`, `capital_expenditure` | `OCF − capex` per period → series | `cashflow[].free_cash_flow` |

Each returns `Optional` + a `reason` when inputs are missing (e.g. *"ROCE unavailable: EBIT missing for FY24"*), surfaced in the UI — never a silent zero.

---

## 5. Architecture diagram

```
┌──────────────────────────────────────────────────────────────────────┐
│  UI:  Analyze Stock · Portfolio · (future) Bull/Bear brief            │
│  Analytics:  revenue_cagr · eps_cagr · roe · roce · d/e · fcf_series  │
│        ▲  depend ONLY on  CompanyFundamentals  + FundamentalsService  │
└────────┼─────────────────────────────────────────────────────────────┘
         │
┌────────┴─────────────────────────────────────────────────────────────┐
│  FundamentalsService (facade)                                         │
│   tiering · 24h cache · per-field gap-fill · derive · provenance      │
└────────┬─────────────────────────────────────────────────────────────┘
         │  FundamentalProvider interface (4 methods) — vendor-neutral
   ┌─────┼───────────────┬────────────────────┐
   ▼     ▼               ▼                    ▼
EODHDAdapter      YahooFinanceAdapter    FinEdgeAdapter      ← map + normalize units
   │                     │                    │
EODHD REST          yfinance/Yahoo        FinEdge REST       ← vendor data (OUT OF SCOPE)
```

## 6. Data flow (per request)
1. `analytics.roe("RELIANCE.NS")` → `FundamentalsService.get_fundamentals(...)`.
2. **Cache check** (key `ticker|period|years`, 24 h TTL). Hit → return `CompanyFundamentals`.
3. Miss → **primary** provider (`is_available()`): `get_income_statement / balance_sheet / cash_flow / ratios`.
4. Adapter maps vendor → schema, **normalizes units/signs**, aligns by `period_end`.
5. **Gap-fill**: any missing field/period pulled from the next available provider; `provenance` stamped per field.
6. **Derive** `total_debt`, `free_cash_flow`, and any missing ratio from statements.
7. Assemble `CompanyFundamentals` (+ `is_partial`, `missing`), cache, return.
8. Analytics compute over the schema → `Optional` value + reason → UI renders value or a "data unavailable" caption.

## 7. Implementation effort (for the later build — not now)
| Component | Effort | Notes |
|---|---|---|
| Schema + `FundamentalProvider` ABC + `FundamentalsService` + cache/provenance | **M (~2–3 d)** | no network; fully unit-testable with fixtures |
| 6 analytics functions + tests | **S (~1 d)** | pure functions; reuse CAGR test pattern |
| YahooFinanceAdapter | **S (~1 d)** | uses existing yfinance plumbing |
| EODHDAdapter | **S (~1 d)** | + the field-validation **pilot** (the real cost) |
| FinEdgeAdapter | **S (~1 d)** | optional/secondary |
| Coverage/provenance monitor (which provider served, gap %) | **S** | ops visibility |
**Contract layer (schema+ABC+service+analytics) ≈ 1 week; each adapter ≈ 1 day. The gating cost is data validation, not code.**

## 8. Migration strategy
- **Phase 0 — contract on free data.** Build schema + ABC + service + the 6 analytics with the
  **YahooFinanceAdapter only** (free, already wired). Ship behind a feature flag, accept yfinance limits.
  *De-risks the contract independently of any paid contract.*
- **Phase 1 — promote EODHD.** After the memo's pilot passes (≥90% / ≥8-yr), add `EODHDAdapter` and set
  service order `[EODHD, Yahoo]`. **Zero UI/analytics change** (they depend only on the schema).
- **Phase 2 — add FinEdge** as a secondary for coverage A/B; provenance shows which served.
- **Rollback** is config: reorder/disable a provider in the service list; the schema contract is unchanged.
- **No data migration** — fundamentals are additive to the existing technical score; nothing existing changes.

---

### Summary
One interface (`FundamentalProvider`, 4 methods), one normalized object (`CompanyFundamentals`), one
facade (`FundamentalsService`) that does tiering + gap-fill + provenance + cache, and six pure analytics
functions mapped to the schema. Providers are interchangeable adapters; the UI and analytics engine never
see a vendor field. Build the contract on free Yahoo data first, then promote EODHD behind the same
interface — adding or swapping a provider is a one-file adapter and a list reorder.
