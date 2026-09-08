"""
alerts/journal_store.py — Headless read/append helpers for data/stock_journal.csv.

The stock journal is the "why did I care about this stock, on what thesis,
with what target and stop, and when should I review it" log. Both the
Streamlit journal page (PR 2) and the alert digests will use these helpers
so there is exactly one place the schema lives.

Schema (kept intentionally small so writes are cheap and reads are grep-able):

    ticker         NSE symbol, no .NS suffix (e.g. RELIANCE)
    added_date     ISO date the entry was created (YYYY-MM-DD)
    thesis         one-line reason ("55d breakout on 2x vol from digest 2026-09-08")
    entry_target   price you wanted to enter at (₹, or blank)
    stop           stop-loss level (₹, or blank)
    target         profit target (₹, or blank)
    review_date    ISO date you plan to re-evaluate (YYYY-MM-DD, or blank)
    tags           comma-separated free tags ("delivery,breakout,momentum")
    status         open | closed | passed | invalidated

No Streamlit dependency — this module can be called from the alert pipeline
to append "we surfaced this in a digest" auto-entries.
"""
from __future__ import annotations

import csv
import datetime
import logging
import os
from dataclasses import dataclass, field, asdict
from typing import Iterator, List, Optional

_log = logging.getLogger("alerts.journal_store")

_JOURNAL_CSV = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data",
    "stock_journal.csv",
)

FIELDNAMES = [
    "ticker", "added_date", "thesis",
    "entry_target", "stop", "target",
    "review_date", "tags", "status",
]

VALID_STATUS = ("open", "closed", "passed", "invalidated")


@dataclass
class JournalEntry:
    ticker: str
    added_date: str = field(default_factory=lambda: datetime.date.today().isoformat())
    thesis: str = ""
    entry_target: str = ""    # kept as string so blank is preserved as blank
    stop: str = ""
    target: str = ""
    review_date: str = ""
    tags: str = ""
    status: str = "open"

    def __post_init__(self):
        self.ticker = self.ticker.strip().upper()
        if self.status not in VALID_STATUS:
            raise ValueError(
                f"status must be one of {VALID_STATUS}, got {self.status!r}"
            )
        if not self.ticker:
            raise ValueError("ticker is required")


def _ensure_file(path: str = _JOURNAL_CSV) -> None:
    """Create the CSV with headers if it doesn't exist yet.

    The repo ships the file with headers already committed (see
    data/stock_journal.csv), but if a deployment nukes it — or a test
    monkeypatches _JOURNAL_CSV to a fresh path — we recreate the header
    row rather than corrupting the schema with a blank first row."""
    if os.path.exists(path):
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow(FIELDNAMES)


def append_entry(entry: JournalEntry, path: str = _JOURNAL_CSV) -> None:
    """Append one entry to the journal. Duplicates (same ticker + added_date)
    are allowed — the schema tolerates multiple entries per ticker across
    time so a user can log an evolving thesis."""
    _ensure_file(path)
    with open(path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writerow(asdict(entry))
    _log.info("journal: appended %s (%s)", entry.ticker, entry.status)


def read_entries(path: str = _JOURNAL_CSV) -> List[JournalEntry]:
    """Read all entries. Rows with unknown status or missing ticker are
    logged and skipped, not raised — a corrupt row shouldn't take down
    the whole reader."""
    if not os.path.exists(path):
        return []
    out: List[JournalEntry] = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                out.append(JournalEntry(
                    ticker      = row.get("ticker", ""),
                    added_date  = row.get("added_date", ""),
                    thesis      = row.get("thesis", ""),
                    entry_target= row.get("entry_target", ""),
                    stop        = row.get("stop", ""),
                    target      = row.get("target", ""),
                    review_date = row.get("review_date", ""),
                    tags        = row.get("tags", ""),
                    status      = row.get("status", "open") or "open",
                ))
            except Exception as _e:
                _log.warning("journal: skipped bad row %r: %s", row, _e)
    return out


def iter_open(path: str = _JOURNAL_CSV) -> Iterator[JournalEntry]:
    """Yield only entries with status == 'open' — the ones the digest
    context loader is interested in."""
    for e in read_entries(path):
        if e.status == "open":
            yield e


def find_open_by_ticker(ticker: str, path: str = _JOURNAL_CSV) -> Optional[JournalEntry]:
    """Return the most recent open entry for `ticker`, or None."""
    ticker = ticker.strip().upper()
    matches = [e for e in iter_open(path) if e.ticker == ticker]
    if not matches:
        return None
    # Most-recent-added wins so digests reflect the current thesis, not stale ones.
    matches.sort(key=lambda e: e.added_date, reverse=True)
    return matches[0]


__all__ = [
    "JournalEntry", "FIELDNAMES", "VALID_STATUS",
    "append_entry", "read_entries", "iter_open", "find_open_by_ticker",
]
