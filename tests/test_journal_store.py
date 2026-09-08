"""tests/test_journal_store.py — Unit tests for the headless journal helpers."""
from __future__ import annotations

import pytest

from alerts.journal_store import (
    JournalEntry, append_entry, read_entries, iter_open, find_open_by_ticker,
)


def test_entry_normalizes_ticker(tmp_path):
    e = JournalEntry(ticker=" reliance ", thesis="test")
    assert e.ticker == "RELIANCE"


def test_entry_rejects_invalid_status():
    with pytest.raises(ValueError):
        JournalEntry(ticker="TCS", status="maybe")


def test_entry_rejects_empty_ticker():
    with pytest.raises(ValueError):
        JournalEntry(ticker="")


def test_append_and_read_roundtrip(tmp_path):
    path = str(tmp_path / "journal.csv")
    e1 = JournalEntry(ticker="TCS", thesis="digest pick", stop="3700", target="4200")
    e2 = JournalEntry(ticker="RELIANCE", thesis="55d breakout")
    append_entry(e1, path=path)
    append_entry(e2, path=path)

    entries = read_entries(path=path)
    assert len(entries) == 2
    tickers = {e.ticker for e in entries}
    assert tickers == {"TCS", "RELIANCE"}
    tcs = next(e for e in entries if e.ticker == "TCS")
    assert tcs.stop == "3700" and tcs.target == "4200"


def test_iter_open_skips_closed(tmp_path):
    path = str(tmp_path / "journal.csv")
    append_entry(JournalEntry(ticker="OPEN1", thesis="a"), path=path)
    append_entry(JournalEntry(ticker="CLOSED1", thesis="b", status="closed"), path=path)
    append_entry(JournalEntry(ticker="OPEN2", thesis="c"), path=path)
    open_ones = list(iter_open(path=path))
    assert {e.ticker for e in open_ones} == {"OPEN1", "OPEN2"}


def test_find_open_by_ticker_returns_most_recent(tmp_path):
    path = str(tmp_path / "journal.csv")
    old = JournalEntry(ticker="INFY", added_date="2026-01-01", thesis="first thesis")
    new = JournalEntry(ticker="INFY", added_date="2026-09-01", thesis="fresh thesis")
    append_entry(old, path=path)
    append_entry(new, path=path)

    hit = find_open_by_ticker("infy", path=path)
    assert hit is not None
    assert hit.thesis == "fresh thesis"


def test_read_missing_file_returns_empty(tmp_path):
    """Not an error — a fresh install with no journal should read as empty."""
    assert read_entries(path=str(tmp_path / "does_not_exist.csv")) == []


def test_read_tolerates_corrupt_row(tmp_path):
    """A row with an unknown status should be skipped, not crash the reader."""
    path = str(tmp_path / "journal.csv")
    append_entry(JournalEntry(ticker="GOOD", thesis="ok"), path=path)
    # Hand-write a corrupt row
    with open(path, "a", encoding="utf-8") as f:
        f.write("BADROW,2026-09-08,broken,,,,,,not-a-real-status\n")
    entries = read_entries(path=path)
    assert len(entries) == 1
    assert entries[0].ticker == "GOOD"
