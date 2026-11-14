"""Timezone-safe generated_at stamps for the warmer KV snapshots."""
from __future__ import annotations

import datetime
from typing import Any, Optional

# The warmers run on GitHub's runners (UTC) and used to stamp a naive
# datetime.now(); readers aged it against their own naive datetime.now().
# That only agrees when both clocks share a timezone — on an IST machine every
# fresh snapshot looked 5.5 h old and was thrown away, so the app always paid
# for a live scan. Writers now stamp an aware UTC time; readers go through
# snapshot_age_seconds(), which treats legacy naive stamps as UTC (every
# scheduled writer ran on a UTC runner).
def snapshot_timestamp() -> str:
    """Aware-UTC ISO timestamp for a snapshot's generated_at."""
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def parse_snapshot_timestamp(gen_at: Any) -> Optional[datetime.datetime]:
    """Parse a generated_at into an aware datetime (naive = UTC); None if unparseable."""
    if not gen_at or not isinstance(gen_at, str):
        return None
    try:
        ts = datetime.datetime.fromisoformat(gen_at)
    except ValueError:
        return None
    return ts if ts.tzinfo else ts.replace(tzinfo=datetime.timezone.utc)


def snapshot_age_seconds(gen_at: Any) -> Optional[float]:
    """Seconds since generated_at, independent of the reader's timezone."""
    ts = parse_snapshot_timestamp(gen_at)
    if ts is None:
        return None
    return (datetime.datetime.now(datetime.timezone.utc) - ts).total_seconds()


# FIX SNAPSHOT-GUARD (2026-11-13): the warmers persisted whatever the scan
# returned. During a provider outage that replaced a good snapshot with an
# empty or half-universe one, which the app and the alert jobs then served as
# "today's lists". A scan that scored under half its universe is not persisted;
# the previous snapshot ages out and readers fall back to their own live scan.
MIN_SCORED_FRACTION = 0.5


def scan_too_degraded(n_universe: Any, n_scored_ok: Any,
                      min_fraction: float = MIN_SCORED_FRACTION) -> bool:
    """True when a scan result must not overwrite the persisted snapshot."""
    try:
        n_u, n_ok = int(n_universe or 0), int(n_scored_ok or 0)
    except (TypeError, ValueError):
        return True
    return n_u <= 0 or n_ok < min_fraction * n_u


def ist_now() -> datetime.datetime:
    """Aware current time in IST (runners are UTC; the owner reads IST)."""
    return datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=5, minutes=30)))
