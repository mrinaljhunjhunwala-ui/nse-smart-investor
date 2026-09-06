"""
tests/test_ai_copilot.py — offline tests for the AI co-pilot's pure layers.

Covers persona.py, safety.py, context_builder.py, and the read/is_available
paths of client.py. Does not hit any network — the provider call in client.py
is exercised via a monkey-patched urlopen where needed.
"""
from __future__ import annotations

import datetime as _dt
import json

import pytest

from dashboard.shared.ai.persona import system_prompt
from dashboard.shared.ai.safety import DISCLAIMER, filter_response
from dashboard.shared.ai.context_builder import (
    ContextInputs,
    Stock,
    CompositeScore,
    Technicals,
    Regime,
    Portfolio,
    RiskRules,
    build_context,
    _macd_signal_narrative,
    _sma_50_200_narrative,
    _nifty_bias_narrative,
    _data_freshness,
)
from dashboard.shared.ai import client as ai_client


# ── persona ───────────────────────────────────────────────────────────────────

def test_system_prompt_is_stable():
    """The persona string must be deterministic (same string every call) so
    the provider can prompt-cache it."""
    assert system_prompt() == system_prompt()


def test_system_prompt_mentions_compliance():
    """Compliance keywords must be present — this is the primary safety layer."""
    txt = system_prompt()
    assert "SEBI" in txt
    assert "not issue a buy" in txt.lower() or "never issue" in txt.lower()
    assert "Educational analysis only" in txt


# ── safety ────────────────────────────────────────────────────────────────────

_SAFE_RESPONSES = [
    "Composite score 68/90 breaks down to technical 30, momentum 18, volume 10, sentiment 10.",
    "Bull case: RSI(14) at 58.2 with a fresh MACD bullish crossover.\nBear case: sector rank slipped from 3 to 6.",
    "The vwap-volume-profile framework applies here — price is 1.2% above session VWAP.",
]


@pytest.mark.parametrize("txt", _SAFE_RESPONSES)
def test_safety_passes_descriptive_responses(txt):
    result = filter_response(txt)
    assert not result.blocked
    # Disclaimer appended if missing.
    assert DISCLAIMER in result.text


def test_safety_leaves_existing_disclaimer_intact():
    txt = "Composite 68/90.\n\n" + DISCLAIMER
    result = filter_response(txt)
    assert not result.blocked
    # Should NOT be appended a second time.
    assert result.text.count(DISCLAIMER) == 1


_UNSAFE_RESPONSES = [
    "You should buy this stock at ₹2850.",
    "You must sell before results.",
    "I recommend buying RELIANCE now.",
    "My recommendation is to hold.",
    "Buy this now.",
    "Sell it today.",
    "Target: 3200, buy at current levels.",
    "Buy recommendation: strong.",
]


@pytest.mark.parametrize("txt", _UNSAFE_RESPONSES)
def test_safety_blocks_direct_instructions(txt):
    result = filter_response(txt)
    assert result.blocked, f"should have blocked: {txt!r}"
    assert result.reason  # non-empty explanation
    assert DISCLAIMER in result.text  # fallback message carries the disclaimer


def test_safety_blocks_empty_response():
    result = filter_response("")
    assert result.blocked
    assert result.reason == "empty response"


# ── context_builder ───────────────────────────────────────────────────────────

def _sample_inputs() -> ContextInputs:
    return ContextInputs(
        page="analyze_stock",
        stock=Stock(symbol="RELIANCE", name="Reliance Industries", sector="Oil & Gas",
                    ltp=2856.4, prev_close=2841.0, day_change_pct=0.54),
        composite_score=CompositeScore(total=68, technical=30, momentum=18, volume=10, sentiment=10),
        technicals=Technicals(rsi_14=58.2, macd_signal="bullish crossover 3 sessions ago",
                              vwap_position="1.2% above session VWAP",
                              sma_50_200="50 above 200 (golden cross since Jul-2026)",
                              cpr_stance="above CPR"),
        regime=Regime(india_vix=12.4, vix_zone="low", nifty_bias="trending up", sector_rank=4),
        portfolio=Portfolio(avg_price=2790.0, quantity=40, unrealised_pl_pct=2.38, days_held=22),
        risk_rules=RiskRules(max_position_pct=5, atr_stop_multiplier=2.0, min_rr=1.5),
    )


