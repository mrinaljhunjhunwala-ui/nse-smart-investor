"""Offline tests for the 15 Nov fixes: stale daily frame patched from the
bhavcopy, end-of-day quotes not shown as live, Market Overview empty-data guard."""
import datetime as dt
import pathlib

import pandas as pd
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
TODAY = dt.date(2026, 11, 13)                                   # Friday


def _frame(days, closes):
    idx = pd.DatetimeIndex([pd.Timestamp(d) for d in days], name="Date")
    c = pd.Series(closes, index=idx, dtype=float)
    return pd.DataFrame({"Open": c, "High": c + 1, "Low": c - 1, "Close": c, "Volume": 1000.0})


def _bdays(end, n):
    return [d.date() for d in pd.bdate_range(end=end, periods=n)]


@pytest.fixture
def F(monkeypatch):
    import data.fetcher as F
    monkeypatch.setattr(F, "_ist_today", lambda: TODAY)
    return F


def _bhav(monkeypatch, frame):
    import data.nse_bhavcopy_prices as bp
    calls = []

    def fake(ticker, period="2y", **k):
        calls.append((ticker, period))
        if frame is None:
            raise ValueError("no rows")
        return frame
    monkeypatch.setattr(bp, "fetch_bhavcopy_history", fake)
    return calls


def test_stale_frame_gets_the_missing_sessions_from_bhavcopy(F, monkeypatch):
    days = _bdays(dt.date(2026, 11, 6), 40)                     # Yahoo stopped on Fri 6 Nov
    df = _frame(days, [100.0] * 40)
    assert F._coverage_problem(df, "2mo") == "stale"
    bhav = _frame(_bdays(dt.date(2026, 11, 12), 6), [99, 100.2, 101, 102, 103, 104])   # 5..12 Nov
    calls = _bhav(monkeypatch, bhav)
    out = F._patch_stale_from_bhavcopy(df, "ABC.NS", "2mo")
    assert calls == [("ABC.NS", "1mo")]
    assert len(out) == 44 and out.index.max().date() == dt.date(2026, 11, 12)
    assert list(out["Close"].iloc[-4:]) == [101.0, 102.0, 103.0, 104.0]
    assert out["Close"].iloc[39] == 100.0                       # Yahoo's own last bar is kept
    assert out.attrs["patched_from"] == "NSE-bhavcopy" and out.attrs["patched_bars"] == 4
    assert out.index.is_monotonic_increasing and not out.index.has_duplicates
    assert F._coverage_problem(out, "2mo") is None
    assert len(df) == 40                                        # input untouched


def test_fresh_frame_and_indices_are_left_alone(F, monkeypatch):
    calls = _bhav(monkeypatch, None)
    fresh = _frame(_bdays(dt.date(2026, 11, 12), 40), [100.0] * 40)
    assert F._patch_stale_from_bhavcopy(fresh, "ABC.NS", "2mo") is fresh
    stale = _frame(_bdays(dt.date(2026, 11, 6), 40), [100.0] * 40)
    assert F._patch_stale_from_bhavcopy(stale, "^NSEI", "2mo") is stale
    assert calls == []                                          # no bhavcopy request for either


def test_stale_frame_not_patched_on_any_doubt(F, monkeypatch):
    stale = _frame(_bdays(dt.date(2026, 11, 6), 40), [100.0] * 40)
    late = _bdays(dt.date(2026, 11, 12), 6)
    # a split inside the gap: bhavcopy (unadjusted) disagrees with the frame's last close
    _bhav(monkeypatch, _frame(late, [200, 200, 100, 101, 102, 103]))
    assert F._patch_stale_from_bhavcopy(stale, "ABC.NS", "2mo") is stale
    # the closes agree on the last bar but then jump 50%
    _bhav(monkeypatch, _frame(late, [100, 100, 150, 151, 152, 153]))
    assert F._patch_stale_from_bhavcopy(stale, "ABC.NS", "2mo") is stale
    # no overlap day to compare prices on
    _bhav(monkeypatch, _frame(late[2:], [101, 102, 103, 104]))
    assert F._patch_stale_from_bhavcopy(stale, "ABC.NS", "2mo") is stale
    # stock really stopped trading: nothing after the last bar
    _bhav(monkeypatch, _frame(late[:2], [100, 100]))
    assert F._patch_stale_from_bhavcopy(stale, "ABC.NS", "2mo") is stale
    # bhavcopy unreachable: never raises
    _bhav(monkeypatch, None)
    assert F._patch_stale_from_bhavcopy(stale, "ABC.NS", "2mo") is stale


