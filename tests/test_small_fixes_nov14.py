"""Offline tests for the 14 Nov small fixes: page wording, score bars, Yahoo
quote age, IST dates in the fetchers, Angel One exact-symbol tokens."""
import datetime as dt
import io
import json
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))


# ── 2. My Portfolio wording ──────────────────────────────────────────────────
def test_my_portfolio_has_no_descriptive_trend_labels():
    src = (ROOT / "dashboard" / "pages" / "05_my_portfolio.py").read_text(encoding="utf-8")
    for old in ("Weakening", "Broken Trend", "Strong Trend", "Uptrend"):
        assert old not in src, old
    from analysis.action_labels import action_display_label as lab
    assert [lab(a) for a in ("STRONG BUY", "BUY", "HOLD", "CAUTION", "EXIT")] == \
        ["STRONG BUY", "BUY", "HOLD", "REDUCE", "SELL"]
    assert "_display_label('CAUTION')" in src and "_display_label('EXIT')" in src


# ── 3. No Pattern score bar ──────────────────────────────────────────────────
def test_pick_score_bars_match_the_composite_components():
    from dashboard.shared import picks_ui
    assert picks_ui.SCORE_BARS == (("Technical", 40), ("Momentum", 25), ("Volume", 15), ("Sentiment", 10))
    assert sum(cap for _, cap in picks_ui.SCORE_BARS) == 90
    assert '"Pattern"' not in (ROOT / "dashboard" / "shared" / "picks_ui.py").read_text(encoding="utf-8")


# ── 4. Yahoo quote age ───────────────────────────────────────────────────────
def _epoch(y, m, d, hh=15, mm=29):
    return dt.datetime(y, m, d, hh, mm, tzinfo=IST).timestamp()


def test_quote_time_fields_flags_a_quote_older_than_the_last_session():
    import utils.live_price as lp
    now = dt.datetime(2026, 11, 13, 11, 0, tzinfo=IST)          # Friday, market open
    # last completed session at that moment is Thursday 12 Nov
    fresh = lp._quote_time_fields(_epoch(2026, 11, 13, 10, 59), now=now)
    assert fresh == {"as_of": "2026-11-13T10:59:00+05:30"}
    assert "eod" not in lp._quote_time_fields(_epoch(2026, 11, 12), now=now)     # last close: not flagged
    stale = lp._quote_time_fields(_epoch(2026, 11, 9), now=now)                  # suspended since Monday
    assert stale == {"as_of": "2026-11-09T15:29:00+05:30", "eod": True}
    for bad in (None, "x", float("nan"), 1e30):
        assert lp._quote_time_fields(bad, now=now) == {}                         # never raises


def test_yahoo_quote_returns_as_of_and_eod(monkeypatch):
    import data.fetcher as F
    import utils.live_price as lp

    def serve(market_time):
        meta = {"regularMarketPrice": 101.5, "previousClose": 100.0}
        if market_time is not None:
            meta["regularMarketTime"] = market_time
        body = json.dumps({"chart": {"result": [{"meta": meta}]}}).encode()

        class Opener:
            def open(self, req, timeout=None):
                return io.BytesIO(body)
        monkeypatch.setattr(F, "_get_yf_crumb", lambda: (Opener(), ""))
        return lp._yahoo_json_quote("X.NS")

    old = serve(_epoch(2020, 1, 6))
    assert old["price"] == 101.5 and old["eod"] is True and old["as_of"].startswith("2020-01-06T15:29")
    assert lp._normalise(old)["eod"] is True and lp._normalise(old)["as_of"] == old["as_of"]
    assert not lp.quote_is_live(lp._normalise(old))
    now_q = serve(dt.datetime.now(IST).timestamp())
    assert "eod" not in now_q and lp.quote_is_live(lp._normalise(now_q))
    missing = serve(None)                                        # no quote time: unchanged behaviour
    assert missing["price"] == 101.5 and "as_of" not in missing and "eod" not in missing
    assert serve("garbage")["price"] == 101.5
    assert lp.quote_is_live({"price": 1.0}) and not lp.quote_is_live(None)


