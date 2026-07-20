"""Deep Dive Analysis - NSE Smart Investor (multipage page).

FIX MERGE1/NEW1: this page is new (page 20). It doesn't scan a universe or
run on a schedule — it's an on-demand, single-stock deep dive that combines
everything the app already computes (fundamentals, valuation, technicals,
governance/pledge flags, thesis verdict) with user-uploaded unstructured
documents (Annual Report, concall transcripts) that the app has no automated
source for.

FIX COST1: this page does NOT call an LLM API. Every other page in this app
runs on free market-data sources (yfinance/NSE/Stooq/Google News RSS) with
zero ongoing cost, and there's no genuine free tier for an LLM API at the
quality this kind of analysis needs — adding one here would make this the
app's first recurring paid dependency. Instead: this page assembles the
analyst prompt + everything already computed for the ticker, you run it in
a Claude conversation you already have access to (attaching your own PDFs
there), and paste the result back in to save it — see Step 1 / Step 2 below.
"""
import os, sys
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import datetime
import logging

import streamlit as st

from dashboard.shared.design import apply_design
from dashboard.shared.nav import render_sidebar
from dashboard.shared.chart_helpers import render_top_bar
from dashboard.shared.cache import get_composite_score
from dashboard.shared.flags_ui import get_cached_flags
from data.universe import resolve_ticker, get_sector
import trade_store as _store

_log = logging.getLogger("dashboard.deep_dive")

apply_design()
render_sidebar(current="Deep Dive Analysis")
render_top_bar()

st.title("📑 Deep Dive Analysis")
st.caption(
    "Get a structured, blunt equity-research read on one stock — fundamentals, "
    "management tone, valuation, technical structure, risks, and a final verdict. "
    "Everything the app already computes (fundamentals, valuation, technicals, "
    "governance/pledge flags, thesis verdict) is auto-filled as context below. "
    "This page doesn't call any LLM itself — it prepares the prompt, you run it "
    "in a Claude conversation with your own Annual Report / concall PDFs attached, "
    "then paste the result back here to save it with a date."
)

_DD_KV_USER = "default"   # matches trade_store's default single-user convention


# ═════════════════════════════════════════════════════════════════════════
# Ticker resolution — canonical analyze_ticker handoff pattern (FIX NAV1)
# ═════════════════════════════════════════════════════════════════════════
_prefill = st.session_state.pop("analyze_ticker", None)
ticker_input = st.text_input(
    "Ticker or company name", value=_prefill or "", key="dd_ticker_input",
    placeholder="e.g. RELIANCE or Reliance Industries",
)

if not ticker_input.strip():
    st.info("Enter a ticker above to begin.")
    st.stop()

try:
    ticker = resolve_ticker(ticker_input.strip())
except ValueError as e:
    st.error(str(e))
    st.stop()


