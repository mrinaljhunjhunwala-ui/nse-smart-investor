"""Regression tests for the 2026-11-25 fundamentals data check
(docs/audits/2026-11-25_fundamentals_data_check.md). Offline: every network seam
is monkeypatched.

Run:  py -m pytest tests/test_fundamentals_data_fixes.py -q
"""
import os
import sys
from datetime import date

import pandas as pd
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from analysis.fundamentals import analytics as A                        # noqa: E402
from analysis.fundamentals.cache import TTLCache                        # noqa: E402
from analysis.fundamentals.models import (                              # noqa: E402
    BalanceSheet, CompanyFundamentals, FiscalPeriod, IncomeStatement, RatioSnapshot,
)
from analysis.fundamentals.providers import screener_fundamentals as SF  # noqa: E402
from analysis.fundamentals.providers.screener_fundamentals import (     # noqa: E402
    ScreenerFundamentalProvider, _parse_col_date,
)
from analysis.fundamentals.providers.yahoo_fundamentals import YahooFundamentalProvider  # noqa: E402
from analysis.fundamentals.service import FundamentalsService           # noqa: E402
from analysis.sector_classification import classify_sector, shows_roce_and_leverage  # noqa: E402


@pytest.fixture(autouse=True)
def _no_throttle(monkeypatch):
    monkeypatch.setattr(SF, "_MIN_INTERVAL_S", 0.0)


def _inc(d, revenue=None, op=None, ni=None):
    return IncomeStatement(period=FiscalPeriod(period_end=d, fiscal_year=d.year),
                           revenue=revenue, operating_income=op, net_income=ni)


def _cf(name, incs=(), bals=(), ratios=None):
    return CompanyFundamentals(symbol="X.NS", provider_name=name,
                               income_statements=list(incs), balance_sheets=list(bals),
                               ratios=ratios)


# ── 1. period matching ──────────────────────────────────────────────────────
def test_screener_columns_dated_at_month_end():
    assert _parse_col_date("Mar 2026") == date(2026, 3, 31)
    assert _parse_col_date("Feb 2024") == date(2024, 2, 29)
    assert _parse_col_date("Sep 2025 *") == date(2025, 9, 30)
    assert _parse_col_date("TTM") is None
    # standalone marker on a consolidated page (SBILIFE)
    assert _parse_col_date("Mar 2015\n            \n            (S)") == date(2015, 3, 31)


def test_merge_same_fiscal_year_into_one_row_and_yoy_computes():
    yahoo = _cf("YahooFinance", [_inc(date(2026, 3, 31), 110.0), _inc(date(2025, 3, 31), 100.0)])
    # Old Screener dating (the 28th) must still merge by fiscal period.
    scr = _cf("Screener.in", [_inc(date(2026, 3, 28), 111.0, ni=9.0),
                              _inc(date(2025, 3, 28), 101.0),
                              _inc(date(2024, 3, 28), 90.0)])
    merged = FundamentalsService._merge(yahoo, scr)
    ends = [r.period.period_end for r in merged.income_statements]
    assert ends == [date(2026, 3, 31), date(2025, 3, 31), date(2024, 3, 28)]
    assert merged.income_statements[0].revenue == 110.0          # primary wins
    assert merged.income_statements[0].net_income == 9.0         # follower fills
    yoy = A.revenue_yoy(merged)
    assert yoy.available and yoy.value == pytest.approx(10.0)


# ── 2. interim columns ──────────────────────────────────────────────────────
def test_half_year_balance_sheet_column_dropped():
    section = {"headers": ["Mar 2024", "Mar 2025", "Mar 2026", "Sep 2026"],
               "rows": {"Total Assets": ["10", "20", "30", "35"]}}
    recs = ScreenerFundamentalProvider._extract_series(section, {"Total Assets": "total_assets"},
                                                       "annual")
    assert [r["_date"] for r in recs] == [date(2026, 3, 31), date(2025, 3, 31), date(2024, 3, 31)]
    assert recs[0]["total_assets"] == 30.0


