"""Scan drops are counted and logged (FIX SCAN-DROPS), and a mostly-failed
scan never overwrites the persisted snapshot (FIX SNAPSHOT-GUARD)."""
from __future__ import annotations

import logging
import os
import sys
from types import SimpleNamespace

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from dashboard.shared import cache as cache_mod  # noqa: E402
from utils.snapshot_time import scan_too_degraded  # noqa: E402


def _score(action="BUY", score=60, headline="h"):
    return SimpleNamespace(
        ticker="X.NS", price=100.0, score=score, grade="B", action=action, headline=headline,
        narrative="", sector="IT", entry=100.0, stop_loss=95.0, target=110.0, risk_reward=2.0,
        technical_score=30, momentum_score=10, volume_score=6, sentiment_score=5,
        horizon="", valid_until="", signals=[], key_levels={})


def _fake_score_stock(tk, **_kw):
    if tk.startswith("OK"):
        return _score()
    if tk.startswith("NODATA"):
        return _score("DATA_UNAVAILABLE", 0,
                      f"Data unavailable: No data for {tk}. All sources failed: [('Yahoo', 'URLError')]")
    if tk.startswith("SHORT"):
        return _score("DATA_UNAVAILABLE", 0, f"Data unavailable: Insufficient data for {tk}")
    raise KeyError(tk)


@pytest.fixture
def scan_env(monkeypatch):
    import analysis.score as score_mod
    import data.universe as uni_mod
    univ = ([f"OK{i}.NS" for i in range(4)] + [f"NODATA{i}.NS" for i in range(12)]
            + ["SHORT0.NS", "BOOM0.NS"])
    monkeypatch.setattr(uni_mod, "get_universe", lambda name: list(univ))
    monkeypatch.setattr(score_mod, "score_stock", _fake_score_stock)
    monkeypatch.setattr(cache_mod, "_list_exclusion", lambda tk, period="2y": None)
    monkeypatch.setattr(cache_mod, "_sector_ranks_tuple", lambda: ())
    cache_mod._tomorrow_watchlist.clear()
    cache_mod._home_top_picks.clear()
    yield univ
    cache_mod._tomorrow_watchlist.clear()
    cache_mod._home_top_picks.clear()


_REASONS = {"all providers failed": 12, "too little history": 1, "error: KeyError": 1}


def test_tomorrow_watchlist_counts_and_logs_dropped_stocks(scan_env, caplog):
    with caplog.at_level(logging.INFO, logger="dashboard.cache"):
        out = cache_mod._tomorrow_watchlist(n=15)
    h = out["scan_health"]
    assert h["n_universe"] == 18 and h["n_unavailable"] == 14
    assert h["unavailable_reasons"] == _REASONS
    assert len(h["unavailable_sample"]) == 10
    assert out["n_universe"] == 18 and out["n_scored"] == 4      # not 17 "scored"
    lines = [r for r in caplog.records if "dropped with no score" in r.getMessage()]
    assert len(lines) == 1 and lines[0].levelno == logging.WARNING
    assert "14 of 18" in lines[0].getMessage()


def test_top_picks_meta_carries_sample_and_reasons(scan_env, caplog):
    with caplog.at_level(logging.INFO, logger="dashboard.cache"):
        out = cache_mod._home_top_picks(vix_regime="normal", n=20, sector_ranks=())
    meta = out["meta"]
    assert meta["n_scanned"] == 18 and meta["n_unavailable"] == 14 and meta["n_scored_ok"] == 4
    assert meta["unavailable_reasons"] == _REASONS
    assert len(meta["unavailable_sample"]) == 10
    assert sum("dropped with no score" in r.getMessage() for r in caplog.records) == 1


def test_healthy_scan_logs_at_info(monkeypatch, scan_env, caplog):
    import data.universe as uni_mod
    monkeypatch.setattr(uni_mod, "get_universe", lambda name: [f"OK{i}.NS" for i in range(5)])
    with caplog.at_level(logging.INFO, logger="dashboard.cache"):
        out = cache_mod._tomorrow_watchlist(n=15)
    assert out["scan_health"]["n_unavailable"] == 0
    line = next(r for r in caplog.records if "dropped with no score" in r.getMessage())
    assert line.levelno == logging.INFO


@pytest.mark.parametrize("n_univ,n_ok,expected", [
    (825, 800, False), (825, 413, False), (825, 412, True), (825, 0, True),
    (0, 0, True), (None, None, True), ("x", 3, True),
])
def test_scan_too_degraded(n_univ, n_ok, expected):
    assert scan_too_degraded(n_univ, n_ok) is expected


# ── warmers: a failed scan keeps the previous snapshot ───────────────────────
@pytest.fixture
def kv_writes(monkeypatch):
    import trade_store
    writes = []
    monkeypatch.setattr(trade_store, "kv_set",
                        lambda key, value, user_id=None: writes.append(key) or True)
    return writes


def _tw_result(n_scored):
    return {"breakout_candidates": [], "breakdown_watch": [], "reversal_watch": [],
            "scan_time": "13 Nov 15:50", "n_universe": 825, "n_scored": n_scored,
            "scan_health": {"unavailable_sample": ["PFC.NS"], "unavailable_reasons": {"x": 1}}}


@pytest.mark.parametrize("n_scored,persisted", [(820, True), (3, False)])
def test_warm_tomorrow_watchlist_persists_only_a_healthy_scan(monkeypatch, kv_writes,
                                                              n_scored, persisted):
    import scripts.warm_tomorrow_watchlist as w
    monkeypatch.setattr(cache_mod, "_tomorrow_watchlist", lambda n=15: _tw_result(n_scored))
    monkeypatch.setattr(w, "_persist_breadth", lambda: None)
    assert w.main() == 0
    assert (w._KV_KEY in kv_writes) is persisted


def test_warm_tomorrow_watchlist_universe_failure_is_not_persisted(monkeypatch, kv_writes):
    import scripts.warm_tomorrow_watchlist as w
    monkeypatch.setattr(cache_mod, "_tomorrow_watchlist", lambda n=15: {
        "breakout_candidates": [], "breakdown_watch": [], "reversal_watch": [], "scan_time": "x"})
    monkeypatch.setattr(w, "_persist_breadth", lambda: None)
    assert w.main() == 0
    assert kv_writes == []


@pytest.mark.parametrize("n_ok,persisted", [(800, True), (40, False)])
def test_warm_top_picks_persists_only_a_healthy_scan(monkeypatch, kv_writes, n_ok, persisted):
    import dashboard.shared.market_hours as mh
    import scripts.warm_top_picks as w
    result = {"buys": [], "sells": [], "all_scored": {"A.NS": {}}, "momentum_leaders": None,
              "meta": {"n_scanned": 825, "n_scored_ok": n_ok, "n_unavailable": 825 - n_ok,
                       "unavailable_sample": ["PFC.NS"], "unavailable_reasons": {"x": 1}}}
    monkeypatch.setattr(mh, "is_trading_day", lambda *a, **k: True)
    monkeypatch.setattr(cache_mod, "_home_top_picks", lambda **k: dict(result))
    monkeypatch.setattr(cache_mod, "get_vix_info", lambda: {"regime": "normal"})
    monkeypatch.setattr(cache_mod, "_sector_ranks_tuple", lambda: ())
    monkeypatch.setattr(w, "log_shadow_picks", lambda buys: 0)
    assert w.main() == 0
    assert (cache_mod._TOP_PICKS_KV_KEY in kv_writes) is persisted
    assert (cache_mod._ALL_SCORES_KV_KEY in kv_writes) is persisted
