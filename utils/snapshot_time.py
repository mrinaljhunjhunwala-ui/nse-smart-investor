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


# FIX SCAN-CADENCE (2026-11-17): the Top Picks warmer is triggered every 45 min
# (09:15-15:15 IST, cron-job.org, alerts/README.md) but readers dropped its
# snapshot after 20 min. For ~25 of every 45 market minutes, and every evening,
# weekend and holiday, the app threw away a current scan: Command Centre paid
# a ~2-min live scan, watchlists live-scored every name, and readers without a
# fallback showed "n/a". A scan snapshot is current while it is under
# SCAN_MAX_AGE_SECONDS old, or while the market is shut and no session has
# opened since it was taken (prices have not moved since).
SCAN_MAX_AGE_SECONDS = 60 * 60          # 45-min cadence + a ~5-min run + slack
_IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
_OPEN, _CLOSE = datetime.time(9, 15), datetime.time(15, 30)


def _session_of(ts: datetime.datetime) -> datetime.date:
    """The NSE session whose prices a scan at ts saw (today once open, else the previous one)."""
    from utils.nse_holidays import is_trading_day
    n = ts.astimezone(_IST)
    d = n.date()
    if is_trading_day(d) and n.time() >= _OPEN:
        return d
    d -= datetime.timedelta(days=1)
    while not is_trading_day(d):
        d -= datetime.timedelta(days=1)
    return d


def market_open_at(ts: datetime.datetime) -> bool:
    """True during the NSE cash session (09:15-15:30 IST on a trading day)."""
    from utils.nse_holidays import is_trading_day
    n = ts.astimezone(_IST)
    return is_trading_day(n.date()) and _OPEN <= n.time() < _CLOSE


def scan_snapshot_current(gen_at: Any, now: Optional[datetime.datetime] = None,
                          max_age_seconds: float = SCAN_MAX_AGE_SECONDS) -> bool:
    """True when an intraday scan snapshot still describes the market (see FIX SCAN-CADENCE)."""
    ts = parse_snapshot_timestamp(gen_at)
    if ts is None:
        return False
    now = now or datetime.datetime.now(datetime.timezone.utc)
    age = (now - ts).total_seconds()
    if age <= max_age_seconds:          # a future stamp (clock skew) counts as fresh, as before
        return True
    return not market_open_at(now) and _session_of(ts) == _session_of(now)


def ist_label(gen_at: Any, fmt: str = "%a %d %b %H:%M IST") -> str:
    """A generated_at (aware UTC, or legacy naive UTC) as IST display text; '' if unparseable.
    Slicing the ISO string showed the UTC clock (a 10:20 IST scan read "04:50")."""
    ts = parse_snapshot_timestamp(gen_at)
    return ts.astimezone(_IST).strftime(fmt) if ts else ""
