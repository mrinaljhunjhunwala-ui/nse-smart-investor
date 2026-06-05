"""
Phase 1 portfolio-risk regression tests — metric functions in isolation + the
orchestrator end-to-end with an injected price loader and a mocked beta engine
(no network).

Run:  py -m pytest tests/test_portfolio_risk.py -q
"""
import math
import os
import sys

import numpy as np
import pandas as pd
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import analysis.portfolio_risk as PR  # noqa: E402


def _series(values, start="2023-01-02"):
    idx = pd.date_range(start, periods=len(values), freq="B")
    return pd.Series(values, index=idx)


def _prices(values, start="2023-01-02"):
    idx = pd.date_range(start, periods=len(values), freq="B")
    return pd.DataFrame({"Close": values}, index=idx)


# ───────────────────────── max drawdown ─────────────────────────
def test_max_drawdown_known():
    nav = _series([100, 120, 90, 110])
    dd, peak, trough = PR.max_drawdown(nav)
    assert dd == pytest.approx(-25.0)        # 90/120 - 1
    assert trough is not None and peak is not None


def test_max_drawdown_monotonic_up_is_zero():
    dd, _, _ = PR.max_drawdown(_series([100, 101, 102, 103]))
    assert dd == pytest.approx(0.0)


def test_max_drawdown_too_short_none():
    assert PR.max_drawdown(_series([100]))[0] is None


# ───────────────────────── sharpe / sortino / calmar ─────────────────────────
def test_sharpe_positive():
    r = _series([0.001] * 100 + [0.002] * 100)
    s = PR.sharpe_ratio(r, rf_annual=0.0)
    assert s is not None and s > 0


def test_sharpe_zero_volatility_none():
    r = _series([0.001] * 50)                # constant → std 0
    assert PR.sharpe_ratio(r) is None


def test_sortino_basic():
    rng = np.random.default_rng(1)
    r = _series(rng.normal(0.001, 0.01, 200))
    assert PR.sortino_ratio(r, rf_annual=0.0) is not None


def test_sortino_no_downside_none():
    r = _series([0.01] * 60)                 # never below rf → no downside
    assert PR.sortino_ratio(r, rf_annual=0.0) is None


def test_calmar():
    assert PR.calmar_ratio(20.0, -10.0) == pytest.approx(2.0)


def test_calmar_none_without_drawdown():
    assert PR.calmar_ratio(20.0, 0.0) is None
    assert PR.calmar_ratio(None, -10.0) is None


# ───────────────────────── correlation ─────────────────────────
def test_correlation_matrix_shape_and_diagonal():
    rng = np.random.default_rng(2)
    df = pd.DataFrame({"A": rng.normal(0, 0.01, 100), "B": rng.normal(0, 0.01, 100),
                       "C": rng.normal(0, 0.01, 100)})
    cm = PR.correlation_matrix(df)
    assert cm.shape == (3, 3)
    assert all(cm.loc[c, c] == pytest.approx(1.0) for c in df.columns)


def test_correlation_single_ticker_none():
    df = pd.DataFrame({"A": np.random.default_rng(3).normal(0, 0.01, 100)})
    assert PR.correlation_matrix(df) is None


# ───────────────────────── risk contributions ─────────────────────────
def test_risk_contributions_sum_to_100():
    rng = np.random.default_rng(4)
    df = pd.DataFrame({"A": rng.normal(0, 0.01, 200), "B": rng.normal(0, 0.02, 200),
                       "C": rng.normal(0, 0.015, 200)})
    rc = PR.risk_contributions(df, {"A": 0.5, "B": 0.3, "C": 0.2})
    assert sum(rc.values()) == pytest.approx(100.0, abs=0.5)


def test_risk_contributions_single_holding_is_100():
    df = pd.DataFrame({"A": np.random.default_rng(5).normal(0, 0.01, 200)})
    assert PR.risk_contributions(df, {"A": 1.0}) == {"A": 100.0}


def test_risk_contributions_higher_vol_weight_dominates():
    rng = np.random.default_rng(6)
    df = pd.DataFrame({"LOWVOL": rng.normal(0, 0.005, 300),
                       "HIGHVOL": rng.normal(0, 0.03, 300)})
    rc = PR.risk_contributions(df, {"LOWVOL": 0.5, "HIGHVOL": 0.5})
    assert rc["HIGHVOL"] > rc["LOWVOL"]      # vol concentration shows up in risk, not weight


