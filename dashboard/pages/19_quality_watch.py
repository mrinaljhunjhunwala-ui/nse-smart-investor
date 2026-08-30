"""Quality Watch — Long-Term Holds (v3: numeric score + sizing/duration).

PURPOSE — this page is deliberately NOT another technical screener. Command
Centre, Smart Screener, and Tomorrow's Watchlist all rank by CompositeScore
(price/volume/momentum) — good for "what to trade this week", structurally
blind to governance/regulatory risk, and not meant for multi-month/year
holding decisions. This page ranks by a QUALITY SCORE (0-100) built from:

  1. Valuation posture (40 pts) — is the price justified by quality/growth
     (analysis/fundamentals/valuation_decision.py's ValuationAssessment)
  2. Confidence in that call (15 pts) — how much evidence backs the posture
  3. Governance safety (25 pts) — red/amber flags from
     analysis/qualitative_flags.py (NSE API + NSE RSS feeds + news) subtract
     from a full score; this is where regulatory/governance risk that
     technical scores structurally can't see actually bites
  4. Quality ratios (20 pts) — ROE, ROCE, Debt/Equity from the same
     fundamentals fetch already used for valuation

The full points breakdown is shown per stock — this is not a black box.
See _compute_quality_score() for the exact formula and _SCORE_WEIGHTS_DOC
for the rationale, mirroring how analysis/score.py documents its own
weights for the technical CompositeScore.

CompositeScore / technical momentum is intentionally NOT a factor.

DEEP DIVE — clicking a ranked stock expands, INLINE on this same page, a
full company deep-dive across 6 tabs: Financials, Peer Comparison,
Governance & Flags, News, Documents, and (v3) Sizing & Duration.

SIZING & DURATION (v3) — deliberately does NOT reuse the technical
CompositeScore's ATR-based stop-loss (that's built for a multi-week swing
and would stop you out on completely ordinary volatility for a hold meant
to last years). Instead: a WIDE technical safety-net level (well below the
200-day SMA) PLUS an explicit fundamental invalidation trigger (red-flag
accumulation / posture degradation) — because for a long hold, "the thesis
broke" is usually a better exit signal than "the price moved". Quantity
is NOT computed here — it hands off to the existing Position Sizer page
(Kelly / fixed-risk calculator) with entry + suggested stop pre-filled,
rather than maintaining a second, divergent sizing formula in this file.

PERFORMANCE — the ranking screen now runs in parallel (ThreadPoolExecutor,
matching the pattern used in research/score_efficacy.py) so a nifty500
scan is actually feasible from inside a Streamlit page load, not just
nifty50/100. The Deep Dive's heavier calls (quarterly statements, peers,
raw shareholding, documents, sizing) still run only for the one ticker
you click into — never across the whole universe.
"""
import os, sys
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

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
from dashboard.shared.trade_utils import _live_quote_price
from analysis.qualitative_flags import QualitativeFlag, summarize_flags

apply_design()
render_sidebar(current="Quality Watch")
render_top_bar()

st.title("🏆 Quality Watch — Long-Term Holds")
st.caption(
    "Ranked by a 0-100 Quality Score (valuation + governance safety + "
    "quality ratios) — not price momentum. This is the page for \"should "
    "I hold this for the long run\", not \"what's setting up to trade this "
    "week\" — see Command Centre or Smart Screener for that."
)

# FIX ANL-XREF — see the matching note in 04_analyze_stock.py.
with st.expander("↔️ Also see: Analyze Stock · Deep Dive", expanded=False):
    st.markdown(
        "Quality Watch answers \"is this a good name to sit in\". For \"how "
        "does the setup look right now\" go to **Analyze Stock**; for the full "
        "structural + valuation + thesis breakdown go to **Deep Dive**. "
        "The 8-factor swing-trade go/no-go now lives as an expander inside "
        "**Analyze Stock**."
    )

_POSTURE_COLOR = {
    "REASONABLE": "#26a69a",
    "SUPPORTED_BY_ROE": "#26a69a",
    "DEMANDING_VS_ROE": "#ffa726",
    "DEMANDING_VS_RETURNS": "#ffa726",
    "DEMANDING_VS_GROWTH": "#ffa726",
    "INSUFFICIENT_EVIDENCE": "#8899bb",
}

