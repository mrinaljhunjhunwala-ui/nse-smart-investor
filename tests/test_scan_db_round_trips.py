"""27 Nov 2026: universe scans must not run one database query per stock, and
ANGEL_DISABLED turns Angel One off for a process.

From 25 Nov the ~826-name scans ran 980 s+ (65 s on 23 Nov) because score_stock read
each stock's delivery history with its own query from a US runner to the Mumbai VM.
"""
import datetime as dt
from contextlib import contextmanager

import pytest

import trade_store
from data import nse_delivery as nd


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(trade_store, "_SQLITE_PATH", str(tmp_path / "t.db"))
    monkeypatch.setattr(nd, "_schema_ready_for", None)
    nd.clear_prefetch()
    yield
    nd.clear_prefetch()


def _rows(sym, n, start=dt.date(2026, 6, 1), step=1, pct0=30.0):
    return [{"symbol": sym, "date": (start + dt.timedelta(days=i * step)).isoformat(),
             "close": 100.0, "traded_qty": 1000.0, "deliv_qty": 400.0,
             "deliv_pct": pct0 + (i % 7)} for i in range(n)]


def _count_conns(monkeypatch):
    calls = []
    real = trade_store._get_conn

    @contextmanager
    def counting():
        calls.append(1)
        with real() as c:
            yield c
    monkeypatch.setattr(trade_store, "_get_conn", counting)
    return calls


def test_prefetch_matches_per_symbol_reads_exactly(store, monkeypatch):
    rows = (_rows("AAA", 150) + _rows("BBB", 150, pct0=50.0) + _rows("CCC", 3)
            # DDD traded on only a few of the recent dates: not answerable from the window
            + _rows("DDD", 70, start=dt.date(2026, 1, 1)) + _rows("DDD", 5, start=dt.date(2026, 10, 1)))
    nd._persist(rows)
    syms = ["AAA.NS", "BBB.NS", "CCC.NS", "DDD.NS", "ZZZ.NS"]
    want = {s: nd.get_snapshot(s) for s in syms}
    assert want["AAA.NS"] and want["DDD.NS"] and want["CCC.NS"] is None

    assert nd.prefetch_snapshots(syms) == 2              # AAA, BBB answerable; the rest per symbol
    calls = _count_conns(monkeypatch)
    assert {s: nd.get_snapshot(s) for s in syms} == want
    assert len(calls) == 3                               # CCC, DDD, ZZZ only


def test_prefetch_on_a_short_table_caches_everything(store, monkeypatch):
    nd._persist(_rows("AAA", 20) + _rows("BBB", 2))
    want = {s: nd.get_snapshot(s) for s in ("AAA", "BBB", "NONE")}
    assert nd.prefetch_snapshots(["AAA", "BBB", "NONE"]) == 3
    calls = _count_conns(monkeypatch)
    assert {s: nd.get_snapshot(s) for s in ("AAA", "BBB", "NONE")} == want
    assert calls == []


def test_prefetch_handles_a_universe_over_the_parameter_limit(store):
    nd._persist(_rows("AAA", 20) + _rows("S1199", 20, pct0=60.0))
    syms = ["AAA"] + [f"S{i}" for i in range(1200)]
    assert nd.prefetch_snapshots(syms) == len(set(syms))
    assert nd.get_snapshot("S1199")["today"] == 60.0 + 19 % 7
    assert nd.get_snapshot("S5") is None


def test_prefetch_expires_and_failure_falls_back(store, monkeypatch):
    nd._persist(_rows("AAA", 20))
    nd.prefetch_snapshots(["AAA"])
    monkeypatch.setattr(nd, "_PREFETCH_TTL_S", -1)       # expired: read the database again
    calls = _count_conns(monkeypatch)
    assert nd.get_snapshot("AAA")["n"] == 20 and calls
    nd.clear_prefetch()

    def boom(*a, **k):
        raise RuntimeError("db down")
    monkeypatch.setattr(nd, "read_sql_df", boom)
    assert nd.prefetch_snapshots(["AAA"]) == 0           # never raises


