"""Audit 2026-11: My Watchlist lived in a local sqlite file trade_store never sees, so it was wiped
on every Streamlit Cloud redeploy even with Postgres configured."""
import sqlite3

from dashboard.views import my_watchlist as W


def test_rows_persist_through_trade_store(monkeypatch):
    import trade_store
    kv = {}
    monkeypatch.setattr(trade_store, "kv_get", lambda k, d=None, user_id="default": kv.get(k, d))
    monkeypatch.setattr(trade_store, "kv_set", lambda k, v, user_id="default": kv.__setitem__(k, v) or True)
    monkeypatch.setattr(W, "_legacy_rows", lambda: [])
    assert W.add_row("infy.ns", "watch results", 1800.0, None)
    assert W.add_row("INFY.NS")                         # no duplicate
    W.add_row("TCS.NS")
    df = W.load_rows()
    assert sorted(df["ticker"]) == ["INFY.NS", "TCS.NS"] and kv[W.WL_KV_KEY]
    W.remove_row("INFY.NS")
    assert list(W.load_rows()["ticker"]) == ["TCS.NS"]


def test_old_local_rows_are_imported_once(monkeypatch, tmp_path):
    import trade_store
    kv = {}
    monkeypatch.setattr(trade_store, "kv_get", lambda k, d=None, user_id="default": kv.get(k, d))
    monkeypatch.setattr(trade_store, "kv_set", lambda k, v, user_id="default": kv.__setitem__(k, v) or True)
    db = tmp_path / "paper_trades.db"
    with sqlite3.connect(db) as con:
        con.execute("CREATE TABLE watchlist (id INTEGER PRIMARY KEY, ticker TEXT, notes TEXT, added_at TEXT,"
                    " target_price REAL, alert_sl REAL)")
        con.execute("INSERT INTO watchlist(ticker, notes, added_at) VALUES ('PFC.NS', 'dividend', '2026-10-01')")
    monkeypatch.setattr(W, "_LEGACY_DB", str(db))
    assert list(W.load_rows()["ticker"]) == ["PFC.NS"] and kv[W.WL_KV_KEY][0]["notes"] == "dividend"


def test_view_no_longer_writes_a_private_sqlite_file():
    src = open("dashboard/views/my_watchlist.py", encoding="utf-8").read()
    assert "INSERT OR IGNORE INTO watchlist" not in src and "_wl_con" not in src


def test_preopen_scan_moves_are_labelled_previous_session():
    from utils.snapshot_time import scan_move_caption
    assert scan_move_caption("2026-11-17T03:15:00+00:00").startswith("Previous session's move")   # 08:45 IST
    assert scan_move_caption("2026-11-17T04:50:00+00:00").startswith("Day's move")                # 10:20 IST
    assert scan_move_caption("2026-11-14T03:15:00+00:00").startswith("Day's move")                # Saturday
    assert scan_move_caption(None) == ""
