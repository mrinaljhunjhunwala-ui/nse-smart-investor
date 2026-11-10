"""
Live canary for utils/vix.py - the India VIX regime classifier.

VIX drives the sentiment pillar in analysis/score.py and gates BUY
signals across the app via `allow_buy` when regime is elevated / fear /
panic. A silent break here would decouple every scored ticker from the
current market fear regime.

Marked `slow` per Task 2.5.

Asserts:
  1. get_india_vix_regime returns a dict
  2. The `vix` field is a positive finite float
  3. The `regime` field is one of the 5 documented buckets
  4. The `allow_buy` field is a bool
"""
from __future__ import annotations

import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from scripts.provider_canary import check_vix_row  # noqa: E402  (shared with the weekly canary)


@pytest.mark.slow
def test_india_vix_live_canary_returns_valid_regime() -> None:
    """Live canary: the tiered VIX fetch (NSE allIndices -> Yahoo) returns a parsable VIX + regime."""
    from utils.vix import get_india_vix_regime

    row = get_india_vix_regime()
    failure = check_vix_row(row)
    assert failure is None, f"{failure} (source={row.get('source')}, attempts={row.get('attempts')})"
