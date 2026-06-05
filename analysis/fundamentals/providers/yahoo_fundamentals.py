"""analysis/fundamentals/providers/yahoo_fundamentals.py

The ONLY module in the fundamentals stack that imports yfinance. It fetches raw Yahoo
financial statements + `info`, then maps them to the normalized schema, normalizing
units/signs at the edge. Raw responses are cached (24 h) so the four get_* calls for one
symbol share a single network fetch.

Yahoo notes encoded here:
  * statement values are absolute INR (no crore scaling needed).
  * `info["debtToEquity"]` is a PERCENT (45.2) → stored as a ratio (0.452).
  * `info["returnOnEquity"]` / margins are already FRACTIONS.
  * capex is reported negative (outflow) → normalized to a positive number.
  * coverage is ~4 annual years and patchy for small-caps → callers see is_partial.
"""
from __future__ import annotations

import logging
from datetime import date
from typing import List, Optional

import pandas as pd

from ..cache import TTLCache
from ..models import (
    BalanceSheet, CashFlow, FiscalPeriod, IncomeStatement, PeriodType, RatioSnapshot,
)
from ..provider import FundamentalProvider

_log = logging.getLogger("fundamentals.yahoo")

# normalized field -> ordered candidate Yahoo row labels (label set varies by yf version)
_INCOME_MAP = {
    "revenue":          ["Total Revenue", "Operating Revenue", "TotalRevenue"],
    "cost_of_revenue":  ["Cost Of Revenue", "Reconciled Cost Of Revenue"],
    "gross_profit":     ["Gross Profit"],
    "operating_income": ["EBIT", "Operating Income", "Total Operating Income As Reported"],
    "ebitda":           ["EBITDA", "Normalized EBITDA"],
    "interest_expense": ["Interest Expense", "Interest Expense Non Operating"],
    "pretax_income":    ["Pretax Income"],
    "tax_expense":      ["Tax Provision", "Income Tax Expense"],
    "net_income":       ["Net Income", "Net Income Common Stockholders",
                         "Net Income From Continuing Operation Net Minority Interest"],
    "eps_basic":        ["Basic EPS"],
    "eps_diluted":      ["Diluted EPS"],
    "shares_diluted":   ["Diluted Average Shares", "Diluted Average Shares Outstanding"],
}
_BALANCE_MAP = {
    "total_assets":        ["Total Assets"],
    "current_assets":      ["Current Assets", "Total Current Assets"],
    "current_liabilities": ["Current Liabilities", "Total Current Liabilities"],
    "total_liabilities":   ["Total Liabilities Net Minority Interest", "Total Liabilities"],
    "short_term_debt":     ["Current Debt", "Current Debt And Capital Lease Obligation",
                            "Short Long Term Debt"],
    "long_term_debt":      ["Long Term Debt", "Long Term Debt And Capital Lease Obligation"],
    "total_debt":          ["Total Debt"],
    "cash_and_equivalents":["Cash And Cash Equivalents",
                            "Cash Cash Equivalents And Short Term Investments"],
    "total_equity":        ["Stockholders Equity", "Common Stock Equity",
                            "Total Equity Gross Minority Interest"],
}
_CASHFLOW_MAP = {
    "operating_cash_flow":  ["Operating Cash Flow", "Cash Flow From Continuing Operating Activities",
                             "Total Cash From Operating Activities"],
    "capital_expenditure":  ["Capital Expenditure", "Capital Expenditures", "Purchase Of PPE"],
    "free_cash_flow":       ["Free Cash Flow"],
    "investing_cash_flow":  ["Investing Cash Flow", "Total Cashflows From Investing Activities"],
    "financing_cash_flow":  ["Financing Cash Flow", "Total Cash From Financing Activities"],
    "dividends_paid":       ["Cash Dividends Paid", "Common Stock Dividend Paid"],
}


def _to_date(col) -> Optional[date]:
    try:
        return pd.Timestamp(col).date()
    except Exception:
        return None


def _f(x) -> Optional[float]:
    """Coerce a raw cell to float, or None (NaN/blank → None, never 0)."""
    try:
        if x is None or pd.isna(x):
            return None
        return float(x)
    except (TypeError, ValueError):
        return None


def _row(df: "pd.DataFrame", candidates) -> Optional["pd.Series"]:
    if df is None or getattr(df, "empty", True):
        return None
    for label in candidates:
        if label in df.index:
            return df.loc[label]
    return None


