"""
analysis/fundamentals/prospective_tracker.py — persistence layer for the
Option A prospective fundamentals study (see research/
fundamentals_prospective_collect.py for the collector script that uses
this, and research/fundamentals_historical_variant.py's module docstring
for why Option A exists alongside Option B).

WHY THIS NEEDS ITS OWN TABLE: unlike research/output/*.csv (per-run
artifacts that don't need to survive between runs), this study is
inherently cross-run — it snapshots today's quant+qual fundamentals score
for every ticker, then MUST still know about that snapshot weeks later when
enough time has passed to check what actually happened to the price.
GitHub Actions runners are stateless (fresh VM every run, nothing persists
on disk), so this needs storage that lives outside the runner.

REUSES trade_store.py's EXISTING connection plumbing (_get_conn, _is_pg,
_q, _database_url) rather than duplicating it — same DATABASE_URL, same
Neon instance already used for paper trades, same automatic SQLite
fallback for local/no-DB-configured use. This module only adds its own
table and queries; it does not touch the trades/user_kv tables at all.

IMPORTANT — for this to actually persist across CI runs (not silently
reset every run), DATABASE_URL must be set as a GitHub Actions repository
secret pointing at the SAME Neon instance already used for paper trades on
Streamlit Cloud (that's a separate secret store from Streamlit Cloud's
secrets.toml — both need to point at the same DB). Without it, this falls
back to a fresh local SQLite file on every run and the study will never
accumulate anything — see validate_persistence()-style reasoning in
trade_store.py for the same caveat applied to trades.
"""
from __future__ import annotations

import datetime as _dt
import logging
from typing import List, Optional

import pandas as pd

from trade_store import _get_conn, _is_pg, _q, _database_url  # noqa: E402 — deliberate reuse, not a new DB layer

_log = logging.getLogger("analysis.fundamentals.prospective_tracker")

_schema_ready_for: Optional[str] = None


