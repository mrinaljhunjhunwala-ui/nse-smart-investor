"""Owner, 17 Nov: remaining fix list, batch A (bugs)."""
import datetime as dt

import numpy as np
import pandas as pd

from trading.paper_exits import REASON_MIS, find_exit, mis_session


def _bars(rows):
    idx = pd.to_datetime([r[0] for r in rows])
    return pd.DataFrame([r[1:] for r in rows], index=idx, columns=["Open", "High", "Low", "Close"])


BARS = _bars([("2026-11-13", 100, 101, 99, 100), ("2026-11-16", 100, 103, 99, 102),
              ("2026-11-17", 102, 104, 101, 103)])


def test_mis_entered_after_the_close_squares_at_the_next_session():
    hit = find_exit(BARS, "2026-11-13T20:05:00", sl=0, tp=0, product="MIS", today=dt.date(2026, 11, 17))
    assert hit["exit_date"] == dt.date(2026, 11, 16) and hit["exit_price"] == 102     # was Fri 13th's close
    assert hit["reason"] == REASON_MIS


def test_mis_entered_at_the_weekend_and_in_session():
    assert mis_session(BARS.index.date, "2026-11-15T11:00:00") == dt.date(2026, 11, 16)    # Sunday
    assert mis_session(BARS.index.date, "2026-11-16T10:00:00") == dt.date(2026, 11, 16)
    # entered after the last bar's close, session not happened yet -> stays open
    assert find_exit(BARS, "2026-11-17T16:00:00", sl=0, tp=0, product="MIS", today=dt.date(2026, 11, 17)) is None


def test_portfolio_risk_says_when_a_recent_listing_shortens_the_window():
    from analysis.portfolio_risk import window_note
    old = pd.Series(np.ones(250), index=pd.bdate_range(end="2026-11-17", periods=250))
    new = pd.Series(np.ones(60), index=pd.bdate_range(end="2026-11-17", periods=60))
    panel = pd.DataFrame({"OLD.NS": old, "NEWIPO.NS": new}).dropna()
    note = window_note({"OLD.NS": old, "NEWIPO.NS": new}, panel)
    assert "NEWIPO" in note and "60 trading days" in note
    assert window_note({"OLD.NS": old}, pd.DataFrame({"OLD.NS": old})) == ""


def test_angel_holding_without_a_price_is_flagged(monkeypatch):
    import data.angel_fetcher as af

    class R:
        status_code = 200

        def json(self):
            return {"data": [{"tradingsymbol": "ABC-EQ", "quantity": 10, "realisedquantity": 10,
                              "averageprice": 100, "ltp": 0}]}

    class S:
        def get(self, url, headers=None, timeout=None):
            return R()
    monkeypatch.setattr(af, "_http", S())
    monkeypatch.setattr(af, "_get_session", lambda: {"jwt": "J", "api_key": "K"})
    h = af.get_holdings()[0]
    assert h["ltp_missing"] is True and h["pnl"] == 0          # was a silent ₹0 P&L with no flag
