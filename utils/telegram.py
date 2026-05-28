"""
utils/telegram.py — Phase 4b
Telegram Bot integration for trade signal alerts.

Set these in your environment (or .env file) before using:
    TELEGRAM_BOT_TOKEN   =  your bot token from @BotFather
    TELEGRAM_CHAT_ID     =  your chat / channel ID

Obtain your chat ID by messaging your bot and calling:
    https://api.telegram.org/bot<TOKEN>/getUpdates

Usage:
    from utils.telegram import TelegramAlerter
    alert = TelegramAlerter()
    alert.send_signal("RELIANCE.NS", "BUY", 2850.0, sl=2790.0, tp=2970.0)
"""

import os
import json
import datetime
import requests
from typing import Optional


class TelegramAlerter:
    """Sends formatted trade-signal messages to a Telegram chat/channel."""

    BASE_URL = "https://api.telegram.org/bot{token}/{method}"

    def __init__(
        self,
        token: Optional[str] = None,
        chat_id: Optional[str] = None,
    ):
        self.token   = token   or os.getenv("TELEGRAM_BOT_TOKEN", "")
        self.chat_id = chat_id or os.getenv("TELEGRAM_CHAT_ID",   "")

        if not self.token or not self.chat_id:
            print(
                "  [Telegram] WARNING: BOT_TOKEN or CHAT_ID not set.\n"
                "  Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID env vars to enable alerts.\n"
                "  Alerts will be printed to console instead."
            )
            self._console_only = True
        else:
            self._console_only = False

    # ── Public API ─────────────────────────────────────────────────────────────

    def send_signal(
        self,
        ticker:   str,
        action:   str,          # "BUY" | "SELL" | "HOLD"
        price:    float,
        sl:       Optional[float] = None,
        tp:       Optional[float] = None,
        strategy: str = "",
        reason:   str = "",
    ) -> bool:
        """
        Send a formatted trade signal.

        Args:
            ticker:   e.g. "RELIANCE.NS"
            action:   "BUY", "SELL", or "HOLD"
            price:    Current / entry price in INR
            sl:       Stop-loss level
            tp:       Take-profit level
            strategy: Strategy name for context
            reason:   Brief reason string

        Returns:
            True if message sent (or printed), False on API error.
        """
        now  = datetime.datetime.now().strftime("%d %b %Y  %H:%M IST")
        icon = {"BUY": "🟢", "SELL": "🔴", "HOLD": "🟡"}.get(action.upper(), "⚪")

        lines = [
            f"{icon} *{action.upper()} SIGNAL — {ticker}*",
            f"━━━━━━━━━━━━━━━━━━━━━━",
            f"📅 {now}",
            f"💰 Price    : ₹{price:,.2f}",
        ]
        if sl:  lines.append(f"🛡 Stop-Loss : ₹{sl:,.2f}  ({(sl/price-1)*100:+.2f}%)")
        if tp:  lines.append(f"🎯 Target    : ₹{tp:,.2f}  ({(tp/price-1)*100:+.2f}%)")
        if sl and tp:
            rr = abs(tp - price) / abs(price - sl) if abs(price - sl) > 0 else 0
            lines.append(f"📊 R:R       : 1 : {rr:.1f}")
        if strategy: lines.append(f"⚙️ Strategy  : {strategy}")
        if reason:   lines.append(f"📝 Reason    : {reason}")
        lines.append(f"━━━━━━━━━━━━━━━━━━━━━━")
        lines.append("_⚠️ For educational purposes only. Not investment advice._")

        message = "\n".join(lines)
        return self._send(message)

    def send_portfolio_summary(self, summary: dict) -> bool:
        """
        Send a portfolio daily summary.

        Args:
            summary: dict with keys: date, portfolio_value, daily_pnl, open_trades
        """
        pnl_icon = "📈" if summary.get("daily_pnl", 0) >= 0 else "📉"
        lines = [
            f"📋 *PORTFOLIO SUMMARY*",
            f"━━━━━━━━━━━━━━━━━━━━━━",
            f"📅 {summary.get('date', '')}",
            f"💼 Value    : ₹{summary.get('portfolio_value', 0):,.0f}",
            f"{pnl_icon} Day P&L  : ₹{summary.get('daily_pnl', 0):+,.0f}",
            f"📂 Open     : {summary.get('open_trades', 0)} positions",
            f"━━━━━━━━━━━━━━━━━━━━━━",
        ]
        return self._send("\n".join(lines))

    def send_text(self, text: str) -> bool:
        """Send raw text message."""
        return self._send(text)

    # ── Internal ───────────────────────────────────────────────────────────────

    def _send(self, text: str) -> bool:
        if self._console_only:
            print(f"\n  [Telegram CONSOLE]\n{text}\n")
            return True

        url = self.BASE_URL.format(token=self.token, method="sendMessage")
        payload = {
            "chat_id":    self.chat_id,
            "text":       text,
            "parse_mode": "Markdown",
        }
        try:
            resp = requests.post(url, json=payload, timeout=10)
            if resp.status_code == 200:
                return True
            print(f"  [Telegram] Error {resp.status_code}: {resp.text[:200]}")
            return False
        except requests.RequestException as e:
            print(f"  [Telegram] Network error: {e}")
            return False
