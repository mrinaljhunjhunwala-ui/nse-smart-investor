"""Quality Watch — Long-Term Holds (v2: adds inline Deep Dive).

PURPOSE — this page is deliberately NOT another technical screener. Command
Centre, Smart Screener, and Tomorrow's Watchlist all rank by CompositeScore
(price/volume/momentum) — good for "what to trade this week", structurally
blind to governance/regulatory risk, and not meant for multi-month/year
holding decisions. This page ranks by:

  1. Valuation quality (analysis/fundamentals/valuation_decision.py's
     ValuationAssessment posture — "is the price justified by quality/
     growth", not "is the chart breaking out")
  2. Qualitative flags (analysis/qualitative_flags.py — governance,
     regulatory, corporate-action, narrative signals from NSE filings +
     news) — these matter MORE over a long hold than a 2-week swing, so
     they're surfaced prominently here, not as an afterthought.

CompositeScore / technical momentum is intentionally NOT part of the
ranking on this page.

DEEP DIVE (v2) — clicking a ranked stock expands, INLINE on this same
page, a full company deep-dive: annual + quarterly P&L/balance sheet/
cash flow, ratio trend, peer comparison (auto same-sector default, with
manual override), shareholding pattern + governance/regulatory flags
(reusing the same panel from Analyze Stock), recent news, and filing
documents (attachment links NSE already returns alongside quarterly
results — no new fetcher needed, just surfacing data already pulled).

PERFORMANCE BOUNDARY — the ranking screen (_assess_one / _run_screen)
deliberately stays light: annual fundamentals + valuation + flags only,
across the whole chosen universe. The Deep Dive's heavier calls (quarterly
statements, peer fetches, raw shareholding table, documents) run ONLY for
the one ticker you click into, never across the whole universe — that
distinction is what keeps this page fast for 50-100 tickers at once.
"""
import os, sys
import logging

_log = logging.getLogger("dashboard.quality_watch")
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import streamlit as st
import pandas as pd

from dashboard.shared.design import apply_design
from dashboard.shared.nav import render_sidebar
from dashboard.shared.chart_helpers import render_top_bar
from dashboard.shared.flags_ui import get_cached_flags, render_flag_strip
from analysis.qualitative_flags import QualitativeFlag, summarize_flags

apply_design()
render_sidebar(current="Quality Watch")
render_top_bar()

st.title("🏆 Quality Watch — Long-Term Holds")
st.caption(
    "Ranked by valuation quality and governance safety, not price momentum. "
    "This is the page for \"should I hold this for the long run\", not "
    "\"what's setting up to trade this week\" — see Command Centre or "
    "Smart Screener for that."
)

# Posture favorability ordering — lower rank number = more favorable for a
# long-term hold. Mirrors ValuationAssessment.posture values from
# analysis/fundamentals/valuation_decision.py. Anything not listed here
# (a posture value added later that this page doesn't know about yet)
# sorts last rather than crashing.
_POSTURE_RANK = {
    "REASONABLE": 0,
    "SUPPORTED_BY_ROE": 1,
    "DEMANDING_VS_ROE": 2,
    "DEMANDING_VS_RETURNS": 2,
    "DEMANDING_VS_GROWTH": 2,
    "INSUFFICIENT_EVIDENCE": 3,
}
_CONFIDENCE_RANK = {"high": 0, "medium": 1, "low": 2, "none": 3}

_POSTURE_COLOR = {
    "REASONABLE": "#26a69a",
    "SUPPORTED_BY_ROE": "#26a69a",
    "DEMANDING_VS_ROE": "#ffa726",
    "DEMANDING_VS_RETURNS": "#ffa726",
    "DEMANDING_VS_GROWTH": "#ffa726",
    "INSUFFICIENT_EVIDENCE": "#8899bb",
}