# ═════════════════════════════════════════════════════════════════════════
# Auto-computed context — reuses the exact same functions Analyze Stock does
# ═════════════════════════════════════════════════════════════════════════
def _gather_context(tkr: str) -> dict:
    """Pull everything the app already computes for this ticker. Every piece
    degrades independently to None/empty on failure — one missing source
    (e.g. fundamentals provider down) never blocks the others."""
    ctx: dict = {
        "ticker": tkr, "cs": None, "sector_profile": None,
        "fundamentals": None, "valuation": None, "valuation_assessment": None,
        "thesis": None, "flags": [],
    }

    try:
        ctx["cs"] = get_composite_score(tkr)
    except Exception as e:
        _log.warning("deep_dive: get_composite_score failed for %s: %s", tkr, e)

    company_name = getattr(ctx["cs"], "company_name", None)
    sector_raw = get_sector(tkr)

    try:
        from analysis.sector_classification import classify_sector
        ctx["sector_profile"] = classify_sector(sector_raw, name=company_name)
    except Exception as e:
        _log.warning("deep_dive: classify_sector failed for %s: %s", tkr, e)

    cf = None
    try:
        from analysis.fundamentals.service import default_service as _fund_service
        cf = _fund_service().get_fundamentals(tkr)
        from analysis.fundamentals import analytics as _fund_analytics
        ctx["fundamentals"] = _fund_analytics.compute_all(cf, cagr_years=5)
    except Exception as e:
        _log.warning("deep_dive: fundamentals failed for %s: %s", tkr, e)

    try:
        from analysis.fundamentals.valuation import build_valuation_context
        ctx["valuation"] = build_valuation_context(cf, sector_profile=ctx["sector_profile"])
        if ctx["valuation"] is not None and ctx["fundamentals"] is not None:
            from analysis.fundamentals.valuation_decision import assess_valuation
            ctx["valuation_assessment"] = assess_valuation(
                ctx["valuation"], ctx["fundamentals"], ctx["sector_profile"], cf=cf)
    except Exception as e:
        _log.warning("deep_dive: valuation failed for %s: %s", tkr, e)

    try:
        from analysis.thesis.thesis_engine import build_inputs, generate_thesis
        _inputs = build_inputs(tkr, composite=ctx["cs"], sector=sector_raw)
        ctx["thesis"] = generate_thesis(_inputs)
    except Exception as e:
        _log.warning("deep_dive: thesis failed for %s: %s", tkr, e)

    try:
        ctx["flags"] = get_cached_flags(tkr, company_name=company_name) or []
    except Exception as e:
        _log.warning("deep_dive: qualitative flags failed for %s: %s", tkr, e)

    return ctx


def _context_to_prompt_text(ctx: dict) -> str:
    """Render the gathered context as plain text for the LLM prompt — the
    same numbers Analyze Stock shows, just as text instead of Streamlit
    widgets. Missing pieces are stated as missing, never silently omitted,
    so the model knows what it does and doesn't have."""
    lines = [f"=== Auto-computed platform data for {ctx['ticker']} ==="]

    cs = ctx["cs"]
    if cs is not None and getattr(cs, "action", "UNAVAILABLE") != "UNAVAILABLE":
        lines.append(
            f"Trend Quality Score: {cs.score:.1f}/90 ({cs.action}, grade {cs.grade}). "
            f"Technical {cs.technical_score:.0f}/40, Momentum {cs.momentum_score:.0f}/25, "
            f"Volume {cs.volume_score:.0f}/15, Sentiment {cs.sentiment_score:.0f}/10."
        )
        lines.append(
            f"Price ₹{cs.price:,.2f}. Entry ₹{cs.entry:,.2f}, Stop ₹{cs.stop_loss:,.2f}, "
            f"Target ₹{cs.target:,.2f} (R:R {cs.risk_reward:.1f}:1). "
            f"Horizon: {getattr(cs, 'horizon', 'n/a')}."
        )
        lines.append(
            "IMPORTANT CONTEXT ON THIS SCORE: platform research (86,589-observation "
            "5-year backtest) found this score correlates +0.40 with trend "
            "PERSISTENCE but only +0.02 with actual forward RETURNS — treat it as a "
            "trend-health gauge, not a return forecast, in your technical-structure "
            "section below."
        )
    else:
        lines.append("Trend Quality Score: unavailable for this ticker.")

    fnd = ctx["fundamentals"]
    if fnd:
        for key, label in [("revenue_cagr", "Revenue CAGR"), ("eps_cagr", "EPS CAGR"),
                            ("roe", "ROE"), ("roce", "ROCE"),
                            ("debt_to_equity", "Debt/Equity"), ("fcf", "Free Cash Flow")]:
            r = fnd.get(key)
            if r is not None and getattr(r, "value", None) is not None:
                lines.append(f"{label}: {r.value:.2f} ({getattr(r, 'confidence', 'n/a')} confidence)")
            else:
                reason = getattr(r, "reason", "not available") if r else "not available"
                lines.append(f"{label}: N/A ({reason})")
    else:
        lines.append("Fundamentals: unavailable for this ticker.")

    val = ctx["valuation"]
    if val:
        _val_parts = []
        _val_parts.append(f"P/E: {val.pe:.1f}x" if val.pe is not None else "P/E: N/A")
        _val_parts.append(f"P/B: {val.pb:.1f}x" if val.pb is not None else "P/B: N/A")
        if getattr(val, "ev_ebitda_applicable", False):
            _val_parts.append(
                f"EV/EBITDA: {val.ev_ebitda:.1f}x" if val.ev_ebitda is not None else "EV/EBITDA: N/A"
            )
        lines.append(", ".join(_val_parts))
    va = ctx["valuation_assessment"]
    if va:
        lines.append(f"Valuation assessment: {va.posture} — {va.phrase} "
                     f"({va.confidence} confidence). {va.justification}")

    thesis = ctx["thesis"]
    if thesis:
        lines.append(f"Platform thesis verdict: {thesis.verdict} "
                     f"(score {thesis.verdict_score}, -2 bearish to +2 bullish)")
        lines.append(f"Verdict rationale: {thesis.verdict_rationale}")
        if thesis.bull_factors:
            lines.append("Bull factors already detected: " +
                         "; ".join(f.text for f in thesis.bull_factors))
        if thesis.bear_factors:
            lines.append("Bear factors already detected: " +
                         "; ".join(f.text for f in thesis.bear_factors))
        if thesis.key_risks:
            lines.append("Key risks already detected: " +
                         "; ".join(r.text for r in thesis.key_risks))

    flags = ctx["flags"]
    if flags:
        lines.append("Governance/news flags (pledge, RPT, insider trading, shareholding "
                     "changes, SAST filings — from NSE's own disclosures):")
        for f in flags[:15]:
            lines.append(f"  - [{f.get('sentiment', '?')}, {f.get('date', 'n/a')}] "
                         f"{f.get('headline', f)}")
    else:
        lines.append("Governance/news flags: none surfaced (either genuinely clean, or "
                     "the underlying NSE feed was unavailable when last checked — "
                     "don't treat absence as confirmation of no issues).")

    return "\n".join(lines)