# ═══════════════════════════════════════════════════════════════════════════
# QUALITY SCORE — 0-100, transparent breakdown (documented in module docstring)
# ═══════════════════════════════════════════════════════════════════════════

_POSTURE_POINTS = {
    "REASONABLE": 40,
    "SUPPORTED_BY_ROE": 35,
    "DEMANDING_VS_ROE": 15,
    "DEMANDING_VS_RETURNS": 15,
    "DEMANDING_VS_GROWTH": 15,
    "INSUFFICIENT_EVIDENCE": 10,  # unknown isn't "bad" — scored neutral-low, not zero
}
_CONFIDENCE_POINTS = {"high": 15, "medium": 10, "low": 5, "none": 0}


def _compute_quality_score(posture, confidence, red_flags, amber_flags,
                           roe, roce, debt_to_equity) -> tuple:
    """Returns (score_0_to_100, breakdown_dict). Never raises — missing
    inputs are rescaled by the weight of what IS available (or given a
    neutral-low default if nothing is), never penalized as if they were
    the worst possible reading. See FIX QW1 below.
    """
    breakdown = {}

    breakdown["valuation_posture"] = _POSTURE_POINTS.get(posture, 10)
    breakdown["confidence"] = _CONFIDENCE_POINTS.get(confidence, 0)

    # Governance safety: start at 25, subtract per flag. Floors at 0 —
    # this is a penalty, not a score that can go negative.
    gov = 25 - (red_flags * 8) - (amber_flags * 3)
    breakdown["governance_safety"] = max(0, gov)

    # Quality ratios: ROE + ROCE + Debt/Equity, weighted up to 20 total.
    #
    # FIX QW1 — this used to add 0 for any metric that was None (Yahoo
    # coverage is patchy for small/mid-caps — see
    # analysis/fundamentals/providers/yahoo_fundamentals.py), so a stock
    # missing e.g. ROCE and D/E silently lost up to 13 of these 20 points
    # for a data-availability reason, not a quality reason — and this
    # score drives the Ranked Results sort order directly, with no
    # indication in that list of why. Missing data should reduce
    # confidence, not distort the ranking (same principle already applied
    # to `posture` below via INSUFFICIENT_EVIDENCE=10, and already
    # correctly done for the equivalent Portfolio quality score — see
    # analysis/portfolio_fundamentals.py compute_quality_score).
    #
    # Now rescaled by the weight of whichever metrics are actually present,
    # same technique as compute_quality_score. If none are available, use
    # a neutral-low default (10/20) rather than 0 — "unknown" isn't "bad".
    q = 0.0
    weight_used = 0.0
    if roe is not None:
        q += 7 if roe > 0.15 else (4 if roe > 0.10 else 1)
        weight_used += 7
    if roce is not None:
        q += 7 if roce > 0.15 else (4 if roce > 0.10 else 1)
        weight_used += 7
    if debt_to_equity is not None:
        q += 6 if debt_to_equity < 0.5 else (3 if debt_to_equity < 1.0 else 0)
        weight_used += 6
    if weight_used > 0:
        breakdown["quality_ratios"] = round(min(20.0, q * 20.0 / weight_used))
    else:
        breakdown["quality_ratios"] = 10

    total = sum(breakdown.values())
    return round(total), breakdown


