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
    wl = []
    assert W.add_row(wl, "infy.ns", "watch results", 1800.0, None)
    assert W.add_row(wl, "INFY.NS")                     # no duplicate
    W.add_row(wl, "TCS.NS")
    assert wl == ["INFY.NS", "TCS.NS"] and kv[W.WL_KV_KEY]
    df = W.load_rows(wl)
    assert list(df["ticker"]) == ["TCS.NS", "INFY.NS"]
    W.remove_row(wl, "INFY.NS")
    assert wl == ["TCS.NS"] and list(W.load_rows(wl)["ticker"]) == ["TCS.NS"]


def test_one_list_with_the_sidebar(monkeypatch):
    """Owner, 17 Nov: the sidebar watchlist and this page were two lists. Now one: the sidebar's."""
    import trade_store
    kv = {}
    monkeypatch.setattr(trade_store, "kv_get", lambda k, d=None, user_id="default": kv.get(k, d))
    monkeypatch.setattr(trade_store, "kv_set", lambda k, v, user_id="default": kv.__setitem__(k, v) or True)
    monkeypatch.setattr(W, "_legacy_rows", lambda: [])
    kv[W.WL_KV_KEY] = [{"ticker": "PFC.NS", "notes": "dividend", "added_at": "2026-10-01"}]
    sidebar = ["RELIANCE.NS", "TCS.NS"]                 # added from the sidebar / Analyze Stock
    W.merge_into(sidebar)
    assert sidebar == ["RELIANCE.NS", "TCS.NS", "PFC.NS"]          # page-only stock joins the list
    df = W.load_rows(sidebar)
    assert set(df["ticker"]) == {"RELIANCE.NS", "TCS.NS", "PFC.NS"}
    assert df.set_index("ticker").loc["PFC.NS", "notes"] == "dividend"
    W.remove_row(sidebar, "PFC.NS")                     # removed anywhere -> gone, details too
    W.merge_into(sidebar)
    assert "PFC.NS" not in sidebar
    full = [f"S{i}.NS" for i in range(W.WL_MAX)]
    assert W.add_row(full, "NEW.NS") is False and len(full) == W.WL_MAX


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
    assert list(W.details()) == ["PFC.NS"] and kv[W.WL_KV_KEY][0]["notes"] == "dividend"


def test_view_no_longer_writes_a_private_sqlite_file():
    src = open("dashboard/views/my_watchlist.py", encoding="utf-8").read()
    assert "INSERT OR IGNORE INTO watchlist" not in src and "_wl_con" not in src


def test_preopen_scan_moves_are_labelled_previous_session():
    from utils.snapshot_time import scan_move_caption
    assert scan_move_caption("2026-11-17T03:15:00+00:00").startswith("Previous session's move")   # 08:45 IST
    assert scan_move_caption("2026-11-17T04:50:00+00:00").startswith("Day's move")                # 10:20 IST
    assert scan_move_caption("2026-11-14T03:15:00+00:00").startswith("Day's move")                # Saturday
    assert scan_move_caption(None) == ""
