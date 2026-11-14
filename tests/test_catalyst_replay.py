"""Replay grading and an end-to-end run with every fetcher stubbed. Offline."""
import datetime as dt

import numpy as np
import pandas as pd

import scripts.catalyst_replay as R

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))


def test_grade_day_buy_paths():
    g = R.grade_day("BUY", 100, 98, 104, o=99, h=105, lo=99, c=103)
    assert g["entered"] and g["outcome"] == "target" and g["r"] == 2.0
    assert R.grade_day("BUY", 100, 98, 104, o=99, h=105, lo=97, c=103)["outcome"] == "stop"     # both touched
    assert R.grade_day("BUY", 100, 98, 104, o=99, h=99.5, lo=98.5, c=99)["outcome"] == "no_entry"
    g = R.grade_day("BUY", 100, 98, 104, o=101, h=103, lo=100, c=102.5)                          # opens above trigger
    assert g["entry"] == 101 and g["outcome"] == "close" and round(g["r"], 2) == 0.5
    assert R.grade_day("WATCH", 100, 98, 104, 99, 105, 97, 103)["outcome"] == "no_plan"


def test_grade_day_sell_mirrors():
    g = R.grade_day("SELL", 100, 102, 96, o=101, h=101.5, lo=95, c=97)
    assert g["entered"] and g["outcome"] == "target" and g["r"] == 2.0
    assert R.grade_day("SELL", 100, 102, 96, o=101, h=103, lo=95, c=97)["outcome"] == "stop"
    assert R.grade_day("SELL", 100, 102, 96, o=101, h=101.5, lo=100.5, c=101)["outcome"] == "no_entry"


def test_summarise_and_report():
    rows = [
        {"date": "2026-11-10", "symbol": "AAA", "kind": "results", "action": "BUY", "strength": 80, "entered": True,
         "outcome": "target", "r": 2.0, "open_to_close": 3.0, "open_to_last": 5.0, "nifty_to_last": 1.0,
         "bucket": R.surprise_bucket(70), "gap": 2.0, "day_move": 5.0, "reasons": ["Q2 profit +86%"]},
        {"date": "2026-11-10", "symbol": "BBB", "kind": "results", "action": "BUY", "strength": 60, "entered": True,
         "outcome": "stop", "r": -1.0, "open_to_close": -2.0, "open_to_last": -3.0, "nifty_to_last": 1.0,
         "bucket": R.surprise_bucket(30), "gap": 3.0, "day_move": 1.0, "reasons": []},
        {"date": "2026-11-11", "symbol": "CCC", "kind": "results", "action": "WATCH", "strength": 40,
         "entered": False, "outcome": "no_plan", "r": None, "open_to_close": 0.5, "open_to_last": 0.2,
         "nifty_to_last": 0.4, "bucket": R.surprise_bucket(-40), "gap": -1.0, "day_move": -0.5, "reasons": []},
    ]
    s = R.summarise(rows)
    b = s["by_action"]["BUY"]
    assert b["n"] == 2 and b["entered"] == 2 and b["target"] == 1 and b["stop"] == 1 and b["avg_r"] == 0.5
    assert b["avg_vs_nifty_to_last"] == 0.0
    assert s["by_bucket"]["strong results (score >= +25)"]["n"] == 2
    assert s["by_bucket"]["weak results (score <= -25)"]["up_on_day"] == 0
    text = "\n".join(R.report_lines(rows, s, [dt.date(2026, 11, 10), dt.date(2026, 11, 11)]))
    assert "AAA" in text and "Limits:" in text
    tg = R.telegram_lines(s, [dt.date(2026, 11, 10), dt.date(2026, 11, 11)])
    assert len(tg) <= 15 and tg[1].startswith("BUY: 2 calls")
    assert R.surprise_bucket(None) == "no figures" and R.surprise_bucket(0) == "mixed results"


def _frame(end, n=70, jump=None):
    idx = pd.bdate_range(end=end, periods=n)
    close = np.linspace(95.0, 100.0, n)
    if jump:
        close[-jump:] = close[-jump:] * 1.06
    return pd.DataFrame({"Open": close * 0.995, "High": close * 1.02, "Low": close * 0.985, "Close": close,
                         "Volume": np.full(n, 2_000_000.0)}, index=idx)