def test_quarterly_series_keeps_every_month():
    section = {"headers": ["Jun 2026", "Sep 2026"], "rows": {"Sales": ["1", "2"]}}
    recs = ScreenerFundamentalProvider._extract_series(section, {"Sales": "revenue"}, "quarterly")
    assert len(recs) == 2


# ── 3. Yahoo currency guard ─────────────────────────────────────────────────
def _yahoo_raw(currency):
    cols = [pd.Timestamp("2026-03-31"), pd.Timestamp("2025-03-31")]
    income = pd.DataFrame({"Total Revenue": [20.0, 19.0]}, index=cols).T
    info = {"financialCurrency": currency, "returnOnEquity": 0.3, "trailingPE": 22.0}
    return {"income": income, "balance": income.iloc[0:0], "cashflow": None, "info": info}


def test_yahoo_non_inr_statements_dropped(monkeypatch):
    p = YahooFundamentalProvider(raw_cache=TTLCache(name="t-usd"))
    monkeypatch.setattr(p, "_fetch_raw", lambda s, per: _yahoo_raw("USD"))
    assert p.get_income_statement("INFY.NS") == []
    assert p.get_ratios("INFY.NS").pe == 22.0              # ratios kept
    assert p.company_info("INFY.NS")["currency"] == "INR"
    assert p.company_info("INFY.NS")["reported_currency"] == "USD"


def test_yahoo_inr_statements_kept(monkeypatch):
    p = YahooFundamentalProvider(raw_cache=TTLCache(name="t-inr"))
    monkeypatch.setattr(p, "_fetch_raw", lambda s, per: _yahoo_raw("INR"))
    assert len(p.get_income_statement("TCS.NS")) == 2


# ── 4. ROCE fallback + rule-3 gate ──────────────────────────────────────────
def test_roce_uses_vendor_ratio_when_current_liabilities_missing():
    bal = BalanceSheet(period=FiscalPeriod(period_end=date(2026, 3, 31)), total_assets=100.0,
                       total_equity=50.0, total_debt=10.0)
    cf = _cf("Screener.in", [_inc(date(2026, 3, 31), op=12.0)], [bal], RatioSnapshot(roce=0.63))
    r = A.roce(cf)
    assert r.available and r.value == 63.0


def test_roce_falls_back_to_equity_plus_debt():
    bal = BalanceSheet(period=FiscalPeriod(period_end=date(2026, 3, 31)), total_assets=100.0,
                       total_equity=50.0, total_debt=10.0)
    cf = _cf("Screener.in", [_inc(date(2026, 3, 31), op=12.0)], [bal], RatioSnapshot())
    r = A.roce(cf)
    assert r.available and r.value == 20.0
    assert r.detail["method"] == "EBIT / (equity + debt)"


def test_roce_prefers_statement_formula():
    bal = BalanceSheet(period=FiscalPeriod(period_end=date(2026, 3, 31)), total_assets=100.0,
                       current_liabilities=40.0)
    cf = _cf("YahooFinance", [_inc(date(2026, 3, 31), op=12.0)], [bal], RatioSnapshot(roce=0.9))
    assert A.roce(cf).value == 20.0


def test_rule3_gate_hides_roce_and_leverage_for_financials():
    assert not shows_roce_and_leverage(classify_sector("Banking"))
    assert not shows_roce_and_leverage(classify_sector("Insurance"))
    assert shows_roce_and_leverage(classify_sector("IT"))
    assert shows_roce_and_leverage(None)


