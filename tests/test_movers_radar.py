"""Movers radar + holding guard: pure selection / evidence maths, NSE feed parsing, alert wiring."""
from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd
import pytest

from analysis import movers as M

BANDS = {"RELIANCE": "Large", "PERSISTENT": "Mid", "KAYNES": "Small"}
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))


# ── tiers and watchlist ranks ───────────────────────────────────────────────

def test_band_map_and_unknown_symbols_are_micro():
    rows = [{"Symbol": "RELIANCE", "Index": "NIFTY50"}, {"Symbol": "IRFC", "Index": "NEXT50"},
            {"Symbol": "PERSISTENT", "Index": "MIDCAP150"}, {"Symbol": "KAYNES", "Index": "SMALLCAP250"}]
    b = M.band_map(rows)
    assert b == {"RELIANCE": "Large", "IRFC": "Large", "PERSISTENT": "Mid", "KAYNES": "Small"}
    assert M.cap_band("STYLEBAAZA.NS", b) == "Micro"


def test_watchlist_ranks_any_rank_first_bucket_wins():
    data = {"breakout_candidates": [{"ticker": f"X{i}.NS"} for i in range(1, 15)] + [{"ticker": "DHANBANK.NS"}],
            "reversal_watch": [{"ticker": "DHANBANK.NS"}, {"ticker": "PFC.NS"}],
            "breakdown_watch": [{"ticker": "WEAK.NS"}]}
    r = M.watchlist_ranks(data)
    assert r["DHANBANK"] == ("Breakout", 15, 1)
    assert r["PFC"] == ("Reversal", 2, 1)
    assert r["WEAK"][2] == -1
    assert M.watchlist_ranks(None) == {}


# ── selection ───────────────────────────────────────────────────────────────

def _row(sym, pct, price=100.0, turnover_cr=50.0):
    return {"symbol": sym, "pct": pct, "price": price, "turnover_cr": turnover_cr}


def test_thresholds_differ_by_tier():
    rows = [_row("RELIANCE", 3.2), _row("PERSISTENT", 4.0), _row("KAYNES", 7.5), _row("TINY", 7.9)]
    out = M.select_movers(rows, bands=BANDS, ranks={})
    assert [m["symbol"] for m in out] == ["RELIANCE", "KAYNES"]   # mid needs 5%, micro 8%
    assert [m["band"] for m in out] == ["Large", "Small"]


def test_watchlist_names_qualify_early_are_listed_first_and_skip_the_cap():
    ranks = {"DHANBANK": ("Breakout", 14, 1), "WEAK": ("Breakdown risk", 3, -1)}
    rows = [_row(f"M{i}", 9 + i) for i in range(8)] + [_row("DHANBANK", 4.5), _row("WEAK", 9.0)]
    out = M.select_movers(rows, bands={}, ranks=ranks, per_band=5)
    syms = [m["symbol"] for m in out]
    assert syms[0] == "DHANBANK" and out[0]["watchlist"] == ("Breakout", 14, 1)
    assert len(syms) == 5                                   # 1 watchlist + 4 others in the band
    assert "WEAK" not in syms[:1] and out[1]["pct"] >= out[2]["pct"]


def test_filters_repeats_penny_and_illiquid():
    rows = [_row("A", 9, price=5), _row("B", 9, turnover_cr=0.2), _row("C", 9), _row("D", 9)]
    out = M.select_movers(rows, bands={}, ranks={}, already=["D.NS"])
    assert [m["symbol"] for m in out] == ["C"]


def test_restrict_to_lists_keeps_holdings_paper_watchlist_and_large_caps():
    rows = [_row("RELIANCE", 3.4), _row("TINYHELD", 9), _row("PAPERCO", 9), _row("DHANBANK", 6),
            _row("WEAK", 9), _row("STYLEBAAZA", 14)]
    ranks = {"DHANBANK": ("Breakout", 14, 1), "WEAK": ("Breakdown risk", 3, -1)}
    out = M.restrict_to_lists(rows, bands=BANDS, ranks=ranks, held=["TINYHELD.NS"], paper=["PAPERCO"])
    assert [r["symbol"] for r in out] == ["RELIANCE", "TINYHELD", "PAPERCO", "DHANBANK"]
    assert M.restrict_to_lists(rows[-1:], bands=BANDS, ranks={}) == []


