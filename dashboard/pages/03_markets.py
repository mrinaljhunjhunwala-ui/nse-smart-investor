"""Markets - NSE Smart Investor.

One page for the market-wide views (merged 2026-11-09): Live Ticker,
Breadth & Macro (the old Market Breadth page) and FII / DII Flows. Each view
does its own live fetches, so a view switch runs only the chosen one rather
than tabs, which would run all three on every rerun. View bodies live in
dashboard/views/. Other pages open a view with nav.request_view("Markets", label)
or the old page name (e.g. _goto_page = "🏦 FII / DII Flows").
"""
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from dashboard.shared.design import apply_design  # noqa: E402
from dashboard.shared.nav import _PAGE_VIEWS, render_sidebar  # noqa: E402
from dashboard.shared.chart_helpers import render_top_bar  # noqa: E402
from dashboard.views import view_switch  # noqa: E402

apply_design()
render_sidebar(current="Markets")
render_top_bar()

_KEY, _VIEWS = _PAGE_VIEWS["Markets"]
_view = view_switch(_KEY, _VIEWS)

if _view == _VIEWS[0]:
    from dashboard.views import market_live
    market_live.render()
elif _view == _VIEWS[1]:
    from dashboard.views import market_breadth
    market_breadth.render()
else:
    from dashboard.views import fii_dii_flows
    fii_dii_flows.render()