def test_both_universe_scans_prefetch_once(monkeypatch):
    import dashboard.shared.cache as cache
    seen, order = [], []
    monkeypatch.setattr(nd, "prefetch_snapshots", lambda syms, lookback=60: seen.append(list(syms)) or 0)
    monkeypatch.setattr("data.universe.get_universe", lambda name: ["AAA.NS", "BBB.NS"])
    monkeypatch.setattr(cache, "_sector_ranks_tuple", lambda *a, **k: ())

    def no_score(tk, **k):
        order.append(("score", tk, len(seen)))
        raise ValueError("offline")
    monkeypatch.setattr("analysis.score.score_stock", no_score)
    cache._tomorrow_watchlist.__wrapped__(n=5)
    cache._home_top_picks.__wrapped__("normal", 5, ())
    assert seen == [["AAA.NS", "BBB.NS"], ["AAA.NS", "BBB.NS"]]
    assert order and all(n >= 1 for _, _, n in order)    # prefetched before any stock is scored


def test_list_exclusion_keeps_its_cache_and_prefetch_has_none():
    """#292's trap: a helper inserted under a decorator steals it. _prefetch_delivery must run
    on every scan (it was cached by mistake once while writing this fix); _list_exclusion
    stays cached."""
    import dashboard.shared.cache as cache
    assert hasattr(cache._list_exclusion, "clear")
    assert not hasattr(cache._prefetch_delivery, "clear")


# ── ANGEL_DISABLED ───────────────────────────────────────────────────────────

def test_angel_disabled_switch(monkeypatch):
    from data import angel_fetcher as af
    for k, v in (("ANGEL_API_KEY", "k"), ("ANGEL_CLIENT_ID", "c"), ("ANGEL_PASSWORD", "p"),
                 ("ANGEL_TOTP_SECRET", "t")):
        monkeypatch.setenv(k, v)
    monkeypatch.setattr(af, "_secrets_section", lambda: {})
    monkeypatch.delenv("ANGEL_DISABLED", raising=False)
    assert af.is_configured()
    for on in ("1", "true", "YES", "on"):
        monkeypatch.setenv("ANGEL_DISABLED", on)
        assert af.disabled() and not af.is_configured()
    monkeypatch.setattr(af, "_SESSION", {"jwt": "cached", "feed_token": None, "api_key": "", "ts": 9e18})

    def no_http(*a, **k):
        raise AssertionError("no Angel call when disabled")
    monkeypatch.setattr(af._http, "post", no_http)
    monkeypatch.setattr(af._http, "get", no_http)
    assert af._get_session() is None                     # even with a cached session
    assert af.fetch_historical("RELIANCE.NS") is None
    monkeypatch.setenv("ANGEL_DISABLED", "0")
    assert not af.disabled()


def test_fetcher_skips_angel_when_disabled(monkeypatch):
    import pandas as pd
    from data import angel_fetcher as af
    from data import fetcher
    monkeypatch.setenv("ANGEL_DISABLED", "1")

    def no_angel(*a, **k):
        raise AssertionError("Angel tier must not run")
    monkeypatch.setattr(af, "fetch_historical", no_angel)
    idx = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=300)
    frame = pd.DataFrame({"Open": 1.0, "High": 1.0, "Low": 1.0, "Close": 1.0, "Volume": 1}, index=idx)
    monkeypatch.setattr(fetcher, "_fetch_yahoo_direct", lambda *a, **k: frame.copy())
    monkeypatch.setattr(fetcher, "_stooq_enabled", lambda: False)
    monkeypatch.setenv("NSE_PRICE_STORE", "0")
    fetcher._cache_clear() if hasattr(fetcher, "_cache_clear") else None
    out = fetcher.fetch_single("ZZANGELOFF.NS", period="1y")
    assert not out.empty


def test_scan_workflows_run_without_angel():
    import pathlib
    for wf, step in ((".github/workflows/warm_tomorrow_watchlist.yml", "- name: Run Tomorrow's Watchlist warm-up"),
                     (".github/workflows/warm-top-picks.yml", "- name: Run Top Picks warm-up"),
                     (".github/workflows/warm-preopen-scan.yml", "- name: Warm Top Picks (pre-open refresh)"),
                     (".github/workflows/warm-preopen-scan.yml", "- name: Warm Tomorrow's Watchlist")):
        text = pathlib.Path(wf).read_text(encoding="utf-8")
        body = text[text.index(step):]
        body = body[:body.index("run: python")]
        assert 'ANGEL_DISABLED: "1"' in body and "ANGEL_API_KEY" not in body, (wf, step)
    pre = pathlib.Path(".github/workflows/warm-preopen-scan.yml").read_text(encoding="utf-8")
    top = pre[pre.index("- name: Warm Top Picks (pre-open refresh)"):pre.index("run: python scripts/warm_top_picks.py")]
    assert "continue-on-error: true" in top and "timeout-minutes:" in top   # the sends still run
