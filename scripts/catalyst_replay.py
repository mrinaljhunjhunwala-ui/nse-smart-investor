"""Replay the results / news calls over the last few sessions and grade them.

For each of the last N completed NSE sessions this rebuilds what the pre-open
catalyst alert (alerts/catalyst_alerts.py) would have read that morning, using
only the daily bars up to the previous close plus that day's opening price as
the pre-open gap, then measures what happened next.

What it can and cannot show (printed with the result):
  * Events: NSE announcements filed from the previous session's open up to the
    09:15 open of the session being replayed (filings made during a session are
    acted on at the NEXT open; the 15-minute live alert is not replayed).
  * Quarterly figures are the ones available today, cut to quarters that had
    ended by the replay date. No analyst estimates: "surprise" is vs the
    year-ago quarter.
  * Daily bars only, so the order of high and low inside a day is unknown. A day
    that touches both stop and target is counted as a stop (the harsher read).
  * One week is a small sample. This checks that the rules behave sensibly; it
    does not prove an edge.

Usage:  python scripts/catalyst_replay.py --sessions 5 --cap 80 [--telegram]
Needs network (NSE, Yahoo, Screener): run it from GitHub Actions
(provider_canary.yml, input replay_sessions), not from a sandbox.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import sys
import time
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

IST = _dt.timezone(_dt.timedelta(hours=5, minutes=30))


def _base(t: Any) -> str:
    return str(t or "").upper().replace(".NS", "").replace(".BO", "").strip()


def _pct(a: Optional[float], b: Optional[float]) -> Optional[float]:
    if a is None or b is None or not b:
        return None
    return (a / b - 1.0) * 100.0


def grade_day(action: str, trigger: Optional[float], stop: Optional[float], target: Optional[float],
              o: float, h: float, lo: float, c: float) -> Dict[str, Any]:
    """Outcome of one call on its own day from that day's OHLC. Pure.

    BUY: entered when the day trades at or above the trigger (at the open if it
    opens above it). Stop touched -> -1R, even if the target was also touched;
    else target touched -> +reward/risk; else marked at the close. SELL mirrors.
    Returns {"entered", "outcome": stop|target|close|no_entry|no_plan, "r", "entry"}."""
    if action not in ("BUY", "SELL") or not trigger or not stop or trigger == stop:
        return {"entered": False, "outcome": "no_plan", "r": None, "entry": None}
    up = action == "BUY"
    if (up and h < trigger) or (not up and lo > trigger):
        return {"entered": False, "outcome": "no_entry", "r": None, "entry": None}
    entry = max(trigger, o) if up else min(trigger, o)
    risk = (entry - stop) if up else (stop - entry)
    if risk <= 0:
        return {"entered": False, "outcome": "no_plan", "r": None, "entry": entry}
    if (up and lo <= stop) or (not up and h >= stop):
        return {"entered": True, "outcome": "stop", "r": -1.0, "entry": entry}
    if target and ((up and h >= target) or (not up and lo <= target)):
        return {"entered": True, "outcome": "target", "r": abs(target - entry) / risk, "entry": entry}
    return {"entered": True, "outcome": "close", "r": ((c - entry) if up else (entry - c)) / risk, "entry": entry}


def surprise_bucket(score: Optional[float]) -> str:
    if score is None:
        return "no figures"
    if score >= 25:
        return "strong results (score >= +25)"
    if score <= -25:
        return "weak results (score <= -25)"
    return "mixed results"


def summarise(rows: List[dict]) -> Dict[str, Any]:
    """Aggregate replay rows. Pure. Rows carry action, outcome, r, open_to_close,
    open_to_last, nifty_to_last, bucket, kind."""
    def avg(xs):
        xs = [x for x in xs if x is not None]
        return round(sum(xs) / len(xs), 2) if xs else None

    out: Dict[str, Any] = {"n": len(rows), "by_action": {}, "by_bucket": {}}
    for act in ("BUY", "SELL", "WATCH"):
        rs = [r for r in rows if r.get("action") == act]
        ent = [r for r in rs if r.get("entered")]
        out["by_action"][act] = {
            "n": len(rs), "entered": len(ent),
            "stop": sum(r["outcome"] == "stop" for r in ent),
            "target": sum(r["outcome"] == "target" for r in ent),
            "wins": sum((r.get("r") or 0) > 0 for r in ent),
            "avg_r": avg([r.get("r") for r in ent]),
            "avg_open_to_close": avg([r.get("open_to_close") for r in rs]),
            "avg_open_to_last": avg([r.get("open_to_last") for r in rs]),
            "avg_vs_nifty_to_last": avg([(r["open_to_last"] - r["nifty_to_last"])
                                         for r in rs if r.get("open_to_last") is not None
                                         and r.get("nifty_to_last") is not None]),
        }
    for r in rows:
        if r.get("kind") != "results":
            continue
        b = out["by_bucket"].setdefault(r["bucket"], [])
        b.append(r)
    out["by_bucket"] = {
        k: {"n": len(v), "avg_gap": avg([x.get("gap") for x in v]),
            "avg_day_move": avg([x.get("day_move") for x in v]),
            "avg_open_to_last": avg([x.get("open_to_last") for x in v]),
            "up_on_day": sum((x.get("day_move") or 0) > 0 for x in v)}
        for k, v in out["by_bucket"].items()}
    return out


def _fmt(x: Optional[float], suffix: str = "%") -> str:
    return "n/a" if x is None else f"{x:+.1f}{suffix}"


def report_lines(rows: List[dict], summ: Dict[str, Any], sessions: List[_dt.date]) -> List[str]:
    lines = [f"CATALYST REPLAY  {sessions[0]} -> {sessions[-1]}  "
             f"({len(sessions)} sessions, {summ['n']} event names)", ""]
    lines.append("Calls the pre-open alert would have made:")
    for act, a in summ["by_action"].items():
        if not a["n"]:
            continue
        line = f"  {act:<5} {a['n']:>3} names"
        if act != "WATCH":
            line += (f" | entered {a['entered']} | target {a['target']} | stop {a['stop']} | "
                     f"profitable {a['wins']} | average {_fmt(a['avg_r'], 'R')}")
        line += (f" | open->close {_fmt(a['avg_open_to_close'])} | open->latest {_fmt(a['avg_open_to_last'])}"
                 f" (vs Nifty {_fmt(a['avg_vs_nifty_to_last'], ' pts')})")
        lines.append(line)
    lines += ["", "Did the quarter's numbers line up with the price? (results filers only; day move = previous "
              "close to that day's close)"]
    for k, b in sorted(summ["by_bucket"].items()):
        lines.append(f"  {k:<32} {b['n']:>3} names | gap {_fmt(b['avg_gap'])} | day move {_fmt(b['avg_day_move'])}"
                     f" ({b['up_on_day']} up) | open->latest {_fmt(b['avg_open_to_last'])}")
    lines += ["", "Every call (strongest first per day):",
              "  date        act   symbol        str  gap     day     open->last  outcome   R      why"]
    for r in sorted(rows, key=lambda x: (x["date"], {"BUY": 0, "SELL": 1, "WATCH": 2}.get(x["action"], 3),
                                         -(x.get("strength") or 0))):
        if r["action"] not in ("BUY", "SELL", "WATCH"):
            continue
        lines.append(f"  {r['date']}  {r['action']:<5} {r['symbol']:<13} {r.get('strength') or 0:>3}  "
                     f"{_fmt(r.get('gap')):>6}  {_fmt(r.get('day_move')):>6}  {_fmt(r.get('open_to_last')):>9}   "
                     f"{r.get('outcome', ''):<9} {_fmt(r.get('r'), 'R'):>6} {'; '.join(r.get('reasons') or [])[:90]}")
    movers = sorted([r for r in rows if r.get("day_move") is not None], key=lambda x: -abs(x["day_move"]))[:12]
    lines += ["", "Biggest day moves among names with a filing, and what the app would have said:"]
    for r in movers:
        lines.append(f"  {r['date']} {r['symbol']:<13} {_fmt(r['day_move']):>7}  call={r['action']:<8} "
                     f"{'; '.join(r.get('why') or r.get('reasons') or [])[:110]}")
    lines += ["", "Limits: daily bars (a day touching stop and target counts as a stop); quarterly figures as "
              "available today; filings made during a session are replayed at the next open; one week is a small "
              "sample."]
    return lines


def run(n_sessions: int, cap: int) -> Dict[str, Any]:
    import pandas as pd

    from analysis import catalysts as C
    from alerts import catalyst_alerts as CA
    from data import nse_announcements as NA
    from data.fetcher import fetch_index, fetch_single
    from data.universe import get_sector, get_universe

    nifty = fetch_index("^NSEI", period="3mo")
    if nifty is None or nifty.empty:
        raise SystemExit("Nifty history unavailable - cannot replay")
    nidx = [d.date() for d in pd.to_datetime(nifty.index)]
    today = _dt.datetime.now(IST)
    done = [d for d in nidx if d < today.date() or today.time() >= _dt.time(15, 45)]
    sessions = done[-n_sessions:]
    prev_of = {d: done[done.index(d) - 1] for d in sessions if done.index(d) > 0}
    sessions = [d for d in sessions if d in prev_of]
    nclose = {d: float(c) for d, c in zip(nidx, nifty["Close"])}
    nopen = {d: float(o) for d, o in zip(nidx, nifty["Open"])}
    universe = {_base(t) for t in get_universe("all")}
    hol = CA._holidays()

    events: List[dict] = []
    for d in sorted({prev_of[s] for s in sessions} | set(sessions)):
        lo_t = _dt.datetime.combine(d, _dt.time(0, 0), tzinfo=IST)
        got = NA.fetch_announcements(lo_t, lo_t + _dt.timedelta(days=1)) or []
        print(f"[replay] {d}: {len(got)} announcements")
        events += got
        time.sleep(1.0)
    # weekend / holiday filings between sessions
    first, last = min(prev_of.values()), max(sessions)
    gaps = [first + _dt.timedelta(days=i) for i in range((last - first).days + 1)]
    for d in gaps:
        if d not in nidx:
            lo_t = _dt.datetime.combine(d, _dt.time(0, 0), tzinfo=IST)
            events += NA.fetch_announcements(lo_t, lo_t + _dt.timedelta(days=1)) or []
            time.sleep(1.0)
    seen, uniq = set(), []
    for e in events:
        k = (e.get("symbol"), str(e.get("when")), e.get("headline"))
        if k not in seen:
            seen.add(k)
            uniq.append(e)
    events = uniq
    print(f"[replay] {len(events)} announcements in window; universe {len(universe)} names")

    frames: Dict[str, Any] = {}
    quarters: Dict[str, list] = {}
    rows: List[dict] = []
    for s in sessions:
        p = prev_of[s]
        w_lo = _dt.datetime.combine(p, _dt.time(9, 15), tzinfo=IST)
        w_hi = _dt.datetime.combine(s, _dt.time(9, 15), tzinfo=IST)
        now = _dt.datetime.combine(s, _dt.time(8, 50), tzinfo=IST)
        by_sym: Dict[str, List[dict]] = {}
        for e in events:
            when = C._to_ist(e.get("when"))
            sym = _base(e.get("symbol"))
            if when is None or sym not in universe or not (w_lo < when <= w_hi):
                continue
            by_sym.setdefault(sym, []).append(e)
        ranked = []
        for sym, evs in by_sym.items():
            cats = [(C.classify_announcement(e.get("category"), e.get("headline"), e.get("detail")), e) for e in evs]
            cats = [(c, e) for c, e in cats if c is not None]
            if cats:
                ranked.append((max(c.weight for c, _ in cats), sym, [e for _, e in cats],
                               sorted({c.kind for c, _ in cats})))
        ranked.sort(key=lambda x: (-x[0], x[1]))
        print(f"[replay] {s}: {len(by_sym)} universe names with filings, {len(ranked)} classified, "
              f"replaying {min(cap, len(ranked))}")
        for _w, sym, evs, kinds in ranked[:cap]:
            try:
                if sym not in frames:
                    frames[sym] = fetch_single(f"{sym}.NS", period="6mo")
                df = frames[sym]
                if df is None or df.empty:
                    continue
                dates = [d.date() for d in pd.to_datetime(df.index)]
                if s not in dates:
                    continue
                i = dates.index(s)
                if i < 30:
                    continue
                hist = df.iloc[:i]
                bar = df.iloc[i]
                o, h, lo, c = (float(bar[k]) for k in ("Open", "High", "Low", "Close"))
                prev_close = float(hist["Close"].iloc[-1])
                last_close = float(df["Close"].iloc[-1])
                surprise = None
                if "results" in kinds:
                    if sym not in quarters:
                        quarters[sym] = NA.fetch_quarterly_figures(sym) or []
                        time.sleep(0.6)
                    qs = [q for q in quarters[sym] if q.get("period_end") and q["period_end"] < s]
                    is_lender = CA._is_lender(get_sector(sym))
                    surprise = C.results_surprise(qs, is_lender=is_lender) if qs else None
                newest = max(evs, key=lambda e: C._to_ist(e.get("when")) or now)
                rx = C.reaction(hist, newest.get("when"), nifty_df=nifty.iloc[:nidx.index(s)])
                pre = {"iep": o, "prev_close": prev_close, "gap_pct": _pct(o, prev_close)}
                read = C.catalyst_read(sym, evs, surprise, rx, preopen=pre, now=now, holidays=hol)
                action = read.action if read is not None else "no call"
                g = grade_day(action, getattr(read, "trigger", None), getattr(read, "stop", None),
                              getattr(read, "target", None), o, h, lo, c)
                day_move = _pct(c, prev_close)
                why = C.explain_move(sym, day_move or 0.0, events=evs, surprise=surprise,
                                     reaction=C.reaction(df.iloc[:i + 1], s), sector_return_pct=None,
                                     nifty_return_pct=_pct(nclose.get(s), nclose.get(p)))
                rows.append({
                    "date": s.isoformat(), "symbol": sym, "kind": "results" if "results" in kinds else kinds[0],
                    "action": action, "strength": getattr(read, "strength", None),
                    "reasons": list(getattr(read, "reasons", []) or []), "why": list(why or []),
                    "trigger": getattr(read, "trigger", None), "stop": getattr(read, "stop", None),
                    "target": getattr(read, "target", None),
                    "surprise": (surprise or {}).get("score"), "bucket": surprise_bucket((surprise or {}).get("score")),
                    "profit_yoy": (surprise or {}).get("profit_yoy_pct"),
                    "revenue_yoy": (surprise or {}).get("revenue_yoy_pct"),
                    "gap": pre["gap_pct"], "day_move": day_move, "open_to_close": _pct(c, o),
                    "open_to_last": _pct(last_close, o),
                    "nifty_to_last": _pct(float(nifty["Close"].iloc[-1]), nopen.get(s)),
                    **g,
                })
            except Exception as e:                              # noqa: BLE001
                print(f"[replay] {s} {sym}: skipped ({type(e).__name__}: {e})")
    summ = summarise(rows)
    return {"sessions": sessions, "rows": rows, "summary": summ}


def telegram_lines(summ: Dict[str, Any], sessions: List[_dt.date]) -> List[str]:
    lines = [f"🧪 <b>Results / news calls replayed</b> · {sessions[0]:%d %b} → {sessions[-1]:%d %b}"]
    for act in ("BUY", "SELL"):
        a = summ["by_action"][act]
        if a["n"]:
            lines.append(f"{act}: {a['n']} calls · {a['entered']} entered · {a['target']} hit target · "
                         f"{a['stop']} stopped · average {_fmt(a['avg_r'], 'R')}")
    w = summ["by_action"]["WATCH"]
    if w["n"]:
        lines.append(f"WATCH: {w['n']} names · open→latest {_fmt(w['avg_open_to_last'])}")
    for k, b in sorted(summ["by_bucket"].items()):
        lines.append(f"{k}: {b['n']} names · day move {_fmt(b['avg_day_move'])} · after the open "
                     f"{_fmt(b['avg_open_to_last'])}")
    lines.append("One week, daily bars: a behaviour check, not proof. Full table in the Actions log.")
    return lines


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sessions", type=int, default=5)
    ap.add_argument("--cap", type=int, default=80, help="max names replayed per session")
    ap.add_argument("--telegram", action="store_true")
    args = ap.parse_args(argv)
    res = run(max(1, args.sessions), max(1, args.cap))
    if not res["sessions"]:
        print("[replay] no completed sessions to replay")
        return 0
    lines = report_lines(res["rows"], res["summary"], res["sessions"])
    print("\n".join(lines))
    step = os.environ.get("GITHUB_STEP_SUMMARY")
    if step:
        with open(step, "a", encoding="utf-8") as fh:
            fh.write("```\n" + "\n".join(lines) + "\n```\n")
    try:
        import trade_store as store
        store.kv_set(f"catalyst_replay:{res['sessions'][-1].isoformat()}",
                     {"summary": res["summary"], "rows": res["rows"],
                      "sessions": [d.isoformat() for d in res["sessions"]]}, user_id="_system")
    except Exception as e:                                      # noqa: BLE001
        print(f"[replay] not persisted: {type(e).__name__}: {e}")
    print("[replay] summary json: " + json.dumps(res["summary"], default=str))
    if args.telegram:
        try:
            from alerts.check_alerts import dispatch
            dispatch("\n".join(telegram_lines(res["summary"], res["sessions"])),
                     subject="Results / news calls replayed")
        except Exception as e:                                  # noqa: BLE001
            print(f"[replay] Telegram send failed (ignored): {type(e).__name__}: {e}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
