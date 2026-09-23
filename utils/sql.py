"""Pure DB-API → DataFrame helper (no Streamlit, no trade_store imports).

Lives here rather than in ``trade_store`` so ``analysis/`` and ``data/`` can use
it without pulling in ``trade_store``'s lazy ``import streamlit`` (secrets
lookup). ``trade_store.read_sql_df`` re-exports this function.
"""
from __future__ import annotations

import pandas as pd


def read_sql_df(sql: str, conn, params=()) -> pd.DataFrame:
    """Run a SELECT via a DB-API cursor and return a DataFrame.

    Equivalent to ``pd.read_sql_query(sql, conn, params=params)`` but works
    identically for sqlite3 and psycopg2 connections without pandas' "only
    supports SQLAlchemy connectable" UserWarning. ``sql`` must already use the
    connection's placeholder style (pass it through ``trade_store._q()``).

    ``coerce_float=True`` mirrors ``read_sql_query``'s default so Postgres
    ``NUMERIC`` columns (``decimal.Decimal``) come back as floats.
    """
    cur = conn.cursor()
    try:
        cur.execute(sql, tuple(params or ()))
        cols = [d[0] for d in (cur.description or [])]
        rows = cur.fetchall() if cur.description else []
    finally:
        try:
            cur.close()
        except Exception:
            pass
    return pd.DataFrame.from_records(rows, columns=cols, coerce_float=True)
