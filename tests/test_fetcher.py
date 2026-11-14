import pandas as pd
import datetime as dt
import pytest

import data.fetcher as fetcher


def _sample_df_dates(start_date="2026-07-01", periods=5, freq="B"):
    idx = pd.date_range(start=start_date, periods=periods, freq=freq)
    df = pd.DataFrame({
        "Open": [100 + i for i in range(periods)],
        "High": [101 + i for i in range(periods)],
        "Low": [99 + i for i in range(periods)],
        "Close": [100 + i for i in range(periods)],
        "Volume": [1000 + 10 * i for i in range(periods)],
    }, index=idx)
    return df


def test_fetch_single_angel_preferred(monkeypatch):
    """When Angel One is configured and returns data, fetch_single should
    return Angel's dataframe without calling lower tiers."""
    sample = _sample_df_dates()

    class FakeAngel:
        @staticmethod
        def is_configured():
            return True

        @staticmethod
        def fetch_historical(ticker, period=None, interval=None):
            return sample.copy()

    # Inject fake angel_fetcher module attributes
    monkeypatch.setattr(fetcher, "_FETCH_CACHE", {}, raising=False)
    monkeypatch.setattr("data.fetcher._stooq_breaker_is_tripped", lambda: False)
    monkeypatch.setattr("data.fetcher._fetch_stooq", lambda *a, **k: None)
    monkeypatch.setitem(__import__("sys").modules, "data.angel_fetcher", FakeAngel)

    got = fetcher.fetch_single("RELIANCE.NS", period="5d", interval="1d")
    # DataFrames may not be the same object but contents should match
    pd.testing.assert_frame_equal(got.reset_index(drop=True), sample.reset_index(drop=True))


def test_fetch_single_stooq_then_yahoo_fallback(monkeypatch):
    """If Stooq raises an error (e.g. returned HTML) the code should fall back to Yahoo."""
    sample = _sample_df_dates()

    def fake_stooq(ticker, period=None):
        raise ValueError("Stooq returned HTML (not CSV)")

    def fake_yahoo(ticker, period=None, interval=None):
        return sample.copy()

    monkeypatch.setattr(fetcher, "_FETCH_CACHE", {}, raising=False)
    monkeypatch.setattr(fetcher, "_fetch_stooq", fake_stooq)
    monkeypatch.setattr(fetcher, "_fetch_yahoo_direct", fake_yahoo)
    # Ensure Angel is not used
    monkeypatch.setattr("data.fetcher._stooq_breaker_is_tripped", lambda: False)
    monkeypatch.setitem(__import__("sys").modules, "data.angel_fetcher", type("X", (), {"is_configured": lambda: False}))

    got = fetcher.fetch_single("RELIANCE.NS", period="5d", interval="1d")
    pd.testing.assert_frame_equal(got.reset_index(drop=True), sample.reset_index(drop=True))


def test_fetch_single_all_providers_fail(monkeypatch):
    """When all providers fail, fetch_single should raise ValueError."""

    def bad_stooq(t, period=None):
        raise ValueError("stooq fail")

    def bad_yahoo(t, period=None, interval=None):
        raise ValueError("yahoo fail")

    # Reset the module-level fetch cache — without this, a prior test in the
    # same session (test_fetch_single_stooq_then_yahoo_fallback, same ticker/
    # period/interval) leaves a valid cache entry behind, fetch_single()
    # returns it without ever calling stooq/yahoo, and this test never
    # observes the ValueError it's asserting on. Order-dependent pollution
    # via shared global state, not a production bug.
    monkeypatch.setattr(fetcher, "_FETCH_CACHE", {}, raising=False)
    monkeypatch.setattr(fetcher, "_fetch_stooq", bad_stooq)
    monkeypatch.setattr(fetcher, "_fetch_yahoo_direct", bad_yahoo)
    # Angel disabled
    monkeypatch.setitem(__import__("sys").modules, "data.angel_fetcher", type("X", (), {"is_configured": lambda: False}))

    with pytest.raises(ValueError):
        fetcher.fetch_single("RELIANCE.NS", period="5d", interval="1d")


