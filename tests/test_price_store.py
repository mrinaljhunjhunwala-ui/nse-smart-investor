"""Price store (data/price_store.py), its nightly fill (scripts/warm_price_store.py)
and fetch_single's Tier 0.5. All offline: SQLite via conftest, Angel/Yahoo mocked."""
from __future__ import annotations

import datetime
import importlib.util
import os
import sys

import pandas as pd
import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from data import fetcher  # noqa: E402
from data import price_store as ps  # noqa: E402
from utils.nse_holidays import is_trading_day  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "warm_price_store", os.path.join(_ROOT, "scripts", "warm_price_store.py"))
wps = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(wps)


@pytest.fixture(autouse=True)
def _fresh_store(monkeypatch):
    monkeypatch.setattr(ps, "_ready_for", None)
    ps._has_rows_cache.clear()
    fetcher.clear_fetch_cache()
    yield
    ps._has_rows_cache.clear()
    fetcher.clear_fetch_cache()


def _sessions_ending(end: datetime.date, n: int) -> list:
    out, d = [], end
    while len(out) < n:
        if is_trading_day(d):
            out.append(d)
        d -= datetime.timedelta(days=1)
    return sorted(out)


def _frame(dates, start=100.0, step=0.1) -> pd.DataFrame:
    closes = [start + i * step for i in range(len(dates))]
    idx = pd.DatetimeIndex([pd.Timestamp(d) for d in dates], name="Date")
    return pd.DataFrame({"Open": closes, "High": [c + 1 for c in closes],
                         "Low": [c - 1 for c in closes], "Close": closes,
                         "Volume": [1000 + i for i in range(len(dates))]}, index=idx)


def _last_session() -> datetime.date:
    return ps.last_completed_session()


# ── Store round trip ─────────────────────────────────────────────────────────

def test_upsert_load_round_trip_and_status():
    dates = _sessions_ending(_last_session(), 30)
    df = _frame(dates)
    assert ps.upsert_daily_bars("ABC.NS", df, "AngelOne") == 30
    # Re-upsert is an update, not new rows.
    assert ps.upsert_daily_bars("ABC.NS", df, "AngelOne") == 0
    got = ps.load_daily_bars("ABC.NS")
    assert list(got.columns) == ["Open", "High", "Low", "Close", "Volume"]
    assert len(got) == 30
    assert got["Close"].iloc[-1] == pytest.approx(df["Close"].iloc[-1])
    assert got.index[0] == pd.Timestamp(dates[0])
    ps.upsert_daily_bars("XYZ.NS", df.iloc[-5:], "AngelOne")
    st = ps.price_store_status()
    assert st == {"symbols": 2, "latest_date": dates[-1].isoformat(),
                  "oldest_date": dates[0].isoformat(), "rows": 35}


def test_status_and_load_degrade_when_table_missing():
    assert ps.price_store_status() == {"symbols": 0, "latest_date": None,
                                       "oldest_date": None, "rows": 0}
    assert ps.load_daily_bars("ABC.NS", "1y").empty


def test_load_period_filters_start():
    dates = _sessions_ending(_last_session(), 400)
    ps.upsert_daily_bars("ABC.NS", _frame(dates), "AngelOne")
    got = ps.load_daily_bars("ABC.NS", "6mo")
    assert got.index[0].date() >= ps.period_start("6mo")
    assert len(got) < 400


# ── Incremental window ───────────────────────────────────────────────────────

def test_fetch_window_backfill_incremental_and_noop():
    target = datetime.date(2026, 11, 10)
    assert wps.fetch_window(None, target, 2000) == (target - datetime.timedelta(days=2000), target)
    assert wps.fetch_window(datetime.date(2026, 11, 6), target, 2000) == (
        datetime.date(2026, 11, 7), target)
    assert wps.fetch_window(target, target, 2000) is None


