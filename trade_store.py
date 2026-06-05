"""
trade_store.py — Storage backend for paper trades.

Two backends, chosen automatically:

  • SQLite (default)  — local file `trades.db`. Works out of the box, but
    Streamlit Cloud's disk is EPHEMERAL, so trades reset on every redeploy.

  • Postgres (opt-in) — set a connection string and your trades survive
    redeploys. Provide it as a Streamlit secret:
        [database]
        url = "postgresql://user:pass@host/dbname"
    or as an environment variable DATABASE_URL.
    Use a free Neon (neon.tech) or Supabase (supabase.com) Postgres.
    See dashboard/DB_SETUP.md for the 5-minute setup.

All paper-trade reads/writes in the dashboard go through this module so the
two backends stay in sync. SQLite behaviour is unchanged from before.
"""

from __future__ import annotations

import datetime
import json
import logging
import os
from typing import Any, List, Optional

import pandas as pd

_log = logging.getLogger("trade_store")
_SQLITE_PATH = "trades.db"


# ─────────────────────────────────────────────────────────────────────────────
# Backend selection
# ─────────────────────────────────────────────────────────────────────────────

def _database_url() -> Optional[str]:
    """Return a Postgres URL from Streamlit secrets or env, else None."""
    url = None
    try:
        import streamlit as st
        _db = st.secrets.get("database", {}) if hasattr(st, "secrets") else {}
        url = (_db or {}).get("url") if isinstance(_db, dict) else None
        if not url:
            try:
                url = st.secrets.get("DATABASE_URL")
            except Exception:
                url = None
    except Exception:
        url = None
    return (url or os.environ.get("DATABASE_URL")) or None


def backend_name() -> str:
    return "postgres" if _database_url() else "sqlite"


def validate_persistence() -> dict:
    """Startup validation for the persistence layer (P1).

    Checks, in order: (1) is a DATABASE_URL configured, (2) is the database reachable,
    (3) is the schema valid (both `trades` and `user_kv` queryable). Returns a structured
    status dict; NEVER raises — callers surface `warnings`/`error` to the user.
    """
    backend = backend_name()
    url_present = bool(_database_url())
    ephemeral = (backend == "sqlite")
    status = {
        "backend": backend,
        "db_url_present": url_present,
        "reachable": False,
        "schema_ok": False,
        "ephemeral": ephemeral,
        "warnings": [],
        "error": None,
    }
    if ephemeral:
        status["warnings"].append(
            "SQLite backend: storage is EPHEMERAL on Streamlit Cloud — paper trades, "
            "watchlist and saved settings RESET on every redeploy. Set DATABASE_URL "
            "(Postgres) to persist them. See DEPLOYMENT_CHECKLIST.md."
        )
    try:
        ensure_schema()
        _kv_ensure()
        conn = _connect()
        try:
            cur = conn.cursor()
            cur.execute("SELECT 1 FROM trades LIMIT 1")
            cur.execute("SELECT 1 FROM user_kv LIMIT 1")
            status["reachable"] = True
            status["schema_ok"] = True
        finally:
            conn.close()
    except Exception as e:
        status["error"] = f"{type(e).__name__}: {e}"
        status["warnings"].append(
            f"Database not reachable / schema invalid ({backend}): {e}. "
            "Reads will return empty and writes will fail — fix before relying on persistence."
        )
        _log.error("validate_persistence failed (%s): %s", backend, e)
    return status


def _is_pg() -> bool:
    return backend_name() == "postgres"


def _connect():
    if _is_pg():
        import psycopg2
        return psycopg2.connect(_database_url())
    import sqlite3
    return sqlite3.connect(_SQLITE_PATH)


def _q(sql: str) -> str:
    """Translate '?' placeholders to '%s' on Postgres; leave as-is on SQLite."""
    return sql.replace("?", "%s") if _is_pg() else sql


# ─────────────────────────────────────────────────────────────────────────────
# Schema
# ─────────────────────────────────────────────────────────────────────────────

