"""
utils/alerts_gmail.py - Task 4.1 (Q1 answer)

Gmail SMTP alert channel, mirroring utils/telegram.py's shape so
alerts/check_alerts.py can fan a single trigger out to both channels
without any per-channel special-casing.

Setup (never commit these):
    ALERT_GMAIL_ADDRESS      = your.address@gmail.com
    ALERT_GMAIL_APP_PASSWORD = 16-char app password from
                               myaccount.google.com/apppasswords
                               (NOT your real Gmail password)
    ALERT_GMAIL_TO           = recipient address (usually your own)

The three env vars are auto-promoted from .streamlit/secrets.toml's
[env] block on the app side; on GitHub Actions they come from
repository secrets exposed in the workflow YAML.

Design:
  * Standard library only (smtplib + email.message). No external dep.
  * send() returns bool - True on success, False on any failure. Never
    raises: alerting is a background concern, must not crash the caller.
  * Console-fallback when not configured, matching TelegramAlerter's
    contract so alerts/check_alerts.py stays symmetric.
"""
from __future__ import annotations

import logging
import os
import smtplib
import ssl
from email.message import EmailMessage
from typing import Optional

_log = logging.getLogger("utils.alerts_gmail")

_SMTP_HOST = "smtp.gmail.com"
_SMTP_PORT = 587    # STARTTLS


class GmailAlerter:
    """SMTP client for sending plain-text alert emails via Gmail."""

    def __init__(
        self,
        address:      Optional[str] = None,
        app_password: Optional[str] = None,
        to_address:   Optional[str] = None,
    ):
        self.address      = (address      or os.getenv("ALERT_GMAIL_ADDRESS", "")).strip()
        # Google's app-password display shows 4 groups of 4 separated by
        # spaces ("uiqu goej alxe kthc") and users legitimately copy it
        # either way. Gmail SMTP accepts both forms, but strip whitespace
        # so an accidental trailing newline / hidden space from copy-paste
        # doesn't turn a valid password into an auth failure.
        _pw_raw           =  app_password  or os.getenv("ALERT_GMAIL_APP_PASSWORD", "")
        self.app_password = "".join(str(_pw_raw).split())
        self.to_address   = (to_address   or os.getenv("ALERT_GMAIL_TO", "") or self.address).strip()

        if not self.address or not self.app_password or not self.to_address:
            self._console_only = True
            _log.info(
                "GmailAlerter: ALERT_GMAIL_* env not fully set - "
                "alerts will print to console instead of sending email."
            )
        else:
            self._console_only = False

    # ── Public API ────────────────────────────────────────────────────────

    def send(self, subject: str, body: str) -> bool:
        """Send one alert email. Returns True on success or console-fallback,
        False on SMTP failure. Never raises."""
        if self._console_only:
            print(f"\n  [Gmail CONSOLE]\n  Subject: {subject}\n{body}\n")
            return True
        try:
            msg = EmailMessage()
            msg["Subject"] = subject
            msg["From"]    = self.address
            msg["To"]      = self.to_address
            msg.set_content(body)
            ctx = ssl.create_default_context()
            with smtplib.SMTP(_SMTP_HOST, _SMTP_PORT, timeout=15) as smtp:
                smtp.ehlo()
                smtp.starttls(context=ctx)
                smtp.ehlo()
                smtp.login(self.address, self.app_password)
                smtp.send_message(msg)
            return True
        except Exception as e:
            # Do NOT log the app password on failure; only log the type +
            # a short message. app_password never appears in log output.
            _log.warning("GmailAlerter.send failed: %s: %s",
                         type(e).__name__, str(e)[:200])
            return False

    def send_signal(
        self,
        ticker:   str,
        action:   str,
        price:    float,
        sl:       Optional[float] = None,
        tp:       Optional[float] = None,
        strategy: str = "",
        reason:   str = "",
    ) -> bool:
        """Convenience mirror of TelegramAlerter.send_signal so callers
        that already speak that API can swap in a GmailAlerter."""
        import datetime
        now = datetime.datetime.now().strftime("%d %b %Y  %H:%M IST")
        icon = {"BUY": "[BUY]", "SELL": "[SELL]", "HOLD": "[HOLD]"}.get(
            action.upper(), "[SIG]")
        subject = f"{action.upper()} {ticker} at Rs.{price:,.2f}"
        body_lines = [
            f"{icon} {action.upper()} SIGNAL for {ticker}",
            "",
            f"Time     : {now}",
            f"Price    : Rs.{price:,.2f}",
        ]
        if sl is not None:
            body_lines.append(f"Stop-Loss: Rs.{sl:,.2f} ({(sl/price-1)*100:+.2f}%)")
        if tp is not None:
            body_lines.append(f"Target   : Rs.{tp:,.2f} ({(tp/price-1)*100:+.2f}%)")
        if sl is not None and tp is not None and abs(price - sl) > 0:
            rr = abs(tp - price) / abs(price - sl)
            body_lines.append(f"R:R      : 1 : {rr:.1f}")
        if strategy:
            body_lines.append(f"Strategy : {strategy}")
        if reason:
            body_lines.append(f"Reason   : {reason}")
        body_lines.append("")
        body_lines.append("For educational purposes only. Not investment advice.")
        return self.send(subject, "\n".join(body_lines))
