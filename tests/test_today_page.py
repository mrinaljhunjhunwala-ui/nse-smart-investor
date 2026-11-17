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
    assert out[1]["details"] == ["#2 Reversal", "avg ₹410.00"]


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


def test_open_trades_line_entry_only():
    import pandas as pd
    from dashboard.shared.trade_utils import open_trades_line
    rows = pd.DataFrame([{"ticker": "TCS.NS", "quantity": 5, "price": 3000.0, "timestamp": "2026-11-12T10:00"},
                         {"ticker": "DHANBANK.NS", "quantity": 1086, "price": 42.84, "timestamp": "2026-11-10T10:00"}])
    txt, n = open_trades_line(rows)
    assert n == 2 and txt == "DHANBANK 1086 @ ₹42.84 · TCS 5 @ ₹3,000.00"
    assert "%" not in txt                                   # no P&L / win rate on Command Centre
    assert open_trades_line(pd.DataFrame()) == ("", 0)


def test_command_centre_keeps_scan_notes_in_data_health_only():
    src = open("dashboard/pages/01_command_centre.py", encoding="utf-8").read()
    picks = src[src.index("def _render_top_picks_section"):src.index("def _render_open_trades_line")]
    assert "st.caption(price_source_caption" not in picks and "st.caption(_cc_excl)" not in picks
    footer = src[src.index('with st.expander("Data health details"'):]
    assert "price_source_caption" in footer and "_cc_excluded_note" in footer
    assert src.index("_render_open_trades_line()") < src.index("_render_top_picks_section(_cc_vix_r")


def test_my_lists_unlocks_in_place(no_network, monkeypatch):
    """A locked list gets a PIN box right on Today; the right PIN unlocks My Portfolio there."""
    monkeypatch.setenv("ANGEL_PAGE_PIN", "4821")
    at = AppTest.from_file(_PAGE, default_timeout=120).run()
    assert not at.exception, [str(e.value) for e in at.exception]
    labels = [e.label for e in at.expander]
    assert any("Unlock My Portfolio" in lb for lb in labels) and any("Unlock Angel One" in lb for lb in labels)
    at.text_input(key="pin_inline_in_my_portfolio_today_lists").input("1111")
    at.button(key="FormSubmitter:pin_inline_my_portfolio_today_lists-Unlock").click().run()
    assert "_pin_unlocked_at_my_portfolio" not in at.session_state
    assert any("Wrong PIN" in str(e.value) for e in at.error)
    at.text_input(key="pin_inline_in_my_portfolio_today_lists").input("4821")
    at.button(key="FormSubmitter:pin_inline_my_portfolio_today_lists-Unlock").click().run()
    assert not at.exception, [str(e.value) for e in at.exception]
    assert "_pin_unlocked_at_my_portfolio" in at.session_state
    assert not any("Unlock My Portfolio" in e.label for e in at.expander)
    assert "_pin_unlocked_at_angel_one" not in at.session_state      # one PIN box unlocks one scope


def test_open_trades_summary_pnl_and_today():
    import pandas as pd
    from dashboard.shared.trade_utils import open_trades_summary
    rows = pd.DataFrame([
        {"ticker": "TCS.NS", "quantity": 10, "price": 3000.0, "action": "BUY", "timestamp": "2026-11-10T10:00"},
        {"ticker": "INFY.NS", "quantity": 5, "price": 1500.0, "action": "SELL", "timestamp": "2026-11-12T10:00"},
        {"ticker": "DHANBANK.NS", "quantity": 100, "price": 40.0, "action": "BUY", "timestamp": "2026-11-17T09:30"},
        {"ticker": "NOQUOTE.NS", "quantity": 1, "price": 10.0, "action": "BUY", "timestamp": "2026-11-11T10:00"}])
    quotes = {"TCS.NS": {"price": 3100.0, "prev_close": 3050.0},
              "INFY.NS": {"price": 1450.0, "prev_close": 1460.0},
              "DHANBANK": {"price": 42.0, "prev_close": 30.0}}
    sm = open_trades_summary(rows, quotes, today=dt.date(2026, 11, 17))
    by = {r["symbol"]: r for r in sm["rows"]}
    assert by["TCS"]["pnl"] == 1000 and round(by["TCS"]["pnl_pct"], 2) == 3.33 and by["TCS"]["day"] == 500
    assert by["INFY"]["pnl"] == 250 and by["INFY"]["side"] == "SHORT" and by["INFY"]["day"] == 50   # short gains on a fall
    assert by["DHANBANK"]["day"] == 200                    # opened today: measured from entry, not prev close
    assert by["NOQUOTE"]["pnl"] is None and sm["n_unpriced"] == 1
    assert sm["n"] == 4 and sm["pnl"] == 1450 and sm["day"] == 750
    assert round(sm["pnl_pct"], 3) == round(1450 / (30000 + 7500 + 4000) * 100, 3)
    empty = open_trades_summary(pd.DataFrame(), {})
    assert empty["n"] == 0 and empty["pnl"] is None and empty["day"] is None



def test_changes_tab_shows_the_eod_check(no_network):
    import trade_store as store
    day = dt.datetime.now(IST).date().isoformat()
    store.kv_set(f"eod_scorecard:{day}", {
        "date": day, "nifty_pct": 0.4,
        "summary": {"n": 1, "up": 1, "avg_pct": 3.0, "avg_vs_nifty": 2.6, "beat_nifty": 1,
                    "stops_hit": 0, "targets_hit": 0, "nifty_pct": 0.4},
        "calls": [{"symbol": "SGMART", "group": "digest", "when": "08:43", "entry": 983.4, "close": 1013.35,
                   "pct": 3.05, "vs_nifty": 2.65, "best_pct": 3.9, "worst_pct": -0.7,
                   "stop_hit": False, "target_hit": False}],
        "levels": [{"symbol": "DHANBANK", "up": 43.65, "down": 41.35, "next_up": 47.11, "close": 43.19,
                    "broke_up": True, "reached_next": False, "broke_down": True, "closed": "inside"}]},
        user_id="_system")
    at = AppTest.from_file(_PAGE, default_timeout=120).run()
    assert not at.exception, [str(e.value) for e in at.exception]
    text = " ".join(str(m.value) for m in at.markdown) + " ".join(str(c.value) for c in at.caption)
    assert "end-of-day check" in text and "1 call · 1 up" in text and "broke ▲ ₹43.65" in text
    assert any("SGMART" in df.value.to_string() for df in at.dataframe)
