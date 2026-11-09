"""Plain-language "why not assessed / not measured" helpers.

* explain_refusal(): a valuation refusal says whether the data was FOUND but
  the method does not apply (negative equity, losses, ...) or was MISSING.
* score_coverage: lists composite-score parts held at neutral for lack of
  data, and recognises the DATA_UNAVAILABLE sentinel as "not scored".
"""
from types import SimpleNamespace

import numpy as np
import pandas as pd

from analysis.fundamentals.valuation_decision import (
    INSUFFICIENT_EVIDENCE,
    REFUSAL_MISSING_DATA,
    REFUSAL_NOT_APPLICABLE,
    ValuationInputs,
    assess,
    explain_refusal,
)
from analysis.score_coverage import coverage_note, is_unscored, neutralised_parts


# ── explain_refusal ───────────────────────────────────────────────────────────
def _inp(**kw):
    base = dict(sector_group="Textiles", is_financial=False, fcf_capex_caveat=False)
    base.update(kw)
    return ValuationInputs(**base)


def test_negative_equity_says_data_found_with_figure():
    inp = _inp(total_equity=-1.6e11, net_income=-8.5e9, pe=None, pb=-2.0)
    va = assess(inp)
    assert va.posture == INSUFFICIENT_EVIDENCE and va.triggered_guard == "H2-negative-equity"
    kind, text = explain_refusal(va, inp)
    assert kind == REFUSAL_NOT_APPLICABLE
    assert text.startswith("Data found: shareholders' equity is negative (-₹16,000 cr)")
    assert "P/E- and P/B-based valuation does not apply" in text
    assert "H2" not in text


def test_negative_equity_without_inputs_still_plain():
    va = assess(_inp(total_equity=-5.0))
    kind, text = explain_refusal(va)
    assert kind == REFUSAL_NOT_APPLICABLE
    assert "shareholders' equity is negative," in text


def test_losses_say_data_found():
    inp = _inp(total_equity=5e10, net_income=-2.5e9, pe=None)
    va = assess(inp)
    assert va.triggered_guard == "H1-negative-earnings"
    kind, text = explain_refusal(va, inp)
    assert kind == REFUSAL_NOT_APPLICABLE
    assert "loss-making" in text and "-₹250 cr" in text


def test_missing_pe_names_the_metric():
    inp = _inp(total_equity=5e10, net_income=2e9, pe=None)
    va = assess(inp)
    assert va.triggered_guard == "H3-missing-metric"
    kind, text = explain_refusal(va, inp)
    assert kind == REFUSAL_MISSING_DATA
    assert text.startswith("Data missing: price-to-earnings (P/E) was not available")


def test_missing_financial_metrics_named():
    inp = _inp(sector_group="Banking", is_financial=True, pb=None, roe=None)
    va = assess(inp)
    kind, text = explain_refusal(va, inp)
    assert kind == REFUSAL_MISSING_DATA
    assert "price-to-book (P/B) and return on equity (ROE) were not available" in text


def test_implausible_pe_and_newly_listed_are_not_applicable():
    inp = _inp(total_equity=1e10, net_income=1e7, pe=450.0)
    kind, text = explain_refusal(assess(inp), inp)
    assert kind == REFUSAL_NOT_APPLICABLE and "450×" in text
    inp = _inp(total_equity=1e10, net_income=1e9, pe=30.0, eps_cagr_points=1)
    va = assess(inp)
    assert va.triggered_guard == "H5-newly-listed"
    assert explain_refusal(va, inp)[0] == REFUSAL_NOT_APPLICABLE


def test_not_a_refusal_returns_none():
    va = SimpleNamespace(posture="REASONABLE", triggered_guard=None, justification="x")
    assert explain_refusal(va) == (None, "")


def test_no_advice_words_in_explanations():
    cases = [
        _inp(total_equity=-1e9), _inp(total_equity=1e9, net_income=-1e8),
        _inp(total_equity=1e9, net_income=1e8, pe=None), _inp(sector_group="Insurance"),
    ]
    for inp in cases:
        _, text = explain_refusal(assess(inp), inp)
        low = text.lower()
        for w in (" buy", " sell", " hold", "undervalued", "overvalued", "cheap"):
            assert w not in low, (w, text)


# ── score coverage ────────────────────────────────────────────────────────────
def _cs(**kw):
    base = dict(action="NEUTRAL", narrative="", momentum_fallback=False,
                rs_score=55.0, sector_rank=3, coverage=None)
    base.update(kw)
    return SimpleNamespace(**base)


def test_all_measured():
    cs = _cs(coverage={"sma200": True, "momentum_history": True, "r60d": True,
                       "rs_vs_nifty": True, "sector_rank": True})
    assert neutralised_parts(cs) == []
    assert coverage_note(cs) == "Data coverage · all score parts measured from available data."


def test_missing_parts_listed_from_coverage_dict():
    cs = _cs(coverage={"sma200": False, "momentum_history": True, "r60d": False,
                       "rs_vs_nifty": False, "sector_rank": False})
    parts = neutralised_parts(cs)
    assert len(parts) == 4
    assert parts[0].startswith("Long-term trend (200-day average)")
    assert any(p.startswith("3-month return") for p in parts)
    assert any(p.startswith("Relative strength vs Nifty") for p in parts)
    assert any(p.startswith("Sector strength") for p in parts)
    assert coverage_note(cs).startswith("Data coverage · not measured, for lack of data")


def test_momentum_fallback_suppresses_r60_duplicate():
    cs = _cs(coverage={"sma200": False, "momentum_history": False, "r60d": False,
                       "rs_vs_nifty": True, "sector_rank": True})
    parts = neutralised_parts(cs)
    assert any(p.startswith("Momentum: fewer than 25") for p in parts)
    assert not any(p.startswith("3-month return") for p in parts)


def test_fallback_to_fields_when_no_coverage_dict():
    cs = _cs(rs_score=None, sector_rank=None,
             narrative="The 200-day average is not yet available (under 200 trading days).")
    parts = neutralised_parts(cs)
    assert len(parts) == 3


def test_unscored_sentinel():
    for act in ("DATA_UNAVAILABLE", "UNAVAILABLE"):
        cs = _cs(action=act)
        assert is_unscored(cs)
        assert neutralised_parts(cs) == [] and coverage_note(cs) == ""


def _frame(n):
    from utils.indicators import add_all_indicators
    idx = pd.bdate_range("2025-01-01", periods=n)
    rng = np.random.default_rng(7)
    close = 500 + np.cumsum(rng.normal(0.3, 4, n))
    df = pd.DataFrame({"Open": close - 1, "High": close + 3, "Low": close - 3,
                       "Close": close, "Volume": rng.integers(1e5, 3e5, n).astype(float)},
                      index=idx)
    df = add_all_indicators(df)
    return df.dropna(subset=["RSI", "ATR"])


def test_score_dataframe_populates_coverage():
    from analysis.score import score_dataframe
    short = score_dataframe(_frame(80), "SHORT.NS", sector="Textiles", sector_rank=None)
    assert short.coverage["sma200"] is False
    assert short.coverage["sector_rank"] is False
    assert short.coverage["rs_vs_nifty"] is False
    assert any("200-day" in p for p in neutralised_parts(short))

    long_ = score_dataframe(_frame(320), "LONG.NS", sector="Textiles", sector_rank=3)
    assert long_.coverage["sma200"] is True and long_.coverage["r60d"] is True
    assert long_.coverage["sector_rank"] is True
    # Coverage is metadata only — it is not part of the serialised score shape.
    assert "coverage" not in long_.as_dict()
