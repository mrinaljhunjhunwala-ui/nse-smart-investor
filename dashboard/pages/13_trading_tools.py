"""Trading Tools - NSE Smart Investor.

Intraday Trader and Position Sizer on one page (merged 2026-11-09). Intraday
Trader does live fetches, so a view switch runs only the chosen view. View
bodies live in dashboard/views/.

Deep links into the Position Sizer:
  * nav.request_view("Trading Tools", "📐 Position Sizer") or the old
    _goto_page = "📐 Position Sizer" (Long-Term Quality uses that);
  * Analyze Stock's "Size Position" button sets ps_entry / ps_sl / ps_tp and
    switches here. New prefill values that this page has not seen yet open
    the Position Sizer view, so that button needs no flag of its own.
"""
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import streamlit as st  # noqa: E402

from dashboard.shared.design import apply_design  # noqa: E402
from dashboard.shared.nav import _PAGE_VIEWS, render_sidebar, request_view  # noqa: E402
from dashboard.shared.chart_helpers import render_top_bar  # noqa: E402
from dashboard.views import view_switch  # noqa: E402

apply_design()
render_sidebar(current="Trading Tools")
render_top_bar()

_KEY, _VIEWS = _PAGE_VIEWS["Trading Tools"]
_PS_KEYS = ("ps_entry", "ps_sl", "ps_tp")


def _ps_prefill() -> tuple:
    return tuple(st.session_state.get(k) for k in _PS_KEYS)


_prefill = _ps_prefill()
if any(v is not None for v in _prefill) and _prefill != st.session_state.get("_tt_ps_seen"):
    request_view("Trading Tools", _VIEWS[1])

_view = view_switch(_KEY, _VIEWS)

if _view == _VIEWS[0]:
    from dashboard.views import intraday_trader
    intraday_trader.render()
else:
    from dashboard.views import position_sizer
    position_sizer.render()

st.session_state["_tt_ps_seen"] = _ps_prefill()
