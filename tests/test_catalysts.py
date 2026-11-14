"""Pure-logic tests for analysis/catalysts.py (offline, no fixtures on disk)."""
from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd
import pytest

from analysis import catalysts as C

IST = C.IST


# ── helpers ─────────────────────────────────────────────────────────────────

def _frame(n=30, close=100.0, vol=1_000_000, end="2026-11-13", event=None):
    """Flat-ish daily bars ending `end`; `event` = dict(open, high, low, close, volume) for the last bar."""
    idx = pd.bdate_range(end=end, periods=n)
    rng = np.random.default_rng(0)
    c = close + rng.normal(0, 0.3, n).cumsum() * 0.1
    df = pd.DataFrame({"Open": c, "High": c + 1.0, "Low": c - 1.0, "Close": c, "Volume": float(vol)}, index=idx)
    if event:
        for k, v in event.items():
            df.iloc[-1, df.columns.get_loc(k)] = v
    return df


def _q(period_end, revenue, profit, eps=None, op=None):
    return {"period_end": period_end, "revenue": revenue, "net_profit": profit, "eps": eps,
            "operating_profit": op, "unit": "cr"}


GOOD_Q = [
    _q("2026-09-30", 138, 41, 4.1, 30), _q("2026-06-30", 120, 30, 3.0, 24),
    _q("2026-03-31", 110, 25, 2.5, 20), _q("2025-12-31", 105, 24, 2.4, 19),
    _q("2025-09-30", 100, 22, 2.2, 17),
]
NOW_PRE = dt.datetime(2026, 11, 14, 8, 50, tzinfo=IST)     # Saturday is fine for maths; use Monday below
MON_PRE = dt.datetime(2026, 11, 16, 8, 50, tzinfo=IST)


def _results_event(when):
    return {"when": when, "category": "Financial Results",
            "headline": "Unaudited financial results for the quarter ended September 30, 2026", "detail": ""}


# ── classification ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("cat,head,kind,direction", [
    ("Updates", "Receipt of order worth Rs 450 crore from NHAI", "order_win", 1),
    ("Award of Order / Receipt of Order", "Company bagged an order", "order_win", 1),
    ("General Updates", "Letter of Award received from NTPC for EPC works", "order_win", 1),
    ("Updates", "Commissioning of new plant at Dahej; commercial production started", "capacity", 1),
    ("Buyback", "Board approves buyback of equity shares", "buyback", 1),
    ("Bonus issue", "Recommended bonus issue 1:1", "bonus", 1),
    ("Corporate Action", "Sub-division of equity shares from Rs 10 to Rs 2", "split", 1),
    ("Dividend", "Declared a special dividend of Rs 20", "special_dividend", 1),
    ("Acquisition", "Acquisition of 100% stake in XYZ Ltd", "acquisition", 1),
    ("Scheme of Arrangement", "Composite scheme of amalgamation", "merger", 0),
    ("Updates", "Board approves demerger of the chemicals business", "demerger", 1),
    ("Preferential Issue", "Allotment on preferential basis to promoter group", "preferential", 1),
    ("Updates", "Launch of QIP; floor price fixed", "dilution", -1),
    ("Updates", "USFDA approval for ANDA of generic drug", "fda_positive", 1),
    ("Updates", "USFDA inspection concluded with zero observations", "fda_positive", 1),
    ("Updates", "Receipt of warning letter from USFDA for Halol unit", "fda_negative", -1),
    ("Updates", "USFDA issued Form 483 with 5 observations", "fda_483", -1),
    ("Credit Rating", "CARE upgraded the long-term rating to AA", "rating_up", 1),
    ("Credit Rating", "ICRA downgraded the rating to BBB", "rating_down", -1),
    ("SAST", "Promoter acquired 2 lakh shares from open market", "promoter_buy", 1),
    ("SAST", "Creation of pledge on promoter shares", "pledge", -1),
    ("Offer for Sale", "Promoter sale of 5% stake via OFS", "promoter_sale", -1),
    ("Resignation", "Resignation of Statutory Auditor", "auditor_exit", -1),
    ("Change in KMP", "Resignation of Chief Financial Officer", "kmp_exit", -1),
    ("Updates", "SEBI interim order restraining the company", "regulatory", -1),
    ("Updates", "Order passed by GST authority - tax demand of Rs 12 crore and penalty", "penalty", -1),
    ("Updates", "Forensic audit reveals fraud by former management", "fraud", -1),
    ("Default", "Delay in payment of interest on NCDs", "default", -1),
    ("Insolvency", "NCLT admits CIRP petition against the company", "insolvency", -1),
    ("Updates", "Fire at the Tarapur plant; operations suspended", "disruption", -1),
    ("Financial Results", "Unaudited financial results for Q2", "results", 0),
    ("Outcome of Board Meeting", "Board approved the financial results for the quarter", "results", 0),
])
def test_classification_table(cat, head, kind, direction):
    c = C.classify_announcement(cat, head, "")
    assert c is not None, (cat, head)
    assert (c.kind, c.direction) == (kind, direction)
    assert 0 < c.weight <= 1


