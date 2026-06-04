"""analysis/fundamentals/models.py — vendor-neutral normalized schema.

The UI and analytics depend ONLY on these dataclasses (and FundamentalsService).
No vendor field names leak past the adapter boundary.

Conventions:
  * Every numeric field is Optional[float] and defaults to None. A missing value is
    None — NEVER substituted with 0 (0 is a real, different number).
  * Monetary values are absolute INR (adapters normalize vendor units at the edge).
  * ratios.roe / roce / roa / margins are stored as FRACTIONS (0.18 == 18%).
    ratios.debt_to_equity is a RATIO (0.45 == 0.45x).
  * Period lists are newest-first and keyed by FiscalPeriod.period_end.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Dict, List, Literal, Optional

PeriodType = Literal["annual", "quarterly"]


@dataclass(frozen=True)
class FiscalPeriod:
    period_end: Optional[date] = None
    fiscal_year: Optional[int] = None
    period_type: PeriodType = "annual"
    currency: str = "INR"


@dataclass
class IncomeStatement:
    period: FiscalPeriod
    revenue: Optional[float] = None
    cost_of_revenue: Optional[float] = None
    gross_profit: Optional[float] = None
    operating_income: Optional[float] = None   # EBIT
    ebitda: Optional[float] = None
    interest_expense: Optional[float] = None
    pretax_income: Optional[float] = None
    tax_expense: Optional[float] = None
    net_income: Optional[float] = None
    eps_basic: Optional[float] = None
    eps_diluted: Optional[float] = None
    shares_diluted: Optional[float] = None


@dataclass
class BalanceSheet:
    period: FiscalPeriod
    total_assets: Optional[float] = None
    current_assets: Optional[float] = None
    current_liabilities: Optional[float] = None
    total_liabilities: Optional[float] = None
    short_term_debt: Optional[float] = None
    long_term_debt: Optional[float] = None
    total_debt: Optional[float] = None
    cash_and_equivalents: Optional[float] = None
    total_equity: Optional[float] = None       # shareholders' equity (ex-minority)


@dataclass
class CashFlow:
    period: FiscalPeriod
    operating_cash_flow: Optional[float] = None
    capital_expenditure: Optional[float] = None  # normalized to a positive outflow
    free_cash_flow: Optional[float] = None       # = OCF - capex (derived if absent)
    investing_cash_flow: Optional[float] = None
    financing_cash_flow: Optional[float] = None
    dividends_paid: Optional[float] = None


@dataclass
class RatioSnapshot:
    as_of: Optional[date] = None
    roe: Optional[float] = None                 # fraction
    roce: Optional[float] = None                # fraction
    roa: Optional[float] = None                 # fraction
    debt_to_equity: Optional[float] = None      # ratio (x)
    current_ratio: Optional[float] = None
    gross_margin: Optional[float] = None
    operating_margin: Optional[float] = None
    net_margin: Optional[float] = None
    pe: Optional[float] = None
    pb: Optional[float] = None


@dataclass
class CompanyFundamentals:
    """The single object the UI + analytics consume."""
    symbol: str
    company_name: Optional[str] = None
    provider_name: Optional[str] = None
    statement_date: Optional[date] = None       # latest annual period_end available
    last_updated: Optional[datetime] = None     # when fetched / normalized
    currency: str = "INR"

    income_statements: List[IncomeStatement] = field(default_factory=list)   # newest-first
    balance_sheets: List[BalanceSheet] = field(default_factory=list)
    cash_flows: List[CashFlow] = field(default_factory=list)
    ratios: Optional[RatioSnapshot] = None

    # provenance: "metric path" -> provider name (e.g. "income.revenue" -> "YahooFinance")
    provenance: Dict[str, str] = field(default_factory=dict)
    is_partial: bool = False
    missing_fields: List[str] = field(default_factory=list)

    # ── convenience accessors (no vendor logic; pure schema navigation) ──────
    def latest_income(self) -> Optional[IncomeStatement]:
        return self.income_statements[0] if self.income_statements else None

    def latest_balance(self) -> Optional[BalanceSheet]:
        return self.balance_sheets[0] if self.balance_sheets else None

    def latest_cashflow(self) -> Optional[CashFlow]:
        return self.cash_flows[0] if self.cash_flows else None

    def has_any_data(self) -> bool:
        return bool(self.income_statements or self.balance_sheets
                    or self.cash_flows or self.ratios)