_ANALYST_FRAMEWORK = """\
Act as a seasoned equity research analyst with 20 years of experience across \
fundamental analysis, technical analysis, and behavioral finance.

You are given: auto-computed platform data for {ticker} (below), plus one or \
more uploaded PDF documents (Annual Report and/or concall transcripts).

Tear this company apart across these dimensions:

FUNDAMENTALS — Is this business genuinely healthy or just looks good on the \
surface? Dig into revenue quality, margin trajectory, cash flow vs reported \
profits, debt structure, and ROE sustainability. Flag any accounting red flags. \
Use the platform's own computed figures below as your starting numbers — verify \
or challenge them against what the uploaded documents say, don't just repeat them.

MANAGEMENT DNA — Read between the lines of the concall transcripts and MDA \
(inside the Annual Report). Is management confident or defensive? Are they \
overpromising and underdelivering versus what they said in prior periods, if \
that's inferable from the documents provided? Any change in language tone? \
Promoter pledge or stake reduction is an automatic red flag — the platform's \
own governance-flag data below already surfaces this from NSE's disclosures; \
call it out explicitly if present, and cross-check against what the documents say.

VALUATION REALITY — Is the market pricing in perfection? Compare current P/E, \
EV/EBITDA (given below) against historical averages and sector peers, using \
whatever the documents disclose. Tell the reader if they'd be paying a premium \
for growth that may never come.

TECHNICAL STRUCTURE — Where is the stock in its trend cycle (accumulation, \
markup, distribution, markdown)? Key support and resistance levels. Is volume \
confirming price action or diverging? Use the platform's technical/momentum/ \
volume scores below as your quantitative base, but note explicitly: this \
platform's own 5-year research found its score correlates with TREND \
PERSISTENCE far more than with FUTURE RETURNS — do not treat a high score as \
a return forecast.

RISK FACTORS — What are the 3 things that could destroy this thesis? Sector \
risk, company-specific risk, macro risk.

FINAL VERDICT — Buy, Hold, or Avoid. Conviction score out of 10. Price at which \
this becomes interesting if not now. One line that summarizes this stock.

Do not give a balanced, diplomatic answer. Give the direct read — even if it's \
uncomfortable — while being explicit about which claims come from the uploaded \
documents vs the platform's auto-computed data vs your own inference, so the \
reader can tell fact from judgment.

=== Platform data ===
{context}
"""


