"""Auto fundamentals cascade, once-a-day NSE filing fetch, field provenance and
the long-lens data gate. Offline: every provider and the fetcher are fakes."""
import datetime as dt
import time

import pytest

from analysis.final_verdict import INSUFFICIENT_DATA, VERDICTS, combine
from analysis.fundamentals import service as svc
from analysis.fundamentals.models import (
    BalanceSheet, FiscalPeriod, IncomeStatement, RatioSnapshot, missing_core_fields,
    sources_caption,
)
from analysis.fundamentals.provider import FundamentalProvider
from analysis.fundamentals.providers import filing_fundamentals as ff

_P = FiscalPeriod(period_end=dt.date(2026, 3, 31), fiscal_year=2026)


class _Fake(FundamentalProvider):
    def __init__(self, name, inc=None, bal=None, ratios=None):
        self.name, self._inc, self._bal, self._r = name, inc or {}, bal or {}, ratios
        self.calls = 0

    def get_income_statement(self, s, period="annual", limit=10):
        self.calls += 1
        return [IncomeStatement(period=_P, **self._inc)] if self._inc else []

    def get_balance_sheet(self, s, period="annual", limit=10):
        return [BalanceSheet(period=_P, **self._bal)] if self._bal else []

    def get_cash_flow(self, s, period="annual", limit=10):
        return []

    def get_ratios(self, s):
        return self._r or RatioSnapshot()


def _filing_rec(equity=5e9, revenue=None, net_income=None):
    inc = {k: v for k, v in (("revenue", revenue), ("net_income", net_income)) if v is not None}
    return {"symbol": "ACME", "source": "exchange", "company_name": "ACME LTD",
            "periods": [{"period_end": "2026-03-31", "income": inc,
                         "balance": {"total_equity": equity}, "cash": {}}]}


@pytest.fixture
def kv(monkeypatch):
    import trade_store
    store = {}
    monkeypatch.setattr(trade_store, "kv_get", lambda k, d=None, user_id=None: store.get(k, d))
    monkeypatch.setattr(trade_store, "kv_set",
                        lambda k, v, user_id=None: store.__setitem__(k, v) or True)
    svc.reset_auto_fetch_state()
    yield store
    svc.reset_auto_fetch_state()


# ── cascade order + provenance ───────────────────────────────────────────────

def test_auto_cascade_order_is_yahoo_screener_exchange_roc():
    names = [p.name for p in svc.auto_providers()]
    assert names == ["YahooFinance", "Screener.in",
                     "Exchange filing (NSE XBRL)", "ROC filing (MCA upload)"]


def test_stored_filing_fills_only_what_yahoo_and_screener_left(kv):
    kv["filing_fund:exchange:ACME"] = _filing_rec(equity=5e9, revenue=1.0)  # revenue loses
    kv["filing_fund:roc:ACME"] = {"periods": [{"period_end": "2026-03-31", "income": {},
                                               "balance": {"total_debt": 1.0, "total_equity": 9.0},
                                               "cash": {}}]}
    yahoo = _Fake("YahooFinance", inc={"revenue": 4e10}, ratios=RatioSnapshot(pe=20.0))
    scr = _Fake("Screener.in", inc={"net_income": 3e9})
    s = svc.FundamentalsService(providers=[yahoo, scr, ff.FilingFundamentalProvider("exchange"),
                                           ff.FilingFundamentalProvider("roc")])
    cf = s.get_fundamentals("ACME.NS")
    li, lb = cf.latest_income(), cf.latest_balance()
    assert li.revenue == 4e10 and li.net_income == 3e9 and lb.total_equity == 5e9
    src = cf.field_sources()
    assert src["income.revenue"] == "YahooFinance"
    assert src["income.net_income"] == "Screener.in"
    assert src["balance.total_equity"] == "Exchange filing (NSE XBRL)"
    assert src["ratios.pe"] == "YahooFinance" and src["ratios.pb"] is None
    assert missing_core_fields(cf) == []
    cap = sources_caption(cf)
    assert cap.startswith("Sources: revenue — Yahoo · net profit — Screener")
    assert "equity — NSE filing" in cap and "P/E — Yahoo" in cap
    assert "P/B — not found in any source" in cap and "EPS — not found in any source" in cap


def test_filing_record_read_once_per_assembly(kv, monkeypatch):
    reads = []
    prov = ff.FilingFundamentalProvider("exchange", loader=lambda src, sym: reads.append(sym)
                                        or _filing_rec())
    svc.FundamentalsService(providers=[prov]).get_fundamentals("ACME")
    assert reads == ["ACME"]


