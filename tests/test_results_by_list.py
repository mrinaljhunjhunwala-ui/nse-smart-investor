"""Results by list, the pre-registered Watchlist rule and the split Friday
report card. Offline; pure functions plus one seeded page render."""
from __future__ import annotations

import datetime as dt
import os
import socket
import sqlite3

import numpy as np
import pandas as pd
import pytest

import alerts.check_alerts as ca
from analysis import verdict_ledger as vl


def _days(n, start="2026-11-04"):
    out, d = [], dt.date.fromisoformat(start)
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.isoformat())
        d += dt.timedelta(days=1)
    return out


def _row(source, day, ticker, ret, nifty, bucket=None, verdict="BUY", at="T16:00:00"):
    return {"source": source, "logged_date": day, "logged_at": day + at, "ticker": ticker,
            "verdict": verdict, "bucket": bucket, "ret_5d": ret, "nifty_ret_5d": nifty,
            "ret_20d": np.nan, "nifty_ret_20d": np.nan}


def _by_key(df):
    return df.set_index("list_key")


# ── results_by_list ──────────────────────────────────────────────────────────

def test_direction_handling_and_costs():
    rows = []
    for i, d in enumerate(_days(12)):
        rows.append(_row("tomorrow_watchlist", d, f"UP{i}.NS", 2.0, 1.0, "breakout"))    # +1.0 edge
        rows.append(_row("tomorrow_watchlist", d, f"DN{i}.NS", -3.0, 1.0, "breakdown"))  # lagged: +4.0
        rows.append(_row("tomorrow_watchlist", d, f"BR{i}.NS", 1.2, 1.0, "reversal_bear"))  # -0.2
    res = _by_key(vl.results_by_list(pd.DataFrame(rows), horizons=(5,)))
    up, dn, br = (res.loc[f"tomorrow_watchlist:{b}"] for b in ("breakout", "breakdown", "reversal_bear"))
    assert up["hit_means"] == "Beat the Nifty" and dn["hit_means"] == "Lagged the Nifty"
    assert up["avg_vs_nifty_5"] == 1.0 and up["avg_vs_nifty_net_5"] == 0.75
    assert dn["avg_vs_nifty_5"] == 4.0 and dn["hit_pct_5"] == 100.0       # fell vs Nifty = a hit
    assert br["avg_vs_nifty_5"] == -0.2 and br["hit_pct_5"] == 0.0         # rose vs Nifty = a miss
    assert 0 < dn["hit_lower_pct_5"] < 100                                 # Wilson over 12 days
    assert res.loc["tomorrow_watchlist:breakout", "status_5"] == "scored"


def test_cost_can_turn_a_small_gross_edge_into_a_miss():
    rows = [_row("shadow_auto", d, "AAA.NS", 1.2, 1.0) for d in _days(10)]    # +0.2 < 0.25 cost
    r = vl.results_by_list(pd.DataFrame(rows), horizons=(5,)).iloc[0]
    assert r["hit_pct_5"] == 0.0 and r["avg_vs_nifty_net_5"] == -0.05
    r0 = vl.results_by_list(pd.DataFrame(rows), horizons=(5,), cost_pct=0.0).iloc[0]
    assert r0["hit_pct_5"] == 100.0


def test_dedupe_same_list_same_day_but_not_across_lists():
    d = "2026-11-04"
    rows = pd.DataFrame([
        _row("shadow_auto", d, "AAA.NS", 5.0, 1.0, at="T10:00:00"),
        _row("shadow_auto", d, "AAA.NS", 5.0, 1.0, at="T14:00:00"),            # repeat scan
        _row("tomorrow_watchlist", d, "AAA.NS", 5.0, 1.0, "breakout"),
        _row("tomorrow_watchlist", d, "AAA.NS", 5.0, 1.0, "breakout", at="T18:00:00"),
    ])
    res = _by_key(vl.results_by_list(rows, horizons=(5,)))
    assert res.loc["shadow_auto", "picks_5"] == 1
    assert res.loc["tomorrow_watchlist:breakout", "picks_5"] == 1


def test_too_early_hides_rates_and_order_puts_ad_hoc_last():
    rows = pd.DataFrame([
        _row("analyze_page", "2026-11-04", "ZZZ.NS", 1.0, 0.0),
        _row("analyze_page", "2026-11-04", "HHH.NS", 1.0, 0.0, verdict="HOLD"),  # no direction
        _row("momentum_leaders", "2026-11-04", "MMM.NS", 3.0, 1.0),
        _row("shadow_auto", "2026-11-04", "AAA.NS", 3.0, 1.0),
        _row("tomorrow_watchlist", "2026-11-05", "OLD.NS", 3.0, 1.0, bucket=None),
        _row("shadow_auto", "2026-11-05", "PEND.NS", np.nan, np.nan),           # still in window
    ])
    res = vl.results_by_list(rows, horizons=(5, 20))
    assert list(res["list"]) == ["Top Picks", "Momentum Leaders",
                                 "Tomorrow's Watchlist · bucket not recorded",
                                 "Analyze Stock views (ad hoc)"]
    top = res.iloc[0]
    assert top["status_5"] == "too early" and np.isnan(top["hit_pct_5"])
    assert top["picks_logged"] == 2 and top["picks_5"] == 1
    assert top["status_20"] == "no data"
    assert res.iloc[-1]["picks_logged"] == 1                                # HOLD dropped
    assert res.attrs["entry_basis"] == "close"