def ensure_schema() -> None:
    conn = _connect()
    try:
        cur = conn.cursor()
        if _is_pg():
            cur.execute("""
                CREATE TABLE IF NOT EXISTS trades (
                    id          SERIAL PRIMARY KEY,
                    account     TEXT    NOT NULL DEFAULT 'My Account',
                    ticker      TEXT    NOT NULL,
                    strategy    TEXT    NOT NULL DEFAULT 'Manual',
                    action      TEXT    NOT NULL,
                    price       DOUBLE PRECISION NOT NULL,
                    quantity    INTEGER NOT NULL,
                    sl          DOUBLE PRECISION,
                    tp          DOUBLE PRECISION,
                    trail_stop  DOUBLE PRECISION,
                    capital     DOUBLE PRECISION,
                    reason      TEXT,
                    timestamp   TEXT    NOT NULL,
                    status      TEXT    DEFAULT 'OPEN',
                    exit_price  DOUBLE PRECISION,
                    exit_reason TEXT,
                    exit_time   TEXT,
                    pnl         DOUBLE PRECISION,
                    pnl_pct     DOUBLE PRECISION
                )
            """)
        else:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS trades (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    account     TEXT    NOT NULL DEFAULT 'My Account',
                    ticker      TEXT    NOT NULL,
                    strategy    TEXT    NOT NULL DEFAULT 'Manual',
                    action      TEXT    NOT NULL,
                    price       REAL    NOT NULL,
                    quantity    INTEGER NOT NULL,
                    sl          REAL,
                    tp          REAL,
                    trail_stop  REAL,
                    capital     REAL,
                    reason      TEXT,
                    timestamp   TEXT    NOT NULL,
                    status      TEXT    DEFAULT 'OPEN',
                    exit_price  REAL,
                    exit_reason TEXT,
                    exit_time   TEXT,
                    pnl         REAL,
                    pnl_pct     REAL
                )
            """)
            # Migration: older DBs may lack the account column
            cols = [r[1] for r in cur.execute("PRAGMA table_info(trades)").fetchall()]
            if "account" not in cols:
                cur.execute(
                    "ALTER TABLE trades ADD COLUMN account TEXT NOT NULL DEFAULT 'My Account'"
                )
        conn.commit()
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# Accounts
# ─────────────────────────────────────────────────────────────────────────────

def list_accounts() -> List[str]:
    ensure_schema()
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute("SELECT DISTINCT account FROM trades ORDER BY account")
        names = [r[0] for r in cur.fetchall() if r[0]]
    finally:
        conn.close()
    return names if names else ["My Account"]


def rename_account(old_name: str, new_name: str) -> None:
    conn = _connect()
    try:
        conn.cursor().execute(_q("UPDATE trades SET account=? WHERE account=?"),
                              (new_name, old_name))
        conn.commit()
    finally:
        conn.close()


def delete_account(name: str) -> None:
    conn = _connect()
    try:
        conn.cursor().execute(_q("DELETE FROM trades WHERE account=?"), (name,))
        conn.commit()
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# Trades
# ─────────────────────────────────────────────────────────────────────────────

def open_trade(ticker: str, price: float, qty: int, sl: float, tp: float,
               reason: str = "", account: str = "My Account") -> int:
    ensure_schema()
    now = datetime.datetime.now().isoformat()
    cols = ("account,ticker,strategy,action,price,quantity,sl,tp,capital,reason,timestamp")
    vals = (account, ticker, "Manual", "BUY", price, qty, sl, tp, price * qty, reason, now)
    conn = _connect()
    try:
        cur = conn.cursor()
        if _is_pg():
            cur.execute(_q(f"INSERT INTO trades ({cols}) VALUES (?,?,?,?,?,?,?,?,?,?,?) RETURNING id"), vals)
            new_id = cur.fetchone()[0]
        else:
            cur.execute(f"INSERT INTO trades ({cols}) VALUES (?,?,?,?,?,?,?,?,?,?,?)", vals)
            new_id = cur.lastrowid
        conn.commit()
        return int(new_id)
    finally:
        conn.close()


def close_trade(trade_id: int, exit_price: float, reason: str = "Manual close") -> None:
    now = datetime.datetime.now().isoformat()
    conn = _connect()
    try:
        cur = conn.cursor()
        cur.execute(_q("SELECT price, quantity FROM trades WHERE id=?"), (trade_id,))
        row = cur.fetchone()
        if not row:
            return
        entry_price, qty = float(row[0]), int(row[1])
        pnl     = (exit_price - entry_price) * qty
        pnl_pct = (exit_price / entry_price - 1) * 100 if entry_price > 0 else 0
        cur.execute(
            _q("UPDATE trades SET status='CLOSED', exit_price=?, exit_time=?, "
               "exit_reason=?, pnl=?, pnl_pct=? WHERE id=?"),
            (exit_price, now, reason, pnl, pnl_pct, trade_id),
        )
        conn.commit()
    finally:
        conn.close()


def edit_trade(trade_id: int, sl: float = None, tp: float = None,
               reason: str = None) -> None:
    fields, vals = [], []
    if sl is not None:
        fields.append("sl=?"); vals.append(sl)
    if tp is not None:
        fields.append("tp=?"); vals.append(tp)
    if reason is not None:
        fields.append("reason=?"); vals.append(reason)
    if not fields:
        return
    vals.append(trade_id)
    conn = _connect()
    try:
        conn.cursor().execute(_q(f"UPDATE trades SET {', '.join(fields)} WHERE id=?"), vals)
        conn.commit()
    finally:
        conn.close()


def load_by_account(account: str) -> pd.DataFrame:
    ensure_schema()
    conn = _connect()
    try:
        return pd.read_sql_query(
            _q("SELECT * FROM trades WHERE account=? ORDER BY id DESC"),
            conn, params=(account,),
        )
    except Exception as e:
        # Was a silent swallow that returned an empty frame — indistinguishable from
        # "no trades", so a broken DB looked like an empty account and the user could
        # unknowingly re-open positions. Log it so the failure is diagnosable; the
        # empty frame is still returned so the UI degrades instead of crashing.
        _log.warning("load_by_account(%r) failed: %s", account, e)
        return pd.DataFrame()
    finally:
        conn.close()


def fetch_open(account: str = None) -> pd.DataFrame:
    ensure_schema()
    conn = _connect()
    try:
        if account:
            return pd.read_sql_query(
                _q("SELECT * FROM trades WHERE status='OPEN' AND account=?"),
                conn, params=(account,),
            )
        return pd.read_sql_query(
            "SELECT * FROM trades WHERE status='OPEN' ORDER BY timestamp DESC", conn
        )
    except Exception as e:
        # P2: was a silent swallow — an empty frame looked like "no open trades", masking a
        # broken DB. Log so the failure is diagnosable; still degrade to an empty frame.
        _log.warning("fetch_open(account=%r) failed: %s", account, e)
        return pd.DataFrame()
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# Key-value store — persists user settings & watchlist across sessions
# (and across redeploys when a Postgres backend is configured)
# ─────────────────────────────────────────────────────────────────────────────

def _kv_ensure() -> None:
    conn = _connect()
    try:
        conn.cursor().execute(
            "CREATE TABLE IF NOT EXISTS user_kv (k TEXT PRIMARY KEY, v TEXT)"
        )
        conn.commit()
    finally:
        conn.close()


def kv_get(key: str, default: Any = None) -> Any:
    """Read a JSON-serialised setting; returns `default` if missing/unavailable."""
    try:
        _kv_ensure()
        conn = _connect()
        try:
            cur = conn.cursor()
            cur.execute(_q("SELECT v FROM user_kv WHERE k=?"), (key,))
            row = cur.fetchone()
            return json.loads(row[0]) if row and row[0] is not None else default
        finally:
            conn.close()
    except Exception as e:
        # P2: log (not silent) — a read failure here silently reverted user settings to
        # defaults, which is indistinguishable from "never set". The default is still
        # returned so the UI degrades gracefully.
        _log.warning("kv_get(%r) failed: %s", key, e)
        return default


def kv_set(key: str, value: Any) -> bool:
    """Upsert a JSON-serialisable setting. Returns True on success, False on failure.

    P2: previously a silent no-op on failure, which could lose a user's watchlist /
    settings without any signal. It now LOGS and returns a success flag so callers can
    surface a save failure to the user — a persistence error is never silent.
    """
    try:
        _kv_ensure()
        payload = json.dumps(value)
        conn = _connect()
        try:
            cur = conn.cursor()
            if _is_pg():
                cur.execute(
                    "INSERT INTO user_kv (k, v) VALUES (%s, %s) "
                    "ON CONFLICT (k) DO UPDATE SET v = EXCLUDED.v",
                    (key, payload),
                )
            else:
                cur.execute("INSERT OR REPLACE INTO user_kv (k, v) VALUES (?, ?)",
                            (key, payload))
            conn.commit()
        finally:
            conn.close()
        return True
    except Exception as e:
        _log.error("kv_set(%r) FAILED — setting not persisted: %s", key, e)
        return False