def test_missing_core_fields_names_each_gap():
    assert missing_core_fields(None) == ["revenue", "net profit", "equity"]
    s = svc.FundamentalsService(providers=[_Fake("YahooFinance", inc={"revenue": 1e9})])
    cf = s.get_fundamentals("X")
    assert missing_core_fields(cf) == ["net profit", "equity"]
    empty = svc.FundamentalsService(providers=[]).get_fundamentals("Y")
    assert sources_caption(empty).count("not found in any source") == 7


# ── once-a-day auto fetch ────────────────────────────────────────────────────

def _auto_service(kv, fetcher):
    yahoo = _Fake("YahooFinance", inc={"revenue": 4e10, "net_income": 3e9})
    return yahoo, svc.FundamentalsService(
        providers=[yahoo, _Fake("Screener.in"), ff.FilingFundamentalProvider("exchange")],
        auto_fetcher=fetcher)


def test_auto_fetch_fills_equity_and_runs_once_per_day(kv, monkeypatch):
    monkeypatch.setenv("NSE_AUTO_FILING_FETCH", "1")
    calls = []

    def fetcher(sym):
        calls.append(sym)
        kv[f"filing_fund:exchange:{sym}"] = _filing_rec(equity=7e9)
        return {"ok": True, "reason": "saved"}

    yahoo, s = _auto_service(kv, fetcher)
    cf = s.get_fundamentals("ACME.NS")
    assert calls == ["ACME"]
    assert cf.latest_balance().total_equity == 7e9
    assert cf.field_sources()["balance.total_equity"] == "Exchange filing (NSE XBRL)"
    assert yahoo.calls == 1                       # Yahoo result reused, not re-fetched
    assert kv["filing_autofetch:ACME"] == dt.date.today().isoformat()

    # Same day, cache dropped (or another process): no second attempt.
    kv.pop("filing_fund:exchange:ACME")
    s.cache.clear()
    s.get_fundamentals("ACME.NS")
    svc.reset_auto_fetch_state()                  # new process: KV memo still says "today"
    _, s2 = _auto_service(kv, fetcher)
    s2.get_fundamentals("ACME")
    assert calls == ["ACME"]


def test_auto_fetch_opt_out(kv, monkeypatch):
    monkeypatch.setenv("NSE_AUTO_FILING_FETCH", "0")
    calls = []
    _, s = _auto_service(kv, lambda sym: calls.append(sym) or {"ok": True})
    cf = s.get_fundamentals("ACME")
    assert calls == [] and missing_core_fields(cf) == ["equity"]


def test_auto_fetch_skipped_when_core_fields_present(kv, monkeypatch):
    monkeypatch.setenv("NSE_AUTO_FILING_FETCH", "1")
    calls = []
    s = svc.FundamentalsService(
        providers=[_Fake("YahooFinance", inc={"revenue": 1.0, "net_income": 1.0},
                         bal={"total_equity": 1.0}), ff.FilingFundamentalProvider("exchange")],
        auto_fetcher=lambda sym: calls.append(sym) or {"ok": True})
    s.get_fundamentals("ACME")
    assert calls == []


def test_auto_fetch_never_raises_and_breaker_stops_retries(kv, monkeypatch):
    monkeypatch.setenv("NSE_AUTO_FILING_FETCH", "1")

    def boom(sym):
        raise RuntimeError("NSE exploded")
    _, s = _auto_service(kv, boom)
    assert missing_core_fields(s.get_fundamentals("AAA")) == ["equity"]   # no exception

    calls = []
    _, s = _auto_service(kv, lambda sym: calls.append(sym) or {"ok": False, "reason": "transport"})
    s.get_fundamentals("BBB")
    s.get_fundamentals("CCC")                      # breaker open: not attempted
    assert calls == ["BBB"]


def test_auto_fetch_times_out_quickly(kv, monkeypatch):
    monkeypatch.setenv("NSE_AUTO_FILING_FETCH", "1")
    monkeypatch.setattr(svc, "AUTO_FETCH_TIMEOUT_S", 0.2)
    _, s = _auto_service(kv, lambda sym: time.sleep(2) or {"ok": True})
    t0 = time.time()
    cf = s.get_fundamentals("SLOW")
    assert time.time() - t0 < 1.5 and missing_core_fields(cf) == ["equity"]


def test_saving_a_filing_drops_the_cached_auto_merge(kv, monkeypatch):
    monkeypatch.setattr(svc, "_DEFAULT", svc.FundamentalsService(
        providers=[_Fake("YahooFinance", inc={"revenue": 1.0, "net_income": 1.0}),
                   ff.FilingFundamentalProvider("exchange")]))
    d = svc.default_service()
    assert d.get_fundamentals("ACME.NS").latest_balance() is None
    ff.save_filing("exchange", "ACME", _filing_rec(equity=2e9))
    assert d.get_fundamentals("ACME.NS").latest_balance().total_equity == 2e9