# ── 5. IST dates ─────────────────────────────────────────────────────────────
@pytest.fixture
def ist_is_tomorrow(monkeypatch):
    """01:00 IST on 14 Nov is still 13 Nov in UTC (what date.today() gives on a runner)."""
    import utils.snapshot_time as st
    monkeypatch.setattr(st, "ist_now", lambda: dt.datetime(2026, 11, 14, 1, 0, tzinfo=IST))
    return dt.date(2026, 11, 14)


def test_fetcher_period_end_is_the_ist_date(ist_is_tomorrow):
    import data.fetcher as F
    assert F._ist_today() == ist_is_tomorrow
    _start, end = F._period_to_dates("1mo")
    assert str(end).replace("-", "")[:8] == "20261114"


def test_angel_period_end_is_the_ist_date(ist_is_tomorrow):
    import data.angel_fetcher as af
    assert af._ist_today() == ist_is_tomorrow
    _start, end = af._period_to_dates("1mo")
    assert end.startswith("2026-11-14")
    assert af._period_to_dates("ytd")[0].startswith("2026-01-01")


def test_events_use_the_ist_clock(ist_is_tomorrow):
    import data.events as ev
    assert ev._now_ist() == dt.datetime(2026, 11, 14, 1, 0) and ev._now_ist().tzinfo is None
    src = (ROOT / "data" / "events.py").read_text(encoding="utf-8")
    assert "datetime.now()" not in src and "date.today()" not in src


# ── 6. Angel One token: exact symbol only ────────────────────────────────────
class _Resp:
    status_code = 200

    def __init__(self, data):
        self._d = {"status": True, "data": data}
        self.text = json.dumps(self._d)
        self.content = self.text.encode()

    def json(self):
        return self._d


@pytest.fixture
def angel(monkeypatch):
    import data.angel_fetcher as af
    af._TOKEN_CACHE.clear()
    af._NO_EXACT_LOGGED.clear()
    monkeypatch.setattr(af, "_INST_MAP", {"DUMMY": "1"})        # non-empty: skip the master download
    monkeypatch.setattr(af, "_angel_rate_limit", lambda: None)
    monkeypatch.setattr(af, "_breaker_tripped", lambda: False)
    calls = []

    def use(scrips):
        class S:
            def post(self, url, json=None, headers=None, timeout=None):
                calls.append(json)
                return _Resp(scrips)
        monkeypatch.setattr(af, "_http", S())
    yield af, use, calls
    af._TOKEN_CACHE.clear()
    af._NO_EXACT_LOGGED.clear()


def test_get_token_rejects_a_different_instrument(angel, caplog):
    af, use, calls = angel
    use([{"tradingsymbol": "TATAMTRDVR-EQ", "symboltoken": "16965"},
         {"tradingsymbol": "TATAMOTORS-BL", "symboltoken": "999"}])
    sess = {"jwt": "J", "api_key": "K"}
    with caplog.at_level("WARNING", logger=af._log.name):
        assert af._get_token("TATAMOTORS", sess) is None
        af._TOKEN_CACHE.clear()                                  # force a second lookup
        assert af._get_token("TATAMOTORS", sess) is None
    assert len(calls) == 2
    assert sum("no exact symbol match" in r.getMessage() for r in caplog.records) == 1    # logged once


def test_get_token_accepts_exact_symbol_with_series_suffix(angel):
    af, use, _ = angel
    use([{"tradingsymbol": "RELIANCEX-EQ", "symboltoken": "1"},
         {"tradingsymbol": "RELIANCE-EQ", "symboltoken": "2885"}])
    assert af._get_token("RELIANCE", {"jwt": "J", "api_key": "K"}) == "2885"
    af._TOKEN_CACHE.clear()
    use([{"tradingsymbol": "INFY", "symboltoken": "1594", "instrumenttype": "EQ"}])
    assert af._get_token("INFY", {"jwt": "J", "api_key": "K"}) == "1594"
