"""
utils/point_in_time.py — run a scan "as of" a past trading date.

Used by the Tomorrow's Watchlist backfill (scripts/warm_tomorrow_watchlist.py
--as-of): while `point_in_time(D)` is active, every daily frame data.fetcher
hands out is cut to bars dated <= D, nse_delivery reads only rows dated <= D,
and analysis.score keys its benchmark / VIX / regime / FII-DII caches by D, so
nothing after D's close reaches the score.

The setting is PROCESS-WIDE on purpose, not a ContextVar: the scan fans out to
thread pools (cache._build_tomorrow_watchlist, analysis.sector_strength) that
would not inherit a context variable, and a missed cut there would leak today's
prices into a past day's list. Only the backfill script sets it, in its own
process. Never set it inside the Streamlit app.
"""
from __future__ import annotations

import contextlib
import datetime as _dt
import threading
from typing import Iterator, Optional

import pandas as pd

_LOCK = threading.Lock()
_AS_OF: Optional[_dt.date] = None


def as_of() -> Optional[_dt.date]:
    """The active point-in-time date, or None for a normal (live) run."""
    return _AS_OF


@contextlib.contextmanager
def point_in_time(d: Optional[_dt.date]) -> Iterator[Optional[_dt.date]]:
    """Make `d` the cut-off for every read until the block exits. None = live."""
    global _AS_OF
    if d is not None and not isinstance(d, _dt.date):
        raise TypeError(f"point_in_time needs a datetime.date, not {type(d).__name__}")
    if isinstance(d, _dt.datetime):
        d = d.date()
    with _LOCK:
        prev, _AS_OF = _AS_OF, d
    try:
        yield d
    finally:
        with _LOCK:
            _AS_OF = prev


def cut(df, d: Optional[_dt.date] = None):
    """`df` without rows dated after `d` (default: the active date). Frames that
    are not date-indexed, and every frame on a live run, come back unchanged."""
    d = d or _AS_OF
    if d is None or df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return df
    idx = df.index
    if not isinstance(idx, pd.DatetimeIndex):
        try:
            idx = pd.DatetimeIndex(pd.to_datetime(idx, errors="coerce"))
        except Exception:
            return df
    if idx.tz is not None:
        idx = idx.tz_localize(None)
    keep = idx.normalize() <= pd.Timestamp(d)
    if keep.all():
        return df
    out = df[keep]
    out.attrs = dict(getattr(df, "attrs", {}) or {})
    return out