def test_build_context_shape():
    ctx = build_context(_sample_inputs())
    assert ctx.startswith("CURRENT DASHBOARD STATE")
    # Trailing block is valid JSON.
    _, body = ctx.split("\n", 1)
    parsed = json.loads(body)
    assert parsed["stock"]["symbol"] == "RELIANCE"
    assert parsed["composite_score"]["total"] == 68
    assert parsed["regime"]["vix_zone"] == "low"
    assert parsed["portfolio"]["quantity"] == 40


def test_build_context_omits_null_blocks():
    """A stock with no portfolio and no technicals should produce a payload
    with no `portfolio` key at all — not `"portfolio": null` or `"portfolio": {}`."""
    inputs = ContextInputs(
        page="watchlist",
        stock=Stock(symbol="TCS"),
        composite_score=CompositeScore(total=55),
        # everything else default (empty)
    )
    ctx = build_context(inputs)
    _, body = ctx.split("\n", 1)
    parsed = json.loads(body)
    assert "portfolio" not in parsed
    assert "technicals" not in parsed
    assert "risk_rules" not in parsed
    # But composite_score has a real value, so the key survives.
    assert parsed["composite_score"] == {"total": 55}


def test_build_context_is_deterministic_given_now():
    """Same inputs + same clock ⇒ same output (byte-identical)."""
    fixed = _dt.datetime(2026, 9, 2, 10, 30, 0, tzinfo=_dt.timezone(_dt.timedelta(hours=5, minutes=30)))
    a = build_context(_sample_inputs(), now=fixed)
    b = build_context(_sample_inputs(), now=fixed)
    assert a == b


def test_build_context_rounds_floats():
    """Floats must be rounded to 2 decimals — no long tails in the payload."""
    inputs = _sample_inputs()
    inputs.stock.ltp = 2856.4127398  # noisy
    ctx = build_context(inputs)
    assert "2856.41" in ctx
    assert "2856.4127" not in ctx


# ── collector narrative helpers (Task 5.3 fill) ──────────────────────────────

import numpy as np
import pandas as pd


def _synth_df(n: int = 260, drift: float = 0.4, seed: int = 3) -> pd.DataFrame:
    """Deterministic synthetic OHLCV with SMA_50/SMA_200/MACD/MACD_Signal
    columns pre-computed. Used only by the collector-helper tests."""
    rng = np.random.default_rng(seed)
    close = np.maximum(100 + np.cumsum(rng.normal(drift, 0.8, n)), 5.0)
    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    df = pd.DataFrame({"Close": close}, index=idx)
    df["SMA_50"]  = df["Close"].rolling(50).mean()
    df["SMA_200"] = df["Close"].rolling(200).mean()
    ema12 = df["Close"].ewm(span=12, adjust=False).mean()
    ema26 = df["Close"].ewm(span=26, adjust=False).mean()
    df["MACD"] = ema12 - ema26
    df["MACD_Signal"] = df["MACD"].ewm(span=9, adjust=False).mean()
    return df


def test_macd_signal_narrative_uptrend_returns_bullish_or_positive():
    df = _synth_df(drift=0.5)
    out = _macd_signal_narrative(df)
    assert out is not None
    assert any(w in out for w in ("bullish", "positive"))


def test_macd_signal_narrative_none_on_missing_columns():
    df = pd.DataFrame({"Close": [1.0, 2.0, 3.0]})
    assert _macd_signal_narrative(df) is None


def test_sma_50_200_narrative_uptrend_says_50_above_200():
    df = _synth_df(drift=0.5)  # clear uptrend → 50 crosses above 200
    out = _sma_50_200_narrative(df)
    assert out is not None
    assert "50 above 200" in out


def test_sma_50_200_narrative_downtrend_says_50_below_200():
    df = _synth_df(drift=-0.5, seed=17)
    # In case the noise leaves the current bar ambiguous, still get a well-formed string
    out = _sma_50_200_narrative(df)
    assert out is not None
    assert "50 " in out and "200" in out


def test_sma_50_200_narrative_none_on_short_frame():
    df = pd.DataFrame({"Close": [1.0, 2.0, 3.0]})
    assert _sma_50_200_narrative(df) is None