@pytest.mark.parametrize("cat,head", [
    ("Trading Window", "Closure of trading window"),
    ("Newspaper Publication", "Copy of newspaper publication of results"),
    ("Loss of Share Certificate", "Loss of share certificate - folio 123"),
    ("Updates", "Updates"),
    ("Board Meeting Intimation", "Board meeting to consider financial results on 12 Nov"),
    ("Certificate under SEBI (Depositories and Participants) Regulations", "Reg 74(5)"),
    ("Credit Rating", "CRISIL reaffirmed the rating at AA+"),
    ("Analysts/Institutional Investor Meet", "Schedule of investor meet"),
    ("ESOP", "Allotment of shares under ESOP scheme"),
    ("Disclosure of defaults", "Disclosure of defaults on loans - Nil"),
    ("", ""),
    (None, None),
])
def test_noise_is_none(cat, head):
    assert C.classify_announcement(cat, head, "") is None


def test_order_from_regulator_is_not_an_order_win():
    c = C.classify_announcement("Updates", "SEBI order against promoters", "")
    assert c.kind == "regulatory"


# ── results surprise ────────────────────────────────────────────────────────

def test_surprise_strong_positive():
    s = C.results_surprise(GOOD_Q)
    assert s["label"] == "Q2"
    assert s["profit_yoy_pct"] == pytest.approx(86.36, abs=0.1)
    assert s["revenue_yoy_pct"] == pytest.approx(38.0)
    assert s["margin_change_pts"] == pytest.approx(30 / 138 * 100 - 17, abs=0.01)
    assert s["profit_qoq_pct"] == pytest.approx(36.67, abs=0.1)
    assert s["score"] > 60 and not s["turnaround"]


def test_surprise_needs_year_ago():
    assert C.results_surprise(GOOD_Q[:3]) is None
    assert C.results_surprise([]) is None
    assert C.results_surprise(None) is None
    assert C.results_surprise([{"period_end": "garbage"}, "x"]) is None


def test_surprise_order_independent_and_string_numbers():
    q = [dict(r) for r in reversed(GOOD_Q)]
    q[0]["revenue"] = "1,00"   # "100" with a stray comma
    assert C.results_surprise(q)["revenue_yoy_pct"] == pytest.approx(38.0)


def test_turnaround_and_negative_base():
    q = [_q("2026-09-30", 120, 15), _q("2026-06-30", 110, 5), _q("2025-09-30", 100, -10)]
    s = C.results_surprise(q)
    assert s["turnaround"] and "turnaround" in s["flags"]
    assert s["profit_yoy_pct"] == pytest.approx(250.0)       # (15 - -10) / 10
    assert s["score"] > 40
    assert "swung to a profit" in C.surprise_phrase(s)


def test_negative_base_deeper_loss_is_negative():
    s = C.results_surprise([_q("2026-09-30", 100, -20), _q("2025-09-30", 100, -10)])
    assert s["profit_yoy_pct"] == pytest.approx(-100.0)
    assert s["score"] < 0 and not s["turnaround"]


