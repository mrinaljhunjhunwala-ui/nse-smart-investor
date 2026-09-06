"""
Live canary for analysis/fundamentals/providers/screener_fundamentals.py -
the other provider the 2026-09-06 audit caught silently degrading
(finding #7: P/B silently None because currency-denominated fields
weren't stripping ₹ / Cr suffixes).

Marked `slow` per Task 2.5 - out of the default lane; run with
`pytest -m slow` on a periodic sweep.

Asserts against the live Screener page:
  1. The provider is available (bs4 installed)
  2. Fetching a known-good large-cap ticker returns a dict
  3. Market Cap, Current Price, Book Value all parse to non-None floats.
     These are the exact fields the 2026-09-06 fix restored - if any of
     them regresses to None, either the Screener HTML restructured OR
     the parser silently dropped the fix.
"""
from __future__ import annotations

import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


@pytest.mark.slow
def test_screener_top_ratios_live_canary_pb_inputs_not_none() -> None:
    """Live canary: assert Screener's Market Cap / Current Price / Book Value
    all parse to a number. These are the 3 fields whose silent-None state
    killed sector-aware P/B scoring for banks / NBFCs / insurers per
    Guardrail 3 pre-FIX PROV-2026-09-06.

    If this test fails, either:
      (a) Screener changed the currency HTML structure again, or
      (b) somebody reverted the _read_top_ratios fix.
    Both need immediate attention - see docs/DATA_PROVENANCE_2026-09.md #7.
    """
    pytest.importorskip("bs4")

    from analysis.fundamentals.providers.screener_fundamentals import (
        ScreenerFundamentalProvider,
    )

    provider = ScreenerFundamentalProvider()
    if not provider.is_available():
        pytest.skip("Screener provider not available (bs4 missing)")

    raw = provider._raw("RELIANCE")
    if raw is None or raw == {}:
        pytest.fail(
            "Screener returned no data for RELIANCE - "
            "network / HTML structure change / URL retirement."
        )

    top = raw.get("top") or {}
    assert isinstance(top, dict) and top, "top-ratios block missing from parsed page"

    for field in ("Market Cap", "Current Price", "Book Value"):
        assert field in top, (
            f"{field!r} missing from top-ratios - Screener HTML may have changed"
        )
        assert top[field] is not None, (
            f"{field!r} parsed to None - regression against FIX PROV-2026-09-06. "
            f"Currency prefix / suffix stripping likely broken."
        )
        assert isinstance(top[field], (int, float)), (
            f"{field!r} parsed to {type(top[field]).__name__}, expected number"
        )
        assert top[field] > 0, (
            f"{field!r} parsed to {top[field]} - suspiciously non-positive"
        )
