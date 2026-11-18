"""alerts/movers_alerts.py — intraday movers radar and the holding guard (Telegram).

check_movers_radar(state, today, now=None)
    Every 15-minute market run from 09:45 to 15:25 IST. Only names the owner can act on count
    (owner, 18 Nov): holdings, open paper trades, Tomorrow's Watchlist, Nifty 100; nothing is sent
    when none of them moved. Sends only stocks that newly crossed
    their tier's move threshold since the last message (each symbol once a day), at most 5 per
    market-cap tier plus every bullish name from last evening's Tomorrow's Watchlist (any rank)
    up 4%+. Each line says why it moved (filings / volume, from evidence only) and how similar
    past moves did over the next 5 sessions vs the Nifty. At most RADAR_MAX_MSGS messages a day.
    The day's list is kept in KV ``movers_radar:<date>`` (user "_system") for the dashboard.

check_holding_guard(state, today, now=None)
    For My Portfolio holdings only real trouble: a sharp one-day fall for the stock's tier, a
    negative filing (fraud, auditor exit, regulatory order, ...) or clearly weak results. Once per
    holding per day. Runs regardless of ALERT_HOLDINGS (the routine ±10% / level alerts stay off).

Maths in analysis/movers.py (pure); network in data/nse_movers.py and data/nse_announcements.py.
Both entry points never raise and return the number of messages sent.
"""
from __future__ import annotations

import datetime as _dt
import logging
from typing import Any, Dict, List, Optional

_log = logging.getLogger("alerts.movers_alerts")
IST = _dt.timezone(_dt.timedelta(hours=5, minutes=30))
KV_USER = "_system"
EVIDENCE_KEY = "movers_evidence"
RADAR_START = _dt.time(9, 45)
RADAR_END = _dt.time(15, 25)
RADAR_MAX_MSGS = 6
# FIX RADAR-PACING (audit 2026-11): one message per 15-minute run spent all 6 by ~11:00 IST
# (17 Nov: "daily cap reached" from 11:30 on), so afternoon moves were never alerted. The same
# 6 are now released one per window; a window's unused message carries forward, and a batch
# with a bullish Tomorrow's Watchlist name is never held back by the pacing (the daily cap
# still applies).
RADAR_WINDOWS = (_dt.time(9, 45), _dt.time(10, 30), _dt.time(11, 30), _dt.time(12, 30),
                 _dt.time(13, 30), _dt.time(14, 30))
RADAR_MAX_ITEMS = 15
TW_MAX_AGE_H = 30            # last evening's Tomorrow's Watchlist is the one that applies today
SCAN_MAX_AGE_H = 3
MSG_CHAR_BUDGET = 3800       # Telegram caps a message at 4096 characters
RADAR_FOOTER = ("<i>Reasons come from filings and volume only. 'Similar past moves' is history, "
                "not a promise. A big up-day is often a poor entry.</i>")
GUARD_FOOTER = "<i>Only sharp falls and bad filings are sent for holdings; daily moves stay quiet.</i>"


def radar_kv_key(day: str) -> str:
    return f"movers_radar:{day}"


def _now(now: Optional[_dt.datetime]) -> _dt.datetime:
    n = now or _dt.datetime.now(IST)
    return n.replace(tzinfo=IST) if n.tzinfo is None else n.astimezone(IST)


def _kv(key: str, user: Optional[str] = KV_USER) -> Any:
    try:
        import trade_store as store
        return store.kv_get(key, None, user_id=user) if user else store.kv_get(key, None)
    except Exception:                                       # noqa: BLE001
        return None


def _kv_set(key: str, value: Any) -> None:
    try:
        import trade_store as store
        store.kv_set(key, value, user_id=KV_USER)
    except Exception as e:                                  # noqa: BLE001
        print(f"[movers] could not store {key}: {type(e).__name__}: {e}")


