"""Upstox market-data source: offline, every HTTP call mocked."""
from __future__ import annotations

import gzip
import json
import logging

import pandas as pd
import pytest

import data.upstox_fetcher as up

TOKEN = "SECRET-TEST-TOKEN-abc123"

INSTRUMENTS = [
    {"segment": "NSE_EQ", "instrument_type": "EQ", "trading_symbol": "RELIANCE",
     "instrument_key": "NSE_EQ|INE002A01018", "name": "RELIANCE INDUSTRIES LTD"},
    {"segment": "NSE_EQ", "instrument_type": "EQ", "trading_symbol": "TCS",
     "instrument_key": "NSE_EQ|INE467B01029", "name": "TATA CONSULTANCY SERV LT"},
    {"segment": "NSE_EQ", "instrument_type": "BE", "trading_symbol": "TCS",
     "instrument_key": "NSE_EQ|WRONG", "name": "dup"},
    {"segment": "NSE_INDEX", "instrument_type": "INDEX", "trading_symbol": "NIFTY",
     "instrument_key": "NSE_INDEX|Nifty 50", "name": "Nifty 50"},
    {"segment": "NSE_FO", "instrument_type": "FUT", "trading_symbol": "RELIANCE FUT",
     "instrument_key": "NSE_FO|1"},
]

QUOTE_PAYLOAD = {
    "status": "success",
    "data": {
        "NSE_EQ:RELIANCE": {
            "instrument_token": "NSE_EQ|INE002A01018", "symbol": "RELIANCE",
            "last_price": 1300.0, "net_change": 26.0, "volume": 1234567,
            "average_price": 1295.5, "last_trade_time": "1732523400000",
            "ohlc": {"open": 1280.0, "high": 1305.0, "low": 1278.0, "close": 1300.0},
        },
        "NSE_INDEX:Nifty 50": {
            "instrument_token": "NSE_INDEX|Nifty 50", "last_price": 24000.0,
            "net_change": -120.0, "volume": 0, "ohlc": {"high": 24100.0, "low": 23900.0},
        },
    },
}

CANDLE_PAYLOAD = {
    "status": "success",
    "data": {"candles": [
        ["2026-11-25T00:00:00+05:30", 1290, 1305, 1280, 1300, 5000000, 0],
        ["2026-11-24T00:00:00+05:30", 1270, 1295, 1265, 1274, 4000000, 0],
    ]},
}


class _Resp:
    def __init__(self, status=200, payload=None, content=b"", text=""):
        self.status_code = status
        self._payload = payload
        self.content = content
        self.text = text or (json.dumps(payload) if payload is not None else "")

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


@pytest.fixture
def calls(monkeypatch, tmp_path):
    """Configured token, isolated cache dir, and a router of fake responses."""
    monkeypatch.setenv("UPSTOX_ANALYTICS_TOKEN", TOKEN)
    monkeypatch.setattr(up, "_CACHE_DIR", tmp_path)
    monkeypatch.setattr(up, "_MIN_GAP_S", 0.0)
    up._reset_state()
    log: list = []
    routes = {"quote": _Resp(200, QUOTE_PAYLOAD), "candle": _Resp(200, CANDLE_PAYLOAD),
              "instr": _Resp(200, content=gzip.compress(json.dumps(INSTRUMENTS).encode()))}

    def fake_get(url, params=None, headers=None, timeout=None):
        log.append({"url": url, "params": params, "headers": headers})
        if "instruments" in url:
            return routes["instr"]
        if "/v2/market-quote" in url:
            return routes["quote"]
        if "historical-candle" in url:
            return routes["candle"]
        raise AssertionError(url)

    monkeypatch.setattr(up.requests, "get", fake_get)
    yield {"log": log, "routes": routes}
    up._reset_state()


def test_not_configured_makes_no_calls(monkeypatch):
    monkeypatch.delenv("UPSTOX_ANALYTICS_TOKEN", raising=False)
    up._reset_state()

    def boom(*a, **k):
        raise AssertionError("network call while not configured")

    monkeypatch.setattr(up.requests, "get", boom)
    assert up.is_configured() is False
    assert up.get_batch_quotes(["RELIANCE.NS"]) == {}
    assert up.get_live_quote("RELIANCE.NS") is None
    assert up.fetch_historical("RELIANCE.NS") is None


