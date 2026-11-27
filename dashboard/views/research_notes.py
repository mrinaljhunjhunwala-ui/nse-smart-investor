"""Research Notes view, rendered by dashboard/pages/08_watchlist_journal.py via render().

Replaces the Stock Journal tab (owner, 17 Nov: "journal has no purpose for me"). Three parts:

  💼 Portfolio briefing for Claude  builds one prompt with every holding (app score and stop,
                                    price levels, sector-aware fundamentals, holding period, checks
                                    on distorted figures), Top Picks and same-sector candidates,
                                    and your latest notes; the answer format follows the question.
                                    Copy it into Claude, paste the answer back, and it is saved
                                    against the stocks it covered.
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
            out.append({"ticker": sym, "qty": qty, "avg": avg,
                        "bought": h.get("date_bought") or h.get("buy_date")})
    return out


SCAN_MAX_AGE_DAYS = 4        # a Friday-close scan still serves a Monday-evening briefing
IST = _dt.timezone(_dt.timedelta(hours=5, minutes=30))


def _scan_snapshot(key: str):
    """(data, 'from the scan at 16 Nov 15:28 IST') for a warm-scan KV snapshot up to
    SCAN_MAX_AGE_DAYS old. The live readers in cache.py drop anything over 20 minutes, which is
    right for Top Picks on screen but left every evening briefing with no scores at all."""
    try:
        from utils.snapshot_time import parse_snapshot_timestamp, snapshot_age_seconds
        snap = _store().kv_get(key, None, user_id="_system")
        if not isinstance(snap, dict) or not isinstance(snap.get("data"), dict):
            return {}, ""
        age = snapshot_age_seconds(snap.get("generated_at"))
        if age is None or age > SCAN_MAX_AGE_DAYS * 86400:
            return {}, ""
        ts = parse_snapshot_timestamp(snap.get("generated_at")).astimezone(IST)
        return snap["data"], f"{ts:%d %b %H:%M} IST"
    except Exception:
        return {}, ""


def _history(sym: str):
    try:
        from data.fetcher import fetch_single
        return fetch_single(f"{sym}.NS", period="1y")
    except Exception:
        return None


def _gather_briefing(holdings: list) -> dict:
    """Holdings enriched with live price, app score / stop / read, sector and industry, price
    levels, sector-aware fundamentals and checks; plus Top Picks, same-sector alternatives, the
    market line and when the prices / scan were taken."""
    import concurrent.futures as _cf
    from analysis.research_notes import alternative_candidates, dividend_yield_pct, technical_levels
    syms = [h["ticker"] for h in holdings]
    try:
        from utils.live_price import get_live_prices_batch
        q = get_live_prices_batch([f"{s}.NS" for s in syms], max_workers=12) or {}
    except Exception:
        q = {}
    scored, scan_at = _scan_snapshot("all_scored_snapshot")
    missing = tuple(f"{s}.NS" for s in syms
                    if (scored.get(f"{s}.NS") or {}).get("score") is None)
    live_scored = {}
    if missing:                       # not in the scan universe (or no scan): score them now
        try:
            from dashboard.shared.cache import _score_watchlist
            live_scored = _score_watchlist(missing) or {}
        except Exception:
            live_scored = {}
    with _cf.ThreadPoolExecutor(max_workers=8) as ex:
        hist = dict(zip(syms, ex.map(_history, syms)))
    try:
        from data.universe import get_industry, get_sector
    except Exception:
        get_sector = get_industry = None
    out = []
    for h in holdings:
        t = h["ticker"]
        live = q.get(f"{t}.NS") or {}
        sc = scored.get(f"{t}.NS") or {}
        ls = live_scored.get(f"{t}.NS") or {}
        if not sc and str(ls.get("action", "")).upper() != "UNAVAILABLE":
            sc = ls
        price = live.get("price") or sc.get("price")
        row = {**h, "price": price, "chg_pct": live.get("chg_pct"),
               "sector": sc.get("sector") or (get_sector(f"{t}.NS") if get_sector else None),
               "industry": get_industry(t) if get_industry else None,
               "score": sc.get("score"), "action": sc.get("action"), "why": sc.get("headline"),
               "sl": sc.get("sl"), "tech": technical_levels(hist.get(t)) if hist.get(t) is not None else {}}
        if price and h.get("avg"):
            row["pnl_pct"] = (float(price) / float(h["avg"]) - 1) * 100
        if price and h.get("qty"):
            row["value"] = float(price) * float(h["qty"])
        try:
            from analysis.fundamentals.service import default_service
            from analysis.fundamentals import analytics as A
            cf = default_service().get_fundamentals(f"{t}.NS")
            if cf is not None:
                row["company"] = cf.company_name
                row["div_yield"] = dividend_yield_pct(cf)
                for key, fn in (("roe", A.roe), ("de", A.debt_to_equity)):
                    r = fn(cf)
                    row[key] = r.value if getattr(r, "available", False) else None
                r = A.revenue_cagr(cf, years=3)
                row["rev_cagr_3y"] = r.value if getattr(r, "available", False) else None
                rt = cf.ratios
                if rt is not None:
                    row["pe"], row["pb"] = rt.pe, rt.pb
        except Exception:
            pass
        out.append(row)
    alts = alternative_candidates(scored, syms, [r.get("sector") for r in out])
    picks_snap, _ = _scan_snapshot("top_picks_snapshot")
    picks = [b for b in (picks_snap.get("buys") or []) if isinstance(b, dict)][:10]
    market = []
    try:
        from dashboard.shared.cache import get_regime_snapshot
        rg = get_regime_snapshot() or {}
        if rg.get("label"):
            market.append(f"regime {str(rg['label']).replace('_', ' ')}")
    except Exception:
        pass
    try:
        from dashboard.shared.cache import get_vix_info
        vx = get_vix_info() or {}
        if vx.get("vix"):
            market.append(f"India VIX {float(vx['vix']):.1f} ({vx.get('regime', 'n/a')})")
    except Exception:
        pass
    from analysis.research_notes import price_note
    n_scored = sum(1 for r in out if r.get("score") is not None)
    if scan_at:
        scan_note = (f"App scores: from the app's scan at {scan_at}"
                     + (f"; {len(out) - n_scored} holding(s) the app could not score" if n_scored < len(out) else ""))
    elif n_scored:
        scan_note = f"App scores: scored just now ({n_scored} of {len(out)}); no recent full-market scan"
    else:
        scan_note = "App scores: not available (no scan in the last few days and live scoring failed)"
    return {"rows": out, "alts": alts, "picks": picks, "market": " · ".join(market),
            "prices_note": price_note(_dt.datetime.now(IST)), "scan_note": scan_note}


def _render_briefing(st) -> None:
    from analysis.research_notes import (
        PORTFOLIO_NOTES_KEY, QUESTION_PRESETS, build_portfolio_briefing, new_portfolio_note,
    )
    from dashboard.shared.pin_gate import unlock_inline
    st.markdown("#### 💼 Portfolio briefing for Claude")
    st.caption("1 · Pick a question · 2 · Build the briefing and copy it into Claude (claude.ai or Claude Code) "
               "· 3 · Paste Claude's answer below and save it. It is kept here and linked to every stock "
               "it covered.")
    if not unlock_inline("my_portfolio", "My Portfolio", "research_notes", collapsible=False):
        return
    holdings = _holdings_rows()
    if not holdings:
        st.info("No holdings saved on My Portfolio yet.", icon="💼")
        return
    labels = list(QUESTION_PRESETS) + ["My own question"]
    pick = st.selectbox("Question", labels, key="rn_q_pick")
    from analysis.research_notes import FRESH_MONEY_KEY
    fresh = st.number_input("Fresh money to invest (₹, optional)", min_value=0, step=10000, value=0,
                            key="rn_fresh", help="Sent to Claude so it can size each suggestion.",
                            ) if pick in (FRESH_MONEY_KEY, "My own question") else 0
    question = (st.text_area("Your question", key="rn_q_custom", height=90,
                             placeholder="e.g. Keep PFC and COALINDIA for dividends, or switch?")
                if pick == "My own question" else QUESTION_PRESETS[pick])
    if pick != "My own question":
        st.caption(question)
    if st.button("🧾 Build the briefing", type="primary", key="rn_build"):
        with st.spinner(f"Collecting prices, scores and fundamentals for {len(holdings)} holdings…"):
            g = _gather_briefing(holdings)
            notes = {t: v for t, v in _load_stock_notes().items() if t in {h['ticker'] for h in holdings}}
            st.session_state["rn_prompt"] = build_portfolio_briefing(
                g["rows"], question, alternatives=g["alts"], notes=notes, market_line=g["market"],
                question_key=pick if pick in QUESTION_PRESETS else None, fresh_money=fresh,
                prices_note=g["prices_note"], scan_note=g["scan_note"], top_picks=g["picks"])
            st.session_state["rn_prompt_q"] = (pick, question, [h["ticker"] for h in holdings])
    prompt = st.session_state.get("rn_prompt")
    if not prompt:
        return
    st.caption("Copy with the icon at the top right of the box, then paste into Claude. Turn on "
               "web search in Claude so it can check today's prices and news.")
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
    from dashboard.shared.pin_gate import holdings_unlocked
    stock_notes = _load_stock_notes()
    # Portfolio notes list held tickers: same gate as the briefing that wrote them.
    port_notes = _load_portfolio_notes() if holdings_unlocked() else []
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
