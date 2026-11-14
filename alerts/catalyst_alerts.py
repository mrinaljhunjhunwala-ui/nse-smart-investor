"""alerts/catalyst_alerts.py — event-driven BUY / SELL Telegram alerts and the after-close
"why did it move" explainer.

Orchestration only: network goes through data/nse_announcements.py and data/fetcher.py, all maths
through analysis/catalysts.py (pure). Helpers from alerts.check_alerts (dispatch, _already_fired,
_mark_fired, _h, _quote, _pick_session) are imported INSIDE functions to avoid an import cycle,
so check_alerts can import this module at top level.

Entry points (each returns the number of messages sent and never raises):
  check_catalyst_preopen(state, today, now=None)  ~08:40-09:10 IST
  check_catalyst_live(state, today, now=None)     every 15 min in market hours
  check_why_moved(state, today, now=None)         after the close

Each run's reads are kept in trade_store KV ``catalyst_picks:<YYYY-MM-DD>`` (user "_system") so the
feature's own record can be graded later (analysis.catalysts.grade_picks). Nothing is written to the
verdict ledger: its pre-registered study pools every ledger source and must stay uncontaminated.
"""
from __future__ import annotations

import datetime as _dt
import logging
import statistics
from typing import Any, Callable, Dict, Iterable, List, Optional

_log = logging.getLogger("alerts.catalyst_alerts")

IST = _dt.timezone(_dt.timedelta(hours=5, minutes=30))
KV_USER = "_system"
PREOPEN_KEY = "catalyst_preopen"
LIVE_KEY_PREFIX = "catalyst_live_"
WHY_KEY = "why_moved"
PREOPEN_BUYS, PREOPEN_SELLS = 5, 3
LIVE_WINDOW_MIN = 45
LIVE_MAX_PER_DAY = 6
WHY_TOP_N = 5
WHY_CANDIDATES = 15
WHY_MAX_SNAPSHOT_AGE_H = 10
MAX_SYMBOLS = 40
MAX_LINES = 14
# 2026-11-14, 20-session replay (15 Oct - 13 Nov, 1,009 names with filings, 184 positive calls):
# same-day plan about breakeven before costs (+0.1R, entry-to-close +0.2%); held to the latest
# close +3.1% from the open but 3.3 pts BEHIND the Nifty, and no better than the names the engine
# only watched (+3.4%). No edge shown, so positive reads go out as WATCH (tracked, not a buy call).
# Change CALL_WORD back to "BUY" only when the Friday-card record supports it.
CALL_WORD = "WATCH"
FOOTER = "<i>Tracked, not yet a buy call: a 4-week replay showed no edge. Model output, not a guarantee.</i>"
WHY_FOOTER = "<i>Reasons come only from filings, prices and volume — nothing is guessed.</i>"


def kv_key(day: str) -> str:
    return f"catalyst_picks:{day}"


# ── small helpers ───────────────────────────────────────────────────────────

def _now(now: Optional[_dt.datetime]) -> _dt.datetime:
    n = now or _dt.datetime.now(IST)
    return n.replace(tzinfo=IST) if n.tzinfo is None else n.astimezone(IST)


def _holidays() -> Optional[frozenset]:
    try:
        from utils.nse_holidays import NSE_HOLIDAYS
        return frozenset(NSE_HOLIDAYS)
    except Exception:                                       # noqa: BLE001
        return None


def previous_session_close(now: _dt.datetime, holidays: Optional[Iterable[str]] = None) -> _dt.datetime:
    """The last 15:30 IST close at or before `now` on a trading day."""
    hol = frozenset(holidays) if holidays is not None else frozenset()
    d = now.date()
    for _ in range(15):
        close = _dt.datetime.combine(d, _dt.time(15, 30), tzinfo=IST)
        if d.weekday() < 5 and d.isoformat() not in hol and close <= now:
            return close
        d -= _dt.timedelta(days=1)
    return now - _dt.timedelta(days=1)


def _base(t: Any) -> str:
    return str(t or "").upper().replace(".NS", "").replace(".BO", "").strip()


def _daily(sym: str, period: str = "6mo"):
    try:
        from data.fetcher import fetch_single
        df = fetch_single(f"{sym}.NS", period=period)
        return df if df is not None and not getattr(df, "empty", True) else None
    except Exception as e:                                  # noqa: BLE001
        _log.debug("daily bars for %s failed: %s", sym, e)
        return None


