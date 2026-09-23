"""dashboard/shared/deep_dive_tab.py -- Deep Dive tab body.

Slice 2 (docs/UI_UX_DESIGN_2026-09.md) folds the old Deep Dive page into
Analyze Stock as a tab. The unique bits of that page were:

  1. `_gather_context()`  -- pulls fundamentals / valuation / thesis /
     governance flags into one dict for LLM prompt assembly
  2. `_context_to_prompt_text()` -- renders the context as text
  3. `_ANALYST_FRAMEWORK` -- the 20-year-analyst research prompt
  4. Past Deep Dives history (kv-persisted) + Step 1 / Step 2 UI

Everything else Deep Dive used to render (live price / chart / signal
badge / short-term vs long-term compare) is already on Analyze Stock's
other tabs, so this module deliberately does NOT duplicate it.

Pure module -- no Streamlit imports at import time except for the tab
renderer, which takes `ticker` from the parent page's already-resolved
scope. No side effects on import.
"""
from __future__ import annotations

import datetime
import logging

import streamlit as st

import trade_store as _store
from dashboard.shared.cache import get_composite_score
from dashboard.shared.trade_utils import _display_label
from data.universe import get_sector

_log = logging.getLogger("dashboard.deep_dive")
_DD_KV_USER = "default"


def _gather_context(tkr: str) -> dict:
    """Pull everything the app already computes for this ticker. Every
    piece degrades independently to None/empty on failure -- one missing
    source (e.g. fundamentals provider down) never blocks the others."""
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
        from dashboard.shared.flags_ui import get_cached_flags
        ctx["flags"] = get_cached_flags(tkr, company_name=company_name) or []
    except Exception as e:
        _log.warning("deep_dive: qualitative flags failed for %s: %s", tkr, e)

    return ctx


