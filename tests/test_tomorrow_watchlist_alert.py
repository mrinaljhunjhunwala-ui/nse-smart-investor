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
    # Same word as the app (audit F2): a breakout under 70 still reads BUY, with its stop
    assert "BUY  <b>B0</b>  above ₹100.00 · stop ₹94.00 · score 70/90" in msg
    assert "BUY  <b>B1</b>  above ₹100.00 · stop ₹94.00 · score 69/90" in msg
    assert "WATCH  <b>M&amp;M</b>  — bounce setup" in msg
    assert "M&amp;M" in msg and "ZZZ" not in msg     # escaped; breakdown not listed
    assert ca.check_tomorrow_watchlist(state, "2026-11-06") == 0


def test_stale_snapshot_says_the_list_was_not_built_once(monkeypatch):
    """25-27 Nov: the warm-up timed out and the stale list was skipped in silence. Now one
    short note a day, never the stale names; a fresh list later that day still goes out."""
    sent = _setup(monkeypatch, {"breakout_candidates": [_p("A.NS", 60, "x")]}, age_h=6)
    state = {}
    assert ca.check_tomorrow_watchlist(state, "2026-11-06") == 1
    assert "could not be built" in sent[0] and "A</b>" not in sent[0] and "IST" in sent[0]
    assert ca.check_tomorrow_watchlist(state, "2026-11-06") == 0 and len(sent) == 1
    sent = _setup(monkeypatch, {"breakout_candidates": [_p("B.NS", 70, "🚀 Breakout setup")]})
    assert ca.check_tomorrow_watchlist(state, "2026-11-06") == 1 and "B</b>" in sent[0]


def test_missing_snapshot_also_says_so(monkeypatch):
    import trade_store
    sent = []
    monkeypatch.setattr(trade_store, "kv_get", lambda *a, **k: None)
    monkeypatch.setattr(ca, "dispatch", lambda m, **k: sent.append(m) or True)
    assert ca.check_tomorrow_watchlist({}, "2026-11-06") == 1
    assert "no earlier list" in sent[0]


def test_empty_fresh_snapshot_sends_nothing(monkeypatch):
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


def test_alerts_have_no_separate_watch_floor():
    """Audit 2026-11-25 F2: Telegram carries the app's word, no 70-point relabel."""
    import inspect
    assert not hasattr(ca, "_floor_word") and not hasattr(ca, "_under_watch_floor")
    assert "action_display_label(" in inspect.getsource(ca.check_weekly_digest)
    assert "verdict_display_label(verdict)" in inspect.getsource(ca._verdict_pick_lines)


def test_breakout_buy_with_no_stop_reads_watch():
    row = ca._tomorrow_row({"ticker": "NOSL.NS", "entry": 100.0, "sl": None, "score": 72}, "BUY")
    assert row.startswith("WATCH  <b>NOSL</b>") and "no stop available" in row and "BUY" not in row
