"""Offline tests for data/nse_announcements.py and alerts/catalyst_alerts.py (fixture payloads only)."""
from __future__ import annotations

import datetime as dt
import sys
import types

import numpy as np
import pandas as pd
import pytest

import alerts.catalyst_alerts as CA
import alerts.check_alerts as ca
import data.nse_announcements as N
from analysis import catalysts as C

IST = N.IST
MON_PRE = dt.datetime(2026, 11, 16, 8, 50, tzinfo=IST)
FRI_EVE = dt.datetime(2026, 11, 13, 18, 0, tzinfo=IST)


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    N.clear_cache()
    monkeypatch.setattr(ca, "_FORCE_SEND", False)
    yield
    N.clear_cache()


@pytest.fixture
def store(monkeypatch):
    kv: dict = {}
    mod = types.ModuleType("trade_store")
    mod.kv_get = lambda key, default=None, user_id="default": kv.get((user_id, key), default)

    def kv_set(key, value, user_id="default"):
        kv[(user_id, key)] = value
        return True
    mod.kv_set = kv_set
    mod.kv = kv
    monkeypatch.setitem(sys.modules, "trade_store", mod)
    return mod


@pytest.fixture
def sent(monkeypatch):
    out: list = []

    def fake_dispatch(msg, *, subject="x"):
        out.append(msg)
        return True
    monkeypatch.setattr(ca, "dispatch", fake_dispatch)
    return out


def _frame(n=40, close=100.0, vol=3_000_000, end="2026-11-13", last=None):
    idx = pd.bdate_range(end=end, periods=n)
    c = close + np.linspace(-2, 0, n)
    df = pd.DataFrame({"Open": c, "High": c + 1.5, "Low": c - 1.5, "Close": c, "Volume": float(vol)}, index=idx)
    if last:
        df.iloc[-1] = last
    return df


GOOD_Q = [
    {"period_end": dt.date(2026, 9, 30), "revenue": 138, "net_profit": 41, "eps": 4.1, "operating_profit": 30},
    {"period_end": dt.date(2026, 6, 30), "revenue": 120, "net_profit": 30, "eps": 3.0, "operating_profit": 24},
    {"period_end": dt.date(2025, 9, 30), "revenue": 100, "net_profit": 22, "eps": 2.2, "operating_profit": 17},
]
BAD_Q = [{"period_end": dt.date(2026, 9, 30), "revenue": 80, "net_profit": 5},
         {"period_end": dt.date(2025, 9, 30), "revenue": 100, "net_profit": 22}]


# ── data: parsing ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expect", [
    ("13-Nov-2026 18:45:12", dt.datetime(2026, 11, 13, 18, 45, 12)),
    ("2026-11-13 18:45:12", dt.datetime(2026, 11, 13, 18, 45, 12)),
    ("2026-11-13T18:45:12.877", dt.datetime(2026, 11, 13, 18, 45, 12, 877000)),
    ("13-NOV-2026", dt.datetime(2026, 11, 13)),
    ("Fri, 13 Nov 2026 13:15:12 +0000", dt.datetime(2026, 11, 13, 18, 45, 12)),
])
def test_parse_when(raw, expect):
    assert N.parse_when(raw) == expect.replace(tzinfo=IST)


@pytest.mark.parametrize("raw", [None, "", "yesterday", 12345, "31-Feb-2026"])
def test_parse_when_garbage(raw):
    assert N.parse_when(raw) is None


@pytest.mark.parametrize("raw,val", [("1,234.5", 1234.5), ("(45)", -45.0), ("-", None), ("abc", None),
                                     (12, 12.0), (None, None), (True, None), ("₹ 1,00", 100.0)])
def test_num(raw, val):
    assert N.num(raw) == val


