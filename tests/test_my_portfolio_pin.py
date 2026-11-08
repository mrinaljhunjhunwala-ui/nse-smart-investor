"""My Portfolio sits behind the owner PIN (public app, no login). Offline."""
import socket
import time
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

_PAGE = str(Path(__file__).resolve().parents[1] / "dashboard" / "pages" / "03_my_portfolio.py")


@pytest.fixture
def page(monkeypatch):
    def _blocked(*a, **k):
        raise OSError("network blocked for portfolio pin test")
    monkeypatch.setattr(socket.socket, "connect", _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)
    import dashboard.shared.trade_utils as tu
    reads = []
    monkeypatch.setattr(tu, "load_manual_holdings", lambda: reads.append(1) or [])
    monkeypatch.delenv("ANGEL_PAGE_PIN", raising=False)
    return monkeypatch, reads


def _text(at) -> str:
    return "\n".join(str(e.value) for e in list(at.markdown) + list(at.error) + list(at.caption))


def test_no_pin_configured_fails_closed(page):
    _, reads = page
    at = AppTest.from_file(_PAGE, default_timeout=180).run()
    assert not at.exception, at.exception
    assert "My Portfolio is locked" in _text(at) and "edit your holdings" in _text(at)
    assert "place real orders" not in _text(at)
    assert reads == []                                   # holdings never loaded


def test_wrong_pin_stays_locked_right_pin_unlocks(page):
    mp, reads = page
    mp.setenv("ANGEL_PAGE_PIN", "4821")
    at = AppTest.from_file(_PAGE, default_timeout=180).run()
    assert "PIN-protected" in _text(at) and reads == []
    at.text_input(key="pin_input_my_portfolio").input("0000")
    at.button[0].click().run()
    assert "Wrong PIN" in _text(at) and reads == []
    at.text_input(key="pin_input_my_portfolio").input("4821")
    at.button[0].click().run()
    assert not at.exception, at.exception
    assert reads, "holdings should load once unlocked"


def test_unlocked_session_skips_the_form(page):
    mp, reads = page
    mp.setenv("ANGEL_PAGE_PIN", "4821")
    at = AppTest.from_file(_PAGE, default_timeout=180)
    at.session_state["_pin_unlocked_at_my_portfolio"] = time.time()
    at.run()
    assert not at.exception, at.exception
    assert "PIN-protected" not in _text(at) and reads


def test_sidebar_quick_view_hides_holdings_until_unlocked(monkeypatch):
    """Every page renders the sidebar quick view; a locked session must not see holdings."""
    import dashboard.shared.pin_gate as pg
    import dashboard.shared.trade_utils as tu
    reads = []
    monkeypatch.setattr(tu, "load_manual_holdings", lambda: reads.append(1) or [])
    monkeypatch.setattr(pg, "holdings_unlocked", lambda: False)
    page = str(Path(_PAGE).with_name("15_investor_guide.py"))
    at = AppTest.from_file(page, default_timeout=180).run()
    assert not at.exception, at.exception
    assert reads == []
    assert any("Unlock **My Portfolio**" in str(c.value) for c in at.sidebar.caption)
