"""Audit 2026-11: data that silently vanished or read wrong after a provider hiccup."""
import datetime as dt

import numpy as np
import pandas as pd

from analysis.qualitative_flags import (FlagCategory, FlagSentiment, QualitativeFlag, load_flags,
                                        refresh_all_flags, save_flags)


def _kv():
    kv = {}
    return kv, (lambda k, d=None, u="default": kv.get((u, k), d)), \
        (lambda k, v, u="default": kv.__setitem__((u, k), v) or True)


def _flag(headline, source, days=60):
    today = dt.date.today()
    return QualitativeFlag("X.NS", FlagCategory.GOVERNANCE, FlagSentiment.RED, headline, source,
                           today.isoformat(), dt.datetime.now().isoformat(),
                           (today + dt.timedelta(days=days)).isoformat())


def test_outage_refresh_keeps_stored_red_flags():
    kv, get, put = _kv()
    save_flags("X.NS", [_flag("Promoter pledge up to 40%", "NSE top-corp-info: shareholdings_patterns"),
                        _flag("Pledge disclosed", "NSE RSS: Reason For Encumbrance (pledge)")], put)
    out = refresh_all_flags("X.NS", get, put, corp_info={}, news_items=[], rss_items_by_category={})
    heads = {f.headline for f in out}
    assert {"Promoter pledge up to 40%", "Pledge disclosed"} <= heads           # were wiped
    assert {f.headline for f in load_flags("X.NS", get)} >= heads


def test_a_source_that_answered_still_replaces_its_own_flags():
    kv, get, put = _kv()
    save_flags("X.NS", [_flag("Old corp flag", "NSE top-corp-info: latest_announcements")], put)
    out = refresh_all_flags("X.NS", get, put, corp_info={"latest_announcements": []},
                            news_items=[], rss_items_by_category={})
    assert "Old corp flag" not in {f.headline for f in out}


def test_empty_fundamentals_are_not_cached():
    from analysis.fundamentals.models import RatioSnapshot
    from analysis.fundamentals.provider import FundamentalProvider
    from analysis.fundamentals.service import FundamentalsService

    class P(FundamentalProvider):
        name, up = "fake", False

        def is_available(self):
            return True

        def _chk(self):
            if not P.up:
                raise ConnectionError("429 rate limited")

        def get_income_statement(self, s, period="annual", years=10):
            self._chk()
            return []

        def get_balance_sheet(self, s, period="annual", years=10):
            self._chk()
            return []

        def get_cash_flow(self, s, period="annual", years=10):
            self._chk()
            return []

        def get_ratios(self, s):
            self._chk()
            return RatioSnapshot(market_cap=1e12)

    import analysis.fundamentals.service as svc_mod
    svc = FundamentalsService(providers=[P()])
    a = svc.get_fundamentals("TCS.NS")
    assert not a.has_any_data()
    P.up = True
    assert svc.get_fundamentals("TCS.NS") is a          # kept briefly: no hammering while rate-limited
    key = next(iter(svc.cache._store))
    exp, val = svc.cache._store[key]
    assert exp - __import__("time").time() <= svc_mod.EMPTY_TTL_SECONDS
    svc.cache._store[key] = (0, val)                    # ten minutes later
    b = svc.get_fundamentals("TCS.NS")
    assert b is not a and b.has_any_data()            # was the cached empty record for 24h


def test_portfolio_fit_does_not_correlate_a_holding_with_itself():
    from analysis.thesis.portfolio_fit import build_fit_inputs
    rng = np.random.default_rng(0)
    idx = pd.bdate_range(end="2026-11-16", periods=120)
    px = {t: pd.DataFrame({"Close": 100 * np.cumprod(1 + rng.normal(0, 0.01, 120))}, index=idx)
          for t in ("A.NS", "B.NS")}
    inp = build_fit_inputs("A.NS", [{"ticker": "A.NS", "quantity": 10}, {"ticker": "B.NS", "quantity": 10}],
                           candidate_thesis=object(), candidate_beta=1.0, candidate_sector="IT",
                           price_loader=lambda t, period="1y": px[t])
    assert inp.most_correlated_with == "B" and inp.max_correlation < 0.5   # was A at 1.0


def test_portfolio_fit_survives_a_failing_candidate_loader():
    from analysis.thesis.portfolio_fit import build_fit_inputs
    idx = pd.bdate_range(end="2026-11-16", periods=60)
    good = pd.DataFrame({"Close": np.linspace(100, 110, 60)}, index=idx)

    def loader(t, period="1y"):
        if t == "C.NS":
            raise ConnectionError("blocked")
        return good
    inp = build_fit_inputs("C.NS", [{"ticker": "B.NS", "quantity": 1}], candidate_thesis=object(),
                           candidate_beta=1.0, candidate_sector="IT", price_loader=loader)
    assert inp.avg_correlation is None                 # used to raise NameError on cdf
