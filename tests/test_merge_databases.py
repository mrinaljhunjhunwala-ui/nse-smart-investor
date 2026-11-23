"""tools/merge_databases.py — old Neon project -> new project copy.

Pure helpers run offline. The end-to-end cases are @pytest.mark.real_postgres: they run
in CI's `real-postgres` job (its own Postgres container) and skip when
TEST_DATABASE_URL is unset. Each builds a source and a target schema inside the test
database and drops both afterwards.
"""
from __future__ import annotations

import importlib
import os
import re
import uuid
from collections import Counter
from pathlib import Path

import pytest

from tools import merge_databases as md

ROOT = Path(__file__).resolve().parents[1]


# ── pure helpers ────────────────────────────────────────────────────────────

def test_redact_hides_credentials():
    url = "postgresql://owner:s3cret@ep-cool-1234-pooler.aws.neon.tech/neondb?sslmode=require"
    out = md.redact(url)
    assert "s3cret" not in out and "owner" not in out
    assert out == "ep-cool-1234-pooler.aws.neon.tech/neondb"
    assert md.redact(None) == "(unset)"


def test_same_database_sees_pooler_and_direct_as_one():
    a = "postgresql://u:p@ep-x-1-pooler.neon.tech/db"
    b = "postgresql://u2:q@ep-x-1.neon.tech/db?sslmode=require"
    assert md.same_database(a, b)
    assert not md.same_database(a, "postgresql://u:p@ep-y-2.neon.tech/db")
    assert not md.same_database(a, None)


def _info(name, cols, pk=(), uniques=(), serial=None, fks=None):
    return md.TableInfo(name=name, columns=list(cols), pk=list(pk), uniques=[list(u) for u in uniques],
                        serial_col=serial, fks=fks or {})


def test_find_refs_uses_fk_and_parent_id_convention():
    infos = {
        "verdict_log": _info("verdict_log", ["id", "ticker"], pk=["id"], serial="id"),
        "verdict_signal_tags": _info("verdict_signal_tags", ["verdict_log_id", "tag"],
                                     pk=["verdict_log_id", "tag"]),
        "trades": _info("trades", ["id", "ticker"], pk=["id"], serial="id"),
        "legs": _info("legs", ["id", "parent"], pk=["id"], fks={"parent": "trades"}),
        "user_kv": _info("user_kv", ["user_id", "k", "v"], pk=["user_id", "k"]),
    }
    refs = md.find_refs(infos)
    # user_kv.user_id is not a reference: there is no surrogate table called "user"
    assert refs == {"verdict_signal_tags": {"verdict_log_id": "verdict_log"},
                    "legs": {"parent": "trades"}}
    order = md.copy_order(infos, refs)
    assert order.index("verdict_log") < order.index("verdict_signal_tags")
    assert order.index("trades") < order.index("legs")


def test_strategy_classification():
    assert _info("t", ["id"], pk=["id"], serial="id").strategy == "surrogate"
    assert _info("t", ["a"], uniques=[["a"]]).strategy == "natural"
    assert _info("t", ["a", "b"]).strategy == "nokey"


def test_surrogate_planner_matches_unique_key_and_renumbers_collisions():
    cols = ["id", "logged_date", "ticker"]
    dst = [(1, "2026-11-20", "NEW"), (2, "2026-11-01", "OLD2")]        # rows written to the new project
    p = md.SurrogatePlanner(cols, "id", [["logged_date", "ticker"]], dst, src_max_id=5)
    assert p.plan((1, "2026-11-01", "OLD1")) == ("insert", 6)           # id 1 taken by NEW -> fresh id
    assert p.plan((2, "2026-11-01", "OLD2")) == ("skip", 2)             # same natural key -> present
    assert p.plan((3, "2026-11-01", "OLD3")) == ("insert", 3)           # id free -> kept
    assert p.plan((4, "2026-11-01", "OLD1")) == ("skip", 6)             # duplicate of a row just planned
    assert p.mapping == {1: 6, 2: 2, 3: 3, 4: 6}


def test_surrogate_planner_without_unique_key_matches_all_columns_as_multiset():
    cols = ["id", "ticker", "price"]
    dst = [(1, "A", 10.0), (2, "B", 20.0)]
    p = md.SurrogatePlanner(cols, "id", [], dst, src_max_id=3)
    assert p.plan((1, "B", 20.0)) == ("skip", 2)        # already copied on an earlier run
    assert p.plan((2, "B", 20.0)) == ("insert", 4)      # a second identical trade is a real row
    assert p.plan((3, "C", 30.0)) == ("insert", 3)