# ── evidence table ──────────────────────────────────────────────────────────

def _frame(closes, vols=None):
    idx = pd.bdate_range("2024-01-01", periods=len(closes))
    return pd.DataFrame({"Close": closes, "Volume": vols if vols is not None else [1000.0] * len(closes)},
                        index=idx)


def test_move_events_measures_excess_vs_nifty():
    closes = [100.0] * 40
    closes[30] = 106.0                                      # +6% day
    for i in range(31, 40):
        closes[i] = 106.0
    closes[35] = 110.0                                      # 5 sessions after the move
    vols = [1000.0] * 40
    vols[30] = 4000.0
    stock = _frame(closes, vols)
    nifty = pd.Series(np.linspace(100, 101, 40), index=stock.index)
    ev = M.move_events(stock, nifty, horizon=5)
    assert len(ev) == 1
    row = ev.iloc[0]
    assert row["pct"] == pytest.approx(6.0)
    assert row["vol_ratio"] == pytest.approx(4.0)
    n0, n5 = nifty.iloc[30], nifty.iloc[35]
    assert row["excess"] == pytest.approx((110 / 106 - 1) * 100 - (n5 / n0 - 1) * 100)


def test_table_lookup_falls_back_to_any_volume_and_needs_enough_cases():
    table = {"Mid|1|2": {"n": 10, "median_excess": 3.0, "beat_pct": 70, "horizon": 5},
             "Mid|1|any": {"n": 120, "median_excess": -1.2, "beat_pct": 41, "horizon": 5}}
    hit = M.chase_lookup(table, "Mid", 6.0, vol_ratio=4.0)
    assert hit["key"] == "Mid|1|any"                        # the 3x+ volume bucket has too few cases
    assert "gave some back" in M.evidence_phrase(hit) and "n=120" in M.evidence_phrase(hit)
    assert M.chase_lookup(table, "Large", 6.0) is None
    assert M.evidence_phrase(None).startswith("past record: too few")


def test_build_chase_table_end_to_end():
    rng = np.random.default_rng(0)
    idx = pd.bdate_range("2022-01-03", periods=400)
    nifty = pd.Series(100 * np.cumprod(1 + rng.normal(0, 0.008, 400)), index=idx)
    hist = {}
    for s in ("AAA.NS", "BBB.NS"):
        rets = rng.normal(0, 0.03, 400)
        hist[s] = pd.DataFrame({"Close": 100 * np.cumprod(1 + rets),
                                "Volume": rng.uniform(1e5, 3e5, 400)}, index=idx)
    t = M.build_chase_table(hist, nifty, lambda s: "Small")
    assert t and all(k.startswith("Small|") for k in t)
    assert sum(v["n"] for k, v in t.items() if k.endswith("|any")) > 10


# ── holding guard ───────────────────────────────────────────────────────────

def test_guard_only_real_trouble():
    assert M.guard_reason(-2.5, "Large") is None                     # ordinary day
    assert "down -5.4%" in M.guard_reason(-5.4, "Large")
    assert M.guard_reason(-6.0, "Mid") is None                       # mid caps need -7%
    assert M.guard_reason(1.0, "Large", results_score=-35) == "weak quarterly results"
    assert "auditor resigned" in M.guard_reason(None, "Small", negative_filings=["auditor resigned"])


# ── NSE feed parsing ────────────────────────────────────────────────────────

def test_parse_gainers_prefers_allsec_and_converts_turnover():
    from data.nse_movers import parse_gainers, parse_volume_gainers, snapshot_gainers
    payload = {"NIFTY": {"data": [{"symbol": "RELIANCE", "series": "EQ", "ltp": 1500, "perChange": 3.1}]},
               "allSec": {"data": [
                   {"symbol": "STYLEBAAZA", "series": "EQ", "ltp": 412.5, "prev_price": 360.0,
                    "net_price": 14.58, "turnover": 4321.0},
                   {"symbol": "XBOND", "series": "N1", "ltp": 1000, "perChange": 9},
                   {"symbol": "DHANBANK", "series": "BE", "lastPrice": 42.84, "pChange": 6.46}]}}
    rows = parse_gainers(payload)
    assert [r["symbol"] for r in rows] == ["STYLEBAAZA", "DHANBANK"]
    assert rows[0]["turnover_cr"] == pytest.approx(43.21) and rows[0]["source"] == "NSE"
    assert parse_gainers("garbage") == []
    assert parse_volume_gainers({"data": [{"symbol": "STYLEBAAZA", "week1volChange": 3.4}]}) == {"STYLEBAAZA": 3.4}
    snap = {"data": {"PFC.NS": {"ticker": "PFC.NS", "return_1d": 5.5, "price": 410}}}
    assert snapshot_gainers(snap)[0]["symbol"] == "PFC" and snapshot_gainers(None) == []


