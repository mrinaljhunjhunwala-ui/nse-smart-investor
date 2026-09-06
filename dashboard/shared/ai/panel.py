"""
dashboard.shared.ai.panel — Streamlit chat UI for the AI co-pilot.

The ONLY module in dashboard/shared/ai/ that imports streamlit. Every other
piece (persona, context_builder, client, safety) is pure so we can test the
brain without spinning up a Streamlit runtime.

Public API: render_chat_panel(symbol, inputs, position=None, risk_rules=None)
"""
from __future__ import annotations

import streamlit as st

from .client import ChatSettings, CopilotUnavailable, Message, chat, is_available
from .context_builder import ContextInputs, Portfolio, RiskRules, build_context
from .persona import system_prompt
from .safety import filter_response


_HISTORY_KEY_TMPL = "ai_copilot_history::{symbol}"


def _get_history(symbol: str) -> list[dict[str, str]]:
    key = _HISTORY_KEY_TMPL.format(symbol=symbol)
    if key not in st.session_state:
        st.session_state[key] = []
    return st.session_state[key]


def _reset_history(symbol: str) -> None:
    st.session_state[_HISTORY_KEY_TMPL.format(symbol=symbol)] = []


def render_chat_panel(
    symbol: str,
    inputs: ContextInputs,
    *,
    portfolio: Portfolio | None = None,
    risk_rules: RiskRules | None = None,
    heading: str = "AI Co-Pilot",
    expanded: bool | None = None,
) -> None:
    """Render the chat panel inside a Streamlit expander.

    The caller passes:
      symbol      — the stock the user is looking at
      inputs      — collected dashboard state (from context_builder.collect_*)
      portfolio   — optional; the user's live position in this symbol
      risk_rules  — optional; the user's risk-management thresholds

    Both `portfolio` and `risk_rules` are merged into `inputs` before the
    context payload is built.
    """
    if portfolio is not None:
        inputs.portfolio = portfolio
    if risk_rules is not None:
        inputs.risk_rules = risk_rules

    # Expand by default when the key is available so users notice the panel.
    # When the key isn't set the expander stays collapsed but the diagnostic
    # message inside surfaces when clicked.
    _is_ok = is_available()
    _open = expanded if expanded is not None else _is_ok
    with st.expander(heading, expanded=_open):
        if not _is_ok:
            st.info(
                "AI co-pilot unavailable. Set `GROQ_API_KEY` in "
                "`.streamlit/secrets.toml` (local) or as a Repository secret in "
                "the Streamlit Cloud settings. Free key at https://console.groq.com."
            )
            return

        st.caption(
            f"Neutral analyst grounded in the live dashboard state for **{symbol}**. "
            "Not investment advice."
        )

        history = _get_history(symbol)

        # Replay prior turns for this symbol.
        for msg in history:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])

        prompt = st.chat_input(
            f"Ask about {symbol} — bull/bear, framework fit, why the score moved…",
            key=f"ai_input_{symbol}",
        )
        col_a, _ = st.columns([1, 6])
        with col_a:
            if st.button("Clear chat", key=f"ai_clear_{symbol}", use_container_width=True):
                _reset_history(symbol)
                st.rerun()

        if not prompt:
            return

        # Push user turn.
        history.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        # Build the outgoing message list: persona + context + last N turns.
        context_msg = build_context(inputs)
        outgoing: list[Message] = [
            Message(role="system", content=system_prompt()),
            Message(role="system", content=context_msg),
            *[Message(role=m["role"], content=m["content"]) for m in history[-6:]],
        ]

        # Call the provider.
        with st.chat_message("assistant"):
            with st.spinner("Thinking…"):
                try:
                    raw = chat(outgoing, settings=ChatSettings())
                except CopilotUnavailable as e:
                    st.error(f"Co-pilot error: {e}")
                    # Roll back the user turn — nothing to reply to.
                    history.pop()
                    return

            filtered = filter_response(raw)
            if filtered.blocked:
                st.warning("Response was filtered for safety.")
            st.markdown(filtered.text)

            history.append({"role": "assistant", "content": filtered.text})
