"""Postgres outage fallback (19 Nov 2026: Neon's free 5 GB transfer allowance ran out).

When the GitHub jobs set STORE_FALLBACK_PATH and Postgres refuses (connect or first query),
trade_store switches to that SQLite file for the rest of the process, so the scans, alerts
and the day's records keep working; the workflows cache and upload the file for a later
merge. Without STORE_FALLBACK_PATH (the Streamlit app) nothing changes: reads return their
default and writes report failure, as before.
"""
from __future__ import annotations

import pytest

import trade_store


@pytest.fixture
def pg_down(monkeypatch):
    # conftest blanks _database_url for safety; stand in a URL that honours the fallback
    # exactly like the real function's first line does.
    monkeypatch.setattr(trade_store, "_database_url",
                        lambda: None if trade_store._pg_fallback else "postgresql://u:p@db.invalid/x")
    monkeypatch.setattr(trade_store, "_pg_pool", None)
    monkeypatch.setattr(trade_store, "_pg_fallback", None)
    monkeypatch.setattr(trade_store, "_SQLITE_PATH", trade_store._SQLITE_PATH)
    monkeypatch.setattr(trade_store, "_kv_ready_for", None)
    monkeypatch.setattr(trade_store, "_schema_ready_for", None)

    def refuse():
        raise RuntimeError("Your project has exceeded the data transfer quota")
    monkeypatch.setattr(trade_store, "_get_pg_pool", refuse)


def test_jobs_fall_back_to_sqlite_and_keep_their_data(pg_down, monkeypatch, tmp_path):
    path = tmp_path / "data" / "store_fallback.db"
    monkeypatch.setenv("STORE_FALLBACK_PATH", str(path))
    assert trade_store.kv_set("buy_calls:2026-11-19", [{"symbol": "DLF"}], user_id="_system")
    assert trade_store.kv_get("buy_calls:2026-11-19", user_id="_system") == [{"symbol": "DLF"}]
    assert path.exists()
    assert trade_store.backend_name() == "sqlite"
    assert "quota" in (trade_store.fallback_reason() or "")


def test_app_without_fallback_path_behaves_as_before(pg_down, monkeypatch):
    monkeypatch.delenv("STORE_FALLBACK_PATH", raising=False)
    assert trade_store.kv_set("x", 1) is False
    assert trade_store.kv_get("x", default="d") == "d"
    assert trade_store.fallback_reason() is None
    assert trade_store.backend_name() == "postgres"


def test_core_jobs_cache_and_upload_the_fallback_file():
    for wf in ("market-alerts", "warm-preopen-scan", "warm-top-picks", "warm_tomorrow_watchlist",
               "market-digest"):
        src = open(f".github/workflows/{wf}.yml", encoding="utf-8").read()
        assert "STORE_FALLBACK_PATH: data/store_fallback.db" in src, wf
        assert "store-fallback-" in src and "actions/cache/restore@v5" in src, wf
        assert "upload-artifact" in src, wf
