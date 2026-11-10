"""utils/vix.py tiered fetch (NSE allIndices -> Yahoo ^INDIAVIX), fail-closed.

Offline: every network boundary is mocked.
"""
from __future__ import annotations

import pytest

import utils.vix as V

# Captured at collection, before conftest's offline stub replaces it per test.
_REAL_NSE_PAYLOAD = V._nse_all_indices_payload


def _nse_payload(last=14.25, pct=-2.5, prev=14.62, name="INDIA VIX"):
    return {"data": [
        {"index": "NIFTY 50", "last": 24123.4, "percentChange": 0.4},
        {"index": name, "indexSymbol": name, "last": last,
         "percentChange": pct, "previousClose": prev},
    ]}


def _yahoo_payload(closes=(15.0, 18.4)):
    return {"chart": {"result": [{
        "meta": {}, "timestamp": [1_760_000_000 + 86_400 * i for i in range(len(closes))],
        "indicators": {"quote": [{"close": list(closes)}]},
    }], "error": None}}


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    monkeypatch.setattr(V, "_VIX_CACHE", None)
    calls = []

    def _yahoo_should_not_run(timeout=10):
        calls.append("yahoo")
        return _yahoo_payload()
    monkeypatch.setattr(V, "_yahoo_chart_payload", _yahoo_should_not_run)
    return calls


def _boom(*_a, **_k):
    raise ConnectionError("network blocked")


def test_nse_tier_answers_first(monkeypatch, _fresh):
    monkeypatch.setattr(V, "_nse_all_indices_payload", lambda timeout=10: _nse_payload())
    info = V.get_india_vix_regime()
    assert info["vix"] == 14.25
    assert info["regime"] == "normal"
    assert info["allow_buy"] is True
    assert info["vix_pct_chg"] == -2.5
    assert info["source"] == "NSE"
    assert info["reason"] == ""
    assert _fresh == []                         # Yahoo never called


def test_nse_tier_uses_the_shared_nse_session(monkeypatch):
    """The NSE tier reuses data.nse_corp_info's session + homepage warm-up."""
    import data.nse_corp_info as NCI

    class _Resp:
        status_code = 200

        def json(self):
            return _nse_payload(last="29.10", pct=None, prev="25.00")

    class _Sess:
        def __init__(self):
            self.urls = []

        def get(self, url, timeout=None):
            self.urls.append(url)
            return _Resp()

    sess = _Sess()
    monkeypatch.setattr(NCI, "_session_singleton", sess)
    monkeypatch.setattr(V, "_nse_all_indices_payload", _REAL_NSE_PAYLOAD)
    info = V.get_india_vix_regime()
    assert sess.urls == ["https://www.nseindia.com/", V.NSE_ALL_INDICES_URL]
    assert info["vix"] == 29.1 and info["regime"] == "panic"
    assert info["allow_buy"] is False                       # VIX > 28
    assert info["vix_pct_chg"] == pytest.approx(16.4)       # from previousClose


def test_nse_fails_falls_back_to_yahoo(monkeypatch, _fresh):
    monkeypatch.setattr(V, "_nse_all_indices_payload", _boom)
    info = V.get_india_vix_regime()
    assert info["source"] == "Yahoo"
    assert info["vix"] == 18.4 and info["regime"] == "elevated"
    assert info["allow_buy"] is True
    assert [a["source"] for a in info["attempts"]] == ["NSE", "Yahoo"]
    assert info["attempts"][0]["ok"] is False
    assert "ConnectionError" in info["attempts"][0]["reason"]


def test_all_sources_fail_closed(monkeypatch):
    monkeypatch.setattr(V, "_nse_all_indices_payload", _boom)
    monkeypatch.setattr(V, "_yahoo_chart_payload", _boom)
    info = V.get_india_vix_regime()
    assert info["vix"] is None
    assert info["regime"] == "unknown"
    assert info["allow_buy"] is False
    assert info["reason"] == "VIX unavailable from NSE / Yahoo"
    assert info["source"] is None
    diag = V.get_last_diagnostic()
    assert diag["ok"] is False and "NSE:" in diag["reason"] and "Yahoo:" in diag["reason"]
    cap = V.unavailable_caption(info)
    assert "VIX unavailable from NSE / Yahoo" in cap
    assert V.unavailable_caption({"vix": 14.0, "regime": "normal"}) == ""


def test_outage_is_cached_briefly_then_retried(monkeypatch):
    monkeypatch.setattr(V, "_nse_all_indices_payload", _boom)
    monkeypatch.setattr(V, "_yahoo_chart_payload", _boom)
    assert V.get_india_vix_regime()["vix"] is None
    monkeypatch.setattr(V, "_nse_all_indices_payload", lambda timeout=10: _nse_payload())
    assert V.get_india_vix_regime()["vix"] is None            # still inside fail TTL
    V._VIX_CACHE["_ts"] -= V._VIX_FAIL_TTL + 1
    assert V.get_india_vix_regime()["source"] == "NSE"


@pytest.mark.parametrize("payload", [
    {"data": [{"index": "NIFTY 50", "last": 24000}]},          # no INDIA VIX row
    {"data": [{"index": "INDIA VIX", "last": "-"}]},           # non-numeric
    {"data": [{"index": "INDIA VIX", "last": None}]},          # null
    {"data": [{"index": "INDIA VIX", "last": 0}]},             # implausible
    {"rows": []},                                               # no data list
    ["not", "a", "dict"],
])
def test_malformed_nse_payload_goes_to_next_tier(monkeypatch, _fresh, payload):
    monkeypatch.setattr(V, "_nse_all_indices_payload", lambda timeout=10: payload)
    info = V.get_india_vix_regime()
    assert info["source"] == "Yahoo"
    assert _fresh == ["yahoo"]
    assert "schema drift" in info["attempts"][0]["reason"] or "plausible" in info["attempts"][0]["reason"]


def test_trading_signals_delegates_to_utils_vix(monkeypatch):
    import trading.signals as TS
    monkeypatch.setattr(V, "_nse_all_indices_payload", _boom)
    monkeypatch.setattr(V, "_yahoo_chart_payload", _boom)
    info = TS.get_india_vix_regime()
    assert info["allow_buy"] is False and info["reason"]


def test_vix_unavailable_alert_is_sent_once_per_day(monkeypatch):
    import alerts.check_alerts as ca
    sent = []
    monkeypatch.setattr(ca, "dispatch", lambda msg, **k: sent.append(msg) or True)
    monkeypatch.setattr(V, "get_india_vix_regime",
                        lambda: {"vix": None, "regime": "unknown", "allow_buy": False,
                                 "reason": "VIX unavailable from NSE / Yahoo"})
    state: dict = {}
    assert ca.check_vix_regime(state, "2026-11-10") == 1
    assert ca.check_vix_regime(state, "2026-11-10") == 0
    assert "VIX unavailable from NSE / Yahoo" in sent[0]
    for word in ("buy", "sell"):
        assert word not in sent[0].lower()
