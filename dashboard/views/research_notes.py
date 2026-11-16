"""Research Notes view, rendered by dashboard/pages/08_watchlist_journal.py via render().

Replaces the Stock Journal tab (owner, 17 Nov: "journal has no purpose for me"). Three parts:

  💼 Portfolio briefing for Claude  builds one prompt with every holding (app score, trend read,
                                    dividend yield, ROE, debt, growth), same-sector alternatives
                                    and your latest notes; copy it into Claude, paste the answer
                                    back, and it is saved against the stocks it covered.
  🔎 Stock deep dive                the Deep Dive research prompt (moved here from Analyze Stock).
  📚 Library                        every saved note, newest first, filterable by stock.

No API key and no cost: Claude runs where you already use it. Holdings appear only after the
My Portfolio PIN is unlocked this session.
"""
from __future__ import annotations

import datetime as _dt


def _store():
    import trade_store as store
    return store


def _load_stock_notes() -> dict:
    from analysis.research_notes import STOCK_NOTES_PREFIX
    try:
        s = _store()
        out = {}
        for k in s.kv_keys(STOCK_NOTES_PREFIX):
            v = s.kv_get(k, None)
            if isinstance(v, list) and v:
                out[k[len(STOCK_NOTES_PREFIX):]] = v
        return out
    except Exception:
        return {}


def _load_portfolio_notes() -> list:
    from analysis.research_notes import PORTFOLIO_NOTES_KEY
    try:
        v = _store().kv_get(PORTFOLIO_NOTES_KEY, None)
        return v if isinstance(v, list) else []
    except Exception:
        return []


def _holdings_rows() -> list:
    """Manual holdings as [{ticker, qty, avg}]."""
    try:
        rows = _store().kv_get("manual_portfolio_holdings", None) or []
    except Exception:
        rows = []
    out = []
    for h in rows if isinstance(rows, list) else []:
        sym = str((h or {}).get("ticker", "")).upper().replace(".NS", "").replace(".BO", "").strip()
        try:
            qty = float(h.get("quantity") or h.get("qty") or 0)
            avg = float(h.get("avg_buy_price") or h.get("avg_price") or 0)
        except (TypeError, ValueError):
            continue
        if sym:
            out.append({"ticker": sym, "qty": qty, "avg": avg})
    return out


def _gather_briefing(holdings: list) -> tuple:
    """Holdings enriched with live price, app score / read, sector and fundamentals; plus the
    scan's same-sector alternatives and a one-line market read."""
    from analysis.research_notes import alternative_candidates, dividend_yield_pct
    syms = [h["ticker"] for h in holdings]
    try:
        from utils.live_price import get_live_prices_batch
        q = get_live_prices_batch([f"{s}.NS" for s in syms], max_workers=12) or {}
    except Exception:
        q = {}
    try:
        from dashboard.shared.cache import _persisted_all_scores_snapshot
        scored = _persisted_all_scores_snapshot() or {}
    except Exception:
        scored = {}
    try:
        from data.universe import get_sector
    except Exception:
        get_sector = None
    out = []
    for h in holdings:
        t = h["ticker"]
        live = q.get(f"{t}.NS") or {}
        sc = scored.get(f"{t}.NS") or {}
        price = live.get("price") or sc.get("price")
        row = {**h, "price": price, "chg_pct": live.get("chg_pct"),
               "sector": sc.get("sector") or (get_sector(f"{t}.NS") if get_sector else None),
               "score": sc.get("score"), "action": sc.get("action"), "why": sc.get("headline")}
        if price and h.get("avg"):
            row["pnl_pct"] = (float(price) / float(h["avg"]) - 1) * 100
        if price and h.get("qty"):
            row["value"] = float(price) * float(h["qty"])
        try:
            from analysis.fundamentals.service import default_service
            from analysis.fundamentals import analytics as A
            cf = default_service().get_fundamentals(f"{t}.NS")
            if cf is not None:
                row["div_yield"] = dividend_yield_pct(cf)
                for key, fn in (("roe", A.roe), ("de", A.debt_to_equity)):
                    r = fn(cf)
                    row[key] = r.value if getattr(r, "available", False) else None
                r = A.revenue_cagr(cf, years=3)
                row["rev_cagr_3y"] = r.value if getattr(r, "available", False) else None
        except Exception:
            pass
        out.append(row)
    alts = alternative_candidates(scored, syms, [r.get("sector") for r in out])
    market = ""
    try:
        from dashboard.shared.cache import get_regime_snapshot
        rg = get_regime_snapshot() or {}
        if rg.get("label"):
            market = f"regime {str(rg['label']).replace('_', ' ')}"
    except Exception:
        pass
    return out, alts, market


