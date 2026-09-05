"""
dashboard.shared.ai.safety — output post-filter for the AI co-pilot.

The system prompt tells the model not to issue buy/sell/hold instructions, but
prompts leak. This module scans the model's response for advice-shaped language
and either:

  * BLOCKS the response (returns a fallback string) if the language is a direct
    instruction ("you should buy X"), OR
  * PASSES the response through unchanged if the language is descriptive
    ("the composite score suggests bullish momentum" is fine — describes data,
    doesn't tell the user what to do).

Also enforces the educational disclaimer at the tail — if the model forgot it,
we append.

Pure module: no I/O, no Streamlit, no external calls. Fully unit-testable.
"""
from __future__ import annotations

import re
from typing import NamedTuple


# Direct-instruction patterns. Case-insensitive, word-boundaried.
# Each pattern matches an *imperative or personal directive*: someone telling
# the user to take an action.
_INSTRUCTION_PATTERNS = [
    # imperatives directed at the user
    r"\byou\s+should\s+(buy|sell|hold|short|add|trim|exit|enter|book|square)\b",
    r"\byou\s+(must|need\s+to)\s+(buy|sell|hold|short|add|trim|exit|enter|book|square)\b",
    r"\b(i\s+)?(recommend|suggest)\s+(buying|selling|shorting|holding|entering|exiting)\b",
    r"\bmy\s+recommendation\s+is\s+(to\s+)?(buy|sell|hold|short|exit|enter)\b",
    # bare imperatives at start of a sentence
    r"(?:^|[.!?]\s+)(buy|sell|short|exit|enter|book|trim|add\s+to)\s+(this|it|the\s+stock|now|today|at\s+)",
    # explicit "buy/sell recommendation" wording
    r"\b(buy|sell|hold)\s+recommendation\b",
    # target-price-as-advice ("target X, buy at Y" or "PT ₹X buy")
    r"target[:\s]+₹?[\d,]+\s*(?:,|\.|;)?\s*(buy|accumulate|enter)",
]

_INSTRUCTION_RE = re.compile("|".join(_INSTRUCTION_PATTERNS), re.IGNORECASE)

DISCLAIMER = "Educational analysis only — not SEBI-registered investment advice."

_FALLBACK_MESSAGE = (
    "I caught myself about to give a directional recommendation, which I'm not "
    "allowed to do. Ask me instead:\n"
    "- What does the composite score break down to?\n"
    "- What's the bull case and bear case from the current data?\n"
    "- What framework applies to this setup (e.g. risk-reward-ratio, "
    "position-sizing)?\n\n"
    f"{DISCLAIMER}"
)


class FilterResult(NamedTuple):
    text: str
    blocked: bool
    reason: str  # empty when not blocked


def filter_response(text: str) -> FilterResult:
    """Post-filter an LLM response.

    Returns a FilterResult:
      * .text     — the safe text to surface to the user
      * .blocked  — True if the original response was rejected and replaced
      * .reason   — short human-readable explanation of the block (empty on pass)

    Rules:
      1. If a direct instruction pattern matches, replace with the fallback.
      2. Otherwise ensure the disclaimer is present; append if missing.
    """
    if not text:
        return FilterResult(text=_FALLBACK_MESSAGE, blocked=True, reason="empty response")

    match = _INSTRUCTION_RE.search(text)
    if match:
        return FilterResult(
            text=_FALLBACK_MESSAGE,
            blocked=True,
            reason=f"matched instruction pattern: {match.group(0)!r}",
        )

    if DISCLAIMER not in text:
        text = text.rstrip() + "\n\n" + DISCLAIMER

    return FilterResult(text=text, blocked=False, reason="")
