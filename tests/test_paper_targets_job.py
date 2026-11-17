"""Market Alerts job closes delivery paper trades whose target was met."""
from __future__ import annotations

import pandas as pd
import pytest

import alerts.check_alerts as ca


def test_target_exit_rules():
    assert ca.paper_target_exit(105.0, 106.0, 104.0) == 105.0      # at/above target now
    assert ca.paper_target_exit(101.0, 104.5, 104.0) == 104.0      # touched between runs
    assert ca.paper_target_exit(101.0, 103.0, 104.0) is None
    assert ca.paper_target_exit(101.0, None, 0) is None


@pytest.fixture
def env(monkeypatch):
    import trade_store
    import utils.live_price as lp
    rows = pd.DataFrame([
        {"id": 1, "ticker": "AAA.NS", "action": "BUY", "price": 100.0, "quantity": 10, "tp": 110.0,
         "account": "My Account", "timestamp": "2026-11-10T10:00"},
        {"id": 2, "ticker": "BBB.NS", "action": "BUY", "price": 50.0, "quantity": 5, "tp": 60.0,
         "account": "My Account", "timestamp": "2026-11-17T14:00"},          # opened today
        {"id": 3, "ticker": "CCC.NS", "action": "BUY", "price": 20.0, "quantity": 5, "tp": 21.0,
         "account": "Intraday", "timestamp": "2026-11-10T10:00"},           # MIS account
        {"id": 4, "ticker": "DDD.NS", "action": "BUY", "price": 80.0, "quantity": 5, "tp": 90.0,
         "account": "My Account", "timestamp": "2026-11-10T10:00"},          # not met
    ])
    quotes = {"AAA.NS": {"price": 108.0, "high": 111.0}, "BBB.NS": {"price": 55.0, "high": 61.0},
              "CCC.NS": {"price": 22.0, "high": 22.0}, "DDD.NS": {"price": 85.0, "high": 86.0}}
    closed, sent = [], []
    monkeypatch.setattr(ca, "_is_market_hours", lambda: True)
    monkeypatch.setattr(trade_store, "fetch_open", lambda *a, **k: rows)
    monkeypatch.setattr(trade_store, "kv_get",
                        lambda key, default=None, **k: "MIS" if key == "acct_type:Intraday" else "CNC")
    monkeypatch.setattr(trade_store, "close_trade",
                        lambda tid, px, reason="": closed.append((tid, px)) or True)
    monkeypatch.setattr(lp, "get_live_prices_batch", lambda syms, **k: quotes)
    monkeypatch.setattr(ca, "dispatch", lambda msg, **k: sent.append(msg) or True)
    return closed, sent


def test_only_delivery_targets_close(env):
    closed, sent = env
    assert ca.check_paper_targets({}, "2026-11-17") == 1
    assert closed == [(1, 110.0)]          # AAA via day high; BBB opened today; CCC is MIS; DDD not met
    assert len(sent) == 1 and "AAA" in sent[0] and "BBB" not in sent[0]


def test_market_closed_does_nothing(env, monkeypatch):
    closed, sent = env
    monkeypatch.setattr(ca, "_is_market_hours", lambda: False)
    assert ca.check_paper_targets({}, "2026-11-17") == 0 and closed == [] and sent == []