def test_last_completed_session_respects_close_and_holidays():
    ist = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
    # Wed 11 Nov 2026 before the close -> Mon 9 Nov (Tue 10 Nov is a holiday);
    # after the close -> Wed.
    assert ps.last_completed_session(datetime.datetime(2026, 11, 11, 11, 0, tzinfo=ist)) == \
        datetime.date(2026, 11, 9)
    assert ps.last_completed_session(datetime.datetime(2026, 11, 11, 18, 30, tzinfo=ist)) == \
        datetime.date(2026, 11, 11)
    # One session behind is fresh, two is not.
    wed_eve = datetime.datetime(2026, 11, 11, 18, 30, tzinfo=ist)
    assert ps.is_fresh(datetime.date(2026, 11, 9), wed_eve) is True
    assert ps.is_fresh(datetime.date(2026, 11, 6), wed_eve) is False
    # Sunday -> Friday.
    assert ps.last_completed_session(datetime.datetime(2026, 11, 8, 12, 0)) == datetime.date(2026, 11, 6)


# ── Nightly job ──────────────────────────────────────────────────────────────

class _FakeClock:
    def __init__(self):
        self.t = 1000.0
        self.sleeps: list = []

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.sleeps.append(s)
        self.t += s


def test_throttle_spaces_calls_at_rps():
    clk = _FakeClock()
    th = wps.Throttle(2.0, clock=clk, sleep=clk.sleep)
    stamps = []
    for _ in range(5):
        th.wait()
        stamps.append(clk.t)
    gaps = [b - a for a, b in zip(stamps, stamps[1:])]
    assert all(g >= 0.5 - 1e-9 for g in gaps)
    assert stamps[-1] - stamps[0] == pytest.approx(2.0)


def test_run_backfills_then_second_run_is_noop(monkeypatch):
    monkeypatch.setenv("ANGEL_BULK_RPS", "2")
    target = _last_session()
    dates = _sessions_ending(target, 50)
    calls = []

    def fake_fetch(sym, d1, d2):
        calls.append((sym, d1, d2))
        return _frame([d for d in dates if d1 <= d <= d2]), "ok"

    clk = _FakeClock()
    r1 = wps.run(["AAA.NS", "BBB.NS"], fetch=fake_fetch, clock=clk, sleep=clk.sleep)
    assert (r1["ok"], r1["skipped"], r1["new_rows"]) == (2, 0, 100)
    assert calls[0][1] == target - datetime.timedelta(days=2000)
    assert r1["line"].startswith("price_store: 2 ok, 0 skipped, 100 new rows, took ")
    # Throttle: second call waited for its 0.5 s slot.
    assert clk.sleeps and clk.sleeps[0] == pytest.approx(0.5)

    r2 = wps.run(["AAA.NS", "BBB.NS"], fetch=fake_fetch, clock=clk, sleep=clk.sleep)
    assert len(calls) == 2            # no new requests
    assert (r2["ok"], r2["skipped"], r2["new_rows"]) == (2, 0, 0)


def test_run_incremental_requests_from_last_date_plus_one():
    target = _last_session()
    dates = _sessions_ending(target, 20)
    ps.upsert_daily_bars("AAA.NS", _frame(dates[:-3]), "AngelOne")
    calls = []

    def fake_fetch(sym, d1, d2):
        calls.append((d1, d2))
        return _frame(dates[-3:], start=101.7), "ok"

    clk = _FakeClock()
    r = wps.run(["AAA.NS"], fetch=fake_fetch, clock=clk, sleep=clk.sleep)
    assert calls == [(dates[-4] + datetime.timedelta(days=1), target)]
    assert r["new_rows"] == 3


def test_rate_limit_sleeps_retries_once_then_skips():
    seq = {"AAA.NS": ["rate_limited", "rate_limited"], "BBB.NS": ["ok"]}
    dates = _sessions_ending(_last_session(), 10)

    def fake_fetch(sym, d1, d2):
        st = seq[sym].pop(0)
        return (_frame(dates), "ok") if st == "ok" else (None, st)

    clk = _FakeClock()
    r = wps.run(["AAA.NS", "BBB.NS"], fetch=fake_fetch, clock=clk, sleep=clk.sleep)
    assert (r["ok"], r["skipped"]) == (1, 1)
    assert wps.RATE_LIMIT_SLEEP_S in clk.sleeps
    assert seq["AAA.NS"] == []        # exactly one retry


def test_rate_limit_streak_stops_run_and_never_raises():
    def fake_fetch(sym, d1, d2):
        return None, "rate_limited"

    clk = _FakeClock()
    syms = [f"S{i}.NS" for i in range(10)]
    r = wps.run(syms, fetch=fake_fetch, clock=clk, sleep=clk.sleep)
    assert r["skipped"] == 10 and r["ok"] == 0
    assert clk.sleeps.count(wps.RATE_LIMIT_SLEEP_S) == wps.MAX_CONSECUTIVE_RATE_LIMITED