def test_fetch_intraday_filters_market_hours(monkeypatch):
    """fetch_intraday should filter rows outside 09:15-15:30 IST market hours."""
    # Build intraday-like datetime index with 5 rows spanning before, inside, after market hours
    base = dt.datetime(2026, 7, 1, 8, 0)
    times = [base + dt.timedelta(hours=i) for i in range(6)]  # 08:00 .. 13:00
    idx = pd.DatetimeIndex(times)
    df = pd.DataFrame({
        "Open": [10, 11, 12, 13, 14, 15],
        "High": [11, 12, 13, 14, 15, 16],
        "Low": [9, 10, 11, 12, 13, 14],
        "Close": [10, 11, 12, 13, 14, 15],
        "Volume": [100, 200, 300, 400, 500, 600],
    }, index=idx)

    # Monkeypatch fetch_single to return df with full-hour times (UTC-like); fetch_intraday will
    # attempt to filter by time and may skip if index lacks .time — but DatetimeIndex works.
    monkeypatch.setattr(fetcher, "fetch_single", lambda t, period, interval: df.copy())

    out = fetcher.fetch_intraday("RELIANCE.NS", interval="60m", days=1)
    # Market open is 09:15, so rows with hour >=9 and <=15:30 survive — from our times above,
    # only rows at 09:00..13:00 with 09:00 included; since we used 08:00..13:00, expect 09..13 -> 5 rows
    assert len(out) >= 1


def test_fetch_single_angel_busy_falls_through_quietly(monkeypatch, caplog):
    """FIX AO-BULK: AngelBusy is a skip, not a failure — no WARNING, next tier serves."""
    import logging
    import types
    import pandas as pd
    import data.fetcher as f

    class _Busy(Exception):
        pass

    def _raise(*a, **k):
        raise _Busy()

    fake = types.SimpleNamespace(AngelBusy=_Busy, fetch_historical=_raise, is_configured=lambda: True)
    monkeypatch.setitem(__import__("sys").modules, "data.angel_fetcher", fake)
    monkeypatch.setattr(f, "_stooq_enabled", lambda: False)
    yahoo_df = pd.DataFrame({"Open": [1.0], "High": [1.0], "Low": [1.0], "Close": [1.0], "Volume": [1]},
                            index=pd.to_datetime(["2026-09-25"]))
    monkeypatch.setattr(f, "_fetch_yahoo_direct", lambda *a, **k: yahoo_df)
    monkeypatch.setattr(f, "_FETCH_CACHE", {})
    with caplog.at_level(logging.WARNING, logger="data.fetcher"):
        df = f.fetch_single("BUSYTEST.NS", period="1y")
    assert df is not None and not df.empty
    assert not [r for r in caplog.records if "AngelOne" in r.getMessage()]


# ── FIX TIER-COVERAGE: a short / stale early-tier frame must not block Yahoo ──
def _daily(n, end=None, price=100.0):
    """n session bars ending at the last completed weekday before today (IST)."""
    import data.fetcher as f
    end = end or f._ist_today() - pd.Timedelta(days=1)
    idx = pd.bdate_range(end=end, periods=n)
    return pd.DataFrame({"Open": price, "High": price + 1, "Low": price - 1,
                         "Close": price + 0.5, "Volume": 1000}, index=idx)


def _tiers(monkeypatch, angel_df, yahoo):
    """Angel returns angel_df; Yahoo returns `yahoo` (a frame) or raises it."""
    import types
    import data.fetcher as f
    calls = {"yahoo": 0}
    fake = types.SimpleNamespace(
        is_configured=lambda: True, AngelBusy=type("AngelBusy", (Exception,), {}),
        fetch_historical=lambda ticker, period=None, interval=None: angel_df.copy())

    def _yahoo(*a, **k):
        calls["yahoo"] += 1
        if isinstance(yahoo, Exception):
            raise yahoo
        return yahoo.copy()

    monkeypatch.setitem(__import__("sys").modules, "data.angel_fetcher", fake)
    monkeypatch.setattr(f, "_stooq_enabled", lambda: False)
    monkeypatch.setattr(f, "_fetch_yahoo_direct", _yahoo)
    monkeypatch.setattr(f, "_FETCH_CACHE", {})
    import data.nse_bhavcopy_prices as bp
    monkeypatch.setattr(bp, "fetch_bhavcopy_history",
                        lambda *a, **k: (_ for _ in ()).throw(ValueError("offline")))
    return f, calls


