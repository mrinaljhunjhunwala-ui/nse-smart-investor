import requests
import pytest
import types

import data.nse_corp_info as nci


class FakeResponse:
    def __init__(self, status=200, json_data=None, content=b""):
        self.status_code = status
        self._json = json_data
        self.content = content

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"status {self.status_code}")

    def json(self):
        if isinstance(self._json, Exception):
            raise self._json
        return self._json


def test_get_corp_info_success(monkeypatch):
    # Simulate homepage GET then API GET returning a dict
    def fake_get(self, url, headers=None, timeout=None):
        if url.endswith("/"):
            return FakeResponse(200, {"ok": True})
        # API path
        return FakeResponse(200, {"latest_announcements": [{"symbol": "RELIANCE"}]})

    monkeypatch.setattr(requests.Session, "get", fake_get, raising=True)
    # reset session singleton to ensure a fresh session is used
    nci._session_singleton = None

    res = nci.get_corp_info("RELIANCE.NS", use_cache=False)
    assert isinstance(res, dict)
    assert "latest_announcements" in res
    diag = nci.get_last_diagnostic("RELIANCE.NS")
    assert diag is not None and diag.get("ok") is True


def test_get_corp_info_blocked_403(monkeypatch):
    # Simulate homepage GET then API returning 403 so get_json retries then raises _NseFetchError
    def fake_get(self, url, headers=None, timeout=None):
        return FakeResponse(403, None)

    monkeypatch.setattr(requests.Session, "get", fake_get, raising=True)
    nci._session_singleton = None

    res = nci.get_corp_info("RELIANCE.NS", use_cache=False)
    assert res == {}
    diag = nci.get_last_diagnostic("RELIANCE.NS")
    assert diag is not None
    assert diag.get("ok") is False
    assert diag.get("status_code") == 403


def test_get_corp_info_malformed_json(monkeypatch):
    def fake_get(self, url, headers=None, timeout=None):
        # Return a JSON that's not a dict (e.g., a list)
        if url.endswith("/"):
            return FakeResponse(200, {"ok": True})
        return FakeResponse(200, [1, 2, 3])

    monkeypatch.setattr(requests.Session, "get", fake_get, raising=True)
    nci._session_singleton = None

    res = nci.get_corp_info("RELIANCE.NS", use_cache=False)
    assert res == {}
    diag = nci.get_last_diagnostic("RELIANCE.NS")
    assert diag is not None and diag.get("ok") is False


def test_get_corp_info_timeout(monkeypatch):
    def fake_get(self, url, headers=None, timeout=None):
        raise requests.Timeout("timed out")

    monkeypatch.setattr(requests.Session, "get", fake_get, raising=True)
    nci._session_singleton = None

    res = nci.get_corp_info("RELIANCE.NS", use_cache=False)
    assert res == {}
    diag = nci.get_last_diagnostic("RELIANCE.NS")
    assert diag is not None and diag.get("ok") is False