def test_remap_row_rewrites_and_flags_orphans():
    ref = {0: {1: 6, 2: 2}}
    assert md.remap_row((1, "x"), ref) == [6, "x"]
    assert md.remap_row((None, "x"), ref) == [None, "x"]
    assert md.remap_row((99, "x"), ref) is None


def test_multiset_missing_keeps_duplicates_and_spans_batches():
    remaining = Counter({("x", 1): 1})
    assert md.multiset_missing([("x", 1), ("x", 1), ("y", 2)], remaining) == [["x", 1], ["y", 2]]
    assert md.multiset_missing([("x", 1)], remaining) == [["x", 1]]   # target's single copy used up
    # json values compare by content
    rem = Counter({md.row_key(({"a": 1},), [0]): 1})
    assert md.multiset_missing([({"a": 1},)], rem) == []


def test_diff_conflicts_reports_changed_keys_only():
    dst = {("default", "k1"): ("default", "k1", "new"), ("default", "k2"): ("default", "k2", "same")}
    rows = [("default", "k1", "old"), ("default", "k2", "same"), ("default", "k3", "x")]
    same, differ = md.diff_conflicts(rows, [0, 1], dst)
    assert same == 1 and differ == [("default", "k1")]


def test_rewrite_indexdef_is_idempotent_and_unqualified():
    d = "CREATE UNIQUE INDEX ux_v ON src_1.verdict_log USING btree (logged_date, ticker)"
    assert md.rewrite_indexdef(d, "src_1") == (
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_v ON verdict_log USING btree (logged_date, ticker)")
    d2 = "CREATE INDEX ix_t ON public.verdict_log USING btree (ticker)"
    assert md.rewrite_indexdef(d2, "public") == "CREATE INDEX IF NOT EXISTS ix_t ON verdict_log USING btree (ticker)"


def test_format_summary_lists_kv_conflicts():
    r = md.TableResult("user_kv", "natural", source_rows=3, copied=1, present=2, differ=1,
                       conflict_keys=[("default", "holdings")])
    s = md.format_summary([r, md.TableResult("daily_bars", "natural", 9, skipped_reason="cache")], apply=False)
    assert "DRY RUN" in s and "('default', 'holdings')" in s and "TARGET (newer) value was kept" in s
    assert "cache" in s


def test_main_refuses_missing_or_identical_urls(monkeypatch, capsys):
    monkeypatch.delenv("OLD_DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert md.main(["--to", "postgresql://u:p@h/db"]) == 2
    assert md.main(["--from", "postgresql://u:p@h-pooler.x/db", "--to", "postgresql://u:p@h.x/db"]) == 2
    assert "same database" in capsys.readouterr().err


def test_repo_ensure_list_resolves_and_covers_every_postgres_create_table():
    """Stale-list guard: every CREATE TABLE in Postgres-capable code lives in a module the
    tool calls an ensure function of (SQLite-only modules excluded)."""
    covered_src = ""
    for mod_name, fn in md.REPO_ENSURE:
        mod = importlib.import_module(mod_name)
        assert callable(getattr(mod, fn))
        covered_src += Path(mod.__file__).read_text(encoding="utf-8")
    covered = set(re.findall(r"CREATE TABLE IF NOT EXISTS (\w+)", covered_src))
    sqlite_only = {"trading/paper_trader.py", "data/price_store.py", "dashboard/shared/trade_utils.py"}
    found = set()
    for p in ROOT.rglob("*.py"):
        rel = p.relative_to(ROOT).as_posix()
        if rel.startswith(("tests/", ".claude/", "tools/")) or rel in sqlite_only:
            continue
        found |= set(re.findall(r"CREATE TABLE IF NOT EXISTS (\w+)", p.read_text(encoding="utf-8")))
    assert found <= covered, f"tables created outside REPO_ENSURE: {found - covered}"


# ── real Postgres (CI `real-postgres` job) ──────────────────────────────────

_SRC_DDL = """
CREATE TABLE trades (id SERIAL PRIMARY KEY, ticker TEXT NOT NULL, price DOUBLE PRECISION NOT NULL);
CREATE TABLE verdict_log (id SERIAL PRIMARY KEY, logged_date TEXT NOT NULL, ticker TEXT NOT NULL,
                          horizon TEXT, source TEXT NOT NULL, backfill_misses INTEGER DEFAULT 0);
CREATE UNIQUE INDEX ux_verdict_log_daily ON verdict_log(logged_date, ticker, horizon, source);
CREATE TABLE verdict_signal_tags (verdict_log_id INTEGER NOT NULL, tag TEXT NOT NULL,
                                  PRIMARY KEY (verdict_log_id, tag));
CREATE TABLE verdict_forward_returns (verdict_log_id INTEGER PRIMARY KEY, ret_5d DOUBLE PRECISION);
CREATE TABLE user_kv (user_id TEXT NOT NULL DEFAULT 'default', k TEXT NOT NULL, v TEXT,
                      PRIMARY KEY (user_id, k));
CREATE TABLE notes_nokey (a TEXT, b INTEGER, meta JSONB);
CREATE INDEX ix_notes_a ON notes_nokey(a);
CREATE TABLE daily_bars (symbol TEXT, date TEXT, close DOUBLE PRECISION, PRIMARY KEY (symbol, date));
INSERT INTO trades (id, ticker, price) VALUES (1, 'OLDA', 10), (2, 'OLDB', 20), (3, 'OLDC', 30);
SELECT setval(pg_get_serial_sequence('trades', 'id'), 3);
INSERT INTO verdict_log (id, logged_date, ticker, horizon, source) VALUES
    (1, '2026-11-01', 'X', 'swing', 'scan'), (2, '2026-11-01', 'Y', 'swing', 'scan');
INSERT INTO verdict_signal_tags VALUES (1, 'a'), (2, 'b'), (99, 'orphan');
INSERT INTO verdict_forward_returns VALUES (1, 0.01), (2, 0.02);
INSERT INTO user_kv VALUES ('default', 'k1', 'old'), ('default', 'k2', 'same'), ('default', 'k3', 'only-old');
INSERT INTO notes_nokey VALUES ('x', 1, '{"n": 1}'), ('x', 1, '{"n": 1}'), ('y', 2, NULL);
INSERT INTO daily_bars VALUES ('RELIANCE', '2026-11-01', 1500);
"""

# the new project: tables the app has created since the switch, with newer rows
_DST_DDL = """
CREATE TABLE trades (id SERIAL PRIMARY KEY, ticker TEXT NOT NULL, price DOUBLE PRECISION NOT NULL);
CREATE TABLE verdict_log (id SERIAL PRIMARY KEY, logged_date TEXT NOT NULL, ticker TEXT NOT NULL,
                          horizon TEXT, source TEXT NOT NULL);
CREATE UNIQUE INDEX ux_verdict_log_daily ON verdict_log(logged_date, ticker, horizon, source);
CREATE TABLE verdict_signal_tags (verdict_log_id INTEGER NOT NULL, tag TEXT NOT NULL,
                                  PRIMARY KEY (verdict_log_id, tag));
CREATE TABLE user_kv (user_id TEXT NOT NULL DEFAULT 'default', k TEXT NOT NULL, v TEXT,
                      PRIMARY KEY (user_id, k));
INSERT INTO trades (ticker, price) VALUES ('NEWT', 99), ('OLDB', 20);
INSERT INTO verdict_log (logged_date, ticker, horizon, source) VALUES ('2026-11-01', 'Y', 'swing', 'scan');
INSERT INTO verdict_signal_tags VALUES (1, 'b');
INSERT INTO user_kv VALUES ('default', 'k1', 'new'), ('default', 'k2', 'same');
"""


def _schema_conn(schema: str):
    import psycopg2
    conn = psycopg2.connect(os.environ["TEST_DATABASE_URL"])
    cur = conn.cursor()
    cur.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
    cur.execute(f'SET search_path TO "{schema}"')
    conn.commit()
    return conn


@pytest.fixture
def two_dbs():
    tag = uuid.uuid4().hex[:8]
    src_s, dst_s = f"mrg_src_{tag}", f"mrg_dst_{tag}"
    src, dst = _schema_conn(src_s), _schema_conn(dst_s)
    src.cursor().execute(_SRC_DDL)
    src.commit()
    dst.cursor().execute(_DST_DDL)
    dst.commit()
    yield src, dst
    for c in (src, dst):
        c.rollback()
        c.set_session(readonly=False)
    cur = dst.cursor()
    cur.execute(f'DROP SCHEMA IF EXISTS "{src_s}" CASCADE')
    cur.execute(f'DROP SCHEMA IF EXISTS "{dst_s}" CASCADE')
    dst.commit()
    src.close()
    dst.close()


def _rows(conn, sql):
    cur = conn.cursor()
    cur.execute(sql)
    out = cur.fetchall()
    conn.rollback()
    return out


def _by_table(results):
    return {r.table: r for r in results}


@pytest.mark.real_postgres
def test_dry_run_writes_nothing_but_counts_exactly(two_dbs):
    src, dst = two_dbs
    res = _by_table(md.merge(src, dst, apply=False, out=lambda *_: None))
    assert res["trades"].copied == 2 and res["trades"].present == 1
    assert res["daily_bars"].skipped_reason
    assert _rows(dst, "SELECT count(*) FROM trades") == [(2,)]
    assert _rows(dst, "SELECT to_regclass('verdict_forward_returns')") == [(None,)]
    assert _rows(dst, "SELECT last_value FROM trades_id_seq") == [(2,)]


@pytest.mark.real_postgres
def test_apply_merges_keeps_target_rows_and_is_rerunnable(two_dbs):
    src, dst = two_dbs
    src_before = {t: _rows(src, f"SELECT * FROM {t} ORDER BY 1, 2") for t in
                  ("trades", "verdict_log", "verdict_signal_tags", "user_kv")}
    res = _by_table(md.merge(src, dst, apply=True, out=lambda *_: None))

    # trades: OLDB already there; OLDA's id 1 is taken by NEWT -> fresh id 4; OLDC keeps id 3
    assert (res["trades"].source_rows, res["trades"].copied, res["trades"].present) == (3, 2, 1)
    assert _rows(dst, "SELECT id, ticker FROM trades ORDER BY id") == [
        (1, "NEWT"), (2, "OLDB"), (3, "OLDC"), (4, "OLDA")]
    assert _rows(dst, "SELECT nextval('trades_id_seq')") == [(5,)]

    # verdict_log: Y matched on the unique key (target id 1); X's id 1 is taken -> id 3
    assert _rows(dst, "SELECT id, ticker FROM verdict_log ORDER BY id") == [(1, "Y"), (3, "X")]
    # source-only column added to the target, values copied
    assert "backfill_misses" in res["verdict_log"].added_columns
    # tags follow the id mapping; the orphan isn't copied
    assert _rows(dst, "SELECT * FROM verdict_signal_tags ORDER BY 1") == [(1, "b"), (3, "a")]
    t = res["verdict_signal_tags"]
    assert (t.copied, t.present, t.orphans) == (1, 1, 1)
    # missing table created from source DDL, rows remapped
    assert res["verdict_forward_returns"].created
    assert _rows(dst, "SELECT * FROM verdict_forward_returns ORDER BY 1") == [(1, 0.02), (3, 0.01)]

    # KV: target value wins, conflict reported
    kv = res["user_kv"]
    assert (kv.copied, kv.present, kv.differ) == (1, 2, 1)
    assert kv.conflict_keys == [("default", "k1")]
    assert _rows(dst, "SELECT k, v FROM user_kv ORDER BY k") == [
        ("k1", "new"), ("k2", "same"), ("k3", "only-old")]

    # key-less table: duplicates kept, json round-trips, index copied
    assert res["notes_nokey"].copied == 3
    assert _rows(dst, "SELECT count(*) FROM notes_nokey WHERE meta = '{\"n\": 1}'::jsonb") == [(2,)]
    assert _rows(dst, "SELECT indexname FROM pg_indexes WHERE schemaname = current_schema() "
                      "AND tablename = 'notes_nokey'") == [("ix_notes_a",)]
    # cache skipped
    assert _rows(dst, "SELECT to_regclass('daily_bars')") == [(None,)]

    # source untouched
    for tname, rows in src_before.items():
        assert _rows(src, f"SELECT * FROM {tname} ORDER BY 1, 2") == rows

    # re-run: nothing new
    again = md.merge(src, dst, apply=True, out=lambda *_: None)
    assert sum(r.copied for r in again) == 0
    assert _rows(dst, "SELECT count(*) FROM trades") == [(4,)]


@pytest.mark.real_postgres
def test_ensure_target_schema_creates_repo_tables():
    ran = md.ensure_target_schema(os.environ["TEST_DATABASE_URL"], out=lambda *_: None)
    assert len(ran) == len(md.REPO_ENSURE)
    import psycopg2   # guarded by conftest: lands in this run's schema, as the ensure calls did
    conn = psycopg2.connect(os.environ["TEST_DATABASE_URL"])
    try:
        have = set(md.list_tables(conn))
    finally:
        conn.close()
    assert {"trades", "user_kv", "verdict_log", "verdict_signal_tags", "verdict_forward_returns",
            "fundamentals_prospective", "fii_dii_daily", "nse_delivery_daily"} <= have
    import trade_store
    assert trade_store._pg_fallback is None
