"""tests/test_screener_top_ratios.py - regression coverage for
ScreenerFundamentalProvider._parse's `_read_top_ratios` inner function.

Guards FIX PROV-2026-09-06: the earlier parser handed the WHOLE value-span
text (e.g. "₹ 1,322" or "₹ 17,89,001 Cr.") to _num(), which choked on the
leading ₹ / trailing "Cr." and silently returned None for every currency-
denominated field. Downstream get_ratios().pb was None for every stock,
which specifically degrades sector-aware scoring for banks / NBFCs /
insurers per Guardrail 3.

Fixture below mirrors the live Screener HTML structure verified by the
2026-09-06 data-provenance audit.
"""
from __future__ import annotations

import pytest

pytest.importorskip("bs4")

from analysis.fundamentals.providers.screener_fundamentals import (
    ScreenerFundamentalProvider,
)


# Screener wraps values as one of these shapes (verified live 2026-09-06):
#   <li>
#     <span class="name">Market Cap</span>
#     <span class="nowrap value">₹ <span class="number">17,89,001</span> Cr.</span>
#   </li>
#
#   <li>
#     <span class="name">Current Price</span>
#     <span class="nowrap value">₹ <span class="number">1,322</span></span>
#   </li>
#
#   <li>
#     <span class="name">High / Low</span>
#     <span class="nowrap value">₹ <span class="number">1,608</span> / <span class="number">1,120</span></span>
#   </li>
#
#   <li>
#     <span class="name">Stock P/E</span>
#     <span class="nowrap value"><span class="number">23.9</span></span>
#   </li>
#
#   <li>
#     <span class="name">ROCE</span>
#     <span class="nowrap value"><span class="number">10.3</span> %</span>
#   </li>
_FIXTURE_HTML = """<html><body>
<ul id="top-ratios">
  <li>
    <span class="name">Market Cap</span>
    <span class="nowrap value">₹ <span class="number">17,89,001</span> Cr.</span>
  </li>
  <li>
    <span class="name">Current Price</span>
    <span class="nowrap value">₹ <span class="number">1,322</span></span>
  </li>
  <li>
    <span class="name">High / Low</span>
    <span class="nowrap value">₹ <span class="number">1,608</span> / <span class="number">1,120</span></span>
  </li>
  <li>
    <span class="name">Stock P/E</span>
    <span class="nowrap value"><span class="number">23.9</span></span>
  </li>
  <li>
    <span class="name">Book Value</span>
    <span class="nowrap value">₹ <span class="number">1,050</span></span>
  </li>
  <li>
    <span class="name">Dividend Yield</span>
    <span class="nowrap value"><span class="number">0.45</span> %</span>
  </li>
  <li>
    <span class="name">ROCE</span>
    <span class="nowrap value"><span class="number">10.3</span> %</span>
  </li>
  <li>
    <span class="name">ROE</span>
    <span class="nowrap value"><span class="number">8.91</span> %</span>
  </li>
  <li>
    <span class="name">Face Value</span>
    <span class="nowrap value">₹ <span class="number">10</span></span>
  </li>
</ul>
</body></html>"""


@pytest.fixture(scope="module")
def parsed_top() -> dict:
    return ScreenerFundamentalProvider._parse(_FIXTURE_HTML)["top"]


# ── Currency-denominated fields must parse (the bug that motivated this) ─────

def test_market_cap_parses_despite_leading_rupee_and_trailing_cr(parsed_top):
    """Was None before FIX PROV-2026-09-06 because '₹ 17,89,001 Cr.' broke _num()."""
    assert parsed_top["Market Cap"] == 1789001.0


def test_current_price_parses_despite_leading_rupee(parsed_top):
    """Was None before FIX PROV-2026-09-06. Loss of this field silently killed P/B."""
    assert parsed_top["Current Price"] == 1322.0


def test_book_value_parses_despite_leading_rupee(parsed_top):
    """The other half of the P/B silent kill."""
    assert parsed_top["Book Value"] == 1050.0


def test_face_value_parses_despite_leading_rupee(parsed_top):
    assert parsed_top["Face Value"] == 10.0


# ── Two-number fields (High / Low) - report the mean, not None ───────────────

def test_high_low_pair_returns_mean_not_none(parsed_top):
    """Two <span class='number'> children: report arithmetic mean so single-
    float downstream consumers get something useful instead of None."""
    assert parsed_top["High / Low"] == pytest.approx((1608.0 + 1120.0) / 2)


# ── Fields the old parser handled correctly must still parse ────────────────

def test_stock_pe_still_parses(parsed_top):
    """Bare-numeric fields (no ₹, no Cr, no %) worked before and must still work."""
    assert parsed_top["Stock P/E"] == 23.9


def test_percent_field_still_divides_by_100(parsed_top):
    """% fields keep the trailing % so _num() divides by 100. Test ROCE = 10.3% -> 0.103."""
    assert parsed_top["ROCE"] == pytest.approx(0.103)


def test_dividend_yield_percent_still_divides_by_100(parsed_top):
    assert parsed_top["Dividend Yield"] == pytest.approx(0.0045)


def test_roe_percent_still_divides_by_100(parsed_top):
    assert parsed_top["ROE"] == pytest.approx(0.0891)


# ── Regression guard: no field the fixture defines should be None ────────────

def test_no_currency_field_silently_returns_none(parsed_top):
    """The whole point of the fix: 4 of 9 fields used to be None. Now zero."""
    for k, v in parsed_top.items():
        assert v is not None, f"field {k!r} regressed to None"
    # The fixture defines exactly the 9 fields the audit found live.
    assert set(parsed_top.keys()) == {
        "Market Cap", "Current Price", "High / Low", "Stock P/E",
        "Book Value", "Dividend Yield", "ROCE", "ROE", "Face Value",
    }
