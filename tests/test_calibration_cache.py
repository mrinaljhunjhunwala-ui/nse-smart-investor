"""Calibration page cost (audit 2026-11-25 F4): cached ledger read + throttled backfill."""
import pandas as pd

import dashboard.shared.cache as cache
from analysis import verdict_ledger as vl


def test_backfill_runs_at_most_once_per_gap(monkeypatch):
    calls = []
    monkeypatch.setattr(vl, "backfill_returns", lambda max_rows=200: calls.append(1) or {"updated": 0})
    monkeypatch.setattr(vl, "backfill_sector_returns", lambda: None)
    monkeypatch.setitem(cache._ledger_backfill_last, "at", 0.0)
    assert cache.ledger_backfill_throttled()["skipped"] is False
    assert cache.ledger_backfill_throttled()["skipped"] is True              # slider rerun: no network
    assert cache.ledger_backfill_throttled(force=True)["skipped"] is False   # the button
    assert len(calls) == 2


def test_full_ledger_read_is_cached_until_the_stamp_changes(monkeypatch):
    reads, stamp = [], ["s1"]
    monkeypatch.setattr(vl, "load_ledger", lambda **k: reads.append(1) or pd.DataFrame({"id": [1]}))
    monkeypatch.setattr(vl, "ledger_stamp", lambda: stamp[0])
    cache.load_full_ledger_cached.clear()
    cache.load_full_ledger_cached()
    cache.load_full_ledger_cached()
    assert len(reads) == 1
    stamp[0] = "s2"                                                          # a new row was logged
    cache.load_full_ledger_cached()
    assert len(reads) == 2
    cache.load_full_ledger_cached.clear()


def test_failed_read_is_not_cached(monkeypatch):
    monkeypatch.setattr(vl, "ledger_stamp", lambda: "x")
    cache.load_full_ledger_cached.clear()

    def boom(**k):
        raise vl.LedgerUnavailable(RuntimeError("down"))
    monkeypatch.setattr(vl, "load_ledger", boom)
    assert vl.ledger_error(cache.load_full_ledger_cached()) == "RuntimeError"
    monkeypatch.setattr(vl, "load_ledger", lambda **k: pd.DataFrame({"id": [1]}))
    assert len(cache.load_full_ledger_cached()) == 1
    cache.load_full_ledger_cached.clear()