def _render_briefing(st) -> None:
    from analysis.research_notes import (
        PORTFOLIO_NOTES_KEY, QUESTION_PRESETS, build_portfolio_briefing, new_portfolio_note,
    )
    from dashboard.shared.pin_gate import holdings_unlocked
    st.markdown("#### 💼 Portfolio briefing for Claude")
    st.caption("1 · Pick a question · 2 · Build the briefing and copy it into Claude (claude.ai or Claude Code) "
               "· 3 · Paste Claude's answer below and save it. It is kept here and linked to every stock "
               "it covered.")
    if not holdings_unlocked():
        st.info("Unlock **My Portfolio** (PIN) in this session to build a briefing from your holdings.",
                icon="🔒")
        return
    holdings = _holdings_rows()
    if not holdings:
        st.info("No holdings saved on My Portfolio yet.", icon="💼")
        return
    labels = list(QUESTION_PRESETS) + ["My own question"]
    pick = st.selectbox("Question", labels, key="rn_q_pick")
    question = (st.text_area("Your question", key="rn_q_custom", height=90,
                             placeholder="e.g. Keep PFC and COALINDIA for dividends, or switch?")
                if pick == "My own question" else QUESTION_PRESETS[pick])
    if pick != "My own question":
        st.caption(question)
    if st.button("🧾 Build the briefing", type="primary", key="rn_build"):
        with st.spinner(f"Collecting prices, scores and fundamentals for {len(holdings)} holdings…"):
            rows, alts, market = _gather_briefing(holdings)
            notes = {t: v for t, v in _load_stock_notes().items() if t in {h['ticker'] for h in holdings}}
            st.session_state["rn_prompt"] = build_portfolio_briefing(
                rows, question, alternatives=alts, notes=notes, market_line=market)
            st.session_state["rn_prompt_q"] = (pick, question, [h["ticker"] for h in holdings])
    prompt = st.session_state.get("rn_prompt")
    if not prompt:
        return
    st.caption("Copy with the icon at the top right of the box, then paste into Claude.")
    st.code(prompt, language=None)
    st.download_button("⬇️ Download as text", prompt, file_name=f"portfolio_briefing_{_dt.date.today()}.txt",
                       key="rn_dl")
    answer = st.text_area("Paste Claude's answer here", height=260, key="rn_answer")
    if st.button("💾 Save answer", key="rn_save_answer"):
        if not answer.strip():
            st.error("Paste Claude's answer first.")
            return
        pick_s, q_s, tickers = st.session_state.get("rn_prompt_q", (pick, question, []))
        hist = _load_portfolio_notes()
        hist.append(new_portfolio_note(pick_s, q_s, tickers, answer))
        if _store().kv_set(PORTFOLIO_NOTES_KEY, hist):
            st.success(f"Saved — linked to {len(tickers)} stocks. It is in the Library below.")
            st.session_state.pop("rn_prompt", None)
        else:
            st.error("Save failed. Copy your text elsewhere before leaving the page.")


def _render_deep_dive(st) -> None:
    st.markdown("#### 🔎 Stock deep dive")
    st.caption("A full research prompt for one stock (the app's numbers + flags + thesis) to use with "
               "its annual report / concall PDFs in Claude. Moved here from Analyze Stock.")
    pre = st.session_state.pop("rn_ticker", None)
    if pre:
        st.session_state["rn_dd_ticker"] = pre
    raw = st.text_input("Stock symbol (e.g. PFC)", key="rn_dd_ticker")
    try:
        from dashboard.shared.cache import _validate_ticker
        sym, err = _validate_ticker(raw or "")
    except Exception:
        sym, err = str(raw or "").upper().replace(".NS", "").strip(), None
    if err:
        st.warning(err)
        return
    if not sym:
        return
    if st.toggle(f"Build the {sym} research prompt", key=f"rn_dd_open_{sym}"):
        from dashboard.shared.deep_dive_tab import render_deep_dive_tab
        render_deep_dive_tab(f"{sym}.NS")


def _render_library(st) -> None:
    from analysis.research_notes import library
    st.markdown("#### 📚 Library")
    stock_notes, port_notes = _load_stock_notes(), _load_portfolio_notes()
    tickers = sorted({t.replace(".NS", "") for t in stock_notes}
                     | {t for n in port_notes for t in n.get("tickers") or []})
    pick = st.selectbox("Show notes for", ["All stocks"] + tickers, key="rn_lib_filter")
    rows = library(stock_notes, port_notes, ticker=None if pick == "All stocks" else pick)
    if not rows:
        st.caption("No saved notes yet. Save a portfolio answer above or a stock deep dive to start.")
        return
    st.caption(f"{len(rows)} note(s), newest first.")
    for r in rows:
        icon = "💼" if r["kind"] == "portfolio" else "🔎"
        with st.expander(f"{icon} {r['date']} · {r['title']}"):
            if r["kind"] == "portfolio":
                st.caption("Stocks covered: " + (", ".join(r["tickers"]) or "n/a"))
                if r.get("question"):
                    st.caption("Question: " + r["question"])
            elif r.get("sources"):
                st.caption("Source documents: " + ", ".join(r["sources"]))
            st.markdown(r["text"] or "*(empty)*")
            if st.button("🗑️ Delete this note", key=f"rn_del_{r['key']}_{r['index']}"):
                s = _store()
                cur = s.kv_get(r["key"], None) or []
                if isinstance(cur, list) and 0 <= r["index"] < len(cur):
                    cur.pop(r["index"])
                    (s.kv_set(r["key"], cur) if cur else s.kv_delete(r["key"]))
                    st.rerun()


def render() -> None:
    import streamlit as st

    st.caption("Talk to Claude where you already do; this keeps what it told you. No API key needed.")
    _render_briefing(st)
    st.divider()
    _render_deep_dive(st)
    st.divider()
    _render_library(st)
