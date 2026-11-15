"""check_tomorrow_watchlist — after-close Telegram from the watchlist snapshot."""
import datetime as dt

import alerts.check_alerts as ca


def _p(tk, score, sig):
    return {"ticker": tk, "score": score, "signal_type": sig, "entry": 100.0, "sl": 94.0}


def _setup(monkeypatch, data, age_h=0.1):
    import trade_store
    gen = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=age_h)).isoformat()
    monkeypatch.setattr(trade_store, "kv_get", lambda *a, **k: {"generated_at": gen, "data": data})
    sent = []
    monkeypatch.setattr(ca, "dispatch", lambda m, **k: sent.append(m) or True)
    return sent


def test_sends_top_names_once_per_day(monkeypatch):
    from tests.test_alert_copy_no_advice import _assert_descriptive
    data = {"breakout_candidates": [_p(f"B{i}.NS", 70 - i, "🚀 Breakout setup") for i in range(8)],
            "reversal_watch": [_p("M&M.NS", 50, "🔄 Bullish divergence")],
            "breakdown_watch": [_p("ZZZ.NS", 20, "🔻 Breakdown risk")]}
    sent = _setup(monkeypatch, data)
    state = {}
    assert ca.check_tomorrow_watchlist(state, "2026-11-06") == 1
    msg = sent[0]
    _assert_descriptive(msg)
    assert "B4" in msg and "B5" not in msg          # top 5 only
    # BUY only at 70+: a breakout under 70 keeps its level but reads WATCH (owner decision, 15 Nov)
    assert "BUY  <b>B0</b>  above ₹100.00 · stop ₹94.00 · score 70/90" in msg
    assert "WATCH  <b>B1</b>  above ₹100.00 · stop ₹94.00 · score 69/90" in msg
    assert "BUY  <b>B1</b>" not in msg and "WATCH  <b>M&amp;M</b>  — bounce setup" in msg
    assert "M&amp;M" in msg and "ZZZ" not in msg     # escaped; breakdown not listed
    assert ca.check_tomorrow_watchlist(state, "2026-11-06") == 0


def test_stale_or_empty_snapshot_sends_nothing(monkeypatch):
    sent = _setup(monkeypatch, {"breakout_candidates": [_p("A.NS", 60, "x")]}, age_h=6)
    assert ca.check_tomorrow_watchlist({}, "2026-11-06") == 0
    sent = _setup(monkeypatch, {"breakout_candidates": [], "reversal_watch": []})
    assert ca.check_tomorrow_watchlist({}, "2026-11-06") == 0 and not sent


def test_empty_breakout_in_bear_market_says_why(monkeypatch):
    from tests.test_alert_copy_no_advice import _assert_descriptive
    data = {"breakout_candidates": [], "reversal_watch": [_p("A.NS", 50, "🔄 Bullish divergence")],
            "bear_scoring_active": True, "regime_label": "trend_down"}
    sent = _setup(monkeypatch, data)
    assert ca.check_tomorrow_watchlist({}, "2026-11-06") == 1
    _assert_descriptive(sent[0])
    assert "held back in the trend down market" in sent[0] and "A</b>" in sent[0]


def test_weekly_digest_and_buy_calls_use_the_same_floor():
    import inspect
    assert "_floor_word(action_display_label(" in inspect.getsource(ca.check_weekly_digest)
    assert "_floor_word(verdict_display_label(verdict)" in inspect.getsource(ca._verdict_pick_lines)
    assert ca._WATCH_FLOOR == 70.0
