"""
Concurrency tests for trade_store's Postgres connection pool.

Regression for 2026-09-26: Tomorrow's Watchlist runs score_stock on 10
threads; each calls data.nse_delivery.load_symbol_history → trade_store
._get_conn(). psycopg2's ThreadedConnectionPool (max 5) raises PoolError the
instant it is exhausted, so most tickers lost their delivery snapshot and were
scored on the legacy volume split — different composite scores than the same
ticker gets on Analyze Stock.

The fake pool below reproduces psycopg2's exact exhaustion semantics
(raise, never wait) so these tests fail against the old _get_conn().
"""
from __future__ import annotations

import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

psycopg2_pool = pytest.importorskip("psycopg2.pool")

import trade_store  # noqa: E402
from data import nse_delivery  # noqa: E402

_COLS = ["date", "close", "deliv_pct", "traded_qty", "deliv_qty"]
_ROWS = [(f"2026-09-{26 - i:02d}", 100.0 + i, 40.0 + i, 1e6, 4e5) for i in range(10)]


class _FakeCursor:
    def __init__(self, hold_s: float):
        self._hold_s = hold_s
        self.description = None

    def execute(self, sql, params=()):
        time.sleep(self._hold_s)   # hold the connection so threads overlap
        self.description = ([(c,) for c in _COLS]
                            if sql.lstrip().upper().startswith("SELECT") else None)

    def fetchall(self):
        return list(_ROWS)

    def close(self):
        pass


class _FakeConn:
    def __init__(self, hold_s: float):
        self._hold_s = hold_s

    def cursor(self):
        return _FakeCursor(self._hold_s)

    def commit(self):
        pass


class _FakeThreadedPool:
    """Mimics psycopg2.pool.ThreadedConnectionPool: raises when exhausted."""

    hold_s = 0.02
    instances: list = []

    def __init__(self, minconn, maxconn, dsn):
        self.maxconn = maxconn
        self._lock = threading.Lock()
        self.out = 0
        self.peak = 0
        _FakeThreadedPool.instances.append(self)

    def getconn(self):
        with self._lock:
            if self.out >= self.maxconn:
                raise psycopg2_pool.PoolError("connection pool exhausted")
            self.out += 1
            self.peak = max(self.peak, self.out)
        return _FakeConn(self.hold_s)

    def putconn(self, conn):
        with self._lock:
            self.out -= 1


@pytest.fixture
def fake_pg(monkeypatch):
    _FakeThreadedPool.instances = []
    monkeypatch.setattr(psycopg2_pool, "ThreadedConnectionPool", _FakeThreadedPool)
    monkeypatch.setattr(trade_store, "_database_url", lambda: "postgresql://fake/db")
    monkeypatch.setattr(trade_store, "_pg_pool", None)
    monkeypatch.setattr(trade_store, "_pg_slots", None)
    monkeypatch.setattr(nse_delivery, "_schema_ready_for", None)
    yield _FakeThreadedPool
    # the per-thread depth counter must be back at zero after every test
    assert getattr(trade_store._pg_held, "n", 0) == 0


def test_fake_pool_reproduces_psycopg2_exhaustion():
    pool = _FakeThreadedPool(1, 2, "x")
    pool.getconn()
    pool.getconn()
    with pytest.raises(psycopg2_pool.PoolError):
        pool.getconn()


def test_concurrent_load_symbol_history_never_exhausts_pool(fake_pg, caplog):
    n = 4 * trade_store._PG_MAXCONN   # well past pool max, like a universe scan
    symbols = [f"SYM{i}" for i in range(n)]
    with ThreadPoolExecutor(max_workers=10) as ex:
        frames = list(ex.map(nse_delivery.load_symbol_history, symbols))

    assert all(len(df) == len(_ROWS) for df in frames), "some tickers got an empty frame"
    assert "connection pool exhausted" not in caplog.text
    assert len(fake_pg.instances) == 1, "pool must be created exactly once under a race"
    pool = fake_pg.instances[0]
    assert pool.peak <= trade_store._PG_MAXCONN
    assert pool.out == 0


def test_concurrent_get_snapshot_keeps_delivery_for_every_ticker(fake_pg):
    """The correctness side: every scanned ticker gets its delivery snapshot,
    so score_stock never falls back to the volume-only split on scan pages."""
    symbols = [f"SYM{i}" for i in range(25)]
    with ThreadPoolExecutor(max_workers=10) as ex:
        snaps = list(ex.map(nse_delivery.get_snapshot, symbols))
    assert all(s is not None and s["n"] == len(_ROWS) for s in snaps)


def test_nested_get_conn_on_same_thread_does_not_deadlock(fake_pg, monkeypatch):
    monkeypatch.setattr(trade_store, "_PG_ACQUIRE_TIMEOUT_S", 1.0)
    fake_pg.hold_s = 0.0
    try:
        with trade_store._get_conn():
            with trade_store._get_conn():
                pass
        # every slot was released — the full set is free again
        slots = trade_store._pg_slots
        assert all(slots.acquire(blocking=False) for _ in range(trade_store._PG_MAXCONN))
        for _ in range(trade_store._PG_MAXCONN):
            slots.release()
        assert fake_pg.instances[0].out == 0
    finally:
        fake_pg.hold_s = 0.02


def test_wait_times_out_with_pool_error_instead_of_hanging(fake_pg, monkeypatch):
    monkeypatch.setattr(trade_store, "_PG_ACQUIRE_TIMEOUT_S", 0.2)
    release = threading.Event()
    ready = threading.Barrier(trade_store._PG_MAXCONN + 1)

    def _hog():
        with trade_store._get_conn():
            ready.wait()
            release.wait(5)

    hogs = [threading.Thread(target=_hog) for _ in range(trade_store._PG_MAXCONN)]
    for t in hogs:
        t.start()
    try:
        ready.wait(5)
        t0 = time.monotonic()
        with pytest.raises(psycopg2_pool.PoolError, match="no Postgres connection free"):
            with trade_store._get_conn():
                pass
        assert time.monotonic() - t0 < 2.0
    finally:
        release.set()
        for t in hogs:
            t.join(5)


def test_getconn_failure_releases_slot(fake_pg, monkeypatch):
    trade_store._get_pg_pool()
    pool = fake_pg.instances[0]

    def _boom():
        raise RuntimeError("neon unreachable")

    monkeypatch.setattr(pool, "getconn", _boom)
    for _ in range(trade_store._PG_MAXCONN + 1):
        with pytest.raises(RuntimeError):
            with trade_store._get_conn():
                pass
    # every failed attempt gave its slot back
    assert trade_store._pg_slots.acquire(blocking=False)
    trade_store._pg_slots.release()
