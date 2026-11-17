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


# Corporate events that make multi-year figures (growth, trailing yield, 52-week range) misleading.
# Keyed by base symbol; the text goes into the briefing as a "check" line.
CORPORATE_EVENTS: Dict[str, str] = {
    "VEDL": ("Vedanta demerged on 15 Jun 2026 into VAML, VOGL, VEDPOWER and VISL; VEDL is now the "
             "residual zinc / critical-minerals business, so its growth, dividend yield and 52-week "
             "range mix pre- and post-demerger numbers"),
    **{t: ("listed after the Vedanta demerger (15 Jun 2026): short price history, and any multi-year "
           "figure belongs to the old combined company") for t in ("VAML", "VOGL", "VEDPOWER", "VISL")},
    **{t: ("Tata Motors demerged on 1 Oct 2025 (TMPV passenger vehicles, TMCV commercial vehicles): "
           "older figures belong to the combined company") for t in ("TMPV", "TMCV")},
}
LONG_TERM_MONTHS = 12          # listed equity: held over 12 months -> long-term capital gains


def _months_between(a: _dt.date, b: _dt.date) -> int:
    return (b.year - a.year) * 12 + (b.month - a.month) - (1 if b.day < a.day else 0)


def holding_period(bought: Any, today: Optional[_dt.date] = None) -> Optional[str]:
    """'held 2y 3m · long-term' from a YYYY-MM-DD purchase date; None when unknown."""
    try:
        d = _dt.date.fromisoformat(str(bought)[:10])
    except (TypeError, ValueError):
        return None
    today = today or _dt.date.today()
    if d > today:
        return None
    m = _months_between(d, today)
    span = f"{m // 12}y {m % 12}m" if m >= 12 else f"{m}m"
    tax = ("long-term for tax" if m >= LONG_TERM_MONTHS
           else f"short-term for tax until {d.replace(year=d.year + 1):%d %b %Y}")
    return f"bought {d:%d %b %Y}, held {span} ({tax})"


def technical_levels(df: Any) -> Dict[str, Any]:
    """52-week range, 50/200-day averages, ATR(14) and 1/3-month returns from daily bars.
    Empty dict when there is nothing usable. Pure (pandas only)."""
    try:
        close = df["Close"].astype(float).dropna()
        high = df["High"].astype(float).reindex(close.index)
        low = df["Low"].astype(float).reindex(close.index)
    except Exception:
        return {}
    n = len(close)
    if n < 2:
        return {}
    last = float(close.iloc[-1])
    yr = close.iloc[-252:]
    out: Dict[str, Any] = {"bars": n, "last": last,
                           "high_52w": float(high.iloc[-252:].max()), "low_52w": float(low.iloc[-252:].min())}
    if not math.isfinite(out["high_52w"]):
        out["high_52w"] = float(yr.max())
    if not math.isfinite(out["low_52w"]):
        out["low_52w"] = float(yr.min())
    if n >= 50:
        out["sma50"] = float(close.iloc[-50:].mean())
    if n >= 200:
        out["sma200"] = float(close.iloc[-200:].mean())
    if n >= 15:
        prev = close.shift(1)
        tr = (high - low).combine((high - prev).abs(), max).combine((low - prev).abs(), max)
        atr = _num(tr.iloc[-14:].mean())
        if atr:
            out["atr14"] = atr
    for key, k in (("ret_1m", 21), ("ret_3m", 63)):
        if n > k and close.iloc[-k - 1] > 0:
            out[key] = (last / float(close.iloc[-k - 1]) - 1) * 100
    return out


def holding_flags(h: Mapping[str, Any]) -> List[str]:
    """Things in this holding's numbers that Claude should not take at face value."""
    sym = base_symbol(h.get("ticker"))
    flags = []
    if sym in CORPORATE_EVENTS:
        flags.append(CORPORATE_EVENTS[sym])
    dy = _num(h.get("div_yield"))
    if dy is not None and dy > 10:
        flags.append(f"a {dy:.1f}% trailing dividend yield is unusual: likely a special dividend, or a "
                     "smaller company after a demerger; check the current payout before relying on it")
    g = _num(h.get("rev_cagr_3y"))
    if g is not None and abs(g) > 50:
        flags.append(f"3-year revenue growth of {g:+.0f}%/yr is extreme: likely a demerger, merger or "
                     "tiny base, not a trend")
    bars = _num((h.get("tech") or {}).get("bars"))
    if bars is not None and bars < 200:
        flags.append(f"only {bars:.0f} trading days of price history: the 200-day average and 52-week "
                     "range are incomplete")
    return flags


