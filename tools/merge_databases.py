"""
tools/merge_databases.py — copy every row of an old Postgres project into a new one.

Why (Nov 2026): the Neon project behind ``DATABASE_URL`` hit its free 5 GB/month
transfer quota on 19 Nov and refused every connection. The owner pointed
``DATABASE_URL`` at a NEW, empty project so the app and jobs work again. Once the old
project resets (~1 Dec) this tool copies its data INTO the new project, which then stays
the main one.

Rules:
  * Read-only on the source (read-only transaction); never deletes anything anywhere.
  * Rows already in the target win (they are newer). Re-running is safe.
  * Tables are discovered from the source's information_schema (its current schema,
    normally ``public``), not from a hard-coded list. Only clear caches are skipped
    (``CACHE_TABLES``; ``--include-cache`` copies them too).
  * The target schema is created with the repo's own ensure functions
    (``REPO_ENSURE``) so column types / indexes match what the code expects; any other
    table is created from the source's DDL (columns, PK / UNIQUE, indexes).

How each table is copied:
  * Surrogate-key tables (a single serial / identity primary key: ``trades``,
    ``verdict_log``, ``fundamentals_prospective``): a source row that matches a target
    row on any UNIQUE key (``verdict_log``: logged_date, ticker, horizon, source), or on
    all non-id columns when there is none (``trades``), is already present and skipped.
    Otherwise it is inserted, keeping its old id when the target hasn't used it, else
    with a fresh id above both databases' max. Old id -> new id is remembered so
    child tables follow.
  * Child tables (a declared foreign key, or a column named ``<table>_id`` for a
    surrogate table, e.g. ``verdict_signal_tags.verdict_log_id``): the reference is
    rewritten through that mapping first; a child whose parent isn't in the source is
    reported as an orphan and not copied.
  * Tables with a natural primary key / unique constraint (``user_kv``,
    ``nse_delivery_daily`` ...): ``INSERT ... ON CONFLICT DO NOTHING``. Keys present in
    both with a different value keep the TARGET's value; for ``user_kv`` every such
    key is listed so the owner can review it.
  * Tables with no key: de-duplicated on all columns (a multiset, so genuine
    duplicate rows survive and a re-run inserts nothing).
  * Afterwards every serial / identity sequence on the target is set so the next id is
    max(id) + 1.

Usage:
    py tools/merge_databases.py --from OLD_URL --to NEW_URL            # dry run
    py tools/merge_databases.py --apply                                # env URLs
Env fallbacks: OLD_DATABASE_URL (source), DATABASE_URL (target).

The dry run does the whole copy inside one target transaction per table and rolls it
back, so its counts are exact (sequences are left alone: setval is not transactional).
Each --apply table commits on its own; a failure part-way leaves earlier tables copied,
and a re-run picks up where it stopped.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import urlparse

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

# Clear caches only. daily_bars is the legacy price store: since 19 Nov 2026 it lives in
# its own SQLite file (data/price_store.py) and Yahoo can re-serve every bar; it was the
# table that burned the transfer quota, so copying it would burn it again.
CACHE_TABLES = frozenset({"daily_bars"})
KV_TABLE = "user_kv"
DEFAULT_BATCH = 1000


# ─────────────────────────────────────────────────────────────────────────────
# Pure helpers (unit-tested offline)
# ─────────────────────────────────────────────────────────────────────────────

def redact(url: Optional[str]) -> str:
    """host/dbname only — never print credentials."""
    if not url:
        return "(unset)"
    try:
        p = urlparse(url)
        return f"{p.hostname or '?'}/{(p.path or '/').lstrip('/') or '?'}"
    except Exception:
        return "(unparseable url)"


def same_database(a: Optional[str], b: Optional[str]) -> bool:
    if not a or not b:
        return False
    if a.strip() == b.strip():
        return True
    pa, pb = urlparse(a.strip()), urlparse(b.strip())

    def _host(h):   # Neon's pooler and direct endpoints are the same database
        return (h or "").lower().replace("-pooler.", ".")
    return (_host(pa.hostname), pa.port or 5432, pa.path) == (_host(pb.hostname), pb.port or 5432, pb.path)


def hashable(v: Any) -> Any:
    """Row values as dict keys (json / jsonb come back as dict / list)."""
    if isinstance(v, (dict, list)):
        return json.dumps(v, sort_keys=True, default=str)
    return v


def row_key(row: Sequence[Any], idx: Sequence[int]) -> tuple:
    return tuple(hashable(row[i]) for i in idx)


@dataclass
class TableInfo:
    name: str
    columns: List[str]
    types: Dict[str, str] = field(default_factory=dict)     # column -> format_type
    pk: List[str] = field(default_factory=list)
    uniques: List[List[str]] = field(default_factory=list)  # unique keys other than the PK
    serial_col: Optional[str] = None                        # single-column serial / identity PK
    identity_always: bool = False
    fks: Dict[str, str] = field(default_factory=dict)       # column -> referenced table (declared)

    @property
    def strategy(self) -> str:
        if self.serial_col:
            return "surrogate"
        if self.pk or self.uniques:
            return "natural"
        return "nokey"


def find_refs(infos: Dict[str, TableInfo]) -> Dict[str, Dict[str, str]]:
    """child table -> {column: parent surrogate table}. Declared FKs, plus the repo's
    convention of an undeclared ``<parent>_id`` column (verdict_signal_tags.verdict_log_id)."""
    surrogate = {t for t, i in infos.items() if i.strategy == "surrogate"}
    refs: Dict[str, Dict[str, str]] = {}
    for t, info in infos.items():
        m = {c: p for c, p in info.fks.items() if p in surrogate and p != t}
        for c in info.columns:
            if c.endswith("_id") and c[:-3] in surrogate and c[:-3] != t:
                m.setdefault(c, c[:-3])
        if m:
            refs[t] = m
    return refs


def copy_order(tables: Iterable[str], refs: Dict[str, Dict[str, str]]) -> List[str]:
    """Parents before children; otherwise alphabetical (stable output)."""
    remaining = sorted(set(tables))
    done: List[str] = []
    while remaining:
        ready = [t for t in remaining
                 if all(p in done or p not in remaining for p in refs.get(t, {}).values())]
        if not ready:                      # a cycle — just keep the rest alphabetical
            ready = remaining[:1]
        for t in ready:
            done.append(t)
            remaining.remove(t)
    return done


class SurrogatePlanner:
    """Decide, per source row of a serial-PK table, skip (already in target) or insert
    (with which id). Pure: fed the target's rows up front."""

    def __init__(self, columns: Sequence[str], id_col: str, uniques: Sequence[Sequence[str]],
                 dst_rows: Iterable[Sequence[Any]], src_max_id: Optional[int]):
        self.columns = list(columns)
        self.id_idx = self.columns.index(id_col)
        self.key_sets = [[self.columns.index(c) for c in u] for u in uniques]
        self.all_idx = [i for i in range(len(self.columns)) if i != self.id_idx]
        self.taken: set = set()
        self.by_unique: List[Dict[tuple, Any]] = [dict() for _ in self.key_sets]
        self.by_all: Dict[tuple, List[Any]] = defaultdict(list)
        for r in dst_rows:
            rid = r[self.id_idx]
            self.taken.add(rid)
            if self.key_sets:
                for ks, idx in zip(self.key_sets, self.by_unique):
                    idx.setdefault(row_key(r, ks), rid)
            else:
                self.by_all[row_key(r, self.all_idx)].append(rid)
        top = max([x for x in self.taken if x is not None] + [src_max_id or 0, 0])
        self.next_free = top + 1
        self.mapping: Dict[Any, Any] = {}

    def plan(self, row: Sequence[Any]) -> Tuple[str, Any]:
        """('skip', target_id) or ('insert', id_to_use). Records old id -> new id."""
        src_id = row[self.id_idx]
        if self.key_sets:
            for ks, idx in zip(self.key_sets, self.by_unique):
                hit = idx.get(row_key(row, ks))
                if hit is not None:
                    self.mapping[src_id] = hit
                    return "skip", hit
        else:
            ids = self.by_all.get(row_key(row, self.all_idx))
            if ids:
                hit = ids.pop()
                self.mapping[src_id] = hit
                return "skip", hit
        if src_id is not None and src_id not in self.taken:
            new_id = src_id
        else:
            while self.next_free in self.taken:
                self.next_free += 1
            new_id = self.next_free
        self.taken.add(new_id)
        self.mapping[src_id] = new_id
        # later source rows that are duplicates of this one are "already present" too
        if self.key_sets:
            for ks, idx in zip(self.key_sets, self.by_unique):
                idx.setdefault(row_key(row, ks), new_id)
        return "insert", new_id


