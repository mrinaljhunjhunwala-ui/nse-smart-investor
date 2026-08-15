import requests
import pytest
import xml.etree.ElementTree as ET

import data.news_feed as nf


class FakeResponse:
    def __init__(self, status=200, content=b"", raise_on_json=False):
        self.status_code = status
        self.content = content

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"status {self.status_code}")


def sample_rss(title="Test Title", link="http://example.com", pubDate="Tue, 01 Jul 2026 10:00:00 GMT"):
    return f"""<?xml version="1.0" encoding="UTF-8"?><rss><channel><item><title>{title}</title><link>{link}</link><pubDate>{pubDate}</pubDate><source>Source A</source></item></channel></rss>""".encode("utf-8")


def test_fetch_news_success(monkeypatch):
    def fake_get(url, headers=None, timeout=None):
        return FakeResponse(200, sample_rss())

    monkeypatch.setattr(requests, "get", fake_get, raising=True)
    nf._cache = nf._cache.__class__(ttl_seconds=1, name="news_feed_test")  # reset cache

    items = nf.fetch_news("RELIANCE.NS", company_name=None, use_cache=False)
    assert isinstance(items, list)
    assert len(items) == 1
    assert items[0]["title"] == "Test Title"
    diag = nf.get_last_diagnostic("RELIANCE.NS")
    assert diag and diag.get("ok") is True


def test_fetch_news_request_exception(monkeypatch):
    def bad_get(url, headers=None, timeout=None):
        raise requests.Timeout("timeout")

    monkeypatch.setattr(requests, "get", bad_get, raising=True)
    nf._cache = nf._cache.__class__(ttl_seconds=1, name="news_feed_test")

    items = nf.fetch_news("RELIANCE.NS", company_name=None, use_cache=False)
    assert items == []
    diag = nf.get_last_diagnostic("RELIANCE.NS")
    assert diag and diag.get("ok") is False


def test_fetch_news_parse_error(monkeypatch):
    def fake_get(url, headers=None, timeout=None):
        return FakeResponse(200, b"<rss><broken></rss>")

    monkeypatch.setattr(requests, "get", fake_get, raising=True)
    nf._cache = nf._cache.__class__(ttl_seconds=1, name="news_feed_test")

    items = nf.fetch_news("RELIANCE.NS", company_name=None, use_cache=False)
    assert items == []
    diag = nf.get_last_diagnostic("RELIANCE.NS")
    assert diag and diag.get("ok") is False
