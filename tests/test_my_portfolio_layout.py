"""My Portfolio (mockup artboard 04): with holdings present, the page renders
the KPI row, the posture strip, sector allocation bars beside the holdings
table, and ONE selected holding card instead of a card per holding.

Holdings, live prices and PortfolioManager are stubbed; network is blocked.
"""
import os
import socket

import pytest
from streamlit.testing.v1 import AppTest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PAGE = os.path.join(_ROOT, "dashboard", "pages", "03_my_portfolio.py")

_HOLDINGS = [
    {"ticker": "AAA", "quantity": 10, "avg_buy_price": 100.0, "date_bought": "2026-01-02"},
    {"ticker": "BBB", "quantity": 5, "avg_buy_price": 400.0, "date_bought": "2026-02-03"},
    {"ticker": "CCC", "quantity": 20, "avg_buy_price": 50.0, "date_bought": "2026-03-04"},
]


def _summary():
    from analysis.portfolio_manager import (
        HoldingResult, PortfolioDiversification, PortfolioSummary,
    )

    def _h(tk, qty, avg, cur, action, sector, score):
        inv, val = qty * avg, qty * cur
        return HoldingResult(
            ticker=f"{tk}.NS", quantity=qty, avg_buy_price=avg, date_bought="2026-01-02",
            current_price=cur, invested=inv, current_value=val, pnl=val - inv,
            pnl_pct=(val / inv - 1) * 100, today_chg_pct=0.5, days_held=30, score=score,
            grade="B", action=action, signal="🟢 Uptrend", headline=f"{tk} headline",
            narrative=f"{tk} narrative", sector=sector, stop_loss=avg * 0.9,
            target=avg * 1.2, risk_reward=2.0)

    hs = [_h("AAA", 10, 100.0, 120.0, "BUY", "IT", 70),
          _h("BBB", 5, 400.0, 380.0, "CAUTION", "Banking", 40),
          _h("CCC", 20, 50.0, 55.0, "HOLD", "IT", 55)]
    return PortfolioSummary(
        generated_at="2026-09-27T10:00:00", holdings=hs,
        total_invested=sum(h.invested for h in hs),
        total_current_value=sum(h.current_value for h in hs),
        total_pnl=sum(h.pnl for h in hs), total_pnl_pct=5.0,
        portfolio_score=58.0, portfolio_grade="B", best_holding=hs[0], worst_holding=hs[1],
        diversification=PortfolioDiversification(
            sector_weights={"IT": 60.0, "Banking": 40.0}, top_sector="IT", top_sector_pct=60.0,
            n_sectors=2, concentration_risk="MEDIUM", advice="IT is the largest sector weight."),
        vix_regime="normal", summary_narrative="Three holdings; one in a weakening trend.",
    )


@pytest.fixture(autouse=True)
def _stubs(monkeypatch):
    def _blocked(*a, **k):
        raise OSError("network blocked for portfolio layout test")
    monkeypatch.setattr(socket.socket, "connect", _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)

    import dashboard.shared.trade_utils as tu
    import analysis.portfolio_manager as pm_mod
    monkeypatch.setattr(tu, "load_manual_holdings", lambda: [dict(h) for h in _HOLDINGS])
    monkeypatch.setattr(tu, "_portfolio_live_prices", lambda tickers: {
        "AAA.NS": {"price": 120.0, "prev": 118.0},
        "BBB.NS": {"price": 380.0, "prev": 385.0},
        "CCC.NS": {"price": 55.0, "prev": 54.0},
    })

    class _FakePM:
        def __init__(self, path):
            self.holdings_raw = [dict(h) for h in _HOLDINGS]

        def mark_to_market(self, parallel=True):
            return _summary()

    monkeypatch.setattr(pm_mod, "PortfolioManager", _FakePM)


def _html_blob(at) -> str:
    return "\n".join(str(m.value) for m in at.markdown)


def test_portfolio_layout_sections_render():
    at = AppTest.from_file(_PAGE, default_timeout=180).run()
    assert not at.exception, at.exception
    html = _html_blob(at)
    assert "Portfolio posture" in html
    assert "Sector allocation" in html and "alloc-row" in html
    # Today's move (+20 +-25 +20 = +15) lands on the NAV tile.
    assert "today" in html
    # One selected holding card, not one per holding.
    assert html.count('class="holding-card') == 1
    assert any("Holding detail" in s.label for s in at.selectbox)


def test_holding_picker_switches_card():
    at = AppTest.from_file(_PAGE, default_timeout=180).run()
    picker = next(s for s in at.selectbox if "Holding detail" in s.label)
    picker.select(1).run()
    assert not at.exception, at.exception
    assert _html_blob(at).count('class="holding-card') == 1