def remap_row(row: Sequence[Any], ref_idx: Dict[int, Dict[Any, Any]]) -> Optional[list]:
    """Rewrite parent references through the id mappings; None if the parent is missing
    (orphan). A NULL reference stays NULL."""
    out = list(row)
    for i, mapping in ref_idx.items():
        v = out[i]
        if v is None:
            continue
        if v not in mapping:
            return None
        out[i] = mapping[v]
    return out


def multiset_missing(src_rows: Iterable[Sequence[Any]], remaining: Counter) -> List[list]:
    """Rows of a key-less table that the target doesn't hold yet, matching by full row as
    a multiset: each target copy absorbs one source copy, so genuine duplicate rows
    survive and a re-run inserts nothing. ``remaining`` (full-row key -> unmatched target
    copies) is consumed in place so it can span batches."""
    out = []
    for r in src_rows:
        k = row_key(r, range(len(r)))
        if remaining[k] > 0:
            remaining[k] -= 1
        else:
            out.append(list(r))
    return out


def diff_conflicts(src_rows: Iterable[Sequence[Any]], key_idx: Sequence[int],
                   dst_by_key: Dict[tuple, tuple]) -> Tuple[int, List[tuple]]:
    """For a natural-key table: (#keys present in both with the same row,
    [keys present in both with a different row]). The target's row is kept either way."""
    same, differ = 0, []
    for r in src_rows:
        k = row_key(r, key_idx)
        d = dst_by_key.get(k)
        if d is None:
            continue
        if tuple(hashable(v) for v in r) == d:
            same += 1
        else:
            differ.append(k)
    return same, differ


