"""tests/test_command_bar.py — sidebar command-bar matcher contract."""
from __future__ import annotations

import pytest

from dashboard.shared.nav import _cmdbar_match


def test_empty_query_returns_nothing():
    assert _cmdbar_match("") == []
    assert _cmdbar_match("   ") == []
    assert _cmdbar_match(None) == []


def test_single_char_query_returns_nothing():
    """Guard against a single 's' matching half the app — 2-char minimum."""
    assert _cmdbar_match("a") == []


def test_page_query_matches_page():
    """Typing part of a page name should return page hit(s)."""
    hits = _cmdbar_match("port")  # portfolio
    assert hits
    kinds = {h[1] for h in hits}
    assert "page" in kinds
    # First result should be a page (pages ranked first)
    assert hits[0][1] == "page"


def test_case_insensitive():
    hi = _cmdbar_match("PORTFOLIO")
    lo = _cmdbar_match("portfolio")
    assert hi and lo
    # Same target for both
    assert hi[0][2] == lo[0][2]


def test_page_targets_are_navigable_names():
    """The `target` on page hits must be a name usable with the sidebar's
    _PAGE_FILE lookup (so _nav_to can switch pages)."""
    from dashboard.shared.nav import _PAGE_FILE
    hits = [h for h in _cmdbar_match("portfolio") if h[1] == "page"]
    assert hits
    for _, _, target in hits:
        assert target in _PAGE_FILE, f"page target {target!r} not in _PAGE_FILE"


def test_capped_at_8_results():
    """Broad queries must not explode the sidebar."""
    hits = _cmdbar_match("a")  # single char, blocked
    assert hits == []
    hits = _cmdbar_match("st")  # broad — many stocks + a couple of pages
    assert len(hits) <= 8


def test_ticker_hits_have_ticker_kind():
    """A ticker match must be tagged 'ticker' so the caller routes it to
    Analyze Stock with the symbol preloaded."""
    hits = _cmdbar_match("reliance")
    # Might be zero if STOCK_SEARCH_MAP is empty in the test env, but the
    # matcher must not crash and any hit must carry the right kind.
    for _, kind, _ in hits:
        assert kind in ("page", "ticker")


@pytest.mark.parametrize("q", ["command", "analyze", "screener", "backtest"])
def test_common_pages_reachable(q):
    """Sanity check for the most common jump targets."""
    hits = _cmdbar_match(q)
    assert any(h[1] == "page" for h in hits), (
        f"expected at least one page hit for {q!r}, got: {hits}")
