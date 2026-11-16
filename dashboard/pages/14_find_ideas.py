"""Find Ideas - NSE Smart Investor.

Smart Screener and the Trend Quality Score scanner on one page (merged
2026-11-09). Both run universe scans, so a view switch at the top runs only
the chosen one. View bodies live in dashboard/views/.
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
render_sidebar(current="Find Ideas")
render_top_bar()

_KEY, _VIEWS = _PAGE_VIEWS["Find Ideas"]
_view = view_switch(_KEY, _VIEWS)

if _view == _VIEWS[0]:
    from dashboard.views import smart_screener
    smart_screener.render()
else:
    from dashboard.views import tqs_scanner
    tqs_scanner.render()
