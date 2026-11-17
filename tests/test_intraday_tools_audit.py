"""Audit 2026-11: intraday CPR from the previous session; Position Sizer price limits."""
import numpy as np
import pandas as pd

from utils.indicators import add_pivot_points


def _two_sessions():
    idx = []
    for d in ("2026-11-16", "2026-11-17"):
        idx += list(pd.date_range(f"{d} 09:15", f"{d} 15:25", freq="5min", tz="Asia/Kolkata"))
    idx = pd.DatetimeIndex(idx)
    rng = np.random.default_rng(1)
    c = 1000 + np.cumsum(rng.normal(0, 2, len(idx)))
    return pd.DataFrame({"Open": c, "High": c + 1.5, "Low": c - 1.5, "Close": c, "Volume": 1000}, index=idx)


def test_intraday_pivot_is_the_previous_sessions_and_constant_through_the_day():
    df = add_pivot_points(_two_sessions())
    d1 = df[df.index.date == pd.Timestamp("2026-11-16").date()]
    d2 = df[df.index.date == pd.Timestamp("2026-11-17").date()]
    want = (d1["High"].max() + d1["Low"].min() + d1["Close"].iloc[-1]) / 3
    assert d2["Pivot"].nunique() == 1                    # took 40+ values a day (previous 5-min bar)
    assert abs(d2["Pivot"].iloc[-1] - want) < 1e-9
    assert d1["Pivot"].isna().all()                      # no previous session in the frame


def test_daily_pivot_unchanged():
    idx = pd.bdate_range("2026-11-02", periods=5)
    df = pd.DataFrame({"High": [11, 12, 13, 14, 15.0], "Low": [9, 10, 11, 12, 13.0],
                       "Close": [10, 11, 12, 13, 14.0]}, index=idx)
    out = add_pivot_points(df)
    assert out["Pivot"].iloc[-1] == (14 + 12 + 13) / 3


def test_position_sizer_keeps_a_high_priced_stock():
    from streamlit.testing.v1 import AppTest

    def app():
        import streamlit as st
        st.session_state.setdefault("ps_entry", 140000.0)
        st.session_state.setdefault("ps_sl", 137200.0)
        from dashboard.views import position_sizer
        position_sizer.render()
        st.session_state["seen"] = (st.session_state["ps_entry"], st.session_state["ps_sl"])

    at = AppTest.from_function(app, default_timeout=60).run()
    assert not at.exception, at.exception
    assert at.session_state["seen"] == (140000.0, 137200.0)      # came back as (1.0, 1.0)