@st.cache_data(ttl=4 * 60 * 60, show_spinner=False)
def _assess_one(ticker: str) -> dict:
    """Light per-ticker pipeline for the RANKING screen: annual fundamentals
    -> valuation context -> valuation assessment -> qualitative flags.
    Returns a flat dict, never raises — a single ticker's failure must not
    break the whole screen. Deliberately does NOT fetch quarterly data,
    peers, or raw shareholding tables — that's the Deep Dive's job, on-
    demand, for one ticker at a time (see module docstring).
    """
    out = {
        "ticker": ticker, "company_name": None, "sector": None, "posture": None,
        "phrase": None, "confidence": None, "pe": None, "pb": None,
        "red_flags": 0, "amber_flags": 0, "green_flags": 0, "error": None,
    }
    try:
        from analysis.fundamentals.service import default_service as _fund_service
        from analysis.fundamentals import analytics as _fund_analytics
        from analysis.fundamentals.valuation import build_valuation_context
        from analysis.fundamentals.valuation_decision import assess_valuation
        from analysis.sector_classification import classify_sector
        from data.universe import get_sector

        cf = _fund_service().get_fundamentals(ticker)
        company_name = getattr(cf, "company_name", None)
        sector = get_sector(ticker)
        sector_profile = classify_sector(sector, name=company_name)
        val_ctx = build_valuation_context(cf, sector_profile=sector_profile)
        analytics_res = _fund_analytics.compute_all(cf)
        va = assess_valuation(val_ctx, analytics_res, sector_profile, cf=cf)

        out.update({
            "company_name": company_name,
            "sector": sector,
            "posture": va.posture,
            "phrase": va.phrase,
            "confidence": va.confidence,
            "pe": val_ctx.pe,
            "pb": val_ctx.pb,
        })
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {e}"
        _log.debug("quality_watch: fundamentals/valuation failed for %s: %s", ticker, e)

    try:
        raw_flags = get_cached_flags(ticker, out.get("company_name"))
        flags = [QualitativeFlag.from_dict(d) for d in raw_flags]
        counts = summarize_flags(flags)
        out["red_flags"] = counts["red"]
        out["amber_flags"] = counts["amber"]
        out["green_flags"] = counts["green"]
    except Exception as e:
        _log.debug("quality_watch: flags failed for %s: %s", ticker, e)

    return out


@st.cache_data(ttl=4 * 60 * 60, show_spinner=False)
def _run_screen(tickers: tuple) -> pd.DataFrame:
    rows = [_assess_one(t) for t in tickers]
    return pd.DataFrame(rows)


# ═══════════════════════════════════════════════════════════════════════════
# DEEP DIVE — heavy, on-demand, ONE ticker at a time
# ═══════════════════════════════════════════════════════════════════════════

@st.cache_data(ttl=6 * 60 * 60, show_spinner=False)
def _fetch_ratios_only(ticker: str) -> dict:
    """Lightweight ratio fetch for peer comparison rows — reuses the same
    cached FundamentalsService call the ranking screen already makes (no
    duplicate network cost if a peer was already screened), just extracts
    the ratio snapshot instead of running full valuation logic."""
    try:
        from analysis.fundamentals.service import default_service as _fund_service
        cf = _fund_service().get_fundamentals(ticker)
        r = cf.ratios
        return {
            "ticker": ticker,
            "company_name": getattr(cf, "company_name", None),
            "pe": getattr(r, "pe", None) if r else None,
            "pb": getattr(r, "pb", None) if r else None,
            "roe": getattr(r, "roe", None) if r else None,
            "roce": getattr(r, "roce", None) if r else None,
            "debt_to_equity": getattr(r, "debt_to_equity", None) if r else None,
            "net_margin": getattr(r, "net_margin", None) if r else None,
        }
    except Exception as e:
        _log.debug("quality_watch: peer ratio fetch failed for %s: %s", ticker, e)
        return {"ticker": ticker, "company_name": None, "pe": None, "pb": None,
                "roe": None, "roce": None, "debt_to_equity": None, "net_margin": None}


