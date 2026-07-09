"""tests/test_pages_smoke.py — CI page smoke coverage (Part 1).

Loads every Streamlit page headlessly via AppTest and asserts it renders with **no uncaught
exception** (which also catches unresolved imports / NameErrors — the P3 risk). Made
deterministic and CI-safe by **fail-fast network blocking**: outbound sockets raise
immediately, so each page takes its graceful degraded path (the pages already wrap their
fetches — P2) and renders quickly, with no dependence on live Yahoo/NSE.

Marked `smoke`; runs in the default suite and CI. The one slow backtest e2e is separate
(`-m slow`).
"""
from __future__ import annotations

import glob
import os
import socket

import pytest
from streamlit.testing.v1 import AppTest

_PAGES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "dashboard", "pages")
_PAGES = sorted(glob.glob(os.path.join(_PAGES_DIR, "*.py")))
_IDS = [os.path.basename(p) for p in _PAGES]


@pytest.fixture
def _no_network(monkeypatch):
    """Block outbound network so pages take the fast, deterministic degraded path."""
    def _blocked(*args, **kwargs):
        raise OSError("network blocked for page smoke test")
    monkeypatch.setattr(socket.socket, "connect", _blocked, raising=False)
    monkeypatch.setattr(socket, "create_connection", _blocked, raising=False)
    yield


def test_all_pages_present():
    # Guard: the universe of pages the smoke covers (catches an accidentally-dropped page).
    # 17 after merging Macro Dashboard + Market Breadth → Market Internals.
    # 18 after adding 18_tqs_scanner.py.
    # Still 18 after: merging Market Overview + Market Internals → Overview
    # (net -1: 09_market_internals.py deleted) and adding 19_quality_watch.py
    # (net +1) — the two changes cancel out in the page COUNT, but _IDS below
    # will differ (09_market_internals.py gone, 19_quality_watch.py present).
    assert len(_PAGES) == 18, f"expected 18 pages, found {len(_PAGES)}: {_IDS}"


@pytest.mark.smoke
@pytest.mark.parametrize("page", _PAGES, ids=_IDS)
def test_page_loads_without_exception(page, _no_network):
    at = AppTest.from_file(page, default_timeout=120).run()
    # AppTest.exception is an ElementList (falsy when empty), not None.
    assert not at.exception, (
        f"{os.path.basename(page)} raised an uncaught exception: "
        + "; ".join(str(e.value) for e in at.exception)
    )