def _nifty():
    try:
        from data.fetcher import fetch_index
        df = fetch_index("^NSEI", period="3mo")
        return df if df is not None and not getattr(df, "empty", True) else None
    except Exception:                                       # noqa: BLE001
        return None


def _is_lender(sector: Optional[str]) -> bool:
    if not sector:
        return False
    try:
        from analysis.sector_classification import classify_sector
        return bool(classify_sector(sector).is_financial)
    except Exception:                                       # noqa: BLE001
        return False


def _sectors() -> Dict[str, str]:
    snap = _kv("all_scored_snapshot")
    data = snap.get("data") if isinstance(snap, dict) else None
    if not isinstance(data, dict):
        return {}
    return {_base(v.get("ticker") or k): str(v.get("sector") or "") for k, v in data.items() if isinstance(v, dict)}


def _kv(key: str) -> Any:
    try:
        import trade_store as store
        return store.kv_get(key, None, user_id=KV_USER)
    except Exception:                                       # noqa: BLE001
        return None


def _fmt_px(x: Optional[float]) -> str:
    return "—" if x is None else f"₹{x:,.1f}"


def _read_dict(r: Any) -> dict:
    return r.as_dict() if hasattr(r, "as_dict") else dict(r)


def persist_reads(day: str, reads: Iterable[Any], mode: str, now: _dt.datetime) -> bool:
    """Merge this run's reads into KV catalyst_picks:<day> (one row per symbol + mode)."""
    try:
        import trade_store as store
        cur = store.kv_get(kv_key(day), None, user_id=KV_USER)
        rows = list(cur.get("reads") or []) if isinstance(cur, dict) else []
        idx = {(r.get("symbol"), r.get("mode")): i for i, r in enumerate(rows) if isinstance(r, dict)}
        for r in reads:
            d = _read_dict(r)
            rec = {"symbol": d.get("symbol"), "action": d.get("action"), "date": day, "mode": mode,
                   "ref_price": d.get("ref_price"), "trigger": d.get("trigger"), "stop": d.get("stop"),
                   "target": d.get("target"), "risk_reward": d.get("risk_reward"), "strength": d.get("strength"),
                   "horizon": d.get("horizon"), "catalyst": d.get("catalyst"), "reasons": d.get("reasons"),
                   "warnings": d.get("warnings"), "at": now.isoformat(timespec="minutes")}
            k = (rec["symbol"], mode)
            if k in idx:
                rows[idx[k]] = rec
            else:
                idx[k] = len(rows)
                rows.append(rec)
        return bool(store.kv_set(kv_key(day), {"date": day, "reads": rows}, user_id=KV_USER))
    except Exception as e:                                  # noqa: BLE001
        print(f"[catalyst] persist failed: {e}")
        return False


def week_record(monday: str, today: str) -> Optional[dict]:
    """This week's stored BUY calls (KV catalyst_picks:<day>, Monday..today) graded on daily bars
    with catalysts.grade_picks: first call per symbol, entry when the trigger trades, -1R when the
    stop is touched, target R when the target is, else marked at the last close. None when there
    is nothing to grade. Never raises."""
    try:
        from analysis.catalysts import grade_picks
        d0, d1 = _dt.date.fromisoformat(monday), _dt.date.fromisoformat(today)
        picks: Dict[str, dict] = {}
        day = d0
        while day <= d1:
            cur = _kv(kv_key(day.isoformat()))
            for r in (cur.get("reads") or []) if isinstance(cur, dict) else []:
                if isinstance(r, dict) and r.get("action") == "BUY" and r.get("symbol"):
                    picks.setdefault(_base(r["symbol"]), {**r, "symbol": _base(r["symbol"])})
            day += _dt.timedelta(days=1)
        if not picks:
            return None
        closes = {sym: _daily(sym, period="1mo") for sym in picks}
        res = grade_picks(list(picks.values()), {k: v for k, v in closes.items() if v is not None})
        if not res or not res.get("picks"):
            return None
        ranked = sorted([g for g in res["picks"] if g.get("r") is not None], key=lambda g: -g["r"])
        return {"summary": res["summary"], "best": ranked[:2], "worst": ranked[-1:] if len(ranked) > 2 else []}
    except Exception as e:                                  # noqa: BLE001
        print(f"[catalyst] week record failed: {type(e).__name__}: {e}")
        return None


