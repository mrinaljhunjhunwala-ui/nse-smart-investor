"""FIX SCAN-CADENCE: the Top Picks warmer runs every 45 min (cron-job.org) but
readers dropped its snapshot after 20 min, so for half of every market hour and
all evening the app threw a current scan away (live re-scan or "n/a")."""
import datetime as dt

from utils.snapshot_time import scan_snapshot_current

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))


def _t(*a):
    return dt.datetime(*a, tzinfo=IST)


def test_snapshot_survives_the_45_minute_gap_between_warm_runs():
    gen = _t(2026, 11, 16, 10, 0).isoformat()                       # Monday
    assert scan_snapshot_current(gen, now=_t(2026, 11, 16, 10, 40))  # was: dropped after 10:20
    assert not scan_snapshot_current(gen, now=_t(2026, 11, 16, 11, 5))  # a missed run shows


def test_last_scan_of_the_day_serves_the_evening_and_weekend():
    gen = _t(2026, 11, 13, 15, 20).isoformat()                       # Friday's last run
    assert scan_snapshot_current(gen, now=_t(2026, 11, 13, 21, 0))
    assert scan_snapshot_current(gen, now=_t(2026, 11, 15, 11, 0))   # Sunday
    assert scan_snapshot_current(gen, now=_t(2026, 11, 16, 8, 30))   # Monday pre-open
    assert not scan_snapshot_current(gen, now=_t(2026, 11, 16, 9, 40))  # Monday's session has opened


def test_scan_from_before_todays_open_is_not_tonights_scan():
    gen = _t(2026, 11, 16, 8, 45).isoformat()                        # pre-open warm, then all runs failed
    assert not scan_snapshot_current(gen, now=_t(2026, 11, 16, 20, 0))
    noon = _t(2026, 11, 16, 12, 0).isoformat()                       # midday run, later runs failed
    assert scan_snapshot_current(noon, now=_t(2026, 11, 16, 20, 0))  # still the latest prices seen today


def test_bad_stamps_are_not_current():
    assert not scan_snapshot_current(None)
    assert not scan_snapshot_current("garbage")


def test_reader_serves_the_afternoon_scan_in_the_evening(monkeypatch):
    import dashboard.shared.cache as cache_mod
    import utils.snapshot_time as snap_mod

    gen = _t(2026, 11, 16, 15, 20).isoformat()
    real = snap_mod.scan_snapshot_current
    monkeypatch.setattr(cache_mod, "_scan_snapshot_current",
                        lambda g: real(g, now=_t(2026, 11, 16, 21, 0)))
    snap = {"generated_at": gen, "data": {"buys": [{"ticker": "TCS.NS"}],
                                          "TCS.NS": {"score": 70}}}
    monkeypatch.setattr(cache_mod._store, "kv_get", lambda key, user_id=None: snap)
    tp = cache_mod._persisted_top_picks_snapshot()
    assert tp is not None and tp["buys"] == [{"ticker": "TCS.NS"}] and not tp.get("stale")
    assert cache_mod._persisted_all_scores_snapshot()["TCS.NS"]["score"] == 70


def test_data_health_uses_the_reader_rule(monkeypatch):
    from dashboard.shared import data_health as dh
    import trade_store

    stamp = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=40)).isoformat()
    monkeypatch.setattr(trade_store, "kv_get", lambda key, user_id=None: {"generated_at": stamp})
    assert dh.probe_warmer_top_picks().status == dh.STATUS_HEALTHY   # was "stale" past 30 min


def test_scan_times_are_shown_in_ist():
    from utils.snapshot_time import ist_label
    assert ist_label("2026-11-17T04:50:12+00:00") == "Tue 17 Nov 10:20 IST"    # was shown as "04:50"
    assert ist_label("2026-11-17T04:50:12") == "Tue 17 Nov 10:20 IST"          # legacy naive = UTC
    assert ist_label(None) == "" and ist_label("x") == ""
