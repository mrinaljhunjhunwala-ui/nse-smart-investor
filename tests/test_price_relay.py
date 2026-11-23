"""Price relay (scripts/price_relay.py), its read tier in utils/live_price.py and the
stale-heartbeat warning in alerts/check_alerts.py. Offline: Angel One, the database
and Telegram are all faked."""
from __future__ import annotations

import datetime
import json

import pytest

import trade_store
import utils.live_price as lp
from scripts import price_relay as pr

IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
OPEN_DAY = datetime.datetime(2026, 11, 23, 11, 0, 0, tzinfo=IST)       # a Monday, trading day
SATURDAY = datetime.datetime(2026, 11, 21, 11, 0, 0, tzinfo=IST)


@pytest.fixture(autouse=True)
def _fresh_relay_cache():
    lp._reset_relay_cache()
    yield
    lp._reset_relay_cache()


class FakeStore:
    def __init__(self, kv=None, fail_reads=False):
        self.kv = dict(kv or {})
        self.writes = []
        self.reads = 0
        self.fail_reads = fail_reads

    def kv_get(self, key, default=None, user_id="default"):
        self.reads += 1
        if self.fail_reads:
            raise RuntimeError("db down")
        return self.kv.get((user_id, key), default)

    def kv_set(self, key, value, user_id="default", compact=False):
        self.writes.append((key, user_id, compact, json.loads(json.dumps(value))))
        self.kv[(user_id, key)] = value
        return True

    def fetch_open(self):
        import pandas as pd
        return pd.DataFrame({"ticker": ["PAPER1.NS"]})


def _angel_batch(calls):
    def batch(tickers):
        calls.append(list(tickers))
        return {t: {"price": 100.0 + i, "prev_close": 100.0, "volume": 1000} for i, t in enumerate(tickers)}
    return batch


# ── relay: window, symbol set, tick ─────────────────────────────────────────

@pytest.mark.parametrize("when,expected", [
    (OPEN_DAY.replace(hour=9, minute=7), False),
    (OPEN_DAY.replace(hour=9, minute=8), True),
    (OPEN_DAY.replace(hour=15, minute=35), True),
    (OPEN_DAY.replace(hour=15, minute=36), False),
    (SATURDAY, False),
    (datetime.datetime(2026, 11, 23, 5, 30, tzinfo=datetime.timezone.utc), True),   # 11:00 IST
])
def test_relay_window_uses_ist(when, expected):
    assert pr.in_relay_window(when) is expected


def test_symbol_set_priority_dedupe_and_cap(monkeypatch):
    today = OPEN_DAY.strftime("%Y-%m-%d")
    store = FakeStore({
        ("default", "manual_portfolio_holdings"): [{"ticker": "ONGC.NS", "quantity": 5}],
        ("default", "watchlist"): ["TCS.NS", "ONGC.NS", "FOO.BO"],
        ("_system", "morning_digest_picks"): {"date": today, "buys": [{"ticker": "SGMART.NS"}]},
        ("_system", f"buy_calls:{today}"): [{"symbol": "DLF"}],
        ("_system", "intraday_levels"): {"date": today, "levels": {"MCX": {}}},
        ("_system", "top_picks_snapshot"): {"data": {"buys": [{"ticker": "NTPC.NS"}]}},
        ("_system", "tomorrow_watchlist_snapshot"): {"data": {"breakout_candidates": [{"ticker": "DHANBANK.NS"}]}},
    })
    src = pr.SymbolSource(store)
    syms = src.symbols(OPEN_DAY)
    assert syms[:8] == ["ONGC", "TCS", "PAPER1", "SGMART", "DLF", "MCX", "^NSEI", "^NSEBANK"]
    assert "^INDIAVIX" in syms and "NTPC" in syms and "DHANBANK" in syms
    assert "FOO" not in syms and "FOO.BO" not in syms
    assert len(syms) == len(set(syms))
    assert "RELIANCE" in syms                                      # NIFTY 50 fills the rest
    monkeypatch.setenv("RELAY_MAX_SYMBOLS", "10")
    assert len(pr.SymbolSource(store).symbols(OPEN_DAY)) == 10


def test_symbol_set_refresh_cadence():
    t = [0.0]
    store = FakeStore()
    src = pr.SymbolSource(store, small_every_s=300, snapshot_every_s=1800, clock=lambda: t[0])
    src.symbols(OPEN_DAY)
    first = store.reads
    t[0] = 100
    src.symbols(OPEN_DAY)
    assert store.reads == first                                    # cached
    t[0] = 301
    src.symbols(OPEN_DAY)
    small_reads = store.reads - first
    assert 0 < small_reads < first                                 # small keys only, not the snapshots


