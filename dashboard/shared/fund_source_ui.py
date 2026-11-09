"""Fundamentals source picker for Analyze Stock.

Default ("Auto") keeps Yahoo → Screener. The two official-filing sources make a
stored XBRL filing the primary provider, with Yahoo/Screener only filling the
fields a filing lacks (price ratios, older years):
  * Exchange filing (NSE XBRL) — fetched on demand from NSE.
  * ROC filing (MCA upload)    — the owner uploads the AOC-4 XBRL from MCA21.
Returns the chosen source key ("auto" | "exchange" | "roc").
"""
from __future__ import annotations

import streamlit as st

_LABELS = {
    "auto": "Auto (Yahoo + Screener)",
    "exchange": "Exchange filing (NSE XBRL)",
    "roc": "ROC filing (MCA upload)",
}


def render_fund_source_picker(ticker: str) -> str:
    from analysis.fundamentals.providers.filing_fundamentals import load_filing

    src = st.radio("Fundamentals source", list(_LABELS), format_func=_LABELS.get,
                   horizontal=True, key=f"fund_src_{ticker}")
    if src == "auto":
        return src

    rec = load_filing(src, ticker)
    if rec:
        years = ", ".join(p["period_end"][:4] for p in rec["periods"][:5])
        kind = {True: "consolidated", False: "standalone"}.get(rec.get("consolidated"), "")
        st.caption(f"On record: **{len(rec['periods'])} year(s)** ({years}) "
                   f"{'· ' + kind if kind else ''} · file `{rec.get('file_name') or '—'}` · "
                   f"saved {str(rec.get('saved_at', ''))[:10]}. Filing figures come first; "
                   "Yahoo/Screener fill only what the filing doesn't carry (price ratios, older years).")

    if src == "exchange":
        if st.button("⬇️ Fetch latest annual filing from NSE", key=f"fund_nse_{ticker}"):
            from data.nse_filings_xbrl import fetch_exchange_filing
            with st.spinner("Fetching the XBRL filing from NSE…"):
                res = fetch_exchange_filing(ticker)
            (st.success if res["ok"] else st.warning)(res["message"])
            if res["ok"]:
                rec = res["record"]
                _refresh()
    else:
        st.caption("Download the company's **AOC-4 XBRL** (financial statements) from the MCA21 "
                   "portal — *View Public Documents* needs an MCA login and a small per-document "
                   "fee — then upload the `.xml` here. Each upload adds its years to this stock's record.")
        up = st.file_uploader("ROC / MCA XBRL file", type=["xml", "xbrl"], key=f"fund_roc_{ticker}")
        if up is not None and st.button("Save this filing", key=f"fund_roc_save_{ticker}"):
            from analysis.fundamentals.providers.filing_fundamentals import save_filing
            from analysis.fundamentals.xbrl_filing import parse_xbrl
            try:
                parsed = parse_xbrl(up.getvalue())
                rec = save_filing("roc", ticker, parsed, file_name=up.name)
                for w in parsed.get("warnings", []):
                    st.caption(f"⚠️ {w}")
                st.success(f"Saved {len(parsed['periods'])} year(s) from {up.name} "
                           f"(latest year ending {rec['periods'][0]['period_end']}).")
                _refresh()
            except Exception as e:
                st.warning(f"Couldn't read that file: {e}")
    if not rec:
        st.info("No filing saved for this stock yet — showing the automatic sources until one is added.")
    return src


def _refresh() -> None:
    from analysis.fundamentals.service import forget_source
    forget_source()