def week_record_lines(rec: Optional[dict], h: Callable[[Any], str]) -> List[str]:
    """Up to three Friday-card lines for week_record(); [] when there is nothing to show."""
    if not rec or not rec.get("summary") or not rec["summary"].get("n"):
        return []
    s = rec["summary"]
    entered = s["n"] - s.get("not_triggered", 0)
    avg = "n/a" if s.get("avg_r") is None else f"{s['avg_r']:+.1f}R"
    lines = [f"📣 <b>Results &amp; news calls (tracked)</b> · {s['n']} this week",
             f"{entered} entered · {s.get('hit', 0)} hit target · {s.get('stop', 0)} stopped · "
             f"{s.get('open', 0)} still open · average {avg}"]
    names = [f"{h(g['symbol'])} {g['r']:+.1f}R" for g in (rec.get("best") or []) + (rec.get("worst") or [])]
    if names:
        lines.append("Best / worst: " + " · ".join(names))
    return lines


def compose(header: str, entries: List[tuple], footer: str, max_lines: int = MAX_LINES) -> str:
    """header + one/two lines per entry + footer, trimmed to max_lines: second lines go first
    (from the bottom), then whole entries."""
    ents = [[a, b] for a, b in entries]

    def _count():
        return 2 + sum(1 + (1 if b else 0) for _, b in ents)
    i = len(ents) - 1
    while _count() > max_lines and i >= 0:
        ents[i][1] = ""
        i -= 1
    while _count() > max_lines and ents:
        ents.pop()
    lines = [header]
    for a, b in ents:
        lines.append(a)
        if b:
            lines.append(b)
    lines.append(footer)
    return "\n".join(lines)


def read_lines(r: Any, h: Callable[[Any], str]) -> tuple:
    """Two short lines for one read. BUY: the level, the stop and the first target of a
    few-day hold. A negative read prints as AVOID with no trade levels: in the 6-13 Nov
    2026 replay, stocks that gapped down on weak results bounced about 5% from the open,
    so it is information for holders and would-be buyers, not a short call."""
    d = _read_dict(r)
    if d.get("action") == "BUY":
        line1 = (f"{CALL_WORD}  <b>{h(d.get('symbol'))}</b>  above {_fmt_px(d.get('trigger'))}"
                 f" · stop {_fmt_px(d.get('stop'))} · first target {_fmt_px(d.get('target'))}")
    else:
        line1 = f"AVOID  <b>{h(d.get('symbol'))}</b>  weak news — no fresh buying; holders review"
    line2 = "   " + " · ".join(h(x) for x in (d.get("reasons") or [])[:3])
    return line1, line2 if line2.strip() else ""


def _group(events: Iterable[dict]) -> Dict[str, List[dict]]:
    out: Dict[str, List[dict]] = {}
    for e in events or []:
        if isinstance(e, dict) and e.get("symbol") and e.get("when") is not None:
            out.setdefault(_base(e["symbol"]), []).append(e)
    return out


def _merge_results(by_sym: Dict[str, List[dict]], results: Iterable[dict]) -> None:
    from analysis.catalysts import classify_announcement
    for r in results or []:
        sym = _base(r.get("symbol"))
        if not sym:
            continue
        evs = by_sym.setdefault(sym, [])
        has = any((c := classify_announcement(e.get("category"), e.get("headline"), e.get("detail")))
                  and c.kind == "results" for e in evs)
        if not has:
            evs.append({**r, "symbol": sym, "category": "Financial Results",
                        "headline": r.get("headline") or "Financial results filed"})


