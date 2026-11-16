"""analysis/research_notes.py — Research Notes: the portfolio briefing for Claude and the notes library.

The owner talks to Claude outside the app (claude.ai or Claude Code) and wants the app to (a) hand
Claude everything it knows about the portfolio in one paste, and (b) remember what Claude said.
No API key, no cost: the app builds the prompt, the owner pastes it into Claude, then pastes the
answer back and it is stored with the date and the stocks it covered.

Storage (trade_store KV, user "default", the same place Deep Dive has always saved):
  deep_dive_history:<TICKER>   per-stock Deep Dive write-ups (list of entries), unchanged
  portfolio_briefing_history   portfolio-level answers (list of entries with the tickers covered)

Pure: no Streamlit, no network, no DB. Callers pass plain dicts in.
"""
from __future__ import annotations

import datetime as _dt
import math
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

STOCK_NOTES_PREFIX = "deep_dive_history:"
PORTFOLIO_NOTES_KEY = "portfolio_briefing_history"
NOTE_EXCERPT_CHARS = 1200

QUESTION_PRESETS: Dict[str, str] = {
    "Reassess my holdings": (
        "Go through every holding and tell me, for each: HOLD, ADD, TRIM or SELL, and if SELL or "
        "TRIM, what you would replace it with for the SAME goal (dividend income stays dividend "
        "income, growth stays growth). Rank the replacements and say why each is better."),
    "Dividend income check": (
        "I hold some stocks mainly for dividends. Judge each of those on dividend yield, payout "
        "safety and price trend. Are there better dividend stocks I should switch to? Name them, "
        "with their yield and the risk you see."),
    "What to trim or exit": (
        "Which holdings are the weakest right now (trend, fundamentals, news) and should be trimmed "
        "or exited? Give a stop level for anything I keep."),
    "Where to add fresh money": (
        "I have fresh money to invest. Should it go into an existing holding or a new name? Give me "
        "the top 3 choices with entry, stop and why."),
}


def _num(x: Any) -> Optional[float]:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def base_symbol(t: Any) -> str:
    return str(t or "").upper().replace(".NS", "").replace(".BO", "").strip()


def dividend_yield_pct(fundamentals: Any) -> Optional[float]:
    """Trailing dividend yield (%) = |latest annual dividends paid| / market cap. None when either
    is missing (never a guessed 0)."""
    try:
        cfw = fundamentals.latest_cashflow() if fundamentals is not None else None
        paid = _num(getattr(cfw, "dividends_paid", None)) if cfw is not None else None
        mcap = _num(getattr(getattr(fundamentals, "ratios", None), "market_cap", None))
    except Exception:
        return None
    if paid is None or not mcap or mcap <= 0:
        return None
    return round(abs(paid) / mcap * 100, 2)


def _fmt(v: Any, spec: str, suffix: str = "", na: str = "n/a") -> str:
    n = _num(v)
    return na if n is None else f"{n:{spec}}{suffix}"


def holding_lines(holdings: Sequence[Mapping[str, Any]]) -> List[str]:
    """One plain-text line per holding for the briefing."""
    total = sum((_num(h.get("value")) or 0.0) for h in holdings) or None
    out = []
    for h in holdings:
        val = _num(h.get("value"))
        weight = f"{val / total * 100:.1f}%" if val and total else "n/a"
        parts = [
            f"{base_symbol(h.get('ticker'))}",
            f"sector {h.get('sector') or 'n/a'}",
            f"qty {_fmt(h.get('qty'), '.0f')}",
            f"avg cost ₹{_fmt(h.get('avg'), ',.2f')}",
            f"now ₹{_fmt(h.get('price'), ',.2f')} ({_fmt(h.get('chg_pct'), '+.2f', '% today')})",
            f"P&L {_fmt(h.get('pnl_pct'), '+.1f', '%')}",
            f"weight {weight}",
            f"app score {_fmt(h.get('score'), '.0f', '/90')} ({h.get('action') or 'n/a'})",
            f"dividend yield {_fmt(h.get('div_yield'), '.2f', '%')}",
            f"ROE {_fmt(h.get('roe'), '.1f', '%')}",
            f"debt/equity {_fmt(h.get('de'), '.2f')}",
            f"revenue growth 3y {_fmt(h.get('rev_cagr_3y'), '+.1f', '%/yr')}",
        ]
        if h.get("why"):
            parts.append(f"app read: {h['why']}")
        out.append("- " + " · ".join(parts))
    return out


def alternative_candidates(scored: Mapping[str, Mapping[str, Any]], held: Iterable[str],
                           sectors: Iterable[str], per_sector: int = 3,
                           min_score: float = 60.0) -> List[dict]:
    """Strongest scan names in the sectors the owner already holds (not already held), for Claude
    to weigh as same-goal replacements."""
    held_set = {base_symbol(t) for t in held}
    want = {str(s) for s in sectors if s}
    by: Dict[str, List[dict]] = {}
    for k, v in (scored or {}).items():
        if not isinstance(v, Mapping):
            continue
        sym = base_symbol(v.get("ticker") or k)
        sec = str(v.get("sector") or "")
        score = _num(v.get("score"))
        if not sym or sym in held_set or sec not in want or score is None or score < min_score:
            continue
        by.setdefault(sec, []).append({"ticker": sym, "sector": sec, "score": score,
                                       "action": v.get("action"), "price": _num(v.get("price")),
                                       "sl": _num(v.get("sl")), "return_1d": _num(v.get("return_1d"))})
    out: List[dict] = []
    for sec in sorted(by):
        out += sorted(by[sec], key=lambda r: -r["score"])[:per_sector]
    return out


