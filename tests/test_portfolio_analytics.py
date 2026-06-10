"""
tests/test_portfolio_analytics.py — coverage for the two previously untested
portfolio-analytics modules:

  • analysis/portfolio_concentration.py  (HHI / diversification)
  • analysis/portfolio_fundamentals.py    (quality score — thin wrapper)
  • alerts/check_alerts_v2.py             (price-alert engine, dependency-injected)

Pure-function tests; no network. The alert tests inject mock Telegram/quoter
objects and monkeypatch the alerts CSV path, so nothing real is sent or read.
"""
from __future__ import annotations

import csv

import pytest

from analysis.portfolio_concentration import (
    calculate_hhi,
    analyze_concentration,
    concentration_grade,
    ConcentrationResult,
)
from analysis.portfolio_fundamentals import compute_quality_score
import alerts.check_alerts_v2 as cav


# ─────────────────────────────────────────────────────────────────────────────
# Section A — portfolio_concentration
# ─────────────────────────────────────────────────────────────────────────────

def test_hhi_equal_weights_ten_holdings():
    # 10 holdings at 10% each → Σ(10²) × 10 = 1000
    assert calculate_hhi([10.0] * 10) == 1000.0


def test_hhi_single_holding():
    assert calculate_hhi([100.0]) == 10000.0


def test_hhi_empty_list():
    assert calculate_hhi([]) == 0.0


def test_hhi_two_holdings_60_40():
    # 60² + 40² = 3600 + 1600 = 5200
    assert calculate_hhi([60.0, 40.0]) == 5200.0


def test_grade_a():
    assert concentration_grade(500) == "A"


def test_grade_b():
    assert concentration_grade(1200) == "B"


def test_grade_c():
    assert concentration_grade(1700) == "C"


def test_grade_d():
    assert concentration_grade(2200) == "D"


def test_grade_f():
    assert concentration_grade(3000) == "F"


def test_analyze_empty_portfolio():
    r = analyze_concentration([])
    assert isinstance(r, ConcentrationResult)
    assert r.total_holdings == 0
    assert r.hhi == 0
    assert r.hhi_category == "Unknown"


def test_analyze_single_holding():
    r = analyze_concentration([{"ticker": "RELIANCE", "weight_pct": 100.0}])
    assert r.hhi == 10000
    assert r.hhi_category == "High"
    assert r.risk_level == "HIGH"
    assert r.top_1_weight == 100.0


def test_analyze_equal_ten_holdings():
    holdings = [{"ticker": f"S{i}", "weight_pct": 10.0} for i in range(10)]
    r = analyze_concentration(holdings)
    assert r.hhi == 1000
    assert r.hhi_category == "Low"
    assert r.risk_level == "LOW"
    assert abs(r.top_5_weight - 50.0) < 0.01


# ─────────────────────────────────────────────────────────────────────────────
# Section B — compute_quality_score (inputs are already in PERCENT)
# ─────────────────────────────────────────────────────────────────────────────

def test_quality_empty_dict():
    assert compute_quality_score({}) == 0


def test_quality_only_roe_15():
    # 15% ROE → 15×2 = 30 (the cap); only metric present → 100% of its weight
    assert compute_quality_score({"roe": 15.0}) == 100


def test_quality_all_zero():
    assert compute_quality_score({
        "roe": 0.0, "roce": 0.0, "revenue_cagr_5y": 0.0, "eps_cagr_5y": 0.0,
    }) == 0


def test_quality_all_maxed():
    assert compute_quality_score({
        "roe": 15.0, "roce": 15.0, "revenue_cagr_5y": 20.0, "eps_cagr_5y": 20.0,
    }) == 100


def test_quality_partial_roe_only():
    # 7.5% ROE → 7.5×2 = 15 of 30 → 50/100 scaled
    assert compute_quality_score({"roe": 7.5}) == 50


def test_quality_negative_cagr_clamped_not_negative():
    # A negative CAGR must contribute 0, never drag the score below 0
    s = compute_quality_score({"eps_cagr_5y": -50.0})
    assert s == 0
    assert s >= 0


# ─────────────────────────────────────────────────────────────────────────────
# Section C — check_alerts_v2 (dependency-injected; mocked Telegram + quoter)
# ─────────────────────────────────────────────────────────────────────────────

class _MockTelegram:
    def __init__(self):
        self.sent = []

    def send(self, text: str) -> bool:
        self.sent.append(text)
        return True


