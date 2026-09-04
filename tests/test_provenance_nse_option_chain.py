"""
Canary tests for data/nse_option_chain.py — PCR + max-pain parser.

Offline fixture-based, Guardrail §14/16. The math helpers
(compute_pcr, compute_max_pain, compute_max_pain_distance_pct) get
dedicated tests because they encode the pillar's semantics.
"""
from __future__ import annotations

import datetime as _dt
import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from data.nse_option_chain import (   # noqa: E402
    compute_pcr, compute_max_pain, compute_max_pain_distance_pct,
    parse_option_chain, _nearest_expiry,
)


# ─────────────────────────────────────────────────────────────────────────────
# Math helpers
# ─────────────────────────────────────────────────────────────────────────────

def test_compute_pcr_basic():
    assert compute_pcr(total_ce_oi=1_000_000, total_pe_oi= 700_000) == 0.700
    assert compute_pcr(total_ce_oi=1_000_000, total_pe_oi=1_500_000) == 1.500
    assert compute_pcr(total_ce_oi=1_000_000, total_pe_oi=       0) == 0.000


def test_compute_pcr_undefined_when_ce_zero():
    assert compute_pcr(total_ce_oi=0,    total_pe_oi=100) is None
    assert compute_pcr(total_ce_oi=None, total_pe_oi=100) is None
    assert compute_pcr(total_ce_oi=100,  total_pe_oi=None) is None


def test_compute_max_pain_needs_at_least_3_strikes():
    assert compute_max_pain([]) is None
    assert compute_max_pain([(100, 10, 20)]) is None
    assert compute_max_pain([(100, 10, 20), (110, 5, 15)]) is None


def test_compute_max_pain_symmetric_oi():
    # Perfectly symmetric OI around 100 -> pin is 100
    strikes = [
        (90,  10_000, 10_000),
        (95,  10_000, 10_000),
        (100, 10_000, 10_000),
        (105, 10_000, 10_000),
        (110, 10_000, 10_000),
    ]
    assert compute_max_pain(strikes) == 100


def test_compute_max_pain_call_heavy_at_higher_strikes():
    # Heavy CE OI at 105 and 110 -> writers hurt if price closes above,
    # so max pain sits lower (below the heavy call band) to minimise
    # combined loss. Confirm the pin lands at or below 100 for this shape.
    strikes = [
        (90,   1_000, 20_000),
        (95,   1_000, 15_000),
        (100,  1_000, 10_000),
        (105, 50_000,  1_000),
        (110, 50_000,  1_000),
    ]
    mp = compute_max_pain(strikes)
    assert mp is not None
    assert mp <= 100, f"expected pin at/below 100 given put weight, got {mp}"


def test_compute_max_pain_distance_pct():
    assert compute_max_pain_distance_pct(spot=1050.0, max_pain_strike=1000.0) ==  5.0
    assert compute_max_pain_distance_pct(spot= 950.0, max_pain_strike=1000.0) == -5.0
    assert compute_max_pain_distance_pct(spot=None,   max_pain_strike=1000.0) is None
    assert compute_max_pain_distance_pct(spot=1000.0, max_pain_strike=None)   is None
    assert compute_max_pain_distance_pct(spot=1000.0, max_pain_strike=0)      is None


# ─────────────────────────────────────────────────────────────────────────────
# _nearest_expiry
# ─────────────────────────────────────────────────────────────────────────────

def test_nearest_expiry_picks_earliest_future():
    # NB: this test is deterministic only when all fixtures are in the
    # future. The dates below are picked far enough out (2030) to stay
    # valid indefinitely.
    got = _nearest_expiry([
        "26-Sep-2030", "31-Oct-2030", "28-Nov-2030"
    ])
    assert got == "26-Sep-2030"


def test_nearest_expiry_ignores_past_dates():
    # 2020 dates are all past; 2030 is future.
    got = _nearest_expiry([
        "25-Sep-2020", "30-Oct-2020", "26-Sep-2030"
    ])
    assert got == "26-Sep-2030"


def test_nearest_expiry_returns_none_when_all_past():
    assert _nearest_expiry(["25-Sep-2020", "30-Oct-2020"]) is None


# ─────────────────────────────────────────────────────────────────────────────
# parse_option_chain — end-to-end on synthetic NSE-shaped JSON
# ─────────────────────────────────────────────────────────────────────────────

def _synthetic_chain(strikes, spot=1000.0, expiry="26-Sep-2030",
                     extra_expiry="31-Oct-2030"):
    """Build a plausible NSE options-chain JSON for a symbol."""
    data = []
    for strike, ce_oi, pe_oi in strikes:
        data.append({
            "strikePrice": strike,
            "expiryDate":  expiry,
            "CE": {"openInterest": ce_oi, "lastPrice": 10.0},
            "PE": {"openInterest": pe_oi, "lastPrice": 10.0},
        })
        # Add far-expiry rows to confirm parser filters to nearest only
        data.append({
            "strikePrice": strike,
            "expiryDate":  extra_expiry,
            "CE": {"openInterest": 999_999, "lastPrice": 10.0},
            "PE": {"openInterest": 999_999, "lastPrice": 10.0},
        })
    return {
        "records": {
            "underlyingValue": spot,
            "expiryDates":     [expiry, extra_expiry],
            "data":            data,
        }
    }


def test_parse_option_chain_extracts_pcr_and_max_pain():
    strikes = [
        ( 950,  50_000,   200_000),
        ( 975,  80_000,   180_000),
        (1000, 100_000,   100_000),   # ATM
        (1025, 180_000,    80_000),
        (1050, 200_000,    50_000),
    ]
    payload = _synthetic_chain(strikes, spot=1000.0)
    row = parse_option_chain(payload, "INFY",
                             target_date=_dt.date(2026, 9, 4))
    assert row is not None
    assert row["symbol"]         == "INFY"
    assert row["date"]           == "2026-09-04"
    assert row["spot"]           == 1000.0
    assert row["nearest_expiry"] == "26-Sep-2030"
    # Total OI only across nearest expiry (far-expiry rows must be ignored)
    assert row["total_ce_oi"] == 610_000
    assert row["total_pe_oi"] == 610_000
    assert row["pcr"]         == 1.0
    assert row["n_strikes"]   == 5
    # Symmetric OI around 1000 -> pin at 1000, distance 0
    assert row["max_pain_strike"] == 1000
    assert row["max_pain_pct"]    == 0.0


def test_parse_option_chain_named_error_on_missing_records():
    # Non-empty payload but no 'records' key — the parser's second guard
    # (Guardrail §14 named ValueError on schema drift) fires here.
    with pytest.raises(ValueError, match="'records' missing"):
        parse_option_chain({"foo": "bar"}, "INFY")


def test_parse_option_chain_named_error_on_empty_data():
    payload = {"records": {"underlyingValue": 100, "expiryDates": [],
                            "data": []}}
    with pytest.raises(ValueError, match="records.data.*empty"):
        parse_option_chain(payload, "INFY")


def test_parse_option_chain_returns_none_when_no_future_expiry():
    # 2020 expiry is past
    payload = _synthetic_chain(
        [(100, 1, 1), (110, 1, 1), (120, 1, 1)],
        spot=110.0, expiry="25-Sep-2020", extra_expiry="30-Oct-2020",
    )
    row = parse_option_chain(payload, "INFY")
    assert row is None


def test_parse_option_chain_named_error_on_empty_payload():
    with pytest.raises(ValueError, match="empty payload"):
        parse_option_chain({}, "INFY")   # {} has no records key