def _fresh(snap: Any, max_age_h: float) -> Optional[dict]:
    if not (isinstance(snap, dict) and isinstance(snap.get("data"), dict)):
        return None
    try:
        from utils.snapshot_time import snapshot_age_seconds
        age = snapshot_age_seconds(snap.get("generated_at"))
    except Exception:                                       # noqa: BLE001
        return None
    return snap if age is not None and age / 3600 <= max_age_h else None


def _bands() -> Dict[str, str]:
    try:
        from analysis.movers import band_map
        from data.universe import _CONSTITUENTS
        return band_map(_CONSTITUENTS)
    except Exception as e:                                  # noqa: BLE001
        print(f"[movers] index tiers unavailable: {e}")
        return {}


def _events_by_symbol(now: _dt.datetime, days: int = 3) -> Dict[str, List[dict]]:
    try:
        from data.nse_announcements import fetch_announcements
        out: Dict[str, List[dict]] = {}
        for e in fetch_announcements(now - _dt.timedelta(days=days), now) or []:
            if isinstance(e, dict) and e.get("symbol"):
                out.setdefault(str(e["symbol"]).upper().replace(".NS", ""), []).append(e)
        return out
    except Exception as e:                                  # noqa: BLE001
        print(f"[movers] announcements unavailable: {e}")
        return {}


def _score_part(scan: Optional[dict], sym: str) -> str:
    """Model read for the line; BUY only at 70+ with a stop (the alerts' BUY floor)."""
    row = (scan or {}).get("data", {}).get(f"{sym}.NS") if scan else None
    if not isinstance(row, dict) or not row.get("score"):
        return "not in the scan"
    score = float(row.get("score") or 0)
    sl = float(row.get("sl") or 0)
    if "BUY" in str(row.get("action") or "").upper() and score >= 70 and sl > 0:
        return f"score {score:.0f} · BUY, stop ₹{sl:,.2f}"
    return f"score {score:.0f} · WATCH"


def radar_allowance(t: _dt.time) -> int:
    """Messages the radar may have sent by time ``t`` (one per window started so far)."""
    return min(RADAR_MAX_MSGS, sum(1 for w in RADAR_WINDOWS if t >= w))


def radar_action(m: dict) -> str:
    """What to do with a radar mover (owner, 17 Nov: every alert says what to do). The radar
    reports a move already made, so it never says BUY: a big up-day is a poor entry."""
    pct = m.get("pct") or 0.0
    if m.get("held"):
        return f"you hold it: HOLD with your stop; don't add after a {pct:+.1f}% day"
    if m.get("paper"):
        return f"open paper trade: HOLD with its stop; don't add after a {pct:+.1f}% day"
    if m.get("watchlist"):
        label, rank, _ = m["watchlist"]
        return (f"on your watchlist ({label} #{rank}): don't chase {pct:+.1f}%; "
                "buy only if it holds the gain into the close or pulls back")
    return f"no action: large cap, not on your lists, and a {pct:+.1f}% day is a poor entry"


def build_radar(movers: List[dict], *, now: _dt.datetime, reasons: Dict[str, List[str]],
                evidence: Optional[dict], scan: Optional[dict], source: str) -> tuple:
    """(message lines, movers that fit). Movers are added in order while the message stays
    under MSG_CHAR_BUDGET; the rest are left for the next run. The old version trimmed the
    text but the caller still marked every selected mover as sent, so names cut from the
    message were never alerted that day (and a trimmed tier could leave an empty header)."""
    from alerts.check_alerts import _h
    from analysis.movers import BAND_LABEL, chase_lookup, evidence_phrase

    src = "all NSE stocks" if source == "NSE" else "scan universe only (NSE feed down)"
    lines = [f"📡 <b>Movers radar</b> · {now:%H:%M} IST · {src}"]
    kept: List[dict] = []
    band = None
    for m in movers:
        block = []
        if m["band"] != band:
            block.append(f"<b>{BAND_LABEL[m['band']]}</b>")
        tag = " · 💼 you hold it" if m.get("held") else (" · 📂 open paper trade" if m.get("paper") else "")
        if m.get("watchlist"):
            label, rank, _ = m["watchlist"]
            tag += f" · 📋 on Tomorrow's Watchlist #{rank} ({_h(label)})"
        block.append(f"▲ <b>{_h(m['symbol'])}</b> {m['pct']:+.1f}% ₹{m['price']:,.2f}{tag}")
        why = "; ".join(_h(r) for r in (reasons.get(m["symbol"]) or [])[:2]) or "no filing found"
        stats = chase_lookup((evidence or {}).get("table"), m["band"], m["pct"], m.get("vol_ratio"))
        block.append(f"   why: {why} · {_h(evidence_phrase(stats))} · {_h(_score_part(scan, m['symbol']))}")
        block.append("   → " + _h(radar_action(m)))
        if kept and len("\n".join(lines + block + [RADAR_FOOTER])) > MSG_CHAR_BUDGET:
            break
        lines += block
        kept.append(m)
        band = m["band"]
    lines.append(RADAR_FOOTER)
    return lines, kept


