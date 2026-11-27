"""Tomorrow's Watchlist backfill (27 Nov 2026).

The after-close scan did not run on 25-26 Nov 2026 (DB round trips after the move to
the Oracle VM, fixed in #413). scripts/warm_tomorrow_watchlist.py --as-of rebuilds a
past session from data up to its close and logs it as backfilled ledger rows, which
WATCHLIST_RULE leaves out. These tests pin: no data after the date leaks in, re-runs
add nothing, live rows are never overwritten, the rule ignores rebuilt rows, the
workflow input is wired and skips every send.
"""
from __future__ import annotations

import concurrent.futures as cf
import datetime as dt
import pathlib
import time
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
import yaml

from analysis import verdict_ledger as vl
from analysis.final_verdict import combine
from data import fetcher
from data import nse_delivery as nd
from utils.point_in_time import as_of, cut, point_in_time

D = dt.date(2026, 11, 25)                # Wednesday, a trading day
TODAY = dt.date(2026, 11, 27)
_PAGES = str(pathlib.Path(__file__).resolve().parents[1] / "dashboard" / "pages")


def _frame(end=TODAY, n=520, seed=1, crash_after=D):
    """Daily OHLCV ending `end`; bars after `crash_after` crash 50% on 10x volume so
    any leak changes the score."""
    idx = pd.bdate_range(end=pd.Timestamp(end), periods=n)
    rng = np.random.default_rng(seed)
    close = 100 * np.cumprod(1 + rng.normal(0.001, 0.015, n))
    vol = rng.integers(100_000, 200_000, n).astype(float)
    after = idx > pd.Timestamp(crash_after)
    close[after] *= 0.5
    vol[after] *= 10
    return pd.DataFrame({"Open": close, "High": close * 1.01, "Low": close * 0.99,
                         "Close": close, "Volume": vol}, index=idx)


@pytest.fixture
def clean_caches(monkeypatch):
    import analysis.score as sc
    fetcher.clear_fetch_cache()
    nd.clear_prefetch()
    for c in (sc._BENCH_CACHE, sc._FLOWS_CACHE, sc._REGIME_LABEL_AS_OF, sc._VIX_AS_OF):
        c.clear()
    sc._REGIME_LABEL_CACHE.update(t=0.0, label=None, ok=False)
    yield sc
    fetcher.clear_fetch_cache()
    nd.clear_prefetch()
    for c in (sc._BENCH_CACHE, sc._FLOWS_CACHE, sc._REGIME_LABEL_AS_OF, sc._VIX_AS_OF):
        c.clear()
    sc._REGIME_LABEL_CACHE.update(t=0.0, label=None, ok=False)


def _seed(frames):
    now = time.time()
    for key, df in frames.items():
        fetcher._cache_put(key, df, now)


# ── point-in-time cut ────────────────────────────────────────────────────────

def test_cut_and_context_restore():
    df = _frame()
    assert as_of() is None and cut(df) is df
    with point_in_time(D):
        assert as_of() == D
        assert cut(df).index.max() == pd.Timestamp(D)
    assert as_of() is None
    tz = df.tz_localize("Asia/Kolkata")
    assert cut(tz, D).index.max().date() == D


def test_fetcher_cuts_cached_frames_even_in_worker_threads(clean_caches):
    _seed({("RELIANCE.NS", "2y", "1d"): _frame()})
    with point_in_time(D):
        with cf.ThreadPoolExecutor(4) as ex:
            seen = list(ex.map(lambda _: fetcher.fetch_single("RELIANCE.NS", period="2y").index.max(),
                               range(8)))
        assert set(seen) == {pd.Timestamp(D)}
        assert fetcher.peek_cached("RELIANCE.NS").index.max() == pd.Timestamp(D)
    assert fetcher.fetch_single("RELIANCE.NS", period="2y").index.max() == pd.Timestamp(TODAY)