def _build_full_prompt(ticker: str, context_text: str) -> str:
    """Assemble the analyst framework + auto-computed context into one
    copy-paste-ready prompt.

    FIX COST1: this used to call the Anthropic API directly from inside the
    app (client.messages.create(...)) — but that requires a paid API key,
    which conflicts with this app's free-data-sources-only design (every
    other page runs on yfinance/NSE/Stooq/Google News RSS, zero ongoing
    cost). There's no genuine free tier for Claude's API at the quality this
    kind of analysis needs. Rather than add the app's first-ever recurring
    cost, this step is now manual: the app prepares everything (this prompt,
    plus the platform's own computed data), you attach your uploaded PDFs and
    run it in a Claude conversation you already have access to (like this
    one), then paste the result back below to save it with a date. Zero
    ongoing cost, no API key, no new dependency.
    """
    return _ANALYST_FRAMEWORK.format(ticker=ticker, context=context_text)


with st.spinner(f"Pulling everything the app already knows about {ticker}..."):
    context = _gather_context(ticker)
    context_text = _context_to_prompt_text(context)

st.subheader(f"📊 {ticker} — Auto-Computed Context")
with st.expander("View what will be sent to the model", expanded=False):
    st.text(context_text)


# ═════════════════════════════════════════════════════════════════════════
# Past deep dives for this ticker (FIX NEW1 — "stored with key dates")
# ═════════════════════════════════════════════════════════════════════════
_HISTORY_KEY = f"deep_dive_history:{ticker}"
history = _store.kv_get(_HISTORY_KEY, default=None, user_id=_DD_KV_USER) or []

if history:
    st.markdown("### 🕰️ Past Deep Dives for this Stock")
    for entry in reversed(history):
        _gen_date = entry.get("generated_at", "")[:10]
        _label = entry.get("doc_period_label") or "Untitled batch"
        with st.expander(f"📅 {_gen_date} — {_label}"):
            st.caption("Source documents: " + ", ".join(entry.get("source_docs", [])) or "n/a")
            st.markdown(entry.get("analysis_text", "*(no content saved)*"))


# ═════════════════════════════════════════════════════════════════════════
# Step 1 — get the prompt ready (free, no API call)
# ═════════════════════════════════════════════════════════════════════════
st.markdown("---")
st.subheader("Step 1 — Copy this prompt")
st.caption(
    "This combines the analyst framework with everything the app already "
    "computed above. Copy it into a Claude conversation, attach your Annual "
    "Report / concall transcript PDF(s) to that same message, and send it."
)

full_prompt = _build_full_prompt(ticker, context_text)
st.text_area("Prompt to copy", value=full_prompt, height=220, key="dd_prompt_display")

doc_period_label = st.text_input(
    "Label this batch (e.g. \"FY25 AR + Q2/Q3 FY26 concalls\") — "
    "used to identify this entry in the history below",
    key="dd_batch_label",
)
_source_doc_names = st.text_input(
    "Document filenames used (comma-separated, for your own record — not uploaded here)",
    key="dd_source_names",
)

# ═════════════════════════════════════════════════════════════════════════
# Step 2 — paste the result back to save it with a date
# ═════════════════════════════════════════════════════════════════════════
st.markdown("---")
st.subheader("Step 2 — Paste the analysis back here to save it")
pasted_result = st.text_area(
    "Paste Claude's response here", height=300, key="dd_pasted_result",
)

if st.button("💾 Save to history", type="primary", key="dd_save_btn"):
    if not pasted_result.strip():
        st.error("Paste the analysis text first.")
    else:
        new_entry = {
            "generated_at": datetime.datetime.now().isoformat(),
            "doc_period_label": doc_period_label.strip() or "Untitled batch",
            "analysis_text": pasted_result.strip(),
            "source_docs": [n.strip() for n in _source_doc_names.split(",") if n.strip()],
        }
        history.append(new_entry)
        ok = _store.kv_set(_HISTORY_KEY, history, user_id=_DD_KV_USER)
        if ok:
            st.success("Saved — refresh the page to see it in Past Deep Dives above.")
        else:
            st.error("Saving failed — trade_store write returned false. Try again.")