def build_reads(by_sym: Dict[str, List[dict]], now: _dt.datetime, *, preopen: Optional[dict] = None,
                live_fn: Optional[Callable[[str, dict], tuple]] = None,
                sectors: Optional[Dict[str, str]] = None) -> List[Any]:
    """One catalyst_read per symbol with a classified event (strongest events first, capped)."""
    from analysis import catalysts as C
    from data.nse_announcements import fetch_quarterly_figures
    hol = _holidays()
    sectors = sectors if sectors is not None else {}
    nifty = None
    ranked = []
    for sym, evs in by_sym.items():
        cats = [(C.classify_announcement(e.get("category"), e.get("headline"), e.get("detail")), e) for e in evs]
        cats = [(c, e) for c, e in cats if c is not None]
        if cats:
            ranked.append((max(c.weight for c, _ in cats), sym, [e for _, e in cats]))
    ranked.sort(key=lambda x: -x[0])
    reads = []
    for _w, sym, evs in ranked[:MAX_SYMBOLS]:
        try:
            surprise = None
            if any(C.classify_announcement(e.get("category"), e.get("headline"), e.get("detail")).kind == "results"
                   for e in evs):
                surprise = C.results_surprise(fetch_quarterly_figures(sym), is_lender=_is_lender(sectors.get(sym)))
            df = _daily(sym)
            if df is None:
                continue
            if nifty is None:
                nifty = _nifty()
            newest = max(evs, key=lambda e: C._to_ist(e.get("when")) or now)
            rx = C.reaction(df, newest.get("when"), nifty_df=nifty)
            live, orr = live_fn(sym, rx or {}) if live_fn else (None, None)
            r = C.catalyst_read(sym, evs, surprise, rx, preopen=(preopen or {}).get(sym), now=now, live=live,
                                opening_range=orr, holidays=hol)
            if r is not None:
                reads.append(r)
        except Exception as e:                              # noqa: BLE001
            print(f"[catalyst] {sym}: read failed: {type(e).__name__}: {e}")
    return C.rank_reads(reads)


# ── 1. pre-open ─────────────────────────────────────────────────────────────

def check_catalyst_preopen(state: dict, today: str, now: Optional[_dt.datetime] = None) -> int:
    """Events since the previous session's close -> top 5 BUY + top 3 SELL in one message."""
    try:
        from alerts.check_alerts import _already_fired, _h, _mark_fired, dispatch
        if _already_fired(state, PREOPEN_KEY, today):
            return 0
        from data.nse_announcements import fetch_announcements, fetch_preopen, fetch_results_filed
        n = _now(now)
        since = previous_session_close(n - _dt.timedelta(minutes=1), _holidays())
        anns = fetch_announcements(since, n)
        by_sym = _group(anns)
        _merge_results(by_sym, fetch_results_filed(since))
        if not by_sym:
            print(f"[catalyst-preopen] no filings since {since:%d %b %H:%M} — nothing to send")
            return 0
        reads = build_reads(by_sym, n, preopen=fetch_preopen(), sectors=_sectors())
        if reads:
            persist_reads(today, reads, "preopen", n)
        buys = [r for r in reads if r.action == "BUY"][:PREOPEN_BUYS]
        sells = [r for r in reads if r.action == "SELL"][:PREOPEN_SELLS]
        print(f"[catalyst-preopen] {len(by_sym)} symbols with filings, {len(reads)} reads, "
              f"{len(buys)} BUY / {len(sells)} SELL")
        if not buys and not sells:
            return 0
        header = (f"🌅 <b>Results &amp; news watch</b> ({n:%H:%M} IST) · "
                  f"filings since {since:%a %H:%M}")
        msg = compose(header, [read_lines(r, _h) for r in buys + sells], FOOTER)
        if dispatch(msg, subject="Results and news watch — NSE Smart Investor"):
            _mark_fired(state, PREOPEN_KEY, today)
            return 1
        return 0
    except Exception as e:                                  # noqa: BLE001
        print(f"[catalyst-preopen] failed: {type(e).__name__}: {e}")
        return 0


# ── 2. live (market hours) ──────────────────────────────────────────────────

def _live_fn(today: str, now: _dt.datetime):
    from alerts.check_alerts import _pick_session, _quote
    start = _dt.datetime.combine(now.date(), _dt.time(9, 15), tzinfo=IST)
    frac = min(1.0, max(0.1, (now - start).total_seconds() / (375 * 60)))

    def fn(sym: str, rx: dict):
        q = _quote(sym)
        if not q:
            return None, None
        ss = _pick_session(sym, today) or {}
        live = {"price": q.get("price"), "chg_pct": q.get("chg_pct"), "prev_close": q.get("prev_close"),
                "high": ss.get("high"), "low": ss.get("low")}
        vol, avg = q.get("volume"), rx.get("avg_volume_20d")
        if vol and avg:
            live["rel_vol"] = round(float(vol) / (float(avg) * frac), 2)
        orr = {"high": ss["or_high"], "low": ss["or_low"]} if ss.get("or_high") and ss.get("or_low") else None
        return live, orr
    return fn


