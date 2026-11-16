"""Watchlist & Notes - NSE Smart Investor.

My Watchlist and Research Notes as two tabs. Research Notes replaced the Stock
Journal tab on 2026-11-17 (owner: the journal had no use; journal entries stay
in data/stock_journal.csv and the weekly digest still reads them). View bodies
live in dashboard/views/. The page is not PIN-gated (owner's choice, see
HANDOFF.md); the portfolio briefing inside Research Notes needs the My Portfolio
PIN. Arriving from Analyze Stock ("Open in Research Notes") puts that tab first.
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
from dashboard.views import my_watchlist, research_notes  # noqa: E402

apply_design()
render_sidebar(current="Watchlist & Notes")
render_top_bar()

_views = [("⭐ My Watchlist", my_watchlist.render), ("📝 Research Notes", research_notes.render)]
if st.session_state.get("rn_ticker"):
    _views.reverse()
for _tab, (_label, _render) in zip(st.tabs([v[0] for v in _views]), _views):
    with _tab:
        _render()