@st.cache_data(ttl=6 * 60 * 60, show_spinner=False)
def _deep_dive_bundle(ticker: str) -> dict:
    """Everything the Deep Dive needs for ONE ticker, fetched once and
    cached. Never raises — each section degrades independently so one
    failure (e.g. NSE blocked) doesn't blank the whole view.
    """
    bundle = {
        "cf_annual": None, "cf_quarterly": None, "company_name": None,
        "sector": None, "corp_info": {}, "documents": [], "error": None,
    }
    try:
        from analysis.fundamentals.service import default_service as _fund_service
        from data.universe import get_sector

        bundle["cf_annual"] = _fund_service().get_fundamentals(ticker, period="annual")
        bundle["cf_quarterly"] = _fund_service().get_fundamentals(ticker, period="quarterly")
        bundle["company_name"] = getattr(bundle["cf_annual"], "company_name", None)
        bundle["sector"] = get_sector(ticker)
    except Exception as e:
        bundle["error"] = f"{type(e).__name__}: {e}"
        _log.warning("quality_watch deep dive: fundamentals failed for %s: %s", ticker, e)

    try:
        from data.nse_corp_info import get_corp_info
        corp_info = get_corp_info(ticker)
        bundle["corp_info"] = corp_info
        # Documents: NSE's financial_results entries carry attachment links
        # alongside the result itself — data already fetched for governance
        # flags, just not surfaced yet. xbrl_attachment / na_attachment can
        # both be null; skip entries with neither.
        docs = []
        for item in (corp_info.get("financial_results") or {}).get("data") or []:
            xbrl = item.get("xbrl_attachment")
            na = item.get("na_attachment")
            if not xbrl and not na:
                continue
            docs.append({
                "period": item.get("toDate") or item.get("period") or "",
                "xbrl_attachment": xbrl,
                "na_attachment": na,
            })
        bundle["documents"] = docs
    except Exception as e:
        _log.debug("quality_watch deep dive: corp_info/documents failed for %s: %s", ticker, e)

    return bundle


def _fmt_cr(val) -> str:
    """Format a raw rupee figure as ₹ crores, 2dp. None-safe."""
    if val is None or pd.isna(val):
        return "—"
    return f"₹{val / 1e7:,.1f} Cr"


def _fmt_pct(val) -> str:
    if val is None or pd.isna(val):
        return "—"
    return f"{val * 100:.1f}%"


def _fmt_x(val) -> str:
    if val is None or pd.isna(val):
        return "—"
    return f"{val:.2f}x"


def _render_financials_tab(cf_annual, cf_quarterly):
    period_choice = st.radio("Period", ["Annual", "Quarterly"], horizontal=True,
                              key="qw_dd_period")
    cf = cf_quarterly if period_choice == "Quarterly" else cf_annual
    if cf is None or not cf.has_any_data():
        st.warning(f"No {period_choice.lower()} fundamentals data available for this ticker.")
        return

    if cf.is_partial and cf.missing_fields:
        st.caption(f"ℹ️ Partial data — missing: {', '.join(cf.missing_fields[:8])}"
                   + (" …" if len(cf.missing_fields) > 8 else ""))

    st.markdown("##### Income Statement")
    if cf.income_statements:
        rows = []
        for stmt in cf.income_statements[:8]:
            rows.append({
                "Period": stmt.period.period_end.isoformat() if stmt.period.period_end else "—",
                "Revenue": _fmt_cr(stmt.revenue),
                "Gross Profit": _fmt_cr(stmt.gross_profit),
                "EBITDA": _fmt_cr(stmt.ebitda),
                "Net Income": _fmt_cr(stmt.net_income),
                "EPS (diluted)": f"{stmt.eps_diluted:.2f}" if stmt.eps_diluted else "—",
            })
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    else:
        st.caption("No income statement data.")

    st.markdown("##### Balance Sheet")
    if cf.balance_sheets:
        rows = []
        for stmt in cf.balance_sheets[:8]:
            rows.append({
                "Period": stmt.period.period_end.isoformat() if stmt.period.period_end else "—",
                "Total Assets": _fmt_cr(stmt.total_assets),
                "Total Debt": _fmt_cr(stmt.total_debt),
                "Cash": _fmt_cr(stmt.cash_and_equivalents),
                "Total Equity": _fmt_cr(stmt.total_equity),
            })
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    else:
        st.caption("No balance sheet data.")

    st.markdown("##### Cash Flow")
    if cf.cash_flows:
        rows = []
        for stmt in cf.cash_flows[:8]:
            rows.append({
                "Period": stmt.period.period_end.isoformat() if stmt.period.period_end else "—",
                "Operating CF": _fmt_cr(stmt.operating_cash_flow),
                "CapEx": _fmt_cr(stmt.capital_expenditure),
                "Free Cash Flow": _fmt_cr(stmt.free_cash_flow),
                "Dividends Paid": _fmt_cr(stmt.dividends_paid),
            })
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    else:
        st.caption("No cash flow data.")

    st.markdown("##### Key Ratios (latest)")
    r = cf.ratios
    if r:
        rc1, rc2, rc3, rc4 = st.columns(4)
        rc1.metric("ROE", _fmt_pct(r.roe))
        rc2.metric("ROCE", _fmt_pct(r.roce))
        rc3.metric("Debt/Equity", _fmt_x(r.debt_to_equity))
        rc4.metric("Net Margin", _fmt_pct(r.net_margin))
        rc5, rc6, rc7 = st.columns(3)
        rc5.metric("P/E", _fmt_x(r.pe))
        rc6.metric("P/B", _fmt_x(r.pb))
        rc7.metric("Current Ratio", _fmt_x(r.current_ratio))
    else:
        st.caption("No ratio data.")


