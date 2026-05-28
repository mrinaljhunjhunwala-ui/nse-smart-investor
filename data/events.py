"""
data/events.py
Earnings and corporate events filter for NSE equities.

Key functions
─────────────
    get_earnings_date(ticker)                → Optional[datetime]
    earnings_within_days(ticker, days)       → bool
    get_earnings_calendar(tickers)           → pd.DataFrame
    should_skip_entry(ticker, days_buffer)   → dict (with reason)

Why this matters
────────────────
    Entering a new position within 1 week of earnings results is a gamble,
    not a trade.  Gap-ups / gap-downs of 5-20% on results day can wipe out
    a carefully constructed R:R.  This module flags such tickers so
    scan_tickers() can suppress new entries near earnings events.

Data source
───────────
    yfinance `.calendar` attribute — contains 'Earnings Date' for US-listed
    and many NSE ADR tickers.  For pure NSE tickers (.NS), yfinance often
    returns an empty calendar, so we fall back to a "unknown, assume safe"
    policy rather than blocking all NSE stocks.
"""

from __future__ import annotations

import warnings
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
import yfinance as yf

warnings.filterwarnings("ignore")


# ─────────────────────────────────────────────────────────────────────────────
# Earnings date fetch
# ─────────────────────────────────────────────────────────────────────────────

def get_earnings_date(ticker: str) -> Optional[datetime]:
    """
    Fetch the next upcoming earnings date for a ticker via yfinance.

    Returns:
        datetime if a future earnings date is found, else None.

    Notes:
        - yfinance .calendar is unreliable for .NS tickers.
        - Returns None (not blocking) when data is unavailable.
    """
    try:
        info     = yf.Ticker(ticker)
        calendar = info.calendar          # dict or DataFrame depending on version
        today    = datetime.now().date()

        # yfinance ≥ 0.2: calendar is a dict with 'Earnings Date' key
        if isinstance(calendar, dict):
            ed = calendar.get("Earnings Date")
            if ed is None:
                return None
            # May be a list (range) or a single value
            if isinstance(ed, (list, tuple)):
                dates = [pd.to_datetime(d).date() for d in ed if pd.notna(d)]
            else:
                dates = [pd.to_datetime(ed).date()]
            future_dates = [d for d in dates if d >= today]
            return datetime.combine(future_dates[0], datetime.min.time()) if future_dates else None

        # Older yfinance: calendar is a DataFrame
        if isinstance(calendar, pd.DataFrame):
            if "Earnings Date" in calendar.index:
                ed_row = calendar.loc["Earnings Date"]
                if not ed_row.empty:
                    d = pd.to_datetime(ed_row.iloc[0]).date()
                    return datetime.combine(d, datetime.min.time()) if d >= today else None

        return None

    except Exception:
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Quick boolean check
# ─────────────────────────────────────────────────────────────────────────────

def earnings_within_days(ticker: str, days: int = 7) -> bool:
    """
    Return True if the ticker has earnings announced within the next `days` days.

    Used in scan_tickers() to suppress new BUY signals before results:

        if earnings_within_days(ticker, days=7):
            skip_signal()

    Returns False when earnings date is unknown (conservative — don't block).
    """
    ed = get_earnings_date(ticker)
    if ed is None:
        return False
    today  = datetime.now()
    return 0 <= (ed - today).days <= days


# ─────────────────────────────────────────────────────────────────────────────
# Batch calendar
# ─────────────────────────────────────────────────────────────────────────────

def get_earnings_calendar(tickers: List[str]) -> pd.DataFrame:
    """
    Fetch earnings dates for a list of tickers.

    Returns a DataFrame with columns:
        ticker, earnings_date, days_away, within_7d, within_14d
    Sorted by days_away ascending (soonest first).
    """
    today  = datetime.now()
    rows   = []
    for tkr in tickers:
        ed = get_earnings_date(tkr)
        if ed:
            diff = (ed - today).days
            rows.append({
                "ticker":       tkr,
                "earnings_date": ed.strftime("%Y-%m-%d"),
                "days_away":    diff,
                "within_7d":    diff <= 7,
                "within_14d":   diff <= 14,
            })
        else:
            rows.append({
                "ticker":       tkr,
                "earnings_date": "Unknown",
                "days_away":    999,
                "within_7d":    False,
                "within_14d":   False,
            })

    df = pd.DataFrame(rows).sort_values("days_away").reset_index(drop=True)
    return df


# ─────────────────────────────────────────────────────────────────────────────
# Entry gate — single ticker
# ─────────────────────────────────────────────────────────────────────────────

def should_skip_entry(
    ticker:      str,
    days_buffer: int = 7,
) -> Dict:
    """
    Decide whether to skip a new entry based on upcoming earnings.

    Returns:
    {
        "skip"        : bool,
        "reason"      : str,
        "earnings_date": str or None,
        "days_away"   : int or None,
    }

    Policy:
        skip=True  → earnings within days_buffer calendar days
        skip=False → earnings outside window, OR date unknown
    """
    ed = get_earnings_date(ticker)

    if ed is None:
        return {
            "skip":          False,
            "reason":        "Earnings date unknown — entry allowed (risk: unconfirmed).",
            "earnings_date": None,
            "days_away":     None,
        }

    days_away = (ed - datetime.now()).days

    if 0 <= days_away <= days_buffer:
        return {
            "skip":          True,
            "reason":        (f"Earnings in {days_away} day(s) on "
                              f"{ed.strftime('%d-%b-%Y')} — skip new entry to avoid results gap."),
            "earnings_date": ed.strftime("%Y-%m-%d"),
            "days_away":     days_away,
        }

    return {
        "skip":          False,
        "reason":        (f"Earnings in {days_away} day(s) — outside {days_buffer}d buffer, "
                          f"entry allowed."),
        "earnings_date": ed.strftime("%Y-%m-%d"),
        "days_away":     days_away,
    }


# ─────────────────────────────────────────────────────────────────────────────
# NSE quarterly results approximate schedule
# ─────────────────────────────────────────────────────────────────────────────

# For .NS tickers where yfinance returns no calendar, we can use the
# approximate Indian quarterly results seasons as a fallback blackout.
# Q1: Apr-Jun  → results in Jul-Aug
# Q2: Jul-Sep  → results in Oct-Nov
# Q3: Oct-Dec  → results in Jan-Feb
# Q4: Jan-Mar  → results in Apr-May

_RESULTS_SEASONS_MONTH_RANGE = [
    (7,  8),   # Q1 results July–August
    (10, 11),  # Q2 results October–November
    (1,  2),   # Q3 results January–February
    (4,  5),   # Q4 results April–May
]


def in_results_season() -> bool:
    """
    Return True if today falls within any of the four NSE quarterly
    results seasons (approximate; used as a conservative fallback).

    When True and earnings date is unknown, the caller may choose to
    be extra cautious and reduce position size.
    """
    month = datetime.now().month
    for start, end in _RESULTS_SEASONS_MONTH_RANGE:
        if start <= month <= end:
            return True
    return False
