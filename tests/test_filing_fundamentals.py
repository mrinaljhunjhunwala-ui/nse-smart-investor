"""Official-filing fundamentals: XBRL parser, stored-filing provider, NSE picker. Offline."""
from pathlib import Path

import pytest

from analysis.fundamentals import xbrl_filing as xf
from analysis.fundamentals.providers import filing_fundamentals as ff

_XML = (Path(__file__).parent / "fixtures" / "sample_indas_aoc4.xml").read_bytes()


def test_parse_two_years_ignores_segment_facts():
    p = xf.parse_xbrl(_XML)
    assert p["company_name"] == "SAMPLE INDUSTRIES LIMITED" and p["cin"].startswith("L17110")
    assert p["consolidated"] is True
    assert [x["period_end"] for x in p["periods"]] == ["2026-03-31", "2025-03-31"]
    cur = p["periods"][0]
    assert cur["income"]["revenue"] == 1_000_000_000          # not the 400m segment fact
    assert cur["income"]["net_income"] == 110_000_000 and cur["income"]["eps_basic"] == 11.0
    assert cur["balance"]["total_assets"] == 2_000_000_000 and cur["balance"]["total_equity"] == 1e9
    assert cur["cash"]["capital_expenditure"] == -60_000_000
    assert p["periods"][1]["income"] == {"revenue": 800_000_000, "net_income": 90_000_000}


def test_parse_rejects_non_xml():
    with pytest.raises(ValueError):
        xf.parse_xbrl(b"%PDF-1.7 not xml")


def _store(monkeypatch):
    import trade_store
    kv = {}
    monkeypatch.setattr(trade_store, "kv_get", lambda k, d=None, user_id=None: kv.get(k, d))
    monkeypatch.setattr(trade_store, "kv_set", lambda k, v, user_id=None: kv.__setitem__(k, v) or True)
    return kv


def test_save_merges_years_and_provider_normalises(monkeypatch):
    kv = _store(monkeypatch)
    parsed = xf.parse_xbrl(_XML)
    older = {"periods": [{"period_end": "2024-03-31", "income": {"revenue": 7e8}, "balance": {}, "cash": {}}]}
    ff.save_filing("roc", "SAMPLE.NS", older, "aoc4_fy24.xml")
    rec = ff.save_filing("roc", "SAMPLE", parsed, "aoc4_fy26.xml")
    assert list(kv) == ["filing_fund:roc:SAMPLE"]
    assert [p["period_end"] for p in rec["periods"]] == ["2026-03-31", "2025-03-31", "2024-03-31"]

    prov = ff.FilingFundamentalProvider("roc")
    inc = prov.get_income_statement("SAMPLE.NS")
    assert len(inc) == 3 and inc[0].period.fiscal_year == 2026
    assert inc[0].operating_income == 170_000_000 and inc[0].ebitda == 200_000_000
    bal = prov.get_balance_sheet("SAMPLE")[0]
    assert bal.total_debt == 250_000_000
    cfl = prov.get_cash_flow("SAMPLE")[0]
    assert cfl.capital_expenditure == 60_000_000 and cfl.free_cash_flow == 100_000_000
    r = prov.get_ratios("SAMPLE")
    assert round(r.roe, 3) == 0.11 and round(r.debt_to_equity, 2) == 0.25 and r.current_ratio == 1.5
    assert prov.get_income_statement("SAMPLE", period="quarterly") == []


def test_save_refuses_empty_and_unknown_source(monkeypatch):
    _store(monkeypatch)
    with pytest.raises(ValueError):
        ff.save_filing("roc", "X", {"periods": []})
    with pytest.raises(ValueError):
        ff.save_filing("bse", "X", xf.parse_xbrl(_XML))


