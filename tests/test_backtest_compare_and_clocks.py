"""Audit 2026-11: Backtest comparison chart was empty on 1M / 6M; 'IST' clocks printed UTC."""
import numpy as np
import pandas as pd


def _bars(n):
    idx = pd.bdate_range(end="2026-11-16", periods=n)
    c = pd.Series(np.linspace(100, 120, n), index=idx)
    return pd.DataFrame({"Open": c, "High": c + 1, "Low": c - 1, "Close": c, "Volume": 1e6})


def test_comparison_loader_keeps_the_whole_period(monkeypatch):
    import data.fetcher as fetcher
    from dashboard.shared import cache
    monkeypatch.setattr(fetcher, "fetch_single", lambda t, period="2y", **k: _bars(130))
    cache.load_close_series.clear()
    s = cache.load_close_series("TCS.NS", period="6m")
    assert len(s) == 130                         # load_ticker_df returned 0 rows (SMA_200 warm-up)
    cache.load_close_series.clear()


def test_backtest_page_no_longer_uses_the_indicator_loader_for_the_chart():
    src = open("dashboard/pages/11_backtest.py", encoding="utf-8").read()
    assert "load_close_series(t, period=comp_period)" in src and "load_ticker_df(" not in src


def test_no_naive_clock_labelled_ist_in_the_ui():
    import pathlib
    import re
    bad = []
    for p in list(pathlib.Path("dashboard/pages").glob("*.py")) + list(pathlib.Path("dashboard/views").glob("*.py")):
        if p.name.startswith("01_") or p.name == "research_notes.py":
            continue
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if re.search(r"datetime\.now\(\)\.strftime\(", line):
                bad.append(f"{p}:{i}")
    assert not bad, bad          # Streamlit Cloud runs UTC: these printed 04:50 for 10:20 IST


def test_fii_dii_does_not_refetch_on_every_rerun(monkeypatch):
    import datetime as dt
    from analysis import fii_dii
    calls = []
    monkeypatch.setattr(fii_dii, "ensure_schema", lambda: None)
    monkeypatch.setattr(fii_dii, "_fetch_nse", lambda: calls.append(1) or [])
    monkeypatch.setattr(fii_dii, "_fetch_nse_exchange_only", lambda: [])
    monkeypatch.setattr(fii_dii, "_LAST_ATTEMPT", {"t": 0.0})
    # Saturday: Friday's figures are stored and current; NSE was asked on every rerun before
    monkeypatch.setattr(fii_dii, "_last_closed_session", lambda: dt.date(2026, 11, 13))
    monkeypatch.setattr(fii_dii, "load_history", lambda days=3: pd.DataFrame({"date": ["2026-11-13"]}))
    assert fii_dii.refresh()["source"] == "cache" and calls == []
    # Monday evening, before NSE publishes: ask once, then not again for 15 minutes
    monkeypatch.setattr(fii_dii, "_last_closed_session", lambda: dt.date(2026, 11, 16))
    fii_dii.refresh()
    fii_dii.refresh()
    assert calls == [1]
    fii_dii.refresh(force=True)
    assert calls == [1, 1]