# ── 5. one revenue definition per series ────────────────────────────────────
def test_lender_revenue_not_mixed_across_providers():
    # Yahoo net revenue (~half) vs Screener gross interest income, 10y deeper.
    yahoo = _cf("YahooFinance", [_inc(date(y, 3, 31), 50.0 + y - 2023, ni=5.0)
                                 for y in (2026, 2025, 2024, 2023)])
    scr = _cf("Screener.in", [_inc(date(y, 3, 31), 100.0 * 1.1 ** (y - 2017))
                              for y in range(2026, 2016, -1)])
    merged = FundamentalsService._merge(yahoo, scr)
    revs = {r.period.period_end.year: r.revenue for r in merged.income_statements}
    for y in range(2017, 2027):
        assert revs[y] == pytest.approx(100.0 * 1.1 ** (y - 2017))   # all Screener
    assert merged.income_statements[0].net_income == 5.0
    cagr = A.revenue_cagr(merged, 5)
    assert cagr.available and cagr.value == pytest.approx(10.0, abs=0.05)


def test_matching_revenue_still_merges_normally():
    yahoo = _cf("YahooFinance", [_inc(date(2026, 3, 31), 100.0)])
    scr = _cf("Screener.in", [_inc(date(2026, 3, 31), 102.0), _inc(date(2025, 3, 31), 90.0)])
    merged = FundamentalsService._merge(yahoo, scr)
    assert [r.revenue for r in merged.income_statements] == [100.0, 90.0]


# ── 6. Screener robustness ──────────────────────────────────────────────────
class _Resp:
    def __init__(self, status, text=""):
        self.status_code, self.text = status, text


class _Session:
    def __init__(self, responses):
        self.responses, self.urls, self.headers = list(responses), [], {}

    def get(self, url, timeout=None):
        self.urls.append(url)
        return self.responses.pop(0)


_EMPTY = '<section id="profit-loss"><table><tr><td>Sales</td><td></td></tr></table></section>'
_FULL = '<section id="profit-loss"><table><tr><td>Sales</td><td>1,234</td></tr></table></section>'


def test_empty_consolidated_page_falls_back_to_standalone():
    s = _Session([_Resp(200, _EMPTY), _Resp(200, _FULL)])
    p = ScreenerFundamentalProvider(raw_cache=TTLCache(name="t1"), session=s)
    assert p._fetch_html("SBILIFE.NS") == _FULL
    assert s.urls[1].endswith("/company/SBILIFE/")


@pytest.mark.parametrize("status", [429, 403, 503])
def test_throttle_is_a_transport_error_not_negative_cached(status):
    cache = TTLCache(name=f"t-{status}")
    p = ScreenerFundamentalProvider(raw_cache=cache, session=_Session([_Resp(status)]))
    with pytest.raises(RuntimeError):
        p._raw("TCS.NS")
    assert cache.get("raw|TCS.NS") is None


def test_unknown_ticker_still_negative_cached():
    cache = TTLCache(name="t-404")
    p = ScreenerFundamentalProvider(raw_cache=cache, session=_Session([_Resp(404), _Resp(404)]))
    assert p._raw("NOPE.NS") is None
    assert cache.get("raw|NOPE.NS") == {}


def test_screener_market_cap_and_bank_borrowing_mapped(monkeypatch):
    p = ScreenerFundamentalProvider(raw_cache=TTLCache(name="t-mc"))
    raw = {"top": {"Market Cap": 1000.0}, "pl": None, "cf": None, "quarters": None,
           "bs": {"headers": ["Mar 2026"], "rows": {"Borrowing": ["50"], "Deposits": ["900"]}}}
    monkeypatch.setattr(p, "_raw", lambda s: raw)
    assert p.get_ratios("SBIN.NS").market_cap == 1000.0 * 1e7
    assert p.get_balance_sheet("SBIN.NS")[0].total_debt == 50.0 * 1e7   # deposits are not debt


# ── 7/9. empty data is visible ──────────────────────────────────────────────
def test_empty_ratio_snapshot_is_not_data():
    cf = _cf("Exchange filing", ratios=RatioSnapshot(as_of=date.today()))
    assert not cf.has_any_data()
    cf.ratios = RatioSnapshot(as_of=date.today(), pb=2.0)
    assert cf.has_any_data()