def test_delivery_reads_stop_at_the_date(tmp_path, monkeypatch):
    import trade_store
    monkeypatch.setattr(trade_store, "_SQLITE_PATH", str(tmp_path / "d.db"))
    monkeypatch.setattr(nd, "_schema_ready_for", None)
    nd.clear_prefetch()
    days = [D - dt.timedelta(days=i) for i in range(30, -3, -1)]      # to D + 2
    nd._persist([{"symbol": "AAA", "date": d.isoformat(), "close": 1.0, "traded_qty": 1.0,
                  "deliv_qty": 1.0, "deliv_pct": 90.0 if d > D else 30.0} for d in days])
    assert nd.get_snapshot("AAA")["today"] == 90.0
    with point_in_time(D):
        assert nd.get_snapshot("AAA")["today"] == 30.0
        assert nd.load_symbol_history("AAA")["date"].max() == D.isoformat()
        nd.prefetch_snapshots(["AAA"], lookback=10)
        assert nd.get_snapshot("AAA", lookback=10)["today"] == 30.0
    # the point-in-time prefetch never serves a live read
    assert nd.get_snapshot("AAA", lookback=10)["today"] == 90.0
    nd.clear_prefetch()


def test_score_stock_as_of_equals_score_on_data_cut_by_hand(clean_caches, monkeypatch):
    """The real scorer: full frames under point_in_time(D) == frames truncated at D."""
    sc = clean_caches
    monkeypatch.delenv("ANGEL_API_KEY", raising=False)
    stock, nifty, vix = _frame(seed=1), _frame(seed=2), _frame(seed=3) * 0 + 14.0
    vix.loc[vix.index > pd.Timestamp(D), "Close"] = 40.0                   # panic after D
    full = {("RELIANCE.NS", "2y", "1d"): stock, ("^NSEI", "2y", "1d"): nifty,
            ("^INDIAVIX", "1mo", "1d"): vix, ("^INDIAVIX", "3mo", "1d"): vix}
    _seed(full)
    with point_in_time(D):
        got = sc.score_stock("RELIANCE.NS")
    assert got.vix_regime == "normal"                 # VIX 14 on D, not the 40 after it

    fetcher.clear_fetch_cache()
    for c in (sc._BENCH_CACHE, sc._FLOWS_CACHE):
        c.clear()
    sc._REGIME_LABEL_CACHE.update(t=0.0, label=None, ok=False)
    _seed({k: v[v.index <= pd.Timestamp(D)] for k, v in full.items()})
    want = sc.score_stock("RELIANCE.NS", vix_info=sc.vix_info_as_of(D))
    for f in ("score", "action", "entry", "stop_loss", "target", "technical_score",
              "momentum_score", "volume_score", "sentiment_score"):
        assert getattr(got, f) == getattr(want, f), f
    assert got.entry == pytest.approx(float(stock.loc[pd.Timestamp(D), "Close"]), abs=0.01)
    assert got.valid_until > D.isoformat()


# ── build + ledger ───────────────────────────────────────────────────────────

@pytest.fixture
def scan(clean_caches, monkeypatch):
    """Universe of two names; score_stock is faked but reads its frame through the
    fetcher, so the test sees exactly what a real scorer would."""
    import analysis.score as sc
    from dashboard.shared import cache as cache_mod
    frames = {("AAA.NS", "2y", "1d"): _frame(seed=4), ("BBB.NS", "2y", "1d"): _frame(seed=5),
              ("^INDIAVIX", "3mo", "1d"): _frame(seed=6) * 0 + 13.0}
    _seed(frames)
    seen = []

    def fake_score(tk, sector_scores_df=None, vix_info=None, **_k):
        df = fetcher.fetch_single(tk, period="2y")
        seen.append((tk, df.index.max(), vix_info))
        px = float(df["Close"].iloc[-1])
        return SimpleNamespace(price=px, score=60, grade="B", action="BUY", headline="h", entry=px,
                               stop_loss=px * 0.95, target=px * 1.1, risk_reward=2.0,
                               technical_score=30, momentum_score=10, volume_score=6,
                               horizon="", valid_until="")
    monkeypatch.setattr("data.universe.get_universe", lambda name: ["AAA.NS", "BBB.NS"])
    monkeypatch.setattr(sc, "score_stock", fake_score)
    monkeypatch.setattr(sc, "_live_regime_label", lambda: None)
    monkeypatch.setattr(cache_mod, "_sector_ranks_as_of", lambda: ())
    monkeypatch.setattr(cache_mod, "_list_exclusion_as_of", lambda tk, d, period="2y": None)
    monkeypatch.setattr(cache_mod, "_sector_ranks_tuple",
                        lambda: pytest.fail("a rebuild must not use the cached live sector ranks"))
    monkeypatch.setattr(vl, "_breadth_shadow", lambda: ("broad", 70.0))
    monkeypatch.setattr(vl, "last_closed_session", lambda now=None: TODAY)
    return cache_mod, frames, seen