@st.cache_data(ttl=4 * 60 * 60, show_spinner=False)
def _assess_one(ticker: str) -> dict:
    """Light per-ticker pipeline for the RANKING screen: annual fundamentals
    -> valuation context -> valuation assessment -> qualitative flags ->
    quality score. Returns a flat dict, never raises.
    """
    out = {
        "ticker": ticker, "company_name": None, "sector": None, "posture": None,
        "phrase": None, "confidence": None, "pe": None, "pb": None,
        "roe": None, "roce": None, "debt_to_equity": None,
        "red_flags": 0, "amber_flags": 0, "green_flags": 0,
        "quality_score": 0, "score_breakdown": {}, "error": None,
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

        r = cf.ratios
        out.update({
            "company_name": company_name,
            "sector": sector,
            "posture": va.posture,
            "phrase": va.phrase,
            "confidence": va.confidence,
            "pe": val_ctx.pe,
            "pb": val_ctx.pb,
            "roe": getattr(r, "roe", None) if r else None,
            "roce": getattr(r, "roce", None) if r else None,
            "debt_to_equity": getattr(r, "debt_to_equity", None) if r else None,
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

    score, breakdown = _compute_quality_score(
        out["posture"], out["confidence"], out["red_flags"], out["amber_flags"],
        out["roe"], out["roce"], out["debt_to_equity"],
    )
    out["quality_score"] = score
    out["score_breakdown"] = breakdown
    return out


@st.cache_data(ttl=4 * 60 * 60, show_spinner=False)
def _run_screen(tickers: tuple, max_workers: int = 12) -> pd.DataFrame:
    """Parallel scan — same ThreadPoolExecutor pattern as
    research/score_efficacy.py's _prepare_ticker fan-out. This is what
    makes a nifty500 scan feasible inside one Streamlit page load instead
    of only nifty50/100; the per-ticker work here is network-bound
    (fundamentals fetch + flags fetch), so threading gives a real speedup.
    """
    rows = []
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futs = {ex.submit(_assess_one, t): t for t in tickers}
        for fut in as_completed(futs):
            try:
                rows.append(fut.result())
            except Exception as e:
                t = futs[fut]
                rows.append({"ticker": t, "error": f"{type(e).__name__}: {e}",
                             "posture": None, "quality_score": 0})
    return pd.DataFrame(rows)


# ═══════════════════════════════════════════════════════════════════════════
# DEEP DIVE — heavy, on-demand, ONE ticker at a time
# ═══════════════════════════════════════════════════════════════════════════

@st.cache_data(ttl=6 * 60 * 60, show_spinner=False)
def _fetch_ratios_only(ticker: str) -> dict:
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


@st.cache_data(ttl=2 * 60 * 60, show_spinner=False)
def _fetch_long_term_stop_reference(ticker: str) -> dict:
    """Wide, long-term-appropriate technical reference — NOT the swing-
    trade ATR stop from analysis/score.py. Returns 52-week low and current
    SMA200 so the Sizing tab can suggest a level well below normal
    volatility, appropriate for a multi-year hold.
    """
    out = {"sma200": None, "low_52w": None, "current_price": None, "error": None}
    try:
        from data.fetcher import fetch_single
        from utils.indicators import add_all_indicators
        df = fetch_single(ticker, period="1y")
        if df is None or df.empty:
            out["error"] = "no price history returned"
            return out
        df = add_all_indicators(df, groups=["trend"])
        out["current_price"] = float(df["Close"].iloc[-1])
        out["low_52w"] = float(df["Low"].min())
        if "SMA_200" in df.columns and df["SMA_200"].notna().any():
            out["sma200"] = float(df["SMA_200"].dropna().iloc[-1])
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {e}"
        _log.debug("quality_watch: stop reference fetch failed for %s: %s", ticker, e)
    return out


def _duration_guidance(quality_score: int) -> tuple:
    """Quality-tiered holding-duration guidance. A long-term hold doesn't
    have a fixed exit DATE the way a swing trade does — the honest framing
    is a minimum horizon + review cadence tied to conviction, not a
    calendar date this app has no basis to predict.
    """
    if quality_score >= 80:
        return ("2-3+ years (core holding)",
                "High conviction — review each quarterly result, re-run "
                "this screen after any major news.", "#26a69a")
    if quality_score >= 60:
        return ("1-2 years",
                "Moderate conviction — review quarterly, re-check sooner "
                "if a red flag appears.", "#8bc34a")
    if quality_score >= 40:
        return ("6-12 months (provisional)",
                "Below-average conviction — treat as a smaller, provisional "
                "position; re-assess sooner rather than later.", "#ffa726")
    return ("Not a long-term-hold candidate right now",
            "Score is too low at current price/quality — reconsider, or "
            "wait for a better entry/improved fundamentals.", "#ef5350")


def _render_sizing_tab(ticker: str, quality_score: int, score_breakdown: dict):
    st.caption(
        "Deliberately different from the technical stop-loss elsewhere in "
        "this app — an ATR-based swing stop would trigger on completely "
        "ordinary volatility for a hold meant to last years. This uses a "
        "WIDE technical safety net plus a fundamental invalidation trigger."
    )

    with st.spinner("Fetching price reference…"):
        ref = _fetch_long_term_stop_reference(ticker)
    live_price = _live_quote_price(ticker) or ref.get("current_price")

    if not live_price:
        st.warning("Could not fetch a live/recent price for this ticker right now.")
        return

    c1, c2, c3 = st.columns(3)
    c1.metric("Current Price", f"₹{live_price:,.2f}")

    wide_stop = None
    if ref.get("sma200"):
        # 15% below the 200-day SMA — well outside normal swings, deliberately
        # not a tight technical stop. Documented rationale, not a magic number.
        wide_stop = ref["sma200"] * 0.85
    elif ref.get("low_52w"):
        wide_stop = ref["low_52w"] * 0.95

    if wide_stop:
        c2.metric("Suggested Wide Stop", f"₹{wide_stop:,.2f}",
                  f"{(wide_stop / live_price - 1) * 100:.1f}%")
    else:
        c2.metric("Suggested Wide Stop", "—")
        st.caption("Not enough price history to compute a reference level.")

    c3.metric("Quality Score", f"{quality_score}/100")

    st.markdown("---")
    st.markdown("##### 📅 Suggested Holding Duration")
    duration, note, color = _duration_guidance(quality_score)
    st.markdown(
        f'<div style="border-left:4px solid {color};padding:10px 14px;'
        f'background:#181818;border-radius:6px">'
        f'<b style="font-size:15px;color:{color}">{duration}</b>'
        f'<br><span style="font-size:13px;color:#ccc">{note}</span>'
        f'</div>', unsafe_allow_html=True,
    )

    st.markdown("---")
    st.markdown("##### ⚠️ Fundamental Invalidation Triggers")
    st.caption(
        "For a long hold, \"the thesis broke\" is usually a better exit "
        "signal than \"the price moved\". Re-assess this position if:"
    )
    st.markdown(
        "- **2 or more red flags** appear (currently: "
        f"{score_breakdown.get('governance_safety', 25) < 17 and 'already triggered' or 'not triggered'})\n"
        "- Valuation posture degrades to a DEMANDING_* category with LOW confidence\n"
        "- Quality Score falls below 40 on a re-run of this screen\n"
        "- Debt/Equity or ROE deteriorates sharply versus the figures shown "
        "in the Financials tab"
    )

    st.markdown("---")
    st.markdown("##### 🔢 Position Size")
    st.caption(
        "Quantity isn't computed here — it depends on your portfolio size "
        "and risk tolerance, which the dedicated Position Sizer already "
        "handles (Kelly Criterion + fixed-risk calculator). Sending your "
        "entry price and suggested stop there now."
    )
    if st.button("📐 Open in Position Sizer", key=f"qw_sizer_{ticker}"):
        st.session_state["ps_entry"] = round(live_price, 2)
        if wide_stop:
            st.session_state["ps_sl"] = round(wide_stop, 2)
        st.session_state["ps_tp"] = round(live_price * 1.25, 2)  # placeholder, user adjusts
        st.session_state["_goto_page"] = "📐 Position Sizer"
        st.rerun()

    with st.expander("Score breakdown (why this number)"):
        bd = score_breakdown
        st.markdown(
            f"- Valuation posture: **{bd.get('valuation_posture', 0)}/40**\n"
            f"- Confidence in that call: **{bd.get('confidence', 0)}/15**\n"
            f"- Governance safety (flags): **{bd.get('governance_safety', 0)}/25**\n"
            f"- Quality ratios (ROE/ROCE/D-E): **{bd.get('quality_ratios', 0)}/20**"
        )


def _fmt_cr(val) -> str:
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


def render_deep_dive(ticker: str, quality_score: int, score_breakdown: dict):
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
        st.markdown(f"### 🔎 {short} — {bundle.get('company_name') or 'Deep Dive'}  ·  "
                   f"**{quality_score}/100**")
        if bundle.get("sector"):
            st.caption(f"Sector: {bundle['sector']}")

    if bundle.get("error"):
        st.warning(f"Some fundamentals data failed to load: {bundle['error']}")

    tabs = st.tabs(["📊 Financials", "💰 Sizing & Duration", "👥 Peer Comparison",
                    "🏛️ Governance & Flags", "📰 News", "📄 Documents"])
    with tabs[0]:
        _render_financials_tab(bundle["cf_annual"], bundle["cf_quarterly"])
    with tabs[1]:
        _render_sizing_tab(ticker, quality_score, score_breakdown)
    with tabs[2]:
        _render_peers_tab(ticker, bundle.get("sector"))
    with tabs[3]:
        render_flag_strip(ticker, company_name=bundle.get("company_name"))
    with tabs[4]:
        _render_news_tab(ticker, bundle.get("company_name"))
    with tabs[5]:
        _render_documents_tab(bundle.get("documents") or [], bundle.get("corp_info") or {})


# ═══════════════════════════════════════════════════════════════════════════
# MAIN — ranking screen, or deep dive if a ticker is selected
# ═══════════════════════════════════════════════════════════════════════════

if st.session_state.get("_qw_selected_ticker"):
    _sel = st.session_state["_qw_selected_ticker"]
    _sel_score = st.session_state.get("_qw_selected_score", 0)
    _sel_breakdown = st.session_state.get("_qw_selected_breakdown", {})
    render_deep_dive(_sel, _sel_score, _sel_breakdown)
else:
    c1, c2, c3 = st.columns([2, 1, 1])
    with c1:
        universe_choice = st.selectbox(
            "Universe", options=["nifty50", "nifty100", "nifty500"], index=1,
            help="nifty500 now runs in parallel and is genuinely feasible, "
                 "but still expect ~3-6 minutes on first run. Cached for "
                 "4 hours after that.",
        )
    with c2:
        hide_red = st.checkbox("Hide red-flagged", value=False)
    with c3:
        run_clicked = st.button("🔍 Compute Now", type="primary")

    if universe_choice == "nifty500":
        st.caption(
            "⏱️ nifty500 scans ~500 tickers in parallel — expect a few "
            "minutes on first run. nifty100 is a faster middle ground."
        )

    if "_qw_last_universe" not in st.session_state:
        st.session_state["_qw_last_universe"] = None

    if run_clicked:
        _run_screen.clear()

    should_display = run_clicked or st.session_state["_qw_last_universe"] == universe_choice

    if not should_display:
        st.info(
            "Click **Compute Now** to run the screen. This fetches fundamentals, "
            "valuation, and qualitative flags for each ticker in the chosen "
            "universe and computes a 0-100 Quality Score — results are "
            "cached for 4 hours."
        )
    else:
        st.session_state["_qw_last_universe"] = universe_choice
        from data.universe import get_universe

        tickers = tuple(get_universe(universe_choice))
        with st.spinner(f"Screening {len(tickers)} tickers (parallel) for Quality Score…"):
            df = _run_screen(tickers)

        if df.empty:
            st.warning("No results — screen returned nothing.")
        else:
            n_errors = int(df["error"].notna().sum()) if "error" in df.columns else 0
            if n_errors:
                st.caption(
                    f"ℹ️ {n_errors}/{len(df)} tickers had a fetch error and are "
                    f"excluded from ranking below (shown at the bottom for "
                    f"visibility, not silently dropped)."
                )

            ranked = df[df["posture"].notna()].copy()
            errored = df[df["posture"].isna()].copy()

            if hide_red:
                ranked = ranked[ranked["red_flags"] == 0]

            ranked = ranked.sort_values(by="quality_score", ascending=False)

            st.markdown("---")
            st.subheader(f"📋 Ranked Results ({len(ranked)} of {len(df)})")
            st.caption(
                "Sorted by Quality Score (0-100), highest first. Technical "
                "momentum is NOT a factor. Click **Deep Dive** for the full "
                "picture including suggested sizing/duration for that stock."
            )

            for _, row in ranked.iterrows():
                short = row["ticker"].replace(".NS", "")
                color = _POSTURE_COLOR.get(row["posture"], "#8899bb")
                score = int(row["quality_score"])
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
                        f'<b style="font-size:18px;color:{color}">{score}</b>'
                        f'<span style="font-size:11px;color:#777">/100</span>  '
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
                        st.session_state["_qw_selected_score"] = score
                        st.session_state["_qw_selected_breakdown"] = row["score_breakdown"]
                        st.rerun()
                with btn_col2:
                    if st.button("📊 Analyze", key=f"qw_analyze_{row['ticker']}",
                                  use_container_width=True):
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
                "**Quality Score breakdown:** valuation posture (40pts) + "
                "confidence (15pts) + governance safety from flags (25pts, "
                "penalized per red/amber flag) + quality ratios: ROE/ROCE/"
                "Debt-Equity (20pts). Open a Deep Dive for the exact "
                "breakdown on any stock."
            )
