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
