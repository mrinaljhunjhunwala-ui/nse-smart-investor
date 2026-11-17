"""Batch B audit fixes: TQS custom tickers get .NS, the Tomorrow's Watchlist
message skips NSE holidays, and the Position Sizer warns when the minimum
lot is over the risk budget."""
from __future__ import annotations

import datetime
import os

import pytest

from dashboard.shared.deeplink import parse_ticker_list


def test_tqs_custom_list_adds_ns_to_bare_symbols():
    raw = "reliance, TCS.NS\nINFY.BO, ^NSEI,, reliance"
    assert parse_ticker_list(raw) == ["RELIANCE.NS", "TCS.NS", "INFY.BO", "^NSEI"]
    assert parse_ticker_list("") == []


@pytest.fixture
def tomorrow_env(monkeypatch):
    import alerts.check_alerts as ca
    import trade_store

    gen = datetime.datetime.now(datetime.timezone.utc).isoformat()
    item = {"ticker": "B.NS", "score": 70, "entry": 100.0, "sl": 94.0, "signal_type": "x"}
    snap = {"generated_at": gen,
            "data": {"breakout_candidates": [item], "reversal_watch": []}}
    monkeypatch.setattr(trade_store, "kv_get", lambda *a, **k: snap)
    sent: list[str] = []
    monkeypatch.setattr(ca, "dispatch", lambda msg, **k: sent.append(msg) or True)
    return ca, sent


def test_tomorrow_watchlist_skips_nse_holiday(tomorrow_env):
    ca, sent = tomorrow_env
    state: dict = {}
    assert ca.check_tomorrow_watchlist(state, "2026-01-26") == 0   # Republic Day, a Monday
    assert sent == []


def test_tomorrow_watchlist_sends_on_trading_day(tomorrow_env):
    ca, sent = tomorrow_env
    assert ca.check_tomorrow_watchlist({}, "2026-11-17") == 1
    assert len(sent) == 1 and "B" in sent[0]


@pytest.mark.smoke
@pytest.mark.parametrize("lot,warn", [(1, False), (500, True)])
def test_position_sizer_warns_when_one_lot_is_over_budget(lot, warn):
    from streamlit.testing.v1 import AppTest

    pages = os.path.join(os.path.dirname(__file__), "..", "dashboard", "pages")
    at = AppTest.from_file(os.path.join(pages, "13_trading_tools.py"), default_timeout=240)
    at.session_state["tt_view"] = "📐 Position Sizer"
    at.session_state["ps_cap"] = 500_000
    at.session_state["ps_risk_pct"] = 1.0
    at.session_state["ps_entry"] = 1000.0
    at.session_state["ps_sl"] = 980.0          # ₹20/share; budget ₹5,000 → 250 shares
    at.session_state["ps_tp"] = 1040.0
    at.session_state["ps_lot"] = lot
    at.run()
    assert not at.exception, at.exception
    hit = any("above your" in w.value for w in at.warning)
    assert hit is warn
