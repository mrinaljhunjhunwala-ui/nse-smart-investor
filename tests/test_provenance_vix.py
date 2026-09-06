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

import math
import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

_VALID_REGIMES = {"complacency", "normal", "elevated", "fear", "panic"}


@pytest.mark.slow
def test_india_vix_live_canary_returns_valid_regime() -> None:
    """Live canary: ^INDIAVIX chart endpoint returns a parsable VIX + regime."""
    from utils.vix import get_india_vix_regime

    row = get_india_vix_regime()
    assert isinstance(row, dict), f"expected dict, got {type(row).__name__}"

    vix = row.get("vix")
    assert vix is not None, "VIX value missing - shape drift or auth failure"
    vix_f = float(vix)
    assert math.isfinite(vix_f) and vix_f > 0, f"suspicious VIX: {vix_f}"
    assert 5.0 < vix_f < 100.0, (
        f"VIX {vix_f} outside plausible band [5, 100]"
    )

    regime = row.get("regime")
    assert regime in _VALID_REGIMES, (
        f"regime {regime!r} not in documented set {_VALID_REGIMES}"
    )

    assert isinstance(row.get("allow_buy"), bool), (
        f"allow_buy must be a bool, got {type(row.get('allow_buy')).__name__}"
    )