def _tw_rows():
    df = vl.load_ledger(source="tomorrow_watchlist", limit=100)
    return df.sort_values("ticker").reset_index(drop=True)


def test_rebuild_sees_only_data_up_to_the_date_and_logs_backfilled_rows(scan):
    cache_mod, frames, seen = scan
    out = cache_mod.build_tomorrow_watchlist_as_of(D)
    assert seen and all(mx == pd.Timestamp(D) for _, mx, _ in seen)
    assert all(v["vix"] == 13.0 and v["regime"] == "normal" for _, _, v in seen)
    assert as_of() is None                                   # restored afterwards
    pit = out["point_in_time"]
    assert pit["as_of"] == D.isoformat() and pit["ledger_rows_added"] == 2
    assert "momentum_leaders" not in out and pit["not_point_in_time"]

    rows = _tw_rows()
    assert list(rows["ticker"]) == ["AAA.NS", "BBB.NS"]
    assert set(rows["logged_date"]) == {D.isoformat()}
    assert set(rows["backfilled"]) == {1}
    assert rows["logged_at"].str.startswith(D.isoformat()).all()
    assert rows["backfill_note"].str.contains(f"from data up to {D.isoformat()}'s close").all()
    assert rows["breadth_label"].isna().all()                # latest-only shadow left out
    for _, r in rows.iterrows():                             # entry = D's close
        close_d = float(frames[(r["ticker"], "2y", "1d")].loc[pd.Timestamp(D), "Close"])
        assert r["entry_price"] == pytest.approx(close_d)
    assert set(vl.tw_buckets(rows["id"].tolist()).values()) == {"breakout"}


def test_rebuild_is_idempotent(scan):
    cache_mod, _, _ = scan
    cache_mod.build_tomorrow_watchlist_as_of(D)
    again = cache_mod.build_tomorrow_watchlist_as_of(D)
    assert again["point_in_time"]["ledger_rows_added"] == 0
    assert len(_tw_rows()) == 2


def test_live_rows_are_never_overwritten(scan, monkeypatch):
    cache_mod, _, _ = scan
    monkeypatch.setattr(vl, "_now_ist", lambda: dt.datetime(2026, 11, 25, 16, 0, tzinfo=vl._IST))
    live_id = vl.log_verdict(ticker="AAA.NS", final_verdict=combine(composite_score=70.0,
                             composite_action="BUY"), entry_price=123.0, composite_score=70.0,
                             source="tomorrow_watchlist")
    assert live_id
    # a day with live rows is not rebuilt at all, so no rebuilt name mixes into it
    with pytest.raises(ValueError, match="live"):
        cache_mod.build_tomorrow_watchlist_as_of(D)
    # and a backfilled insert for the same key is a no-op
    assert vl.log_verdict(ticker="AAA.NS", final_verdict=combine(composite_score=60.0,
                          composite_action="BUY"), entry_price=1.0, source="tomorrow_watchlist",
                          as_of=D, backfill_note="x") is None
    rows = _tw_rows()
    assert len(rows) == 1 and rows["entry_price"].iloc[0] == 123.0 and rows["backfilled"].iloc[0] == 0


def test_rebuild_refuses_holidays_weekends_and_open_sessions(scan):
    cache_mod, _, _ = scan
    for bad in (dt.date(2026, 11, 24), dt.date(2026, 11, 28), dt.date(2026, 11, 30)):
        with pytest.raises(ValueError):
            cache_mod.build_tomorrow_watchlist_as_of(bad)
    assert vl.load_ledger(limit=10).empty