def test_run_end_to_end_with_stubs(monkeypatch):
    import alerts.catalyst_alerts as CA
    import data.fetcher as F
    import data.nse_announcements as NA
    import data.universe as U

    end = "2026-11-13"
    monkeypatch.setattr(F, "fetch_index", lambda *a, **k: _frame(end))
    monkeypatch.setattr(F, "fetch_single", lambda t, **k: _frame(end, jump=2) if t.startswith("GOOD") else None)
    monkeypatch.setattr(U, "get_universe", lambda level="all": ["GOOD.NS", "GONE.NS"])
    monkeypatch.setattr(U, "get_sector", lambda t: "IT")
    monkeypatch.setattr(CA, "_holidays", lambda: frozenset())
    monkeypatch.setattr(R.time, "sleep", lambda s: None)
    filed = dt.datetime(2026, 11, 11, 18, 30, tzinfo=IST)                     # after Wednesday's close

    def _ann(since, until=None):
        if since.date() != filed.date():
            return []
        return [{"symbol": s, "when": filed, "category": "Financial Result Updates",
                 "headline": "Unaudited financial results for the quarter ended September 30, 2026",
                 "detail": "", "url": "", "source": "nse_api"} for s in ("GOOD", "GONE", "NOTINUNIVERSE")]
    monkeypatch.setattr(NA, "fetch_announcements", _ann)
    q = [{"period_end": dt.date(2026, 9, 30), "revenue": 138.0, "net_profit": 41.0, "eps": 1.5},
         {"period_end": dt.date(2026, 6, 30), "revenue": 110.0, "net_profit": 28.0, "eps": 1.0},
         {"period_end": dt.date(2026, 3, 31), "revenue": 105.0, "net_profit": 25.0, "eps": 0.9},
         {"period_end": dt.date(2025, 12, 31), "revenue": 102.0, "net_profit": 24.0, "eps": 0.9},
         {"period_end": dt.date(2025, 9, 30), "revenue": 100.0, "net_profit": 22.0, "eps": 0.8}]
    monkeypatch.setattr(NA, "fetch_quarterly_figures", lambda sym: q)
    res = R.run(3, 10)
    assert [r["symbol"] for r in res["rows"]] == ["GOOD"]                       # no bars / outside universe dropped
    row = res["rows"][0]
    assert row["date"] == "2026-11-12" and row["kind"] == "results"             # traded at the next open
    assert row["bucket"].startswith("strong results") and row["action"] in ("BUY", "WATCH")
    assert row["gap"] is not None and row["day_move"] is not None
    assert R.report_lines(res["rows"], res["summary"], res["sessions"])


def _b(o, h, lo, c):
    return {"open": o, "high": h, "low": lo, "close": c}


def test_grade_intraday_walks_bars_in_order():
    # low BEFORE the entry does not stop the trade (the daily-bar grader could not tell)
    bars = [_b(99, 99.5, 97, 99.4), _b(99.4, 100.5, 99.3, 100.4), _b(100.4, 104.5, 100.2, 104)]
    g = R.grade_intraday("BUY", 100, 98, 104, bars)
    assert g["entered"] and g["outcome"] == "target" and g["r"] == 2.0
    g = R.grade_intraday("BUY", 100, 98, 104, [_b(99, 100.5, 99, 100.2), _b(100.2, 100.4, 97.5, 98)])
    assert g["outcome"] == "stop" and g["r"] == -1.0
    g = R.grade_intraday("BUY", 100, 98, 104, [_b(99, 100.5, 99, 100.2), _b(100.2, 101.5, 99.5, 101)])
    assert g["outcome"] == "close" and round(g["r"], 2) == 0.5
    assert R.grade_intraday("BUY", 100, 98, 104, [_b(99, 99.8, 98.5, 99)])["outcome"] == "no_entry"
    assert R.grade_intraday("BUY", 100, 98, 104, [_b(99, 104.5, 97, 97.5)])["outcome"] == "stop"   # closes through stop
    g = R.grade_intraday("SELL", 100, 102, 96, [_b(101, 101.2, 99.5, 99.8), _b(99.8, 100, 95.5, 96)])
    assert g["outcome"] == "target" and g["r"] == 2.0
    assert R.grade_intraday("WATCH", 100, 98, 104, bars)["outcome"] == "no_plan"


def test_day_bars_15m_handles_utc_and_ist_indexes():
    utc = pd.date_range("2026-11-12 03:45", periods=25, freq="15min")           # naive UTC = 09:15 IST
    df = pd.DataFrame({"Open": 1.0, "High": 2.0, "Low": 0.5, "Close": 1.5}, index=utc)
    bars = R.day_bars_15m(df, dt.date(2026, 11, 12))
    assert len(bars) == 25 and bars[0]["t"].time() == dt.time(9, 15)
    aware = df.copy()
    aware.index = utc.tz_localize("UTC")
    assert len(R.day_bars_15m(aware, dt.date(2026, 11, 12))) == 25
    ist = df.copy()
    ist.index = pd.date_range("2026-11-12 09:15", periods=25, freq="15min")
    assert R.day_bars_15m(ist, dt.date(2026, 11, 12))[0]["t"].time() == dt.time(9, 15)
    assert R.day_bars_15m(None, dt.date(2026, 11, 12)) == []


