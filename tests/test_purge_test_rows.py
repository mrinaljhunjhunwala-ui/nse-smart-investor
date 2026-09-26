"""tests/test_purge_test_rows.py — tools/purge_test_rows.py against a tmp SQLite.

conftest.py points trade_store at a per-test SQLite file, so these seed real
and fixture rows there and check the tool deletes only the fixture ones.
"""
from __future__ import annotations

import pytest

import trade_store
from analysis.final_verdict import combine
from analysis.verdict_ledger import ensure_schema as ledger_schema, load_ledger, log_verdict
from tools import purge_test_rows as purge


@pytest.mark.parametrize("ticker,expected", [
    ("FAKE1.NS", True), ("fake2.bo", True), ("TEST.NS", True), ("DUMMY", True), ("MOCK9.NS", True),
    ("RELIANCE.NS", False), ("TESTBED.NS", False), ("FAKEX.NS", False),
    ("JUBLFOOD.NS", False), ("", False), (None, False),
])
def test_is_test_ticker(ticker, expected):
    assert purge.is_test_ticker(ticker) is expected


def _seed():
    ledger_schema()
    for tk, px in (("FAKE1.NS", 100.0), ("RELIANCE.NS", 2900.0)):
        log_verdict(ticker=tk, final_verdict=combine(composite_score=70.0, composite_action="BUY"),
                    entry_price=px, composite_score=70.0, source="tomorrow_watchlist",
                    signal_tags=["tech_high"])
    trade_store.open_trade("FAKE1.NS", price=100.0, qty=1, sl=95.0, tp=110.0, account="UT")
    trade_store.open_trade("TCS.NS", price=4000.0, qty=1, sl=3900.0, tp=4200.0, account="MJ")
    trade_store.kv_set("qualitative_flags:FAKE1.NS", [{"ticker": "FAKE1.NS"}])
    trade_store.kv_set("qualitative_flags:INFY.NS", [{"ticker": "INFY.NS"}])
    trade_store.kv_set("watchlist", ["TCS.NS", "FAKE1.NS"])  # mixed blob → review only


def _scan():
    with trade_store._get_conn() as conn:
        return purge.find_test_rows(conn.cursor(), trade_store)


def test_dry_run_reports_but_deletes_nothing(capsys):
    _seed()
    plan = _scan()
    assert [r[2] for r in plan["verdict_log"]] == ["FAKE1.NS"]
    assert [r[1] for r in plan["verdict_signal_tags"]] == ["tech_high"]
    assert [r[2] for r in plan["trades"]] == ["FAKE1.NS"]
    assert plan["user_kv"] == [("default", "qualitative_flags:FAKE1.NS")]
    assert [r[1] for r in plan["user_kv_values_review"]] == ["watchlist"]

    assert purge.main([]) == 0
    out = capsys.readouterr().out
    assert "DRY RUN" in out and "Total rows that --apply would delete: 4" in out
    assert _scan() == plan  # untouched


def test_apply_deletes_only_fixture_rows():
    _seed()
    assert purge.main(["--apply"]) == 0

    after = _scan()
    assert all(not after[k] for k in ("verdict_log", "verdict_signal_tags", "trades", "user_kv"))
    assert sorted(load_ledger()["ticker"]) == ["RELIANCE.NS"]
    assert list(trade_store.load_by_account("MJ")["ticker"]) == ["TCS.NS"]
    assert trade_store.kv_get("qualitative_flags:INFY.NS") == [{"ticker": "INFY.NS"}]
    assert trade_store.kv_get("watchlist") == ["TCS.NS", "FAKE1.NS"]  # never auto-edited


def test_empty_database_is_a_noop():
    assert purge.main(["--apply"]) == 0
