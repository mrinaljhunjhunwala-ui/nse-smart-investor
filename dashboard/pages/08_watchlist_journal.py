"""Watchlist & Journal - NSE Smart Investor.

My Watchlist and Stock Journal as two tabs (merged 2026-11-09). Both are light
(local store reads plus a capped live-price batch for the watchlist), so tabs
are fine here. View bodies live in dashboard/views/. Like the pages they
replace, this page is not PIN-gated (owner's choice, see HANDOFF.md).
"""
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import streamlit as st  # noqa: E402

from dashboard.shared.design import apply_design  # noqa: E402
from dashboard.shared.nav import render_sidebar  # noqa: E402
from dashboard.shared.chart_helpers import render_top_bar  # noqa: E402
from dashboard.views import my_watchlist, stock_journal  # noqa: E402

apply_design()
render_sidebar(current="Watchlist & Journal")
render_top_bar()

_tab_wl, _tab_journal = st.tabs(["⭐ My Watchlist", "📓 Stock Journal"])
with _tab_wl:
    my_watchlist.render()
with _tab_journal:
    stock_journal.render()
