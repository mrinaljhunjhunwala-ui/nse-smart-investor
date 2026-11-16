"""dashboard/shared/pin_gate.py — PIN lock for pages that touch a live broker account.

The app has no user login, so anyone who can open it (the private viewer list)
could see Angel One holdings/funds and place real orders (audit 2026-10-04,
replica-test S1). This gate sits in front of that page:

* PIN comes from ``[angel_one] page_pin`` in st.secrets, else ``ANGEL_PAGE_PIN``.
* Fails CLOSED: broker credentials configured but no PIN set → page stays locked
  with setup instructions, never silently open.
* Constant-time compare; after ``MAX_ATTEMPTS`` wrong PINs the gate locks for
  ``LOCKOUT_S`` seconds process-wide (a page reload can't reset it).
* An unlock lasts ``UNLOCK_TTL_S`` in this browser session, then asks again.
"""
from __future__ import annotations

import hmac
import os
import time
from typing import Dict, Optional

import streamlit as st

MAX_ATTEMPTS = 5
LOCKOUT_S = 300
UNLOCK_TTL_S = 15 * 60

# Process-wide failure tracking, keyed by gate scope: {"fails": int, "locked_until": float}
_FAILS: Dict[str, Dict[str, float]] = {}


def configured_pin() -> Optional[str]:
    """The owner's PIN, or None when none is set."""
    pin = None
    try:
        # Same single read point angel_fetcher uses for [angel_one] (tests blank it).
        from data.angel_fetcher import _secrets_section
        pin = _secrets_section().get("page_pin")
    except Exception:   # no secrets file at all
        pin = None
    pin = pin or os.environ.get("ANGEL_PAGE_PIN")
    pin = str(pin).strip() if pin is not None else ""
    return pin or None


def lockout_remaining(scope: str, now: Optional[float] = None) -> int:
    now = time.time() if now is None else now
    until = _FAILS.get(scope, {}).get("locked_until", 0.0)
    return max(0, int(round(until - now)))


def check_pin(scope: str, entered: str, expected: str, now: Optional[float] = None) -> str:
    """"ok", "wrong" or "locked". Pure apart from the module-level counter."""
    now = time.time() if now is None else now
    if lockout_remaining(scope, now):
        return "locked"
    if hmac.compare_digest(str(entered).strip().encode(), str(expected).encode()):
        _FAILS.pop(scope, None)
        return "ok"
    rec = _FAILS.setdefault(scope, {"fails": 0, "locked_until": 0.0})
    rec["fails"] += 1
    if rec["fails"] >= MAX_ATTEMPTS:
        rec["fails"] = 0
        rec["locked_until"] = now + LOCKOUT_S
        return "locked"
    return "wrong"


def _unlock_key(scope: str) -> str:
    return f"_pin_unlocked_at_{scope}"


def is_unlocked(scope: str, now: Optional[float] = None) -> bool:
    now = time.time() if now is None else now
    at = st.session_state.get(_unlock_key(scope))
    return at is not None and (now - float(at)) < UNLOCK_TTL_S


def relock(scope: str) -> None:
    st.session_state.pop(_unlock_key(scope), None)


def require_pin(scope: str = "angel_one", label: str = "Angel One",
                guards: str = "holdings and funds and place real orders") -> None:
    """Render the PIN form and st.stop() until this session is unlocked.

    `guards` finishes "This page can show/edit …" in the locked message, so a
    gate on a non-broker page doesn't talk about orders."""
    if is_unlocked(scope):
        return

    expected = configured_pin()
    if expected is None:
        st.error(
            f"🔒 **{label} is locked.** This page can show {guards}, "
            "so it needs a PIN before it opens."
        )
        st.markdown(
            "Add a PIN to the app's secrets (Streamlit Cloud → App settings → Secrets, "
            "or `.streamlit/secrets.toml` locally), inside the existing block:"
        )
        st.code('[angel_one]\npage_pin = "choose-a-pin"', language="toml")
        st.stop()

    st.markdown(f"#### 🔒 {label} is PIN-protected")
    st.caption("Opens after the owner's PIN. "
               f"The unlock lasts {UNLOCK_TTL_S // 60} minutes in this browser.")
    left = lockout_remaining(scope)
    if left:
        st.error(f"Too many wrong PINs. Try again in {left // 60}m {left % 60:02d}s.")
        st.stop()

    _pin_form(scope, expected, f"pin_form_{scope}", f"pin_input_{scope}")
    st.stop()


def _pin_form(scope: str, expected: str, form_key: str, input_key: str) -> None:
    """The PIN box + Unlock button; on the right PIN it unlocks `scope` and reruns."""
    with st.form(form_key, clear_on_submit=True):
        entered = st.text_input("PIN", type="password", key=input_key)
        submitted = st.form_submit_button("Unlock")
    if submitted:
        result = check_pin(scope, entered, expected)
        if result == "ok":
            st.session_state[_unlock_key(scope)] = time.time()
            st.rerun()
        elif result == "locked":
            st.error(f"Too many wrong PINs. Locked for {LOCKOUT_S // 60} minutes.")
        else:
            st.error("Wrong PIN.")


def unlock_inline(scope: str, label: str, where: str, *, collapsible: bool = True) -> bool:
    """True when `scope` is unlocked; otherwise show a small PIN box right here.

    For places that only *read* locked data (Today's lists, Research Notes, the
    sidebar quick view, Analyze Stock): the owner unlocks in place instead of
    walking to My Portfolio / Angel One first. Same PIN, same lockout, same
    15-minute unlock, so the page gates themselves are not weakened. Never
    st.stop()s, so the rest of the page keeps rendering. `where` keeps widget
    keys unique when one page shows several boxes."""
    try:
        if is_unlocked(scope):
            return True
        expected = configured_pin()
    except Exception:
        return False
    if expected is None:
        st.caption(f"🔒 {label} is locked and no PIN is set yet. Add `page_pin` under "
                   "`[angel_one]` in the app's secrets.")
        return False
    left = lockout_remaining(scope)

    def _body():
        if left:
            st.caption(f"Too many wrong PINs. Try again in {left // 60}m {left % 60:02d}s.")
            return
        st.caption(f"Enter the owner PIN. The unlock lasts {UNLOCK_TTL_S // 60} minutes in this browser.")
        _pin_form(scope, expected, f"pin_inline_{scope}_{where}", f"pin_inline_in_{scope}_{where}")

    if collapsible:
        with st.expander(f"🔒 Unlock {label} to include it here"):
            _body()
    else:
        st.caption(f"🔒 {label} is locked.")
        _body()
    return False


def holdings_unlocked() -> bool:
    """True once this browser session has unlocked My Portfolio. Every other
    place that reads the manual holdings (sidebar quick view, Analyze Stock's
    position / portfolio fit) checks this, so a locked session never sees them."""
    try:
        return is_unlocked("my_portfolio")
    except Exception:
        return False
