"""Market Breadth tab (mockup artboard 07): with a breadth scan in session
the tab renders the A/D gauge panel, the moving-average bars on a 0-100
track and the FII/DII flow panel from the local ledger. With nothing stored
it degrades to empty states. Network is blocked; the ledger is stubbed.
"""
import os
import socket

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PAGE = os.path.join(_ROOT, "dashboard", "pages", "05_market_overview.py")

_BREADTH = {
    "advance": 34, "decline": 16, "total": 50, "ad_ratio": 2.12,
    "pct_above_20": 76.0, "pct_above_50": 68.0, "pct_above_200": 58.0,
    "near_52w_high": 9, "near_52w_low": 2,
}


def _flows():
    return pd.DataFrame({
        "date": pd.date_range("2026-09-14", periods=10, freq="B").strftime("%Y-%m-%d")[::-1],
        "fii_net": [1200.0, -800.0, 450.0, 300.0, -150.0, 900.0, 600.0, -200.0, 100.0, 50.0],
        "dii_net": [-300.0, 700.0, 100.0, -50.0, 400.0, -100.0, 200.0, 300.0, -80.0, 20.0],
    })


@pytest.fixture
def _stubs(monkeypatch):
    def _blocked(*a, **k):
        raise OSError("network blocked for breadth layout test")
    monkeypatch.setattr(socket.socket, "connect", _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)
    import analysis.fii_dii as fd
    return monkeypatch, fd


def _html(at) -> str:
    return "\n".join(str(m.value) for m in at.markdown)


def test_breadth_panels_render(_stubs):
    mp, fd = _stubs
    mp.setattr(fd, "load_history", lambda days=90: _flows())
    at = AppTest.from_file(_PAGE, default_timeout=180)
    at.session_state["ov_breadth"] = dict(_BREADTH)
    at.run()
    assert not at.exception, at.exception
    html = _html(at)
    assert 'class="breadth-gauge"' in html and "34 : 16" in html and "2.12 A/D ratio" in html
    assert "Moderate breadth" in html
    # Absolute 0-100 track: 76% renders at 76% width, not scaled to the peak.
    assert "Above 20-DMA" in html and "width:76.0%" in html
    assert "FII &amp; DII activity" in html and html.count('class="flow-col"') == 10
    assert "+₹2,450 Cr" in html and "+₹1,190 Cr" in html


def test_breadth_empty_states(_stubs):
    mp, fd = _stubs
    mp.setattr(fd, "load_history", lambda days=90: pd.DataFrame())
    at = AppTest.from_file(_PAGE, default_timeout=180).run()
    assert not at.exception, at.exception
    html = _html(at)
    assert "No breadth scan yet" in html
    assert "No FII / DII history stored yet" in html
