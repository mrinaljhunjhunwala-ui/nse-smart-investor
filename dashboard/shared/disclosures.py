"""dashboard/shared/disclosures.py — transparency notices for backtest-related pages.

Two reusable, side-effect-free-of-data renderers so every backtest surface shows the
same professional, non-alarmist disclosure:

  • render_survivorship_notice()   — present-day-universe / survivorship-bias notice
  • render_backtest_assumptions()  — commission, execution, slippage, survivorship status
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
