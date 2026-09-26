"""
tools/purge_test_rows.py — one-off cleanup of test-fixture rows that leaked
into the shared trade_store database.

Background (2026-09-26): before tests/conftest.py existed, locally-run tests
wrote into production Postgres because DATABASE_URL is a system env var on
the owner's machine. The visible damage: FAKE1.NS @ ₹100 rows in verdict_log
(source="tomorrow_watchlist"), which Tomorrow's Watchlist then showed users
as a "previous pick".

What counts as a test row (deliberately narrow — only fixture tickers that
can never be real NSE/BSE symbols):
    ticker matches  ^(FAKE|TEST|DUMMY|MOCK)[0-9]*(\\.NS|\\.BO)?$   (case-insensitive)

Tables covered:
    verdict_log              ticker matches
    verdict_signal_tags      verdict_log_id belongs to a matched verdict_log row
    verdict_forward_returns  verdict_log_id belongs to a matched verdict_log row
    trades                   ticker matches
    user_kv                  key names a fixture ticker (e.g. qualitative_flags:FAKE1.NS)
    user_kv (report only)    VALUE mentions a fixture ticker — printed for manual
                             review, never auto-edited (it's a JSON blob that may
                             also hold real data)

Usage (targets whatever trade_store resolves: DATABASE_URL, else local SQLite):
    py tools/purge_test_rows.py            # dry run — read-only, deletes nothing
    py tools/purge_test_rows.py --apply    # delete exactly the rows listed

--apply deletes by primary key inside ONE transaction (children first), then
re-runs the scan and reports what's left.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from typing import Dict, List, Tuple
from urllib.parse import urlparse

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

TEST_TICKER_RE = re.compile(r"^(FAKE|TEST|DUMMY|MOCK)[0-9]*(\.NS|\.BO)?$", re.IGNORECASE)
_KV_VALUE_RE = re.compile(r"\b(FAKE|TEST|DUMMY|MOCK)[0-9]*\.(NS|BO)\b", re.IGNORECASE)


def is_test_ticker(ticker) -> bool:
    return bool(ticker) and bool(TEST_TICKER_RE.match(str(ticker).strip()))


def _kv_key_ticker(key: str) -> str:
    return key.rsplit(":", 1)[-1] if ":" in key else ""


def _target_label(store) -> str:
    url = store._database_url()
    if not url:
        return f"SQLite · {os.path.abspath(store._SQLITE_PATH)}"
    p = urlparse(url)
    return f"Postgres · {p.hostname}/{(p.path or '/').lstrip('/')}"  # never print credentials


def _table_exists(cur, store, table: str) -> bool:
    if store._is_pg():
        cur.execute("SELECT to_regclass(%s)", (f"public.{table}",))
        return cur.fetchone()[0] is not None
    cur.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,))
    return cur.fetchone() is not None


def _fetch(cur, sql: str, params: Tuple = ()) -> List[tuple]:
    cur.execute(sql, params)
    return cur.fetchall()


def find_test_rows(cur, store) -> Dict[str, list]:
    """Scan for fixture rows. Read-only. Returns {section: [row tuples]}."""
    q = store._q
    plan: Dict[str, list] = {
        "verdict_log": [], "verdict_signal_tags": [], "verdict_forward_returns": [],
        "trades": [], "user_kv": [], "user_kv_values_review": [],
    }

    if _table_exists(cur, store, "verdict_log"):
        rows = _fetch(cur, "SELECT id, logged_date, ticker, entry_price, verdict, source "
                           "FROM verdict_log ORDER BY id")
        plan["verdict_log"] = [r for r in rows if is_test_ticker(r[2])]
    ids = [r[0] for r in plan["verdict_log"]]

    for child in ("verdict_signal_tags", "verdict_forward_returns"):
        if ids and _table_exists(cur, store, child):
            marks = ",".join("?" * len(ids))
            cols = "verdict_log_id, tag" if child == "verdict_signal_tags" else "verdict_log_id, checked_at"
            plan[child] = _fetch(
                cur, q(f"SELECT {cols} FROM {child} WHERE verdict_log_id IN ({marks}) "
                       f"ORDER BY verdict_log_id"), tuple(ids))

    if _table_exists(cur, store, "trades"):
        rows = _fetch(cur, "SELECT id, account, ticker, price, quantity, status, timestamp "
                           "FROM trades ORDER BY id")
        plan["trades"] = [r for r in rows if is_test_ticker(r[2])]

    if _table_exists(cur, store, "user_kv"):
        for user_id, k, v in _fetch(cur, "SELECT user_id, k, v FROM user_kv ORDER BY user_id, k"):
            if is_test_ticker(_kv_key_ticker(k)):
                plan["user_kv"].append((user_id, k))
            elif v and _KV_VALUE_RE.search(v):
                hits = sorted({m.group(0).upper() for m in _KV_VALUE_RE.finditer(v)})
                plan["user_kv_values_review"].append((user_id, k, ", ".join(hits)))
    return plan


def print_plan(plan: Dict[str, list]) -> int:
    headers = {
        "verdict_log":             "id, logged_date, ticker, entry_price, verdict, source",
        "verdict_signal_tags":     "verdict_log_id, tag",
        "verdict_forward_returns": "verdict_log_id, checked_at",
        "trades":                  "id, account, ticker, price, quantity, status, timestamp",
        "user_kv":                 "user_id, k",
        "user_kv_values_review":   "user_id, k, fixture tickers in value  (REPORT ONLY — not deleted)",
    }
    total = 0
    for section, rows in plan.items():
        deletable = section != "user_kv_values_review"
        total += len(rows) if deletable else 0
        print(f"\n[{section}] {len(rows)} row(s){'' if deletable else ' — manual review'}")
        if rows:
            print(f"    ({headers[section]})")
            for r in rows:
                print(f"    {r}")
    print(f"\nTotal rows that --apply would delete: {total}")
    return total


def apply_plan(cur, store, plan: Dict[str, list]) -> Dict[str, int]:
    """Delete exactly the rows in `plan`, by primary key. Caller commits."""
    q = store._q
    deleted: Dict[str, int] = {}
    ids = [r[0] for r in plan["verdict_log"]]

    def _delete_in(table: str, col: str, keys: list) -> int:
        if not keys:
            return 0
        marks = ",".join("?" * len(keys))
        cur.execute(q(f"DELETE FROM {table} WHERE {col} IN ({marks})"), tuple(keys))
        return cur.rowcount

    # Children before parents.
    if plan["verdict_signal_tags"]:
        deleted["verdict_signal_tags"] = _delete_in("verdict_signal_tags", "verdict_log_id", ids)
    if plan["verdict_forward_returns"]:
        deleted["verdict_forward_returns"] = _delete_in("verdict_forward_returns", "verdict_log_id", ids)
    deleted["verdict_log"] = _delete_in("verdict_log", "id", ids)
    deleted["trades"] = _delete_in("trades", "id", [r[0] for r in plan["trades"]])
    n_kv = 0
    for user_id, k in plan["user_kv"]:
        cur.execute(q("DELETE FROM user_kv WHERE user_id=? AND k=?"), (user_id, k))
        n_kv += cur.rowcount
    deleted["user_kv"] = n_kv
    return deleted


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--apply", action="store_true",
                    help="actually delete the listed rows (default: dry run, read-only)")
    args = ap.parse_args(argv)

    import trade_store as store

    print(f"Target: {_target_label(store)}")
    print(f"Mode:   {'APPLY — rows below WILL be deleted' if args.apply else 'DRY RUN — nothing is modified'}")

    with store._get_conn() as conn:
        if store._is_pg() and not args.apply:
            conn.set_session(readonly=True)
        try:
            cur = conn.cursor()
            plan = find_test_rows(cur, store)
            total = print_plan(plan)

            if not args.apply:
                conn.rollback()
                print("\nDry run only. Re-run with --apply to delete.")
                return 0
            if total == 0:
                conn.rollback()
                print("\nNothing to delete.")
                return 0

            deleted = apply_plan(cur, store, plan)
            conn.commit()
            print(f"\nDeleted: {deleted}")

            remaining = find_test_rows(cur, store)
            conn.rollback()
            left = sum(len(v) for k, v in remaining.items() if k != "user_kv_values_review")
            print(f"Re-scan after delete: {left} test row(s) remain.")
            return 0 if left == 0 else 1
        except Exception:
            conn.rollback()
            raise
        finally:
            if store._is_pg() and not args.apply:
                conn.set_session(readonly=False)  # connection goes back to the pool


if __name__ == "__main__":
    sys.exit(main())