def _render_peers_tab(ticker: str, sector: str):
    from data.universe import get_tickers_by_sector

    auto_peers = [t for t in get_tickers_by_sector(sector) if t != ticker][:6] if sector else []
    st.caption(
        f"Auto peers from sector **{sector or 'Unknown'}** (up to 6). "
        f"Add or remove tickers below — comparison recomputes on change."
    )
    manual_extra = st.text_input(
        "Add extra peer ticker(s), comma-separated (e.g. TCS.NS, INFY.NS)",
        key=f"qw_peer_extra_{ticker}",
    )
    extra = [t.strip().upper() for t in manual_extra.split(",") if t.strip()]
    extra = [t if t.endswith(".NS") else t + ".NS" for t in extra]
    peer_pool = st.multiselect(
        "Peers to compare", options=sorted(set(auto_peers + extra)),
        default=auto_peers, key=f"qw_peer_select_{ticker}",
    )

    if not peer_pool:
        st.info("No peers selected — pick some above, or leave the auto-detected default.")
        return

    with st.spinner(f"Fetching ratios for {len(peer_pool) + 1} companies…"):
        rows = [_fetch_ratios_only(ticker)] + [_fetch_ratios_only(p) for p in peer_pool]

    df = pd.DataFrame(rows)
    df_disp = pd.DataFrame({
        "Ticker": [t.replace(".NS", "") for t in df["ticker"]],
        "Company": df["company_name"].fillna("—"),
        "P/E": df["pe"].apply(_fmt_x),
        "P/B": df["pb"].apply(_fmt_x),
        "ROE": df["roe"].apply(_fmt_pct),
        "ROCE": df["roce"].apply(_fmt_pct),
        "Debt/Equity": df["debt_to_equity"].apply(_fmt_x),
        "Net Margin": df["net_margin"].apply(_fmt_pct),
    })
    # Highlight the focal ticker's row visually via bold in a fresh column
    # rather than relying on styler complexity across an all-string frame.
    df_disp.loc[0, "Ticker"] = f"⭐ {df_disp.loc[0, 'Ticker']}"
    st.dataframe(df_disp, hide_index=True, width="stretch")
    st.caption("⭐ = the stock you're viewing. Ratios are latest-available, annual basis.")


def _render_documents_tab(documents: list, corp_info: dict):
    if documents:
        st.markdown("##### Quarterly Result Filings")
        for doc in documents[:12]:
            links = []
            if doc.get("xbrl_attachment"):
                links.append(f"[XBRL]({doc['xbrl_attachment']})")
            if doc.get("na_attachment"):
                links.append(f"[Notes]({doc['na_attachment']})")
            st.markdown(f"- **{doc.get('period', 'Unknown period')}** — " + " · ".join(links))
    else:
        st.info(
            "No filing documents surfaced for this ticker right now — this "
            "may mean NSE's fetch was blocked (see the Governance & Flags "
            "tab for the diagnostic) rather than there being no filings."
        )

    board = (corp_info.get("borad_meeting") or {}).get("data") or []
    if board:
        st.markdown("##### Recent Board Meetings")
        rows = [{"Date": b.get("meetingdate", "—"), "Purpose": b.get("purpose", "—")}
                for b in board[:8]]
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")