def test_fetch_exception_and_errors_are_skips():
    def fake_fetch(sym, d1, d2):
        if sym == "BAD.NS":
            raise RuntimeError("boom")
        return None, "no_token"

    clk = _FakeClock()
    r = wps.run(["BAD.NS", "NOTOK.NS"], fetch=fake_fetch, clock=clk, sleep=clk.sleep)
    assert (r["ok"], r["skipped"], r["new_rows"]) == (0, 2, 0)


def test_hist_api_key_only_when_switched_on(monkeypatch):
    from data import angel_fetcher as af
    monkeypatch.setenv("ANGEL_API_KEY", "main")
    monkeypatch.setenv("ANGEL_HIST_API_KEY", "hist")
    monkeypatch.setattr(af, "_secrets_section", lambda: {})
    monkeypatch.setattr(af, "_USE_HIST_KEY", [False])
    assert af._get_credentials()["api_key"] == "main"
    af.use_hist_api_key(True)
    assert af._get_credentials()["api_key"] == "hist"


def test_fetch_daily_candles_detects_rate_limit(monkeypatch):
    from data import angel_fetcher as af

    class _Resp:
        status_code = 403
        text = "Access denied because of exceeding access rate"

        def json(self):
            raise ValueError("not json")

    monkeypatch.setattr(af, "_get_session", lambda: {"jwt": "j", "api_key": "k"})
    monkeypatch.setattr(af, "_get_token", lambda s, sess: "123")
    monkeypatch.setattr(af._http, "post", lambda *a, **k: _Resp())
    df, status = af.fetch_daily_candles("ABC.NS", datetime.date(2026, 1, 1), datetime.date(2026, 2, 1))
    assert df is None and status == "rate_limited"


# ── Fetcher Tier 0.5 ─────────────────────────────────────────────────────────

def _yahoo_frame(dates, start=100.0):
    return _frame(dates, start=start)


def _no_angel(monkeypatch):
    from data import angel_fetcher as af
    monkeypatch.setattr(af, "is_configured", lambda: False)


def test_fetcher_serves_fresh_store(monkeypatch):
    monkeypatch.setenv("NSE_PRICE_STORE", "1")
    _no_angel(monkeypatch)
    dates = _sessions_ending(_last_session(), 300)
    ps.upsert_daily_bars("ABC.NS", _frame(dates), "AngelOne")

    def _boom(*a, **k):
        raise AssertionError("Yahoo must not be called when the store is fresh")

    monkeypatch.setattr(fetcher, "_fetch_yahoo_direct", _boom)
    df = fetcher.fetch_single("ABC.NS", period="1y", interval="1d")
    assert not df.empty
    assert df.index[-1].date() == dates[-1]
    assert df.index[0].date() >= ps.period_start("1y")
    assert fetcher.get_last_diagnostic("PriceStore")["ok"] is True


@pytest.mark.parametrize("case", ["stale", "short"])
def test_fetcher_falls_through_when_stale_or_short(monkeypatch, case):
    monkeypatch.setenv("NSE_PRICE_STORE", "1")
    _no_angel(monkeypatch)
    last = _last_session()
    if case == "stale":
        dates = _sessions_ending(last - datetime.timedelta(days=10), 300)
    else:
        dates = _sessions_ending(last, 40)          # 1y requested, ~2 months stored
    ps.upsert_daily_bars("ABC.NS", _frame(dates), "AngelOne")
    ydates = _sessions_ending(last, 250)
    hits = []

    def _yahoo(t, period="1y", interval="1d"):
        hits.append(t)
        return _yahoo_frame(ydates)

    monkeypatch.setattr(fetcher, "_fetch_yahoo_direct", _yahoo)
    df = fetcher.fetch_single("ABC.NS", period="1y", interval="1d")
    assert hits == ["ABC.NS"]
    assert df.index[-1].date() == ydates[-1]
    assert fetcher.get_last_diagnostic("PriceStore")["ok"] is False


