"""Research Notes: portfolio briefing prompt, dividend yield, same-sector alternatives, the notes
library, kv_keys, and the page (locked / unlocked briefing, library, Analyze Stock link)."""
from __future__ import annotations

import datetime as dt
import os
import socket
import time
from types import SimpleNamespace

import pytest
from streamlit.testing.v1 import AppTest

from analysis import research_notes as R

_PAGE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "dashboard", "pages",
                     "08_watchlist_journal.py")


def test_dividend_yield_from_fundamentals():
    cf = SimpleNamespace(latest_cashflow=lambda: SimpleNamespace(dividends_paid=-1_500.0),
                         ratios=SimpleNamespace(market_cap=50_000.0))
    assert R.dividend_yield_pct(cf) == 3.0
    missing = SimpleNamespace(latest_cashflow=lambda: None, ratios=SimpleNamespace(market_cap=1.0))
    assert R.dividend_yield_pct(missing) is None
    assert R.dividend_yield_pct(None) is None


def test_alternatives_same_sector_not_held_strongest_first():
    scored = {"NTPC.NS": {"sector": "Power", "score": 74, "action": "BUY", "price": 350, "sl": 330},
              "TATAPOWER.NS": {"sector": "Power", "score": 66},
              "WEAKCO.NS": {"sector": "Power", "score": 40},
              "PFC.NS": {"sector": "Power", "score": 80},
              "TCS.NS": {"sector": "IT", "score": 79}}
    alts = R.alternative_candidates(scored, held=["PFC"], sectors=["Power"])
    assert [a["ticker"] for a in alts] == ["NTPC", "TATAPOWER"]


def test_briefing_has_holdings_alternatives_notes_and_rules():
    holdings = [{"ticker": "PFC", "qty": 100, "avg": 400, "price": 420, "chg_pct": 1.2, "pnl_pct": 5.0,
                 "value": 42000, "sector": "Power", "score": 71, "action": "BUY", "div_yield": 3.4,
                 "roe": 19.5, "de": 6.2, "rev_cagr_3y": 12.0},
                {"ticker": "COALINDIA", "qty": 50, "avg": 380, "price": 378, "value": 18900, "sector": "Mining"}]
    text = R.build_portfolio_briefing(
        holdings, "Keep PFC and COALINDIA for dividends?",
        alternatives=[{"ticker": "NTPC", "sector": "Power", "score": 74, "action": "BUY", "price": 350, "sl": 330}],
        notes={"PFC": [{"generated_at": "2026-11-01T10:00", "doc_period_label": "FY25 AR",
                        "analysis_text": "Strong book, " * 200}]},
        today=dt.date(2026, 11, 17))
    assert "MY QUESTION: Keep PFC and COALINDIA for dividends?" in text
    assert "PFC · sector Power" in text and "dividend yield 3.40%" in text and "weight 69.0%" in text
    assert "COALINDIA" in text and "dividend yield n/a" in text
    assert "NTPC · Power · app score 74/90" in text and "stop ₹330.00" in text
    assert "PFC (2026-11-01, FY25 AR)" in text and "…" in text            # excerpted note
    assert "Every BUY or ADD needs an entry and a stop" in text and "Never promise returns" in text
    assert "1. Answer my question directly first." in text           # custom question -> generic format
    assert "guarantee" in text and "sure shot" not in text.lower()


def test_library_merges_and_filters():
    stock = {"PFC.NS": [{"generated_at": "2026-11-01T10:00:00", "doc_period_label": "FY25 AR",
                         "analysis_text": "a"}]}
    port = [R.new_portfolio_note("Dividend income check", "q", ["PFC", "COALINDIA.NS"], " ans ",
                                 now=dt.datetime(2026, 11, 17, 9, 0))]
    rows = R.library(stock, port)
    assert [r["kind"] for r in rows] == ["portfolio", "stock"]
    assert rows[0]["tickers"] == ["COALINDIA", "PFC"] and rows[0]["text"] == "ans"
    assert [r["kind"] for r in R.library(stock, port, ticker="COALINDIA")] == ["portfolio"]
    assert [r["kind"] for r in R.library(stock, port, ticker="PFC.NS")] == ["portfolio", "stock"]


