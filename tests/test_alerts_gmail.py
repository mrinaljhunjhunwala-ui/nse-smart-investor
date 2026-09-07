"""
tests/test_alerts_gmail.py - Task 4.1

Covers the pure-Python surface of utils/alerts_gmail.py + the dispatcher
in alerts/check_alerts.py. Does NOT talk to Gmail's SMTP server - the
socket-level send is monkey-patched and asserted on the argument shape.
"""
from __future__ import annotations

import io
import os
import re
import sys
from contextlib import redirect_stdout
from unittest import mock

import pytest


# ─────────────────────────────────────────────────────────────────────────────
# GmailAlerter
# ─────────────────────────────────────────────────────────────────────────────

def test_gmail_console_fallback_when_unconfigured(monkeypatch):
    """No env vars set -> console mode, send returns True, prints subject."""
    for k in ("ALERT_GMAIL_ADDRESS", "ALERT_GMAIL_APP_PASSWORD", "ALERT_GMAIL_TO"):
        monkeypatch.delenv(k, raising=False)
    from utils.alerts_gmail import GmailAlerter
    a = GmailAlerter()
    assert a._console_only is True
    buf = io.StringIO()
    with redirect_stdout(buf):
        ok = a.send("VIX PANIC", "India VIX at 32.4")
    assert ok is True
    assert "Gmail CONSOLE" in buf.getvalue()
    assert "VIX PANIC" in buf.getvalue()
    assert "32.4" in buf.getvalue()


def test_gmail_sends_via_smtp_when_configured(monkeypatch):
    """All three env vars set -> real send path. SMTP is mocked; we assert
    starttls + login + send_message all happen, and that the message
    carries the given subject/body/to/from."""
    monkeypatch.setenv("ALERT_GMAIL_ADDRESS",      "test@example.com")
    monkeypatch.setenv("ALERT_GMAIL_APP_PASSWORD", "not-a-real-secret")
    monkeypatch.setenv("ALERT_GMAIL_TO",           "test@example.com")
    from utils.alerts_gmail import GmailAlerter

    smtp_instance = mock.MagicMock()
    smtp_instance.__enter__.return_value = smtp_instance
    with mock.patch("utils.alerts_gmail.smtplib.SMTP", return_value=smtp_instance) as smtp_cls:
        a = GmailAlerter()
        assert a._console_only is False
        ok = a.send("BUY RELIANCE", "Reliance BUY signal at Rs.2850")
    assert ok is True
    smtp_cls.assert_called_once()
    smtp_instance.starttls.assert_called_once()
    smtp_instance.login.assert_called_once_with("test@example.com", "not-a-real-secret")
    # send_message received an EmailMessage with the expected fields
    smtp_instance.send_message.assert_called_once()
    msg = smtp_instance.send_message.call_args.args[0]
    assert msg["Subject"] == "BUY RELIANCE"
    assert msg["From"]    == "test@example.com"
    assert msg["To"]      == "test@example.com"
    assert "Reliance BUY signal at Rs.2850" in msg.get_content()


def test_gmail_send_swallows_smtp_errors(monkeypatch):
    """Any SMTP exception -> returns False, never raises, does NOT print
    the app password."""
    monkeypatch.setenv("ALERT_GMAIL_ADDRESS",      "test@example.com")
    monkeypatch.setenv("ALERT_GMAIL_APP_PASSWORD", "sekret-app-pw-16")
    monkeypatch.setenv("ALERT_GMAIL_TO",           "test@example.com")
    from utils.alerts_gmail import GmailAlerter

    smtp_instance = mock.MagicMock()
    smtp_instance.__enter__.return_value = smtp_instance
    smtp_instance.login.side_effect = RuntimeError("boom")
    with mock.patch("utils.alerts_gmail.smtplib.SMTP", return_value=smtp_instance):
        buf = io.StringIO()
        with redirect_stdout(buf):
            ok = GmailAlerter().send("x", "y")
    assert ok is False
    # Critical: the app password must never appear in stdout on failure.
    assert "sekret-app-pw-16" not in buf.getvalue()


def test_gmail_send_signal_builds_reasonable_body(monkeypatch):
    """send_signal produces a subject + body carrying all trade fields."""
    for k in ("ALERT_GMAIL_ADDRESS", "ALERT_GMAIL_APP_PASSWORD", "ALERT_GMAIL_TO"):
        monkeypatch.delenv(k, raising=False)
    from utils.alerts_gmail import GmailAlerter
    a = GmailAlerter()
    buf = io.StringIO()
    with redirect_stdout(buf):
        ok = a.send_signal("RELIANCE.NS", "BUY", 2850.0,
                           sl=2790.0, tp=2970.0, strategy="momentum",
                           reason="52wk high breakout")
    assert ok is True
    out = buf.getvalue()
    assert "Subject: BUY RELIANCE.NS at Rs.2,850.00" in out
    assert "Stop-Loss: Rs.2,790.00" in out
    assert "Target   : Rs.2,970.00" in out
    assert "Strategy : momentum" in out
    assert "Reason   : 52wk high breakout" in out


# ─────────────────────────────────────────────────────────────────────────────
# dispatch() in alerts/check_alerts.py
# ─────────────────────────────────────────────────────────────────────────────

def test_dispatch_fans_out_to_both_channels(monkeypatch):
    """dispatch() calls both send_telegram and send_gmail regardless of
    each other's success, and returns True if either succeeded."""
    import alerts.check_alerts as ca

    tg  = mock.MagicMock(return_value=True)
    gm  = mock.MagicMock(return_value=False)
    monkeypatch.setattr(ca, "send_telegram", tg)
    monkeypatch.setattr(ca, "send_gmail",    gm)

    ok = ca.dispatch("<b>VIX PANIC</b> at 32.4")
    assert ok is True
    tg.assert_called_once()
    gm.assert_called_once()
    # send_gmail subject derived from first-line HTML-stripped
    subject_arg = gm.call_args.args[0]
    assert subject_arg == "VIX PANIC at 32.4"


def test_dispatch_returns_false_when_both_channels_fail(monkeypatch):
    import alerts.check_alerts as ca
    monkeypatch.setattr(ca, "send_telegram", mock.MagicMock(return_value=False))
    monkeypatch.setattr(ca, "send_gmail",    mock.MagicMock(return_value=False))
    assert ca.dispatch("anything") is False


def test_subject_from_message_strips_html_and_caps_length():
    import alerts.check_alerts as ca
    # first-line-strip
    assert ca._subject_from_message("<b>Line 1</b>\nLine 2", "fb") == "Line 1"
    # empty -> fallback
    assert ca._subject_from_message("\n\n\n", "fallback subj") == "fallback subj"
    # long -> truncated with ellipsis
    long = "x" * 200
    got = ca._subject_from_message(long, "fb")
    assert len(got) <= 123 and got.endswith("...")
