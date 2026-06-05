"""tests/test_valuation_golden_snapshot.py — OFFLINE validation of the E1-v2 golden
snapshot (Part 2, Component C). No network — verifies the committed snapshot's structure
and a few known postures from V1. The live drift check is the diagnostic script
`tools/validate_valuation.py` (NOT run in CI)."""
from __future__ import annotations

import json
import os

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SNAPSHOT = os.path.join(_ROOT, "data", "valuation_golden_snapshot.json")

# The 62 V1-validated tickers (V1_NSE_VALIDATION_REPORT.md).
_EXPECTED_TICKERS = {
    "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK", "HINDUNILVR", "ITC", "LT",
    "BHARTIARTL", "MARUTI", "SBIN", "KOTAKBANK", "AXISBANK", "BANKBARODA", "PNB",
    "INDUSINDBK", "FEDERALBNK", "BAJFINANCE", "BAJAJFINSV", "CHOLAFIN", "MUTHOOTFIN",
    "SHRIRAMFIN", "SBICARD", "LICHSGFIN", "ICICIGI", "ICICIPRULI", "HDFCLIFE", "SBILIFE",
    "ONGC", "NTPC", "POWERGRID", "BHEL", "SAIL", "GAIL", "IOC", "COALINDIA", "NMDC",
    "SIEMENS", "ABB", "CUMMINSIND", "THERMAX", "BEL", "HAVELLS", "NESTLEIND", "BRITANNIA",
    "DABUR", "MARICO", "TATACONSUM", "COLPAL", "WIPRO", "HCLTECH", "TECHM", "LTIM",
    "PERSISTENT", "COFORGE", "SRF", "DEEPAKNITR", "POLYCAB", "DIXON", "TATAELXSI",
    "TATASTEEL", "HINDALCO",
}
_REQUIRED_FIELDS = {"posture", "confidence", "branch", "guards_triggered"}


@pytest.fixture(scope="module")
def snap():
    assert os.path.exists(_SNAPSHOT), "golden snapshot file missing"
    with open(_SNAPSHOT, "r", encoding="utf-8") as f:
        return json.load(f)


def test_snapshot_valid_json_and_schema(snap):
    assert snap.get("schema_version") == 1
    assert snap.get("source") == "V1_NSE_VALIDATION_REPORT.md"
    assert isinstance(snap.get("tickers"), dict)


def test_snapshot_contains_all_62_v1_tickers(snap):
    tickers = set(snap["tickers"].keys())
    assert len(tickers) == 62
    assert tickers == _EXPECTED_TICKERS


def test_every_entry_has_required_fields(snap):
    for tk, entry in snap["tickers"].items():
        assert _REQUIRED_FIELDS <= set(entry.keys()), f"{tk} missing fields"
        assert isinstance(entry["guards_triggered"], list)
        assert entry["confidence"] in ("high", "medium", "low", "none")


# ── spot-checks against known V1 postures ────────────────────────────────────────
def test_spotcheck_known_postures(snap):
    t = snap["tickers"]
    assert t["ICICIBANK"]["posture"] == "SUPPORTED_BY_ROE"
    assert t["HDFCBANK"]["posture"] == "DEMANDING_VS_ROE"
    assert t["TCS"]["posture"] == "SUPPORTED_BY_QUALITY"
    assert t["SBILIFE"]["posture"] == "INSUFFICIENT_EVIDENCE"          # H4 insurance
    assert "H4-insurance" in t["SBILIFE"]["guards_triggered"]
    assert t["SAIL"]["posture"] == "INSUFFICIENT_EVIDENCE"             # cyclical trough
    assert "TR-cyclical-trough" in t["SAIL"]["guards_triggered"]


def test_powergrid_not_insufficient_after_part1_fix(snap):
    # Part 1 fix: POWERGRID (regulated utility) must NOT be refused.
    pg = snap["tickers"]["POWERGRID"]
    assert pg["posture"] != "INSUFFICIENT_EVIDENCE"
    assert pg["guards_triggered"] == []
