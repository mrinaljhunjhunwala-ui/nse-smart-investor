"""
utils/market_hours.py — NSE market hours and session detection.

FIX MH2: this module used to maintain its OWN hardcoded, single-year
(2026-only) holiday calendar, completely independent of
dashboard/shared/market_hours.py's calendar. The two drifted — this file's
2026 dates for Holi, Ram Navami, and Diwali were all wrong, and it was
missing Mahavir Jayanti, Good Friday, Bakri Id, Muharram, Ganesh Chaturthi,
Dussehra, and Guru Nanak Jayanti outright. Every year it wasn't manually
extended it would also silently stop detecting ANY holiday at all.

This module is still imported directly by 5 files (dashboard/pages/
01_market_live.py, 04_analyze_stock.py, dashboard/shared/chart_helpers.py,
dashboard/shared/nav.py, dashboard/shared/trade_utils.py) — including
trade_utils.py's _is_market_open(), which is the primary gate for the
auto square-off / SL-TP auto-close logic. Rather than update all 5 call
sites (a wider, riskier change), this module now delegates ALL of its
open/closed/holiday logic to dashboard.shared.market_hours — the single
source of truth — while keeping its exact original function names,
signatures, and market_status() return-dict shape, so every existing
caller keeps working unchanged and automatically gets the correct calendar.
"""

from __future__ import annotations
from datetime import datetime, timezone, timedelta, time as dtime

from dashboard.shared.market_hours import (
    is_market_open as _canonical_is_open,
    is_preopen as _canonical_is_preopen,
    market_status as _canonical_status,
    NSE_HOLIDAYS as _CANONICAL_HOLIDAYS,   # kept importable for anything reading it directly
)

IST = timezone(timedelta(hours=5, minutes=30))

MARKET_OPEN  = dtime(9, 15)
MARKET_CLOSE = dtime(15, 30)
PRE_OPEN     = dtime(9, 0)


def now_ist() -> datetime:
    return datetime.now(IST)


def is_market_open() -> bool:
    return _canonical_is_open()


def is_pre_open() -> bool:
    return _canonical_is_preopen()


def market_status() -> dict:
    """Same return shape as before (is_open/is_pre/status/color/detail/
    time_ist/day) — now sourced from the corrected canonical calendar."""
    c = _canonical_status()
    n = c["ist_now"]

    session = c["session"]
    if session == "open":
        status = "OPEN"
    elif session == "preopen":
        status = "PRE-OPEN"
    elif session == "weekend":
        status = "CLOSED (Weekend)"
    elif session == "holiday":
        status = "CLOSED (Holiday)"
    else:
        status = "CLOSED"

    # Preserve the old emoji-only color convention (old callers expect a
    # plain 🟢/🟡/🔴, not the canonical module's hex color codes).
    color = "🟢" if session == "open" else ("🟡" if session == "preopen" else "🔴")

    return {
        "is_open":  c["is_open"],
        "is_pre":   session == "preopen",
        "status":   status,
        "color":    color,
        "detail":   c["next_event"],
        "time_ist": n.strftime("%H:%M IST"),
        "day":      n.strftime("%A, %d %b %Y"),
    }


def refresh_interval_seconds() -> int:
    """Return recommended auto-refresh interval based on market status."""
    if is_market_open():
        return 180    # 3 min during market hours
    if is_pre_open():
        return 300    # 5 min during pre-open
    return 0          # no refresh outside market hours