def _excerpt(text: str, n: int = NOTE_EXCERPT_CHARS) -> str:
    t = " ".join(str(text or "").split())
    return t if len(t) <= n else t[: n - 1].rstrip() + "…"


def build_portfolio_briefing(holdings: Sequence[Mapping[str, Any]], question: str, *,
                             alternatives: Sequence[Mapping[str, Any]] = (),
                             notes: Mapping[str, Sequence[Mapping[str, Any]]] = (),
                             market_line: str = "",
                             today: Optional[_dt.date] = None) -> str:
    """The full prompt to paste into Claude: role, the owner's question, holdings with the app's
    numbers, same-sector alternatives, the latest saved notes per holding, and output rules."""
    today = today or _dt.date.today()
    lines = [
        "You are a seasoned Indian-equity portfolio analyst. Below is my real portfolio as my "
        "stock app sees it today. Use the numbers as your starting point, add what you know, and "
        "say clearly which statements come from this data and which are your own judgement.",
        "",
        f"MY QUESTION: {question.strip() or QUESTION_PRESETS['Reassess my holdings']}",
        "",
        f"=== Portfolio on {today:%d %b %Y} ({len(holdings)} holdings) ===",
    ]
    if market_line:
        lines.append(f"Market: {market_line}")
    lines += holding_lines(holdings) or ["(no holdings)"]
    lines += ["", "Notes on the app's numbers: 'app score' is a 0-90 trend-health score (it tracks "
              "trend persistence far better than future returns); dividend yield is trailing, from "
              "the last annual report; 'n/a' means the app had no data, not zero."]
    if alternatives:
        lines += ["", "=== Same-sector candidates the app's scan rates highly (not held) ==="]
        for a in alternatives:
            lines.append(f"- {a['ticker']} · {a['sector']} · app score {a['score']:.0f}/90 "
                         f"({a.get('action') or 'n/a'}) · ₹{_fmt(a.get('price'), ',.2f')}"
                         + (f" · stop ₹{a['sl']:,.2f}" if a.get("sl") else ""))
        lines.append("(The app has no dividend data for these; use your own knowledge and say so.)")
    note_lines = []
    for t, entries in (notes or {}).items():
        if entries:
            e = entries[-1]
            note_lines.append(f"- {t} ({str(e.get('generated_at', ''))[:10]}, "
                              f"{e.get('doc_period_label') or e.get('question_label') or 'note'}): "
                              f"{_excerpt(e.get('analysis_text') or e.get('answer') or '')}")
    if note_lines:
        lines += ["", "=== My earlier research notes (latest per stock, excerpts) ==="] + note_lines
    lines += [
        "",
        "=== How to answer ===",
        "1. A table: stock | your call (HOLD / ADD / TRIM / SELL) | one-line reason | stop level.",
        "2. For every TRIM / SELL: the replacement you prefer for the same goal, with entry and stop.",
        "3. Anything here that looks risky that I may not have noticed (concentration, a sector, a "
        "weak balance sheet, a dividend at risk).",
        "4. One line: the overall health of this portfolio.",
        "Be direct. Every BUY or ADD needs a stop. Never promise returns; these are judgements, "
        "not guarantees.",
    ]
    return "\n".join(lines)


def new_portfolio_note(question_label: str, question: str, tickers: Iterable[str], answer: str,
                       now: Optional[_dt.datetime] = None) -> dict:
    return {"generated_at": (now or _dt.datetime.now()).isoformat(timespec="seconds"),
            "question_label": question_label, "question": question,
            "tickers": sorted({base_symbol(t) for t in tickers if t}), "answer": answer.strip()}


def library(stock_notes: Mapping[str, Sequence[Mapping[str, Any]]],
            portfolio_notes: Sequence[Mapping[str, Any]],
            ticker: Optional[str] = None) -> List[dict]:
    """Every saved note, newest first, as uniform rows. With ``ticker``, only that stock's Deep
    Dives plus the portfolio answers that covered it."""
    want = base_symbol(ticker) if ticker else None
    rows: List[dict] = []
    for t, entries in (stock_notes or {}).items():
        b = base_symbol(t)
        if want and b != want:
            continue
        for i, e in enumerate(entries or []):
            rows.append({"kind": "stock", "key": f"{STOCK_NOTES_PREFIX}{t}", "index": i,
                         "date": str(e.get("generated_at", ""))[:10], "when": str(e.get("generated_at", "")),
                         "title": f"{b} · {e.get('doc_period_label') or 'Deep Dive'}",
                         "tickers": [b], "text": e.get("analysis_text", ""),
                         "sources": e.get("source_docs") or []})
    for i, e in enumerate(portfolio_notes or []):
        tk = [base_symbol(x) for x in e.get("tickers") or []]
        if want and want not in tk:
            continue
        rows.append({"kind": "portfolio", "key": PORTFOLIO_NOTES_KEY, "index": i,
                     "date": str(e.get("generated_at", ""))[:10], "when": str(e.get("generated_at", "")),
                     "title": f"Portfolio · {e.get('question_label') or 'briefing'}",
                     "tickers": tk, "text": e.get("answer", ""), "question": e.get("question", "")})
    return sorted(rows, key=lambda r: r["when"], reverse=True)