NSE_ANN = [
    {"symbol": "CUPID", "desc": "Financial Result Updates", "attchmntText": "Q2 results approved",
     "an_dt": "13-Nov-2026 18:00:00", "attchmntFile": "https://nsearchives.nseindia.com/corporate/CUPID_1.pdf",
     "sm_name": "Cupid Limited"},
    {"symbol": "ABC", "desc": "Updates", "attchmntText": "Receipt of order worth Rs 500 crore",
     "sort_date": "2026-11-13 19:10:00"},
    {"symbol": "", "desc": "x", "an_dt": "13-Nov-2026 18:00:00"},          # no symbol
    {"symbol": "BAD", "desc": "x", "an_dt": "not a date"},                # bad date
    "garbage",
    {"symbol": "OLD", "desc": "Updates", "an_dt": "01-Nov-2026 10:00:00"},  # outside window
]


def test_fetch_announcements_nse(monkeypatch):
    calls = []

    def fake(path, params=None):
        calls.append((path, params))
        return NSE_ANN
    monkeypatch.setattr(N, "_nse_json", fake)
    out = N.fetch_announcements(dt.datetime(2026, 11, 13, 15, 30, tzinfo=IST), MON_PRE)
    assert [r["symbol"] for r in out] == ["ABC", "CUPID"]
    assert out[1]["when"] == FRI_EVE and out[1]["source"] == "nse_api" and out[1]["url"].endswith(".pdf")
    assert calls[0][1]["from_date"] == "13-11-2026" and calls[0][1]["to_date"] == "16-11-2026"
    N.fetch_announcements(dt.datetime(2026, 11, 13, 15, 30, tzinfo=IST), MON_PRE)
    assert len(calls) == 1                                         # cached


def test_announcements_dict_payload_and_schema_drift_falls_back(monkeypatch):
    monkeypatch.setattr(N, "_nse_json", lambda p, q=None: {"data": [{"foo": 1}, {"bar": 2}]})
    import data.nse_rss_feeds as R
    rss = [{"title": "Cupid Limited", "link": "https://nsearchives.nseindia.com/corporate/CUPID_13112026180000_x.pdf",
            "description": "SUBJECT: Financial Results |", "pub_date": "13-Nov-2026 18:00:00"},
           {"title": "No symbol here", "link": "", "description": "", "pub_date": "13-Nov-2026 18:00:00"}]
    monkeypatch.setattr(R, "_fetch_one", lambda cat, fn: (rss, {"ok": True}))
    out = N.fetch_announcements(dt.datetime(2026, 11, 13, 15, 30, tzinfo=IST), MON_PRE)
    assert [(r["symbol"], r["source"], r["category"]) for r in out] == [("CUPID", "nse_rss", "Financial Results")]


def test_tier_fallback_to_bse(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("HTTP 403 from /api/corporate-announcements")
    monkeypatch.setattr(N, "_nse_json", boom)
    import data.bse_corp_info as B
    import data.nse_rss_feeds as R
    monkeypatch.setattr(R, "_fetch_one", lambda cat, fn: ([], {"reason": "empty"}))

    class FakeBSE:
        def announcements(self, page_no=1, from_date=None, to_date=None):
            return {"Table": [{"NSURL": "https://www.bseindia.com/stock-share-price/abc-ltd/abc/500001/",
                               "NEWSSUB": "ABC Ltd - Bagged order worth Rs 200 crore",
                               "DissemDT": "2026-11-13T19:00:00.123", "CATEGORYNAME": "Company Update",
                               "ATTACHMENTNAME": "a.pdf"},
                              {"NSURL": "", "NEWSSUB": "x", "DissemDT": "2026-11-13T19:00:00"}]}
    monkeypatch.setattr(B, "_get_client", lambda: FakeBSE())
    out = N.fetch_announcements(dt.datetime(2026, 11, 13, 15, 30, tzinfo=IST), MON_PRE)
    assert [(r["symbol"], r["source"]) for r in out] == [("ABC", "bse")]
    assert out[0]["url"].endswith("a.pdf")


def test_all_tiers_fail_returns_empty(monkeypatch):
    monkeypatch.setattr(N, "_nse_json", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("down")))
    import data.bse_corp_info as B
    import data.nse_rss_feeds as R
    monkeypatch.setattr(R, "_fetch_one", lambda cat, fn: (_ for _ in ()).throw(ValueError("bad xml")))
    monkeypatch.setattr(B, "_get_client", lambda: None)
    assert N.fetch_announcements(MON_PRE - dt.timedelta(days=1), MON_PRE) == []
    assert N.fetch_announcements("garbage") == []
    assert N.get_last_diagnostic("nse_api")["ok"] is False