def test_slipped_to_loss():
    s = C.results_surprise([_q("2026-09-30", 90, -5), _q("2025-09-30", 100, 10)])
    assert s["slipped_to_loss"]
    assert s["score"] <= -40


def test_tiny_base_is_capped():
    s = C.results_surprise([_q("2026-09-30", 105, 50), _q("2025-09-30", 100, 0.1)])
    assert s["profit_yoy_pct"] == C.GROWTH_CAP
    assert s["score"] <= 100


def test_profit_up_revenue_down_is_downweighted():
    good = C.results_surprise([_q("2026-09-30", 100, 20), _q("2025-09-30", 100, 10)])
    odd = C.results_surprise([_q("2026-09-30", 80, 20), _q("2025-09-30", 100, 10)])
    assert "profit_without_revenue" in odd["flags"] and "mixed" in odd["flags"]
    assert odd["score"] < good["score"] and abs(odd["score"]) <= 40


def test_lender_uses_total_income_and_skips_margin():
    q = [{"period_end": "2026-09-30", "revenue": 50, "total_income": 130, "net_profit": 30, "operating_profit": 1},
         {"period_end": "2025-09-30", "revenue": 50, "total_income": 100, "net_profit": 20, "operating_profit": 40}]
    s = C.results_surprise(q, is_lender=True)
    assert s["revenue_yoy_pct"] == pytest.approx(30.0)
    assert s["margin_change_pts"] is None
    assert C.results_surprise(q)["margin_change_pts"] is not None


# ── reaction ────────────────────────────────────────────────────────────────

def test_reaction_maths():
    df = _frame(event={"Open": 104.0, "High": 109.0, "Low": 103.0, "Close": 108.5, "Volume": 4_000_000})
    prev = float(df["Close"].iloc[-2])
    r = C.reaction(df, dt.date(2026, 11, 13))
    assert r["is_event_day"]
    assert r["ret_pct"] == pytest.approx((108.5 / prev - 1) * 100, abs=0.01)
    assert r["gap_pct"] == pytest.approx((104 / prev - 1) * 100, abs=0.01)
    assert r["rel_vol"] == pytest.approx(4.0)
    assert r["close_pos"] == pytest.approx(5.5 / 6, abs=1e-3)
    assert r["above_20d_high"]
    assert r["avg_turnover_cr"] == pytest.approx(prev * 1e6 / 1e7, rel=0.05)
    assert r["atr14"] > 0 and not r["circuit_locked"]


def test_reaction_after_close_filing_maps_to_next_session_and_nifty():
    df = _frame(event={"Close": 110.0, "High": 110.0})
    nifty = _frame(close=20000.0, event={"Close": 20200.0})
    # filed Thursday 12 Nov 18:30 -> reaction is Friday 13 Nov's bar
    r = C.reaction(df, dt.datetime(2026, 11, 12, 18, 30, tzinfo=IST), nifty_df=nifty)
    assert r["is_event_day"] and r["event_date"] == dt.date(2026, 11, 13)
    assert r["ret_vs_nifty_pct"] == pytest.approx(r["ret_pct"] - r["nifty_ret_pct"])


def test_reaction_circuit_lock():
    df = _frame()
    prev = float(df["Close"].iloc[-2])
    up = round(prev * 1.10, 2)
    df.iloc[-1] = [prev * 1.03, up, prev * 1.02, up, 2e6]
    r = C.reaction(df, "2026-11-13")
    assert r["circuit_locked"] and r["circuit_band_pct"] == 10.0


def test_reaction_pending_event_and_garbage():
    df = _frame()
    r = C.reaction(df, dt.datetime(2026, 11, 13, 17, 0, tzinfo=IST))   # next session not traded yet
    assert r["is_event_day"] is False and r["ret_pct"] is None and r["atr14"] > 0
    assert C.reaction(pd.DataFrame(), "2026-11-13") is None
    assert C.reaction("nope", "2026-11-13") is None
    assert C.reaction(_frame(n=3), "2026-11-13") is None
    assert C.reaction(df, None) is None


