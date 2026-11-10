"""dashboard/shared/breadth_panel.py — NSE-wide (bhavcopy) breadth panel.

Moved out of Command Centre on 2026-11-09: the full panel now renders on
Markets → Breadth & Macro → Breadth, and Command Centre shows one compact line
(`summary_line`) with a link to Markets instead of the full panel plus the
sectoral-index heatmap. Descriptive only (CLAUDE.md rule 1).
"""
from __future__ import annotations

import datetime as _dt
import html as _html
import logging

import streamlit as st

_log = logging.getLogger("dashboard.breadth_panel")

# Nifty sectoral indices used for the one-line sector read (label in the
# index strip -> short name).
SECTOR_IDX = [("BANK NIFTY", "Bank"), ("NIFTY IT", "IT"), ("NIFTY AUTO", "Auto"),
              ("NIFTY FMCG", "FMCG"), ("NIFTY PHARMA", "Pharma"), ("NIFTY METAL", "Metal"),
              ("NIFTY ENERGY", "Energy")]


def fmt_pct(v) -> str:
    return f"{v:.0f}%" if isinstance(v, (int, float)) else "–"


def breadth_provenance(b: dict) -> str:
    """'as of 08 Oct · niftytotalmarket, 825 stocks' (escaped, small header text)."""
    try:
        asof = _dt.date.fromisoformat(str(b.get("date"))[:10]).strftime("%d %b")
    except Exception:
        asof = str(b.get("date") or "?")
    uni = b.get("universe") or ("all EQ" if b.get("source") == "bhavcopy" else "?")
    size = b.get("universe_size")
    tail = f", {int(size):,} stocks" if isinstance(size, (int, float)) else ""
    src = "bhavcopy" if b.get("source") == "bhavcopy" else "scan"
    return _html.escape(f"as of {asof} · {uni}{tail} · {src}")


def load_breadth():
    """Cached bhavcopy breadth dict, or None when unavailable."""
    try:
        from dashboard.shared.cache import get_market_breadth
        return get_market_breadth()
    except Exception as e:
        _log.debug("breadth unavailable: %s", e)
        return None


def render_breadth_panel(regime_label: str) -> None:
    """Full NSE breadth panel: A/D, share above 20/50/200 DMA, 52W highs/lows,
    and whether breadth agrees with the regime label."""
    from analysis.market_breadth import breadth_agreement
    from dashboard.shared.ui_components import chip_pill, gate_strip, section_header
    b = load_breadth()
    if not b:
        st.markdown(section_header("NSE breadth", "all EQ stocks · bhavcopy"), unsafe_allow_html=True)
        st.caption("Breadth unavailable: not enough bhavcopy sessions cached yet.")
        return
    st.markdown(section_header("NSE breadth", breadth_provenance(b)), unsafe_allow_html=True)
    _ad = b.get("ad_ratio")
    _hi, _lo = b.get("new_52w_highs"), b.get("new_52w_lows")
    cells = [
        ("Adv / Dec", f"{b['advances']:,} / {b['declines']:,}",
         f"A/D {_ad:.2f}" if isinstance(_ad, (int, float)) else "A/D –"),
        ("Above 20DMA", fmt_pct(b.get("pct_above_20dma")), "share of stocks"),
        ("Above 50DMA", fmt_pct(b.get("pct_above_50dma")), "share of stocks"),
        ("Above 200DMA", fmt_pct(b.get("pct_above_200dma")), "share of stocks"),
        ("52W highs / lows",
         f"{int(_hi)} / {int(_lo)}" if isinstance(_hi, (int, float)) and isinstance(_lo, (int, float)) else "–",
         "close-based"),
    ]
    st.markdown(gate_strip(cells), unsafe_allow_html=True)
    agree = breadth_agreement(regime_label, b.get("breadth_label"), b.get("pct_above_50dma"))
    tone = {"MATCH": "good", "MISMATCH": "warn"}.get(agree["status"], "neutral")
    st.markdown(
        f'<div style="font-size:12px;color:var(--dim);margin:4px 0 12px">'
        f'{chip_pill(agree["status"], tone=tone)} {_html.escape(agree["text"])}'
        f' · breadth reads <b>{_html.escape(str(b.get("breadth_label", "unknown")))}</b></div>',
        unsafe_allow_html=True,
    )


def summary_line(b, idx: dict) -> str:
    """One escaped line: breadth numbers + strongest / weakest sector index.

    `b` is the breadth dict (or None); `idx` maps index-strip labels to
    (price, 1-day change %)."""
    bits = []
    if b:
        _ad = b.get("ad_ratio")
        try:
            bits.append(f"Adv / Dec {int(b['advances']):,} / {int(b['declines']):,}"
                        + (f" (A/D {_ad:.2f})" if isinstance(_ad, (int, float)) else ""))
        except (KeyError, TypeError, ValueError):
            pass
        if isinstance(b.get("pct_above_50dma"), (int, float)):
            bits.append(f"{b['pct_above_50dma']:.0f}% above 50DMA")
        if b.get("breadth_label"):
            bits.append(f"breadth reads {b['breadth_label']}")
    else:
        bits.append("NSE breadth unavailable")
    rows = [(name, idx[lbl][1]) for lbl, name in SECTOR_IDX
            if lbl in idx and isinstance(idx[lbl][1], (int, float))]
    if rows:
        rows.sort(key=lambda r: -r[1])
        best, worst = rows[0], rows[-1]
        bits.append(f"sectors: {best[0]} {best[1]:+.2f}% strongest, {worst[0]} {worst[1]:+.2f}% weakest")
    else:
        bits.append("sector index quotes unavailable")
    return _html.escape(" · ".join(bits))
