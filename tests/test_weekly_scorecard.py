"""Plain-language calibration summary + Friday weekly report card. Offline."""
import datetime as dt

import pandas as pd

import alerts.check_alerts as ca
from analysis import verdict_ledger as vl


def _res(status, n_alpha=0, days=0, win=None):
    return {"status": status, "n_alpha": n_alpha, "alpha_days": days,
            "day_win_vs_nifty": win, "rule": vl.DECISION_RULE}


def test_plain_summary_states():
    s = vl.plain_summary(_res("insufficient", 80, 12, 58.0), pending_days=5)
    assert s["state"] == "too_early" and "Too early" in s["headline"]
    assert "13 more trading days" in s["detail"]                  # 30 - 12 - 5
    assert "58% of the 12 scored days" in s["so_far"]
    assert 0 < s["picks_progress"] < 1 and s["days_progress"] == 12 / 30
    assert vl.plain_summary(_res("insufficient", 80, 12), pending_days=40)["detail"].startswith("Enough days")
    assert vl.plain_summary(_res("met", 200, 35, 70.0))["state"] == "passing"
    assert vl.plain_summary(_res("not_met", 200, 35, 45.0))["state"] == "failing"
    assert vl.plain_summary(_res("unavailable"))["state"] == "unavailable"


def _rows():
    return pd.DataFrame([
        {"ticker": "AAA.NS", "logged_date": "2026-11-02", "entry_price": 100.0, "verdict": "BUY",
         "source": "shadow_auto"},
        {"ticker": "AAA.NS", "logged_date": "2026-11-04", "entry_price": 120.0, "verdict": "BUY",
         "source": "shadow_auto"},
        {"ticker": "BBB.NS", "logged_date": "2026-11-03", "entry_price": 200.0, "verdict": "STRONG BUY",
         "source": "shadow_auto"},
        {"ticker": "CCC.NS", "logged_date": "2026-11-03", "entry_price": 50.0, "verdict": "WATCH",
         "source": "analyze_page"},
    ])


def _nifty():
    idx = pd.to_datetime(["2026-11-02", "2026-11-03", "2026-11-04", "2026-11-05", "2026-11-06"])
    return pd.Series([1000.0, 1000.0, 1010.0, 1020.0, 1020.0], index=idx)


def test_week_scorecard_math():
    card = vl.week_scorecard(_rows(), {"AAA.NS": 110.0, "BBB.NS": 190.0}, _nifty(), 1020.0)
    assert card["n"] == 2                                     # first log per ticker; WATCH dropped
    assert round(card["mean_move"], 2) == 2.5                 # (+10 − 5) / 2
    assert card["up"] == 1 and card["ahead"] == 1             # Nifty +2% from both log days
    assert round(card["mean_edge"], 2) == 0.5
    assert vl.week_scorecard(_rows(), {}, _nifty(), 1020.0) is None


def test_scorecard_sends_on_friday_only_and_once(monkeypatch):
    from tests.test_alert_copy_no_advice import _assert_descriptive
    monkeypatch.setattr(vl, "load_ledger", lambda **k: _rows())
    monkeypatch.setattr(vl, "ledger_error", lambda df: None)
    monkeypatch.setattr(ca, "_quote", lambda b: {"price": {"AAA": 110.0, "BBB": 190.0}.get(b)})
    import data.fetcher as f
    monkeypatch.setattr(f, "fetch_single", lambda *a, **k: pd.DataFrame({"Close": _nifty()}))
    sent = []
    monkeypatch.setattr(ca, "dispatch", lambda m, **k: sent.append(m) or True)
    ist = dt.timezone(dt.timedelta(hours=5, minutes=30))
    thu = dt.datetime(2026, 11, 5, 16, 0, tzinfo=ist)
    fri = dt.datetime(2026, 11, 6, 16, 0, tzinfo=ist)
    state = {}
    assert ca.check_weekly_scorecard(state, "2026-11-05", now=thu) == 0
    assert ca.check_weekly_scorecard(state, "2026-11-06", now=fri) == 1
    assert ca.check_weekly_scorecard(state, "2026-11-06", now=fri) == 0
    _assert_descriptive(sent[0])
    assert "2 names" in sent[0] and "+2.5%" in sent[0] and "AAA +10.0%" in sent[0]


def _sector_rows():
    names = [("B1", 100, 110), ("B2", 100, 108), ("B3", 100, 112),      # Banks: +10 / +8 / +12
             ("I1", 100, 95), ("I2", 100, 97), ("I3", 100, 96),        # IT: -5 / -3 / -4
             ("X1", 100, 130), ("O1", 100, 101)]                        # one-name sector, unmapped
    rows = pd.DataFrame([{"ticker": f"{t}.NS", "logged_date": "2026-11-03", "entry_price": float(e),
                          "verdict": "BUY", "source": "shadow_auto"} for t, e, _ in names])
    return rows, {f"{t}.NS": float(p) for t, _, p in names}


def _sector_of(ticker):
    return {"B": "Banks", "I": "IT", "X": "Metals"}.get(ticker[0], "Other")


def test_week_scorecard_sector_split_and_median():
    rows, prices = _sector_rows()
    card = vl.week_scorecard(rows, prices, _nifty(), 1020.0, sector_of=_sector_of)
    assert [s["sector"] for s in card["sectors"]] == ["Banks", "IT"]      # best first; <3 names and Other left out
    assert card["sectors"][0]["n"] == 3 and round(card["sectors"][0]["mean_edge"], 1) == 8.0   # +10 avg − Nifty +2
    assert round(card["sectors"][1]["mean_edge"], 1) == -6.0
    assert round(card["median_move"], 1) == 4.5 and card["mean_move"] > card["median_move"]
    assert vl.week_scorecard(rows, prices, _nifty(), 1020.0)["sectors"] == []           # no map, no split

    def _boom(t):
        raise KeyError(t)
    assert vl.week_scorecard(rows, prices, _nifty(), 1020.0, sector_of=_boom)["sectors"] == []


def test_scorecard_message_shows_sectors_and_median():
    from tests.test_alert_copy_no_advice import _assert_descriptive
    rows, prices = _sector_rows()
    cards = {"top_picks": vl.week_scorecard(rows, prices, _nifty(), 1020.0, sector_of=_sector_of)}
    msg = "\n".join(ca.weekly_scorecard_lines(cards, "2026-11-02", "2026-11-06"))
    _assert_descriptive(msg)
    assert "By sector, vs the Nifty (names): Banks +8.0 pts (3) · IT -6.0 pts (3)" in msg
    assert "Middle name (median): +4.5%" in msg
    assert ca._sector_lines([{"sector": "Banks", "n": 3, "mean_edge": 8.0}]) == []        # one sector says nothing