def _render_news_tab(ticker: str, company_name: str):
    from data.news_feed import fetch_news
    with st.spinner("Fetching recent news…"):
        items = fetch_news(ticker, company_name=company_name)
    if not items:
        st.info("No recent news items found for this ticker.")
        return
    for item in items[:10]:
        st.markdown(
            f"- [{item['title']}]({item['link']}) "
            f"— *{item.get('source', 'Google News')}*"
            + (f" · {item['pub_date'][:16]}" if item.get("pub_date") else "")
        )


def render_deep_dive(ticker: str):
    st.markdown("---")
    back_col, title_col = st.columns([1, 5])
    with back_col:
        if st.button("← Back to list"):
            st.session_state.pop("_qw_selected_ticker", None)
            st.rerun()

    with st.spinner(f"Loading deep dive for {ticker}…"):
        bundle = _deep_dive_bundle(ticker)

    short = ticker.replace(".NS", "")
    with title_col:
        st.markdown(f"### 🔎 {short} — {bundle.get('company_name') or 'Deep Dive'}")
        if bundle.get("sector"):
            st.caption(f"Sector: {bundle['sector']}")

    if bundle.get("error"):
        st.warning(f"Some fundamentals data failed to load: {bundle['error']}")

    tabs = st.tabs(["📊 Financials", "👥 Peer Comparison", "🏛️ Governance & Flags",
                    "📰 News", "📄 Documents"])
    with tabs[0]:
        _render_financials_tab(bundle["cf_annual"], bundle["cf_quarterly"])
    with tabs[1]:
        _render_peers_tab(ticker, bundle.get("sector"))
    with tabs[2]:
        render_flag_strip(ticker, company_name=bundle.get("company_name"))
    with tabs[3]:
        _render_news_tab(ticker, bundle.get("company_name"))
    with tabs[4]:
        _render_documents_tab(bundle.get("documents") or [], bundle.get("corp_info") or {})


# ═══════════════════════════════════════════════════════════════════════════
# MAIN — ranking screen, or deep dive if a ticker is selected
# ═══════════════════════════════════════════════════════════════════════════

if st.session_state.get("_qw_selected_ticker"):
    render_deep_dive(st.session_state["_qw_selected_ticker"])
