"""Pure helpers for rendering backtest result tables (no Streamlit).

Column names come from backtest/runner.py ("Buy & Hold (%)") and
backtest/portfolio.py ("B&H (%)", "Alpha (%)").
"""
from __future__ import annotations

from typing import List, Optional

import pandas as pd

# Columns whose sign carries meaning (P&L-style: +/- arrows + colour).
_SIGNED_EXACT = {"Return (%)", "Return(%)", "B&H (%)", "Buy & Hold (%)", "Alpha (%)"}
# Count columns — shown as integers, never "{:.2f}".
_INTEGER_EXACT = {"# Trades", "Trades", "N", "n"}


def signed_columns(frame: pd.DataFrame, ret_col: Optional[str]) -> List[str]:
    return [c for c in frame.columns
            if c == ret_col or str(c) in _SIGNED_EXACT
            or any(k in str(c) for k in ("Buy & Hold", "Alpha", "Return"))]


def integer_columns(frame: pd.DataFrame) -> List[str]:
    return [c for c in frame.columns
            if str(c) in _INTEGER_EXACT or pd.api.types.is_integer_dtype(frame[c])]
