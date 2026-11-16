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
    assert "Every BUY or ADD needs a stop" in text and "Never promise returns" in text
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
    assert any("Unlock **My Portfolio**" in str(i.value) for i in tab.info)
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
