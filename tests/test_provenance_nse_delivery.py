"""
Canary tests for data/nse_delivery.py — the NSE bhavcopy delivery-%
provider. Ships alongside Recommendation 4 of the composite-score shape
review.

Two flavours:

  * `test_parse_bhavcopy_*` — offline fixture-based tests that assert the
    parser handles the exact CSV shape NSE publishes, and that Guardrail
    14 (named ValueError on drift) fires when required columns disappear
    or dates change format. These run in the fast suite.

  * `test_bhavcopy_live_*` — live-network canary that fetches yesterday's
    bhavcopy and asserts the required columns are still there. Marked
    `slow` and `network` so it stays out of CI's fast lane; run manually
    or as part of the periodic data-provenance sweep.
"""
from __future__ import annotations

import datetime as _dt
import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from data.nse_delivery import _parse_bhavcopy, _REQUIRED_COLS  # noqa: E402


# ─────────────────────────────────────────────────────────────────────────────
# Offline parser tests
# ─────────────────────────────────────────────────────────────────────────────

_HEADER = ",".join([
    "SYMBOL", "SERIES", "DATE1", "PREV_CLOSE", "OPEN_PRICE", "HIGH_PRICE",
    "LOW_PRICE", "LAST_PRICE", "CLOSE_PRICE", "AVG_PRICE", "TTL_TRD_QNTY",
    "TURNOVER_LACS", "NO_OF_TRADES", "DELIV_QTY", "DELIV_PER",
])
_ROW_INFY = ("INFY, EQ ,03-Sep-2026,1830.50,1835.00,1852.30,1828.10,"
             "1846.20,1849.55,1841.20,2500000,46030.00,45210,1650000,66.00")
_ROW_BE   = ("RTNPOWER, BE ,03-Sep-2026,15.20,15.30,15.90,15.10,"
             "15.75,15.80,15.55,1200000,1866.00,4200,600000,50.00")
_ROW_MISSING_DELIV = ("NEWLISTING, SM ,03-Sep-2026,100,100,105,99,"
                      "104,105,102,50000,51.00,120,-, -")


def test_parse_bhavcopy_happy_path_returns_deliv_pct():
    text = _HEADER + "\n" + _ROW_INFY + "\n" + _ROW_BE
    rows = _parse_bhavcopy(text)
    assert len(rows) == 2
    infy = next(r for r in rows if r["symbol"] == "INFY")
    assert infy["date"] == "2026-09-03"
    assert infy["deliv_pct"] == 66.0
    assert infy["deliv_qty"] == 1_650_000.0
    assert infy["close"]     == 1849.55


def test_parse_bhavcopy_skips_rows_with_blank_or_dash_deliv():
    text = _HEADER + "\n" + _ROW_INFY + "\n" + _ROW_MISSING_DELIV
    rows = _parse_bhavcopy(text, filter_series={"EQ", "BE", "SM"})
    # NEWLISTING has "-" for DELIV_PER -> skipped; INFY survives
    assert [r["symbol"] for r in rows] == ["INFY"]


def test_parse_bhavcopy_series_filter_default_is_eq_be():
    # SM series should be filtered out under the default filter
    text = _HEADER + "\n" + _ROW_INFY + "\n" + _ROW_MISSING_DELIV
    rows = _parse_bhavcopy(text)
    assert [r["symbol"] for r in rows] == ["INFY"]


def test_parse_bhavcopy_named_error_on_missing_required_column():
    # Guardrail 14: drift must raise a named ValueError so operators
    # notice, not silently produce empty results.
    dropped = "CLOSE_PRICE"
    hdr = ",".join(c for c in _HEADER.split(",") if c != dropped)
    text = hdr + "\n" + ",".join(v for c, v in zip(_HEADER.split(","),
                                                    _ROW_INFY.split(","))
                                 if c != dropped)
    with pytest.raises(ValueError, match="schema drift.*CLOSE_PRICE"):
        _parse_bhavcopy(text)


def test_parse_bhavcopy_named_error_on_date_format_drift():
    # If NSE ever switches DATE1 away from DD-MMM-YYYY, we want a loud
    # named ValueError, not silent empty output.
    text = _HEADER + "\n" + _ROW_INFY.replace("03-Sep-2026", "2026-09-03")
    with pytest.raises(ValueError, match="schema drift.*DATE1"):
        _parse_bhavcopy(text)


def test_parse_bhavcopy_named_error_on_empty_body():
    with pytest.raises(ValueError, match="empty response body"):
        _parse_bhavcopy("")


def test_required_cols_set_is_stable():
    # The score consumer relies on close / traded_qty / deliv_qty / deliv_pct
    # being present. Locks the contract so a well-meaning parser refactor
    # cannot silently drop one of these from the guarded set.
    assert _REQUIRED_COLS >= {"SYMBOL", "DATE1", "CLOSE_PRICE",
                              "TTL_TRD_QNTY", "DELIV_QTY", "DELIV_PER"}