def radar_lines(movers: List[dict], **kw) -> List[str]:
    """Message body only (see build_radar)."""
    return build_radar(movers, **kw)[0]


def check_movers_radar(state: dict, today: str, now: Optional[_dt.datetime] = None) -> int:
    try:
        from alerts.check_alerts import _FORCE_SEND, dispatch
        from analysis import catalysts as C
        from analysis.movers import base_symbol, restrict_to_lists, select_movers, watchlist_ranks
        from data.nse_movers import fetch_gainers

        n = _now(now)
        if not (RADAR_START <= n.time() <= RADAR_END) and not _FORCE_SEND:
            return 0
        sent_msgs = sum(1 for k in state if k.startswith("movers_msg_"))
        if sent_msgs >= RADAR_MAX_MSGS and not _FORCE_SEND:
            print(f"[movers] daily cap of {RADAR_MAX_MSGS} radar messages reached")
            return 0
        scan = _fresh(_kv("all_scored_snapshot"), SCAN_MAX_AGE_H)
        rows = fetch_gainers(scan)
        if not rows:
            print("[movers] no gainers feed (NSE and scan snapshot both unavailable)")
            return 0
        tw = _fresh(_kv("tomorrow_watchlist_snapshot"), TW_MAX_AGE_H)
        ranks = watchlist_ranks(tw["data"]) if tw else {}
        already = [k[len("mover_"):] for k in state if k.startswith("mover_")]
        bands = _bands()
        held = {base_symbol(s) for s in _holdings()}
        paper = {base_symbol(s) for s in _paper_symbols()}
        mine = restrict_to_lists(rows, bands=bands, ranks=ranks, held=held, paper=paper)
        movers = select_movers(mine, bands=bands, ranks=ranks, already=already)[:RADAR_MAX_ITEMS]
        if not movers:
            print(f"[movers] nothing to send: no new mover among your holdings, paper trades, "
                  f"Tomorrow's Watchlist or large caps ({len(rows)} gainers checked)")
            return 0
        for m in movers:
            m["held"] = m["symbol"] in held
            m["paper"] = m["symbol"] in paper
        if (sent_msgs >= radar_allowance(n.time()) and not any(m.get("watchlist") for m in movers)
                and not _FORCE_SEND):
            print(f"[movers] pacing: {sent_msgs} of {RADAR_MAX_MSGS} sent; the next is released at "
                  f"the next window ({len(movers)} mover(s) wait and stay eligible)")
            return 0
        events = _events_by_symbol(n)
        reasons = {m["symbol"]: C.explain_move(m["symbol"], m["pct"], events=events.get(m["symbol"], []),
                                               reaction={"rel_vol": m.get("vol_ratio")})
                   for m in movers}
        evidence = _kv(EVIDENCE_KEY)
        lines, movers = build_radar(movers, now=n, reasons=reasons, evidence=evidence, scan=scan,
                                    source=str(rows[0].get("source") or ""))
        if not dispatch("\n".join(lines), subject="Movers radar"):
            return 0
        for m in movers:
            state[f"mover_{m['symbol']}"] = today
        state[f"movers_msg_{sent_msgs + 1}"] = today
        log = _kv(radar_kv_key(today))
        log = log if isinstance(log, list) else []
        stamp = f"{n:%H:%M}"
        log += [{"time": stamp, "symbol": m["symbol"], "pct": m["pct"], "price": m["price"],
                 "band": m["band"], "watchlist": list(m["watchlist"]) if m.get("watchlist") else None,
                 "vol_ratio": m.get("vol_ratio"), "why": reasons.get(m["symbol"], [])[:2]} for m in movers]
        _kv_set(radar_kv_key(today), log)
        print(f"[movers] sent {len(movers)} mover(s)")
        return 1
    except Exception as e:                                  # noqa: BLE001
        print(f"[movers] radar failed: {type(e).__name__}: {e}")
        return 0