def test_circuit_breaker_opens_after_three_failures(monkeypatch):
    n = {"calls": 0}

    def boom(*a, **k):
        n["calls"] += 1
        raise RuntimeError("timeout")
    monkeypatch.setattr(N, "_nse_json", boom)
    for _ in range(5):
        assert N.fetch_preopen() == {}
    assert n["calls"] == 3 and N.breaker_open("nse_preopen")
    N.clear_cache()
    assert not N.breaker_open("nse_preopen")


def test_session_warm_up_and_http_error(monkeypatch):
    class Resp:
        def __init__(self, code, payload=None):
            self.status_code, self._p = code, payload

        def json(self):
            return self._p

    class Sess:
        def __init__(self):
            self.urls = []

        def get(self, url, params=None, timeout=None):
            assert timeout and timeout <= 15
            self.urls.append(url)
            return Resp(200, {"data": []}) if "pre-open" in url else Resp(403)
    s = Sess()
    import data.nse_corp_info as NC
    monkeypatch.setattr(NC, "_ensure_session", lambda: s)
    assert N._nse_json("/api/market-data-pre-open", {"key": "ALL"}) == {"data": []}
    assert s.urls[0] == "https://www.nseindia.com/"
    with pytest.raises(RuntimeError, match="HTTP 403"):
        N._nse_json("/api/corporate-announcements")
    assert s.urls.count("https://www.nseindia.com/") == 1          # warm-up not repeated


# ── data: results filed ─────────────────────────────────────────────────────

def test_fetch_results_filed_nse(monkeypatch):
    rows = [{"symbol": "CUPID", "toDate": "30-Sep-2026", "broadCastDate": "13-Nov-2026 18:00",
             "consolidated": "Non-Consolidated", "xbrl": "https://x/a.xml"},
            {"symbol": "CUPID", "toDate": "30-Sep-2026", "broadCastDate": "13-Nov-2026 18:05",
             "consolidated": "Consolidated", "xbrl": "https://x/b.xml"},
            {"symbol": "OLDCO", "toDate": "30-Sep-2026", "broadCastDate": "01-Nov-2026 10:00"},
            {"symbol": "JUNK"}, 7]
    monkeypatch.setattr(N, "_nse_json", lambda p, q=None: rows)
    out = N.fetch_results_filed(dt.datetime(2026, 11, 13, 15, 30, tzinfo=IST))
    assert len(out) == 1 and out[0]["symbol"] == "CUPID" and out[0]["consolidated"]
    assert out[0]["period_end"] == dt.date(2026, 9, 30) and out[0]["xbrl"].endswith("b.xml")


def test_fetch_results_filed_falls_back_to_announcements(monkeypatch):
    def fake(path, params=None):
        if "financial-results" in path:
            raise RuntimeError("HTTP 401")
        return NSE_ANN
    monkeypatch.setattr(N, "_nse_json", fake)
    out = N.fetch_results_filed(dt.datetime(2026, 11, 13, 15, 30, tzinfo=IST))
    assert [r["symbol"] for r in out] == ["CUPID"]


# ── data: quarterly figures ─────────────────────────────────────────────────

RES_CMP = {"resCmpData": [
    {"re_to_dt": "30-SEP-2026", "re_net_sale": "13,800", "re_con_pro_loss": "4,100", "re_basic_eps_for_cont_dic_opr": "4.1",
     "re_res_type": "Standalone"},
    {"re_to_dt": "30-SEP-2026", "re_net_sale": "14,000", "re_net_profit": "4,200", "re_basic_eps": "4.2",
     "re_res_type": "Consolidated"},
    {"re_to_dt": "30-JUN-2026", "re_net_sale": "12,000", "re_net_profit": "3,000"},
    {"re_to_dt": "garbage", "re_net_sale": "1"},
    {"re_to_dt": "31-MAR-2026"},                                     # no numbers
    {"re_to_dt": "30-SEP-2025", "re_net_sale": "10,000.00", "re_net_profit": "(2,200)"},
]}


