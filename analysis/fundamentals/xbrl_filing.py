"""analysis/fundamentals/xbrl_filing.py — read an Ind-AS XBRL financial filing.

Two official sources ship the same audited numbers as XBRL:
  * MCA / Registrar of Companies — the AOC-4 (XBRL) financial statements a
    company files every year. Downloaded by the owner from MCA21 (login +
    fee), then uploaded on Analyze Stock.
  * NSE / BSE — the annual financial results listed companies file with the
    exchange, fetched automatically by data/nse_filings_xbrl.py.

Both use Ind-AS taxonomies whose element *local names* overlap
(RevenueFromOperations, ProfitLossForPeriod, Assets, BorrowingsNoncurrent …),
so this parser matches on local name and ignores the namespace prefix. Pure
stdlib (xml.etree); no network, no Streamlit.

parse_xbrl() returns a plain dict:
    {"company_name", "cin", "periods": [ {period_end, income{…}, balance{…},
     cash{…}} newest-first ], "consolidated": bool | None, "warnings": [...]}
Values are rupees as filed (XBRL facts carry absolute amounts; a `decimals`
attribute only states precision). Missing tags stay absent — never zero.
"""
from __future__ import annotations

import datetime as _dt
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional, Tuple

# field -> candidate element local names, first match wins
_INCOME = {
    "revenue": ("RevenueFromOperations", "Revenue", "RevenueFromOperationsNet"),
    "other_income": ("OtherIncome",),
    "total_income": ("Income", "TotalIncome"),
    "interest_expense": ("FinanceCosts",),
    "depreciation": ("DepreciationDepletionAndAmortisationExpense",
                     "DepreciationAndAmortisationExpense", "DepreciationDepletionAndAmortisation"),
    "pretax_income": ("ProfitBeforeTax", "ProfitLossBeforeTax",
                      "ProfitLossBeforeTaxFromContinuingOperations"),
    "tax_expense": ("TaxExpense", "IncomeTaxExpenseContinuingOperations"),
    "net_income": ("ProfitLossAttributableToOwnersOfParent", "ProfitLossForPeriod",
                   "ProfitLoss", "ProfitLossForThePeriod"),
    "eps_basic": ("BasicEarningsLossPerShareFromContinuingAndDiscontinuedOperations",
                  "BasicEarningsLossPerShareFromContinuingOperations",
                  "BasicEarningsLossPerShare", "BasicEarningsPerShare"),
    "eps_diluted": ("DilutedEarningsLossPerShareFromContinuingAndDiscontinuedOperations",
                    "DilutedEarningsLossPerShareFromContinuingOperations",
                    "DilutedEarningsLossPerShare", "DilutedEarningsPerShare"),
}
_BALANCE = {
    "total_assets": ("Assets", "TotalAssets"),
    "current_assets": ("CurrentAssets",),
    "current_liabilities": ("CurrentLiabilities",),
    "total_liabilities": ("Liabilities",),
    "long_term_debt": ("BorrowingsNoncurrent", "NoncurrentBorrowings", "LongTermBorrowings"),
    "short_term_debt": ("BorrowingsCurrent", "CurrentBorrowings", "ShortTermBorrowings"),
    "cash_and_equivalents": ("CashAndCashEquivalents",),
    "total_equity": ("EquityAttributableToOwnersOfParent", "Equity", "TotalEquity",
                     "ShareholdersFunds"),
}
_CASH = {
    "operating_cash_flow": ("CashFlowsFromUsedInOperatingActivities",
                            "NetCashFlowsFromUsedInOperatingActivities"),
    "capital_expenditure": ("PurchaseOfPropertyPlantAndEquipment",
                            "PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities"),
    "investing_cash_flow": ("CashFlowsFromUsedInInvestingActivities",
                            "NetCashFlowsFromUsedInInvestingActivities"),
    "financing_cash_flow": ("CashFlowsFromUsedInFinancingActivities",
                            "NetCashFlowsFromUsedInFinancingActivities"),
    "dividends_paid": ("DividendsPaidClassifiedAsFinancingActivities", "DividendsPaid"),
}
_NAME_TAGS = ("NameOfCompany", "EntityName", "NameOfTheCompany")
_CIN_TAGS = ("CorporateIdentityNumber", "CIN")
_CONSOLIDATED_TAGS = ("NatureOfReportStandaloneConsolidated", "TypeOfReport",
                      "WhetherResultsAreAuditedOrUnaudited")


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag.split(":")[-1]