def test_service_for_source_still_filing_first(kv):
    kv["filing_fund:roc:ACME"] = _filing_rec(equity=1.0, revenue=5.0)
    names = [p.name for p in svc.service_for_source("roc").providers]
    assert names == ["ROC filing (MCA upload)", "YahooFinance", "Screener.in"]
    assert svc.service_for_source("auto") is svc.default_service()


# ── long-lens data gate ──────────────────────────────────────────────────────

_TECH = dict(composite_score=70, composite_action="BUY", tqs=55)


def test_long_lens_says_not_enough_data_when_metric_missing():
    v = combine(**_TECH, valuation_posture="INSUFFICIENT_EVIDENCE",
                valuation_guard="H3-missing-metric", horizon="long")
    assert v.verdict == INSUFFICIENT_DATA and v.verdict not in VERDICTS
    assert v.primary_reason.startswith("Not enough fundamental data for a long-term read")
    assert v.confidence == "low" and v.conviction == 0
    for hz in ("short", "medium"):
        assert combine(**_TECH, valuation_posture="INSUFFICIENT_EVIDENCE",
                       valuation_guard="H3-missing-metric", horizon=hz).verdict in VERDICTS


def test_long_lens_gate_when_no_fundamentals_found():
    v = combine(**_TECH, fundamentals_missing=True, horizon="long")
    assert v.verdict == INSUFFICIENT_DATA and "in any source" in v.primary_reason
    # Callers that never fetch fundamentals are unchanged.
    assert combine(**_TECH, horizon="long").verdict in VERDICTS


def test_long_lens_keeps_read_when_quality_score_available():
    v = combine(**_TECH, quality_score=72, valuation_posture="INSUFFICIENT_EVIDENCE",
                valuation_guard="H3-missing-metric", horizon="long")
    assert v.verdict in VERDICTS


def test_red_flag_veto_beats_the_data_gate():
    v = combine(**_TECH, fundamentals_missing=True, horizon="long",
                quality_flags={"severity": "red", "top_flag": "SEBI order"})
    assert v.verdict == "AVOID"


def test_not_applicable_refusal_keeps_read_and_explains():
    kw = dict(**_TECH, valuation_posture="INSUFFICIENT_EVIDENCE",
              valuation_guard="H2-negative-equity")
    before = combine(**kw, horizon="medium")
    v = combine(**kw, horizon="long")
    assert v.verdict in VERDICTS
    assert "Negative shareholders' equity" in v.primary_reason
    assert "Negative shareholders' equity" not in before.primary_reason


def test_ledger_does_not_log_the_no_data_state():
    from analysis.verdict_ledger import log_verdict
    v = combine(**_TECH, fundamentals_missing=True, horizon="long")
    assert log_verdict(ticker="ACME.NS", final_verdict=v, horizon="long") is None


def test_display_label_is_descriptive():
    from analysis.action_labels import verdict_display_label
    assert verdict_display_label(INSUFFICIENT_DATA) == "Not enough fundamental data"


# ── Analyze Stock page: sources caption + long-lens state ────────────────────

def test_analyze_stock_shows_sources_and_no_long_read(monkeypatch):
    """Statement-less fundamentals: Fundamentals tab and Valuation card list
    where each core field came from (or that it was found nowhere), and the
    long-term lens says there is not enough fundamental data."""
    from tests.test_analyze_stock_layout import _run, _stubs  # noqa: F401
    import tests.test_analyze_stock_layout as lay
    from analysis.fundamentals.models import CompanyFundamentals

    mp, cache = lay._stubs.__wrapped__(monkeypatch)

    class _Svc:
        def get_fundamentals(self, ticker):
            return CompanyFundamentals(symbol=ticker, provider_name=None)
    mp.setattr(svc, "default_service", lambda: _Svc())
    at = _run(cache, mp, "NODATA", "Textiles", "No Data Ltd")
    assert not at.exception, at.exception
    caps = [str(c.value) for c in at.caption]
    src = [c for c in caps if c.startswith("Sources: ")]
    assert len(src) >= 2, caps                        # Fundamentals tab + Valuation card
    assert "revenue — not found in any source" in src[0]
    html = "\n".join(str(m.value) for m in at.markdown)
    assert "Not enough fundamental data" in html
    assert any("Not enough fundamental data for a long-term read" in c for c in caps)