def test_service_for_source_filing_first_then_fill(monkeypatch):
    from analysis.fundamentals import service as svc
    from analysis.fundamentals.models import IncomeStatement, RatioSnapshot
    from analysis.fundamentals.provider import FundamentalProvider
    _store(monkeypatch)
    ff.save_filing("roc", "SAMPLE", xf.parse_xbrl(_XML))

    class _Fill(FundamentalProvider):
        name = "YahooFinance"
        def get_income_statement(self, s, period="annual", limit=10):
            from analysis.fundamentals.models import FiscalPeriod
            import datetime as dt
            return [IncomeStatement(period=FiscalPeriod(period_end=dt.date(2026, 3, 31)), revenue=9e8,
                                    cost_of_revenue=5e8)]
        def get_balance_sheet(self, s, period="annual", limit=10): return []
        def get_cash_flow(self, s, period="annual", limit=10): return []
        def get_ratios(self, s): return RatioSnapshot(pe=25.0)

    svc.forget_source()
    s = svc.FundamentalsService(providers=[ff.FilingFundamentalProvider("roc"), _Fill()])
    cf = s.get_fundamentals("SAMPLE")
    assert cf.provider_name.startswith("ROC filing (MCA upload)")
    li = cf.latest_income()
    assert li.revenue == 1e9 and li.cost_of_revenue == 5e8      # filing wins, Yahoo fills gaps
    assert cf.ratios.pe == 25.0 and round(cf.ratios.roe, 2) == 0.11
    assert svc.service_for_source("auto") is svc.default_service()


def test_pick_latest_annual_prefers_newest_audited_consolidated():
    from data.nse_filings_xbrl import pick_latest_annual
    rows = [
        {"toDate": "31-Mar-2025", "consolidated": "Consolidated", "audited": "Audited",
         "xbrl": "https://nsearchives.nseindia.com/a/FY25C.xml"},
        {"toDate": "31-Mar-2026", "consolidated": "Non-Consolidated", "audited": "Audited",
         "xbrl": "https://nsearchives.nseindia.com/a/FY26S.xml"},
        {"toDate": "31-Mar-2026", "consolidated": "Consolidated", "audited": "Audited",
         "xbrl": "https://nsearchives.nseindia.com/a/FY26C.xml"},
        {"toDate": "31-Mar-2026", "consolidated": "Consolidated", "audited": "Audited", "xbrl": "-"},
    ]
    assert pick_latest_annual(rows)["xbrl"].endswith("FY26C.xml")
    assert pick_latest_annual([{"toDate": "31-Mar-2026", "xbrl": "-"}]) is None


def test_fetch_exchange_filing_end_to_end_offline(monkeypatch):
    import data.nse_corp_info as nci
    from data import nse_filings_xbrl as nfx
    kv = _store(monkeypatch)

    class _Resp:
        def __init__(self, payload=None, content=b""):
            self._p, self.content = payload, content
        def raise_for_status(self): pass
        def json(self): return self._p

    class _Sess:
        def get(self, url, params=None, timeout=None):
            if "corporates-financial-results" in url:
                return _Resp([{"toDate": "31-Mar-2026", "consolidated": "Consolidated",
                               "audited": "Audited", "xbrl": "https://nsearchives.nseindia.com/x/S.xml"}])
            if url.endswith("S.xml"):
                return _Resp(content=_XML)
            return _Resp()
    monkeypatch.setattr(nci, "_ensure_session", lambda: _Sess())
    res = nfx.fetch_exchange_filing("SAMPLE.NS")
    assert res["ok"] and "2026-03-31" in res["message"] and "filing_fund:exchange:SAMPLE" in kv

    class _Blocked(_Sess):
        def get(self, url, params=None, timeout=None):
            raise ConnectionError("blocked")
    monkeypatch.setattr(nci, "_ensure_session", lambda: _Blocked())
    res = nfx.fetch_exchange_filing("SAMPLE")
    assert not res["ok"] and "upload the filing" in res["message"]


def test_picker_renders_each_source(monkeypatch):
    from streamlit.testing.v1 import AppTest
    kv = _store(monkeypatch)
    ff.save_filing("roc", "SAMPLE", xf.parse_xbrl(_XML), "aoc4.xml")

    def _app():
        import streamlit as st
        from dashboard.shared.fund_source_ui import render_fund_source_picker
        st.write("SRC=" + render_fund_source_picker("SAMPLE.NS"))

    at = AppTest.from_function(_app, default_timeout=30).run()
    assert not at.exception and "SRC=auto" in at.markdown[-1].value
    at.radio(key="fund_src_SAMPLE.NS").set_value("roc").run()
    assert not at.exception and "SRC=roc" in at.markdown[-1].value
    assert any("2 year(s)" in c.value and "consolidated" in c.value for c in at.caption)
    at.radio(key="fund_src_SAMPLE.NS").set_value("exchange").run()
    assert not at.exception and any("No filing saved" in i.value for i in at.info)
    assert at.button(key="fund_nse_SAMPLE.NS")
    assert kv
