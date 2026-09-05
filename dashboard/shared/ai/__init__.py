"""
dashboard.shared.ai — in-app AI co-pilot.

Layered architecture (mirrors the ai-copilot-context skill):

    persona.py           layer 1 — static system prompt (persona + compliance)
    context_builder.py   layer 2 — per-turn dashboard state → JSON block
    client.py            provider-agnostic OpenAI-compatible chat client (Groq default)
    safety.py            output post-filter: catches accidental buy/sell language
    panel.py             layer 3 — Streamlit chat UI (the ONLY streamlit-aware module)

Public surface:

    from dashboard.shared.ai import render_chat_panel, ContextInputs, build_context

`render_chat_panel(symbol, inputs)` is what a page calls.  `ContextInputs` and
`build_context` are exposed for tests and for pages that want to preview the
context payload without launching the panel.
"""
from __future__ import annotations

from .context_builder import ContextInputs, build_context, collect_for_analyze_stock
from .panel import render_chat_panel

__all__ = [
    "ContextInputs",
    "build_context",
    "collect_for_analyze_stock",
    "render_chat_panel",
]
