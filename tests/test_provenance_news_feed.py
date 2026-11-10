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

from scripts.provider_canary import check_news_items  # noqa: E402  (shared with the weekly canary)


@pytest.mark.slow
def test_google_news_rss_live_canary_returns_items() -> None:
    """Live canary: a common-name query yields a non-empty item list with
    the shape the fetcher and downstream consumers expect."""
    from data.news_feed import fetch_news

    items = fetch_news("RELIANCE", company_name="Reliance Industries", max_items=5)

    failure = check_news_items(items)
    assert failure is None, f"Google News RSS: {failure}"
