"""Audit 2026-11: paper-trade fills and P&L shown on Paper Trades."""
import datetime as dt

import pandas as pd

from dashboard.shared import trade_utils as tu

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))


def test_todays_pnl_for_a_position_bought_today_starts_at_entry():
    today = dt.date(2026, 11, 17)
    # prev close 950, bought at 1000 today, now 1005: today's P&L is +5/share, not +55
    assert tu.day_pnl(1000, 1005, 950, 10, "2026-11-17T11:00:00", today=today) == 50
    assert tu.day_pnl(1000, 1005, 950, 10, "2026-11-10T11:00:00", today=today) == 550
    assert tu.day_pnl(1000, 1005, None, 10, "2026-11-10", today=today) == 0


def test_squareoff_window_ends_at_the_close(monkeypatch):
    for hhmm, want in (((15, 10), False), ((15, 15), True), ((15, 30), True), ((20, 0), False)):
        monkeypatch.setattr(tu, "_ist_now", lambda h=hhmm: dt.datetime(2026, 11, 17, *h, tzinfo=IST))
        assert tu._is_squareoff_time() is want, hhmm      # 20:00 used to be True


def test_stop_gapped_through_fills_at_the_market(monkeypatch):
    rows = pd.DataFrame([{"id": 1, "ticker": "ABC.NS", "price": 100, "quantity": 10, "sl": 95, "tp": 120,
                          "account": "My Account"}])
    closed = {}
    monkeypatch.setattr(tu, "_is_market_open", lambda: True)
    monkeypatch.setattr(tu, "_is_squareoff_time", lambda: False)
    monkeypatch.setattr(tu, "_ist_now", lambda: dt.datetime(2026, 11, 17, 9, 20, tzinfo=IST))
    monkeypatch.setattr(tu._store, "fetch_open", lambda account=None: rows)
    monkeypatch.setattr(tu, "_portfolio_live_prices", lambda syms: {"ABC.NS": {"price": 85.0}})
    monkeypatch.setattr(tu, "paper_account_type", lambda a: "CNC")
    monkeypatch.setattr(tu, "paper_close_trade", lambda tid, px, why: closed.update({tid: px}))
    out = tu._auto_close_breached()
    assert closed == {1: 85.0} and out[0]["pnl"] == -150      # was filled at the ₹95 stop (-50)


def test_win_rate_and_insights_use_net_pnl():
    df = pd.DataFrame({"pnl": [10.0, 200.0, -50.0], "charges": [20.0, 20.0, 20.0]})
    net = tu._net_closed_pnl(df)
    assert list(net) == [-10.0, 180.0, -70.0] and int((net > 0).sum()) == 1
    assert tu._net_closed_pnl(pd.DataFrame()).empty


def _monitor_app(toggle):
    import streamlit as st
    from dashboard.shared import market_hours, squareoff_monitor as sm, trade_utils
    market_hours.is_market_open = lambda: True
    market_hours.is_squareoff_window = lambda: False
    trade_utils._auto_close_breached = lambda account=None: st.session_state.setdefault("calls", []).append(1) or []
    st.session_state["auto_close_on"] = toggle
    sm.render_squareoff_monitor(show_badge=False)


def test_my_portfolio_monitor_respects_the_auto_close_toggle(monkeypatch):
    from streamlit.testing.v1 import AppTest
    from dashboard.shared import market_hours
    for name in ("is_market_open", "is_squareoff_window"):
        monkeypatch.setattr(market_hours, name, getattr(market_hours, name))
    monkeypatch.setattr(tu, "_auto_close_breached", tu._auto_close_breached)
    off = AppTest.from_function(_monitor_app, args=(False,)).run()
    assert not off.exception and "calls" not in off.session_state    # closed trades with the toggle off
    on = AppTest.from_function(_monitor_app, args=(True,)).run()
    assert not on.exception and on.session_state["calls"] == [1]
