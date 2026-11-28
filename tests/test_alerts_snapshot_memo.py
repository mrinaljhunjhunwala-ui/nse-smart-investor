"""alerts.check_alerts reads the big kv scan snapshots once per process."""
from alerts import check_alerts as ca


def test_snapshot_kv_reads_once(monkeypatch):
    monkeypatch.setattr(ca, "_SNAPSHOT_MEMO", {})
    reads = []

    class Store:
        @staticmethod
        def kv_get(key, user_id=None):
            reads.append(key)
            return {"data": {"buys": [1]}}

    a = ca._snapshot_kv(Store, "top_picks_snapshot")
    a["data"]["buys"].append(2)  # a caller edit must not leak into later reads
    b = ca._snapshot_kv(Store, "top_picks_snapshot")
    ca._snapshot_kv(Store, "all_scored_snapshot")
    assert reads == ["top_picks_snapshot", "all_scored_snapshot"]
    assert b == {"data": {"buys": [1]}}
