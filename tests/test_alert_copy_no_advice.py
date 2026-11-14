"""Format guard for Telegram/Gmail alert copy (owner decision, 13 Nov 2026).

The owner replaced the descriptive-only convention with direct BUY / SELL /
HOLD wording and much shorter messages. This file drives every
message-producing path in alerts/check_alerts.py (plus the formatters it calls
in analysis/momentum_scanner.py and analysis/portfolio_posture.py) with
offline fixtures, captures what would be dispatched, and checks the format:

  (a) at most 15 lines (weekly digest / scorecard: 20), no visible line over
      110 characters;
  (b) no raw internal posture tags (EXIT_WATCH, TRIM_WATCH, ...);
  (c) none of the removed jargon (model read, conviction, invalidation,
      Model reference levels);
  (d) every line that starts with BUY / STRONG BUY carries a stop;
  (e) at most one footer / disclaimer line.

Other tests import ``_assert_descriptive`` — kept as an alias of the checker.
"""
from __future__ import annotations

import datetime
import re
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest

import alerts.check_alerts as ca
from analysis.momentum_scanner import format_momentum_message
from analysis.portfolio_posture import (
    HoldingPosture, _classify_delivery, analyse_intraday_position,
    format_portfolio_message,
)

MAX_LINES, MAX_LINES_WEEKLY, MAX_LINE_CHARS = 15, 20, 110
RAW_TAGS = re.compile(r"\b(EXIT_WATCH|TRIM_WATCH|ADD_WATCH|STOP_HIT|TARGET_HIT|TRAIL_TIGHTER|STOPPED_OUT)\b|_WATCH\]")
JARGON = re.compile(r"model read|conviction|invalidation|model reference levels", re.I)
FOOTER = re.compile(r"not a guarantee|not (investment )?advice|descriptive|disclaimer", re.I)
BUY_LINE = re.compile(r"^\s*(STRONG BUY|BUY)\b")


def _visible(line: str) -> str:
    return ca._plain(line)


def _assert_alert_format(msg: str, *, max_lines: int = MAX_LINES, stops: bool = True) -> None:
    lines = msg.splitlines()
    assert len(lines) <= max_lines, f"{len(lines)} lines (max {max_lines}):\n{msg}"
    for ln in lines:
        vis = _visible(ln)
        assert len(vis) <= MAX_LINE_CHARS, f"line of {len(vis)} chars:\n{vis}"
        assert not RAW_TAGS.search(vis), f"raw posture tag in alert:\n{msg}"
        m = JARGON.search(vis)
        assert not m, f"removed jargon {m.group(0)!r} in alert:\n{msg}"
        if stops and BUY_LINE.match(vis):
            assert "stop" in vis, f"BUY line without a stop:\n{vis}"
    n_footer = sum(bool(FOOTER.search(_visible(ln))) for ln in lines)
    assert n_footer <= 1, f"{n_footer} footer/disclaimer lines:\n{msg}"


# Kept for the tests that import it (test_verdict_alerts, test_tomorrow_watchlist_alert).
_assert_descriptive = _assert_alert_format


@pytest.fixture
def sent(monkeypatch):
    """Capture every dispatched message; never send."""
    box: list[str] = []
    monkeypatch.setattr(ca, "dispatch", MagicMock(side_effect=lambda m, **kw: box.append(m) or True))
    monkeypatch.setattr(ca, "_FORCE_SEND", False)
    return box