def test_secrets_section_is_read(monkeypatch):
    monkeypatch.delenv("UPSTOX_ANALYTICS_TOKEN", raising=False)
    monkeypatch.setattr(up, "_secrets_section", lambda: {"analytics_token": " tok "})
    assert up.is_configured() and up._token() == "tok"
    monkeypatch.setattr(up, "_secrets_section", lambda: {"analytics_token": ""})
    assert not up.is_configured()


def test_symbol_map_and_keys(calls):
    m = up.build_symbol_map(INSTRUMENTS)
    assert m["RELIANCE"] == "NSE_EQ|INE002A01018"
    assert m["TCS"] == "NSE_EQ|INE467B01029"            # EQ beats BE
    assert "RELIANCE FUT" not in m
    assert up.instrument_key("RELIANCE.NS") == "NSE_EQ|INE002A01018"
    assert up.instrument_key("reliance") == "NSE_EQ|INE002A01018"
    assert up.instrument_key("^NSEI") == "NSE_INDEX|Nifty 50"
    assert up.instrument_key("^NSEBANK") == "NSE_INDEX|Nifty Bank"
    assert up.instrument_key("^INDIAVIX") == "NSE_INDEX|India VIX"
    assert up.instrument_key("RELIANCE.BO") is None
    assert up.instrument_key("NOSUCH") is None
    # cached on disk: a fresh process state reads the file, no second download
    n = sum("instruments" in c["url"] for c in calls["log"])
    up._MAP.clear()
    up._MAP_AT[0] = 0.0
    assert up.instrument_key("TCS") == "NSE_EQ|INE467B01029"
    assert sum("instruments" in c["url"] for c in calls["log"]) == n == 1


def test_quote_parsing(calls):
    out = up.get_batch_quotes(["RELIANCE.NS", "^NSEI", "TCS.NS"])
    r = out["RELIANCE.NS"]
    assert r["price"] == 1300.0 and r["prev_close"] == 1274.0
    assert r["chg_pct"] == pytest.approx((1300 / 1274 - 1) * 100)
    assert r["volume"] == 1234567 and r["source"] == "upstox"
    assert r["high"] == 1305.0 and r["vwap"] == 1295.5
    assert r["as_of"].startswith("2024-11-25T") and r["as_of"].endswith("+05:30")
    assert out["^NSEI"]["prev_close"] == 24120.0
    assert "TCS.NS" not in out                          # not in the response
    q = [c for c in calls["log"] if "/v2/market-quote" in c["url"]]
    assert len(q) == 1
    assert set(q[0]["params"]["instrument_key"].split(",")) == {
        "NSE_EQ|INE002A01018", "NSE_INDEX|Nifty 50", "NSE_EQ|INE467B01029"}
    assert q[0]["headers"]["Authorization"] == f"Bearer {TOKEN}"


def test_quote_batching(calls, monkeypatch):
    monkeypatch.setattr(up, "QUOTE_BATCH", 1)
    up.get_batch_quotes(["RELIANCE.NS", "TCS.NS"])
    assert sum("/v2/market-quote" in c["url"] for c in calls["log"]) == 2


def test_candle_parsing(calls):
    df = up.fetch_historical("RELIANCE.NS", period="5d", interval="1d")
    assert list(df.columns) == ["Open", "High", "Low", "Close", "Volume"]
    assert df.index.tz is None and df.index.is_monotonic_increasing
    assert df.index[0] == pd.Timestamp("2026-11-24") and df["Close"].iloc[-1] == 1300
    url = [c["url"] for c in calls["log"] if "historical-candle" in c["url"]][0]
    assert "/v3/historical-candle/NSE_EQ%7CINE002A01018/days/1/" in url


def test_intraday_candles_keep_time(calls):
    calls["routes"]["candle"] = _Resp(200, {"status": "success", "data": {"candles": [
        ["2026-11-25T09:15:00+05:30", 1, 2, 0.5, 1.5, 10, 0]]}})
    df = up.fetch_historical("RELIANCE.NS", period="5d", interval="5m")
    assert df.index[0] == pd.Timestamp("2026-11-25 09:15")
    assert any("/minutes/5/" in c["url"] for c in calls["log"])


@pytest.mark.parametrize("status", [401, 403])
def test_auth_error_trips_breaker_and_never_leaks_token(calls, caplog, status):
    calls["routes"]["quote"] = _Resp(status, text=f'{{"errors":"bad token {TOKEN}"}}')
    with caplog.at_level(logging.DEBUG):
        assert up.get_batch_quotes(["RELIANCE.NS"]) == {}
    assert up.breaker_open()
    assert f"HTTP {status}" in caplog.text and TOKEN not in caplog.text
    assert TOKEN not in json.dumps(up.status())
    n = len(calls["log"])
    assert up.get_batch_quotes(["RELIANCE.NS"]) == {}       # open: no call
    assert up.fetch_historical("RELIANCE.NS") is None
    assert len(calls["log"]) == n