def test_parse_results_comparison():
    q = N.parse_results_comparison(RES_CMP)
    assert [x["period_end"] for x in q] == [dt.date(2026, 9, 30), dt.date(2026, 6, 30), dt.date(2025, 9, 30)]
    assert q[0]["consolidated"] and q[0]["revenue"] == 140.0 and q[0]["net_profit"] == 42.0 and q[0]["eps"] == 4.2
    assert q[2]["net_profit"] == -22.0 and q[0]["unit"] == "cr"
    assert N.parse_results_comparison("garbage") == [] and N.parse_results_comparison({"resCmpData": None}) == []
    assert N.parse_results_comparison(RES_CMP, unit="crore")[0]["revenue"] == 14000.0


def test_quarterly_tier_prefers_latest_quarter(monkeypatch):
    monkeypatch.setattr(N, "latest_reportable_quarter_end", lambda today=None: dt.date(2026, 9, 30))
    calls = []

    def t1(sym):
        calls.append("nse")
        return [{"period_end": dt.date(2026, 6, 30), "net_profit": 1, "revenue": 1}]

    def t2(sym):
        calls.append("screener")
        return [{"period_end": dt.date(2026, 9, 30), "net_profit": 2, "revenue": 2}]

    def t3(sym):
        calls.append("yahoo")
        return [{"period_end": dt.date(2026, 9, 30), "net_profit": 3, "revenue": 3}]
    out = N.fetch_quarterly_figures("cupid.ns", tiers=[("a", t1), ("b", t2), ("c", t3)])
    assert out[0]["net_profit"] == 2 and calls == ["nse", "screener"]      # stops once the latest is found


def test_quarterly_tier_errors_and_empty(monkeypatch):
    monkeypatch.setattr(N, "latest_reportable_quarter_end", lambda today=None: dt.date(2026, 9, 30))

    def boom(sym):
        raise RuntimeError("down")
    old = [{"period_end": dt.date(2026, 6, 30), "net_profit": 1, "revenue": 1}]
    assert N.fetch_quarterly_figures("X", tiers=[("a", boom), ("b", lambda s: []), ("c", lambda s: old)]) == old
    assert N.fetch_quarterly_figures("Y", tiers=[("a", boom)]) == []
    assert N.fetch_quarterly_figures("") == []
    assert N.choose_tier([("a", old), ("b", [{"period_end": dt.date(2026, 6, 30)}])]) == old   # tie keeps first


def test_statement_tiers_convert_to_crore():
    from analysis.fundamentals.models import FiscalPeriod, IncomeStatement
    st = [IncomeStatement(period=FiscalPeriod(period_end=dt.date(2026, 9, 28)), revenue=1.38e9, net_income=4.1e8,
                          eps_basic=4.1, operating_income=3e8)]
    q = N._from_statements(st, "screener", None)
    assert q[0]["period_end"] == dt.date(2026, 9, 30) and q[0]["revenue"] == pytest.approx(138.0)
    assert N._from_statements(None, "yahoo", True) == []


def test_latest_reportable_quarter_end():
    assert N.latest_reportable_quarter_end(dt.date(2026, 11, 14)) == dt.date(2026, 9, 30)
    assert N.latest_reportable_quarter_end(dt.date(2026, 1, 5)) == dt.date(2025, 12, 31)
    assert N.latest_reportable_quarter_end(dt.date(2026, 4, 1)) == dt.date(2026, 3, 31)


# ── data: pre-open ──────────────────────────────────────────────────────────

PREOPEN = {"data": [
    {"metadata": {"symbol": "CUPID", "iep": "104.00", "previousClose": "100.00", "pChange": "4", "finalQuantity": 5000},
     "detail": {"preOpenMarket": {"IEP": 104}}},
    {"metadata": {"symbol": "ZERO", "iep": 0, "previousClose": 50}},
    {"metadata": {"symbol": "NOPREV", "iep": "55", "pChange": "-2.5"}},
    {"bad": True}, "junk",
]}