# ─────────────────────────────────────────────────────────────────────────────
# Catalog discovery
# ─────────────────────────────────────────────────────────────────────────────

_REL = "to_regclass(quote_ident(current_schema()) || '.' || quote_ident(%s))"


def list_tables(conn) -> List[str]:
    cur = conn.cursor()
    cur.execute("SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = current_schema() AND table_type = 'BASE TABLE' "
                "ORDER BY table_name")
    return [r[0] for r in cur.fetchall()]


def describe(conn, table: str) -> TableInfo:
    cur = conn.cursor()
    cur.execute(f"""
        SELECT a.attname, format_type(a.atttypid, a.atttypmod), a.attidentity
        FROM pg_attribute a
        WHERE a.attrelid = {_REL} AND a.attnum > 0 AND NOT a.attisdropped
        ORDER BY a.attnum""", (table,))
    cols = cur.fetchall()
    info = TableInfo(name=table, columns=[c[0] for c in cols], types={c[0]: c[1] for c in cols})
    identity = {c[0]: c[2] for c in cols}
    cur.execute(f"""
        SELECT i.indisprimary,
               array_agg(a.attname ORDER BY k.ord)
        FROM pg_index i
        CROSS JOIN LATERAL unnest(i.indkey::int2[]) WITH ORDINALITY AS k(attnum, ord)
        JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = k.attnum
        WHERE i.indrelid = {_REL} AND i.indisunique AND i.indpred IS NULL
          AND 0 <> ALL (i.indkey::int2[])
        GROUP BY i.indexrelid, i.indisprimary
        ORDER BY i.indisprimary DESC, i.indexrelid""", (table,))
    for is_pk, colnames in cur.fetchall():
        colnames = list(colnames)
        if is_pk:
            info.pk = colnames
        elif colnames not in info.uniques:
            info.uniques.append(colnames)
    if len(info.pk) == 1:
        col = info.pk[0]
        cur.execute("SELECT pg_get_serial_sequence(quote_ident(current_schema()) || '.' "
                    "|| quote_ident(%s), %s)", (table, col))
        if cur.fetchone()[0]:
            info.serial_col = col
            info.identity_always = identity.get(col) == "a"
    cur.execute(f"""
        SELECT a.attname, rc.relname
        FROM pg_constraint c
        JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = c.conkey[1]
        JOIN pg_class rc ON rc.oid = c.confrelid
        WHERE c.conrelid = {_REL} AND c.contype = 'f' AND array_length(c.conkey, 1) = 1""", (table,))
    info.fks = {a: r for a, r in cur.fetchall()}
    return info