def check_catalyst_live(state: dict, today: str, now: Optional[_dt.datetime] = None) -> int:
    """Filings from the last ~45 minutes, confirmed by the live quote; max 6 per day, once per symbol."""
    try:
        from alerts.check_alerts import _already_fired, _h, _mark_fired, dispatch
        sent_today = sum(1 for k, v in state.items() if k.startswith(LIVE_KEY_PREFIX) and v == today)
        room = LIVE_MAX_PER_DAY - sent_today
        if room <= 0:
            print(f"[catalyst-live] daily cap of {LIVE_MAX_PER_DAY} reached")
            return 0
        from data.nse_announcements import fetch_announcements
        n = _now(now)
        by_sym = _group(fetch_announcements(n - _dt.timedelta(minutes=LIVE_WINDOW_MIN), n))
        by_sym = {s: e for s, e in by_sym.items() if not _already_fired(state, LIVE_KEY_PREFIX + s, today)}
        if not by_sym:
            return 0
        reads = [r for r in build_reads(by_sym, n, live_fn=_live_fn(today, n), sectors=_sectors())
                 if r.action in ("BUY", "SELL")][:room]
        if not reads:
            print(f"[catalyst-live] {len(by_sym)} new filers, none confirmed by price")
            return 0
        persist_reads(today, reads, "live", n)
        msg = compose(f"⚡ <b>Fresh catalyst</b> ({n:%H:%M} IST)", [read_lines(r, _h) for r in reads], FOOTER)
        if dispatch(msg, subject="Fresh catalyst — NSE Smart Investor"):
            for r in reads:
                _mark_fired(state, LIVE_KEY_PREFIX + r.symbol, today)
            return 1
        return 0
    except Exception as e:                                  # noqa: BLE001
        print(f"[catalyst-live] failed: {type(e).__name__}: {e}")
        return 0


# ── 3. after the close: why did they move? ──────────────────────────────────

def flagged_symbols(today: str) -> set:
    """Names the app had on a list for today before/at the move: Top Picks, Morning Digest,
    Tomorrow's Watchlist made BEFORE today's session, and this feature's own BUY/SELL reads."""
    out: set = set()
    try:
        from utils.snapshot_time import parse_snapshot_timestamp
    except Exception:                                       # noqa: BLE001
        parse_snapshot_timestamp = None                     # noqa: N806
    tp = _kv("top_picks_snapshot")
    if isinstance(tp, dict) and isinstance(tp.get("data"), dict):
        out |= {_base(b.get("ticker")) for b in tp["data"].get("buys") or [] if isinstance(b, dict)}
    md = _kv("morning_digest_picks")
    if isinstance(md, dict) and md.get("date") == today:
        out |= {_base(b.get("ticker")) for b in md.get("buys") or [] if isinstance(b, dict)}
    tw = _kv("tomorrow_watchlist_snapshot")
    if isinstance(tw, dict) and isinstance(tw.get("data"), dict) and parse_snapshot_timestamp:
        ts = parse_snapshot_timestamp(tw.get("generated_at"))
        if ts is not None and ts.astimezone(IST).date().isoformat() < today:
            for k in ("breakout_candidates", "breakdown_watch", "reversal_watch"):
                out |= {_base(p.get("ticker")) for p in tw["data"].get(k) or [] if isinstance(p, dict)}
    cp = _kv(kv_key(today))
    if isinstance(cp, dict):
        out |= {_base(r.get("symbol")) for r in cp.get("reads") or []
                if isinstance(r, dict) and r.get("action") in ("BUY", "SELL")}
    out.discard("")
    return out


def _snapshot_rows() -> List[dict]:
    snap = _kv("all_scored_snapshot")
    if not (isinstance(snap, dict) and isinstance(snap.get("data"), dict)):
        return []
    try:
        from utils.snapshot_time import snapshot_age_seconds
        age = snapshot_age_seconds(snap.get("generated_at"))
        if age is None or age / 3600 > WHY_MAX_SNAPSHOT_AGE_H:
            print(f"[why-moved] scan snapshot stale (generated_at={snap.get('generated_at')})")
            return []
    except Exception:                                       # noqa: BLE001
        return []
    rows = []
    for k, v in snap["data"].items():
        if not isinstance(v, dict):
            continue
        try:
            ret = float(v.get("return_1d"))
        except (TypeError, ValueError):
            continue
        if ret != ret:
            continue
        rows.append({"symbol": _base(v.get("ticker") or k), "ret": ret, "sector": str(v.get("sector") or ""),
                     "price": v.get("price")})
    return [r for r in rows if r["symbol"] and not r["symbol"].startswith("^")]