def test_fetch_single_serves_the_patched_frame(F, monkeypatch):
    stale = _frame(_bdays(dt.date(2026, 11, 6), 40), [100.0] * 40)
    _bhav(monkeypatch, _frame(_bdays(dt.date(2026, 11, 12), 6), [100, 100, 101, 102, 103, 104]))
    monkeypatch.setattr(F, "_fetch_yahoo_direct", lambda t, period="1y", interval="1d": stale.copy())
    monkeypatch.setattr(F, "_stooq_enabled", lambda: False)
    monkeypatch.setattr(F, "_price_store_split_check", lambda *a, **k: None)
    monkeypatch.setenv("ANGEL_API_KEY", "")
    F.clear_cache() if hasattr(F, "clear_cache") else None
    out = F.fetch_single("PATCHME.NS", period="2mo")
    assert out.index.max().date() == dt.date(2026, 11, 12) and float(out["Close"].iloc[-1]) == 104.0


# ── end-of-day quotes are not shown as live ──────────────────────────────────
def test_trade_utils_passes_the_eod_flag_through(monkeypatch):
    import dashboard.shared.trade_utils as tu
    import utils.live_price as lp
    q = {"price": 50.0, "prev_close": 49.0, "chg_pct": 2.0, "eod": True, "as_of": "2026-11-09T15:29:00+05:30"}
    monkeypatch.setattr(lp, "get_live_prices_batch", lambda tickers, **k: {tickers[0]: dict(q)})
    tu._fetch_single_live_price.clear()
    out = tu._fetch_single_live_price("X.NS")
    assert out["price"] == 50.0 and out["eod"] is True and out["as_of"].startswith("2026-11-09")
    monkeypatch.setattr(lp, "get_live_prices_batch",
                        lambda tickers, **k: {tickers[0]: {"price": 50.0, "prev_close": 49.0, "chg_pct": 2.0}})
    assert "eod" not in tu._fetch_single_live_price("Y.NS")           # other ticker: the function is cached


def test_live_ticker_tags_an_eod_quote():
    from dashboard.views import market_live as ml
    assert ml._eod_tag({"as_of": "2026-11-09T15:29:00+05:30"}) == " · last traded 2026-11-09"
    assert ml._eod_tag({}) == " · not live"
    src = (ROOT / "dashboard" / "views" / "market_live.py").read_text(encoding="utf-8")
    assert src.count('_eod_tag(q) if q.get("eod")') == 2


def test_paper_trades_live_badge_ignores_eod_quotes():
    src = (ROOT / "dashboard" / "pages" / "06_paper_trades.py").read_text(encoding="utf-8")
    assert '_has_live = bool(_lp.get("price")) and not _lp.get("eod")' in src


def test_market_overview_guards_empty_vix_frames():
    src = (ROOT / "dashboard" / "views" / "market_breadth.py").read_text(encoding="utf-8")
    assert '"Close" not in vix_df or "Close" not in nifty_df' in src
    assert src.index("data providers unreachable") < src.index('curr_vix   = float(vix_df["Close"]')


# ── a stock that re-enters an index is no longer a "former constituent" ──────
def test_reentered_constituent_is_dropped_from_the_former_list():
    import data.universe as u
    assert u._drop_current_constituents(["PFIZER.NS", "GONE.NS"], ["PFIZER.NS", "TCS.NS"]) == ["GONE.NS"]
    assert not (set(u.FORMER_CONSTITUENTS) & set(u.get_universe("all")))
    assert u.resolve_ticker("PFIZER") == "PFIZER.NS"            # resolvable either way
