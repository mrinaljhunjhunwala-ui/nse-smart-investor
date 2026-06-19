"""
alerts/check_alerts_v2.py — Price alert engine (dependency-injected).

Reads alert rules from a CSV, checks live prices, sends Telegram notifications
when conditions are met. Designed for testability — Telegram sender and price
quoter are injected rather than imported as globals.

CSV format (alerts.csv):
    ticker, condition, level, enabled
    RELIANCE, above, 3000, 1
    TCS, below, 3500, 1

State dict format:
    {"price_{TICKER}_{condition}_{level:.2f}": "YYYY-MM-DD", ...}
    Used to prevent re-firing the same alert on the same day.

Usage:
    from alerts.check_alerts_v2 import check_price_alerts, prune_state
    fired = check_price_alerts(state, today, telegram, quoter)
"""
from __future__ import annotations

import csv
import logging
import os
from typing import Dict

_log = logging.getLogger("alerts.check_alerts_v2")

# Module-level path — monkeypatched in tests via monkeypatch.setattr
_ALERTS_CSV = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "alerts.csv",
)


def _state_key(ticker: str, condition: str, level: float) -> str:
    """Canonical dedup key for a fired alert."""
    return f"price_{ticker.upper()}_{condition}_{level:.2f}"


def check_price_alerts(
    state: Dict[str, str],
    today: str,
    telegram,
    quoter,
) -> int:
    """Check all enabled price alerts and fire any that trigger.

    Args:
        state:    Dedup dict {state_key: date_str}. Modified in-place.
        today:    ISO date string "YYYY-MM-DD" — used for dedup.
        telegram: Object with .send(text: str) -> bool method.
        quoter:   Object with .get_quote(ticker: str) -> {"price": float} | {}.

    Returns:
        Number of alerts fired this call.
    """
    if not os.path.exists(_ALERTS_CSV):
        _log.debug("check_price_alerts: alerts CSV not found at %s", _ALERTS_CSV)
        return 0

    fired = 0
    try:
        with open(_ALERTS_CSV, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    ticker    = row.get("ticker", "").strip().upper()
                    condition = row.get("condition", "").strip().lower()
                    level     = float(row.get("level", 0))
                    enabled   = int(row.get("enabled", 0))

                    if not ticker or condition not in ("above", "below") or not enabled:
                        continue

                    # Dedup — skip if already fired today
                    key = _state_key(ticker, condition, level)
                    if state.get(key) == today:
                        continue

                    # Fetch price
                    q = quoter.get_quote(ticker)
                    price = q.get("price") if isinstance(q, dict) else None
                    if price is None:
                        continue

                    price = float(price)

                    # Check condition
                    triggered = (
                        (condition == "above" and price > level) or
                        (condition == "below" and price < level)
                    )
                    if not triggered:
                        continue

                    # Fire alert
                    direction = "above" if condition == "above" else "below"
                    msg = (
                        f"🔔 Price Alert: {ticker} is {direction} ₹{level:,.2f}\n"
                        f"Current price: ₹{price:,.2f}"
                    )
                    telegram.send(msg)
                    state[key] = today
                    fired += 1
                    _log.info("alert fired: %s %s %.2f @ %.2f", ticker, condition, level, price)

                except Exception as _row_err:
                    _log.warning("check_price_alerts row error: %s", _row_err)

    except Exception as _e:
        _log.warning("check_price_alerts failed: %s", _e)

    return fired


def prune_state(state: Dict[str, str], today: str) -> Dict[str, str]:
    """Remove state entries that are not from today (stale dedup records).

    Args:
        state: Existing state dict.
        today: ISO date string "YYYY-MM-DD".

    Returns:
        New dict with only today's entries.
    """
    return {k: v for k, v in state.items() if v == today}
