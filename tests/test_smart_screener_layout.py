"""Smart Screener (mockup artboard 08): the scan path renders, and results
persist across reruns (SCR-PERSIST).

Before SCR-PERSIST, results existed only in the run where "Run screen" was
clicked, so any later widget interaction discarded a finished scan. The scan,
scoring, fundamentals and sparkline calls are stubbed; network is blocked.
"""
import os
import socket
from types import SimpleNamespace

import pytest
from streamlit.testing.v1 import AppTest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PAGE = os.path.join(_ROOT, "dashboard", "pages", "06_smart_screener.py")

_FAKE_SIGNALS = [
    {"ticker": "AAA.NS", "price": 100.0, "sl": 95.0, "tp": 112.0, "screen": "Breakout",
     "sector": "IT", "reason": "Closed above 20-day high", "stop_type": "atr"},
    {"ticker": "BBB.NS", "price": 250.0, "sl": 240.0, "tp": 270.0, "screen": "Oversold_Bounce",
     "sector": "Bank", "reason": "RSI 28 turning up", "stop_type": "swing"},
    {"ticker": "CCC.NS", "price": 50.0, "sl": 48.0, "tp": 55.0, "screen": "Breakout",
     "sector": "Auto", "reason": "Volume 2x", "stop_type": "atr"},
]


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    def _blocked(*a, **k):
        raise OSError("network blocked for screener layout test")
    monkeypatch.setattr(socket.socket, "connect", _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)

    import trading.signals as signals_mod
    import analysis.score as score_mod
    import dashboard.shared.cache as cache_mod
    import analysis.fundamentals.service as fund_mod

    monkeypatch.setattr(signals_mod, "scan_tickers",
                        lambda universe, strategy="all", period="1y": [dict(s) for s in _FAKE_SIGNALS])
    scores = {"AAA.NS": 72.0, "BBB.NS": 41.0, "CCC.NS": 60.0}
    monkeypatch.setattr(score_mod, "score_stock", lambda tk, **kw: SimpleNamespace(
        score=scores[tk], grade="B", action="BUY", headline=f"{tk} headline",
        stop_loss=1.0, target=2.0))
    monkeypatch.setattr(cache_mod, "get_vix_info", lambda: {"vix": 12.0, "regime": "normal"})
    monkeypatch.setattr(cache_mod, "_sparkline_closes", lambda tk, n=22: [1.0, 2.0, 1.5])

    def _no_fundamentals():
        raise RuntimeError("fundamentals disabled in test")
    monkeypatch.setattr(fund_mod, "default_service", _no_fundamentals)


def _run_button(at):
    return next(b for b in at.button if "Run screen" in b.label)


def test_scan_renders_ranked_results_and_detail():
    at = AppTest.from_file(_PAGE, default_timeout=120).run()
    assert not at.exception
    assert "scr_run" not in at.session_state

    _run_button(at).click().run()
    assert not at.exception
    run = at.session_state["scr_run"]
    tickers = [s["ticker"] for s in run["signals"]]
    assert tickers == ["AAA.NS", "CCC.NS", "BBB.NS"]      # ranked by composite, desc
    assert run["signals"][0]["_rr"] == pytest.approx(2.4)
    assert len(at.dataframe) == 1
    assert any("Setup detail" in s.label for s in at.selectbox)


def test_results_survive_later_interaction():
    at = AppTest.from_file(_PAGE, default_timeout=120).run()
    _run_button(at).click().run()
    detail = next(s for s in at.selectbox if "Setup detail" in s.label)
    detail.select(2).run()                                  # any widget change = rerun
    assert not at.exception
    assert len(at.session_state["scr_run"]["signals"]) == 3
    assert len(at.dataframe) == 1