def test_tick_chunks_by_50_and_writes_one_doc(monkeypatch):
    calls = []
    syms = [f"S{i}" for i in range(120)] + ["^NSEI"]

    class Src:
        def symbols(self, now=None):
            return syms

    store = FakeStore()
    relay = pr.Relay(store, _angel_batch(calls), source=Src())
    st = relay.tick(OPEN_DAY)
    assert [len(c) for c in calls] == [50, 50, 21]
    assert calls[0][0] == "S0.NS" and "^NSEI" in calls[2]
    quote_writes = [w for w in store.writes if w[0] == "live_quotes"]
    assert len(quote_writes) == 1
    key, user, compact, doc = quote_writes[0]
    assert user == "_system" and compact is True
    assert doc["source"] == "angel-relay" and doc["ts"].endswith("+00:00")
    assert len(doc["quotes"]) == 121
    q = doc["quotes"]["S1"]
    assert set(q) == {"ltp", "prev_close", "change_pct", "volume", "ts"}
    assert q["ltp"] == 101.0 and q["change_pct"] == 1.0 and q["ts"] == int(OPEN_DAY.timestamp())
    hb = [w for w in store.writes if w[0] == "live_quotes_heartbeat"][-1][3]
    assert hb["n_symbols"] == 121 and hb["last_error"] == "" and "ts" in hb
    assert st["n_fresh"] == 121 and st["bytes"] < 121 * 100


def test_tick_with_no_quotes_keeps_doc_and_reports_error(monkeypatch):
    class Src:
        def symbols(self, now=None):
            return ["A", "B"]

    store = FakeStore()
    relay = pr.Relay(store, lambda t: {x: None for x in t}, source=Src())
    st = relay.tick(OPEN_DAY)
    assert not [w for w in store.writes if w[0] == "live_quotes"]
    hb = store.writes[-1]
    assert hb[0] == "live_quotes_heartbeat" and hb[3]["n_symbols"] == 0 and hb[3]["last_error"]
    assert st["error"]


def test_failed_symbol_keeps_recent_quote_then_drops_it():
    class Src:
        def symbols(self, now=None):
            return ["A", "B"]

    answers = [{"A.NS": {"price": 10, "prev_close": 10}, "B.NS": {"price": 20, "prev_close": 20}},
               {"A.NS": {"price": 11, "prev_close": 10}, "B.NS": None}]
    store = FakeStore()
    relay = pr.Relay(store, lambda t: answers.pop(0), source=Src())
    relay.tick(OPEN_DAY)
    relay.tick(OPEN_DAY + datetime.timedelta(seconds=20))
    doc = store.kv[("_system", "live_quotes")]
    assert doc["quotes"]["A"]["ltp"] == 11
    assert doc["quotes"]["B"]["ts"] == int(OPEN_DAY.timestamp())          # carried, older ts


def test_loop_survives_exceptions_and_sleeps_when_closed():
    sleeps = []
    ticks = []

    class Boom:
        def tick(self, now):
            ticks.append(now)
            raise RuntimeError("angel exploded")

    pr.run_forever(Boom(), sleep=sleeps.append, now_fn=lambda: OPEN_DAY, max_loops=3)
    assert len(ticks) == 3 and len(sleeps) == 3 and sleeps[0] > 0 and sleeps[1] >= sleeps[0]

    sleeps.clear()
    ticks.clear()
    pr.run_forever(Boom(), sleep=sleeps.append, now_fn=lambda: SATURDAY, max_loops=2)
    assert ticks == [] and sleeps == [60, 60]


def test_loop_survives_sleep_and_clock_errors():
    def bad_now():
        raise ValueError("clock")
    pr.run_forever(object(), sleep=lambda s: (_ for _ in ()).throw(OSError("x")), now_fn=bad_now, max_loops=2)


# ── read tier: utils.live_price ─────────────────────────────────────────────

def _doc(age_s=5, now=OPEN_DAY, syms=("RELIANCE", "TCS")):
    ts = int(now.timestamp()) - age_s
    return {"ts": datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).isoformat(),
            "source": "angel-relay",
            "quotes": {s: {"ltp": 1000.0 + i, "prev_close": 1000.0, "change_pct": 0.1 * i,
                           "volume": 5000, "ts": ts} for i, s in enumerate(syms)}}


@pytest.fixture
def relay_kv(monkeypatch):
    box = {"doc": None, "reads": 0, "fail": False}

    def fake_get(key, default=None, user_id="default"):
        box["reads"] += 1
        if box["fail"]:
            raise RuntimeError("neon over quota")
        return box["doc"] if key == "live_quotes" and user_id == "_system" else default

    monkeypatch.setattr(trade_store, "kv_get", fake_get)
    monkeypatch.setattr(lp, "_ist_now", lambda: OPEN_DAY)
    return box


@pytest.fixture
def no_other_tiers(monkeypatch):
    import data.angel_fetcher as af
    monkeypatch.setattr(af, "is_configured", lambda: False)
    for name in ("_yahoo_json_quote", "_nse_live_price", "_stooq_eod_price"):
        monkeypatch.setattr(lp, name, lambda a: {"price": 1.0, "prev_close": 1.0})