def test_fetcher_tier_disabled_by_env(monkeypatch):
    monkeypatch.setenv("NSE_PRICE_STORE", "0")
    _no_angel(monkeypatch)
    dates = _sessions_ending(_last_session(), 300)
    ps.upsert_daily_bars("ABC.NS", _frame(dates), "AngelOne")
    hits = []

    def _yahoo(t, period="1y", interval="1d"):
        hits.append(t)
        return _yahoo_frame(dates)

    monkeypatch.setattr(fetcher, "_fetch_yahoo_direct", _yahoo)
    fetcher.fetch_single("ABC.NS", period="1y", interval="1d")
    assert hits == ["ABC.NS"]
    assert ps.serve("ABC.NS", "1y") is None


# ── Split guards ─────────────────────────────────────────────────────────────

def test_split_check_drops_symbol_on_mismatch():
    dates = _sessions_ending(_last_session(), 60)
    ps.upsert_daily_bars("ABC.NS", _frame(dates, start=1000.0), "AngelOne")   # unadjusted
    yahoo = _frame(dates, start=500.0)                                         # 1:2 split-adjusted
    assert ps.price_store_split_check("ABC.NS", yahoo) is True
    assert ps.load_daily_bars("ABC.NS").empty


def test_split_check_keeps_matching_symbol():
    dates = _sessions_ending(_last_session(), 60)
    ps.upsert_daily_bars("ABC.NS", _frame(dates), "AngelOne")
    assert ps.price_store_split_check("ABC.NS", _frame(dates, start=100.5)) is False
    assert len(ps.load_daily_bars("ABC.NS")) == 60


def test_fetcher_runs_split_check_on_yahoo_fallthrough(monkeypatch):
    monkeypatch.setenv("NSE_PRICE_STORE", "1")
    _no_angel(monkeypatch)
    last = _last_session()
    dates = _sessions_ending(last - datetime.timedelta(days=10), 60)          # stale -> Yahoo
    ps.upsert_daily_bars("ABC.NS", _frame(dates, start=1000.0), "AngelOne")
    monkeypatch.setattr(fetcher, "_fetch_yahoo_direct",
                        lambda t, period="1y", interval="1d": _frame(_sessions_ending(last, 80), start=500.0))
    fetcher.fetch_single("ABC.NS", period="6mo", interval="1d")
    assert ps.load_daily_bars("ABC.NS").empty


def test_trim_discontinuity_keeps_post_split_basis():
    dates = _sessions_ending(_last_session(), 40)
    df = _frame(dates, start=1000.0, step=0.0)
    df.iloc[25:, :4] = df.iloc[25:, :4] / 2                                   # 1:2 split on day 25
    ps.upsert_daily_bars("ABC.NS", df, "AngelOne")
    assert ps.trim_discontinuity("ABC.NS") == 25
    left = ps.load_daily_bars("ABC.NS")
    assert len(left) == 15 and left.index[0].date() == dates[25]
    # Indices are exempt (VIX moves >30% for real).
    vix = _frame(dates, start=12.0, step=0.0)
    vix.iloc[30:, :4] = 18.0
    ps.upsert_daily_bars("^INDIAVIX", vix, "AngelOne")
    assert ps.trim_discontinuity("^INDIAVIX") == 0


def test_caption_text():
    from dashboard.shared.cache import price_source_caption
    assert price_source_caption({}) == "Prices: Yahoo (store empty)"
    assert price_source_caption({"rows": 10, "symbols": 2, "latest_date": "2026-11-09"}) == \
        "Prices: store (as of 2026-11-09, 2 names) · Yahoo fallback"


@pytest.mark.real_postgres
def test_postgres_ddl_upsert_and_status_round_trip():
    """Runs only in CI's real-postgres job (TEST_DATABASE_URL)."""
    dates = _sessions_ending(_last_session(), 30)
    df = _frame(dates)
    assert ps.upsert_daily_bars("PGT.NS", df, "AngelOne") == 30
    assert ps.upsert_daily_bars("PGT.NS", df, "AngelOne") == 0
    got = ps.load_daily_bars("PGT.NS", "1y")
    assert len(got) == 30 and got.index[-1].date() == dates[-1]
    assert ps.price_store_status()["rows"] >= 30
    assert ps.all_latest_dates()["PGT.NS"] == dates[-1]
    assert ps.delete_symbol("PGT.NS") == 30
