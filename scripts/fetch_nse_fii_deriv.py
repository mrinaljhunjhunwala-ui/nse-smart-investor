"""
scripts/fetch_nse_fii_deriv.py — NSE FII derivatives daily fetcher.

Feeds the FII-deriv sub-score inside Recommendation 6's Positioning
pillar. See docs/POSITIONING_INTEGRATION_2026-09.md.

MUST BE RUN FROM A RESIDENTIAL IP — same constraint as the other
NSE-archives scrapers (nse_delivery, nse_fno_bhavcopy, qualitative_flags).

USAGE
    py -m scripts.fetch_nse_fii_deriv                # today
    py -m scripts.fetch_nse_fii_deriv --date 2026-09-02
    py -m scripts.fetch_nse_fii_deriv --days 30      # backfill
    py -m scripts.fetch_nse_fii_deriv --days 30 --end 2026-09-01

Universe-level file, one row per day. Cheaper than per-symbol fetchers.

EXIT CODES
    0  all requested days OK
    1  at least one date failed after retry
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

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from data.nse_fii_deriv import (   # noqa: E402
    _fetch, _parse, _persist, ensure_schema,
)

_log = logging.getLogger("scripts.fetch_nse_fii_deriv")


def _is_weekend(d: _dt.date) -> bool:
    return d.weekday() >= 5


def _daterange(end: _dt.date, days: int) -> List[_dt.date]:
    out: List[_dt.date] = []
    cursor = end
    while len(out) < days:
        if not _is_weekend(cursor):
            out.append(cursor)
        cursor -= _dt.timedelta(days=1)
    return list(reversed(out))


def _fetch_one_day(date: _dt.date, max_retries: int = 2) -> int:
    for attempt in range(max_retries + 1):
        try:
            text = _fetch(date)
            row = _parse(text, date)
            if row is None:
                _log.info("%s: no FII row parsed — skipped", date.isoformat())
                return 0
            written = _persist(row)
            _log.info("%s: written (fut_idx_net=%s)",
                      date.isoformat(), row.get("fut_idx_net"))
            return written
        except ValueError as e:
            msg = str(e)
            if "not available" in msg or "404" in msg:
                _log.info("%s: not published — skipped", date.isoformat())
                return 0
            _log.warning("%s: parse/fetch error attempt %d/%d: %s",
                         date.isoformat(), attempt + 1, max_retries + 1, e)
        except Exception as e:
            _log.warning("%s: unexpected error attempt %d/%d: %s",
                         date.isoformat(), attempt + 1, max_retries + 1, e)
        if attempt < max_retries:
            time.sleep(random.uniform(3.0, 6.0))
    _log.error("%s: gave up after %d retries", date.isoformat(), max_retries + 1)
    return -1


def _parse_args(argv: List[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Fetch NSE FII derivatives participant-OI data into trade_store."
    )
    p.add_argument("--date", type=str, default=None)
    p.add_argument("--days", type=int, default=1)
    p.add_argument("--end",  type=str, default=None)
    p.add_argument("--verbose", "-v", action="store_true")
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
        if i < len(dates) - 1:
            time.sleep(random.uniform(1.5, 3.5))

    _log.info("done. requested=%d, failed=%d", len(dates), failed)
    return 1 if failed > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