# ───────────────────────── orchestrator ─────────────────────────
def _loader_factory(price_map):
    def loader(ticker, period="1y"):
        if ticker in price_map:
            return price_map[ticker]
        raise ValueError("no data")
    return loader


@pytest.fixture
def mock_beta(monkeypatch):
    import analysis.hedging as H
    monkeypatch.setattr(H, "calculate_portfolio_beta", lambda holdings, period="1y": {
        "portfolio_beta": 0.95,
        "holdings_beta": [{"ticker": h["ticker"], "beta": 1.1} for h in holdings],
    })


def test_compute_end_to_end(mock_beta):
    rng = np.random.default_rng(7)
    a = 100 * np.cumprod(1 + rng.normal(0.0005, 0.01, 200))
    b = 50 * np.cumprod(1 + rng.normal(0.0004, 0.015, 200))
    loader = _loader_factory({"AAA.NS": _prices(a), "BBB.NS": _prices(b)})
    res = PR.compute_portfolio_risk(
        [{"ticker": "AAA.NS", "quantity": 10}, {"ticker": "BBB.NS", "quantity": 20}],
        period="1y", price_loader=loader)
    assert res.error is None
    assert res.nav_curve is not None and res.n_days == 200
    assert res.sharpe is not None and res.sortino is not None
    assert res.max_drawdown_pct is not None and res.max_drawdown_pct <= 0
    assert res.annualized_vol_pct is not None and res.annualized_vol_pct > 0
    assert res.portfolio_beta == 0.95                       # reused beta engine
    assert len(res.risk_contributions) == 2
    assert sum(p.risk_contribution_pct for p in res.risk_contributions) == pytest.approx(100, abs=0.5)
    assert res.confidence == "high" and res.notes


def test_compute_drops_insufficient_history(mock_beta):
    rng = np.random.default_rng(8)
    good = _prices(100 * np.cumprod(1 + rng.normal(0, 0.01, 200)))
    short = _prices([100, 101, 102])                        # < 30 days → dropped
    loader = _loader_factory({"GOOD.NS": good, "SHORT.NS": short})
    res = PR.compute_portfolio_risk(
        [{"ticker": "GOOD.NS", "quantity": 1}, {"ticker": "SHORT.NS", "quantity": 1}],
        price_loader=loader)
    assert "SHORT" in res.holdings_dropped and "GOOD" in res.holdings_used
    assert res.nav_curve is not None


def test_compute_no_holdings_errors():
    res = PR.compute_portfolio_risk([], price_loader=_loader_factory({}))
    assert res.error is not None and res.nav_curve is None


def test_compute_all_dropped_errors():
    loader = _loader_factory({"X.NS": _prices([100, 101])})
    res = PR.compute_portfolio_risk([{"ticker": "X.NS", "quantity": 1}], price_loader=loader)
    assert res.error is not None


def test_compute_total_return_known(mock_beta):
    # single holding, price 100 -> 121 over the window => +21% total return
    vals = list(np.linspace(100, 121, 120))
    loader = _loader_factory({"Z.NS": _prices(vals)})
    res = PR.compute_portfolio_risk([{"ticker": "Z.NS", "quantity": 3}], price_loader=loader)
    assert res.total_return_pct == pytest.approx(21.0, abs=0.5)
    assert res.risk_contributions[0].risk_contribution_pct == 100.0


def test_compute_confidence_low_for_short_window(mock_beta):
    rng = np.random.default_rng(9)
    loader = _loader_factory({"S.NS": _prices(100 * np.cumprod(1 + rng.normal(0, 0.01, 40)))})
    res = PR.compute_portfolio_risk([{"ticker": "S.NS", "quantity": 1}], price_loader=loader)
    assert res.confidence == "low" and res.n_days == 40


def test_compute_methodology_notes_present(mock_beta):
    rng = np.random.default_rng(10)
    loader = _loader_factory({"N.NS": _prices(100 * np.cumprod(1 + rng.normal(0, 0.01, 200)))})
    res = PR.compute_portfolio_risk([{"ticker": "N.NS", "quantity": 1}], price_loader=loader)
    assert any("held constant" in n for n in res.notes)        # constant-holdings caveat
    assert any("risk-free" in n for n in res.notes)


