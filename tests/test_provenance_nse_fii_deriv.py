"""
Canary tests for data/nse_fii_deriv.py — the FII derivatives (index-
futures net position) provider. Offline fixture-based, Guardrail §14/16.
"""
from __future__ import annotations

import datetime as _dt
import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from data.nse_fii_deriv import _parse, _REQUIRED_COLS   # noqa: E402


# Minimal fao_participant_oi shape — 15 columns, four client-type rows.
_HEADER = ",".join([
    "Client Type",
    "Future Index Long", "Future Index Short",
    "Future Stock Long", "Future Stock Short",
    "Option Index Call Long", "Option Index Put Long",
    "Option Index Call Short", "Option Index Put Short",
    "Option Stock Call Long", "Option Stock Put Long",
    "Option Stock Call Short", "Option Stock Put Short",
    "Total Long Contracts", "Total Short Contracts",
])
_ROW_CLIENT = "Client,25000,22000,150000,145000,80000,90000,85000,95000,120000,110000,115000,105000,455000,462000"
_ROW_DII    = "DII,15000,8000,20000,18000,10000,12000,8000,9000,15000,14000,13000,12000,73000,60000"
_ROW_FII    = "FII,85000,45000,120000,110000,180000,175000,190000,185000,140000,135000,145000,130000,660000,650000"
_ROW_PRO    = "Pro,20000,25000,60000,65000,50000,55000,48000,52000,45000,42000,40000,38000,215000,220000"

_TARGET_DATE = _dt.date(2026, 9, 3)


def test_parse_extracts_fii_row_and_computes_nets():
    text = "\n".join([_HEADER, _ROW_CLIENT, _ROW_DII, _ROW_FII, _ROW_PRO])
    row = _parse(text, _TARGET_DATE)
    assert row is not None
    assert row["date"]           == "2026-09-03"
    assert row["fut_idx_long"]   == 85_000
    assert row["fut_idx_short"]  == 45_000
    assert row["fut_idx_net"]    == 40_000   # net long 40k contracts
    assert row["fut_stk_long"]   == 120_000
    assert row["fut_stk_short"]  == 110_000
    assert row["fut_stk_net"]    == 10_000


def test_parse_returns_none_when_fii_row_missing_but_warns():
    # No FII row — Client / DII / Pro only. Parser should return None
    # and (in production) log a WARNING; we assert the None return here.
    text = "\n".join([_HEADER, _ROW_CLIENT, _ROW_DII, _ROW_PRO])
    row = _parse(text, _TARGET_DATE)
    assert row is None


def test_parse_strips_leading_preamble_line_if_present():
    # NSE has occasionally prepended an "As on <date>" comment line.
    text = "As on 03-Sep-2026\n" + "\n".join([_HEADER, _ROW_FII])
    row = _parse(text, _TARGET_DATE)
    assert row is not None
    assert row["fut_idx_net"] == 40_000


def test_parse_handles_thousands_separators():
    # Values with commas in the numeric fields (NSE has toggled this).
    fii_commas = ('FII,"85,000","45,000","120,000","110,000",'
                  '180000,175000,190000,185000,'
                  '140000,135000,145000,130000,660000,650000')
    text = "\n".join([_HEADER, fii_commas])
    row = _parse(text, _TARGET_DATE)
    assert row is not None
    assert row["fut_idx_net"] == 40_000


def test_parse_named_error_on_missing_required_column():
    # Drop 'Future Index Short' — parser must raise, not silently return
    # null nets.
    dropped = "Future Index Short"
    hdr = ",".join(c for c in _HEADER.split(",") if c != dropped)
    # Row must line up with the trimmed header
    fii_vals = _ROW_FII.split(",")
    hdr_names = _HEADER.split(",")
    body = ",".join(v for c, v in zip(hdr_names, fii_vals) if c != dropped)
    text = hdr + "\n" + body
    with pytest.raises(ValueError, match="schema drift.*Future Index Short"):
        _parse(text, _TARGET_DATE)


def test_parse_named_error_on_empty_body():
    with pytest.raises(ValueError, match="empty response body"):
        _parse("", _TARGET_DATE)


def test_parse_handles_blank_or_dash_values():
    # If Future Stock Short is blank on a partial-day file, fut_stk_net
    # should degrade to None (not raise).
    fii_partial = ('FII,85000,45000,120000,,'
                   '180000,175000,190000,185000,'
                   '140000,135000,145000,130000,660000,650000')
    text = "\n".join([_HEADER, fii_partial])
    row = _parse(text, _TARGET_DATE)
    assert row is not None
    assert row["fut_stk_short"] is None
    assert row["fut_stk_net"]   is None
    # Index nets still populate
    assert row["fut_idx_net"] == 40_000


def test_required_cols_locked():
    assert _REQUIRED_COLS >= {"Client Type", "Future Index Long",
                              "Future Index Short"}
