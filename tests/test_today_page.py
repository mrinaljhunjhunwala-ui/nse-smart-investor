"""Today page: every tab renders real content from stored scans, the alert log, and the pure
helpers behind it (list moves, sectors, cap-size gainers / losers, the scrolling line)."""
from __future__ import annotations

import datetime as dt
import os
import socket

import pytest
from streamlit.testing.v1 import AppTest

from analysis import movers as M

_PAGE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "dashboard", "pages",
                     "02_today.py")
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))


# ── pure helpers ────────────────────────────────────────────────────────────

def test_gainers_and_losers_no_backfill():
    rows = [("A", 10, 3.0), ("B", 10, -2.0), ("C", 10, 1.0), ("D", 10, -4.0), ("E", 10, 0.0)]
    up, down = M.gainers_and_losers(rows, n=5)
    assert [r[0] for r in up] == ["A", "C"] and [r[0] for r in down] == ["D", "B"]


def test_list_moves_joins_sources_and_filters():
    sources = {"Tomorrow's Watchlist": {"DHANBANK.NS": "#14 Breakout", "PFC": "#2 Reversal"},
               "My Portfolio": {"PFC": "avg ₹410.00"}, "Angel One": {"COALINDIA": "qty 50"}}
    quotes = {"DHANBANK": {"price": 42.8, "chg_pct": 6.5}, "PFC.NS": {"price": 401, "chg_pct": -1.6},
              "COALINDIA": {"price": 380, "chg_pct": 0.4}}
    out = M.list_moves(sources, quotes, threshold_pct=1.5)
    assert [r["symbol"] for r in out] == ["DHANBANK", "PFC"]
    assert out[1]["sources"] == ["Tomorrow's Watchlist", "My Portfolio"]
    assert "My Portfolio: avg ₹410.00" in out[1]["details"]


def test_sector_and_band_moves():
    scored = {f"S{i}.NS": {"ticker": f"S{i}.NS", "sector": "Bank" if i < 4 else "Pharma",
                           "return_1d": (i - 2.0), "price": 100} for i in range(8)}
    sec = M.sector_moves(scored)
    assert sec[0]["sector"] == "Pharma" and sec[-1]["sector"] == "Bank"
    gl = M.band_gainers_losers(scored, {"S7": "Large"}, n=2)
    assert gl["Large"][0][0]["symbol"] == "S7"
    assert [r["symbol"] for r in gl["Micro"][1]] == ["S0", "S1"]


def test_ticker_tape_is_nifty50_gainers_then_losers(monkeypatch):
    import utils.live_price as lp
    from dashboard.shared import chart_helpers as ch
    monkeypatch.setattr(lp, "get_live_prices_batch", lambda names, max_workers=12: {
        "RELIANCE.NS": {"price": 1500, "chg_pct": 2.0}, "TCS.NS": {"price": 3000, "chg_pct": -1.0},
        "ITC.NS": {"price": 295, "chg_pct": 3.5}})
    ch._ticker_tape_data.clear()
    out = ch._ticker_tape_data()
    assert [(k, s) for k, s, _, _ in out] == [("gainer", "ITC"), ("gainer", "RELIANCE"), ("loser", "TCS")]
    ch._ticker_tape_data.clear()


# ── alert log ───────────────────────────────────────────────────────────────

def test_dispatch_logs_sent_alerts(monkeypatch):
    import alerts.check_alerts as ca
    import trade_store as store
    monkeypatch.setattr(ca, "send_telegram", lambda msg: True)
    monkeypatch.setattr(ca, "send_gmail", lambda subj, msg: False)
    assert ca.dispatch("📡 <b>Movers radar</b> · 11:00\n▲ <b>A&amp;B</b> +5%", subject="Movers radar")
    log = store.kv_get(f"alerts_sent:{dt.datetime.now(IST):%Y-%m-%d}", None, user_id="_system")
    assert log[-1]["text"].startswith("📡 Movers radar") and "A&B" in log[-1]["text"]
    monkeypatch.setattr(ca, "send_telegram", lambda msg: False)
    n = len(log)
    assert not ca.dispatch("nope")
    assert len(store.kv_get(f"alerts_sent:{dt.datetime.now(IST):%Y-%m-%d}", None, user_id="_system")) == n


# ── page render with data ───────────────────────────────────────────────────

@pytest.fixture
def no_network(monkeypatch):
    def _blocked(*a, **k):
        raise OSError("network blocked")
    monkeypatch.setattr(socket.socket, "connect", _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)


def test_today_page_tabs_render_stored_data(no_network):
    import trade_store as store
    now = dt.datetime.now(IST)
    gen = now.replace(tzinfo=None).isoformat(timespec="seconds")
    scored = {f"{s}.NS": {"ticker": f"{s}.NS", "sector": sec, "return_1d": r, "price": 100.0, "score": 60}
              for s, sec, r in [("RELIANCE", "Energy", 2.1), ("ONGC", "Energy", 1.0), ("BPCL", "Energy", 0.5),
                                ("SUNPHARMA", "Pharma", -2.0), ("CIPLA", "Pharma", -1.5), ("LUPIN", "Pharma", -1.0)]}
    store.kv_set("all_scored_snapshot", {"data": scored, "generated_at": gen}, user_id="_system")
    store.kv_set("top_picks_snapshot", {"data": {"buys": [
        {"ticker": "RELIANCE.NS", "score": 76, "price": 1500, "sl": 1440, "tp": 1620}], "sells": []},
        "generated_at": gen}, user_id="_system")
    store.kv_set("tomorrow_watchlist_snapshot", {"data": {"breakout_candidates": [{"ticker": "DHANBANK.NS"}]},
                                                 "generated_at": gen}, user_id="_system")
    store.kv_set(f"movers_radar:{now:%Y-%m-%d}", [{"time": "11:00", "symbol": "DHANBANK", "pct": 6.5,
                                                   "price": 42.8, "band": "Micro",
                                                   "watchlist": ["Breakout", 14, 1], "why": ["2.1x normal volume"]}],
                 user_id="_system")
    store.kv_set(f"alerts_sent:{now:%Y-%m-%d}", [{"time": "11:00", "subject": "Movers radar", "text": "▲ DHANBANK"}],
                 user_id="_system")
    at = AppTest.from_file(_PAGE, default_timeout=120)
    at.run()
    assert not at.exception, [str(e.value) for e in at.exception]
    text = " ".join(str(m.value) for m in at.markdown) + " ".join(str(c.value) for c in at.caption)
    assert "Sectors" in text and "By market cap" in text and "Movers radar" in text
    assert "Today's 1 Top Picks" in text
    assert "My Portfolio is locked" in text and "Angel One is locked" in text
    assert any("Movers radar" in e.label for e in at.expander)
    frames = [df.value for df in at.dataframe]
    assert any("DHANBANK" in df.to_string() for df in frames)          # radar list
    assert any("RELIANCE" in df.to_string() for df in frames)          # picks / cap tables