class YahooFundamentalProvider(FundamentalProvider):
    name = "YahooFinance"

    def __init__(self, raw_cache: Optional[TTLCache] = None):
        self._raw_cache = raw_cache or TTLCache(name="yahoo-raw")

    def is_available(self) -> bool:
        try:
            import yfinance  # noqa: F401
            return True
        except Exception:
            return False

    # ── raw fetch (the only network seam — monkeypatched in tests) ───────────
    def _fetch_raw(self, symbol: str, period: PeriodType) -> dict:
        import yfinance as yf
        tk = yf.Ticker(symbol)
        if period == "quarterly":
            inc, bal, cfl = tk.quarterly_income_stmt, tk.quarterly_balance_sheet, tk.quarterly_cashflow
        else:
            inc, bal, cfl = tk.income_stmt, tk.balance_sheet, tk.cashflow
        try:
            info = tk.info or {}
        except Exception:
            info = {}
        return {"income": inc, "balance": bal, "cashflow": cfl, "info": info}

    def _raw(self, symbol: str, period: PeriodType) -> dict:
        key = f"raw|{symbol}|{period}"
        cached = self._raw_cache.get(key)
        if cached is not None:
            return cached
        try:
            raw = self._fetch_raw(symbol, period)
        except Exception as e:   # transport failure → surface so the service can fall back
            _log.warning("Yahoo raw fetch failed symbol=%s: %s: %s",
                         symbol, type(e).__name__, e)
            raise RuntimeError(f"Yahoo fetch failed for {symbol}: {e}") from e
        self._raw_cache.set(key, raw)
        return raw

    # ── normalized statement builders ───────────────────────────────────────
    def get_income_statement(self, symbol, period: PeriodType = "annual",
                             limit: int = 10) -> List[IncomeStatement]:
        df = self._raw(symbol, period).get("income")
        if df is None or getattr(df, "empty", True):
            return []
        rows = {k: _row(df, c) for k, c in _INCOME_MAP.items()}
        out: List[IncomeStatement] = []
        for col in list(df.columns)[:limit]:
            d = _to_date(col)
            stmt = IncomeStatement(
                period=FiscalPeriod(period_end=d, fiscal_year=d.year if d else None,
                                    period_type=period),
                **{k: (_f(r[col]) if r is not None else None) for k, r in rows.items()},
            )
            out.append(stmt)
        return out

    def get_balance_sheet(self, symbol, period: PeriodType = "annual",
                          limit: int = 10) -> List[BalanceSheet]:
        df = self._raw(symbol, period).get("balance")
        if df is None or getattr(df, "empty", True):
            return []
        rows = {k: _row(df, c) for k, c in _BALANCE_MAP.items()}
        out: List[BalanceSheet] = []
        for col in list(df.columns)[:limit]:
            d = _to_date(col)
            vals = {k: (_f(r[col]) if r is not None else None) for k, r in rows.items()}
            # derive total_debt if vendor gave only the parts
            if vals.get("total_debt") is None:
                st, lt = vals.get("short_term_debt"), vals.get("long_term_debt")
                if st is not None or lt is not None:
                    vals["total_debt"] = (st or 0.0) + (lt or 0.0)
            out.append(BalanceSheet(
                period=FiscalPeriod(period_end=d, fiscal_year=d.year if d else None,
                                    period_type=period), **vals))
        return out

    def get_cash_flow(self, symbol, period: PeriodType = "annual",
                      limit: int = 10) -> List[CashFlow]:
        df = self._raw(symbol, period).get("cashflow")
        if df is None or getattr(df, "empty", True):
            return []
        rows = {k: _row(df, c) for k, c in _CASHFLOW_MAP.items()}
        out: List[CashFlow] = []
        for col in list(df.columns)[:limit]:
            d = _to_date(col)
            vals = {k: (_f(r[col]) if r is not None else None) for k, r in rows.items()}
            # capex → positive outflow
            if vals.get("capital_expenditure") is not None:
                vals["capital_expenditure"] = abs(vals["capital_expenditure"])
            # derive FCF if absent but OCF + capex present
            if vals.get("free_cash_flow") is None:
                ocf, capex = vals.get("operating_cash_flow"), vals.get("capital_expenditure")
                if ocf is not None and capex is not None:
                    vals["free_cash_flow"] = ocf - capex
            out.append(CashFlow(
                period=FiscalPeriod(period_end=d, fiscal_year=d.year if d else None,
                                    period_type=period), **vals))
        return out

    def get_ratios(self, symbol: str) -> RatioSnapshot:
        info = self._raw(symbol, "annual").get("info") or {}
        d2e = _f(info.get("debtToEquity"))
        return RatioSnapshot(
            as_of=date.today(),
            roe=_f(info.get("returnOnEquity")),
            roce=None,                                   # Yahoo has no ROCE — derived later
            roa=_f(info.get("returnOnAssets")),
            debt_to_equity=(d2e / 100.0) if d2e is not None else None,   # percent → ratio
            current_ratio=_f(info.get("currentRatio")),
            gross_margin=_f(info.get("grossMargins")),
            operating_margin=_f(info.get("operatingMargins")),
            net_margin=_f(info.get("profitMargins")),
            pe=_f(info.get("trailingPE")),
            pb=_f(info.get("priceToBook")),
            # already present in the Yahoo `info` we fetch — just surfaced now (Phase C1)
            ev_ebitda=_f(info.get("enterpriseToEbitda")),
        )

    def company_info(self, symbol: str) -> dict:
        info = self._raw(symbol, "annual").get("info") or {}
        return {"company_name": info.get("longName") or info.get("shortName"),
                "sector": info.get("sector"),
                "currency": info.get("financialCurrency") or "INR"}