# ── sessions / freshness ────────────────────────────────────────────────────

def test_sessions_between_and_holidays():
    fri_evening = dt.datetime(2026, 11, 13, 18, 0, tzinfo=IST)
    assert C.sessions_between(fri_evening, MON_PRE) == 0
    assert C.sessions_between(dt.datetime(2026, 11, 13, 11, 0, tzinfo=IST), MON_PRE) == 1
    assert C.sessions_between(dt.datetime(2026, 11, 11, 11, 0, tzinfo=IST), MON_PRE) == 3
    # a holiday on Friday removes that close
    assert C.sessions_between(dt.datetime(2026, 11, 12, 11, 0, tzinfo=IST), MON_PRE,
                              holidays={"2026-11-13"}) == 1
    assert C.freshness(0) == 1.0 and C.freshness(1) == 0.6 and C.freshness(3) == 0
    assert C.freshness(4, kind="results", strong_reaction=True) == 0.5
    assert C.freshness(6, kind="results", strong_reaction=True) == 0


# ── catalyst_read ───────────────────────────────────────────────────────────

def _pending_rx(df=None):
    return C.reaction(df if df is not None else _frame(vol=3_000_000), dt.datetime(2026, 11, 13, 18, 0, tzinfo=IST))


def _read(gap, events=None, surprise="good", rx=None, **kw):
    s = C.results_surprise(GOOD_Q) if surprise == "good" else surprise
    rx = rx or _pending_rx()
    pre = None if gap is None else {"iep": rx["last_close"] * (1 + gap / 100), "prev_close": rx["last_close"],
                                    "gap_pct": gap}
    ev = events if events is not None else [_results_event(dt.datetime(2026, 11, 13, 18, 0, tzinfo=IST))]
    return C.catalyst_read("cupid", ev, s, rx, preopen=pre, now=MON_PRE, **kw)


def test_buy_in_tradable_gap_zone():
    r = _read(4.2)
    assert r.action == "BUY" and r.symbol == "CUPID" and r.horizon == "intraday"
    assert r.reasons[0].startswith("Q2 profit +86% YoY") and "gap +4.2%" in r.reasons
    assert r.stop < r.trigger < r.target and r.risk_reward >= 1.5
    assert 0 < r.strength <= 100
    assert r.as_dict()["action"] == "BUY" and r["action"] == "BUY"


def test_gap_discipline_extended_is_watch():
    r = _read(9.5)
    assert r.action == "WATCH" and C.EXTENDED_WARNING in r.warnings


def test_circuit_locked_is_watch():
    df = _frame(vol=3_000_000)
    prev = float(df["Close"].iloc[-2])
    up = round(prev * 1.2, 2)
    df.iloc[-1] = [prev * 1.05, up, prev * 1.04, up, 9e6]
    rx = C.reaction(df, dt.date(2026, 11, 13))
    ev = [_results_event(dt.datetime(2026, 11, 13, 9, 30, tzinfo=IST))]
    r = C.catalyst_read("X", ev, C.results_surprise(GOOD_Q), rx, now=dt.datetime(2026, 11, 13, 15, 0, tzinfo=IST))
    assert r.action == "WATCH" and C.EXTENDED_WARNING in r.warnings


def test_good_news_sold_into_and_small_gap():
    r = _read(-2.5)
    assert r.action == "WATCH" and "good news sold into" in r.reasons
    assert _read(0.4).action == "WATCH"
    assert _read(None).action == "WATCH"


def test_sell_mirror():
    bad = [_q("2026-09-30", 80, 5), _q("2025-09-30", 100, 22)]
    r = _read(-4.0, surprise=C.results_surprise(bad))
    assert r.action == "SELL" and r.direction == -1
    assert r.target < r.trigger < r.stop
    assert C.SELL_WARNING in r.warnings
    assert _read(-11.0, surprise=C.results_surprise(bad)).action == "WATCH"


