"""dashboard/shared/disclosures.py — transparency notices for score & backtest pages.

Reusable, side-effect-free-of-data renderers so every surface shows the same
professional, non-alarmist disclosure:

  • render_survivorship_notice()    — present-day-universe / survivorship-bias notice
  • render_backtest_assumptions()   — commission, execution, slippage, survivorship status
  • render_score_methodology()      — "What this score measures" (trend quality, not returns)
  • render_regime_reliability_note() — VIX-regime reliability note from the 5y regime study

The score components implement Phase 1 (UI honesty) of the score research:
SCORE_EFFICACY_REPORT.md and REGIME_STUDY_REPORT.md found the composite score
correlates with trend persistence (+0.41 Spearman) far more than with future
returns (+0.04), and that its ranking power degrades/inverts in elevated-fear
regimes. Wording here reflects those findings; the scoring engine is unchanged.
"""
from __future__ import annotations
import streamlit as st


def render_survivorship_notice() -> None:
    """Concise survivorship-bias disclosure shown near the top of backtest pages."""
    st.info(
        "ℹ️ **Survivorship bias — please read.** Backtests run on the **present-day** "
        "stock universe (today's index membership). Companies that were delisted, "
        "merged, or dropped from the index during the test window are **not** included, "
        "and historical constituent changes are **not yet modelled**. Results therefore "
        "reflect today's survivors and can **overstate** what was achievable at the time. "
        "Treat them as directional research, not a guarantee of past or future returns."
    )


def render_backtest_assumptions() -> None:
    """Expandable 'assumptions & limitations' section (commission, execution, slippage,
    survivorship). Cost figures are read from the live backtest constants so the
    disclosure can never drift from what the engine actually charges."""
    try:
        from backtest.runner import (
            TOTAL_COST, STT_RATE, BROKERAGE_RATE, EXCHANGE_FEES,
        )
    except Exception:
        TOTAL_COST, STT_RATE, BROKERAGE_RATE, EXCHANGE_FEES = 0.0023, 0.001, 0.0003, 0.00035

    with st.expander("📋 Backtest assumptions & limitations", expanded=False):
        st.markdown(
            f"""
**Commission — modelled.** Round-trip cost ≈ **{TOTAL_COST * 100:.2f}%**, applied to every
trade: STT {STT_RATE * 100:.2f}% (sell side) + brokerage {BROKERAGE_RATE * 100:.2f}% × 2 legs
+ exchange / SEBI / GST {EXCHANGE_FEES * 100:.3f}% × 2 legs (approximate Indian equity-delivery costs).

**Execution — realistic timing.** Signals are computed on each bar's **close**; orders fill at
the **next bar's open**. There are no same-bar fills and no look-ahead (verified by an automated
no-look-ahead regression test).

**Slippage — not modelled.** Fills assume the exact OHLC price. Real-world fills, especially in
mid- and small-caps, include bid–ask spread and market impact, so **live results will typically be
worse** than the backtest. Treat reported returns as an optimistic upper bound.

**Survivorship — not modelled.** The backtest uses the **current** index universe; delisted /
removed names and historical constituent changes are excluded (see the notice above).

**Data.** Daily bars. All indicators use only trailing (historical) windows.
"""
        )


def render_score_methodology(expanded: bool = False) -> None:
    """'What this score measures' — reusable methodology transparency component.

    Shown wherever the trend-quality (composite) score is a primary element.
    Grounded in the 5-year regime study (REGIME_STUDY_REPORT.md, 40,667 obs).
    """
    with st.expander("ℹ️ What this score measures", expanded=expanded):
        st.markdown(
            "This is a **Trend Quality Score (0–100)** built from four price-based "
            "pillars:\n"
            "- **Trend strength** — moving-average alignment (price vs SMA 20/50/200) and ADX\n"
            "- **Trend persistence** — multi-horizon momentum (5/20/60-day returns)\n"
            "- **Momentum quality** — RSI zone and MACD state\n"
            "- **Technical confirmation** — volume behaviour (accumulation vs distribution) "
            "and candlestick context\n\n"
            "**What a high score means:** the stock is in a strong uptrend that has "
            "historically tended to *persist* (5-year validation: +0.41 rank correlation "
            "with staying in an uptrend over the following month).\n\n"
            "**What it does not mean:** the score is **not a direct forecast of future "
            "returns** (the same validation found only ≈ +0.04 correlation with next-month "
            "returns). A strong trend can drift sideways; a weak one can rebound. Use the "
            "score to assess trend health, then apply your own entry, risk and position "
            "rules. Not SEBI-registered investment advice."
        )


def render_regime_reliability_note() -> None:
    """VIX-regime reliability note for score surfaces.

    The 5-year regime study found score rankings work mildly in calm/normal
    regimes but degrade and even invert during elevated-fear/high-VIX periods
    (Spearman vs 60-day forward return: complacency +0.12 → fear −0.11).
    This renderer surfaces that finding next to live scores, using the existing
    VIX plumbing. Read-only; degrades silently if VIX is unavailable.
    """
    try:
        from utils.vix import get_india_vix_regime
        info = get_india_vix_regime() or {}
        regime = str(info.get("regime", "unknown")).lower()
        vix = info.get("vix")
        vix_txt = f" (India VIX {vix:.1f})" if isinstance(vix, (int, float)) else ""
    except Exception:
        return

    if regime in ("elevated", "fear", "panic"):
        st.warning(
            f"⚠️ **Reduced reliability in the current market regime{vix_txt}.** "
            "Historical testing (5-year study, 40,667 observations) shows trend-quality "
            "rankings become **less reliable — and can invert — during elevated-fear "
            "regimes**, when beaten-down stocks often rebound harder than trending ones. "
            "Interpret scores with additional caution and rely more on position sizing "
            "and stops.",
            icon="🌪️",
        )
    elif regime in ("normal", "complacency"):
        st.caption(
            f"🟢 Calm market regime{vix_txt} — historically the conditions where "
            "trend-quality rankings have been most informative (see Investor Guide → "
            "scores)."
        )