def test_preopen_parse_and_fetch(monkeypatch):
    p = N.parse_preopen(PREOPEN)
    assert p["CUPID"] == {"iep": 104.0, "prev_close": 100.0, "gap_pct": 4.0, "qty": 5000.0}
    assert "ZERO" not in p and p["NOPREV"]["gap_pct"] == -2.5
    monkeypatch.setattr(N, "_nse_json", lambda path, params=None: PREOPEN)
    assert set(N.fetch_preopen()) == {"CUPID", "NOPREV"}
    N.clear_cache()
    monkeypatch.setattr(N, "_nse_json", lambda path, params=None: "<html>blocked</html>")
    assert N.fetch_preopen() == {}


# ── alerts: helpers ─────────────────────────────────────────────────────────

def test_previous_session_close_and_compose():
    assert CA.previous_session_close(MON_PRE) == dt.datetime(2026, 11, 13, 15, 30, tzinfo=IST)
    assert CA.previous_session_close(MON_PRE, {"2026-11-13"}) == dt.datetime(2026, 11, 12, 15, 30, tzinfo=IST)
    msg = CA.compose("H", [(f"a{i}", f"b{i}") for i in range(8)], "F")
    lines = msg.split("\n")
    assert len(lines) <= 14 and lines[0] == "H" and lines[-1] == "F"
    assert "a7" in msg and "b0" in msg and "b7" not in msg
    assert len(CA.compose("H", [(f"a{i}", "") for i in range(20)], "F").split("\n")) == 14


# ── alerts: pre-open ────────────────────────────────────────────────────────

def _wire(monkeypatch, *, anns, results=(), preopen=None, quarters=None, frames=None):
    monkeypatch.setattr(N, "fetch_announcements", lambda since, until=None: list(anns))
    monkeypatch.setattr(N, "fetch_results_filed", lambda since: list(results))
    monkeypatch.setattr(N, "fetch_preopen", lambda: dict(preopen or {}))
    monkeypatch.setattr(N, "fetch_quarterly_figures", lambda sym: list((quarters or {}).get(sym, [])))
    monkeypatch.setattr(CA, "_daily", lambda sym, period="6mo": (frames or {}).get(sym, _frame()))
    monkeypatch.setattr(CA, "_nifty", lambda: None)


def _ann(sym, cat, head, when=FRI_EVE):
    return {"symbol": sym, "when": when, "category": cat, "headline": head, "detail": "", "source": "nse_api"}


def test_preopen_message(monkeypatch, store, sent):
    last = float(_frame()["Close"].iloc[-1])
    anns = [_ann("CUPID", "Financial Results", "Unaudited financial results"),
            _ann("WEAK", "Financial Results", "Unaudited financial results"),
            _ann("ABC", "Updates", "Receipt of order worth Rs 900 crore"),
            _ann("NOISE", "Trading Window", "Closure of trading window"),
            _ann("HOT", "Buyback", "Board approves buyback")]
    pre = {"CUPID": {"iep": last * 1.042, "prev_close": last, "gap_pct": 4.2},
           "WEAK": {"iep": last * 0.96, "prev_close": last, "gap_pct": -4.0},
           "ABC": {"iep": last * 1.02, "prev_close": last, "gap_pct": 2.0},
           "HOT": {"iep": last * 1.12, "prev_close": last, "gap_pct": 12.0}}
    _wire(monkeypatch, anns=anns, preopen=pre, quarters={"CUPID": GOOD_Q, "WEAK": BAD_Q})
    state: dict = {}
    assert CA.check_catalyst_preopen(state, "2026-11-16", now=MON_PRE) == 1
    msg = sent[0]
    lines = msg.split("\n")
    assert len(lines) <= 14 and "Catalyst picks" in lines[0] and "not a guarantee" in lines[-1]
    assert any(ln.startswith("BUY  <b>CUPID</b>  above ₹") and "· stop ₹" in ln and "· first target ₹" in ln
               for ln in lines)
    assert "Q2 profit +86% YoY, revenue +38% · gap +4.2%" in msg
    assert "AVOID  <b>WEAK</b>  weak news" in msg and "SELL" not in msg
    assert "HOT" not in msg and "NOISE" not in msg                    # extended gap -> WATCH, noise -> none
    assert state[CA.PREOPEN_KEY] == "2026-11-16"
    kv = store.kv[("_system", "catalyst_picks:2026-11-16")]
    acts = {r["symbol"]: r["action"] for r in kv["reads"]}
    assert acts["CUPID"] == "BUY" and acts["HOT"] == "WATCH" and acts["WEAK"] == "SELL"
    assert all(k[1] != "verdict_log" for k in store.kv)
    # dedupe: second run sends nothing
    assert CA.check_catalyst_preopen(state, "2026-11-16", now=MON_PRE) == 0 and len(sent) == 1


