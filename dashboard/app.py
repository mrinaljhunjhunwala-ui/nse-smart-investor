"""
dashboard/app.py — NSE Smart Investor Platform (multipage entry point)

This file is intentionally thin. The UI lives in:
    dashboard/shared/   design.py · nav.py · cache.py · trade_utils.py · chart_helpers.py
    dashboard/pages/    01_market_live.py … 17_angel_one.py

app.py only:
    1. calls st.set_page_config (ONCE per session — must not appear in any page)
    2. applies the NSE Pro theme (CSS + Plotly template)
    3. redirects to the Command Centre as the default landing page

Run:
    streamlit run dashboard/app.py
"""

import os
import sys

# ── ensure project root is on sys.path (app.py lives in dashboard/) ───────────
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import streamlit as st

# ── Page config — the ONLY st.set_page_config call in the whole app ───────────
st.set_page_config(
    page_title="NSE Smart Investor",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

from dashboard.shared.design import apply_design

apply_design()

# Default landing → Command Centre. Streamlit's own pages/ nav is hidden via
# .streamlit/config.toml (showSidebarNavigation = false); custom nav lives in
# render_sidebar(). Each page renders its own sidebar + top bar.
st.switch_page("pages/02_command_centre.py")
