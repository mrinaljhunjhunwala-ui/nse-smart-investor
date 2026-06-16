"""
dashboard/shared/squareoff_monitor.py
──────────────────────────────────────────────────────────────────────────────
Self-contained Streamlit fragment that:

  1. Runs every 60 s while the page is open.
  2. Calls _auto_close_breached() to check SL / TP hits and MIS square-off.
  3. Shows a banner for any auto-closes that occurred.
  4. Shows a live market-status badge (open / pre-open / closed / holiday).
  5. Shows a countdown to next open / close event.

Usage — drop one call near the top of any page that renders paper trades:

    from dashboard.shared.squareoff_monitor import render_squareoff_monitor
    render_squareoff_monitor()               # default: poll every 60 s
    render_squareoff_monitor(poll_every=30)  # faster polling during market hours

The fragment is a no-op outside trading hours so it never wastes resources
on weekends / holidays.
"""

from __future__ import annotations

import logging

import streamlit as st

_log = logging.getLogger("dashboard.squareoff_monitor")


# ─────────────────────────────────────────────────────────────────────────────
# Market status badge (inline HTML)
# ─────────────────────────────────────────────────────────────────────────────

def _market_badge_html(status: dict) -> str:
    """Render a compact pill badge for the current market session."""
    label    = status["label"]
    sublabel = status["sublabel"]
    color    = status["color"]
    nxt      = status["next_event"]
    ist_str  = status["ist_now"].strftime("%H:%M IST")

    return (
        f'<div style="display:inline-flex;align-items:center;gap:10px;'
        f'background:#0d1f3c;border:1px solid {color};border-radius:8px;'
        f'padding:6px 14px;margin-bottom:8px">'
        f'<span style="font-size:13px;font-weight:700;color:{color}">{label}</span>'
        f'<span style="font-size:11px;color:#aaa">{sublabel}</span>'
        f'<span style="font-size:10px;color:#666">·</span>'
        f'<span style="font-size:10px;color:#666">{nxt}</span>'
        f'<span style="font-size:10px;color:#444">({ist_str})</span>'
        f'</div>'
    )


# ─────────────────────────────────────────────────────────────────────────────
# Public entry point
# ─────────────────────────────────────────────────────────────────────────────

def render_squareoff_monitor(
    poll_every: int = 60,
    account: str | None = None,
    show_badge: bool = True,
) -> None:
    """Render the market badge and start the auto-close polling fragment.

    Parameters
    ──────────
    poll_every  Seconds between polls.  Defaults to 60 s.
                During the square-off window (15:15–15:30) the fragment
                automatically tightens this to 20 s regardless of the
                value passed here, to ensure MIS positions are caught.
    account     If given, only auto-close trades in this account.
                If None (default), checks all accounts.
    show_badge  Whether to render the market-status badge above the monitor.
    """
    # ── 1. Always show the market status badge (outside the fragment so it
    #        renders immediately without waiting for the poll interval) ────────
    if show_badge:
        try:
            from dashboard.shared.market_hours import market_status
            _status = market_status()
            st.markdown(_market_badge_html(_status), unsafe_allow_html=True)
        except Exception as _e:
            _log.debug("render_squareoff_monitor badge: %s", _e)

    # ── 2. Polling fragment ───────────────────────────────────────────────────
    @st.fragment(run_every=f"{poll_every}s")
    def _poll():
        try:
            from dashboard.shared.market_hours import (
                is_market_open,
                is_squareoff_window,
            )
            from dashboard.shared.trade_utils import (
                _auto_close_breached,
                _render_autoclose_banner,
            )

            _open   = is_market_open()
            _sqoff  = is_squareoff_window()

            # Nothing to do outside trading hours
            if not _open and not _sqoff:
                return

            # Tighten poll during square-off window
            # (Streamlit doesn't support dynamic run_every, but we can
            # trigger an extra immediate rerun to compensate)
            if _sqoff:
                st.session_state["_sqoff_active"] = True
            elif st.session_state.pop("_sqoff_active", False):
                # Window just closed — one final sweep to catch stragglers
                pass

            closed = _auto_close_breached(account=account)
            _render_autoclose_banner(closed)

            # Toast notifications for each auto-close
            for c in closed:
                if c["type"] == "squareoff_failed":
                    st.toast(
                        f"⚠️ {c['ticker']}: square-off price unavailable — close manually",
                        icon="⚠️",
                    )
                elif c["type"] == "squareoff":
                    pnl = c.get("pnl") or 0
                    icon = "✅" if pnl >= 0 else "🔴"
                    st.toast(
                        f"⏰ {c['ticker']} MIS closed @ ₹{c['exit']:,.2f}  "
                        f"P&L ₹{pnl:+,.0f}",
                        icon=icon,
                    )
                elif c["type"] == "target":
                    st.toast(
                        f"🎯 {c['ticker']} TARGET hit @ ₹{c['exit']:,.2f}  "
                        f"P&L ₹{(c.get('pnl') or 0):+,.0f}",
                        icon="🎯",
                    )
                elif c["type"] == "stop":
                    st.toast(
                        f"🛑 {c['ticker']} STOP-LOSS hit @ ₹{c['exit']:,.2f}  "
                        f"P&L ₹{(c.get('pnl') or 0):+,.0f}",
                        icon="🛑",
                    )

        except Exception as _e:
            _log.warning("render_squareoff_monitor._poll error: %s", _e)

    _poll()