def _date(text: Optional[str]) -> Optional[_dt.date]:
    try:
        return _dt.date.fromisoformat((text or "").strip()[:10])
    except ValueError:
        return None


def _contexts(root: ET.Element) -> Dict[str, Tuple[Optional[_dt.date], Optional[_dt.date], bool]]:
    """context id -> (start, end_or_instant, has_dimensions)."""
    out = {}
    for el in root.iter():
        if _local(el.tag) != "context":
            continue
        start = end = None
        dims = False
        for sub in el.iter():
            name = _local(sub.tag)
            if name == "startDate":
                start = _date(sub.text)
            elif name in ("endDate", "instant"):
                end = _date(sub.text)
            elif name in ("segment", "scenario") and len(list(sub)):
                dims = True
        out[el.get("id", "")] = (start, end, dims)
    return out


def parse_xbrl(data: bytes | str) -> Dict[str, Any]:
    """Parse one Ind-AS XBRL instance. Raises ValueError if it isn't XML."""
    try:
        root = ET.fromstring(data if isinstance(data, (bytes, str)) else bytes(data))
    except ET.ParseError as e:
        raise ValueError(f"not a valid XBRL/XML file: {e}") from e
    ctx = _contexts(root)

    # facts[local_name] = list of (end, start, value), dimensionless contexts only
    facts: Dict[str, List[Tuple[_dt.date, Optional[_dt.date], float]]] = {}
    text_facts: Dict[str, str] = {}
    for el in root.iter():
        cref = el.get("contextRef")
        if not cref or cref not in ctx:
            continue
        start, end, dims = ctx[cref]
        name = _local(el.tag)
        raw = (el.text or "").strip()
        if not raw:
            continue
        if name in _NAME_TAGS + _CIN_TAGS + _CONSOLIDATED_TAGS:
            text_facts.setdefault(name, raw)
            continue
        if dims or end is None:
            continue
        try:
            val = float(raw)
        except ValueError:
            continue
        facts.setdefault(name, []).append((end, start, val))

    # Annual periods: duration contexts of ~12 months; BS facts are instants on the same end.
    ends = sorted({e for rows in facts.values() for e, s, _ in rows
                   if s is not None and 300 <= (e - s).days <= 400}, reverse=True)
    warnings: List[str] = []
    if not ends:
        ends = sorted({e for rows in facts.values() for e, _, _ in rows}, reverse=True)[:1]
        if ends:
            warnings.append("no 12-month period found; using the latest dated facts")

    def pick(tags, end, duration: bool):
        for t in tags:
            for e, s, v in facts.get(t, []):
                if e != end:
                    continue
                if duration and (s is None or not 300 <= (e - s).days <= 400):
                    continue
                if not duration and s is not None:
                    continue
                return v
        return None

    periods = []
    for end in ends[:2]:                      # current year + comparative
        inc = {k: v for k, tags in _INCOME.items() if (v := pick(tags, end, True)) is not None}
        cash = {k: v for k, tags in _CASH.items() if (v := pick(tags, end, True)) is not None}
        bal = {k: v for k, tags in _BALANCE.items() if (v := pick(tags, end, False)) is not None}
        if inc or bal or cash:
            periods.append({"period_end": end.isoformat(), "income": inc,
                            "balance": bal, "cash": cash})
    if not periods:
        warnings.append("no recognised Ind-AS financial facts in this file")

    kind = " ".join(text_facts.get(t, "") for t in _CONSOLIDATED_TAGS).lower()
    consolidated = True if "consolidated" in kind and "standalone" not in kind else (
        False if "standalone" in kind else None)
    return {
        "company_name": next((text_facts[t] for t in _NAME_TAGS if t in text_facts), None),
        "cin": next((text_facts[t] for t in _CIN_TAGS if t in text_facts), None),
        "consolidated": consolidated,
        "periods": periods,
        "warnings": warnings,
    }