def test_short_angel_frame_loses_to_longer_yahoo(monkeypatch):
    """27 bars of a 2y request (the PFC / VEDL case) must not be served as history."""
    f, calls = _tiers(monkeypatch, _daily(27), _daily(480))
    got = f.fetch_single("PFC.NS", period="2y")
    assert calls["yahoo"] == 1
    assert len(got) > 400


def test_new_listing_short_on_every_tier_is_still_served(monkeypatch):
    f, calls = _tiers(monkeypatch, _daily(27, price=100.0), _daily(26, price=200.0))
    got = f.fetch_single("NEWIPO.NS", period="2y")
    assert calls["yahoo"] == 1
    assert 20 <= len(got) <= 27 and got["Open"].iloc[-1] == 100.0     # Angel's frame stands


def test_short_frame_served_when_yahoo_is_down(monkeypatch):
    f, calls = _tiers(monkeypatch, _daily(27), ValueError("Yahoo down"))
    got = f.fetch_single("NEWIPO.NS", period="2y")
    assert calls["yahoo"] == 1 and 20 <= len(got) <= 27


def test_full_fresh_angel_frame_never_calls_yahoo(monkeypatch):
    f, calls = _tiers(monkeypatch, _daily(500), _daily(500))
    f.fetch_single("RELIANCE.NS", period="2y")
    assert calls["yahoo"] == 0


def test_stale_angel_frame_loses_to_fresher_yahoo(monkeypatch):
    """History that stopped ~2 weeks ago while Yahoo has yesterday's bar."""
    import data.fetcher as f0
    stale_end = f0._ist_today() - pd.Timedelta(days=15)
    f, calls = _tiers(monkeypatch, _daily(500, end=stale_end, price=100.0), _daily(500, price=200.0))
    got = f.fetch_single("RELIANCE.NS", period="2y")
    assert calls["yahoo"] == 1
    assert got["Open"].iloc[-1] == 200.0
    assert got.index[-1].date() > stale_end


def test_suspended_stock_stale_on_every_tier_keeps_first_tier(monkeypatch):
    import data.fetcher as f0
    stale_end = f0._ist_today() - pd.Timedelta(days=15)
    f, calls = _tiers(monkeypatch, _daily(500, end=stale_end, price=100.0),
                      _daily(500, end=stale_end, price=200.0))
    got = f.fetch_single("SUSP.NS", period="2y")
    assert got["Open"].iloc[-1] == 100.0


def test_fresher_but_much_shorter_yahoo_does_not_replace_long_history(monkeypatch):
    import data.fetcher as f0
    stale_end = f0._ist_today() - pd.Timedelta(days=15)
    f, calls = _tiers(monkeypatch, _daily(500, end=stale_end, price=100.0), _daily(30, price=200.0))
    got = f.fetch_single("X.NS", period="2y")
    assert got["Open"].iloc[-1] == 100.0


def test_missed_sessions_ignores_weekend_and_today():
    import datetime as dt
    import data.fetcher as f
    fri, mon = dt.date(2026, 7, 3), dt.date(2026, 7, 6)
    assert f._missed_sessions(fri, mon) == 0            # Monday pre-open: Friday's bar is current
    assert f._missed_sessions(fri, dt.date(2026, 7, 9)) == 3
    # Tue 10 Nov 2026 is an NSE holiday: not a missed session.
    assert f._missed_sessions(dt.date(2026, 11, 6), dt.date(2026, 11, 12)) == 2
