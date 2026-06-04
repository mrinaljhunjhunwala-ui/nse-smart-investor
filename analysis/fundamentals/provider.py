"""analysis/fundamentals/provider.py — the provider abstraction.

Every data vendor is wrapped in a FundamentalProvider subclass that returns ONLY the
normalized schema (models.py) — never raw vendor objects/field names. Adding a vendor =
one new subclass; nothing upstream (service, analytics, UI) changes.

Contract rules for every adapter:
  * return normalized objects; map + unit-normalize at the edge.
  * return [] / None fields on missing DATA — do NOT raise for missing data.
  * raise only on TRANSPORT failure (network/auth) so the service can fall back/log.
  * key each period by FiscalPeriod.period_end.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List

from .models import (
    BalanceSheet, CashFlow, IncomeStatement, PeriodType, RatioSnapshot,
)


class FundamentalProvider(ABC):
    #: human-readable provider name, recorded in provenance (e.g. "YahooFinance")
    name: str = "abstract"

    def is_available(self) -> bool:
        """Cheap probe — is this provider configured and usable? Default: yes."""
        return True

    @abstractmethod
    def get_income_statement(self, symbol: str, period: PeriodType = "annual",
                             limit: int = 10) -> List[IncomeStatement]:
        ...

    @abstractmethod
    def get_balance_sheet(self, symbol: str, period: PeriodType = "annual",
                          limit: int = 10) -> List[BalanceSheet]:
        ...

    @abstractmethod
    def get_cash_flow(self, symbol: str, period: PeriodType = "annual",
                      limit: int = 10) -> List[CashFlow]:
        ...

    @abstractmethod
    def get_ratios(self, symbol: str) -> RatioSnapshot:
        ...