class _MockQuoter:
    """check_price_alerts upper-cases the CSV ticker, so key by the UPPER form."""
    def __init__(self, prices: dict):
        self._p = prices

    def get_quote(self, ticker: str) -> dict:
        p = self._p.get(ticker)
        return {"price": p} if p is not None else {}


def _write_alerts_csv(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["ticker", "condition", "level", "enabled"])
        w.writeheader()
        for r in rows:
            w.writerow(r)


def test_alerts_no_trigger_sends_nothing(tmp_path, monkeypatch):
    csv_path = tmp_path / "alerts.csv"
    _write_alerts_csv(csv_path, [{"ticker": "RELIANCE", "condition": "above",
                                  "level": 100, "enabled": 1}])
    monkeypatch.setattr(cav, "_ALERTS_CSV", csv_path)
    tg = _MockTelegram()
    # price 80 < 100 → "above" not hit
    n = cav.check_price_alerts(state={}, today="2026-01-01", telegram=tg,
                               quoter=_MockQuoter({"RELIANCE": 80}))
    assert n == 0
    assert tg.sent == []


def test_alerts_above_trigger_fires(tmp_path, monkeypatch):
    csv_path = tmp_path / "alerts.csv"
    _write_alerts_csv(csv_path, [{"ticker": "RELIANCE", "condition": "above",
                                  "level": 100, "enabled": 1}])
    monkeypatch.setattr(cav, "_ALERTS_CSV", csv_path)
    tg = _MockTelegram()
    n = cav.check_price_alerts(state={}, today="2026-01-01", telegram=tg,
                               quoter=_MockQuoter({"RELIANCE": 150}))
    assert n == 1
    assert len(tg.sent) == 1
    assert "RELIANCE" in tg.sent[0]


def test_alerts_below_trigger_fires(tmp_path, monkeypatch):
    csv_path = tmp_path / "alerts.csv"
    _write_alerts_csv(csv_path, [{"ticker": "RELIANCE", "condition": "below",
                                  "level": 200, "enabled": 1}])
    monkeypatch.setattr(cav, "_ALERTS_CSV", csv_path)
    tg = _MockTelegram()
    n = cav.check_price_alerts(state={}, today="2026-01-01", telegram=tg,
                               quoter=_MockQuoter({"RELIANCE": 150}))
    assert n == 1
    assert "RELIANCE" in tg.sent[0]


def test_alerts_already_fired_today_skipped(tmp_path, monkeypatch):
    csv_path = tmp_path / "alerts.csv"
    _write_alerts_csv(csv_path, [{"ticker": "RELIANCE", "condition": "above",
                                  "level": 100, "enabled": 1}])
    monkeypatch.setattr(cav, "_ALERTS_CSV", csv_path)
    tg = _MockTelegram()
    # key format: price_{TICKER}_{condition}_{level:.2f}
    state = {"price_RELIANCE_above_100.00": "2026-01-01"}
    n = cav.check_price_alerts(state=state, today="2026-01-01", telegram=tg,
                               quoter=_MockQuoter({"RELIANCE": 150}))
    assert n == 0
    assert tg.sent == []


def test_alerts_disabled_rule_skipped(tmp_path, monkeypatch):
    csv_path = tmp_path / "alerts.csv"
    _write_alerts_csv(csv_path, [{"ticker": "RELIANCE", "condition": "above",
                                  "level": 100, "enabled": 0}])
    monkeypatch.setattr(cav, "_ALERTS_CSV", csv_path)
    tg = _MockTelegram()
    n = cav.check_price_alerts(state={}, today="2026-01-01", telegram=tg,
                               quoter=_MockQuoter({"RELIANCE": 150}))
    assert n == 0
    assert tg.sent == []


def test_prune_state_removes_old_entries():
    state = {"price_A_above_10.00": "2025-01-01",
             "price_B_below_20.00": "2026-01-01"}
    pruned = cav.prune_state(state, "2026-01-01")
    assert pruned == {"price_B_below_20.00": "2026-01-01"}


def test_alerts_missing_csv_returns_zero(tmp_path, monkeypatch):
    missing = tmp_path / "does_not_exist.csv"
    monkeypatch.setattr(cav, "_ALERTS_CSV", missing)
    tg = _MockTelegram()
    n = cav.check_price_alerts(state={}, today="2026-01-01", telegram=tg,
                               quoter=_MockQuoter({"RELIANCE": 150}))
    assert n == 0
    assert tg.sent == []
