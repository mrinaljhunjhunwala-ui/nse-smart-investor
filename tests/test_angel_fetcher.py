import json
import types
import pytest
import requests
from unittest.mock import Mock

import data.angel_fetcher as af


class FakeResponse:
    def __init__(self, status=200, data=None):
        self.status_code = status
        self._data = data or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"status {self.status_code}")

    def json(self):
        if isinstance(self._data, Exception):
            raise self._data
        return self._data


class FakeSession:
    def __init__(self):
        self.posts = []
        self.get_calls = []

    def post(self, url, json=None, headers=None, timeout=None):
        self.posts.append((url, json))
        # login endpoint
        if 'loginByPassword' in url:
            return FakeResponse(200, {"status": True, "data": {"jwtToken": "J", "feedToken": "F"}})
        if 'searchScrip' in url:
            return FakeResponse(200, {"data": [{"tradingsymbol": json.get("searchscrip"), "symboltoken": "123", "instrumenttype": "EQ"}]})
        if 'getCandleData' in url:
            return FakeResponse(200, {"data": [["2026-07-01 09:15", 100, 101, 99, 100, 1000]]})
        if 'quote' in url:
            return FakeResponse(200, {"data": {"fetched": [{"ltp": 100, "close": 99, "tradeVolume": 1000}]}})
        return FakeResponse(404)

    def get(self, url, headers=None, timeout=None):
        self.get_calls.append(url)
        return FakeResponse(200, {"dummy": True})


@pytest.fixture(autouse=True)
def patch_session(monkeypatch):
    # Replace the module-level _http Session with our fake
    fake = FakeSession()
    monkeypatch.setattr(af, "_http", fake)
    af._SESSION["jwt"] = None
    yield fake


def test_login_and_fetch_historical_success(patch_session):
    # ensure login works and fetch_historical returns DataFrame-like data
    df = af.fetch_historical("RELIANCE.NS", period="5d", interval="1d")
    assert df is not None
    # check that session jwt got set
    assert af._SESSION["jwt"] is not None


def test_get_full_quote_success(patch_session):
    q = af.get_full_quote("RELIANCE.NS")
    assert q is not None
    assert q["price"] == 100


def test_get_batch_quotes_success(patch_session):
    res = af.get_batch_quotes(["RELIANCE.NS", "TCS.NS"])
    assert isinstance(res, dict)
    # both keys present (FakeSession returns token for any searchScrip)
    assert "RELIANCE.NS" in res and "TCS.NS" in res


def test_login_failure(monkeypatch):
    # simulate login returning status false
    class BadSession(FakeSession):
        def post(self, url, json=None, headers=None, timeout=None):
            if 'loginByPassword' in url:
                return FakeResponse(200, {"status": False, "message": "bad creds"})
            return super().post(url, json=json, headers=headers, timeout=timeout)

    monkeypatch.setattr(af, "_http", BadSession())
    af._SESSION["jwt"] = None
    # login should fail and fetch_historical should return None
    assert af.fetch_historical("RELIANCE.NS") is None


def test_malformed_json_from_searchscrip(monkeypatch):
    class MalformSession(FakeSession):
        def post(self, url, json=None, headers=None, timeout=None):
            if 'searchScrip' in url:
                return FakeResponse(200, Exception("Expecting value"))
            return super().post(url, json=json, headers=headers, timeout=timeout)

    monkeypatch.setattr(af, "_http", MalformSession())
    af._SESSION["jwt"] = None
    # Token lookup fails but should be handled and return None
    assert af.get_full_quote("RELIANCE.NS") is None


def test_searchscrip_rate_limit_trips_breaker(monkeypatch):
    # simulate repeated failures to trip the breaker
    class FailSession(FakeSession):
        def post(self, url, json=None, headers=None, timeout=None):
            if 'searchScrip' in url:
                return FakeResponse(500, {})
            return super().post(url, json=json, headers=headers, timeout=timeout)

    s = FailSession()
    monkeypatch.setattr(af, "_http", s)
    af._TOKEN_CACHE.clear()
    # call _get_token several times to record failures
    for _ in range(af._BREAKER_THRESHOLD + 1):
        _ = af._get_token("RELIANCE", {"jwt": "J", "api_key": "K"})
    assert af._breaker_tripped()

