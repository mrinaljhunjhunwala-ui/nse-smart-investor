"""
check_universe_drift() must read the same store the F&O bhavcopy fetcher
writes to (trade_store._get_conn → Postgres or trade_store._SQLITE_PATH).
It used to open ./trades.db directly, so on a Postgres deployment — or any
run where _SQLITE_PATH isn't ./trades.db — it always saw an empty table.
"""
from __future__ import annotations

import os
import sqlite3
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import trade_store  # noqa: E402
from data import fno_universe  # noqa: E402
from data.nse_fno_bhavcopy import ensure_schema  # noqa: E402


def _insert(rows):
    ensure_schema()
    with sqlite3.connect(trade_store._SQLITE_PATH) as con:
        con.executemany(
            "INSERT INTO nse_fno_oi_daily (symbol, date, total_oi, n_contracts) VALUES (?,?,?,?)",
            [(s, d, 1.0, 1) for s, d in rows],
        )


def test_empty_store_returns_empty_result():
    got = fno_universe.check_universe_drift()
    assert got == {"db_date": None, "db_count": 0, "stale": set(), "missing": set()}


def test_reads_trade_store_path_not_cwd_trades_db(monkeypatch, tmp_path):
    # A decoy ./trades.db with different data must be ignored.
    cwd = tmp_path / "elsewhere"
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    with sqlite3.connect("trades.db") as decoy:
        decoy.execute("CREATE TABLE nse_fno_oi_daily (symbol TEXT, date TEXT)")
        decoy.execute("INSERT INTO nse_fno_oi_daily VALUES ('DECOY', '2026-12-31')")
    assert os.path.abspath("trades.db") != os.path.abspath(trade_store._SQLITE_PATH)
    static = sorted(fno_universe._FNO_TICKERS)
    kept, dropped = static[:-1], static[-1]
    _insert([(s, "2026-09-25", ) for s in kept] + [("NEWFNO", "2026-09-25")]
            + [("OLDDAY", "2026-09-24")])

    got = fno_universe.check_universe_drift()

    assert got["db_date"] == "2026-09-25"          # latest date picked
    assert got["db_count"] == len(kept) + 1
    assert got["stale"] == {dropped}
    assert got["missing"] == {"NEWFNO"}


def test_explicit_date():
    _insert([("OLDDAY", "2026-09-24"), ("NEWDAY", "2026-09-25")])
    got = fno_universe.check_universe_drift(date="2026-09-24")
    assert got["db_date"] == "2026-09-24"
    assert got["missing"] == {"OLDDAY"}
