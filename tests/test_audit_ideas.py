"""Audit follow-up ideas: VIX change labelled by its bar's date, and My lists
naming the Tomorrow's Watchlist scan its ranks come from."""
from __future__ import annotations

import datetime

import pandas as pd

from utils.snapshot_time import bar_change_label

_IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30))


def test_change_is_today_only_for_todays_bar():
    now = datetime.datetime(2026, 11, 17, 11, 0, tzinfo=_IST)
    assert bar_change_label(pd.Timestamp("2026-11-17"), now) == "today"


def test_pre_open_change_names_the_previous_session():
    now = datetime.datetime(2026, 11, 17, 8, 30, tzinfo=_IST)       # Tuesday, before the open
    assert bar_change_label(pd.Timestamp("2026-11-16"), now) == "on Mon 16 Nov"


def test_weekend_and_utc_now():
    now = datetime.datetime(2026, 11, 22, 4, 0, tzinfo=datetime.timezone.utc)   # Sunday
    assert bar_change_label("2026-11-20", now) == "on Fri 20 Nov"
    assert bar_change_label(None, now) == "vs previous session"