def ensure_schema() -> None:
    """Create the fundamentals_prospective table if needed. Skips if already
    run for this DB path (same idempotency pattern as trade_store.ensure_schema)."""
    global _schema_ready_for
    db_key = _database_url() or "sqlite"
    if _schema_ready_for == db_key:
        return

    with _get_conn() as conn:
        cur = conn.cursor()
        if _is_pg():
            cur.execute("""
                CREATE TABLE IF NOT EXISTS fundamentals_prospective (
                    id                SERIAL PRIMARY KEY,
                    ticker            TEXT NOT NULL,
                    snapshot_date     TEXT NOT NULL,
                    price_at_snapshot DOUBLE PRECISION NOT NULL,
                    quant_score       DOUBLE PRECISION,
                    posture           TEXT,
                    qual_score        DOUBLE PRECISION,
                    qual_green        INTEGER,
                    qual_red          INTEGER,
                    qual_amber        INTEGER,
                    technical_score   DOUBLE PRECISION,
                    fwd_20d           DOUBLE PRECISION,
                    fwd_60d           DOUBLE PRECISION,
                    fwd_120d          DOUBLE PRECISION,
                    evaluated_at      TEXT,
                    UNIQUE(ticker, snapshot_date)
                )
            """)
        else:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS fundamentals_prospective (
                    id                INTEGER PRIMARY KEY AUTOINCREMENT,
                    ticker            TEXT NOT NULL,
                    snapshot_date     TEXT NOT NULL,
                    price_at_snapshot REAL NOT NULL,
                    quant_score       REAL,
                    posture           TEXT,
                    qual_score        REAL,
                    qual_green        INTEGER,
                    qual_red          INTEGER,
                    qual_amber        INTEGER,
                    technical_score   REAL,
                    fwd_20d           REAL,
                    fwd_60d           REAL,
                    fwd_120d          REAL,
                    evaluated_at      TEXT,
                    UNIQUE(ticker, snapshot_date)
                )
            """)
        conn.commit()
    _schema_ready_for = db_key


def record_snapshot(ticker: str, snapshot_date: _dt.date, price: float,
                    quant_score: Optional[float], posture: Optional[str],
                    qual_score: Optional[float], qual_green: int, qual_red: int,
                    qual_amber: int, technical_score: Optional[float]) -> bool:
    """Insert one snapshot row. No-op (not an error) if this ticker already
    has a snapshot for this date — collector may run more than once a day."""
    ensure_schema()
    sql = _q("""
        INSERT INTO fundamentals_prospective
            (ticker, snapshot_date, price_at_snapshot, quant_score, posture,
             qual_score, qual_green, qual_red, qual_amber, technical_score)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """)
    if _is_pg():
        sql = sql.rstrip() + " ON CONFLICT (ticker, snapshot_date) DO NOTHING"
    else:
        sql = sql.replace("INSERT INTO", "INSERT OR IGNORE INTO")
    try:
        with _get_conn() as conn:
            cur = conn.cursor()
            cur.execute(sql, (ticker, str(snapshot_date), price, quant_score, posture,
                              qual_score, qual_green, qual_red, qual_amber, technical_score))
            conn.commit()
        return True
    except Exception as e:
        _log.warning("record_snapshot failed for %s/%s: %s", ticker, snapshot_date, e)
        return False


def fetch_due_for_evaluation(horizon_col: str, min_age_calendar_days: int) -> pd.DataFrame:
    """Rows where `horizon_col` (fwd_20d/fwd_60d/fwd_120d) is still NULL and
    the snapshot is old enough to plausibly have that many trading days
    elapsed. min_age_calendar_days is a coarse pre-filter (calendar days,
    generous over the trading-day horizon to account for weekends/holidays)
    — the CALLER still must locate the exact trading-day-offset price
    itself (this function doesn't know about trading calendars), so a row
    returned here isn't guaranteed to have enough real trading days yet;
    the caller should just skip it that case and it'll be picked up again
    next run."""
    ensure_schema()
    if horizon_col not in ("fwd_20d", "fwd_60d", "fwd_120d"):
        raise ValueError(f"unknown horizon column: {horizon_col}")
    cutoff = (_dt.date.today() - _dt.timedelta(days=min_age_calendar_days)).isoformat()
    sql = _q(f"""
        SELECT id, ticker, snapshot_date, price_at_snapshot
        FROM fundamentals_prospective
        WHERE {horizon_col} IS NULL AND snapshot_date <= ?
    """)
    with _get_conn() as conn:
        cur = conn.cursor()
        cur.execute(sql, (cutoff,))
        cols = [d[0] for d in cur.description]
        rows = cur.fetchall()
    return pd.DataFrame(rows, columns=cols)


def update_forward_return(row_id: int, horizon_col: str, value: float) -> None:
    ensure_schema()
    if horizon_col not in ("fwd_20d", "fwd_60d", "fwd_120d"):
        raise ValueError(f"unknown horizon column: {horizon_col}")
    sql = _q(f"UPDATE fundamentals_prospective SET {horizon_col} = ?, "
             f"evaluated_at = ? WHERE id = ?")
    with _get_conn() as conn:
        cur = conn.cursor()
        cur.execute(sql, (value, _dt.datetime.now().isoformat(), row_id))
        conn.commit()


def already_snapshotted_today(ticker: str, snapshot_date: _dt.date) -> bool:
    ensure_schema()
    sql = _q("SELECT 1 FROM fundamentals_prospective WHERE ticker = ? AND snapshot_date = ?")
    with _get_conn() as conn:
        cur = conn.cursor()
        cur.execute(sql, (ticker, str(snapshot_date)))
        return cur.fetchone() is not None


def fetch_all() -> pd.DataFrame:
    """Full table export, for research analysis / CSV download."""
    ensure_schema()
    with _get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM fundamentals_prospective ORDER BY snapshot_date, ticker")
        cols = [d[0] for d in cur.description]
        rows = cur.fetchall()
    return pd.DataFrame(rows, columns=cols)


def row_count() -> int:
    ensure_schema()
    with _get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM fundamentals_prospective")
        return int(cur.fetchone()[0])