def check_why_moved(state: dict, today: str, now: Optional[_dt.datetime] = None) -> int:
    """Top gainers / losers among liquid names with the evidence for each move (two messages)."""
    try:
        from alerts.check_alerts import _already_fired, _h, _mark_fired, dispatch
        if _already_fired(state, WHY_KEY, today):
            return 0
        from analysis import catalysts as C
        from data.nse_announcements import fetch_announcements, fetch_quarterly_figures
        n = _now(now)
        rows = _snapshot_rows()
        if not rows:
            print("[why-moved] no usable scan snapshot — nothing to explain")
            return 0
        by_sector: Dict[str, List[float]] = {}
        for r in rows:
            if r["sector"]:
                by_sector.setdefault(r["sector"], []).append(r["ret"])
        sector_med = {s: statistics.median(v) for s, v in by_sector.items() if len(v) >= 3}
        nifty_ret = None
        nf = _nifty()
        try:
            if nf is not None and len(nf) >= 2 and str(nf.index[-1])[:10] == today:
                nifty_ret = (float(nf["Close"].iloc[-1]) / float(nf["Close"].iloc[-2]) - 1) * 100
        except Exception:                                   # noqa: BLE001
            nifty_ret = None
        events = _group(fetch_announcements(n - _dt.timedelta(days=4), n))
        flagged = flagged_symbols(today)
        rows.sort(key=lambda r: r["ret"], reverse=True)
        cands = rows[:WHY_CANDIDATES] + rows[::-1][:WHY_CANDIDATES]
        explained: Dict[str, dict] = {}
        for r in cands:
            sym = r["symbol"]
            if sym in explained:
                continue
            df = _daily(sym, period="3mo")
            rx = C.reaction(df, _dt.date.fromisoformat(today)) if df is not None else None
            if not rx or (rx.get("avg_turnover_cr") or 0) < C.MIN_TURNOVER_CR:
                continue
            ret = rx["ret_pct"] if rx.get("is_event_day") and rx.get("ret_pct") is not None else r["ret"]
            price = rx.get("close") or rx.get("last_close") or 0
            if price < C.MIN_PRICE:
                continue
            evs = events.get(sym, [])
            surprise = None
            if any((c := C.classify_announcement(e.get("category"), e.get("headline"), e.get("detail")))
                   and c.kind == "results" for e in evs):
                surprise = C.results_surprise(fetch_quarterly_figures(sym), is_lender=_is_lender(r["sector"]))
            reasons = C.explain_move(sym, ret, events=evs, surprise=surprise,
                                     reaction=rx if rx.get("is_event_day") else None,
                                     sector_return_pct=sector_med.get(r["sector"]), nifty_return_pct=nifty_ret)
            explained[sym] = {"symbol": sym, "ret": ret, "reasons": reasons, "flagged": sym in flagged}
        gain = sorted([x for x in explained.values() if x["ret"] > 0], key=lambda x: -x["ret"])[:WHY_TOP_N]
        loss = sorted([x for x in explained.values() if x["ret"] < 0], key=lambda x: x["ret"])[:WHY_TOP_N]
        sent = 0
        day = _dt.date.fromisoformat(today)
        for title, items, arrow in (("top gainers", gain, "▲"), ("top losers", loss, "▼")):
            if not items:
                continue
            entries = [(f"{arrow} <b>{_h(x['symbol'])}</b> {x['ret']:+.1f}% · on your list: "
                        f"{'yes' if x['flagged'] else 'no'}",
                        "   " + " · ".join(_h(s) for s in x["reasons"][:3])) for x in items]
            msg = compose(f"🔎 <b>Why they moved — {title}</b> ({day:%d %b})", entries, WHY_FOOTER)
            if dispatch(msg, subject=f"Why they moved — {title}"):
                sent += 1
        if sent:
            _mark_fired(state, WHY_KEY, today)
        else:
            print("[why-moved] no liquid movers to explain")
        return sent
    except Exception as e:                                  # noqa: BLE001
        print(f"[why-moved] failed: {type(e).__name__}: {e}")
        return 0
