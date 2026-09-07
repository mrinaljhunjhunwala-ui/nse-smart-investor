"""
dashboard/app.py — NSE Smart Investor Platform (multipage entry point)

This file is intentionally thin. The UI lives in:
    dashboard/shared/   design.py · nav.py · cache.py · trade_utils.py · chart_helpers.py
    dashboard/pages/    01_market_live.py … 17_tomorrow_watchlist.py

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


# ─────────────────────────────────────────────────────────────────────────────
# Promote [env] block from .streamlit/secrets.toml to os.environ.
# Streamlit Cloud secrets.toml keys are accessed via st.secrets["..."], NOT
# as environment variables. Score / positioning flags (NSE_USE_*), read via
# os.environ.get() in analysis.score, would otherwise stay dark on the
# hosted app. Reading here at process start makes the toml the single
# source of truth for the operator. Idempotent — os.environ.setdefault
# never clobbers an explicit shell export.
# ─────────────────────────────────────────────────────────────────────────────
def _promote_env_secrets() -> None:
    try:
        env_block = st.secrets.get("env")   # missing block returns None safely
    except Exception:
        return
    if not env_block:
        return
    try:
        for k, v in dict(env_block).items():
            if v is None:
                continue
            os.environ.setdefault(str(k), str(v))
    except Exception:
        # Silent by design — a broken secrets file must not crash startup.
        pass


_promote_env_secrets()


# ── Page config — the ONLY st.set_page_config call in the whole app ───────────
st.set_page_config(
    page_title="NSE Smart Investor",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

from dashboard.shared.design import apply_design

apply_design()


# ─────────────────────────────────────────────────────────────────────────────
# Task 2.4 F2 (audit docs/RENDER_SPEED_AUDIT_2026-09.md): on-import cache
# prime. The first visitor after a Streamlit Cloud redeploy or a container
# recycle used to pay a full ~2 min live scan because the process-local
# @st.cache_data caches AND the trade_store snapshot read both start cold.
#
# This fires get_top_picks() + get_vix_info() once in a daemon background
# thread the moment the container boots, so by the time a real user's page
# render calls those functions the snapshot read has already completed (and
# in the worst case the live scan is already in flight, still faster than
# waiting for the first user's request to trigger it).
#
# Idempotent by design:
#   - get_top_picks reads the trade_store snapshot first; if it exists it
#     returns instantly and the prime is a ~50 ms no-op.
#   - Streamlit's @st.cache_data key is the same regardless of which caller
#     hits it first, so a subsequent real request finds the primed result.
#   - Background thread; never blocks st.switch_page below.
#
# Safety:
#   - Prime runs exactly once per process, gated by module-level flag.
#   - Every failure path swallowed - a prime error must never break app
#     startup, only leave the cache cold as before.
#   - Guardrail 11 remains satisfied: analysis/ is not imported here; the
#     prime only calls dashboard/shared/cache.py helpers.
# ─────────────────────────────────────────────────────────────────────────────
# @st.cache_resource is the Streamlit-native "run this exactly once per
# process" primitive; the wrapped call returns the same Thread object on
# every rerun without re-firing the initializer. This is the correct gate
# (session_state was wrong here - it is per-user, not per-process, and
# would re-prime on every new visitor).
@st.cache_resource(show_spinner=False)
def _prime_hot_caches_bg():
    import threading

    def _worker() -> None:
        try:
            from dashboard.shared.cache import get_top_picks, get_vix_info
            # get_vix_info first (small, feeds get_top_picks's regime input)
            try:
                _vix = get_vix_info() or {}
                _regime = _vix.get("regime", "normal")
            except Exception:
                _regime = "normal"
            # Then the big one. If the trade_store snapshot exists this
            # returns in ~50 ms; if not it fires the ~2 min live scan in
            # this background thread, so the first real user still hits a
            # populated cache when they arrive.
            try:
                get_top_picks(vix_regime=_regime)
            except Exception:
                pass
        except Exception:
            # Never break startup on a prime failure.
            pass

    t = threading.Thread(target=_worker, name="cache-prime", daemon=True)
    t.start()
    return t


_prime_hot_caches_bg()


# Default landing → Command Centre. Streamlit's own pages/ nav is hidden via
# .streamlit/config.toml (showSidebarNavigation = false); custom nav lives in
# render_sidebar(). Each page renders its own sidebar + top bar.
st.switch_page("pages/02_command_centre.py")