def test_kv_keys_prefix_is_literal():
    import trade_store as store
    store.kv_set("deep_dive_history:PFC.NS", [1])
    store.kv_set("deep_dive_history:M&M.NS", [1])
    store.kv_set("deep_diveXhistory:NOPE", [1])                  # '_' must not act as a wildcard
    store.kv_set("deep_dive_history:OTHERUSER", [1], user_id="someone")
    assert store.kv_keys("deep_dive_history:") == ["deep_dive_history:M&M.NS", "deep_dive_history:PFC.NS"]


# ── page ─────────────────────────────────────────────────────────────────────

@pytest.fixture
def no_network(monkeypatch):
    def _blocked(*a, **k):
        raise OSError("network blocked")
    monkeypatch.setattr(socket.socket, "connect", _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)


def _rn_tab(at):
    return next(t for t in at.tabs if t.label == "📝 Research Notes")


def test_locked_briefing_and_library(no_network):
    import trade_store as store
    store.kv_set("deep_dive_history:PFC.NS", [{"generated_at": "2026-11-01T10:00:00",
                                               "doc_period_label": "FY25 AR", "analysis_text": "PFC note"}])
    store.kv_set("portfolio_briefing_history", [R.new_portfolio_note("Dividend income check", "q", ["PFC"], "Keep")])
    at = AppTest.from_file(_PAGE, default_timeout=120).run()
    assert not at.exception, [str(e.value) for e in at.exception]
    tab = _rn_tab(at)
    assert any("My Portfolio is locked" in str(c.value) for c in tab.caption)
    labels = [e.label for e in tab.expander]
    assert any("Portfolio · Dividend income check" in lb for lb in labels)
    assert any("PFC · FY25 AR" in lb for lb in labels)


def test_unlocked_builds_briefing_and_saves_answer(no_network):
    import trade_store as store
    store.kv_set("manual_portfolio_holdings", [{"ticker": "PFC.NS", "quantity": 100, "avg_buy_price": 400},
                                                {"ticker": "COALINDIA", "quantity": 50, "avg_buy_price": 380}])
    store.kv_delete("portfolio_briefing_history")
    at = AppTest.from_file(_PAGE, default_timeout=120)
    at.session_state["_pin_unlocked_at_my_portfolio"] = time.time()
    at.run()
    tab = _rn_tab(at)
    tab.button(key="rn_build").click().run()
    assert not at.exception, [str(e.value) for e in at.exception]
    prompt = at.session_state["rn_prompt"]
    assert "PFC · sector" in prompt and "COALINDIA" in prompt and "MY QUESTION:" in prompt
    tab = _rn_tab(at)
    tab.text_area(key="rn_answer").input("PFC: HOLD, stop ₹380").run()
    _rn_tab(at).button(key="rn_save_answer").click().run()
    saved = store.kv_get("portfolio_briefing_history", None)
    assert saved and saved[-1]["tickers"] == ["COALINDIA", "PFC"] and saved[-1]["answer"] == "PFC: HOLD, stop ₹380"


def test_analyze_stock_links_to_research_notes():
    src = open("dashboard/pages/05_analyze_stock.py", encoding="utf-8").read()
    assert 'st.session_state["rn_ticker"]' in src and '_nav_to_rn("Research Notes")' in src
    from dashboard.shared import nav
    assert nav.resolve_page("Research Notes")[0] == "Watchlist & Notes"
    assert nav.resolve_page("Watchlist & Journal")[0] == "Watchlist & Notes"


def test_technical_levels_from_daily_bars():
    import numpy as np
    import pandas as pd
    idx = pd.date_range("2025-10-01", periods=260, freq="B")
    c = pd.Series(np.linspace(100, 200, 260), index=idx)
    t = R.technical_levels(pd.DataFrame({"Close": c, "High": c + 2, "Low": c - 2}))
    assert t["bars"] == 260 and t["high_52w"] == 202 and round(t["low_52w"], 2) == round(c.iloc[-252] - 2, 2)
    assert t["sma50"] > t["sma200"] and 3.9 < t["atr14"] < 4.1 and t["ret_1m"] > 0
    short = R.technical_levels(pd.DataFrame({"Close": c[:60], "High": c[:60], "Low": c[:60]}))
    assert "sma200" not in short and "sma50" in short
    assert R.technical_levels(None) == {}


def test_holding_period_and_tax_side():
    today = dt.date(2026, 11, 16)
    assert R.holding_period("2024-03-01", today) == "bought 01 Mar 2024, held 2y 8m (long-term for tax)"
    assert "short-term for tax until 01 Jun 2027" in R.holding_period("2026-06-01", today)
    assert R.holding_period("", today) is None and R.holding_period("2027-01-01", today) is None


