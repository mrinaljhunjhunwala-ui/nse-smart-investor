"""End-of-day check of the day's BUY calls (owner, 17 Nov)."""
from __future__ import annotations

import datetime as dt

from analysis import calls_scorecard as CS


def test_grade_call_move_nifty_stop_target():
    g = CS.grade_call(entry=100, close=103, high=111, low=94, stop=95, target=110, nifty_pct=0.5)
    assert round(g["pct"], 2) == 3.0 and round(g["vs_nifty"], 2) == 2.5
    assert round(g["best_pct"], 2) == 11.0 and round(g["worst_pct"], 2) == -6.0
    assert g["stop_hit"] and g["target_hit"]
    quiet = CS.grade_call(entry=100, close=99, high=101, low=98, stop=95, target=110)
    assert not quiet["stop_hit"] and not quiet["target_hit"] and quiet["vs_nifty"] is None
    assert CS.grade_call(entry=None, close=100)["pct"] is None
    assert CS.call_line("X", CS.grade_call(entry=0, close=None)) == "X — no closing price"


def test_grade_levels_and_line():
    lv = {"up": 43.65, "down": 41.35, "next_up": 47.11}
    g = CS.grade_levels(lv, close=43.19, high=44.74, low=40.11)
    assert g["broke_up"] and g["broke_down"] and not g["reached_next"] and g["closed"] == "inside"
    line = CS.levels_line("DHANBANK", g)
    assert "broke ▲ ₹43.65" in line and "broke ▼ ₹41.35" in line and "closed inside at ₹43.19" in line
    assert CS.grade_levels(lv, close=48, high=48)["reached_next"]


def test_summary_counts_and_line():
    rows = [CS.grade_call(entry=100, close=103, nifty_pct=1.0, stop=90, target=102, high=104, low=99),
            CS.grade_call(entry=100, close=99.5, nifty_pct=1.0, stop=99.6, high=100.5, low=99.4),
            CS.grade_call(entry=None, close=10)]
    s = CS.summarize(rows, 1.0)
    assert s["n"] == 2 and s["up"] == 1 and round(s["avg_pct"], 2) == 1.25
    assert round(s["avg_vs_nifty"], 2) == 0.25 and s["beat_nifty"] == 1
    assert s["stops_hit"] == 1 and s["targets_hit"] == 1
    line = CS.summary_line(s)
    assert "2 calls · 1 up / 1 down or flat" in line and "Nifty +1.0%" in line and "stops hit 1" in line
    assert CS.summary_line(CS.summarize([])) == "No call had a closing price."


def test_eod_alert_grades_digest_calls_and_levels(monkeypatch):
    import alerts.check_alerts as CA
    import trade_store
    today = "2026-11-17"
    kv = {("_system", "morning_digest_picks"): {"date": today, "generated_at": "2026-11-17T03:13:00+00:00",
                                                "buys": [{"ticker": "SGMART.NS", "price": 983.40, "sl": 900.77,
                                                          "tp": 1196.82, "action": "STRONG BUY"}]},
          ("_system", "buy_calls:" + today): [{"symbol": "DELTACORP", "verdict": "STRONG BUY", "time": "09:31",
                                               "price": 84.06, "sl": 70.44, "tp": 120.28},
                                              {"symbol": "SGMART", "price": 990}],          # dup of a digest pick
          ("_system", "intraday_levels"): {"date": today, "levels": {"DHANBANK": {"up": 43.65, "down": 41.35,
                                                                                   "next_up": 47.11}}}}
    monkeypatch.setattr(trade_store, "kv_get", lambda k, d=None, user_id="default": kv.get((user_id, k), d))
    monkeypatch.setattr(trade_store, "kv_set", lambda k, v, user_id="default": kv.__setitem__((user_id, k), v) or True)
    px = {"SGMART": {"close": 1013.35, "high": 1022.0, "low": 976.95},
          "DELTACORP": {"close": 82.0, "high": 85.0, "low": 81.0},
          "DHANBANK": {"close": 43.19, "high": 44.74, "low": 40.11}}
    monkeypatch.setattr(CA, "_day_prices", lambda base, today: px[base])
    monkeypatch.setattr(CA, "_nifty_day_pct", lambda today: 0.4)
    sent = []
    monkeypatch.setattr(CA, "dispatch", lambda msg, subject="": sent.append(msg) or True)
    state = {}
    assert CA.check_eod_scorecard(state, today) == 1
    msg = sent[0]
    assert "Delivery Digest picks" in msg and "SGMART ₹983.40 → ₹1,013.35 +3.0%" in msg
    assert "DELTACORP 09:31 ₹84.06 → ₹82.00 -2.5%" in msg
    assert msg.count("SGMART") == 1                                   # not graded twice
    assert "broke ▲ ₹43.65" in msg and "2 calls · 1 up" in msg and "Nifty +0.4%" in msg
    saved = kv[("_system", "eod_scorecard:" + today)]
    assert [c["symbol"] for c in saved["calls"]] == ["SGMART", "DELTACORP"] and saved["levels"][0]["symbol"] == "DHANBANK"
    assert CA.check_eod_scorecard(state, today) == 0                  # once a day


