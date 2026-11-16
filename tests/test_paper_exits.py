"""Paper-trade catch-up exits: trades whose SL / TP was touched while the app
wasn't watching must close (and show in Closed Trade History) on next load."""
from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest

from trading.paper_exits import (
    REASON_GAP_STOP, REASON_GAP_TARGET, REASON_MIS, REASON_STOP, REASON_TARGET, find_exit,
)


def _bars(rows):
    """rows: list of (date, open, high, low, close)."""
    idx = pd.to_datetime([r[0] for r in rows])
    return pd.DataFrame(
        {"Open": [r[1] for r in rows], "High": [r[2] for r in rows],
         "Low": [r[3] for r in rows], "Close": [r[4] for r in rows]},
        index=idx,
    )


ENTRY = "2026-11-09T10:15:00"


def test_target_touched_then_pulled_back_closes_at_target():
    bars = _bars([
        ("2026-11-09", 100, 120, 90, 101),   # entry day: ignored (pre-entry prices mixed in)
        ("2026-11-10", 101, 104, 99, 103),
        ("2026-11-11", 103, 111, 102, 104),  # high touches TP 110, closes back at 104
        ("2026-11-12", 104, 105, 92, 93),
    ])
    hit = find_exit(bars, ENTRY, sl=95, tp=110)
    assert hit == {"exit_price": 110.0, "exit_date": dt.date(2026, 11, 11), "reason": REASON_TARGET}


def test_stop_hit_closes_at_stop():
    bars = _bars([("2026-11-10", 100, 101, 94, 96)])
    hit = find_exit(bars, ENTRY, sl=95, tp=110)
    assert hit["exit_price"] == 95.0 and hit["reason"] == REASON_STOP


def test_both_on_same_day_assumes_the_worse_fill():
    bars = _bars([("2026-11-10", 100, 112, 94, 100)])
    assert find_exit(bars, ENTRY, sl=95, tp=110)["reason"] == REASON_STOP


def test_gaps_fill_at_open():
    down = find_exit(_bars([("2026-11-10", 90, 92, 88, 91)]), ENTRY, sl=95, tp=110)
    assert down == {"exit_price": 90.0, "exit_date": dt.date(2026, 11, 10), "reason": REASON_GAP_STOP}
    up = find_exit(_bars([("2026-11-10", 115, 116, 113, 114)]), ENTRY, sl=95, tp=110)
    assert up["exit_price"] == 115.0 and up["reason"] == REASON_GAP_TARGET


def test_untouched_trade_stays_open_and_entry_day_is_ignored():
    bars = _bars([
        ("2026-11-09", 100, 130, 80, 100),   # entry day extremes must not count
        ("2026-11-10", 100, 105, 97, 103),
    ])
    assert find_exit(bars, ENTRY, sl=95, tp=110) is None


def test_short_side_mirrors():
    bars = _bars([("2026-11-10", 100, 101, 89, 90)])
    hit = find_exit(bars, ENTRY, sl=105, tp=90, action="SELL")
    assert hit["exit_price"] == 90.0 and hit["reason"] == REASON_TARGET


def test_mis_squared_off_at_entry_session_close_once_over():
    bars = _bars([("2026-11-09", 100, 103, 98, 102.5), ("2026-11-10", 102, 104, 101, 103)])
    hit = find_exit(bars, ENTRY, sl=95, tp=110, product="MIS", today=dt.date(2026, 11, 10))
    assert hit == {"exit_price": 102.5, "exit_date": dt.date(2026, 11, 9), "reason": REASON_MIS}
    assert find_exit(bars, ENTRY, sl=95, tp=110, product="MIS", today=dt.date(2026, 11, 9)) is None


def test_bad_inputs_return_none():
    assert find_exit(None, ENTRY, 95, 110) is None
    assert find_exit(pd.DataFrame(), ENTRY, 95, 110) is None
    assert find_exit(_bars([("2026-11-10", 100, 101, 94, 96)]), None, 95, 110) is None
    assert find_exit(_bars([("2026-11-10", 100, 101, 94, 96)]), ENTRY, None, 0) is None


# ── store + reconcile ───────────────────────────────────────────────────────

@pytest.fixture
def store(tmp_path, monkeypatch):
    import trade_store
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(trade_store, "_SQLITE_PATH", str(tmp_path / "pt.db"))
    trade_store.ensure_schema()
    return trade_store


def test_close_trade_only_closes_open_rows_and_keeps_exit_time(store):
    tid = store.open_trade("RELIANCE.NS", 100.0, 10, 95.0, 110.0, account="UT")
    assert store.close_trade(tid, 110.0, "first", exit_time="2026-11-11T15:30:00") is True
    assert store.close_trade(tid, 50.0, "second click") is False   # must not overwrite
    row = store.load_by_account("UT").iloc[0]
    assert row["status"] == "CLOSED" and row["exit_price"] == 110.0
    assert row["exit_reason"] == "first" and row["exit_time"].startswith("2026-11-11")
    assert row["pnl"] == pytest.approx(100.0)


def test_reconcile_closes_hit_trades_and_leaves_others_open(store, monkeypatch):
    from dashboard.shared import trade_utils as tu

    hit_id = store.open_trade("AAA.NS", 100.0, 10, 95.0, 110.0, account="UT")
    open_id = store.open_trade("BBB.NS", 100.0, 10, 95.0, 110.0, account="UT")
    entry = pd.Timestamp(store.load_by_account("UT").iloc[0]["timestamp"]).normalize()
    next_day = (entry + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    frames = {
        "AAA.NS": _bars([(next_day, 101, 112, 100, 104)]),   # touched TP
        "BBB.NS": _bars([(next_day, 101, 104, 99, 103)]),    # untouched
    }
    monkeypatch.setattr(tu, "paper_account_type", lambda name: "CNC")
    done = tu.reconcile_paper_exits(account="UT", history_fn=frames.get)

    assert [d["ticker"] for d in done] == ["AAA"]
    df = store.load_by_account("UT").set_index("id")
    assert df.loc[hit_id, "status"] == "CLOSED" and df.loc[hit_id, "exit_price"] == 110.0
    assert df.loc[hit_id, "exit_time"].startswith(next_day)
    assert df.loc[open_id, "status"] == "OPEN"
    # Second pass is a no-op (already closed, other still untouched).
    assert tu.reconcile_paper_exits(account="UT", history_fn=frames.get) == []


def test_reconcile_survives_missing_history(store, monkeypatch):
    from dashboard.shared import trade_utils as tu
    store.open_trade("CCC.NS", 100.0, 10, 95.0, 110.0, account="UT")
    monkeypatch.setattr(tu, "paper_account_type", lambda name: "CNC")

    def boom(_tk):
        raise OSError("network blocked")
    assert tu.reconcile_paper_exits(account="UT", history_fn=boom) == []
    assert tu.reconcile_paper_exits(account="UT", history_fn=lambda tk: None) == []