def test_exception_text_is_scrubbed(calls, monkeypatch, caplog):
    def raising(url, params=None, headers=None, timeout=None):
        if "instruments" in url:
            return calls["routes"]["instr"]
        raise ConnectionError(f"failed with header Bearer {TOKEN}")

    monkeypatch.setattr(up.requests, "get", raising)
    with caplog.at_level(logging.DEBUG):
        assert up.fetch_historical("RELIANCE.NS") is None
    assert "ConnectionError" in caplog.text and TOKEN not in caplog.text


def test_repeated_failures_trip_breaker(calls):
    calls["routes"]["candle"] = _Resp(500, text="oops")
    for _ in range(up._FAIL_THRESHOLD):
        assert up.fetch_historical("RELIANCE.NS") is None
    assert up.breaker_open()


# ─── wiring into the existing tiers ─────────────────────────────────────────

def test_live_price_uses_upstox_first(calls, monkeypatch):
    import utils.live_price as lp
    monkeypatch.setattr(lp, "relay_quotes", lambda *a, **k: (_ for _ in ()).throw(AssertionError))
    q = lp.get_live_quote("RELIANCE.NS")
    assert q["source"] == "upstox" and q["price"] == 1300.0
    out = lp.get_live_prices_batch(["RELIANCE.NS", "^NSEI"])
    assert out["RELIANCE.NS"]["source"] == "upstox" and out["^NSEI"]["price"] == 24000.0


def test_live_price_falls_back_on_403(calls, monkeypatch):
    import utils.live_price as lp
    calls["routes"]["quote"] = _Resp(403, text="forbidden")
    monkeypatch.setattr(lp, "relay_quotes", lambda *a, **k: {})
    monkeypatch.setattr(lp, "_yahoo_json_quote", lambda s: {"price": 99.0, "prev_close": 98.0})
    import data.angel_fetcher as af
    monkeypatch.setattr(af, "is_configured", lambda: False)
    q = lp.get_live_quote("RELIANCE.NS")
    assert q["price"] == 99.0 and "source" not in q
    assert up.breaker_open()


def test_live_price_not_configured_never_touches_upstox(monkeypatch):
    import utils.live_price as lp
    monkeypatch.delenv("UPSTOX_ANALYTICS_TOKEN", raising=False)
    monkeypatch.setattr(up, "get_batch_quotes", lambda *a: (_ for _ in ()).throw(AssertionError))
    assert lp._upstox_quotes(["RELIANCE.NS"]) == {}


def test_fetcher_tier_upstox_then_fallback(calls, monkeypatch):
    import data.fetcher as f
    f.clear_fetch_cache()
    monkeypatch.setattr(f, "_coverage_problem", lambda df, period: None)
    monkeypatch.setattr(f, "_patch_stale_from_bhavcopy", lambda df, t, p: df)
    import data.angel_fetcher as af
    monkeypatch.setattr(af, "is_configured", lambda: (_ for _ in ()).throw(AssertionError("angel ran")))
    df = f.fetch_single("RELIANCE.NS", period="5d")
    assert df["Close"].iloc[-1] == 1300
    assert f.get_last_diagnostic("Upstox")["ok"] is True

    # 403 -> breaker -> next tier (Yahoo here)
    f.clear_fetch_cache()
    up._reset_state()
    calls["routes"]["candle"] = _Resp(403, text="forbidden")
    monkeypatch.setattr(af, "is_configured", lambda: False)
    monkeypatch.setattr(f, "_stooq_enabled", lambda: False)
    yahoo = pd.DataFrame({"Open": [1.0], "High": [1.0], "Low": [1.0], "Close": [7.0], "Volume": [1]},
                         index=pd.DatetimeIndex([pd.Timestamp("2026-11-25")], name="Date"))
    monkeypatch.setattr(f, "_fetch_yahoo_direct", lambda *a, **k: yahoo.copy())
    monkeypatch.setattr(f, "_price_store_split_check", lambda *a: None)
    try:
        from data import price_store as ps
        monkeypatch.setattr(ps, "enabled", lambda: False)
    except ImportError:
        pass
    df = f.fetch_single("RELIANCE.NS", period="5d")
    assert df["Close"].iloc[-1] == 7.0 and up.breaker_open()
    f.clear_fetch_cache()