def test_buy_calls_are_recorded_for_the_eod_check(monkeypatch):
    import alerts.check_alerts as CA
    kv = {}

    class Store:
        @staticmethod
        def kv_get(k, d=None, user_id="default"):
            return kv.get((user_id, k), d)

        @staticmethod
        def kv_set(k, v, user_id="default"):
            kv[(user_id, k)] = v
            return True
    monkeypatch.setattr(CA, "_FORCE_SEND", False)
    CA._record_buy_calls(Store, "2026-11-17", [("BUY", {"ticker": "PNB.NS", "price": 110.5, "sl": 104, "tp": 125})])
    CA._record_buy_calls(Store, "2026-11-17", [("STRONG BUY", {"ticker": "TCS.NS", "price": 3000})])
    rows = kv[("_system", "buy_calls:2026-11-17")]
    assert [r["symbol"] for r in rows] == ["PNB", "TCS"] and rows[0]["sl"] == 104 and rows[0]["time"]


def test_momentum_digest_retired_and_why_moved_unscheduled(monkeypatch):
    import pathlib
    import sys
    import alerts.check_alerts as CA
    called = []
    monkeypatch.setattr(CA, "check_momentum_opportunities", lambda *a, **k: called.append(1) or 1)
    monkeypatch.setattr(CA, "_is_market_hours", lambda: True)
    monkeypatch.setattr(CA, "_load_state", lambda: {})
    monkeypatch.setattr(CA, "_save_state", lambda *a, **k: None)
    monkeypatch.setattr(sys, "argv", ["check_alerts.py", "--mode=momentum"])
    CA.main()
    assert called == []
    wf = pathlib.Path(".github/workflows/warm_tomorrow_watchlist.yml").read_text(encoding="utf-8")
    assert "--mode=eod-scorecard" in wf and "run: python alerts/check_alerts.py --mode=why-moved" not in wf
    assert CA._in_send_window("eod-scorecard", dt.datetime(2026, 11, 17, 16, 2, tzinfo=CA._IST))
    assert not CA._in_send_window("eod-scorecard", dt.datetime(2026, 11, 17, 14, 0, tzinfo=CA._IST))


def test_postclose_job_sends_even_when_the_scan_is_slow():
    """18 Nov: a 19-minute scan hit the 20-minute job limit and the end-of-day check, the
    watchlist and the posture message were all skipped."""
    import pathlib
    import re
    wf = pathlib.Path(".github/workflows/warm_tomorrow_watchlist.yml").read_text(encoding="utf-8")
    scan = wf[wf.index("- name: Run Tomorrow's Watchlist warm-up"):wf.index("run: python scripts/warm_tomorrow_watchlist.py")]
    assert "continue-on-error: true" in scan
    step_limit = int(re.search(r"timeout-minutes:\s*(\d+)", scan).group(1))
    job_limit = int(re.search(r"\n    timeout-minutes:\s*(\d+)", wf).group(1))
    assert step_limit + 10 <= job_limit          # room left for the sends after a timed-out scan
