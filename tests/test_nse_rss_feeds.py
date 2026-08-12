import requests
import pytest

import data.nse_rss_feeds as rf


class FakeResponse:
    def __init__(self, status=200, content=b""):
        self.status_code = status
        self.content = content

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"status {self.status_code}")


SAMPLE_FEED = b"""<?xml version='1.0'?><rss><channel><item><title>Related Party: RELIANCE</title><link>http://x</link><description>Desc</description><pubDate>Tue, 01 Jul 2026</pubDate></item></channel></rss>"""


def test_fetch_feed_success(monkeypatch):
    def fake_get(url, headers=None, timeout=None):
        return FakeResponse(200, SAMPLE_FEED)

    monkeypatch.setattr(requests, "get", fake_get, raising=True)
    rf._feed_cache = rf._feed_cache.__class__(ttl_seconds=1, name="nse_rss_test")

    items = rf.fetch_feed("related_party_transactions", use_cache=False)
    assert isinstance(items, list)
    assert items and "Related Party" in items[0]["title"]
    diag = rf.get_last_diagnostic("related_party_transactions")
    assert diag and diag.get("ok") is True


def test_fetch_feed_parse_error(monkeypatch):
    def fake_get(url, headers=None, timeout=None):
        return FakeResponse(200, b"<rss><broken></rss>")

    monkeypatch.setattr(requests, "get", fake_get, raising=True)
    rf._feed_cache = rf._feed_cache.__class__(ttl_seconds=1, name="nse_rss_test")

    items = rf.fetch_feed("related_party_transactions", use_cache=False)
    assert items == []
    diag = rf.get_last_diagnostic("related_party_transactions")
    assert diag and diag.get("ok") is False


def test_unknown_category_returns_empty():
    out = rf.fetch_feed("no_such_category")
    assert out == []


def test_get_items_for_company_filters(monkeypatch):
    def fake_get(url, headers=None, timeout=None):
        return FakeResponse(200, SAMPLE_FEED)

    monkeypatch.setattr(requests, "get", fake_get, raising=True)
    rf._feed_cache = rf._feed_cache.__class__(ttl_seconds=1, name="nse_rss_test")

    matched = rf.get_items_for_company("related_party_transactions", "RELIANCE.NS")
    assert isinstance(matched, list)
    assert matched and "RELIANCE" in matched[0]["title"].upper()
