"""dashboard/views — bodies of pages that were merged into a parent page.

Each module exposes ``render()``, the old page's body moved verbatim. The
merged page (dashboard/pages/NN_*.py) owns apply_design(), render_sidebar()
and render_top_bar(), then picks which view(s) to render:

* ``view_switch`` (a segmented control) for heavy views — scans and live
  fetches — so only the chosen view runs on a rerun;
* ``st.tabs`` for light views that are fine to render together.

Streamlit is fine here (this is dashboard/, not analysis/).
"""
from __future__ import annotations

import streamlit as st


def view_switch(key: str, options: list[str]) -> str:
    """Segmented control choosing one of `options`; returns the chosen label.

    Another page (or the sidebar, via nav.request_view) can ask for a view by
    setting the one-shot flag ``st.session_state[f"_open_{key}"]`` before
    switching here. Clicking the selected segment again (which would leave
    nothing selected) keeps the previous view.
    """
    _wanted = st.session_state.pop(f"_open_{key}", None)
    if _wanted in options:
        st.session_state[key] = _wanted
    if st.session_state.get(key) not in options:
        st.session_state[key] = st.session_state.get(f"{key}__last") or options[0]

    def _keep_selection() -> None:
        if st.session_state.get(key) not in options:
            st.session_state[key] = st.session_state.get(f"{key}__last") or options[0]

    choice = st.segmented_control(
        "View", options, key=key, selection_mode="single",
        label_visibility="collapsed", on_change=_keep_selection,
    )
    if choice not in options:
        choice = options[0]
    st.session_state[f"{key}__last"] = choice
    return choice
