"""
Live canary for the Yahoo v8 chart API - Tier 2 of data/fetcher.py's
`Angel -> Stooq -> Yahoo` fallback chain, and the tier that carries most
of the load when Angel isn't available or Stooq is degraded.

Marked `slow` per Task 2.5. Run with `pytest -m slow`.

Asserts:
  1. A single-ticker fetch returns a non-empty DataFrame
  2. The DataFrame has all 5 OHLCV columns the score / indicator pipeline
     depends on (Open, High, Low, Close, Volume)
  3. At least one row is present with sane values

Failure modes this catches:
  - Yahoo v8 auth (cookie+crumb) breaking silently
  - Response schema drift renaming indicators.quote
  - Cloudflare 403 across the board (rate-limit / IP block)
"""
from __future__ import annotations

import os
import sys

import pandas as pd
import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


@pytest.mark.slow
def test_yahoo_v8_chart_live_canary_reliance() -> None:
    """Live canary: RELIANCE.NS via Yahoo v8 chart returns clean OHLCV.

    Uses _fetch_yahoo_direct so we bypass Angel and Stooq - the canary
    covers Yahoo specifically. If this fails but Angel is still working,
    Yahoo has drifted and the fallback chain is one link shorter than
    the app assumes.
    """
    from data.fetcher import _fetch_yahoo_direct  # noqa: WPS437

    df = _fetch_yahoo_direct("RELIANCE.NS", period="5d")

    assert isinstance(df, pd.DataFrame), (
        f"expected DataFrame, got {type(df).__name__}"
    )
    assert not df.empty, "Yahoo returned empty frame - auth or shape drift"

    required_cols = {"Open", "High", "Low", "Close", "Volume"}
    missing = required_cols - set(df.columns)
    assert not missing, f"missing columns: {sorted(missing)}"

    # Sanity: sane numeric close, positive volume
    last_close = float(df["Close"].iloc[-1])
    last_volume = float(df["Volume"].iloc[-1])
    assert last_close > 0, f"suspicious close: {last_close}"
    assert last_volume > 0, f"suspicious volume: {last_volume}"