def _sector_text(h: Mapping[str, Any]) -> str:
    sec, ind = h.get("sector") or "n/a", h.get("industry")
    return f"{ind} (app bucket {sec})" if ind and ind != sec else str(sec)


def _is_financial(h: Mapping[str, Any]) -> bool:
    from analysis.sector_classification import classify_sector
    return classify_sector(h.get("industry") or h.get("sector"), h.get("company")).is_financial


def holding_lines(holdings: Sequence[Mapping[str, Any]], today: Optional[_dt.date] = None) -> List[str]:
    """A short block per holding: position, the app's read, price levels, fundamentals, checks."""
    total = sum((_num(h.get("value")) or 0.0) for h in holdings) or None
    out = []
    for h in holdings:
        val = _num(h.get("value"))
        weight = f"{val / total * 100:.1f}%" if val and total else "n/a"
        name = base_symbol(h.get("ticker")) + (f" ({h['company']})" if h.get("company") else "")
        head = [name, f"sector {_sector_text(h)}", f"qty {_fmt(h.get('qty'), '.0f')}",
                f"avg cost ₹{_fmt(h.get('avg'), ',.2f')}"]
        held = holding_period(h.get("bought"), today)
        if held:
            head.append(held)
        head += [f"now ₹{_fmt(h.get('price'), ',.2f')} ({_fmt(h.get('chg_pct'), '+.2f', '% on the day')})",
                 f"P&L {_fmt(h.get('pnl_pct'), '+.1f', '%')}", f"weight {weight}"]
        out.append("- " + " · ".join(head))

        app = [f"score {_fmt(h.get('score'), '.0f', '/90')} ({h.get('action') or 'n/a'})"]
        if _num(h.get("sl")):
            app.append(f"app stop ₹{_num(h.get('sl')):,.2f}")
        if h.get("why"):
            app.append(f"read: {h['why']}")
        out.append("    app: " + " · ".join(app))

        t = h.get("tech") or {}
        if t:
            lv = []
            if _num(t.get("high_52w")) and _num(t.get("low_52w")):
                below = ""
                if _num(t.get("last")) and t["high_52w"]:
                    below = f", {(1 - t['last'] / t['high_52w']) * 100:.0f}% below the high"
                lv.append(f"52-week range ₹{t['low_52w']:,.2f}–₹{t['high_52w']:,.2f}{below}")
            for key, lab in (("sma50", "50-day avg"), ("sma200", "200-day avg")):
                if _num(t.get(key)):
                    lv.append(f"{lab} ₹{t[key]:,.2f}")
            if _num(t.get("atr14")):
                pct = f" ({t['atr14'] / t['last'] * 100:.1f}% of price)" if _num(t.get("last")) else ""
                lv.append(f"typical daily range (ATR 14) ₹{t['atr14']:,.2f}{pct}")
            for key, lab in (("ret_1m", "1 month"), ("ret_3m", "3 months")):
                if _num(t.get(key)) is not None:
                    lv.append(f"{lab} {t[key]:+.1f}%")
            if lv:
                out.append("    levels: " + " · ".join(lv))
        else:
            out.append("    levels: n/a (no price history reached the app)")

        if _is_financial(h):
            fu = [f"P/B {_fmt(h.get('pb'), '.2f')}", f"ROE {_fmt(h.get('roe'), '.1f', '%')}",
                  f"dividend yield {_fmt(h.get('div_yield'), '.2f', '%')}",
                  f"revenue growth 3y {_fmt(h.get('rev_cagr_3y'), '+.1f', '%/yr')}",
                  "lender: judge on P/B and ROE; debt/equity is not meaningful for a bank or NBFC"]
        else:
            fu = [f"P/E {_fmt(h.get('pe'), '.1f')}", f"P/B {_fmt(h.get('pb'), '.2f')}",
                  f"ROE {_fmt(h.get('roe'), '.1f', '%')}", f"debt/equity {_fmt(h.get('de'), '.2f')}",
                  f"dividend yield {_fmt(h.get('div_yield'), '.2f', '%')}",
                  f"revenue growth 3y {_fmt(h.get('rev_cagr_3y'), '+.1f', '%/yr')}"]
        out.append("    fundamentals: " + " · ".join(fu))
        for f in holding_flags(h):
            out.append(f"    ⚠ check: {f}")
    return out