def test_fresh_relay_quote_is_used(relay_kv, no_other_tiers):
    relay_kv["doc"] = _doc(age_s=12)
    q = lp.get_live_quote("RELIANCE.NS")
    assert q["price"] == 1000.0 and q["source"] == "angel-relay" and q["volume"] == 5000
    out = lp.get_live_prices_batch(["TCS.NS", "INFY.NS", "X.BO"])
    assert out["TCS.NS"]["price"] == 1001.0 and out["TCS.NS"]["chg_pct"] == pytest.approx(0.1)
    assert out["INFY.NS"]["price"] == 1.0 and "source" not in out["INFY.NS"]      # fell through
    assert out["X.BO"]["price"] == 1.0
    assert lp.relay_source_label(out, now=OPEN_DAY) == "live (Angel via relay, 12 s ago)"


def test_stale_relay_quote_is_ignored(relay_kv, no_other_tiers, monkeypatch):
    relay_kv["doc"] = _doc(age_s=91)
    assert lp.get_live_quote("RELIANCE.NS")["price"] == 1.0
    monkeypatch.setenv("RELAY_MAX_AGE_S", "120")
    assert lp.get_live_quote("RELIANCE.NS")["price"] == 1000.0


def test_relay_ignored_when_market_closed(relay_kv, no_other_tiers, monkeypatch):
    relay_kv["doc"] = _doc(age_s=5, now=SATURDAY)
    monkeypatch.setattr(lp, "_ist_now", lambda: SATURDAY)
    assert lp.get_live_quote("RELIANCE.NS")["price"] == 1.0
    assert relay_kv["reads"] == 0                                  # no DB read outside hours


def test_relay_kv_failure_falls_through_quietly(relay_kv, no_other_tiers):
    relay_kv["fail"] = True
    out = lp.get_live_prices_batch(["RELIANCE.NS", "TCS.NS"])
    assert all(v["price"] == 1.0 for v in out.values())
    lp.get_live_quote("TCS.NS")
    assert relay_kv["reads"] == 1                                  # failure cached too


def test_relay_garbage_doc_falls_through(relay_kv, no_other_tiers):
    relay_kv["doc"] = {"quotes": {"RELIANCE": {"ltp": "nan?"}, "TCS": "x"}}
    assert lp.get_live_quote("RELIANCE.NS")["price"] == 1.0


def test_one_kv_read_for_a_100_symbol_batch(relay_kv, no_other_tiers):
    syms = [f"S{i}" for i in range(100)]
    relay_kv["doc"] = _doc(syms=syms)
    import threading
    out = lp.get_live_prices_batch([f"{s}.NS" for s in syms])
    assert all(v["source"] == "angel-relay" for v in out.values())
    threads = [threading.Thread(target=lp.get_live_quote, args=(f"S{i}.NS",)) for i in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert relay_kv["reads"] == 1


def test_relay_label_none_without_relay_quotes():
    assert lp.relay_source_label({"A": {"price": 1}}) is None
    assert lp.relay_source_label([]) is None


# ── heartbeat warning: alerts/check_alerts.py ───────────────────────────────

@pytest.fixture
def alerts(monkeypatch):
    import alerts.check_alerts as ca
    sent = []
    monkeypatch.setattr(ca, "send_telegram", lambda text: sent.append(text) or True)
    monkeypatch.setattr(ca, "_FORCE_SEND", False)
    return ca, sent


def _hb(store_kv, minutes_ago):
    ts = (OPEN_DAY - datetime.timedelta(minutes=minutes_ago)).astimezone(datetime.timezone.utc)
    trade_store.kv_set("live_quotes_heartbeat", {"ts": ts.isoformat(), "n_symbols": 0,
                                                 "last_error": "rate limit"}, user_id="_system")


def test_heartbeat_never_set_up_is_silent(alerts):
    ca, sent = alerts
    assert ca.check_relay_heartbeat({}, "2026-11-23", now=OPEN_DAY, market_open=True) == 0
    assert sent == []


def test_heartbeat_fresh_is_silent(alerts):
    ca, sent = alerts
    _hb(None, 3)
    assert ca.check_relay_heartbeat({}, "2026-11-23", now=OPEN_DAY, market_open=True) == 0
    assert sent == []


def test_heartbeat_stale_warns_once_a_day(alerts):
    ca, sent = alerts
    _hb(None, 25)
    state: dict = {}
    assert ca.check_relay_heartbeat(state, "2026-11-23", now=OPEN_DAY, market_open=True) == 1
    assert "stopped at 10:35" in sent[0] and "Yahoo" in sent[0] and "rate limit" in sent[0]
    assert ca.check_relay_heartbeat(state, "2026-11-23", now=OPEN_DAY, market_open=True) == 0
    assert len(sent) == 1


def test_heartbeat_stale_silent_when_market_closed(alerts):
    ca, sent = alerts
    _hb(None, 25)
    assert ca.check_relay_heartbeat({}, "2026-11-23", now=OPEN_DAY, market_open=False) == 0
    assert sent == []


def test_heartbeat_from_yesterday_names_the_day(alerts):
    ca, sent = alerts
    _hb(None, 60 * 20)
    assert ca.check_relay_heartbeat({}, "2026-11-23", now=OPEN_DAY, market_open=True) == 1
    assert "on 22 Nov" in sent[0]
