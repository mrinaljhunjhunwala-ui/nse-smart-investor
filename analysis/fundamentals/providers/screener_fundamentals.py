"""analysis/fundamentals/providers/screener_fundamentals.py

Screener.in scraper — free, deep coverage for every listed NSE/BSE company.
Used as a *fill-in* behind YahooFinance where Yahoo returns None (small/mid-cap gap).

Design rules (same as Yahoo provider):
  * Return normalized `models.*` objects only. Map + unit-normalize at the edge.
  * Missing DATA → None / [] (never raise; never zero-fill).
  * Only TRANSPORT failures raise, so the service can log & fall back.
  * Screener statement values are in Rs. Crore → multiplied by 1e7 to match the
    absolute-INR convention Yahoo already uses.
  * Ratios shown as "18%" become fractions (0.18). Debt/Equity is a ratio.

Symbol resolution:
  * "BAJHIND.NS" → tries `/company/BAJHIND/consolidated/` first, falls back to
    standalone `/company/BAJHIND/`. Consolidated is preferred where available.
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime
from typing import Dict, List, Optional

import requests

from ..cache import TTLCache
from ..models import (
    BalanceSheet, CashFlow, FiscalPeriod, IncomeStatement, PeriodType, RatioSnapshot,
)
from ..provider import FundamentalProvider

_log = logging.getLogger("fundamentals.screener")

_CR = 1e7                       # Rs. Crore → absolute INR
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/122.0 Safari/537.36")
_TIMEOUT = 12                   # seconds

# Screener section-id → (row label on the site → normalized field name)
_PL_MAP = {
    "Sales":            "revenue",
    "Revenue":          "revenue",           # banks/NBFCs use "Revenue"
    "Operating Profit": "operating_income",  # screener's OP ≈ EBITDA-ish; safe as OI proxy
    "Net Profit":       "net_income",
    "Interest":         "interest_expense",
    "EPS in Rs":        "eps_basic",
    "Tax %":            "_tax_pct",          # used only to derive tax_expense
}
_BS_MAP = {
    "Equity Capital":       "_equity_capital",     # combined with reserves
    "Reserves":             "_reserves",
    "Borrowings":           "total_debt",
    "Other Liabilities":    "_other_liab",
    "Total Liabilities":    "total_liabilities",
    "Fixed Assets":         "_fixed_assets",
    "CWIP":                 "_cwip",
    "Investments":          "_investments",
    "Other Assets":         "_other_assets",
    "Total Assets":         "total_assets",
}
_CF_MAP = {
    "Cash from Operating Activity":  "operating_cash_flow",
    "Cash from Investing Activity":  "investing_cash_flow",
    "Cash from Financing Activity":  "financing_cash_flow",
    # capex is not broken out; we derive FCF only when capex is available (rare on screener)
}


def _num(txt: str) -> Optional[float]:
    """Parse '1,234.5' / '-45' / '' / '-' → float or None."""
    if txt is None:
        return None
    s = str(txt).strip().replace(",", "").replace("–", "-").replace("−", "-")
    if not s or s in {"-", "--", "N/A", "NA"}:
        return None
    # strip trailing '%' if present
    pct = s.endswith("%")
    if pct:
        s = s[:-1].strip()
    try:
        v = float(s)
        return v / 100.0 if pct else v
    except ValueError:
        return None


def _parse_col_date(header: str) -> Optional[date]:
    """'Mar 2024' | 'Mar 2024 *' | 'TTM' → date or None (TTM ignored)."""
    if not header:
        return None
    h = re.sub(r"[\s *]+", " ", header).strip()
    if h.upper() == "TTM":
        return None
    try:
        return datetime.strptime(h, "%b %Y").date().replace(day=28)
    except ValueError:
        return None


class ScreenerFundamentalProvider(FundamentalProvider):
    """Screener.in fallback — deep 10-yr coverage for every listed Indian stock."""

    name = "Screener.in"

    def __init__(self, raw_cache: Optional[TTLCache] = None, session: Optional[requests.Session] = None):
        self._raw_cache = raw_cache or TTLCache(name="screener-raw")
        self._session = session or requests.Session()
        self._session.headers.update({"User-Agent": _UA, "Accept-Language": "en-IN,en;q=0.9"})

    # ── availability ────────────────────────────────────────────────────────
    def is_available(self) -> bool:
        try:
            import bs4  # noqa: F401
            return True
        except Exception:
            _log.info("beautifulsoup4 not installed — Screener provider disabled")
            return False

    # ── raw fetch (only network seam; monkeypatched in tests) ───────────────
    def _fetch_html(self, symbol: str) -> Optional[str]:
        """Fetch the company page HTML. Returns None on 404 (unknown ticker)."""
        code = symbol.upper().replace(".NS", "").replace(".BO", "").strip()
        for path in (f"/company/{code}/consolidated/", f"/company/{code}/"):
            url = f"https://www.screener.in{path}"
            try:
                r = self._session.get(url, timeout=_TIMEOUT)
            except requests.RequestException as e:
                raise RuntimeError(f"Screener fetch failed for {symbol}: {e}") from e
            if r.status_code == 200 and "profit-loss" in r.text:
                return r.text
            if r.status_code == 404:
                continue
        return None

    def _raw(self, symbol: str) -> Optional[dict]:
        """Parsed page dict, cached. Returns None if the ticker is unknown to Screener."""
        key = f"raw|{symbol}"
        cached = self._raw_cache.get(key)
        if cached is not None:
            return cached
        html = self._fetch_html(symbol)
        if html is None:
            self._raw_cache.set(key, {})       # negative-cache 24h to avoid re-hammering
            return None
        parsed = self._parse(html)
        self._raw_cache.set(key, parsed)
        return parsed

    # ── HTML → structured dict ──────────────────────────────────────────────
    @staticmethod
    def _parse(html: str) -> dict:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "lxml")

        def _read_section(section_id: str) -> Optional[dict]:
            sec = soup.find("section", id=section_id)
            if sec is None:
                return None
            table = sec.find("table")
            if table is None:
                return None
            headers = [th.get_text(strip=True) for th in table.find_all("th")]
            if not headers:
                return None
            headers = headers[1:]              # drop leading empty "label" column
            rows = {}
            for tr in table.find_all("tr"):
                cells = tr.find_all("td")
                if not cells:
                    continue
                label = cells[0].get_text(strip=True).rstrip(" +").strip()
                # nested rows on screener have "+" toggles — keep the collapsed label only
                label = re.sub(r"\s+", " ", label)
                vals = [c.get_text(strip=True) for c in cells[1:]]
                rows[label] = vals
            return {"headers": headers, "rows": rows}

        def _read_top_ratios() -> Dict[str, Optional[float]]:
            """`#top-ratios` list: Market Cap, Stock P/E, Book Value, ROCE, ROE, D/E …

            FIX PROV-2026-09-06 - the earlier implementation grabbed the whole
            value span's text (e.g. "₹ 1,322" or "₹ 17,89,001 Cr.") and handed
            it to _num(), which only strips commas / dashes / trailing %. The
            leading ₹ and trailing "Cr." made float() raise, so every currency-
            denominated field (Market Cap, Current Price, High/Low, Book Value)
            silently returned None. Downstream: get_ratios().pb was None for
            every stock Screener served, which specifically degrades sector-
            aware scoring for banks / NBFCs / insurers per Guardrail 3. See
            docs/DATA_PROVENANCE_2026-09.md finding #7.

            New strategy: prefer the nested <span class="number"> children of
            the value span, which Screener always renders as bare numeric
            (comma-formatted but no currency / unit). If exactly one, parse
            that. If exactly two (High / Low pair renders as two numbers
            joined by a slash), use their arithmetic mean so the caller still
            gets a single float. Fall back to the whole-text path only when
            the meaningful unit is % (Dividend Yield, ROCE, ROE), where _num()
            already handles the trailing %.
            """
            out: Dict[str, Optional[float]] = {}
            ul = soup.find("ul", id="top-ratios")
            if ul is None:
                return out
            for li in ul.find_all("li"):
                name_el  = li.find("span", class_="name")
                value_el = li.find("span", class_="value")
                if not name_el or not value_el:
                    continue
                name = name_el.get_text(strip=True)

                number_spans = value_el.find_all("span", class_="number")
                whole_text   = value_el.get_text(" ", strip=True)

                if not number_spans:
                    out[name] = _num(whole_text)
                    continue

                # % values keep the trailing sign, so let the whole-text +
                # _num() path handle them (it strips % and divides by 100).
                if whole_text.rstrip().endswith("%"):
                    out[name] = _num(whole_text)
                    continue

                if len(number_spans) == 1:
                    out[name] = _num(number_spans[0].get_text(strip=True))
                    continue

                # Two-number field (High / Low pair): report the mean so
                # downstream single-float consumers get something meaningful
                # rather than None. Individual highs / lows are also available
                # from the yearly `ratios` section for callers that need them.
                parsed = [_num(s.get_text(strip=True)) for s in number_spans]
                parsed = [v for v in parsed if v is not None]
                if not parsed:
                    out[name] = None
                elif len(parsed) == 1:
                    out[name] = parsed[0]
                else:
                    out[name] = sum(parsed) / len(parsed)
            return out

        result = {
            "pl":       _read_section("profit-loss"),
            "bs":       _read_section("balance-sheet"),
            "cf":       _read_section("cash-flow"),
            "ratios":   _read_section("ratios"),
            "quarters": _read_section("quarters"),
            "top":      _read_top_ratios(),
            "name":     (soup.find("h1").get_text(strip=True)
                         if soup.find("h1") else None),
        }

        # Label-drift self-check — flagged HIGH RISK by data-provenance-auditor
        # 2026-09-02. Screener.in periodically renames row labels (e.g.
        # "Operating Profit" → "Op. Profit"); the row-map lookups downstream
        # (_PL_MAP / _BS_MAP / _CF_MAP) then silently yield None for every
        # renamed row and every stock, with no exception raised. Guard: after
        # parsing, at least one of {pl, bs, cf} MUST have ≥ 1 label that
        # matches one of our maps. If none do — HTML shape changed. Log
        # WARNING with the labels we DID see so operators can update the map.
        _seen: set[str] = set()
        for _sec_key in ("pl", "bs", "cf"):
            _sec = result.get(_sec_key)
            if isinstance(_sec, dict):
                _seen.update((_sec.get("rows") or {}).keys())
        _known = set(_PL_MAP) | set(_BS_MAP) | set(_CF_MAP)
        if _seen and not (_seen & _known):
            _log.warning(
                "screener: NO label from _PL_MAP/_BS_MAP/_CF_MAP matched any "
                "row across pl/bs/cf — probable Screener.in HTML/label rewrite. "
                "Fundamentals will silently become None for every stock until "
                "the label maps are updated. First 15 labels seen: %s",
                sorted(_seen)[:15],
            )
        return result

    # ── helpers for statement builders ──────────────────────────────────────
    @staticmethod
    def _extract_series(section: Optional[dict], label_map: Dict[str, str],
                        period: PeriodType) -> List[dict]:
        """Turn a section {headers, rows} + label→field mapping into a
        newest-first list of {"date": …, "period_type": …, fields}."""
        if not section:
            return []
        headers = section["headers"]
        # Drop TTM columns entirely from statements (they aren't a period).
        col_dates = [_parse_col_date(h) for h in headers]
        row_vals: Dict[str, List[Optional[float]]] = {
            fld: [None] * len(headers) for fld in set(label_map.values())
        }
        for label, values in section["rows"].items():
            fld = label_map.get(label)
            if not fld:
                continue
            for i in range(min(len(values), len(headers))):
                row_vals[fld][i] = _num(values[i])

        # Assemble per-column, newest-first
        out: List[dict] = []
        for i in range(len(headers) - 1, -1, -1):
            d = col_dates[i]
            if d is None:
                continue       # skip TTM / unparseable
            rec = {"_date": d, "_period": period}
            for fld, series in row_vals.items():
                rec[fld] = series[i]
            out.append(rec)
        return out

    # ── FundamentalProvider API ─────────────────────────────────────────────
    def get_income_statement(self, symbol, period: PeriodType = "annual",
                             limit: int = 10) -> List[IncomeStatement]:
        raw = self._raw(symbol)
        if not raw:
            return []
        section = raw["quarters"] if period == "quarterly" else raw["pl"]
        recs = self._extract_series(section, _PL_MAP, period)[:limit]
        out: List[IncomeStatement] = []
        for r in recs:
            rev = r.get("revenue")
            oi = r.get("operating_income")
            ni = r.get("net_income")
            interest = r.get("interest_expense")
            eps = r.get("eps_basic")
            tax_pct = r.get("_tax_pct")            # fraction (screener already %)
            # derive pretax + tax where possible
            pretax = None
            tax_exp = None
            if ni is not None and tax_pct is not None and tax_pct < 1:
                # net = pretax * (1 - tax); pretax = net / (1 - tax)
                if (1 - tax_pct) > 0:
                    pretax = ni / (1 - tax_pct)
                    tax_exp = pretax - ni
            d = r["_date"]
            out.append(IncomeStatement(
                period=FiscalPeriod(period_end=d, fiscal_year=d.year, period_type=period),
                revenue=rev * _CR if rev is not None else None,
                operating_income=oi * _CR if oi is not None else None,
                interest_expense=interest * _CR if interest is not None else None,
                pretax_income=pretax * _CR if pretax is not None else None,
                tax_expense=tax_exp * _CR if tax_exp is not None else None,
                net_income=ni * _CR if ni is not None else None,
                eps_basic=eps,                          # per-share Rs, not Cr
                eps_diluted=eps,                        # screener doesn't split basic/diluted
            ))
        return out

    def get_balance_sheet(self, symbol, period: PeriodType = "annual",
                          limit: int = 10) -> List[BalanceSheet]:
        raw = self._raw(symbol)
        if not raw or period == "quarterly":
            return []           # screener doesn't publish quarterly BS
        recs = self._extract_series(raw["bs"], _BS_MAP, period)[:limit]
        out: List[BalanceSheet] = []
        for r in recs:
            eq = r.get("_equity_capital")
            res = r.get("_reserves")
            equity = None
            if eq is not None or res is not None:
                equity = (eq or 0.0) + (res or 0.0)
            d = r["_date"]
            out.append(BalanceSheet(
                period=FiscalPeriod(period_end=d, fiscal_year=d.year, period_type=period),
                total_assets=(r.get("total_assets") * _CR) if r.get("total_assets") is not None else None,
                total_liabilities=(r.get("total_liabilities") * _CR) if r.get("total_liabilities") is not None else None,
                total_debt=(r.get("total_debt") * _CR) if r.get("total_debt") is not None else None,
                total_equity=(equity * _CR) if equity is not None else None,
            ))
        return out

    def get_cash_flow(self, symbol, period: PeriodType = "annual",
                      limit: int = 10) -> List[CashFlow]:
        raw = self._raw(symbol)
        if not raw or period == "quarterly":
            return []
        recs = self._extract_series(raw["cf"], _CF_MAP, period)[:limit]
        out: List[CashFlow] = []
        for r in recs:
            d = r["_date"]
            out.append(CashFlow(
                period=FiscalPeriod(period_end=d, fiscal_year=d.year, period_type=period),
                operating_cash_flow=(r.get("operating_cash_flow") * _CR)
                    if r.get("operating_cash_flow") is not None else None,
                investing_cash_flow=(r.get("investing_cash_flow") * _CR)
                    if r.get("investing_cash_flow") is not None else None,
                financing_cash_flow=(r.get("financing_cash_flow") * _CR)
                    if r.get("financing_cash_flow") is not None else None,
                # capex/FCF: screener doesn't break capex out cleanly at the top level.
                # Leaving None here is honest — the merge layer keeps Yahoo's value if any.
            ))
        return out

    def get_ratios(self, symbol: str) -> RatioSnapshot:
        raw = self._raw(symbol)
        if not raw:
            return RatioSnapshot(as_of=date.today())
        top = raw.get("top") or {}
        # Screener top-ratio labels: 'Stock P/E', 'Book Value', 'Dividend Yield',
        # 'ROCE', 'ROE', 'Debt to equity', 'Face Value'
        pe = top.get("Stock P/E")
        roe = top.get("ROE")          # already fraction (percent-suffixed → /100 by _num)
        roce = top.get("ROCE")
        d2e = top.get("Debt to equity")
        book_value = top.get("Book Value")
        cmp_ = top.get("Current Price")
        pb = (cmp_ / book_value) if (cmp_ is not None and book_value not in (None, 0)) else None
        return RatioSnapshot(
            as_of=date.today(),
            roe=roe, roce=roce,
            debt_to_equity=d2e,
            pe=pe, pb=pb,
        )

    def company_info(self, symbol: str) -> dict:
        raw = self._raw(symbol)
        if not raw:
            return {}
        return {"company_name": raw.get("name"), "sector": None, "currency": "INR"}
