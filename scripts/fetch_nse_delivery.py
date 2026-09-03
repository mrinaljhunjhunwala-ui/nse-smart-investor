"""
scripts/fetch_nse_delivery.py — NSE bhavcopy delivery-% fetcher.

Feeds Recommendation 4 of docs/COMPOSITE_SCORE_SHAPE_REVIEW.md
(analysis.score reads delivery snapshots via data.nse_delivery.get_snapshot).

MUST BE RUN FROM A RESIDENTIAL IP — NOT GitHub Actions, NOT Streamlit
Cloud. NSE's WAF blocks essentially all cloud/datacenter IP ranges (same
constraint as scripts/refresh_qualitative_flags.py — see that file's header
for the deeper context). Home broadband works; run this manually from
Task Scheduler or a local cron, and let it write into the shared Postgres
(DATABASE_URL) that Streamlit Cloud reads from.

USAGE

    # Daily cron — fetch today's bhavcopy (best-effort: NSE typically
    # publishes around 6-7 PM IST; before then this will 404 gracefully).
    py -m scripts.fetch_nse_delivery

    # Fetch a specific date (YYYY-MM-DD)
    py -m scripts.fetch_nse_delivery --date 2026-09-02

    # One-time backfill: last N calendar days, skipping weekends. Useful
    # when standing the DB up for the first time so scoring has ~60 days
    # of history for the z-score sub-score.
    py -m scripts.fetch_nse_delivery --days 90

    # Combine: backfill up to a specific end date (inclusive)
    py -m scripts.fetch_nse_delivery --days 30 --end 2026-09-01

RATE LIMITING

Between requests we sleep a randomized 1.5-3.5s. NSE serves the bhavcopy
CSV via a lightly cached CDN so a small burst is fine, but hammering it
gets the connection reset. If you see 403/RST, wait 10 min and try again.

EXIT CODES

  0  All requested days written OK (or already present as no-ops).
  1  At least one requested day failed after the retry budget.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import logging
import os
import random
import sys
import time
from typing import List

# Ensure project root is on sys.path so `data.*` imports work when this
# script is invoked as `py -m scripts.fetch_nse_delivery` OR directly.
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from data.nse_delivery import (   # noqa: E402
    _fetch_bhavcopy, _parse_bhavcopy, _persist, ensure_schema,
)

_log = logging.getLogger("scripts.fetch_nse_delivery")


# ─────────────────────────────────────────────────────────────────────────────
# Date helpers
# ─────────────────────────────────────────────────────────────────────────────

def _is_weekend(d: _dt.date) -> bool:
    # Saturday = 5, Sunday = 6. NSE cash market runs Mon-Fri only. Holidays
    # are handled by _fetch_bhavcopy raising ValueError on 404 — cheap to
    # try and let it fail than to maintain a holiday calendar here.
    return d.weekday() >= 5


def _daterange(end: _dt.date, days: int) -> List[_dt.date]:
    """Return `days` most-recent weekdays ending at `end` (inclusive)."""
    out: List[_dt.date] = []
    cursor = end
    while len(out) < days:
        if not _is_weekend(cursor):
            out.append(cursor)
        cursor -= _dt.timedelta(days=1)
    return list(reversed(out))   # oldest first — more sensible progress output


# ─────────────────────────────────────────────────────────────────────────────
# Fetch a single day with retry + rate-limit
# ─────────────────────────────────────────────────────────────────────────────

def _fetch_one_day(date: _dt.date, max_retries: int = 2) -> int:
    """Return rows written; 0 on graceful skip (holiday / not yet published)."""
    for attempt in range(max_retries + 1):
        try:
            csv_text = _fetch_bhavcopy(date)
            rows = _parse_bhavcopy(csv_text)
            written = _persist(rows)
            _log.info("%s: %d rows written", date.isoformat(), written)
            return written
        except ValueError as e:
            msg = str(e)
            if "not available" in msg or "404" in msg:
                _log.info("%s: not published (holiday or too early) — skipped",
                          date.isoformat())
                return 0
            _log.warning("%s: parse/fetch error on attempt %d/%d: %s",
                         date.isoformat(), attempt + 1, max_retries + 1, e)
        except Exception as e:
            _log.warning("%s: unexpected error on attempt %d/%d: %s",
                         date.isoformat(), attempt + 1, max_retries + 1, e)
        if attempt < max_retries:
            time.sleep(random.uniform(3.0, 6.0))
    _log.error("%s: gave up after %d retries", date.isoformat(), max_retries + 1)
    return -1


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

def _parse_args(argv: List[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Fetch NSE bhavcopy delivery data into the shared trade_store."
    )
    p.add_argument("--date", type=str, default=None,
                   help="Single YYYY-MM-DD to fetch (mutually exclusive with --days)")
    p.add_argument("--days", type=int, default=1,
                   help="Fetch the N most-recent weekdays ending at --end (default 1)")
    p.add_argument("--end", type=str, default=None,
                   help="YYYY-MM-DD end date for --days (default today)")
    p.add_argument("--verbose", "-v", action="store_true",
                   help="Enable DEBUG logging")
    return p.parse_args(argv)


def main(argv: List[str] | None = None) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])
    logging.basicConfig(
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        level=logging.DEBUG if args.verbose else logging.INFO,
    )

    ensure_schema()

    if args.date:
        dates = [_dt.date.fromisoformat(args.date)]
    else:
        end = _dt.date.fromisoformat(args.end) if args.end else _dt.date.today()
        dates = _daterange(end, args.days)

    _log.info("fetching %d date(s): %s .. %s",
              len(dates), dates[0].isoformat(), dates[-1].isoformat())

    failed = 0
    for i, d in enumerate(dates):
        rc = _fetch_one_day(d)
        if rc < 0:
            failed += 1
        # Rate-limit between requests only when there is a next one.
        if i < len(dates) - 1:
            time.sleep(random.uniform(1.5, 3.5))

    _log.info("done. requested=%d, failed=%d", len(dates), failed)
    return 1 if failed > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