def test_inline_results_give_no_read():
    flat = [_q("2026-09-30", 101, 22), _q("2025-09-30", 100, 22)]
    assert _read(3.0, surprise=C.results_surprise(flat)) is None
    assert _read(3.0, surprise=None) is None          # results with no numbers -> no direction


def test_liquidity_floor():
    thin = _pending_rx(_frame(vol=50_000))           # ~₹0.5 cr / day
    assert _read(4.0, rx=thin) is None
    penny = _pending_rx(_frame(close=12.0, vol=50_000_000))
    assert _read(4.0, rx=penny) is None
    assert _read(4.0, avg_turnover_cr=None) is not None   # falls back to the reaction's turnover


def test_freshness_decay_and_expiry():
    fresh = _read(4.0)
    old = _read(4.0, events=[_results_event(dt.datetime(2026, 11, 13, 11, 0, tzinfo=IST))])   # 1 close ago
    assert old.horizon == "swing" and old.strength < fresh.strength
    stale = _read(4.0, events=[_results_event(dt.datetime(2026, 11, 10, 11, 0, tzinfo=IST))])
    assert stale is None


def test_volume_not_confirming_on_event_day():
    df = _frame(vol=3_000_000)
    prev = float(df["Close"].iloc[-2])
    df.iloc[-1] = [prev * 1.01, prev * 1.04, prev * 1.005, prev * 1.035, 3_300_000]
    rx = C.reaction(df, dt.date(2026, 11, 13))
    ev = [{"when": dt.datetime(2026, 11, 13, 9, 20, tzinfo=IST), "category": "Updates",
           "headline": "Receipt of order worth Rs 900 crore"}]
    r = C.catalyst_read("X", ev, None, rx, now=dt.datetime(2026, 11, 13, 15, 0, tzinfo=IST))
    assert r.action == "WATCH" and any("volume not confirming" in w for w in r.warnings)


def test_opening_range_stop_rule_and_rr_rejection():
    rx = _pending_rx()
    orr = {"high": rx["last_close"] * 1.05, "low": rx["last_close"] * 1.01}
    r = _read(4.0, rx=rx, opening_range=orr)
    assert r.trigger == pytest.approx(orr["high"], abs=0.01)
    assert r.stop == pytest.approx(min(orr["low"], orr["high"] - 0.5 * rx["atr14"]), abs=0.01)
    # circuit band 5% just above the trigger caps the target -> under 1.5R -> WATCH
    capped = _read(4.0, rx=rx, opening_range=orr, price_band_pct=5.5)
    assert capped.action == "WATCH" and any("under 1.5R" in w for w in capped.warnings)


def test_live_quote_confirmation():
    rx = _pending_rx()
    live = {"price": rx["last_close"] * 1.03, "chg_pct": 3.0, "rel_vol": 2.4, "high": rx["last_close"] * 1.035}
    r = _read(None, rx=rx, live=live)
    assert r.action == "BUY" and "today +3.0%" in r.reasons and "2.4x volume" in r.reasons
    assert r.trigger == pytest.approx(live["high"], abs=0.01)


def test_catalyst_read_never_raises_on_garbage():
    assert C.catalyst_read("X", None, None, None) is None
    assert C.catalyst_read("X", ["junk", {"when": "bad"}], {"score": "x"}, {"avg_turnover_cr": "a"}) is None
    assert C.catalyst_read("X", [{"category": "Buyback"}], None, _pending_rx(), now=MON_PRE) is None  # no 'when'


def test_rank_reads_dedupes_by_symbol():
    a = _read(4.0)
    b = C.CatalystRead("CUPID", "WATCH", 10, "swing")
    c = C.CatalystRead("ABC", "SELL", 70, "intraday")
    out = C.rank_reads([b, None, c, a, {"symbol": "XYZ", "strength": 5, "action": "BUY"}])
    syms = [x["symbol"] if isinstance(x, dict) else x.symbol for x in out]
    assert syms.count("CUPID") == 1 and syms[0] in ("CUPID", "ABC") and syms[-1] == "XYZ"
    assert next(x for x in out if getattr(x, "symbol", None) == "CUPID").action == "BUY"


