"""Display labels for internal CompositeScore action / FinalVerdict strings.

Owner decision, 13 Nov 2026: this app is a purely personal tool, so what a
person reads is direct BUY / SELL / HOLD wording ("Strong trend" was the wrong
word for a pick). That replaces the earlier descriptive-label convention for
display copy only.

The engine's action strings ("STRONG BUY", "EXIT", ...) and FinalVerdict
values are internal keys (DB, CSV export, ledger, sort keys, dedupe / state
keys, signal logic) and are NEVER changed here. Anything a person reads —
dashboard pages, Telegram/Gmail alerts — goes through action_display_label()
/ verdict_display_label().

Pure module (no Streamlit) so alerts/ can use it without importing the UI.
"""

ACTION_DISPLAY_LABELS = {
    "STRONG BUY": "STRONG BUY",
    "BUY":        "BUY",
    "WATCHLIST":  "WATCH",
    "HOLD":       "HOLD",
    "CAUTION":    "REDUCE",
    "EXIT":       "SELL",
    "SELL":       "SELL",   # legacy alias from signals.py
}


def action_display_label(action: str) -> str:
    """Display label for an internal action string; unknown values pass through."""
    return ACTION_DISPLAY_LABELS.get(action, action)


# FinalVerdict (analysis/final_verdict.VERDICTS) → display label.
VERDICT_DISPLAY_LABELS = {
    "STRONG BUY": "STRONG BUY",
    "BUY":        "BUY",
    "WATCH":      "WATCH",
    "HOLD":       "HOLD",
    "AVOID":      "AVOID / SELL",
    "INSUFFICIENT_DATA": "Not enough fundamental data",   # long lens only; non-directional
}


def verdict_display_label(verdict: str) -> str:
    """Display label for a FinalVerdict value."""
    return VERDICT_DISPLAY_LABELS.get(verdict, verdict)


__all__ = ["ACTION_DISPLAY_LABELS", "action_display_label",
           "VERDICT_DISPLAY_LABELS", "verdict_display_label"]
