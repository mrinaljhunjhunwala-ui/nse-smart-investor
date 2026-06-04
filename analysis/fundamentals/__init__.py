"""Provider-agnostic fundamentals package (Phase 0 — Yahoo only).

Public surface the UI/analytics may depend on:
    from analysis.fundamentals import FundamentalsService, default_service
    from analysis.fundamentals.models import CompanyFundamentals
    from analysis.fundamentals import analytics
"""
from .models import (
    BalanceSheet, CashFlow, CompanyFundamentals, FiscalPeriod, IncomeStatement,
    RatioSnapshot,
)
from .provider import FundamentalProvider
from .service import FundamentalsService, default_service

__all__ = [
    "CompanyFundamentals", "IncomeStatement", "BalanceSheet", "CashFlow",
    "RatioSnapshot", "FiscalPeriod", "FundamentalProvider",
    "FundamentalsService", "default_service",
]