def test_preopen_results_filed_merge_and_nothing_to_send(monkeypatch, store, sent):
    res = [{"symbol": "CUPID", "when": FRI_EVE, "period_end": dt.date(2026, 9, 30), "consolidated": True}]
    _wire(monkeypatch, anns=[], results=res, preopen={}, quarters={"CUPID": GOOD_Q})
    state: dict = {}
    assert CA.check_catalyst_preopen(state, "2026-11-16", now=MON_PRE) == 0   # no pre-open gap -> WATCH only
    assert sent == [] and CA.PREOPEN_KEY not in state
    reads = store.kv[("_system", "catalyst_picks:2026-11-16")]["reads"]
    assert reads[0]["symbol"] == "CUPID" and reads[0]["action"] == "WATCH"
    _wire(monkeypatch, anns=[], results=[])
    assert CA.check_catalyst_preopen({}, "2026-11-16", now=MON_PRE) == 0


def test_preopen_never_raises(monkeypatch, store, sent):
    monkeypatch.setattr(N, "fetch_announcements", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
    assert CA.check_catalyst_preopen({}, "2026-11-16", now=MON_PRE) == 0
    _wire(monkeypatch, anns=[{"symbol": "X"}, "junk", None, {"symbol": "Y", "when": "bad", "category": "Buyback"}])
    monkeypatch.setattr(CA, "_daily", lambda sym, period="6mo": "not a frame")
    assert CA.check_catalyst_preopen({}, "2026-11-16", now=MON_PRE) == 0 and sent == []


# ── alerts: live ────────────────────────────────────────────────────────────

LIVE_NOW = dt.datetime(2026, 11, 16, 11, 0, tzinfo=IST)


def _wire_live(monkeypatch, anns, quotes):
    _wire(monkeypatch, anns=anns, frames={})
    monkeypatch.setattr(ca, "_quote", lambda sym: quotes.get(sym))
    monkeypatch.setattr(ca, "_pick_session", lambda sym, today: None)


def test_live_alert_dedupe_and_cap(monkeypatch, store, sent):
    last = float(_frame()["Close"].iloc[-1])
    when = LIVE_NOW - dt.timedelta(minutes=20)
    anns = [_ann(s, "Updates", "Receipt of order worth Rs 900 crore", when) for s in ("AAA", "BBB", "CCC")]
    q = {"price": last * 1.03, "prev_close": last, "chg_pct": 3.0, "volume": 3_000_000}
    _wire_live(monkeypatch, anns, {"AAA": q, "BBB": q, "CCC": {**q, "chg_pct": -0.5}})
    state = {f"catalyst_live_X{i}": "2026-11-16" for i in range(4)}
    assert CA.check_catalyst_live(state, "2026-11-16", now=LIVE_NOW) == 1
    msg = sent[0]
    assert "Fresh catalyst" in msg and "BUY  <b>AAA</b>" in msg and "BUY  <b>BBB</b>" in msg and "CCC" not in msg
    assert "today +3.0%" in msg and len(msg.split("\n")) <= 14
    assert state["catalyst_live_AAA"] == "2026-11-16"
    assert CA.check_catalyst_live(state, "2026-11-16", now=LIVE_NOW) == 0          # cap 6 reached
    st2 = {"catalyst_live_AAA": "2026-11-16"}
    assert CA.check_catalyst_live(st2, "2026-11-16", now=LIVE_NOW) == 1
    assert "AAA" not in sent[-1] and "BBB" in sent[-1]                               # per-symbol dedupe


def test_live_room_limits_batch(monkeypatch, store, sent):
    last = float(_frame()["Close"].iloc[-1])
    when = LIVE_NOW - dt.timedelta(minutes=10)
    anns = [_ann(s, "Updates", "Bagged order", when) for s in ("A1", "A2", "A3")]
    q = {"price": last * 1.03, "prev_close": last, "chg_pct": 3.0}
    _wire_live(monkeypatch, anns, {s: q for s in ("A1", "A2", "A3")})
    state = {f"catalyst_live_X{i}": "2026-11-16" for i in range(5)}
    assert CA.check_catalyst_live(state, "2026-11-16", now=LIVE_NOW) == 1
    assert sum(k.startswith("catalyst_live_A") for k in state) == 1


def test_live_no_quote_or_no_filings(monkeypatch, store, sent):
    _wire_live(monkeypatch, [_ann("AAA", "Updates", "Bagged order", LIVE_NOW)], {})
    assert CA.check_catalyst_live({}, "2026-11-16", now=LIVE_NOW) == 0
    _wire_live(monkeypatch, [], {})
    assert CA.check_catalyst_live({}, "2026-11-16", now=LIVE_NOW) == 0 and sent == []
    monkeypatch.setattr(N, "fetch_announcements", lambda *a, **k: 1 / 0)
    assert CA.check_catalyst_live({}, "2026-11-16", now=LIVE_NOW) == 0


# ── alerts: why moved ───────────────────────────────────────────────────────

CLOSE_NOW = dt.datetime(2026, 11, 13, 16, 0, tzinfo=IST)


def _mover_frame(ret_pct, vol_mult=4.0):
    df = _frame()
    prev = float(df["Close"].iloc[-2])
    c = prev * (1 + ret_pct / 100)
    df.iloc[-1] = [prev, max(c, prev) * 1.001, min(c, prev) * 0.999, c, 3_000_000 * vol_mult]
    return df


def test_why_moved(monkeypatch, store, sent):
    gen = dt.datetime.now(dt.timezone.utc).isoformat()
    data = {f"{s}.NS": {"ticker": f"{s}.NS", "return_1d": r, "sector": sec, "price": 100}
            for s, r, sec in [("CUPID", 12.0, "FMCG"), ("RAIL", 7.0, "Infra"), ("MYST", 6.0, "Pharma"),
                              ("FALL", -8.0, "IT"), ("IT2", -3.0, "IT"), ("IT3", -2.5, "IT"),
                              ("THIN", 15.0, "Pharma"), ("FLAT", 0.1, "FMCG")]}
    store.kv[("_system", "all_scored_snapshot")] = {"data": data, "generated_at": gen}
    store.kv[("_system", "top_picks_snapshot")] = {"data": {"buys": [{"ticker": "RAIL.NS"}]}, "generated_at": gen}
    anns = [_ann("CUPID", "Financial Results", "Unaudited financial results", dt.datetime(2026, 11, 12, 18, 0,
                                                                                         tzinfo=IST)),
            _ann("RAIL", "Updates", "Bagged order worth Rs 300 crore from Indian Railways")]
    frames = {s: _mover_frame(r) for s, r in [("CUPID", 12.0), ("RAIL", 7.0), ("MYST", 6.0), ("FALL", -8.0),
                                             ("IT2", -3.0), ("IT3", -2.5), ("FLAT", 0.1)]}
    frames["THIN"] = _frame(vol=10_000)
    _wire(monkeypatch, anns=anns, quarters={"CUPID": GOOD_Q}, frames=frames)
    state: dict = {}
    assert CA.check_why_moved(state, "2026-11-13", now=CLOSE_NOW) == 2
    gain, loss = sent
    assert "top gainers" in gain and "top losers" in loss
    assert "▲ <b>CUPID</b> +12.0% · on your list: no" in gain
    assert "Q2 profit ₹41 cr vs ₹22 cr a year ago, +86%; revenue +38%" in gain
    assert "▲ <b>RAIL</b> +7.0% · on your list: yes" in gain and "order win" in gain
    assert C.NO_EVIDENCE in gain                                        # MYST
    assert "THIN" not in gain                                           # illiquid
    assert "whole sector -3.0%" in loss and "4.0x normal volume" in loss
    assert all(len(m.split("\n")) <= 14 for m in sent)
    assert state[CA.WHY_KEY] == "2026-11-13"
    assert CA.check_why_moved(state, "2026-11-13", now=CLOSE_NOW) == 0


def test_why_moved_no_or_stale_snapshot(monkeypatch, store, sent):
    _wire(monkeypatch, anns=[])
    assert CA.check_why_moved({}, "2026-11-13", now=CLOSE_NOW) == 0
    store.kv[("_system", "all_scored_snapshot")] = {"data": {"X": {"ticker": "X", "return_1d": 5}},
                                                    "generated_at": "2026-01-01T00:00:00+00:00"}
    assert CA.check_why_moved({}, "2026-11-13", now=CLOSE_NOW) == 0
    store.kv[("_system", "all_scored_snapshot")] = {"data": "garbage", "generated_at": None}
    assert CA.check_why_moved({}, "2026-11-13", now=CLOSE_NOW) == 0 and sent == []


def test_flagged_symbols(store):
    yday = "2026-11-12T10:30:00+00:00"
    store.kv[("_system", "tomorrow_watchlist_snapshot")] = {
        "data": {"breakout_candidates": [{"ticker": "BRK.NS"}], "reversal_watch": [{"ticker": "REV.NS"}]},
        "generated_at": yday}
    store.kv[("_system", "morning_digest_picks")] = {"date": "2026-11-13", "buys": [{"ticker": "MORN.NS"}]}
    store.kv[("_system", "catalyst_picks:2026-11-13")] = {"reads": [{"symbol": "CAT", "action": "BUY"},
                                                                   {"symbol": "W", "action": "WATCH"}]}
    assert CA.flagged_symbols("2026-11-13") == {"BRK", "REV", "MORN", "CAT"}
    store.kv[("_system", "tomorrow_watchlist_snapshot")]["generated_at"] = "2026-11-13T10:30:00+00:00"
    assert "BRK" not in CA.flagged_symbols("2026-11-13")              # made after today's session


def test_persist_reads_merges(store):
    r1 = C.CatalystRead("AAA", "BUY", 70, "intraday", ["x"], 10, 9, 12, 2.0)
    r2 = C.CatalystRead("AAA", "WATCH", 30, "intraday")
    assert CA.persist_reads("2026-11-16", [r1], "preopen", MON_PRE)
    assert CA.persist_reads("2026-11-16", [r2], "preopen", MON_PRE)
    assert CA.persist_reads("2026-11-16", [r1], "live", MON_PRE)
    rows = store.kv[("_system", "catalyst_picks:2026-11-16")]["reads"]
    assert [(r["mode"], r["action"]) for r in rows] == [("preopen", "WATCH"), ("live", "BUY")]
    assert C.grade_picks(rows, {})["summary"]["n"] == 1


# ── canary probes ───────────────────────────────────────────────────────────

def test_canary_catalyst_probes(monkeypatch):
    import scripts.provider_canary as pc
    assert pc.check_rows([], pc.ANNOUNCEMENT_KEYS).startswith("only 0")
    assert "missing keys" in pc.check_rows([{"symbol": "X"}], pc.ANNOUNCEMENT_KEYS)
    assert pc.check_rows("x", ()) == "expected list, got str"
    ann = {k: "x" for k in pc.ANNOUNCEMENT_KEYS}
    monkeypatch.setattr(N, "fetch_announcements", lambda s, u=None: [dict(ann, source="nse_api")])
    monkeypatch.setattr(N, "fetch_results_filed", lambda s: [])
    monkeypatch.setattr(N, "fetch_quarterly_figures", lambda s: GOOD_Q)          # only 3 quarters
    monkeypatch.setattr(N, "fetch_preopen", lambda: {f"S{i}": dict.fromkeys(pc.PREOPEN_KEYS, 1) for i in range(60)})
    res = {r.provider: r for r in pc.run_probes(pc.CATALYST_PROBES)}
    assert res["nse_announcements"].status == pc.OK
    assert res["nse_results_filed"].status == pc.DEGRADED
    assert res["nse_quarterly"].status == pc.FAILED and ">= 4" in res["nse_quarterly"].check
    assert res["nse_preopen"].status == pc.OK
    assert pc.exit_code(res.values()) == 0 and not any(r.scoring for r in res.values())