def test_fetch_gainers_falls_back_to_scan_when_nse_is_down(monkeypatch):
    import data.nse_movers as NM
    monkeypatch.setattr(NM, "fetch_nse_gainers", lambda: [])
    rows = NM.fetch_gainers({"data": {"PFC.NS": {"return_1d": 5.5, "price": 410}}})
    assert rows[0]["source"] == "scan"


# ── alert wiring ────────────────────────────────────────────────────────────

@pytest.fixture
def wired(monkeypatch):
    import alerts.check_alerts as ca
    import alerts.movers_alerts as ma
    sent = []
    monkeypatch.setattr(ca, "_FORCE_SEND", False)
    monkeypatch.setattr(ca, "dispatch", lambda msg, *, subject="x": sent.append(msg) or True)
    kv = {}
    monkeypatch.setattr(ma, "_kv", lambda key, user="_system": kv.get(key))
    monkeypatch.setattr(ma, "_kv_set", lambda key, value: kv.__setitem__(key, value))
    monkeypatch.setattr(ma, "_fresh", lambda snap, h: snap)
    monkeypatch.setattr(ma, "_bands", lambda: {"RELIANCE": "Large"})
    monkeypatch.setattr(ma, "_events_by_symbol", lambda now, days=3: {})
    return ma, sent, kv


def test_radar_sends_new_movers_once_and_logs_them(wired, monkeypatch):
    ma, sent, kv = wired
    import data.nse_movers as NM
    monkeypatch.setattr(NM, "fetch_gainers", lambda snap=None: [
        {"symbol": "STYLEBAAZA", "pct": 14.6, "price": 412.5, "turnover_cr": 43, "source": "NSE", "vol_ratio": 3.4},
        {"symbol": "TINYHELD", "pct": 14.6, "price": 80.0, "turnover_cr": 5, "source": "NSE", "vol_ratio": 3.4},
        {"symbol": "PAPERCO", "pct": 8.5, "price": 120.0, "turnover_cr": 5, "source": "NSE"},
        {"symbol": "RELIANCE", "pct": 3.4, "price": 1500, "turnover_cr": 900, "source": "NSE"},
        {"symbol": "DHANBANK", "pct": 6.5, "price": 42.84, "turnover_cr": 20, "source": "NSE"}])
    monkeypatch.setattr(ma, "_holdings", lambda: ["TINYHELD"])
    monkeypatch.setattr(ma, "_paper_symbols", lambda: ["PAPERCO"])
    kv["tomorrow_watchlist_snapshot"] = {"data": {"breakout_candidates": [{"ticker": f"X{i}.NS"} for i in range(13)]
                                                  + [{"ticker": "DHANBANK.NS"}]}}
    kv["all_scored_snapshot"] = {"data": {"RELIANCE.NS": {"score": 74, "action": "BUY", "sl": 1440}}}
    kv["movers_evidence"] = {"table": {"Micro|3|any": {"n": 80, "median_excess": -2.1, "beat_pct": 38, "horizon": 5}}}
    state, now = {}, dt.datetime(2026, 11, 17, 11, 0, tzinfo=IST)
    assert ma.check_movers_radar(state, "2026-11-17", now=now) == 1
    msg = sent[0]
    assert "Movers radar" in msg and "all NSE stocks" in msg
    assert "Large cap" in msg and "Micro / other" in msg
    assert "DHANBANK" in msg and "Tomorrow's Watchlist #14 (Breakout)" in msg
    assert "STYLEBAAZA" not in msg                        # micro cap on none of your lists
    assert "TINYHELD" in msg and "you hold it" in msg
    assert "PAPERCO" in msg and "open paper trade" in msg
    assert "BUY, stop ₹1,440.00" in msg                  # BUY only with score 70+ and a stop
    assert "-2.1 pts vs Nifty" in msg and "3.4x normal volume" in msg
    assert "guarantee" not in msg.lower() and "sure" not in msg.lower()
    assert {r["symbol"] for r in kv["movers_radar:2026-11-17"]} == {"TINYHELD", "PAPERCO", "RELIANCE", "DHANBANK"}
    # same names on the next run: nothing new to send
    assert ma.check_movers_radar(state, "2026-11-17", now=now) == 0 and len(sent) == 1


