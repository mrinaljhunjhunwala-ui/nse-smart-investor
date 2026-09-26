"""Position Sizer (mockup artboard 05): the quiet layout renders the keyed
input column and one sunken output panel per tab, with the existing sizing
maths unchanged. Network is blocked.
"""
import os
import socket

import pytest
from streamlit.testing.v1 import AppTest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PAGE = os.path.join(_ROOT, "dashboard", "pages", "12_position_sizer.py")


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    def _blocked(*a, **k):
        raise OSError("network blocked for position sizer layout test")
    monkeypatch.setattr(socket.socket, "connect", _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)


def _html(at) -> str:
    return "\n".join(str(m.value) for m in at.markdown)


def test_fixed_risk_output_panel():
    at = AppTest.from_file(_PAGE, default_timeout=120).run()
    assert not at.exception, at.exception
    html = _html(at)
    # Defaults: 5,00,000 capital, 1% risk, entry 500, stop 480 -> 250 shares.
    assert "Position size" in html and 'class="quiet-lead">250<' in html
    assert "₹1,25,000 position value" in html
    assert "R:R at target (scenario)" in html and "2.5 : 1" in html
    assert "Reward at target (scenario)" in html and "₹12,500" in html
    assert "Shares to Buy" not in html


def test_inputs_recompute_and_lots():
    at = AppTest.from_file(_PAGE, default_timeout=120).run()
    at.number_input(key="ps_lot").set_value(100).run()
    assert not at.exception, at.exception
    html = _html(at)
    assert 'class="quiet-lead">200<' in html and "2 × 100" in html


def test_stop_above_entry_warns():
    at = AppTest.from_file(_PAGE, default_timeout=120).run()
    at.number_input(key="ps_sl").set_value(600.0).run()
    assert not at.exception, at.exception
    assert any("greater than stop-loss" in w.value for w in at.warning)


def test_kelly_panel_renders():
    at = AppTest.from_file(_PAGE, default_timeout=120).run()
    html = _html(at)
    assert "Kelly-implied size" in html and "Raw Kelly" in html
