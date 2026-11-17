"""Audit 2026-11: a scored Smart Screener BUY could show no stop."""
from dashboard.views.smart_screener import signal_stop


def test_falls_back_to_the_composite_stop():
    assert signal_stop({"sl": 0, "stop_loss": 95.5}) == 95.5        # was 0 -> "–" next to a BUY label
    assert signal_stop({"sl": None, "stop_loss": 95.5}) == 95.5
    assert signal_stop({"sl": 97.0, "stop_loss": 95.5}) == 97.0
    assert signal_stop({}) == 0.0
