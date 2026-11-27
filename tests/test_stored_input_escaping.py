"""Regression tests for the 2026-11 security audit leads: viewer-stored text must not
render as raw HTML, and portfolio notes must stay behind the My Portfolio unlock."""
from contextlib import nullcontext

from dashboard.shared.ui_components import ticker_hover_wrap

EVIL = '<a href="https://example.invalid">x</a>'


def test_ticker_hover_wrap_escapes_label_and_sector():
    out = ticker_hover_wrap(EVIL, sector=EVIL)
    assert "<a href" not in out
    assert "&lt;a href" in out


def test_ticker_hover_wrap_keeps_ampersand_tickers_readable():
    assert "M&amp;M" in ticker_hover_wrap("M&M")


def test_autoclose_banner_escapes_ticker_and_account(monkeypatch):
    from dashboard.shared import trade_utils
    seen = []
    monkeypatch.setattr(trade_utils.st, "markdown", lambda s, **k: seen.append(s))
    trade_utils._render_autoclose_banner([
        {"type": "stop", "ticker": EVIL, "account": EVIL, "exit": None, "pnl": None},
        {"type": "stop", "ticker": EVIL, "account": EVIL, "exit": 10.0, "pnl": 1.0},
    ])
    joined = "".join(seen)
    assert "<a href" not in joined
    assert "&lt;a href" in joined


class _FakeSt:
    """Just enough of the streamlit API for _render_library."""

    def __init__(self):
        self.text = []

    def markdown(self, s, **k):
        self.text.append(s)

    caption = markdown

    def selectbox(self, label, options, **k):
        self.text.extend(options)
        return options[0]

    def expander(self, title):
        self.text.append(title)
        return nullcontext()

    def button(self, *a, **k):
        return False


def _run_library(monkeypatch, unlocked):
    from dashboard.views import research_notes as rn
    import dashboard.shared.pin_gate as pg
    monkeypatch.setattr(pg, "holdings_unlocked", lambda: unlocked)
    monkeypatch.setattr(rn, "_load_stock_notes", lambda: {})
    monkeypatch.setattr(rn, "_load_portfolio_notes", lambda: [{
        "generated_at": "2026-01-01T00:00:00", "question_label": "q", "question": "q",
        "tickers": ["SECRETHOLD"], "answer": "held"}])
    fake = _FakeSt()
    rn._render_library(fake)
    return " ".join(map(str, fake.text))


def test_library_hides_portfolio_notes_when_locked(monkeypatch):
    assert "SECRETHOLD" not in _run_library(monkeypatch, unlocked=False)


def test_library_shows_portfolio_notes_when_unlocked(monkeypatch):
    assert "SECRETHOLD" in _run_library(monkeypatch, unlocked=True)