def test_next_open_entry_falls_back_to_close_and_empty_input():
    rows = pd.DataFrame([_row("shadow_auto", "2026-11-04", "AAA.NS", 3.0, 1.0)])
    assert vl.results_by_list(rows, entry="next_open").attrs["entry_basis"] == "close"
    with pytest.raises(ValueError):
        vl.results_by_list(rows, entry="vwap")
    assert vl.results_by_list(pd.DataFrame()).empty


# ── WATCHLIST_RULE ───────────────────────────────────────────────────────────

def test_watchlist_rule_is_frozen():
    assert vl.WATCHLIST_RULE == {
        "registered_on": "2026-11-09", "source": "tomorrow_watchlist",
        "buckets": ("breakout", "reversal_bull", "breakdown", "reversal_bear"),
        "logged_from": "2026-11-04", "horizon_days": 5, "min_verdicts": 100, "min_days": 30,
        "cost_pct": 0.25, "threshold_pct": 50.0, "entry": "close",
    }
    assert vl.DECISION_RULE["registered_on"] == "2026-09-29"       # untouched
    assert vl.DECISION_RULE["horizon_days"] == 20 and vl.DECISION_RULE["min_verdicts"] == 150


def _tw_rows(n_days, per_day, up_ret, dn_ret, start="2026-11-04"):
    rows = []
    for d in _days(n_days, start):
        for i in range(per_day):
            rows.append(_row("tomorrow_watchlist", d, f"U{i}.NS", up_ret, 0.0, "breakout"))
            rows.append(_row("tomorrow_watchlist", d, f"D{i}.NS", dn_ret, 0.0, "breakdown"))
    return pd.DataFrame(rows)


def test_watchlist_rule_states():
    early = vl.evaluate_watchlist_rule(_tw_rows(10, 3, 2.0, -2.0))
    assert early["status"] == "too_early" and early["picks"] == 60 and early["days"] == 10
    assert "Too early" in early["summary"] and "60 of 100" in early["summary"]
    good = vl.evaluate_watchlist_rule(_tw_rows(32, 2, 2.0, -2.0))       # both directions right
    assert good["status"] == "pass" and good["hit_lower_pct"] > 50 and good["avg_vs_nifty_net"] == 1.75
    bad = vl.evaluate_watchlist_rule(_tw_rows(32, 2, -2.0, 2.0))        # both directions wrong
    assert bad["status"] == "fail" and bad["hit_pct"] == 0.0
    assert "Not passing" in bad["summary"]


def test_watchlist_rule_scope():
    rows = pd.concat([
        _tw_rows(32, 2, 2.0, -2.0, start="2026-09-01"),                # before logged_from
        pd.DataFrame([_row("shadow_auto", "2026-11-04", "X.NS", 2.0, 0.0),
                      _row("tomorrow_watchlist", "2026-11-04", "Y.NS", 2.0, 0.0, bucket=None)]),
    ])
    res = vl.evaluate_watchlist_rule(rows)
    assert res["status"] == "too_early" and res["picks"] == 0
    assert vl.evaluate_watchlist_rule(pd.DataFrame())["status"] == "too_early"


# ── Friday report card, split by list ────────────────────────────────────────

def _week_rows():
    return pd.DataFrame([
        {"id": 1, "source": "shadow_auto", "ticker": "AAA.NS", "logged_date": "2026-11-02",
         "entry_price": 100.0, "verdict": "BUY"},
        {"id": 2, "source": "shadow_auto", "ticker": "BBB.NS", "logged_date": "2026-11-03",
         "entry_price": 200.0, "verdict": "WATCH"},
        {"id": 3, "source": "tomorrow_watchlist", "ticker": "CCC.NS", "logged_date": "2026-11-03",
         "entry_price": 50.0, "verdict": "BUY"},
        {"id": 4, "source": "tomorrow_watchlist", "ticker": "DDD.NS", "logged_date": "2026-11-03",
         "entry_price": 80.0, "verdict": "AVOID"},
        {"id": 5, "source": "analyze_page", "ticker": "EEE.NS", "logged_date": "2026-11-03",
         "entry_price": 10.0, "verdict": "BUY"},
    ])


_BUCKETS = {3: "breakout", 4: "breakdown"}
_PRICES = {"AAA.NS": 110.0, "BBB.NS": 190.0, "CCC.NS": 52.0, "DDD.NS": 72.0, "EEE.NS": 11.0}


def _nifty():
    idx = pd.to_datetime(["2026-11-02", "2026-11-03", "2026-11-04", "2026-11-05", "2026-11-06"])
    return pd.Series([1000.0, 1000.0, 1010.0, 1020.0, 1020.0], index=idx)


