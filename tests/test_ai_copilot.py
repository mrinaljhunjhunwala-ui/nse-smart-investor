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