else:
    c1, c2, c3 = st.columns([2, 1, 1])
    with c1:
        universe_choice = st.selectbox(
            "Universe", options=["nifty50", "nifty100"], index=0,
            help="Kept modest by default — this page runs a real fundamentals + "
                 "valuation compute per ticker (network + CPU cost), not a "
                 "lightweight price scan.",
        )
    with c2:
        hide_red = st.checkbox("Hide red-flagged", value=False)
    with c3:
        run_clicked = st.button("🔍 Compute Now", type="primary")

    if "_qw_last_universe" not in st.session_state:
        st.session_state["_qw_last_universe"] = None

    if run_clicked:
        _run_screen.clear()

    should_display = run_clicked or st.session_state["_qw_last_universe"] == universe_choice

    if not should_display:
        st.info(
            "Click **Compute Now** to run the screen. This fetches fundamentals "
            "and valuation for each ticker in the chosen universe plus "
            "qualitative flags — results are cached for 4 hours."
        )
    else:
        st.session_state["_qw_last_universe"] = universe_choice
        from data.universe import get_universe

        tickers = tuple(get_universe(universe_choice))
        with st.spinner(f"Screening {len(tickers)} tickers for valuation quality + flags…"):
            df = _run_screen(tickers)

        if df.empty:
            st.warning("No results — screen returned nothing.")
        else:
            n_errors = int(df["error"].notna().sum())
            if n_errors:
                st.caption(
                    f"ℹ️ {n_errors}/{len(df)} tickers had a fundamentals/valuation "
                    f"fetch error and are excluded from ranking below (shown at "
                    f"the bottom for visibility, not silently dropped)."
                )

            ranked = df[df["posture"].notna()].copy()
            errored = df[df["posture"].isna()].copy()

            if hide_red:
                ranked = ranked[ranked["red_flags"] == 0]

            ranked["_posture_rank"] = ranked["posture"].map(_POSTURE_RANK).fillna(9)
            ranked["_conf_rank"] = ranked["confidence"].map(_CONFIDENCE_RANK).fillna(9)
            ranked = ranked.sort_values(
                by=["_posture_rank", "red_flags", "_conf_rank"],
                ascending=[True, True, True],
            )

            st.markdown("---")
            st.subheader(f"📋 Ranked Results ({len(ranked)} of {len(df)})")
            st.caption(
                "Sorted by: valuation posture (reasonable → demanding) first, "
                "then fewest red flags, then confidence. Technical momentum is "
                "NOT a factor in this ranking. Click a card to open its full "
                "Deep Dive — financials, peers, governance, news, documents."
            )

            for _, row in ranked.iterrows():
                short = row["ticker"].replace(".NS", "")
                color = _POSTURE_COLOR.get(row["posture"], "#8899bb")
                flag_bits = []
                if row["red_flags"]:
                    flag_bits.append(f"🔴 {int(row['red_flags'])}")
                if row["amber_flags"]:
                    flag_bits.append(f"🟡 {int(row['amber_flags'])}")
                if row["green_flags"]:
                    flag_bits.append(f"🟢 {int(row['green_flags'])}")
                flag_str = "  ".join(flag_bits) if flag_bits else "no flags"

                card_col, btn_col1, btn_col2 = st.columns([4, 1, 1])
                with card_col:
                    st.markdown(
                        f'<div style="border-left:4px solid {color};padding:10px 14px;'
                        f'margin:4px 0;background:#181818;border-radius:6px">'
                        f'<b style="font-size:15px">{short}</b>'
                        f'<span style="color:#999;font-size:12px"> '
                        f'{row.get("company_name") or ""}</span>'
                        f'<span style="float:right;font-size:12px;color:#ccc">{flag_str}</span>'
                        f'<br><span style="font-size:13px;color:{color}">{row["phrase"]}</span>'
                        f'<br><span style="font-size:11px;color:#777">'
                        f'confidence: {row["confidence"]}'
                        + (f' · P/E {row["pe"]:.1f}x' if pd.notna(row["pe"]) else '')
                        + (f' · P/B {row["pb"]:.1f}x' if pd.notna(row["pb"]) else '')
                        + '</span></div>',
                        unsafe_allow_html=True,
                    )
                with btn_col1:
                    if st.button("🔎 Deep Dive", key=f"qw_dd_{row['ticker']}",
                                  use_container_width=True):
                        st.session_state["_qw_selected_ticker"] = row["ticker"]
                        st.rerun()
                with btn_col2:
                    if st.button("📊 Analyze", key=f"qw_analyze_{row['ticker']}",
                                  use_container_width=True):
                        # FIX NAV1: canonical analyze_ticker hand-off key —
                        # see 04_analyze_stock.py's FIX A8.
                        st.session_state["analyze_ticker"] = row["ticker"]
                        st.session_state["_goto_page"] = "🔍 Analyze Stock"
                        st.rerun()

            if not errored.empty:
                with st.expander(f"⚠️ {len(errored)} ticker(s) with fetch errors"):
                    st.dataframe(
                        errored[["ticker", "error"]].reset_index(drop=True),
                        hide_index=True,
                    )

            st.markdown("---")
            st.caption(
                "**Posture legend:** REASONABLE / SUPPORTED_BY_ROE — valuation "
                "looks justified by quality or growth. DEMANDING_VS_* — pricier "
                "than fundamentals currently support (not necessarily wrong, "
                "just paying up). INSUFFICIENT_EVIDENCE — not enough data to "
                "judge; treat as unknown, not as a red flag itself."
            )