def test_degraded_rebuild_logs_nothing(scan, monkeypatch):
    import analysis.score as sc
    cache_mod, _, _ = scan
    monkeypatch.setattr("data.universe.get_universe", lambda name: ["AAA.NS", "BBB.NS"] + [
        f"X{i}.NS" for i in range(10)])                     # 10 of 12 names fail to fetch
    real = sc.score_stock

    def flaky(tk, **k):
        if tk.startswith("X"):
            raise ValueError("no data")
        return real(tk, **k)
    monkeypatch.setattr(sc, "score_stock", flaky)
    out = cache_mod.build_tomorrow_watchlist_as_of(D)
    assert "too degraded" in out["point_in_time"]["ledger_skipped"]
    assert vl.load_ledger(limit=10).empty


def test_no_telegram_or_snapshot_overwrite(scan, monkeypatch):
    import scripts.warm_tomorrow_watchlist as w
    import trade_store
    sent, kv = [], {}
    monkeypatch.setattr("utils.telegram.send_message", lambda *a, **k: sent.append(a), raising=False)
    monkeypatch.setattr(trade_store, "kv_set", lambda key, val, user_id=None, **k: kv.setdefault(key, val))
    added = w.backfill([dt.date(2026, 11, 24), D, dt.date(2026, 11, 28)])   # holiday, D, Saturday
    assert added == 2 and sent == []
    assert list(kv) == [f"tomorrow_watchlist_snapshot:backfill:{D.isoformat()}"]


# ── the pre-registered rule and Results by list ──────────────────────────────

def _rule_rows(n_days=40, backfilled_days=()):
    rows = []
    days = pd.bdate_range("2026-11-04", periods=n_days)
    for i, d in enumerate(days):
        for j in range(3):
            rows.append({"id": i * 10 + j, "source": "tomorrow_watchlist", "bucket": "breakout",
                         "logged_date": d.date().isoformat(), "logged_at": f"{d.date()}T15:50:00",
                         "ticker": f"T{j}.NS", "verdict": "BUY", "ret_5d": 3.0, "nifty_ret_5d": 0.0,
                         "backfilled": 1 if d.date().isoformat() in backfilled_days else 0})
    return pd.DataFrame(rows)


def test_watchlist_rule_excludes_backfilled_rows():
    base = vl.evaluate_watchlist_rule(_rule_rows())
    assert base["picks"] == 120 and base["excluded_backfilled"] == 0
    bf = ("2026-11-05", "2026-11-06")
    res = vl.evaluate_watchlist_rule(_rule_rows(backfilled_days=bf))
    assert res["picks"] == 114 and res["days"] == 38 and res["excluded_backfilled"] == 6
    # a frame from before the column existed reads as live
    assert vl.evaluate_watchlist_rule(_rule_rows().drop(columns="backfilled"))["picks"] == 120


def test_watchlist_rule_definition_unchanged():
    assert vl.WATCHLIST_RULE["registered_on"] == "2026-11-09"
    assert vl.WATCHLIST_RULE["logged_from"] == "2026-11-04"


def test_results_by_list_counts_rebuilt_days_and_flags_them():
    rows = _rule_rows(backfilled_days=("2026-11-05",))
    res = vl.results_by_list(rows, horizons=(5,))
    assert int(res["picks_5"].iloc[0]) == 120                # included here
    assert res.attrs["rebuilt_days"] == ["2026-11-05"]
    assert vl.results_by_list(_rule_rows(), horizons=(5,)).attrs["rebuilt_days"] == []


# ── workflow + script wiring ─────────────────────────────────────────────────

def test_workflow_as_of_dates_input_runs_backfill_only_and_skips_sends():
    wf = yaml.safe_load(pathlib.Path(".github/workflows/warm_tomorrow_watchlist.yml").read_text("utf-8"))
    on = wf.get("on", wf.get(True))
    inp = on["workflow_dispatch"]["inputs"]["as_of_dates"]
    assert inp["default"] == "" and inp["required"] is False
    steps = {s["name"]: s for s in wf["jobs"]["warm"]["steps"]}
    bf = steps["Backfill Tomorrow's Watchlist"]
    assert "inputs.as_of_dates != ''" in bf["if"]
    assert bf["env"]["AS_OF_DATES"] == "${{ inputs.as_of_dates }}"
    assert "TELEGRAM_BOT_TOKEN" not in bf["env"]
    live = "inputs.as_of_dates == ''"
    assert live in steps["Run Tomorrow's Watchlist warm-up"]["if"]
    for name, s in steps.items():
        if name.startswith("Send ") or name == "Restore alert state":
            assert live in s.get("if", ""), name