def test_week_scorecard_by_list_splits_and_flips_direction():
    rows = _week_rows().assign(bucket=lambda d: d["id"].map(_BUCKETS))
    cards = vl.week_scorecard_by_list(rows, _PRICES, _nifty(), 1020.0)
    assert cards["top_picks"]["n"] == 2                         # every Top Picks card, any verdict
    up, dn = cards["watchlist_up"], cards["watchlist_down"]
    assert up["n"] == 1 and up["hits"] == 1                     # +4% vs Nifty +2%
    assert dn["n"] == 1 and dn["direction"] == -1 and dn["hits"] == 1   # −10% lagged the Nifty
    assert dn["best"][0]["ticker"] == "DDD.NS"
    assert vl.week_scorecard_by_list(rows, {}, _nifty(), 1020.0) is None


def test_friday_message_has_two_sections(monkeypatch):
    from tests.test_alert_copy_no_advice import _assert_descriptive
    monkeypatch.setattr(vl, "load_ledger", lambda **k: _week_rows())
    monkeypatch.setattr(vl, "ledger_error", lambda df: None)
    monkeypatch.setattr(vl, "tw_buckets", lambda ids: {i: _BUCKETS[i] for i in ids if i in _BUCKETS})
    monkeypatch.setattr(ca, "_quote", lambda b: {"price": _PRICES.get(b + ".NS")})
    import data.fetcher as f
    monkeypatch.setattr(f, "fetch_single", lambda *a, **k: pd.DataFrame({"Close": _nifty()}))
    sent = []
    monkeypatch.setattr(ca, "dispatch", lambda m, **k: sent.append(m) or True)
    ist = dt.timezone(dt.timedelta(hours=5, minutes=30))
    fri = dt.datetime(2026, 11, 6, 16, 0, tzinfo=ist)
    assert ca.check_weekly_scorecard({}, "2026-11-06", now=fri) == 1
    msg = sent[0]
    _assert_descriptive(msg)
    assert msg.index("Top Picks") < msg.index("Tomorrow's Watchlist")
    assert "Top Picks</b> · 2 names" in msg and "AAA +10.0%" in msg
    assert "Bullish setups" in msg and "1 of 1 ahead of the Nifty" in msg
    assert "Bearish setups" in msg and "1 of 1 lagged the Nifty" in msg and "DDD -10.0%" in msg
    assert "EEE" not in msg                                     # ad-hoc views stay out


# ── Page: the new section renders against a seeded ledger ────────────────────

def test_calibration_page_shows_results_by_list(monkeypatch):
    from streamlit.testing.v1 import AppTest

    import trade_store

    def _blocked(*a, **k):
        raise OSError("network blocked")
    monkeypatch.setattr(socket.socket, "connect", _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)
    monkeypatch.setattr(vl, "_fetch_history", lambda t: None)
    vl.ensure_schema()
    with sqlite3.connect(trade_store._SQLITE_PATH) as con:
        for k, day in enumerate(_days(12, "2026-10-12")):
            for src, tk, tag, ret in (("shadow_auto", f"A{k}.NS", None, 3.0),
                                      ("tomorrow_watchlist", f"B{k}.NS", "tw:breakdown", -2.0)):
                cur = con.execute(
                    "INSERT INTO verdict_log (logged_at, logged_date, ticker, entry_price, verdict, "
                    "conviction, horizon, composite_action, source) VALUES (?,?,?,?,?,?,?,?,?)",
                    (f"{day}T16:00:00", day, tk, 100.0, "BUY", 70, "medium", "BUY", src))
                con.execute("INSERT INTO verdict_forward_returns (verdict_log_id, ret_5d, nifty_ret_5d) "
                            "VALUES (?,?,?)", (cur.lastrowid, ret, 0.5))
                if tag:
                    con.execute("INSERT INTO verdict_signal_tags (verdict_log_id, tag) VALUES (?,?)",
                                (cur.lastrowid, tag))
    page = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "dashboard", "pages", "09_verdict_calibration.py")
    at = AppTest.from_file(page, default_timeout=120).run()
    assert not at.exception, at.exception
    tbl = next(d.value for d in at.dataframe if "List" in d.value.columns)
    assert list(tbl.columns[:7]) == ["List", "What counts as a hit", "Picks", "Days",
                                     "Hit vs Nifty (5 days)", "Cautious estimate",
                                     "Avg vs Nifty after costs"]
    top = tbl[tbl["List"] == "Top Picks"].iloc[0]
    assert top["Picks"] == 12 and top["Hit vs Nifty (5 days)"] == "100%"
    assert top["Avg vs Nifty after costs"] == "+2.25%"
    dn = tbl[tbl["List"] == "Tomorrow's Watchlist · Breakdown risk"].iloc[0]
    assert dn["What counts as a hit"] == "Lagged the Nifty" and dn["Hit vs Nifty (5 days)"] == "100%"
    text = " ".join(str(m.value) for m in (*at.markdown, *at.caption, *at.info))
    assert "Results by list" in text and "Tomorrow's Watchlist test" in text
    assert "close to close" in text
    assert "BUY/STRONG BUY" not in text and "STRONG BUY / BUY" not in text