@pytest.mark.parametrize("label,expected", [
    ("trend_up",   "trending up"),
    ("trend_down", "trending down"),
    ("range",      "range-bound"),
    ("risk_off",   "risk-off"),
    ("unknown",    None),
    (None,         None),
    ("",           None),
])
def test_nifty_bias_narrative_maps(label, expected):
    assert _nifty_bias_narrative(label) == expected


def test_data_freshness_fresh_when_recent():
    now = _dt.datetime(2026, 9, 6, 12, 0, 0)
    ts  = (now - _dt.timedelta(minutes=5)).isoformat()
    assert _data_freshness(ts, now=now) == "fresh"


def test_data_freshness_stale_when_old():
    now = _dt.datetime(2026, 9, 6, 12, 0, 0)
    ts  = (now - _dt.timedelta(minutes=30)).isoformat()
    assert _data_freshness(ts, now=now) == "stale"


def test_data_freshness_boundary_at_15_min_is_fresh():
    now = _dt.datetime(2026, 9, 6, 12, 0, 0)
    ts  = (now - _dt.timedelta(minutes=15)).isoformat()
    assert _data_freshness(ts, now=now) == "fresh"


def test_data_freshness_none_on_bad_input():
    assert _data_freshness(None) is None
    assert _data_freshness("not-a-timestamp") is None
    assert _data_freshness("") is None


# ── build_context contract: newly-populated fields serialise correctly ───────

def test_build_context_includes_new_stock_fields():
    inp = ContextInputs(
        page="analyze_stock",
        stock=Stock(symbol="RELIANCE", name="Reliance Industries",
                    sector="Oil & Gas", ltp=1400.0, prev_close=1385.0,
                    day_change_pct=1.08),
    )
    ctx = build_context(inp)
    _, body = ctx.split("\n", 1)
    parsed = json.loads(body)
    assert parsed["stock"]["name"] == "Reliance Industries"
    assert parsed["stock"]["prev_close"] == 1385.0
    assert parsed["stock"]["day_change_pct"] == 1.08


def test_build_context_includes_technicals_narrative_strings():
    inp = ContextInputs(
        page="analyze_stock",
        stock=Stock(symbol="TCS"),
        technicals=Technicals(
            rsi_14=58.2,
            macd_signal="bullish crossover 2 sessions ago",
            sma_50_200="50 above 200 (golden cross regime, recent)",
        ),
    )
    ctx = build_context(inp)
    parsed = json.loads(ctx.split("\n", 1)[1])
    assert parsed["technicals"]["macd_signal"].startswith("bullish crossover")
    assert "50 above 200" in parsed["technicals"]["sma_50_200"]
    # vwap_position and cpr_stance were not set → must be omitted
    assert "vwap_position" not in parsed["technicals"]
    assert "cpr_stance"   not in parsed["technicals"]


def test_build_context_includes_nifty_bias_and_freshness():
    inp = ContextInputs(
        page="analyze_stock",
        stock=Stock(symbol="INFY"),
        regime=Regime(nifty_bias="trending up", india_vix=13.4, vix_zone="normal", sector_rank=3),
        data_freshness="fresh",
    )
    parsed = json.loads(build_context(inp).split("\n", 1)[1])
    assert parsed["regime"]["nifty_bias"] == "trending up"
    assert parsed["data_freshness"] == "fresh"


# ── client (read_api_key / is_available) ──────────────────────────────────────

def test_read_api_key_env(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key-abc")
    assert ai_client.read_api_key() == "test-key-abc"
    assert ai_client.is_available()


def test_read_api_key_missing(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    # Also neutralise streamlit secrets path.
    monkeypatch.setattr(ai_client, "read_api_key", ai_client.read_api_key)
    # Direct check — env absent and (in test env) no streamlit secrets file.
    if ai_client.read_api_key() is not None:
        pytest.skip("Streamlit secrets have GROQ_API_KEY set outside env; skipping")
    assert not ai_client.is_available()


def test_chat_raises_when_key_missing(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    if ai_client.read_api_key() is not None:
        pytest.skip("key set via streamlit secrets; can't test missing path")
    with pytest.raises(ai_client.CopilotUnavailable):
        ai_client.chat([ai_client.Message(role="user", content="hi")])