def _snapshot(actions=("STRONG BUY", "BUY", "WATCHLIST")):
    buys = [{
        "ticker": f"TICK{i}", "action": a, "score": 85 - i * 10,
        "price": 1000.0 + i, "entry_zone": "~1000", "stop_loss": 950,
        "target": 1150, "sector": "IT",
    } for i, a in enumerate(actions)]
    return {"generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "data": {"buys": buys, "sells": [], "meta": {}}}


def _ohlcv(closes):
    closes = np.asarray(closes, dtype=float)
    idx = pd.date_range("2026-06-01", periods=len(closes), freq="B")
    return pd.DataFrame({"Open": closes, "High": closes * 1.01, "Low": closes * 0.99,
                         "Close": closes, "Volume": np.full(len(closes), 1e5)}, index=idx)


# ─────────────────────────────────────────────────────────────────────────────

def test_vix_regime_alert_is_short_and_direct(sent, monkeypatch):
    for regime in ("fear", "panic"):
        monkeypatch.setattr("utils.vix.get_india_vix_regime",
                            lambda r=regime: {"regime": r, "vix": 27.4})
        assert ca.check_vix_regime({}, "2026-09-30") == 1
    assert len(sent) == 2
    for m in sent:
        _assert_descriptive(m)
    assert "27.4" in sent[0] and "FEAR" in sent[0]


def test_nifty_trend_alert_is_short_and_direct(sent, monkeypatch):
    falling = np.linspace(26000, 23000, 70)       # price < SMA20 < SMA50
    monkeypatch.setattr("data.fetcher.fetch_single", lambda *a, **kw: _ohlcv(falling))
    assert ca.check_nifty_trend({}, "2026-09-30") == 1
    _assert_descriptive(sent[0])
    assert "SMA20" in sent[0] and "SMA50" in sent[0] and "downtrend" in sent[0]


def test_price_and_portfolio_alerts_are_descriptive(sent, monkeypatch, tmp_path):
    csv = tmp_path / "alerts.csv"
    csv.write_text("ticker,condition,level,note,enabled\nTCS,above,3000,,1\n", encoding="utf-8")
    monkeypatch.setattr(ca, "_ALERTS_CSV", str(csv))
    prices = {"TCS": 3100.0, "VEDL": 250.0, "PFC": 400.0}
    monkeypatch.setitem(sys.modules, "utils.live_price", SimpleNamespace(
        get_live_quote=lambda t: {"price": prices[t], "chg_pct": 1.0}))
    kv = {"manual_portfolio_holdings": [
              {"ticker": "VEDL.NS", "avg_buy_price": 253.22},
              {"ticker": "PFC.NS", "avg_buy_price": 300.0}],
          "portfolio_alert_anchors": {
              "VEDL": {"ref": 259.95, "ref_date": "2026-09-28", "side": "above"},
              "PFC": {"ref": 330.0, "ref_date": "2026-09-28", "side": "above"}}}
    monkeypatch.setitem(sys.modules, "trade_store", SimpleNamespace(
        kv_get=lambda k, d=None, user_id="default": kv.get(k, d),
        kv_set=lambda k, v, user_id="default": kv.__setitem__(k, v)))

    assert ca.check_price_alerts({}, "2026-09-30") == 1
    assert ca.check_portfolio_alerts({}, "2026-09-30") == 2   # VEDL cost cross + PFC +21% step
    assert len(sent) == 3
    for m in sent:
        _assert_descriptive(m)


def test_delivery_digest_is_descriptive_and_maps_action_labels(sent, monkeypatch):
    monkeypatch.setitem(sys.modules, "trade_store",
                        SimpleNamespace(kv_get=lambda k, user_id: _snapshot()))
    assert ca.check_delivery_digest({}, "2026-09-30") == 1
    _assert_descriptive(sent[0])
    # TICK0/TICK1 score 85/75 (BUY words), TICK2 scores 65 → WATCH, not BUY
    lines = sent[0].splitlines()
    assert any(ln.startswith(("STRONG BUY  <b>TICK0", "BUY  <b>TICK0")) for ln in lines)
    assert any(ln.startswith("WATCH  <b>TICK2</b>") for ln in lines)
    assert "score 85/90" in sent[0]                            # data unchanged


def test_intraday_watchlist_is_short_and_direct(sent, monkeypatch):
    monkeypatch.setitem(sys.modules, "trade_store",
                        SimpleNamespace(kv_get=lambda k, user_id: _snapshot()))
    monkeypatch.setattr("data.fetcher.fetch_single", lambda *a, **kw: _ohlcv(np.full(30, 1000.0)))
    assert ca.check_intraday_watchlist({}, "2026-09-30") == 1
    _assert_descriptive(sent[0])


def test_weekly_digest_is_short_and_direct(sent, monkeypatch):
    _real_strptime = datetime.datetime.strptime
    fake_now = datetime.datetime(2026, 9, 27, 9, 0, tzinfo=ca._IST)   # Sunday

    class _FakeDt(datetime.datetime):
        @classmethod
        def now(cls, tz=None): return fake_now

        @classmethod
        def strptime(cls, s, f): return _real_strptime(s, f)
    monkeypatch.setattr(ca.datetime, "datetime", _FakeDt)
    monkeypatch.setitem(sys.modules, "trade_store",
                        SimpleNamespace(kv_get=lambda k, user_id: _snapshot()))
    monkeypatch.setattr("alerts.journal_store.read_entries", lambda: [])
    assert ca.check_weekly_digest({}, "2026-09-27") == 1
    _assert_descriptive(sent[0], max_lines=MAX_LINES_WEEKLY)
    assert "STRONG BUY  <b>TICK0</b>" in sent[0] and "stop ₹950.00" in sent[0]


def test_momentum_messages_are_descriptive():
    cand = {"ticker": "ABC", "price": 500.0, "breakout_pct": 2.1, "volume_ratio": 1.8,
            "rsi": 64.0, "rs_63d": 7.5, "suggested_entry": 500.0,
            "suggested_stop": 480.0, "suggested_target": 540.0}
    _assert_descriptive(format_momentum_message([]))
    _assert_descriptive(format_momentum_message([cand]))


def test_portfolio_posture_messages_are_descriptive():
    """Uses the engine's real reason strings for every delivery + intraday posture."""
    keys = ("trend", "breakout", "volume", "rsi_band", "vwap", "atr_ok")
    holdings = []
    for n_pass, ltp, pnl in ((0, 90.0, -10.0), (1, 90.0, -10.0), (6, 120.0, 20.0), (2, 110.0, 5.0), (4, 110.0, 5.0)):
        filters = {k: i < n_pass for i, k in enumerate(keys)}
        posture, reason = _classify_delivery(filters, pnl, ltp, 100.0, 3.0)
        holdings.append(HoldingPosture(symbol="XYZ", qty=10, avg_price=100.0, ltp=ltp,
                                       pnl_pct=pnl, posture=posture, reason=reason,
                                       filters_passing=n_pass))
    positions = [
        analyse_intraday_position({"symbol": "ABC", "qty": 5, "avg_price": 100.0,
                                   "ltp": ltp, "side": "LONG"}, _ohlcv(np.full(30, 100.0)))
        for ltp in (98.0, 103.0, 101.5, 100.2)          # STOP / TARGET / TRAIL / RUNNING
    ]
    assert {p.posture for p in positions} >= {"STOP_HIT", "TARGET_HIT", "TRAIL_TIGHTER"}
    _assert_descriptive(format_portfolio_message([], []))
    msg = format_portfolio_message(holdings, positions, only_actionable=False)
    _assert_descriptive(msg)
    words = [ln.split("  ")[0] for ln in msg.splitlines()[1:]]
    assert words[0] == "SELL" and {"SELL", "TRIM", "ADD", "HOLD", "STOP HIT", "TARGET HIT", "TRAIL"} <= set(words)
    assert words == sorted(words, key=["SELL", "STOP HIT", "TRIM", "TARGET HIT", "TRAIL", "ADD", "HOLD"].index)


def test_buy_batch_and_tomorrow_watchlist_are_short_and_direct(monkeypatch):
    """The BUY batch at its 8-name cap and Tomorrow's Watchlist at 5 per bucket."""
    batch = [(f"k{i}", "STRONG BUY" if i < 3 else "BUY",
              {"ticker": f"NAME{i}.NS", "score": 80 - i, "price": 118.4, "sl": 112.1, "tp": 131.0,
               "sector": "Financial Services"}, None) for i in range(8)]
    gen = datetime.datetime.now(datetime.timezone.utc).isoformat()
    for n in (1, 5, 8):
        msg = "\n".join(ca._format_verdict_batch(batch[:n], ca._MARKET_DOWN, gen))
        _assert_descriptive(msg)
        assert msg.splitlines()[0].startswith(f"🟢 <b>{n} new BUY call")
    assert "STRONG BUY  <b>NAME0</b>  ₹118.40 · stop ₹112.10 · target ₹131.00" in msg

    item = {"ticker": "B.NS", "score": 70, "entry": 100.0, "sl": 94.0, "signal_type": "x"}
    data = {"breakout_candidates": [dict(item, ticker=f"B{i}.NS") for i in range(8)],
            "reversal_watch": [dict(item, ticker=f"R{i}.NS") for i in range(8)]}
    msg = "\n".join(ca.tomorrow_watchlist_lines(data, gen))
    _assert_descriptive(msg)
    assert "BUY  <b>B0</b>  above ₹100.00 · stop ₹94.00" in msg and "B5" not in msg
    assert "WATCH  <b>R0</b>  — bounce setup · stop ₹94.00" in msg and "R5" not in msg


def test_not_analysed_is_one_line():
    line = ca._not_analysed_line([
        {"symbol": "VEDL", "reason": "price history could not be fetched"},
        {"symbol": "PFC", "reason": "price history could not be fetched"}])
    assert line == "Not analysed: VEDL, PFC (price history unavailable)"


def test_guard_catches_the_old_copy():
    """The checker must flag the formats this rework removed."""
    old = [
        "🟢 <b>AAA</b> — model read <b>Strong trend ▲▲</b> · conviction 86 · score 70/90",
        "   Model reference levels: invalidation ₹95.00 · target ₹110.00",
        "• <b>XYZ</b> [EXIT_WATCH] P&amp;L -10.0% — Price below SMA50",
        "BUY  <b>AAA</b>  ₹100.00 · target ₹110.00",                          # BUY without a stop
        "<i>Descriptive, not advice.</i>\n<i>Model output, not a guarantee.</i>",   # two footers
        "\n".join(["x"] * 16),
        "x" * 111,
    ]
    for msg in old:
        with pytest.raises(AssertionError):
            _assert_alert_format(msg)