def _holdings() -> List[str]:
    rows = _kv("manual_portfolio_holdings", user=None) or []
    out = []
    for h in rows if isinstance(rows, list) else []:
        sym = str((h or {}).get("ticker", "")).upper().replace(".NS", "").replace(".BO", "").strip()
        if sym and sym not in out:
            out.append(sym)
    return out


def _paper_symbols() -> List[str]:
    """Symbols of open paper trades (trade_store); empty when the store is unreachable."""
    try:
        import trade_store as store
        df = store.fetch_open()
        col = "ticker" if "ticker" in getattr(df, "columns", []) else "symbol"
        return [str(t).upper().replace(".NS", "").replace(".BO", "").strip()
                for t in (df[col].tolist() if df is not None and col in df.columns else []) if t]
    except Exception as e:                                  # noqa: BLE001
        print(f"[movers] open paper trades unavailable: {e}")
        return []


def check_holding_guard(state: dict, today: str, now: Optional[_dt.datetime] = None) -> int:
    try:
        from alerts.check_alerts import _h, dispatch
        from analysis import catalysts as C
        from analysis.movers import BAND_LABEL, cap_band, guard_reason

        n = _now(now)
        held = [s for s in _holdings() if state.get(f"guard_{s}") != today]
        if not held:
            return 0
        bands = _bands()
        events = _events_by_symbol(n, days=1)
        hits = []
        for sym in held:
            q = None
            try:
                from utils.live_price import get_live_quote
                q = get_live_quote(sym)
            except Exception:                               # noqa: BLE001
                q = None
            pct = q.get("chg_pct") if isinstance(q, dict) else None
            negs, results_score = [], None
            for ev in events.get(sym, []):
                cat = C.classify_announcement(ev.get("category"), ev.get("headline"), ev.get("detail"))
                if cat is None:
                    continue
                if cat.direction < 0:
                    negs.append(cat.label)
                elif cat.kind == "results" and results_score is None:
                    try:
                        from data.nse_announcements import fetch_quarterly_figures
                        s = C.results_surprise(fetch_quarterly_figures(sym))
                        results_score = s.get("score") if s else None
                    except Exception:                       # noqa: BLE001
                        results_score = None
            band = cap_band(sym, bands)
            why = guard_reason(pct, band, negative_filings=negs, results_score=results_score)
            if why:
                price = q.get("price") if isinstance(q, dict) else None
                hits.append((sym, band, price, why))
        if not hits:
            return 0
        lines = [f"⚠️ <b>Holding alert</b> · {n:%H:%M} IST"]
        for sym, band, price, why in hits:
            px = f" ₹{float(price):,.2f}" if price else ""
            lines.append(f"<b>{_h(sym)}</b>{px} · {_h(BAND_LABEL[band])}")
            lines.append(f"   {_h(why)}")
        lines.append(GUARD_FOOTER)
        if not dispatch("\n".join(lines), subject="Holding alert"):
            return 0
        for sym, *_ in hits:
            state[f"guard_{sym}"] = today
        return 1
    except Exception as e:                                  # noqa: BLE001
        print(f"[holding-guard] failed: {type(e).__name__}: {e}")
        return 0
