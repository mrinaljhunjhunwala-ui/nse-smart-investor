"""Fundamentals from official XBRL filings stored per ticker.

Two sources, one shape (analysis.fundamentals.xbrl_filing.parse_xbrl output):
  * "roc"      — MCA / Registrar of Companies AOC-4 XBRL the owner uploaded.
  * "exchange" — annual results XBRL fetched from NSE (data/nse_filings_xbrl.py).

Stored in the KV store under user `_system`, key `filing_fund:<SOURCE>:<SYMBOL>`,
as {"symbol", "source", "file_name", "saved_at", "company_name", "cin",
"consolidated", "periods": [...]}. Several uploads for one ticker merge by
period_end (newest upload wins for a period), so years of AOC-4s build a history.
"""
from __future__ import annotations

import contextlib
import datetime as _dt
import logging
from typing import Any, Dict, List, Optional

from ..models import (
    BalanceSheet, CashFlow, FiscalPeriod, IncomeStatement, PeriodType, RatioSnapshot,
)
from ..provider import FundamentalProvider

_log = logging.getLogger("analysis.fundamentals.filing")

SOURCES = {"roc": "ROC filing (MCA upload)", "exchange": "Exchange filing (NSE XBRL)"}
_KV_USER = "_system"


def _base(symbol: str) -> str:
    return str(symbol).upper().replace(".NS", "").replace(".BO", "").strip()


def _key(source: str, symbol: str) -> str:
    return f"filing_fund:{source}:{_base(symbol)}"


def load_filing(source: str, symbol: str) -> Optional[Dict[str, Any]]:
    try:
        import trade_store as store
        rec = store.kv_get(_key(source, symbol), None, user_id=_KV_USER)
    except Exception as e:
        _log.warning("filing load failed for %s/%s: %s", source, symbol, e)
        return None
    return rec if isinstance(rec, dict) and rec.get("periods") else None


def save_filing(source: str, symbol: str, parsed: Dict[str, Any], file_name: str = "") -> Dict[str, Any]:
    """Merge a parsed filing into the stored record for this ticker and return it."""
    if source not in SOURCES:
        raise ValueError(f"unknown filing source {source!r}")
    if not parsed.get("periods"):
        raise ValueError("the filing has no recognisable financial periods")
    prev = load_filing(source, symbol) or {}
    by_end = {p["period_end"]: p for p in prev.get("periods", [])}
    for p in parsed["periods"]:
        by_end[p["period_end"]] = p
    rec = {
        "symbol": _base(symbol), "source": source, "file_name": file_name,
        "saved_at": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
        "company_name": parsed.get("company_name") or prev.get("company_name"),
        "cin": parsed.get("cin") or prev.get("cin"),
        "consolidated": parsed.get("consolidated"),
        "periods": sorted(by_end.values(), key=lambda p: p["period_end"], reverse=True),
    }
    import trade_store as store
    if not store.kv_set(_key(source, symbol), rec, user_id=_KV_USER):
        raise RuntimeError("could not save the filing (storage unavailable)")
    try:                                   # the Auto cascade reads stored filings too
        from ..service import forget_symbol
        forget_symbol(symbol)
    except Exception as e:
        _log.debug("cache refresh after saving %s/%s failed: %s", source, symbol, e)
    return rec


def _fp(p: Dict[str, Any]) -> FiscalPeriod:
    end = _dt.date.fromisoformat(p["period_end"])
    return FiscalPeriod(period_end=end, fiscal_year=end.year if end.month <= 3 else end.year + 1)