def create_table_sql(conn, table: str) -> List[str]:
    """DDL for ``table`` as it is in ``conn``'s current schema: columns (serial defaults
    become identity), PK / UNIQUE constraints, then the other indexes."""
    cur = conn.cursor()
    cur.execute(f"""
        SELECT a.attname, format_type(a.atttypid, a.atttypmod), a.attnotnull,
               pg_get_expr(d.adbin, d.adrelid), a.attidentity
        FROM pg_attribute a
        LEFT JOIN pg_attrdef d ON d.adrelid = a.attrelid AND d.adnum = a.attnum
        WHERE a.attrelid = {_REL} AND a.attnum > 0 AND NOT a.attisdropped
        ORDER BY a.attnum""", (table,))
    parts = []
    for name, typ, notnull, default, ident in cur.fetchall():
        line = f"{_qi(name)} {typ}"
        if ident or (default and default.startswith("nextval(")):
            line += " GENERATED BY DEFAULT AS IDENTITY"
        elif default:
            line += f" DEFAULT {default}"
        if notnull:
            line += " NOT NULL"
        parts.append(line)
    cur.execute(f"""SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint
                    WHERE conrelid = {_REL} AND contype IN ('p', 'u') ORDER BY contype, conname""",
                (table,))
    cons = cur.fetchall()
    parts += [f"CONSTRAINT {_qi(n)} {d}" for n, d in cons]
    stmts = [f"CREATE TABLE IF NOT EXISTS {_qi(table)} (\n    " + ",\n    ".join(parts) + "\n)"]
    cur.execute("SELECT quote_ident(current_schema())")
    schema = cur.fetchone()[0]
    cur.execute("SELECT indexname, indexdef FROM pg_indexes "
                "WHERE schemaname = current_schema() AND tablename = %s ORDER BY indexname", (table,))
    con_names = {n for n, _ in cons}
    for iname, idef in cur.fetchall():
        if iname in con_names:
            continue
        stmts.append(rewrite_indexdef(idef, schema))
    return stmts


def rewrite_indexdef(indexdef: str, src_schema: str) -> str:
    """pg_indexes.indexdef -> idempotent, unqualified (lands in the target's schema)."""
    s = indexdef.replace("CREATE UNIQUE INDEX ", "CREATE UNIQUE INDEX IF NOT EXISTS ", 1)
    if "IF NOT EXISTS" not in s:
        s = s.replace("CREATE INDEX ", "CREATE INDEX IF NOT EXISTS ", 1)
    return s.replace(f" ON {src_schema}.", " ON ", 1).replace(f" ON ONLY {src_schema}.", " ON ONLY ", 1)


