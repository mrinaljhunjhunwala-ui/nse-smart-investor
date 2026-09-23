"""dashboard/shared/table_styles.py — shared dataframe patterns (P2 table upgrades).

Two patterns from the UI/UX backlog, used by My Portfolio (03), Smart
Screener (06), Backtest (08):

  * P&L table   — row background tinted by a return column, ▲/▼ arrow on
                  signed columns, bold weight on large moves, pinned first
                  column. Direction never relies on red/green alone (F7b).
  * Signal table — rank / posture / sector / score columns via
                  st.column_config, so result lists read at a glance.

Hex values live here (not in pages) because pandas Styler CSS is rendered
inside the glide-data-grid canvas, where `var(--bull)` doesn't resolve.
They mirror the design.py tokens: bull #16c784 · bear #ff4d4d.
"""
from __future__ import annotations

import math
from typing import Iterable, Optional

import pandas as pd
import streamlit as st

_BULL_RGB = (22, 199, 132)   # --bull
_BEAR_RGB = (255, 77, 77)    # --bear
_BULL = "#16c784"
_BEAR = "#ff4d4d"


def _num(v) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) else f


def arrow_fmt(decimals: int = 2, unit: str = "%", prefix: str = "",
              indian: bool = False):
    """Styler formatter: `▲ 1.23%` / `▼ ₹4,500`. Blank for missing values."""
    def _f(v):
        f = _num(v)
        if f is None:
            return "—"
        if indian:
            from dashboard.shared.ui_components import fmt_inr
            body = fmt_inr(abs(f), decimals)
        else:
            body = f"{abs(f):,.{decimals}f}"
        return f"{'▲' if f >= 0 else '▼'} {prefix}{body}{unit}"
    return _f


def signed_text_css(v, bold_at: float = float("inf")) -> str:
    """Cell text colour by sign; bold weight at |v| >= bold_at (F7b cue)."""
    f = _num(v)
    if f is None or f == 0:
        return ""
    css = f"color:{_BULL if f > 0 else _BEAR}"
    if abs(f) >= bold_at:
        css += "; font-weight:700"
    return css


def row_tint_css(v, full_at: float = 20.0, max_alpha: float = 0.16) -> str:
    """Row background: tinted toward bull/bear, alpha scaled by |v|/full_at."""
    f = _num(v)
    if f is None or f == 0:
        return ""
    r, g, b = _BULL_RGB if f > 0 else _BEAR_RGB
    a = max(0.04, min(abs(f) / full_at, 1.0) * max_alpha)
    return f"background-color: rgba({r},{g},{b},{a:.3f})"


def pnl_styler(df: pd.DataFrame,
               tint_col: str,
               signed_cols: Iterable[str],
               formats: Optional[dict] = None,
               bold_at: Optional[dict] = None,
               full_at: float = 20.0):
    """Build the P&L-table Styler.

    tint_col    — column whose sign/magnitude tints the whole row.
    signed_cols — columns that get sign colour (+ bold via bold_at[col]).
    formats     — Styler.format mapping; use arrow_fmt() for signed cols.
    """
    bold_at = bold_at or {}
    sty = df.style
    if formats:
        sty = sty.format(formats, na_rep="—")
    if tint_col in df.columns:
        sty = sty.apply(
            lambda row: [row_tint_css(row[tint_col], full_at)] * len(row),
            axis=1,
        )
    for c in signed_cols:
        if c in df.columns:
            _b = bold_at.get(c, float("inf"))
            sty = sty.map(lambda v, _b=_b: signed_text_css(v, _b), subset=[c])
    return sty


def pinned_text_col(label: Optional[str] = None, **kw):
    """TextColumn pinned to the left edge (sticky first column).

    `pinned` landed in Streamlit 1.45; requirements allow >=1.35, so fall
    back to an unpinned column rather than crash on older installs.
    """
    try:
        return st.column_config.TextColumn(label, pinned=True, **kw)
    except TypeError:
        return st.column_config.TextColumn(label, **kw)


def posture_label(action: str) -> str:
    """Honest display label (trade_utils._display_label). Those labels
    already carry ▲/▼ for directional postures; the neutral ones get a
    ◆/● glyph so every row has a shape cue, not just a colour."""
    from dashboard.shared.trade_utils import _display_label
    a = (action or "").upper().strip()
    lbl = _display_label(a) or "—"
    if "▲" in lbl or "▼" in lbl:
        return lbl
    return f"{'◆' if a == 'WATCHLIST' else '●'} {lbl}"