def test_script_parses_dates_and_routes_to_backfill(monkeypatch):
    import scripts.warm_tomorrow_watchlist as w
    assert w.parse_as_of_dates(" 2026-11-26,2026-11-25, 2026-11-25 ") == [D, dt.date(2026, 11, 26)]
    assert w.parse_as_of_dates("") == []
    got = []
    monkeypatch.setattr(w, "backfill", lambda dates: got.append(dates) or 0)
    monkeypatch.setattr("sys.argv", ["warm_tomorrow_watchlist.py"])
    monkeypatch.setenv("AS_OF_DATES", "2026-11-25,2026-11-26")
    assert w.main() == 0 and got == [[D, dt.date(2026, 11, 26)]]
    monkeypatch.setenv("AS_OF_DATES", "25-11-2026")
    assert w.main() == 0 and len(got) == 1                  # malformed: logged, nothing run


# ── pages ────────────────────────────────────────────────────────────────────

def _seed_rebuilt_day():
    """One live day (23 Nov) and one rebuilt day (25 Nov) of watchlist picks."""
    vl.ensure_schema()
    for day, bf in (("2026-11-23", None), ("2026-11-25", "rebuilt after the fact")):
        d = dt.date.fromisoformat(day)
        for tk in ("AAA.NS", "BBB.NS"):
            fv = combine(composite_score=60.0, composite_action="BUY")
            if bf:
                vl.log_verdict(ticker=tk, final_verdict=fv, entry_price=100.0, composite_score=60.0,
                               signal_tags=["tw:breakout"], source="tomorrow_watchlist",
                               as_of=d, backfill_note=bf)
            else:
                import unittest.mock as um
                with um.patch.object(vl, "_now_ist",
                                     lambda: dt.datetime.combine(d, dt.time(16, 0), tzinfo=vl._IST)):
                    vl.log_verdict(ticker=tk, final_verdict=fv, entry_price=100.0, composite_score=60.0,
                                   signal_tags=["tw:breakout"], source="tomorrow_watchlist")


@pytest.fixture
def offline(monkeypatch):
    import socket

    def _blocked(*a, **k):
        raise OSError("network blocked")
    monkeypatch.setattr(socket.socket, "connect", _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)
    monkeypatch.setattr(vl, "_fetch_history", lambda t: None)


def test_calibration_page_flags_rebuilt_days(offline):
    from streamlit.testing.v1 import AppTest
    _seed_rebuilt_day()
    rows = vl.load_ledger(source="tomorrow_watchlist", limit=10)
    assert sorted(set(rows.loc[rows["backfilled"] == 1, "logged_date"])) == ["2026-11-25"]
    at = AppTest.from_file(_PAGES + "/10_verdict_calibration.py", default_timeout=180).run()
    assert not at.exception, at.exception
    text = " ".join(str(m.value) for m in (*at.markdown, *at.caption))
    assert "Includes 1 rebuilt day(s) (2026-11-25)" in text
    assert "2 rebuilt pick(s) left out" in text


def test_tomorrow_watchlist_page_badges_rebuilt_days(offline, monkeypatch):
    from streamlit.testing.v1 import AppTest
    import trade_store
    _seed_rebuilt_day()
    monkeypatch.setattr(vl, "session_date", lambda now=None: TODAY)
    # a current snapshot, so the page renders without starting a live scan
    trade_store.kv_set("tomorrow_watchlist_snapshot", {
        "generated_at": trade_store.snapshot_timestamp(),
        "data": {"breakout_candidates": [], "breakdown_watch": [], "reversal_watch": [],
                 "scan_time": "27 Nov 15:50", "n_universe": 826, "n_scored": 820}}, user_id="_system")
    at = AppTest.from_file(_PAGES + "/04_tomorrow_watchlist.py", default_timeout=240).run()
    assert not at.exception, at.exception
    text = " ".join(str(m.value) for m in (*at.markdown, *at.caption))
    assert "rebuilt later" in text