# ── explain_move ────────────────────────────────────────────────────────────

def test_explain_move_with_evidence():
    s = C.results_surprise(GOOD_Q)
    rx = {"rel_vol": 5.2, "above_20d_high": True}
    out = C.explain_move("CUPID", 12.0, events=[_results_event("2026-11-13")], surprise=s, reaction=rx,
                         sector_return_pct=3.1, nifty_return_pct=1.0)
    assert out[0] == "Q2 profit ₹41 cr vs ₹22 cr a year ago, +86%; revenue +38%"
    assert "whole sector +3.1%" in out and "market-wide move: Nifty +1.0%" in out
    assert "5.2x normal volume" in out and "broke its 20-day high" in out
    assert C.NO_EVIDENCE not in out


def test_explain_move_announcement_and_opposite_sector():
    ev = [{"category": "Updates", "headline": "Bagged order worth Rs 300 crore from Indian Railways"}]
    out = C.explain_move("X", 6.0, events=ev, sector_return_pct=-2.0, nifty_return_pct=-1.0)
    assert out[0].startswith("order win: Bagged order")
    assert not any("sector" in o or "Nifty" in o for o in out)


def test_explain_move_without_evidence():
    out = C.explain_move("X", -9.0, events=[{"category": "Trading Window", "headline": "closure"}],
                         reaction={"rel_vol": 3.0, "below_20d_low": True})
    assert out[0] == C.NO_EVIDENCE
    assert "3.0x normal volume" in out and "broke below its 20-day low" in out
    assert C.explain_move("X", 5.0) == [C.NO_EVIDENCE]


# ── grade_picks ─────────────────────────────────────────────────────────────

def test_grade_picks():
    idx = pd.to_datetime(["2026-11-12", "2026-11-13", "2026-11-16", "2026-11-17"])
    up = pd.DataFrame({"High": [99, 101, 104, 108], "Low": [97, 99.5, 100.5, 103], "Close": [98, 100.5, 103, 107]},
                      index=idx)
    down = pd.DataFrame({"High": [101, 101, 100], "Low": [99, 97, 96], "Close": [100, 98, 97]}, index=idx[1:])
    picks = [
        {"symbol": "UP", "action": "BUY", "date": "2026-11-13", "trigger": 100, "stop": 98, "target": 106},
        {"symbol": "STOP", "action": "BUY", "date": "2026-11-13", "trigger": 100, "stop": 98, "target": 106},
        {"symbol": "NEVER", "action": "BUY", "date": "2026-11-13", "trigger": 200, "stop": 190, "target": 220},
        {"symbol": "OPEN", "action": "SELL", "date": "2026-11-13", "trigger": 99, "stop": 102, "target": 90},
        {"symbol": "BAD", "action": "WATCH", "date": "2026-11-13", "trigger": 1, "stop": 1, "target": 1},
        "junk",
    ]
    closes = {"UP": up, "STOP": down, "NEVER": up, "OPEN": down["Close"]}
    g = C.grade_picks(picks, closes)
    by = {p["symbol"]: p for p in g["picks"]}
    assert by["UP"]["status"] == "hit" and by["UP"]["r"] == 3.0
    assert by["STOP"]["status"] == "stop" and by["STOP"]["r"] == -1.0
    assert by["NEVER"]["status"] == "not_triggered" and by["NEVER"]["r"] is None
    assert by["OPEN"]["status"] == "open" and by["OPEN"]["r"] == pytest.approx((99 - 97) / 3, abs=0.01)
    assert "BAD" not in by
    sm = g["summary"]
    assert sm["n"] == 4 and sm["hit"] == 1 and sm["stop"] == 1 and sm["win_rate"] == 0.5
    assert C.grade_picks(None, None)["summary"]["n"] == 0
