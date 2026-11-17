"""Audit 2026-11: My Portfolio rows for holdings that could not be scored or quoted."""
import analysis.portfolio_manager as pm_mod
from analysis.portfolio_manager import NO_DATA, PortfolioManager, today_rupees


def _pm():
    p = PortfolioManager.__new__(PortfolioManager)
    return p


def test_today_rupees_is_measured_from_the_previous_close():
    assert today_rupees(110, 10, 10.0) == 100.0          # was 110 (price x chg%)
    assert today_rupees(90, 10, -10.0) == -100.0
    assert today_rupees(110, 10, None) is None


def test_unscored_holding_is_not_a_hold_50(monkeypatch):
    import analysis.score as S
    monkeypatch.setattr(S, "score_stock", lambda *a, **k: (_ for _ in ()).throw(ConnectionError("yahoo")))
    h = _pm()._score_holding({"ticker": "ABC.NS", "quantity": 10, "avg_buy_price": 100,
                              "date_bought": "2026-01-02"}, {})
    assert h.error and h.action == NO_DATA and h.today_chg_pct is None    # was HOLD, 50/90, 0.00%


def test_missing_quote_is_not_zero_percent(monkeypatch):
    import analysis.score as S
    import utils.live_price as LP

    class CS:
        price, score, grade, action, headline, narrative, sector = 100.0, 60, "B", "HOLD", "", "", "IT"
        stop_loss, target, risk_reward = 95.0, 110.0, 2.0
    monkeypatch.setattr(S, "score_stock", lambda *a, **k: CS())
    monkeypatch.setattr(LP, "get_live_quote", lambda t: None)
    h = _pm()._score_holding({"ticker": "ABC.NS", "quantity": 10, "avg_buy_price": 100,
                              "date_bought": "2026-01-02"}, {})
    assert not h.error and h.today_chg_pct is None                   # was 0.0, shown as "+0.00%"


def test_page_keeps_unscored_holding_out_of_posture_and_signal_monitor(monkeypatch):
    import socket

    from streamlit.testing.v1 import AppTest

    import dashboard.shared.pin_gate as pg
    import dashboard.shared.trade_utils as tu
    from tests import test_my_portfolio_layout as L

    monkeypatch.setattr(socket.socket, "connect", lambda *a, **k: (_ for _ in ()).throw(OSError("blocked")))
    monkeypatch.setattr(pg, "require_pin", lambda *a, **k: None)
    monkeypatch.setattr(tu, "load_manual_holdings", lambda: [dict(h) for h in L._HOLDINGS])
    monkeypatch.setattr(tu, "_portfolio_live_prices", lambda tickers: {})
    saved = {}
    monkeypatch.setattr(tu, "load_signal_monitor_state", lambda: {"BBB.NS": "CAUTION"})
    monkeypatch.setattr(tu, "save_signal_monitor_state", lambda a: saved.update(a))

    def _summary():
        s = L._summary()
        b = s.holdings[1]
        b.error, b.action, b.score, b.current_price, b.today_chg_pct = "yahoo", NO_DATA, 0.0, 0.0, None
        return s

    class _FakePM:
        def __init__(self, path):
            self.holdings_raw = [dict(h) for h in L._HOLDINGS]

        def mark_to_market(self, parallel=True):
            return _summary()
    monkeypatch.setattr(pm_mod, "PortfolioManager", _FakePM)
    at = AppTest.from_file(L._PAGE, default_timeout=180).run()
    assert not at.exception, at.exception
    html = "\n".join(str(m.value) for m in at.markdown)
    assert "Portfolio posture" in html and "2 holdings" in html     # the unscored one is not counted
    assert saved.get("BBB.NS") == "CAUTION"                          # last known action kept, no fake flip
