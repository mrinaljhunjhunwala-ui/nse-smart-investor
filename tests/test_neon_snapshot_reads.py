"""Scan snapshots are read from Postgres at most once per 2 minutes per process
(Neon bills transfer; Command Centre reruns every 20 s)."""
from dashboard.shared import cache


def test_snapshot_read_is_shared(monkeypatch):
    calls = []
    monkeypatch.setattr(cache._store, "kv_get", lambda k, user_id="default": calls.append(k) or {"x": 1})
    for _ in range(5):
        assert cache._kv_snapshot("top_picks_snapshot", "_system") == {"x": 1}
    assert calls == ["top_picks_snapshot"]
    t = [1000.0]
    import time
    monkeypatch.setattr(time, "monotonic", lambda: t[0])
    cache._snapshot_reads.clear()
    cache._kv_snapshot("top_picks_snapshot", "_system")
    t[0] += cache._SNAPSHOT_READ_TTL + 1
    cache._kv_snapshot("top_picks_snapshot", "_system")
    assert len(calls) == 3