def _qi(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


# ─────────────────────────────────────────────────────────────────────────────
# Repo ensure functions (so the target matches what the code creates)
# ─────────────────────────────────────────────────────────────────────────────

# (module, function) — every Postgres table the repo creates. price_store.ensure_table is
# left out on purpose: since 19 Nov 2026 it only ever writes its own SQLite file.
REPO_ENSURE: Tuple[Tuple[str, str], ...] = (
    ("trade_store", "ensure_schema"),                         # trades
    ("trade_store", "_kv_ensure"),                            # user_kv
    ("analysis.verdict_ledger", "ensure_schema"),             # verdict_log, _signal_tags, _forward_returns
    ("analysis.fundamentals.prospective_tracker", "ensure_schema"),  # fundamentals_prospective
    ("analysis.fii_dii", "ensure_schema"),                    # fii_dii_daily
    ("data.nse_delivery", "ensure_schema"),                   # nse_delivery_daily
    ("data.nse_fii_deriv", "ensure_schema"),                  # nse_fii_deriv_daily
    ("data.nse_option_chain", "ensure_schema"),               # nse_option_chain_daily
    ("data.nse_fno_bhavcopy", "ensure_schema"),               # nse_fno_oi_daily
)
_READY_FLAGS = ("_schema_ready_for", "_kv_ready_for", "_ready_for")


def ensure_target_schema(url: str, out=print) -> List[str]:
    """Run the repo's own ensure functions with trade_store pointed at ``url``.
    Returns the functions that ran. trade_store is restored afterwards."""
    import importlib

    import trade_store
    saved_env = os.environ.pop("STORE_FALLBACK_PATH", None)   # never fall back to SQLite here
    saved_url_fn, saved_pool = trade_store._database_url, trade_store._pg_pool
    saved_fallback = trade_store._pg_fallback
    patched: List[Tuple[Any, str, Any]] = []

    def _target_url():
        return url

    ran = []
    try:
        trade_store._database_url = _target_url
        trade_store._pg_pool = None
        trade_store._pg_fallback = None
        for mod_name, fn_name in REPO_ENSURE:
            mod = importlib.import_module(mod_name)
            # modules that did `from trade_store import _database_url` hold their own name
            if mod is not trade_store and getattr(mod, "_database_url", None) is saved_url_fn:
                patched.append((mod, "_database_url", saved_url_fn))
                mod._database_url = _target_url
            for flag in _READY_FLAGS:
                if hasattr(mod, flag):
                    patched.append((mod, flag, getattr(mod, flag)))
                    setattr(mod, flag, None)
            getattr(mod, fn_name)()
            ran.append(f"{mod_name}.{fn_name}")
        if trade_store._pg_fallback:
            raise RuntimeError(f"trade_store fell back to SQLite: {trade_store._pg_fallback}")
    finally:
        pool = trade_store._pg_pool
        if pool is not None and pool is not saved_pool:
            try:
                pool.closeall()
            except Exception:
                pass
        trade_store._database_url = saved_url_fn
        trade_store._pg_pool = saved_pool
        trade_store._pg_fallback = saved_fallback
        for mod, attr, val in reversed(patched):
            setattr(mod, attr, val)
        if saved_env is not None:
            os.environ["STORE_FALLBACK_PATH"] = saved_env
    out(f"Target schema ensured by: {', '.join(ran)}")
    return ran


# ─────────────────────────────────────────────────────────────────────────────
# Copy
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class TableResult:
    table: str
    strategy: str
    source_rows: int = 0
    copied: int = 0
    present: int = 0          # skipped: already in the target
    differ: int = 0           # of `present`: same key, different value (target kept)
    orphans: int = 0          # child rows whose parent isn't in the source
    created: bool = False
    added_columns: List[str] = field(default_factory=list)
    dropped_columns: List[str] = field(default_factory=list)   # in source only, not copied
    conflict_keys: List[tuple] = field(default_factory=list)
    sequence: Optional[str] = None
    skipped_reason: Optional[str] = None


def _stream(src, table: str, columns: Sequence[str], batch: int, order_by: Optional[str] = None):
    cur = src.cursor(name=f"merge_{table}"[:60])
    cur.itersize = batch
    order = f" ORDER BY {_qi(order_by)}" if order_by else ""
    cur.execute(f"SELECT {', '.join(_qi(c) for c in columns)} FROM {_qi(table)}{order}")
    while True:
        rows = cur.fetchmany(batch)
        if not rows:
            break
        yield rows
    cur.close()


def _adapt(rows: Iterable[Sequence[Any]], columns: Sequence[str], types: Dict[str, str]):
    from psycopg2.extras import Json
    json_idx = [i for i, c in enumerate(columns) if types.get(c, "").startswith("json")]
    if not json_idx:
        return [tuple(r) for r in rows]
    out = []
    for r in rows:
        r = list(r)
        for i in json_idx:
            if r[i] is not None and not isinstance(r[i], str):
                r[i] = Json(r[i])
            elif isinstance(r[i], str):
                r[i] = Json(json.loads(r[i]))
        out.append(tuple(r))
    return out


def _insert(dst, info: TableInfo, columns: Sequence[str], rows: List[Sequence[Any]], batch: int) -> int:
    if not rows:
        return 0
    from psycopg2.extras import execute_values
    override = " OVERRIDING SYSTEM VALUE" if info.identity_always and info.serial_col in columns else ""
    sql = (f"INSERT INTO {_qi(info.name)} ({', '.join(_qi(c) for c in columns)}){override} "
           f"VALUES %s ON CONFLICT DO NOTHING RETURNING 1")
    got = execute_values(dst.cursor(), sql, _adapt(rows, columns, info.types), page_size=batch, fetch=True)
    return len(got)


def _fetch_all(conn, table: str, columns: Sequence[str]) -> List[tuple]:
    cur = conn.cursor()
    cur.execute(f"SELECT {', '.join(_qi(c) for c in columns)} FROM {_qi(table)}")
    return cur.fetchall()


def reset_sequence(dst, table: str, col: str) -> Optional[str]:
    """Next id = max(id) + 1 (1 on an empty table). Returns a description, or None."""
    cur = dst.cursor()
    cur.execute("SELECT pg_get_serial_sequence(quote_ident(current_schema()) || '.' || quote_ident(%s), %s)",
                (table, col))
    seq = cur.fetchone()[0]
    if not seq:
        return None
    cur.execute(f"SELECT setval(%s, COALESCE(MAX({_qi(col)}), 0) + 1, false) FROM {_qi(table)}", (seq,))
    nxt = cur.fetchone()[0]
    return f"{seq} -> next {nxt}"


def copy_table(src, dst, info: TableInfo, dst_info: TableInfo, *, mappings: Dict[str, Dict[Any, Any]],
               refs: Dict[str, str], batch: int, result: TableResult) -> None:
    """Copy one table's rows (caller owns the transaction)."""
    columns = [c for c in info.columns if c in dst_info.columns]
    result.dropped_columns = [c for c in info.columns if c not in dst_info.columns]
    ref_idx = {columns.index(c): mappings.get(p, {}) for c, p in refs.items() if c in columns}

    def _remapped(rows):
        out = []
        for r in rows:
            m = remap_row(r, ref_idx) if ref_idx else list(r)
            if m is None:
                result.orphans += 1
            else:
                out.append(m)
        return out

    strategy = dst_info.strategy if dst_info.strategy != "nokey" else info.strategy
    if info.serial_col and dst_info.serial_col == info.serial_col:
        cur = src.cursor()
        cur.execute(f"SELECT MAX({_qi(info.serial_col)}) FROM {_qi(info.name)}")
        src_max = cur.fetchone()[0]
        planner = SurrogatePlanner(columns, info.serial_col, dst_info.uniques,
                                   _fetch_all(dst, info.name, columns), src_max)
        id_i = columns.index(info.serial_col)
        for rows in _stream(src, info.name, columns, batch, order_by=info.serial_col):
            result.source_rows += len(rows)
            todo = []
            for r in _remapped(rows):
                action, new_id = planner.plan(r)
                if action == "skip":
                    result.present += 1
                else:
                    r[id_i] = new_id
                    todo.append(r)
            n = _insert(dst, dst_info, columns, todo, batch)
            result.copied += n
            result.present += len(todo) - n
        mappings[info.name] = planner.mapping
    elif strategy == "natural":
        key = dst_info.pk or dst_info.uniques[0]
        key_idx = [columns.index(c) for c in key]
        dst_by_key = {row_key(r, key_idx): tuple(hashable(v) for v in r)
                      for r in _fetch_all(dst, info.name, columns)}
        for rows in _stream(src, info.name, columns, batch):
            result.source_rows += len(rows)
            rows = _remapped(rows)
            _same, differ = diff_conflicts(rows, key_idx, dst_by_key)
            result.differ += len(differ)
            if info.name == KV_TABLE:
                result.conflict_keys += differ
            n = _insert(dst, dst_info, columns, rows, batch)
            result.copied += n
            result.present += len(rows) - n
    else:
        remaining = Counter(row_key(r, range(len(columns))) for r in _fetch_all(dst, info.name, columns))
        for rows in _stream(src, info.name, columns, batch):
            result.source_rows += len(rows)
            rows = _remapped(rows)
            todo = multiset_missing(rows, remaining)
            n = _insert(dst, dst_info, columns, todo, batch)
            result.copied += n
            result.present += len(rows) - n


def merge(src, dst, *, apply: bool = False, include_cache: bool = False,
          only: Optional[Sequence[str]] = None, exclude: Sequence[str] = (),
          batch: int = DEFAULT_BATCH, ensure: Optional[Callable[[], Any]] = None,
          out=print) -> List[TableResult]:
    """Copy src -> dst. ``src`` / ``dst`` are open psycopg2 connections (their current
    schema is used). ``ensure`` (apply only) creates the repo's tables on the target first."""
    src.set_session(readonly=True)
    tables = list_tables(src)
    infos = {t: describe(src, t) for t in tables}
    src.rollback()
    refs = find_refs(infos)
    results: List[TableResult] = []
    mappings: Dict[str, Dict[Any, Any]] = {}   # surrogate table -> old id -> new id
    wanted = []
    out(f"Discovered {len(tables)} table(s) in the source:")
    for t in tables:
        i = infos[t]
        cur = src.cursor()
        cur.execute(f"SELECT COUNT(*) FROM {_qi(t)}")
        n = cur.fetchone()[0]
        key = (f"serial id {i.serial_col}" + (f", unique {i.uniques}" if i.uniques else ", match on all columns")
               if i.strategy == "surrogate" else
               f"key {i.pk or i.uniques[0]}" if i.strategy == "natural" else "no key: all columns")
        note = ""
        if t in CACHE_TABLES and not include_cache:
            note = "  [cache: skipped, --include-cache to copy]"
        elif only and t not in only:
            note = "  [not in --only]"
        elif t in exclude:
            note = "  [--exclude]"
        else:
            wanted.append(t)
        ref = f"; refs {refs[t]}" if t in refs else ""
        out(f"  {t:<28} {n:>9} rows  {key}{ref}{note}")
        if note:
            results.append(TableResult(t, i.strategy, source_rows=n, skipped_reason=note.strip(" []")))
    src.rollback()

    if apply and ensure is not None:
        ensure()
    dst_tables = set(list_tables(dst))
    dst.commit()

    for t in copy_order(wanted, refs):
        info = infos[t]
        res = TableResult(t, info.strategy)
        try:
            if t not in dst_tables:
                for stmt in create_table_sql(src, t):
                    dst.cursor().execute(stmt)
                res.created = True
            dst_info = describe(dst, t)
            for c in info.columns:
                if c not in dst_info.columns:
                    dst.cursor().execute(
                        f"ALTER TABLE {_qi(t)} ADD COLUMN IF NOT EXISTS {_qi(c)} {info.types[c]}")
                    res.added_columns.append(c)
            if res.added_columns:
                dst_info = describe(dst, t)
            copy_table(src, dst, info, dst_info, mappings=mappings,
                       refs=refs.get(t, {}), batch=batch, result=res)
            if dst_info.serial_col:
                if apply:
                    res.sequence = reset_sequence(dst, t, dst_info.serial_col)
                else:
                    res.sequence = "(reset to max(id)+1 on --apply)"
            if apply:
                dst.commit()
            else:
                dst.rollback()
            src.rollback()
        except Exception:
            dst.rollback()
            src.rollback()
            raise
        results.append(res)
    return results


def format_summary(results: Sequence[TableResult], apply: bool) -> str:
    head = "APPLIED" if apply else "DRY RUN (nothing written; counts are what --apply would do)"
    lines = [f"\n{head}",
             f"{'table':<28} {'source':>9} {'copied':>9} {'present':>9} {'differ':>7} {'orphan':>7}  notes"]
    for r in results:
        notes = []
        if r.skipped_reason:
            notes.append(r.skipped_reason)
        if r.created:
            notes.append("created from source DDL" if apply else "missing in target: would be created")
        if r.added_columns:
            notes.append(f"added columns {r.added_columns}")
        if r.dropped_columns:
            notes.append(f"source-only columns not copied {r.dropped_columns}")
        if r.sequence:
            notes.append(f"seq {r.sequence}")
        copied = "-" if r.skipped_reason else r.copied
        present = "-" if r.skipped_reason else r.present
        lines.append(f"{r.table:<28} {r.source_rows:>9} {copied:>9} {present:>9} {r.differ:>7} "
                     f"{r.orphans:>7}  {'; '.join(notes)}")
    lines.append("present = already in the target (target row kept); differ = of those, same key but "
                 "a different value; orphan = child row whose parent isn't in the source (not copied)")
    for r in results:
        if r.conflict_keys:
            lines.append(f"\n{r.table}: {len(r.conflict_keys)} key(s) in both with different values "
                         f"— the TARGET (newer) value was kept; review these:")
            lines += [f"  {k}" for k in r.conflict_keys]
    return "\n".join(lines)


def _connect(url: str):
    import psycopg2
    return psycopg2.connect(url, connect_timeout=20, application_name="merge_databases")


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--from", dest="src", default=os.environ.get("OLD_DATABASE_URL"),
                    help="source (old) database URL; default env OLD_DATABASE_URL")
    ap.add_argument("--to", dest="dst", default=os.environ.get("DATABASE_URL"),
                    help="target (new) database URL; default env DATABASE_URL")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", default=True, help="report only (default)")
    mode.add_argument("--apply", action="store_true", help="write to the target")
    ap.add_argument("--include-cache", action="store_true",
                    help=f"also copy cache tables {sorted(CACHE_TABLES)}")
    ap.add_argument("--only", nargs="*", help="copy only these tables")
    ap.add_argument("--exclude", nargs="*", default=[], help="skip these tables")
    ap.add_argument("--batch", type=int, default=DEFAULT_BATCH)
    ap.add_argument("--no-repo-ensure", action="store_true",
                    help="create missing target tables from source DDL instead of the repo's ensure functions")
    a = ap.parse_args(argv)

    if not a.src or not a.dst:
        print("Need --from/--to (or OLD_DATABASE_URL / DATABASE_URL).", file=sys.stderr)
        return 2
    if same_database(a.src, a.dst):
        print("Source and target are the same database — refusing.", file=sys.stderr)
        return 2
    print(f"Source (read-only): {redact(a.src)}")
    print(f"Target:             {redact(a.dst)}")
    print(f"Mode: {'APPLY' if a.apply else 'DRY RUN'}\n")
    src, dst = _connect(a.src), _connect(a.dst)
    try:
        ensure = None if a.no_repo_ensure else (lambda: ensure_target_schema(a.dst))
        results = merge(src, dst, apply=a.apply, include_cache=a.include_cache, only=a.only,
                        exclude=a.exclude or (), batch=a.batch, ensure=ensure)
    finally:
        src.close()
        dst.close()
    print(format_summary(results, a.apply))
    return 0


if __name__ == "__main__":
    sys.exit(main())
