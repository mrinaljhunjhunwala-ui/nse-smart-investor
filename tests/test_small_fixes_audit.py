"""Audit 2026-11 follow-up: gap scanner, paper-trade stops, FII/DII freshness, mover volume."""
import datetime as dt
import time

import numpy as np
import pandas as pd
import pytest


def test_gap_scan_says_how_many_stocks_were_checked(monkeypatch):
    from trading import gap_scanner as G
    monkeypatch.setattr(G, "_single_gap", lambda t: None)              # network down: no data
    df = G.scan_gaps(["A.NS", "B.NS"])
    assert df.empty and df.attrs == {"checked": 0, "total": 2}         # was read as "opened flat"


def test_gap_scan_timeout_does_not_raise(monkeypatch):
    from trading import gap_scanner as G
    monkeypatch.setattr(G, "as_completed", lambda futs, timeout=None: (_ for _ in ()).throw(G.FuturesTimeout()))
    monkeypatch.setattr(G, "_single_gap", lambda t: time.sleep(0.01))
    df = G.scan_gaps(["A.NS"])                                         # used to raise into the tab
    assert df.attrs["checked"] == 0


def test_open_trade_rejects_impossible_stops(monkeypatch):
    import trade_store as S
    monkeypatch.setattr(S, "ensure_schema", lambda: (_ for _ in ()).throw(AssertionError("validated first")))
    with pytest.raises(ValueError):
        S.open_trade("X.NS", 100, 1, -5, 0)                            # negative stop was saved
    with pytest.raises(ValueError):
        S.open_trade("X.NS", 100, 1, 95, 0, action="SHORT")            # short stop below entry
    with pytest.raises(ValueError):
        S.open_trade("X.NS", 100, 1, 105, 0)                           # long stop above entry


def test_fii_dii_this_week_ignores_stale_rows():
    from analysis.fii_dii import recent_flows
    df = pd.DataFrame({"date": ["2026-10-01", "2026-10-02", "2026-10-03"], "fii_net": [1, 2, 3],
                       "dii_net": [1, 1, 1]})
    assert recent_flows(df, today=dt.date(2026, 11, 17)).empty         # EOD job stopped weeks ago
    fresh = pd.DataFrame({"date": ["2026-11-13", "2026-11-14", "2026-11-17"], "fii_net": [1, 2, 3],
                          "dii_net": [1, 1, 1]})
    assert len(recent_flows(fresh, today=dt.date(2026, 11, 17))) == 3


def test_mover_volume_ratio_is_measured():
    from utils.indicators import volume_ratio_today
    idx = pd.bdate_range(end="2026-11-17", periods=30)
    df = pd.DataFrame({"Close": np.ones(30), "Volume": [100.0] * 29 + [50.0]}, index=idx)
    assert volume_ratio_today(df, today_volume=300) == 3.0             # was always 1.0
    assert volume_ratio_today(df) == 0.5
    assert volume_ratio_today(df.iloc[:5]) is None
