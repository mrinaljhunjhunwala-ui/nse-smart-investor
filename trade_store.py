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
import os
from typing import List, Optional

import pandas as pd

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
    except Exception:
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
    except Exception:
        return pd.DataFrame()
    finally:
        conn.close()
