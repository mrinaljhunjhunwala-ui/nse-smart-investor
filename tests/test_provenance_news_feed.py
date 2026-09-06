"""
Live canary for data/news_feed.py - Google News RSS for per-symbol news.

The audit (finding #6a) confirmed the endpoint is healthy today. This
canary locks in that shape: RSS with item[].title / .link / .pub_date /
.source. Google News RSS is one of only two qualitative signals
currently live in production (NSE corp-info was dark until FIX
PROV-2026-09-06, and BSE is dep-gated), so silent breakage here
significantly degrades the qualitative-flags pipeline.

Marked `slow` per Task 2.5.
"""
from __future__ import annotations

import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


@pytest.mark.slow
def test_google_news_rss_live_canary_returns_items() -> None:
    """Live canary: a common-name query yields a non-empty item list with
    the shape the fetcher and downstream consumers expect."""
    from data.news_feed import fetch_news

    items = fetch_news("RELIANCE", company_name="Reliance Industries", max_items=5)

    assert isinstance(items, list), (
        f"expected list, got {type(items).__name__}"
    )
    assert items, (
        "Google News RSS returned zero items for a common-name query - "
        "endpoint drift or geo-block."
    )

    first = items[0]
    # fetch_news returns dicts; each must carry the fields the qualitative-
    # flags aggregator reads.
    assert isinstance(first, dict), (
        f"expected item to be dict, got {type(first).__name__}"
    )
    for field in ("title", "link"):
        assert first.get(field), (
            f"item missing/empty {field!r}: {first!r}"
        )