class FilingFundamentalProvider(FundamentalProvider):
    """Normalized statements from a stored filing. Annual only; no price ratios."""

    def __init__(self, source: str, loader=load_filing):
        if source not in SOURCES:
            raise ValueError(f"unknown filing source {source!r}")
        self.source = source
        self.name = SOURCES[source]
        self._loader = loader
        self._held: Optional[tuple] = None     # (symbol, record) during batch()

    @contextlib.contextmanager
    def batch(self, symbol: str):
        """Read the stored record once for a whole statement assembly (the
        service calls five getters per provider; the Auto cascade runs this for
        every ticker, so one KV read instead of seven)."""
        self._held = (symbol, self._loader(self.source, symbol))
        try:
            yield self
        finally:
            self._held = None

    def _record(self, symbol: str) -> Optional[Dict[str, Any]]:
        if self._held is not None and self._held[0] == symbol:
            return self._held[1]
        return self._loader(self.source, symbol)

    def _periods(self, symbol: str, period: PeriodType, limit: int) -> List[Dict[str, Any]]:
        if period != "annual":
            return []
        rec = self._record(symbol)
        return (rec or {}).get("periods", [])[:limit]

    def company_info(self, symbol: str) -> Dict[str, Any]:
        rec = self._record(symbol) or {}
        return {"company_name": rec.get("company_name"), "currency": "INR"}

    def get_income_statement(self, symbol, period="annual", limit=10):
        out = []
        for p in self._periods(symbol, period, limit):
            i = p.get("income", {})
            pretax, interest = i.get("pretax_income"), i.get("interest_expense")
            ebit = pretax + interest if pretax is not None and interest is not None else None
            dep = i.get("depreciation")
            out.append(IncomeStatement(
                period=_fp(p), revenue=i.get("revenue"), operating_income=ebit,
                ebitda=ebit + dep if ebit is not None and dep is not None else None,
                interest_expense=interest, pretax_income=pretax, tax_expense=i.get("tax_expense"),
                net_income=i.get("net_income"), eps_basic=i.get("eps_basic"),
                eps_diluted=i.get("eps_diluted")))
        return out

    def get_balance_sheet(self, symbol, period="annual", limit=10):
        out = []
        for p in self._periods(symbol, period, limit):
            b = p.get("balance", {})
            if not b:
                continue
            lt, st = b.get("long_term_debt"), b.get("short_term_debt")
            debt = (lt or 0.0) + (st or 0.0) if (lt is not None or st is not None) else None
            out.append(BalanceSheet(
                period=_fp(p), total_assets=b.get("total_assets"),
                current_assets=b.get("current_assets"),
                current_liabilities=b.get("current_liabilities"),
                total_liabilities=b.get("total_liabilities"), short_term_debt=st,
                long_term_debt=lt, total_debt=debt,
                cash_and_equivalents=b.get("cash_and_equivalents"),
                total_equity=b.get("total_equity")))
        return out

    def get_cash_flow(self, symbol, period="annual", limit=10):
        out = []
        for p in self._periods(symbol, period, limit):
            c = p.get("cash", {})
            if not c:
                continue
            ocf, capex = c.get("operating_cash_flow"), c.get("capital_expenditure")
            capex = abs(capex) if capex is not None else None
            out.append(CashFlow(
                period=_fp(p), operating_cash_flow=ocf, capital_expenditure=capex,
                free_cash_flow=ocf - capex if ocf is not None and capex is not None else None,
                investing_cash_flow=c.get("investing_cash_flow"),
                financing_cash_flow=c.get("financing_cash_flow"),
                dividends_paid=abs(c["dividends_paid"]) if c.get("dividends_paid") is not None else None))
        return out

    def get_ratios(self, symbol):
        inc = self.get_income_statement(symbol)
        bal = self.get_balance_sheet(symbol)
        if not inc and not bal:
            return RatioSnapshot()
        i, b = (inc[0] if inc else None), (bal[0] if bal else None)

        def div(a, c):
            return a / c if a is not None and c not in (None, 0) else None
        return RatioSnapshot(
            as_of=(i or b).period.period_end,
            roe=div(i and i.net_income, b and b.total_equity),
            roa=div(i and i.net_income, b and b.total_assets),
            debt_to_equity=div(b and b.total_debt, b and b.total_equity),
            current_ratio=div(b and b.current_assets, b and b.current_liabilities),
            operating_margin=div(i and i.operating_income, i and i.revenue),
            net_margin=div(i and i.net_income, i and i.revenue))
