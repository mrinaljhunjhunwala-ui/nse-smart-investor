"""
utils/market_hours.py — NSE market hours and session detection.
No external dependencies — uses stdlib datetime only.
"""

from __future__ import annotations
from datetime import datetime, timezone, timedelta, time as dtime


IST = timezone(timedelta(hours=5, minutes=30))

# NSE holidays 2026 (add more as needed)
NSE_HOLIDAYS_2026 = {
    (2026, 1, 26),   # Republic Day
    (2026, 3, 25),   # Holi
    (2026, 4, 2),    # Ram Navami
    (2026, 4, 14),   # Dr. Ambedkar Jayanti
    (2026, 5, 1),    # Maharashtra Day
    (2026, 8, 15),   # Independence Day
    (2026, 10, 2),   # Gandhi Jayanti
    (2026, 11, 4),   # Diwali (Laxmi Pujan)
    (2026, 12, 25),  # Christmas
}

MARKET_OPEN  = dtime(9, 15)
MARKET_CLOSE = dtime(15, 30)
PRE_OPEN     = dtime(9, 0)


def now_ist() -> datetime:
    return datetime.now(IST)


def is_market_open() -> bool:
    n = now_ist()
    if n.weekday() >= 5:
        return False
    if (n.year, n.month, n.day) in NSE_HOLIDAYS_2026:
        return False
    return MARKET_OPEN <= n.time() <= MARKET_CLOSE


def is_pre_open() -> bool:
    n = now_ist()
    if n.weekday() >= 5:
        return False
    return PRE_OPEN <= n.time() < MARKET_OPEN


def market_status() -> dict:
    n = now_ist()
    open_ = is_market_open()
    pre   = is_pre_open()
    if open_:
        status = "OPEN"
        color  = "🟢"
        detail = f"Closes at 3:30 PM IST"
    elif pre:
        status = "PRE-OPEN"
        color  = "🟡"
        detail = f"Market opens at 9:15 AM IST"
    elif n.weekday() >= 5:
        status = "CLOSED (Weekend)"
        color  = "🔴"
        detail = "Opens Monday 9:15 AM"
    elif n.time() < MARKET_OPEN:
        status = "CLOSED"
        color  = "🔴"
        detail = "Opens at 9:15 AM IST"
    else:
        status = "CLOSED"
        color  = "🔴"
        detail = "Reopens tomorrow 9:15 AM IST"
    return {
        "is_open":   open_,
        "is_pre":    pre,
        "status":    status,
        "color":     color,
        "detail":    detail,
        "time_ist":  n.strftime("%H:%M IST"),
        "day":       n.strftime("%A, %d %b %Y"),
    }


def refresh_interval_seconds() -> int:
    """Return recommended auto-refresh interval based on market status."""
    if is_market_open():
        return 180    # 3 min during market hours
    if is_pre_open():
        return 300    # 5 min during pre-open
    return 0          # no refresh outside market hours
