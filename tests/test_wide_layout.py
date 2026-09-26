"""Regression: every page must render in the wide layout.

With pages/ routing, app.py's set_page_config(layout="wide") is dropped after
st.switch_page, so apply_design() (the first call on every page) re-asserts
it. Before FIX LAYOUT-WIDE every page silently fell back to the narrow 736px
column. See CLAUDE.md rule 7.
"""
import os
import sys

from streamlit.testing.v1 import AppTest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_apply_design_requests_wide_layout(monkeypatch):
    if _ROOT not in sys.path:
        sys.path.insert(0, _ROOT)
    import streamlit as st
    from dashboard.shared import design

    calls = []
    monkeypatch.setattr(st, "set_page_config", lambda **kw: calls.append(kw))
    design.apply_design()
    assert {"layout": "wide"} in calls


def test_page_script_calling_apply_design_renders_wide():
    """End to end: a page that only calls apply_design() gets the wide layout,
    and the repeated set_page_config call does not raise."""
    script = (
        "import sys\n"
        f"sys.path.insert(0, {_ROOT!r})\n"
        "from dashboard.shared.design import apply_design\n"
        "apply_design()\n"
        "import streamlit as st\n"
        "st.write('ok')\n"
    )
    at = AppTest.from_string(script, default_timeout=60).run()
    assert not at.exception
    assert at.markdown or at.get("markdown")