def test_radar_sends_nothing_when_only_unlisted_small_names_move(wired, monkeypatch):
    """18 Nov 09:45: five micro caps, all 'no action: not on your lists'. Now nothing is sent."""
    ma, sent, kv = wired
    import data.nse_movers as NM
    monkeypatch.setattr(NM, "fetch_gainers", lambda snap=None: [
        {"symbol": f"MICRO{i}", "pct": 12.0 + i, "price": 50.0, "turnover_cr": 5, "source": "NSE"} for i in range(5)])
    monkeypatch.setattr(ma, "_holdings", lambda: [])
    monkeypatch.setattr(ma, "_paper_symbols", lambda: [])
    state = {}
    assert ma.check_movers_radar(state, "2026-11-18", now=dt.datetime(2026, 11, 18, 9, 45, tzinfo=IST)) == 0
    assert sent == [] and not any(k.startswith("movers_msg_") for k in state)


def test_radar_quiet_outside_window_and_at_daily_cap(wired):
    ma, sent, _ = wired
    early = dt.datetime(2026, 11, 17, 9, 20, tzinfo=IST)
    assert ma.check_movers_radar({}, "2026-11-17", now=early) == 0
    capped = {f"movers_msg_{i}": "2026-11-17" for i in range(1, ma.RADAR_MAX_MSGS + 1)}
    assert ma.check_movers_radar(capped, "2026-11-17", now=early.replace(hour=12)) == 0
    assert sent == []


def test_holding_guard_sends_only_trouble_once(wired, monkeypatch):
    ma, sent, kv = wired
    monkeypatch.setattr(ma, "_holdings", lambda: ["RELIANCE", "PFC", "COALINDIA"])
    quotes = {"RELIANCE": {"price": 1400, "chg_pct": -6.2}, "PFC": {"price": 400, "chg_pct": -1.0},
              "COALINDIA": {"price": 380, "chg_pct": -0.5}}
    import utils.live_price as lp
    monkeypatch.setattr(lp, "get_live_quote", lambda s: quotes.get(s))
    monkeypatch.setattr(ma, "_events_by_symbol", lambda now, days=3: {
        "COALINDIA": [{"category": "Resignation", "headline": "Statutory auditor resigns", "detail": ""}]})
    state, now = {}, dt.datetime(2026, 11, 17, 11, 0, tzinfo=IST)
    assert ma.check_holding_guard(state, "2026-11-17", now=now) == 1
    msg = sent[0]
    assert "RELIANCE" in msg and "COALINDIA" in msg and "PFC" not in msg
    assert ma.check_holding_guard(state, "2026-11-17", now=now) == 0


def test_default_run_includes_radar_and_guard():
    src = open("alerts/check_alerts.py", encoding="utf-8").read()
    assert '"movers":    _movers_radar(state, today)' in src
    assert '"guard":     _holding_guard(state, today)' in src


def test_canary_gainers_probe(monkeypatch):
    import data.nse_movers as NM
    import scripts.provider_canary as pc
    monkeypatch.setattr(NM, "fetch_nse_gainers", lambda: [
        {"symbol": f"S{i}", "pct": 10 - i * 0.1, "price": 100, "turnover_cr": 5} for i in range(12)])
    res = pc.run_probes(pc.MOVERS_PROBES)[0]
    assert res.status == pc.OK and "12 gainers" in res.reason
    monkeypatch.setattr(NM, "fetch_nse_gainers", lambda: [])
    assert pc.run_probes(pc.MOVERS_PROBES)[0].status == pc.FAILED