# ───────────────── IMPROVE: recency detection / confidence / disclosure ─────────────────
from datetime import date as _date    # noqa: E402


def test_detect_recent_purchases_basic():
    rec = PR.detect_recent_purchases(
        {"A.NS": _date(2024, 6, 1), "B.NS": _date(2020, 1, 1)},   # A after window, B before
        window_start=_date(2024, 1, 1), weights={"A.NS": 0.4, "B.NS": 0.6})
    assert rec["n_affected"] == 1 and rec["affected_holdings"] == ["A"]
    assert rec["affected_weight_pct"] == pytest.approx(40.0)


def test_detect_recent_purchases_all_predate():
    rec = PR.detect_recent_purchases(
        {"A.NS": _date(2019, 1, 1), "B.NS": _date(2018, 1, 1)},
        window_start=_date(2024, 1, 1), weights={"A.NS": 0.5, "B.NS": 0.5})
    assert rec["n_affected"] == 0 and rec["affected_weight_pct"] == pytest.approx(0.0)


def test_detect_recent_purchases_no_dates_returns_none():
    rec = PR.detect_recent_purchases(
        {"A.NS": None, "B.NS": None}, window_start=_date(2024, 1, 1),
        weights={"A.NS": 0.5, "B.NS": 0.5})
    assert rec["affected_weight_pct"] is None and rec["dated_coverage"] == 0


def test_adjust_confidence_majority_bought_in_window_is_low():
    conf, reason = PR.adjust_confidence("high", 60.0)
    assert conf == "low" and "60%" in reason


def test_adjust_confidence_quarter_downgrades_one_notch():
    assert PR.adjust_confidence("high", 30.0)[0] == "medium"
    assert PR.adjust_confidence("medium", 30.0)[0] == "low"


def test_adjust_confidence_small_unaffected():
    conf, _ = PR.adjust_confidence("high", 10.0)
    assert conf == "high"


def test_adjust_confidence_unknown_dates_unchanged():
    conf, reason = PR.adjust_confidence("high", None)
    assert conf == "high" and "unavailable" in reason.lower()


def test_build_disclosure_specific_warning():
    d = PR.build_disclosure("1y", {"affected_weight_pct": 34.0, "n_affected": 2})
    assert "34%" in d and "1-year" in d and "hypothetical" in d and "realized" in d


def test_build_disclosure_all_predate_reliable():
    d = PR.build_disclosure("2y", {"affected_weight_pct": 0.0, "n_affected": 0})
    assert "predate" in d and "2-year" in d


def test_build_disclosure_unknown_dates():
    d = PR.build_disclosure("3y", {"affected_weight_pct": None, "n_affected": 0})
    assert "unavailable" in d.lower() and "hypothetical" in d


def test_end_to_end_recency_and_disclosure(mock_beta):
    rng = np.random.default_rng(11)
    a = 100 * np.cumprod(1 + rng.normal(0.0005, 0.01, 200))   # panel starts 2023-01-02
    b = 50 * np.cumprod(1 + rng.normal(0.0004, 0.012, 200))
    loader = _loader_factory({"AAA.NS": _prices(a), "BBB.NS": _prices(b)})
    res = PR.compute_portfolio_risk(
        [{"ticker": "AAA.NS", "quantity": 10, "date_bought": "2023-06-01"},   # inside window
         {"ticker": "BBB.NS", "quantity": 20, "date_bought": "2020-01-01"}],  # predates
        period="1y", price_loader=loader)
    assert res.error is None
    assert "AAA" in res.affected_holdings and res.n_affected == 1
    assert res.affected_weight_pct and res.affected_weight_pct > 0
    assert "hypothetical" in res.disclosure and "%" in res.disclosure
    assert res.purchase_dates_known is True


def test_metric_groups_classification(mock_beta):
    rng = np.random.default_rng(12)
    loader = _loader_factory({"Z.NS": _prices(100 * np.cumprod(1 + rng.normal(0, 0.01, 200)))})
    res = PR.compute_portfolio_risk([{"ticker": "Z.NS", "quantity": 1}], price_loader=loader)
    perf = [m[0] for m in res.performance_metrics()]
    risk = [m[0] for m in res.risk_metrics()]
    assert "Sharpe" in perf and "Calmar" in perf and "CAGR (Ann. Return)" in perf
    assert "Portfolio Beta" in risk and "Annualised Volatility" in risk


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