def test_telegram_lines_escape_bucket_names():
    """Bucket names carry raw <= / >=; unescaped they made Telegram reject the HTML send."""
    rows = [{"date": "2026-11-10", "symbol": s, "kind": "results", "action": "WATCH", "entered": False,
             "outcome": "no_plan", "r": None, "bucket": R.surprise_bucket(sc), "day_move": 1.0}
            for s, sc in (("AAA", 70), ("BBB", -40))]
    tg = "\n".join(R.telegram_lines(R.summarise(rows), [dt.date(2026, 11, 10)]))
    assert "score &gt;= +25" in tg and "score &lt;= -25" in tg
    import re
    assert not re.search(r"<(?!/?b>)", tg) and ">=" not in tg.replace("&gt;=", "")


def test_grade_held_paths():
    # no close under the stop: out at the close 5 sessions after the entry day
    g = R.grade_held("BUY", 100.0, 95.0, [101, 102, 99, 103, 104, 110, 150])
    assert g["h_outcome"] == "time" and g["h_days"] == 5 and round(g["h_pct"], 6) == 10.0
    # an intraday dip is not seen; the first CLOSE below the stop ends it
    g = R.grade_held("BUY", 100.0, 95.0, [101, 94, 120])
    assert g["h_outcome"] == "stop_close" and g["h_days"] == 1 and round(g["h_pct"], 6) == -6.0
    # fewer than 5 sessions of history: marked at the latest close
    g = R.grade_held("BUY", 100.0, 95.0, [101, 103])
    assert g["h_outcome"] == "open" and round(g["h_pct"], 6) == 3.0
    # SELL mirrors: a close above the stop ends it, a fall is a profit
    assert round(R.grade_held("SELL", 100.0, 105.0, [98, 96])["h_pct"], 6) == 4.0
    assert R.grade_held("SELL", 100.0, 105.0, [106, 90])["h_outcome"] == "stop_close"
    assert R.grade_held("WATCH", 100.0, 95.0, [101])["h_pct"] is None
    assert R.grade_held("BUY", None, 95.0, [101])["h_pct"] is None


def test_held_grade_in_summary_report_and_telegram():
    base = {"date": "2026-11-10", "kind": "news", "action": "BUY", "entered": True, "outcome": "close", "r": 0.2,
            "bucket": "no figures"}
    rows = [{**base, "symbol": "AAA", **R.grade_held("BUY", 100.0, 95.0, [101, 102, 103, 104, 105, 108])},
            {**base, "symbol": "BBB", **R.grade_held("BUY", 100.0, 95.0, [94])},
            {**base, "symbol": "CCC", "entered": False, "outcome": "no_entry", "r": None}]
    s = R.summarise(rows)
    assert s["by_action"]["BUY"]["held"] == {"graded": 2, "wins": 1, "stopped": 1, "avg_pct": 1.0}
    days = [dt.date(2026, 11, 10)]
    text = "\n".join(R.report_lines(rows, s, days))
    assert "2 held | profitable 1 | closed beyond stop 1 | average +1.0%" in text
    assert any(ln.startswith("BUY held 5 sessions: 2 trades · 1 profitable · average +1.0%")
               for ln in R.telegram_lines(s, days))


def test_fetch_15m_asks_for_the_widest_range_then_falls_back():
    asked = []

    def ok(t, period, interval):
        asked.append((period, interval))
        return pd.DataFrame({"Close": [1.0]})
    assert R.fetch_15m(ok, "X.NS") is not None and asked == [("60d", "15m")]

    def only_month(t, period, interval):
        asked.append((period, interval))
        if period == "60d":
            raise ValueError("range not served")
        return pd.DataFrame({"Close": [1.0]})
    asked.clear()
    assert R.fetch_15m(only_month, "X.NS") is not None and [a[0] for a in asked] == ["60d", "1mo"]
    assert R.fetch_15m(lambda t, period, interval: pd.DataFrame(), "X.NS") is None


def test_fetcher_serves_60d_for_15m():
    """The replay's widest 15-minute request must be a period data/fetcher knows."""
    import inspect

    import data.fetcher as F
    assert '"60d"' in inspect.getsource(F._fetch_yahoo_direct)
    assert R.INTRADAY_15M_PERIODS[0] == "60d"