def price_note(now: _dt.datetime) -> str:
    """When the prices were taken, and whether the market was open (NSE 09:15-15:30 IST, Mon-Fri;
    exchange holidays are not known here)."""
    open_ = now.weekday() < 5 and _dt.time(9, 15) <= now.time() <= _dt.time(15, 30)
    stamp = f"{now:%d %b %Y %H:%M} IST"
    if open_:
        return f"Prices: live quotes taken at {stamp} while the market was open; they will have moved since."
    return f"Prices: taken at {stamp} with the market closed, so they are the last closing prices."


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


FRESH_MONEY_KEY = "Where to add fresh money"
_RULES = ("Be direct: say BUY / ADD / HOLD / TRIM / SELL plainly. Every BUY or ADD needs an entry and a "
          "stop; use the levels above (52-week range, averages, typical daily range) rather than "
          "round numbers. Never promise returns; these are judgements, not guarantees.")
ANSWER_FORMATS: Dict[str, List[str]] = {
    "Reassess my holdings": [
        "1. A table: stock | your call (HOLD / ADD / TRIM / SELL) | one-line reason | stop level.",
        "2. For every TRIM / SELL: the replacement you prefer for the same goal, with entry and stop "
        "(prefer names from the candidate lists above, or say why not).",
        "3. Anything risky I may not have noticed (concentration, a sector, a weak balance sheet, a "
        "dividend at risk, tax on selling a big gain).",
        "4. One line: the overall health of this portfolio.",
    ],
    "Dividend income check": [
        "1. A table of the stocks you think I hold for income: stock | yield (data or yours, say "
        "which) | payout safety | call (HOLD / ADD / TRIM / SELL) | stop.",
        "2. Better dividend stocks to switch to, with yield, entry, stop and the risk you see.",
        "3. Any dividend that looks at risk, and why.",
        "4. One line: how dependable this income is.",
    ],
    "What to trim or exit": [
        "1. Weakest first: stock | TRIM / SELL / HOLD | reason (trend, fundamentals, news) | stop for "
        "anything I keep.",
        "2. The tax side of each sale (short- or long-term, from the holding periods above).",
        "3. What the freed-up money should do, with entry and stop.",
        "4. One line: the overall health of this portfolio.",
    ],
    FRESH_MONEY_KEY: [
        "1. Your top 3: stock | existing holding or new | entry zone | stop | how much of the fresh "
        "money (amount or %) | why now.",
        "2. Why each beats adding to my biggest positions; mind my concentration and sector mix.",
        "3. One holding I should NOT add to, and why.",
        "4. Anything risky I may not have noticed.",
    ],
}
_CUSTOM_FORMAT = [
    "1. Answer my question directly first.",
    "2. For every stock you name: your call (BUY / ADD / HOLD / TRIM / SELL), entry and stop.",
    "3. Anything risky in this portfolio I may not have noticed.",
    "4. One line: the overall health of this portfolio.",
]


def candidate_lines(picks: Sequence[Mapping[str, Any]], held: Iterable[str] = ()) -> List[str]:
    """New names from the app's latest Top Picks scan (not already held)."""
    held_set = {base_symbol(t) for t in held}
    out = []
    for p in picks:
        sym = base_symbol(p.get("ticker"))
        if not sym or sym in held_set:
            continue
        bits = [sym, str(p.get("sector") or "n/a"),
                f"app score {_fmt(p.get('score'), '.0f', '/90')} ({p.get('action') or 'n/a'})",
                f"₹{_fmt(p.get('price'), ',.2f')}"]
        if _num(p.get("entry")):
            bits.append(f"entry ₹{_num(p.get('entry')):,.2f}")
        if _num(p.get("sl")):
            bits.append(f"stop ₹{_num(p.get('sl')):,.2f}")
        if _num(p.get("tp")):
            bits.append(f"target ₹{_num(p.get('tp')):,.2f}")
        if p.get("headline"):
            bits.append(str(p["headline"]))
        out.append("- " + " · ".join(bits))
    return out