def test_price_note_open_vs_closed():
    assert "last closing prices" in R.price_note(dt.datetime(2026, 11, 16, 22, 10))
    assert "while the market was open" in R.price_note(dt.datetime(2026, 11, 16, 11, 0))
    assert "last closing prices" in R.price_note(dt.datetime(2026, 11, 15, 11, 0))     # Sunday


def test_briefing_sector_aware_flags_picks_and_fresh_money_format():
    rows = [{"ticker": "VEDL", "company": "Vedanta Ltd", "sector": "Metal", "qty": 100, "avg": 253, "price": 253,
             "value": 25300, "div_yield": 13.4, "rev_cagr_3y": -26.9, "de": 2.44, "pe": 10, "sl": 240,
             "tech": {"bars": 120, "last": 253, "high_52w": 300, "low_52w": 200, "atr14": 8}},
            {"ticker": "DHANBANK", "sector": "Banking", "qty": 3100, "avg": 11, "price": 42.8, "value": 132680,
             "de": 0.36, "pb": 1.2, "roe": 7.2},
            {"ticker": "BALRAMCHIN", "sector": "FMCG", "industry": "Sugar", "qty": 430, "avg": 83, "price": 650,
             "value": 279500}]
    text = R.build_portfolio_briefing(
        rows, R.QUESTION_PRESETS[R.FRESH_MONEY_KEY], question_key=R.FRESH_MONEY_KEY, fresh_money=200000,
        prices_note="Prices: taken at X", scan_note="App scores: from the app's scan at Y",
        top_picks=[{"ticker": "RELIANCE.NS", "sector": "Energy", "score": 76, "action": "BUY", "price": 1500,
                    "sl": 1440}, {"ticker": "VEDL.NS", "score": 70}], today=dt.date(2026, 11, 16))
    assert "Fresh money available to invest: ₹200,000" in text
    assert "Prices: taken at X" in text and "App scores: from the app's scan at Y" in text
    assert "VEDL (Vedanta Ltd)" in text and "app stop ₹240.00" in text and "debt/equity 2.44" in text
    assert "⚠ check: Vedanta demerged" in text and "13.4% trailing dividend yield is unusual" in text
    assert "only 120 trading days" in text and "52-week range ₹200.00–₹300.00" in text
    dhan = text.split("- DHANBANK")[1].split("\n- ")[0]
    assert "P/B 1.20" in dhan and "debt/equity is not meaningful" in dhan and "debt/equity 0.36" not in dhan
    assert "sector Sugar (app bucket FMCG)" in text
    assert "- RELIANCE · Energy · app score 76/90 (BUY)" in text and "- VEDL · " not in text.split("New names")[1]
    assert "1. Your top 3:" in text and "how much of the fresh money" in text
    assert "search the web" in text


def test_industry_hints():
    from data.universe import get_industry
    assert get_industry("BALRAMCHIN") == "Sugar" and get_industry("XCHANGING.NS") == "IT services"
    assert get_industry("TCS") is None


def test_briefing_uses_an_hours_old_scan(no_network, monkeypatch):
    """The evening briefing must still carry scores from the afternoon scan (was: all n/a)."""
    import trade_store as store
    from dashboard.views import research_notes as V
    old = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=7)).isoformat(timespec="seconds")
    store.kv_set("all_scored_snapshot", {"data": {"PFC.NS": {"score": 64, "action": "HOLD", "sl": 300,
                                                             "sector": "Finance", "price": 330}},
                                         "generated_at": old}, user_id="_system")
    store.kv_set("top_picks_snapshot", {"data": {"buys": [{"ticker": "NTPC.NS", "score": 75}]},
                                        "generated_at": old}, user_id="_system")
    g = V._gather_briefing([{"ticker": "PFC", "qty": 10, "avg": 400, "bought": "2025-01-01"}])
    assert g["rows"][0]["score"] == 64 and g["rows"][0]["sl"] == 300
    assert g["picks"][0]["ticker"] == "NTPC.NS" and "from the app's scan at" in g["scan_note"]
    store.kv_set("all_scored_snapshot", {"data": {"PFC.NS": {"score": 64}},
                                         "generated_at": "2020-01-01T00:00:00+00:00"}, user_id="_system")
    assert V._scan_snapshot("all_scored_snapshot") == ({}, "")