def _context_to_prompt_text(ctx: dict) -> str:
    """Render the gathered context as plain text for the LLM prompt.
    Missing pieces are stated as missing, never silently omitted, so the
    model knows what it does and doesn't have."""
    lines = [f"=== Auto-computed platform data for {ctx['ticker']} ==="]

    cs = ctx["cs"]
    if cs is not None and getattr(cs, "action", "UNAVAILABLE") != "UNAVAILABLE":
        lines.append(
            f"Composite Score: {cs.score:.1f}/90 ({_display_label(cs.action)}, grade {cs.grade}). "
            f"Technical {cs.technical_score:.0f}/40, Momentum {cs.momentum_score:.0f}/25, "
            f"Volume {cs.volume_score:.0f}/15, Sentiment {cs.sentiment_score:.0f}/10."
        )
        lines.append(
            f"Price Rs.{cs.price:,.2f}. Entry Rs.{cs.entry:,.2f}, Stop Rs.{cs.stop_loss:,.2f}, "
            f"Target Rs.{cs.target:,.2f} (R:R {cs.risk_reward:.1f}:1). "
            f"Horizon: {getattr(cs, 'horizon', 'n/a')}."
        )
        lines.append(
            "IMPORTANT CONTEXT ON THIS SCORE: platform research (86,589-observation "
            "5-year backtest) found this score correlates +0.40 with trend "
            "PERSISTENCE but only +0.02 with actual forward RETURNS -- treat it as a "
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
        lines.append(f"Valuation assessment: {va.posture} -- {va.phrase} "
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
                     "changes, SAST filings -- from NSE's own disclosures):")
        for f in flags[:15]:
            lines.append(f"  - [{f.get('sentiment', '?')}, {f.get('date', 'n/a')}] "
                         f"{f.get('headline', f)}")
    else:
        lines.append("Governance/news flags: none surfaced (either genuinely clean, or "
                     "the underlying NSE feed was unavailable when last checked -- "
                     "don't treat absence as confirmation of no issues).")

    return "\n".join(lines)


_ANALYST_FRAMEWORK = """\
Act as a seasoned equity research analyst with 20 years of experience across \
fundamental analysis, technical analysis, and behavioral finance.

You are given: auto-computed platform data for {ticker} (below), plus one or \
more uploaded PDF documents (Annual Report and/or concall transcripts).

Tear this company apart across these dimensions:

FUNDAMENTALS -- Is this business genuinely healthy or just looks good on the \
surface? Dig into revenue quality, margin trajectory, cash flow vs reported \
profits, debt structure, and ROE sustainability. Flag any accounting red flags. \
Use the platform's own computed figures below as your starting numbers -- verify \
or challenge them against what the uploaded documents say, don't just repeat them.

MANAGEMENT DNA -- Read between the lines of the concall transcripts and MDA \
(inside the Annual Report). Is management confident or defensive? Are they \
overpromising and underdelivering versus what they said in prior periods, if \
that's inferable from the documents provided? Any change in language tone? \
Promoter pledge or stake reduction is an automatic red flag -- the platform's \
own governance-flag data below already surfaces this from NSE's disclosures; \
call it out explicitly if present, and cross-check against what the documents say.

VALUATION REALITY -- Is the market pricing in perfection? Compare current P/E, \
EV/EBITDA (given below) against historical averages and sector peers, using \
whatever the documents disclose. Tell the reader if they'd be paying a premium \
for growth that may never come.

TECHNICAL STRUCTURE -- Where is the stock in its trend cycle (accumulation, \
markup, distribution, markdown)? Key support and resistance levels. Is volume \
confirming price action or diverging? Use the platform's technical/momentum/ \
volume scores below as your quantitative base, but note explicitly: this \
platform's own 5-year research found its score correlates with TREND \
PERSISTENCE far more than with FUTURE RETURNS -- do not treat a high score as \
a return forecast.

RISK FACTORS -- What are the 3 things that could destroy this thesis? Sector \
risk, company-specific risk, macro risk.

FINAL VERDICT -- Buy, Hold, or Avoid. Conviction score out of 10. Price at which \
this becomes interesting if not now. One line that summarizes this stock.

Do not give a balanced, diplomatic answer. Give the direct read -- even if it's \
uncomfortable -- while being explicit about which claims come from the uploaded \
documents vs the platform's auto-computed data vs your own inference, so the \
reader can tell fact from judgment.

=== Platform data ===
{context}
"""


def _build_full_prompt(ticker: str, context_text: str) -> str:
    """Assemble the analyst framework + auto-computed context into one
    copy-paste-ready prompt.

    This step is intentionally manual: the app prepares everything (the
    prompt + the platform's own computed data), the user attaches uploaded
    PDFs and runs it in a Claude conversation they already have access to,
    then pastes the result back below to save it. Zero ongoing cost, no
    API key, no new dependency.
    """
    return _ANALYST_FRAMEWORK.format(ticker=ticker, context=context_text)


def render_deep_dive_tab(ticker: str) -> None:
    """Render the Deep Dive tab body inside Analyze Stock.

    The parent page has already resolved `ticker`. This function skips
    ticker resolution / live-snapshot / short-term-vs-long-term / chart
    since Analyze Stock's other tabs already cover those, and focuses on
    the unique Deep Dive workflow:

      - Auto-computed context expander (what the prompt will send)
      - Past deep dives history (kv-persisted per ticker)
      - Step 1 -- copy-ready prompt + label / source-doc inputs
      - Step 2 -- paste-back-result + save button
    """
    st.caption(
        "Prepare a structured equity-research prompt combining the platform's "
        "own computed data with your uploaded PDFs (Annual Report / concalls). "
        "Runs off-app in a Claude conversation you already have access to -- "
        "no LLM API key needed. Paste the response back below to save it with "
        "a date."
    )

    with st.spinner(f"Pulling everything the app already knows about {ticker}..."):
        context = _gather_context(ticker)
    context_text = _context_to_prompt_text(context)

    _HISTORY_KEY = f"deep_dive_history:{ticker}"
    history = _store.kv_get(_HISTORY_KEY, default=None, user_id=_DD_KV_USER) or []

    with st.expander("📋 View what will be sent to the model", expanded=False):
        st.text(context_text)

    if history:
        st.markdown(
            '<div class="t-h2" style="margin:14px 0 6px 0">'
            '🕰️ Past Deep Dives for this stock</div>',
            unsafe_allow_html=True,
        )
        for entry in reversed(history):
            _gen_date = entry.get("generated_at", "")[:10]
            _label = entry.get("doc_period_label") or "Untitled batch"
            with st.expander(f"📅 {_gen_date} — {_label}"):
                st.caption("Source documents: " + (", ".join(entry.get("source_docs", [])) or "n/a"))
                st.markdown(entry.get("analysis_text", "*(no content saved)*"))

    st.markdown("---")
    st.markdown(
        '<div class="t-h2" style="margin:14px 0 6px 0">'
        'Step 1 · Copy this prompt</div>',
        unsafe_allow_html=True,
    )
    st.caption(
        "This combines the analyst framework with everything the app already "
        "computed above. Copy it into a Claude conversation, attach your Annual "
        "Report / concall transcript PDF(s) to that same message, and send it."
    )
    full_prompt = _build_full_prompt(ticker, context_text)
    st.text_area("Prompt to copy", value=full_prompt, height=220,
                 key=f"dd_prompt_display_{ticker}")

    doc_period_label = st.text_input(
        'Label this batch (e.g. "FY25 AR + Q2/Q3 FY26 concalls") -- '
        "used to identify this entry in the history above",
        key=f"dd_batch_label_{ticker}",
    )
    _source_doc_names = st.text_input(
        "Document filenames used (comma-separated, for your own record -- not uploaded here)",
        key=f"dd_source_names_{ticker}",
    )

    st.markdown("---")
    st.markdown(
        '<div class="t-h2" style="margin:14px 0 6px 0">'
        'Step 2 · Paste the analysis back here to save it</div>',
        unsafe_allow_html=True,
    )
    pasted_result = st.text_area(
        "Paste Claude's response here", height=300,
        key=f"dd_pasted_result_{ticker}",
    )
    if st.button("💾 Save to history", type="primary",
                 key=f"dd_save_btn_{ticker}"):
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
                st.success("Saved — reload the tab to see it in Past Deep Dives above.")
            else:
                st.error("Save failed. Copy your text elsewhere before navigating away.")
