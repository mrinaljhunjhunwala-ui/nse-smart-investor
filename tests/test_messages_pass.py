"""Message pass (owner, 17 Nov): fewer BUY calls, posture SELL only when it means it,
recap folded into the end-of-day check, and an action line on every pick."""
from __future__ import annotations

import inspect

from analysis.portfolio_posture import _classify_delivery

_OFF = {k: False for k in ("trend", "breakout", "volume", "rsi_band", "vwap", "atr_ok")}


def test_posture_just_under_the_50_day_is_hold_with_the_exit_level():
    """ONGC on 17 Nov: 1.6% under its 50-day average read SELL."""
    posture, reason = _classify_delivery(_OFF, -0.2, 226.0, 229.73, 4.5, long_trend_up=False)
    assert posture == "HOLD" and "SELL on a close below ₹225.23" in reason


def test_posture_far_under_names_the_stop():
    posture, reason = _classify_delivery(_OFF, -76.0, 57.36, 59.97, 2.0, long_trend_up=False)
    assert posture == "EXIT_WATCH" and "longer trend down" in reason and "stop ₹55.36" in reason
    posture, reason = _classify_delivery(_OFF, 690.0, 650.0, 672.83, 18.0, long_trend_up=True)
    assert posture == "TRIM_WATCH" and "longer trend still up" in reason and "stop ₹632.00" in reason


def test_buy_calls_capped_at_five_beyond_the_digest():
    import alerts.check_alerts as CA
    assert CA._VERDICT_MAX_PER_DAY + CA._VERDICT_FRESH_MAX_PER_DAY == 5
    assert CA._VERDICT_MAX_PER_RUN <= CA._VERDICT_MAX_PER_DAY


def test_buy_line_carries_the_plan():
    import alerts.check_alerts as CA
    b = {"ticker": "DELTACORP.NS", "price": 84.06, "sl": 70.44, "tp": 120.28, "score": 75.1,
         "sector": "Hospitality", "horizon": "Positional (2–4 weeks)"}
    lines = CA._verdict_pick_lines("STRONG BUY", b)
    assert len(lines) == 2
    assert "risk -16.2% / reward +43.1%" in lines[1] and "hold 2–4 weeks" in lines[1]
    assert "skip above ₹85.74" in lines[1]
    assert "hold 2–6 weeks" in " ".join(CA._plan_bits({"price": 100}))     # no horizon on the pick


def test_digest_lines_carry_the_plan_but_no_stop_names_do_not():
    """Every BUY line carries its plan (no 70-point floor since audit F2); a BUY
    with no stop reads WATCH and gets no trade plan (audit F5)."""
    import alerts.check_alerts as CA
    buys = [{"ticker": "AAA.NS", "price": 100, "sl": 95, "tp": 110, "score": 78, "sector": "IT",
             "action": "STRONG BUY"},
            {"ticker": "BBB.NS", "price": 50, "sl": None, "tp": 56, "score": 60, "sector": "IT", "action": "BUY"}]
    text = "\n".join(CA._digest_lines(buys, "2026-11-17T03:13:00+00:00", 5))
    a, b = text.split("BBB")[0], text.split("BBB")[1]
    assert "risk -5.0% / reward +10.0%" in a and "skip above" not in b and "no stop available" in b


def test_recap_left_the_15_minute_run():
    import alerts.check_alerts as CA
    assert "check_picks_recap(state, today)" not in inspect.getsource(CA.main)


def test_radar_says_what_to_do():
    from alerts.movers_alerts import radar_action
    assert radar_action({"pct": 7.9}).startswith("no action")
    assert "don't chase +6.2%" in radar_action({"pct": 6.2, "watchlist": ("Breakout", 4, 1)})
    assert radar_action({"pct": 9.0, "held": True}).startswith("you hold it")
    assert radar_action({"pct": 9.0, "paper": True}).startswith("open paper trade")


def test_wide_stop_gets_a_sizing_hint():
    """18 Nov review: stops ran 10-16% away (AARTIPHARM -13.0%, DELTACORP -16.2%). With the same
    rupee risk such a trade must be smaller; the line says how much."""
    import alerts.check_alerts as CA
    wide = " · ".join(CA._plan_bits({"price": 100, "sl": 87, "tp": 137}))
    assert "wide stop: 1% risk = 7.7% of capital" in wide
    assert "wide stop" not in " · ".join(CA._plan_bits({"price": 100, "sl": 94, "tp": 115}))


def test_repeat_buy_call_names_the_earlier_call():
    """18 Nov: 7 of 10 'new' BUY calls had been called on 17 Nov. A repeat says so, with the
    earlier price, so it is not read as a fresh signal."""
    import alerts.check_alerts as CA

    class Store:
        def kv_get(self, key, default=None, user_id=None):
            return {"buy_calls:2026-11-17": [{"symbol": "PHOENIXLTD", "price": 2202.0}]}.get(key, default)

    seen = CA._earlier_calls(Store(), "2026-11-18")
    assert seen == {"PHOENIXLTD": ("2026-11-17", 2202.0)}
    b = {"ticker": "PHOENIXLTD.NS", "price": 2229.0, "sl": 2092.13, "tp": 2539.86, "score": 80.4}
    lines = CA._format_verdict_batch([("k", "STRONG BUY", b, None)], "", "2026-11-18T03:14:00+00:00",
                                     earlier=seen)
    assert any("repeat: BUY call on Tue 17 Nov at ₹2,202.00" in ln for ln in lines)
    assert CA._earlier_calls(None, "2026-11-18") == {}