def build_portfolio_briefing(holdings: Sequence[Mapping[str, Any]], question: str, *,
                             alternatives: Sequence[Mapping[str, Any]] = (),
                             notes: Mapping[str, Sequence[Mapping[str, Any]]] = (),
                             market_line: str = "",
                             today: Optional[_dt.date] = None,
                             question_key: Optional[str] = None,
                             fresh_money: Optional[float] = None,
                             prices_note: str = "",
                             scan_note: str = "",
                             top_picks: Sequence[Mapping[str, Any]] = ()) -> str:
    """The full prompt to paste into Claude: role, the owner's question, holdings with the app's
    numbers and levels, candidate new names, the latest saved notes per holding, and an answer
    format that fits the question asked."""
    today = today or _dt.date.today()
    lines = [
        "You are a seasoned Indian-equity portfolio analyst. Below is my real portfolio as my "
        "stock app sees it. Use the numbers as your starting point and say clearly which statements "
        "come from this data, which you checked online today, and which are your own judgement.",
        "Your training data stops at a cut-off date. If you can search the web, check today's price "
        "and latest news (results, corporate actions, management, regulatory) for every stock you "
        "make a call on, and say what you checked. If you cannot, say so plainly and do not quote "
        "prices from memory. Some of these companies may be newer than your training data; rely on "
        "the figures here for them.",
        "",
        f"MY QUESTION: {question.strip() or QUESTION_PRESETS['Reassess my holdings']}",
    ]
    fm = _num(fresh_money)
    if fm and fm > 0:
        lines.append(f"Fresh money available to invest: ₹{fm:,.0f}")
    total = sum((_num(h.get("value")) or 0.0) for h in holdings)
    lines += ["", f"=== Portfolio on {today:%d %b %Y} ({len(holdings)} holdings"
              + (f", worth ₹{total:,.0f}" if total else "") + ") ==="]
    for extra in (prices_note, f"Market: {market_line}" if market_line else "", scan_note):
        if extra:
            lines.append(extra)
    lines += holding_lines(holdings, today) or ["(no holdings)"]
    lines += ["", "Notes on the app's numbers: 'app score' is a 0-90 trend-health score (it tracks "
              "trend persistence far better than future returns) and 'app stop' is the stop the app "
              "would set today; dividend yield is trailing, from the last annual report; sectors are "
              "the app's broad buckets (correct them if you know better); 'n/a' means the app had no "
              "data, not zero; '⚠ check' lines are figures the app itself does not trust."]
    held = [h.get("ticker") for h in holdings]
    pick_lines = candidate_lines(top_picks, held)
    if pick_lines:
        lines += ["", "=== New names: the app's latest Top Picks scan (not held) ==="] + pick_lines
    if alternatives:
        lines += ["", "=== Same-sector candidates the app's scan rates highly (not held) ==="]
        for a in alternatives:
            lines.append(f"- {a['ticker']} · {a['sector']} · app score {a['score']:.0f}/90 "
                         f"({a.get('action') or 'n/a'}) · ₹{_fmt(a.get('price'), ',.2f')}"
                         + (f" · stop ₹{a['sl']:,.2f}" if a.get("sl") else ""))
    if pick_lines or alternatives:
        lines.append("(The app has no dividend or valuation data for these; use your own knowledge "
                     "and say so.)")
    note_lines = []
    for t, entries in (notes or {}).items():
        if entries:
            e = entries[-1]
            note_lines.append(f"- {t} ({str(e.get('generated_at', ''))[:10]}, "
                              f"{e.get('doc_period_label') or e.get('question_label') or 'note'}): "
                              f"{_excerpt(e.get('analysis_text') or e.get('answer') or '')}")
    if note_lines:
        lines += ["", "=== My earlier research notes (latest per stock, excerpts) ==="] + note_lines
    fmt = ANSWER_FORMATS.get(question_key or "", _CUSTOM_FORMAT)
    lines += ["", "=== How to answer ==="] + fmt + [_RULES]
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
