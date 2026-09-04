"""
Canary tests for data/nse_fno_bhavcopy.py — the OI-regime provider.

Follows the same offline-fixture pattern as
tests/test_provenance_nse_delivery.py.
"""
from __future__ import annotations

import datetime as _dt
import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from data.nse_fno_bhavcopy import (  # noqa: E402
    _parse_bhavcopy, _REQUIRED_COLS, classify_oi_regime,
)


# ─────────────────────────────────────────────────────────────────────────────
# Fixture: minimal F&O bhavcopy with a stock fut + two option rows + one
# index-fut row (to be filtered out).
# ─────────────────────────────────────────────────────────────────────────────

_HEADER = ",".join([
    "TckrSymb", "FinInstrmTp", "XpryDt", "StrkPric", "OptnTp",
    "OpnPric", "HghPric", "LwPric", "ClsPric", "LastPric",
    "TtlTradgVol", "TtlTrfVal", "OpnIntrst", "ChngInOpnIntrst",
])
# STF row
_ROW_INFY_FUT = ("INFY,STF,25-Sep-2026,,,1830,1855,1828,1848,1850,"
                 "1200000,222000000,4500000,150000")
# STO row (call)
_ROW_INFY_CE  = ("INFY,STO,25-Sep-2026,1850,CE,25.5,32.1,24.9,30.2,30.5,"
                 "450000,13590000000,2100000,80000")
# STO row (put)
_ROW_INFY_PE  = ("INFY,STO,25-Sep-2026,1850,PE,28.4,29.9,20.1,22.3,22.0,"
                 "380000,8580000000,1900000,-40000")
# IDF row - must be filtered out by _STOCK_INSTR_TYPES
_ROW_NIFTY_FUT = ("NIFTY,IDF,25-Sep-2026,,,24500,24680,24450,24610,24615,"
                  "180000,44300000000,12500000,400000")

_TARGET_DATE = _dt.date(2026, 9, 25)


def test_parse_bhavcopy_aggregates_stock_oi_across_contracts():
    text = "\n".join([_HEADER, _ROW_INFY_FUT, _ROW_INFY_CE, _ROW_INFY_PE,
                      _ROW_NIFTY_FUT])
    rows = _parse_bhavcopy(text, _TARGET_DATE)
    assert len(rows) == 1, "index instruments must be filtered out"
    infy = rows[0]
    assert infy["symbol"]      == "INFY"
    assert infy["date"]        == "2026-09-25"
    # 4.5M + 2.1M + 1.9M = 8.5M across the three stock rows
    assert infy["total_oi"]    == 4_500_000 + 2_100_000 + 1_900_000
    assert infy["n_contracts"] == 3


def test_parse_bhavcopy_filters_out_index_derivatives():
    # A file that ONLY has index rows should aggregate to zero symbols
    text = "\n".join([_HEADER, _ROW_NIFTY_FUT])
    rows = _parse_bhavcopy(text, _TARGET_DATE)
    assert rows == []


def test_parse_bhavcopy_named_error_on_missing_required_column():
    dropped = "OpnIntrst"
    hdr = ",".join(c for c in _HEADER.split(",") if c != dropped)
    body = ",".join(v for c, v in zip(_HEADER.split(","),
                                      _ROW_INFY_FUT.split(","))
                    if c != dropped)
    text = hdr + "\n" + body
    with pytest.raises(ValueError, match="schema drift.*OpnIntrst"):
        _parse_bhavcopy(text, _TARGET_DATE)


def test_parse_bhavcopy_named_error_on_empty_body():
    with pytest.raises(ValueError, match="empty response body"):
        _parse_bhavcopy("", _TARGET_DATE)


def test_parse_bhavcopy_skips_rows_with_blank_or_dash_oi():
    # Same INFY futures row but blank OpnIntrst -> skipped, other rows still count
    blank_oi_row = _ROW_INFY_FUT.replace(",4500000,150000", ",,150000")
    text = "\n".join([_HEADER, blank_oi_row, _ROW_INFY_CE])
    rows = _parse_bhavcopy(text, _TARGET_DATE)
    assert len(rows) == 1
    assert rows[0]["total_oi"]    == 2_100_000   # only the CE row counted
    assert rows[0]["n_contracts"] == 1


def test_required_cols_locked():
    assert _REQUIRED_COLS >= {"TckrSymb", "FinInstrmTp", "OpnIntrst"}


# ─────────────────────────────────────────────────────────────────────────────
# classify_oi_regime — the four-way classifier used by score
# ─────────────────────────────────────────────────────────────────────────────

def test_classify_oi_regime_four_quadrants():
    assert classify_oi_regime(oi_pct_change=+5.0, price_pct_change=+1.5) == "long_buildup"
    assert classify_oi_regime(oi_pct_change=-5.0, price_pct_change=+1.5) == "short_covering"
    assert classify_oi_regime(oi_pct_change=+5.0, price_pct_change=-1.5) == "short_buildup"
    assert classify_oi_regime(oi_pct_change=-5.0, price_pct_change=-1.5) == "long_unwinding"


def test_classify_oi_regime_returns_none_when_price_or_oi_is_flat():
    # price too flat
    assert classify_oi_regime(oi_pct_change=+5.0, price_pct_change=+0.05) is None
    # OI too flat (threshold is 5x the price threshold = 1 pct default)
    assert classify_oi_regime(oi_pct_change=+0.3, price_pct_change=+1.5) is None


def test_classify_oi_regime_none_inputs():
    assert classify_oi_regime(None, +1.5) is None
    assert classify_oi_regime(+5.0, None) is None
