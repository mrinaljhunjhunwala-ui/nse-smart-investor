"""scripts/provider_canary.py — offline: every provider probe is mocked."""
from __future__ import annotations

import datetime as dt
import importlib

import pandas as pd
import pytest

pc = importlib.import_module("scripts.provider_canary")


def _ok(name):
    return lambda: pc.ProbeResult(name, pc.OK, "fine")


def _all_ok_probes():
    return [(name, _ok(name), scoring) for name, _fn, scoring in pc.PROBES]


def test_probe_list_covers_every_provider_and_scoring_flags():
    names = [n for n, _f, _s in pc.PROBES]
    assert names == ["yahoo_chart", "nse_all_indices", "nse_corp_info", "google_news",
                     "nse_rss", "screener", "nse_bhavcopy", "india_vix"]
    assert {n for n, _f, s in pc.PROBES if s} == {"yahoo_chart", "nse_bhavcopy", "india_vix"}


def test_all_ok_exit_zero_and_green_one_liner():
    res = pc.run_probes(_all_ok_probes())
    assert pc.exit_code(res) == 0
    msg = pc.format_telegram(res, today=dt.date(2026, 11, 15))
    assert msg.startswith("🟢") and "all 8 providers ok" in msg
    assert "\n" not in msg
    table = pc.format_table(res)
    assert "yahoo_chart" in table and "FAILED" not in table


def test_scoring_provider_failed_exits_one():
    probes = _all_ok_probes()
    probes[0] = ("yahoo_chart", lambda: (_ for _ in ()).throw(ConnectionError("blocked")), True)
    res = pc.run_probes(probes)
    yahoo = res[0]
    assert yahoo.status == pc.FAILED and yahoo.check == "probe raised"
    assert "ConnectionError: blocked" in yahoo.reason
    assert pc.exit_code(res) == 1


def test_non_scoring_failure_and_degraded_exit_zero_but_red():
    probes = _all_ok_probes()
    probes[2] = ("nse_corp_info", lambda: pc.ProbeResult(
        "nse_corp_info", pc.FAILED, "HTTP 404 from NSE API", "HTTP 200 + JSON object"), False)
    probes[7] = ("india_vix", lambda: pc.ProbeResult(
        "india_vix", pc.DEGRADED, "14.20 from Yahoo (NSE tier down)", "tier 1 answered"), True)
    res = pc.run_probes(probes)
    assert pc.exit_code(res) == 0
    msg = pc.format_telegram(res, today=dt.date(2026, 11, 15))
    assert msg.startswith("🔴") and "1 FAILED, 1 degraded of 8" in msg
    assert "FAILED   nse_corp_info: HTTP 404 from NSE API [HTTP 200 + JSON object]" in msg
    assert "degraded india_vix" in msg
    assert "yahoo_chart" not in msg                    # ok rows are left out
    assert "Scoring inputs down" not in msg            # degraded VIX is not "down"


def test_telegram_text_names_scoring_failures_escaped():
    probes = _all_ok_probes()
    probes[0] = ("yahoo_chart", lambda: pc.ProbeResult(
        "yahoo_chart", pc.FAILED, "missing columns: ['Volume'] `x`", "check_yahoo_frame"), True)
    msg = pc.format_telegram(pc.run_probes(probes), today=dt.date(2026, 11, 15))
    assert r"Scoring inputs down: yahoo\_chart" in msg     # Markdown-escaped outside the block
    assert msg.count("```") == 2 and "`x`" not in msg      # no stray backticks inside


def test_send_telegram_never_raises():
    class _Boom:
        def send_text(self, text):
            raise RuntimeError("telegram down")
    assert pc.send_telegram("hi", alerter_factory=_Boom) is False

    class _Ok:
        def send_text(self, text):
            return True
    assert pc.send_telegram("hi", alerter_factory=_Ok) is True


def test_main_sends_and_returns_code(monkeypatch, capsys):
    probes = _all_ok_probes()
    probes[6] = ("nse_bhavcopy", lambda: pc.ProbeResult(
        "nse_bhavcopy", pc.FAILED, "schema drift", "check_bhavcopy_text"), True)
    monkeypatch.setattr(pc, "PROBES", probes)
    sent = []
    monkeypatch.setattr(pc, "send_telegram", lambda text: sent.append(text) or True)
    assert pc.main(["--telegram"]) == 1
    assert sent and sent[0].startswith("🔴")
    assert "nse_bhavcopy" in capsys.readouterr().out


# ── shared schema checks (also used by tests/test_provenance_*) ─────────────

def test_check_yahoo_frame():
    good = pd.DataFrame({"Open": [1.0], "High": [1.0], "Low": [1.0], "Close": [1.0], "Volume": [5]})
    assert pc.check_yahoo_frame(good) is None
    assert "missing columns" in pc.check_yahoo_frame(good.drop(columns=["Volume"]))
    assert "empty" in pc.check_yahoo_frame(pd.DataFrame())


def test_check_vix_corp_news_screener():
    assert pc.check_vix_row({"vix": 14.0, "regime": "normal", "allow_buy": True}) is None
    assert "missing" in pc.check_vix_row({"vix": None, "regime": "unknown", "allow_buy": False})
    assert pc.check_corp_info({"corporate_actions": {}}) is None
    assert "none of the expected" in pc.check_corp_info({"foo": 1})
    assert pc.check_news_items([{"title": "t", "link": "l"}]) is None
    assert "zero items" in pc.check_news_items([])
    top = {"Market Cap": 1.0, "Current Price": 2.0, "Book Value": 3.0}
    assert pc.check_screener_top(top) is None
    assert "None" in pc.check_screener_top({**top, "Book Value": None})


def test_probe_vix_statuses(monkeypatch):
    import utils.vix as V
    monkeypatch.setattr(V, "fetch_vix_tiered", lambda: {
        "vix": 14.0, "regime": "normal", "allow_buy": True, "source": "NSE", "attempts": []})
    assert pc._probe_vix().status == pc.OK
    monkeypatch.setattr(V, "fetch_vix_tiered", lambda: {
        "vix": 14.0, "regime": "normal", "allow_buy": True, "source": "Yahoo", "attempts": []})
    assert pc._probe_vix().status == pc.DEGRADED
    monkeypatch.setattr(V, "fetch_vix_tiered", lambda: {
        "vix": None, "regime": "unknown", "allow_buy": False, "source": None,
        "attempts": [{"source": "NSE", "ok": False, "reason": "x"}]})
    r = pc._probe_vix()
    assert r.status == pc.FAILED and r.check == "check_vix_row"


@pytest.mark.parametrize("payload,status", [
    ({"data": [{"index": "INDIA VIX", "last": 13.1}]}, "ok"),
    ({"data": [{"index": "NIFTY 50", "last": 1}]}, "FAILED"),
])
def test_probe_nse_all_indices(monkeypatch, payload, status):
    import utils.vix as V
    monkeypatch.setattr(V, "_nse_all_indices_payload", lambda timeout=10: payload)
    assert pc._probe_nse_all_indices().status == status


def test_degraded_only_is_amber_not_red():
    res = [pc.ProbeResult("yahoo_chart", pc.OK, "5 bars", ""),
           pc.ProbeResult("nse_quarterly", pc.DEGRADED, "8 quarters from screener", "NSE tier")]
    msg = pc.format_telegram(res)
    assert msg.startswith("🟡") and "nothing failed" in msg and "1 of 2 sources on a backup route" in msg
