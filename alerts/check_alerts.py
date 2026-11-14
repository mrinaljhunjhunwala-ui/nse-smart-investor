"""
alerts/check_alerts.py — Headless market alert checker.

Runs on a schedule (GitHub Actions) during NSE market hours and sends a
Telegram message when:
    1. A custom price alert from data/alerts.csv triggers
       (price crosses above/below a level you defined)
    2. India VIX enters a fear/panic regime
    3. Nifty 50 breaks into a confirmed downtrend

NO Streamlit dependency — pure Python stdlib + the project's headless
data helpers (utils.vix, utils.live_price, data.fetcher). Safe to run in CI.

Credentials (set as GitHub Actions secrets, NEVER committed):
    TELEGRAM_BOT_TOKEN   — from @BotFather
    TELEGRAM_CHAT_ID     — your numeric chat id (from @userinfobot)

De-duplication:
    A small data/alert_state.json records which alerts already fired today,
    so the same alert is not re-sent every run. The GitHub Actions cache
    persists this file between runs.

Exit codes: always 0 (a failed alert check should not fail the workflow).
"""

from __future__ import annotations

import html as _html
import datetime
import json
import re
import logging
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

_log = logging.getLogger("alerts.check_alerts")

# Ensure emoji/Unicode in log output never crash on a non-UTF-8 console (Windows)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception as _enc_e:
    print(f"[startup] stdout reconfigure skipped: {_enc_e}")

# Make project root importable (script lives in <root>/alerts/)
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from analysis.action_labels import action_display_label, verdict_display_label  # noqa: E402

_ALERTS_CSV  = os.path.join(_ROOT, "data", "alerts.csv")
_STATE_JSON  = os.path.join(_ROOT, "data", "alert_state.json")
_IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30))


# ─────────────────────────────────────────────────────────────────────────────
# Telegram
# ─────────────────────────────────────────────────────────────────────────────

def _h(x) -> str:
    """HTML-escape outside text (tickers, sectors, reasons) before it goes into
    a parse_mode=HTML message — a bare & or < makes Telegram reject the send."""
    return _html.escape(str(x), quote=False)


def _plain(text: str) -> str:
    """Strip tags and unescape entities — the plain-text fallback body."""
    return _html.unescape(re.sub(r"<[^>]+>", "", text))


# ── Message copy (owner decision 13 Nov 2026: direct BUY / SELL wording, short) ──
# Line 1: emoji + bold title + time. One line per stock, action word first:
#   "STRONG BUY  <b>PNB</b>  ₹118.40 · stop ₹112.10 · target ₹131.00"
# One short footer at most. Copy only — logic, caps and dedupe keys unchanged.
_FOOTER = "<i>Model output, not a guarantee.</i>"
_MARKET_DOWN = "Market: downtrend — smaller size"


def _now_hm() -> str:
    return f"{datetime.datetime.now(_IST):%H:%M}"


def _rs(x) -> str:
    """₹-formatted number; non-numeric levels (e.g. '~1000') pass through escaped."""
    try:
        return f"₹{float(x):,.2f}"
    except (TypeError, ValueError):
        return _h(x)


def _stock_line(word: str, symbol, price=None, stop=None, target=None, extra: str = "") -> str:
    """'BUY  <b>SYM</b>  ₹price · stop ₹x · target ₹y' — missing parts dropped."""
    parts = [f"{word}  <b>{_h(symbol)}</b>"]
    head = f"{_rs(price)}" if price not in (None, "") else ""
    tail = [s for s in (head,
                        f"stop {_rs(stop)}" if stop not in (None, "", 0) else "",
                        f"target {_rs(target)}" if target not in (None, "", 0) else "",
                        extra) if s]
    return parts[0] + ("  " + " · ".join(tail) if tail else "")


def send_telegram(text: str) -> bool:
    """Send an HTML message to the configured Telegram chat."""
    token   = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        print("[telegram] TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set — printing instead:")
        print(text)
        return False
    try:
        url  = f"https://api.telegram.org/bot{token}/sendMessage"
        data = urllib.parse.urlencode({
            "chat_id":    chat_id,
            "text":       text,
            "parse_mode": "HTML",
            "disable_web_page_preview": "true",
        }).encode()
        req = urllib.request.Request(url, data=data)
        with urllib.request.urlopen(req, timeout=15) as r:
            ok = r.status == 200
            print(f"[telegram] sent ({r.status})")
            return ok
    except urllib.error.HTTPError as e:
        if e.code != 400:
            print(f"[telegram] FAILED: {e}")
            return False
        # 400 = Telegram couldn't parse the HTML. Don't lose the alert:
        # resend the same content as plain text.
        print(f"[telegram] HTML rejected ({e}) — resending as plain text")
        try:
            data = urllib.parse.urlencode({
                "chat_id": chat_id, "text": _plain(text),
                "disable_web_page_preview": "true",
            }).encode()
            with urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=15) as r:
                print(f"[telegram] sent as plain text ({r.status})")
                return r.status == 200
        except Exception as e2:
            print(f"[telegram] FAILED: {e2}")
            return False
    except Exception as e:
        print(f"[telegram] FAILED: {e}")
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Gmail (Task 4.1 Q1 answer, added 2026-09-08)
# ─────────────────────────────────────────────────────────────────────────────

def send_gmail(subject: str, body_html: str) -> bool:
    """Send the alert as email via Gmail SMTP. body_html is stripped of
    the HTML tags used for Telegram, since email clients render plain
    text more reliably across mobile / web / desktop."""
    try:
        from utils.alerts_gmail import GmailAlerter
    except ImportError as _ie:
        print(f"[gmail] alerts_gmail import failed: {_ie}")
        return False
    import re as _re
    # Cheap HTML-to-text: strip <b>/<i>/<br>/etc, keep whitespace.
    _plain = _re.sub(r"<[^>]+>", "", body_html)
    _plain = (_plain
              .replace("&amp;", "&")
              .replace("&lt;",  "<")
              .replace("&gt;",  ">")
              .replace("&nbsp;", " "))
    return GmailAlerter().send(subject, _plain)


def _subject_from_message(msg: str, fallback: str) -> str:
    """Derive a subject line from the first non-empty line of the alert
    text, with HTML tags stripped and length-capped. Falls back to the
    channel-level label if the message is empty."""
    import re as _re
    first = ""
    for _ln in msg.splitlines():
        _s = _re.sub(r"<[^>]+>", "", _ln).strip()
        if _s:
            first = _s
            break
    if not first:
        return fallback
    return (first[:120] + "...") if len(first) > 120 else first


def dispatch(msg: str, *, subject: str = "NSE Smart Investor alert") -> bool:
    """Fan one alert out to every configured channel. Returns True if at
    least one channel accepted the message (so the de-dup marker gets
    set), False only if BOTH channels failed AND neither was in console-
    fallback mode. Channels that are unconfigured print to console and
    count as delivered locally (matching prior behaviour so a local dev
    run still marks the state file)."""
    _subj = _subject_from_message(msg, fallback=subject)
    _tg_ok    = send_telegram(msg)
    _gmail_ok = send_gmail(_subj, msg)
    # Name the alert in the run log — "1 alert(s) sent" alone didn't say which.
    print(f"[sent] {_subj} (telegram={'ok' if _tg_ok else 'fail'}, "
          f"gmail={'ok' if _gmail_ok else 'fail'})")
    return bool(_tg_ok or _gmail_ok)


# ─────────────────────────────────────────────────────────────────────────────
# De-dup state (per-day)
# ─────────────────────────────────────────────────────────────────────────────

def _load_state() -> dict:
    try:
        with open(_STATE_JSON, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}   # normal on first run — no state file yet
    except Exception as e:
        _log.warning(
            "_load_state: %s exists but is unreadable/corrupt, resetting to empty "
            "state (previously-fired alerts may re-fire today): %s", _STATE_JSON, e
        )
        return {}


def _save_state(state: dict) -> None:
    try:
        with open(_STATE_JSON, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
    except Exception as e:
        print(f"[state] could not save: {e}")


# _FORCE_SEND is set to True by main() when --force is on argv. It makes
# _already_fired() always return False AND _mark_fired() a no-op, so a
# manual test run (workflow_dispatch) does not pollute the shared state
# file and thereby starve subsequent scheduled runs of the same bucket.
# Root cause of "scheduled cron produced no email" bug diagnosed via the
# GitHub Actions runs API 2026-09-09: workflow_dispatch runs at 12:58 and
# 13:04 IST stamped momentum_pm=today, then every scheduled fire that
# afternoon saw dedup-set and exited in <1 second silently.
_FORCE_SEND = False


def _already_fired(state: dict, key: str, today: str) -> bool:
    """Dedup check. Prints when it's returning True so scheduled runs that
    silently skip because of dedup show up in the workflow log — before
    this diagnostic print, the "successful 1-second run that sent nothing"
    was indistinguishable from a healthy send in the Actions UI."""
    if _FORCE_SEND:
        # --force bypasses dedup for manual testing so the tester actually
        # sees the alert land in Gmail/Telegram right now.
        return False
    already = state.get(key) == today
    if already:
        print(f"[dedup] '{key}' already fired today ({today}) — skipping this check")
    return already


def _mark_fired(state: dict, key: str, today: str) -> None:
    """Set dedup state. --force is a no-op so manual tests don't leave a
    stamp that later starves the real scheduled fire."""
    if _FORCE_SEND:
        print(f"[dedup] --force is set; NOT marking '{key}' fired "
              "(manual test won't block the real scheduled fire)")
        return
    state[key] = today


def _prune_state(state: dict, today: str) -> dict:
    """Keep only today's entries so the file doesn't grow forever."""
    return {k: v for k, v in state.items() if v == today}


# ─────────────────────────────────────────────────────────────────────────────
# Market hours guard
#
# FIX HOL1: this used to be a hand-rolled weekday+time-of-day check with no
# NSE holiday awareness at all — a real gap given FIX MH2 (see
# dashboard/shared/market_hours.py) already consolidated every OTHER
# market-hours check in the repo onto one canonical, holiday-aware calendar
# specifically because a second, independent implementation like this one
# drifts out of date. Without this fix, check_price_alerts() would run and
# attempt to fetch "live" prices on every NSE holiday that falls on a
# weekday, on a schedule that fires every 15 minutes for ~8 hours.
# ─────────────────────────────────────────────────────────────────────────────

def _is_market_hours() -> bool:
    from dashboard.shared.market_hours import is_market_open
    return is_market_open()


# Morning messages bypass the market-hours guard, so they need their own
# clock: on 2026-09-30 GitHub ran the 09:20 cron at 15:31 and the "morning"
# watchlist went out after the close. A trigger outside the window is dropped.
_SEND_WINDOWS = {
    "morning-digest":     (datetime.time(7, 0),  datetime.time(10, 0)),
    "intraday-watchlist": (datetime.time(9, 15), datetime.time(10, 30)),
    "catalyst-preopen":   (datetime.time(8, 0),  datetime.time(9, 20)),
    "why-moved":          (datetime.time(15, 35), datetime.time(21, 0)),
}


def _in_send_window(mode: str, now: datetime.datetime | None = None) -> bool:
    window = _SEND_WINDOWS.get(mode)
    if window is None:
        return True
    t = (now or datetime.datetime.now(_IST)).astimezone(_IST).time()
    return window[0] <= t < window[1]


# ─────────────────────────────────────────────────────────────────────────────
# Checks
# ─────────────────────────────────────────────────────────────────────────────

def check_price_alerts(state: dict, today: str) -> int:
    """Read data/alerts.csv, fetch live prices, fire on threshold crossings."""
    sent = 0
    try:
        import csv
        from utils.live_price import get_live_quote
    except Exception as e:
        print(f"[price] import failed: {e}")
        return 0

    rules = []
    try:
        with open(_ALERTS_CSV, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if str(row.get("enabled", "1")).strip() in ("0", "false", "False", ""):
                    continue
                rules.append(row)
    except FileNotFoundError:
        print(f"[price] no alerts.csv at {_ALERTS_CSV}")
        return 0
    except Exception as e:
        print(f"[price] could not read alerts.csv: {e}")
        return 0

    for r in rules:
        ticker    = str(r.get("ticker", "")).strip().upper()
        condition = str(r.get("condition", "")).strip().lower()
        try:
            level = float(r.get("level", 0))
        except Exception as _lvl_e:
            print(f"[price] {r.get('ticker','?')}: invalid level '{r.get('level')}' — {_lvl_e}")
            continue
        note = str(r.get("note", "")).strip()
        if not ticker or condition not in ("above", "below") or level <= 0:
            continue

        key = f"price_{ticker}_{condition}_{level:.2f}"
        if _already_fired(state, key, today):
            continue

        q = get_live_quote(ticker)
        if not q or not q.get("price"):
            print(f"[price] {ticker}: no quote")
            continue
        price = float(q["price"])

        hit = (condition == "above" and price >= level) or \
              (condition == "below" and price <= level)
        if not hit:
            continue

        arrow = "🔼" if condition == "above" else "🔽"
        chg   = q.get("chg_pct", 0.0)
        msg = (
            f"{arrow} <b>{_h(ticker)} {condition} ₹{level:,.2f}</b> · {_now_hm()}\n"
            f"Now <b>₹{price:,.2f}</b> ({chg:+.2f}% today)"
            + (f"\n📝 {_h(note)}" if note else "")
        )
        if dispatch(msg):
            _mark_fired(state, key, today)
            sent += 1
    return sent


# ─────────────────────────────────────────────────────────────────────────────
# Portfolio alerts — derived from the My Portfolio holdings on every run
#
# No list to maintain: holdings are read from the same trade_store KV key the
# My Portfolio page writes, so adds / sells / avg-price edits take effect on
# the next run. Two alerts per holding:
#   * Step move: ±_PF_STEP_PCT from a per-holding reference price. The first
#     sighting only records the reference; each alert re-anchors it to the
#     alert price, so the next alert is the NEXT 10% move, not a repeat.
#   * Cost cross: price crosses the current average buy price, either way.
# References + last cost side persist in KV (_PF_ANCHORS_KEY, user "_system");
# sold holdings are pruned from it.
# ─────────────────────────────────────────────────────────────────────────────

def _holding_alerts_on() -> bool:
    """Holdings alerts (avg-cost, ±10%, levels on holdings) are opt-in since
    2026-10-01 — the user wants alerts on the digest picks, not their holdings.
    Set the repo variable ALERT_HOLDINGS=1 to bring them back."""
    return os.getenv("ALERT_HOLDINGS", "").strip().lower() in ("1", "true", "yes")


_PF_HOLDINGS_KEY = "manual_portfolio_holdings"
_PF_ANCHORS_KEY  = "portfolio_alert_anchors"
_PF_STEP_PCT     = 10.0
_PF_COST_MARGIN_PCT = 1.0


def check_portfolio_alerts(state: dict, today: str) -> int:
    try:
        import trade_store as store
        from utils.live_price import get_live_quote
    except Exception as e:
        print(f"[portfolio] import failed: {e}")
        return 0
    try:
        holdings = store.kv_get(_PF_HOLDINGS_KEY, None) or []
        anchors  = store.kv_get(_PF_ANCHORS_KEY, None, user_id="_system") or {}
    except Exception as e:
        print(f"[portfolio] kv read failed: {e}")
        return 0
    if not holdings:
        print("[portfolio] no holdings on the My Portfolio page — nothing to check")
        return 0

    sent, held = 0, set()
    for h in holdings:
        ticker = str(h.get("ticker", "")).upper().replace(".NS", "").replace(".BO", "").strip()
        try:
            avg = float(h.get("avg_buy_price") or 0)
        except (TypeError, ValueError):
            avg = 0.0
        if not ticker:
            continue
        held.add(ticker)
        q = get_live_quote(ticker)
        if not q or not q.get("price"):
            print(f"[portfolio] {ticker}: no quote")
            continue
        price = float(q["price"])
        chg = q.get("chg_pct", 0.0) or 0.0
        a = anchors.get(ticker)
        if not a or not a.get("ref"):
            anchors[ticker] = {"ref": price, "ref_date": today,
                               "side": ("above" if price >= avg else "below") if avg else None}
            print(f"[portfolio] {ticker}: reference set at {price:.2f}")
            continue

        # 1) Step move from the reference price
        ref = float(a["ref"])
        move = (price / ref - 1) * 100
        if abs(move) >= _PF_STEP_PCT:
            key = f"pf_step_{ticker}_{ref:.2f}"
            if not _already_fired(state, key, today):
                arrow = "🔼" if move > 0 else "🔽"
                msg = (f"{arrow} <b>{_h(ticker)} {move:+.1f}% since ₹{ref:,.2f}</b> · {_now_hm()}\n"
                       f"Now ₹{price:,.2f} ({chg:+.2f}% today) · holding since {a.get('ref_date', '?')} "
                       f"· next alert ±{_PF_STEP_PCT:.0f}%")
                if dispatch(msg):
                    _mark_fired(state, key, today)
                    sent += 1
                    a["ref"], a["ref_date"] = price, today

        # 2) Average-cost cross. A cross only counts once the price is
        # _PF_COST_MARGIN_PCT past the average, and at most one alert per
        # holding per day: on 2026-10-01 ONGC wobbled 21 paise around its
        # average and sent "above" then "below" 15 min apart.
        if avg:
            band = avg * _PF_COST_MARGIN_PCT / 100
            side = ("above" if price >= avg + band else
                    "below" if price <= avg - band else None)
            if not a.get("side"):
                a["side"] = side or ("above" if price >= avg else "below")
            elif side and side != a["side"]:
                a["side"] = side
                key = f"pf_cost_{ticker}"
                if not _already_fired(state, key, today):
                    arrow = "🔼" if side == "above" else "🔽"
                    msg = (f"{arrow} <b>{_h(ticker)} crossed {side} your average cost ₹{avg:,.2f}</b>"
                           f" · {_now_hm()}\n"
                           f"Now ₹{price:,.2f} ({chg:+.2f}% today)")
                    if dispatch(msg):
                        _mark_fired(state, key, today)
                        sent += 1

    for t in [t for t in anchors if t not in held]:
        print(f"[portfolio] {t}: no longer held — dropping its reference")
        anchors.pop(t)
    try:
        store.kv_set(_PF_ANCHORS_KEY, anchors, user_id="_system")
    except Exception as e:
        print(f"[portfolio] kv write failed: {e}")
    return sent


# ─────────────────────────────────────────────────────────────────────────────
# Digest picks through the day — the user follows the suggested stocks, not
# their holdings (2026-10-02). Three messages, all about today's Morning
# Digest names:
#   * Opening update  — first run from 09:30: open, gap, first-15-min range
#   * ±2% moves       — day change from yesterday's close crosses ±2%, once
#                       per direction per stock per day (a stock that falls
#                       2% and then rallies 2% sends both)
#   * Picks recap     — first run from 15:15: move since the scan + day range
# Levels come from analysis/intraday_levels.py and are saved by the 09:20
# watchlist (KV intraday_levels) so later runs reuse the same numbers.
# ─────────────────────────────────────────────────────────────────────────────

_MOVE_PCT = 2.0
_OPENING_FROM = datetime.time(9, 30)
_OPENING_UNTIL = datetime.time(10, 30)
_RECAP_FROM = datetime.time(15, 15)
_LEVELS_KEY = "intraday_levels"


def _base_symbol(t) -> str:
    return str(t or "").upper().replace(".NS", "").replace(".BO", "").strip()


def _today_picks(store, today: str) -> dict | None:
    """Today's saved Morning Digest picks, or None."""
    try:
        morning = store.kv_get(_MORNING_PICKS_KEY, None, user_id="_system")
    except Exception:
        return None
    if isinstance(morning, dict) and morning.get("date") == today and morning.get("buys"):
        return morning
    return None


def _pick_levels(store, base: str, today: str) -> dict | None:
    """The watchlist's saved levels for `base`, else computed from daily bars."""
    try:
        saved = store.kv_get(_LEVELS_KEY, None, user_id="_system")
    except Exception:
        saved = None
    if isinstance(saved, dict) and saved.get("date") == today and base in (saved.get("levels") or {}):
        return saved["levels"][base]
    try:
        import pandas as pd
        from analysis.intraday_levels import daily_levels
        from data.fetcher import fetch_single
        df = fetch_single(f"{base}.NS", period="3mo")
        df = df[pd.to_datetime(df.index).strftime("%Y-%m-%d") < today]
        return daily_levels(df)
    except Exception as e:
        _log.debug("levels for %s failed: %s", base, e)
        return None


def _pick_session(base: str, today: str) -> dict | None:
    """Today's open / high / low / last / opening range from 5-min bars."""
    try:
        from analysis.intraday_levels import session_stats
        from data.fetcher import fetch_intraday
        bars = fetch_intraday(f"{base}.NS", interval="5m", days=1)
        return session_stats(bars, datetime.date.fromisoformat(today))
    except Exception as e:
        _log.debug("session for %s failed: %s", base, e)
        return None


def _quote(base: str) -> dict | None:
    try:
        from utils.live_price import get_live_quote
        q = get_live_quote(base)
    except Exception:
        return None
    return q if q and q.get("price") else None


def check_opening_update(state: dict, today: str, now: datetime.datetime | None = None) -> int:
    key = "opening_update"
    if _already_fired(state, key, today):
        return 0
    now = (now or datetime.datetime.now(_IST)).astimezone(_IST)
    if not (_OPENING_FROM <= now.time() < _OPENING_UNTIL):
        return 0
    try:
        import trade_store as store
        from analysis.intraday_levels import position_vs_levels
    except Exception as e:
        print(f"[opening] import failed: {e}")
        return 0
    morning = _today_picks(store, today)
    if not morning:
        print("[opening] no Morning Digest picks for today — nothing to update")
        return 0

    rows = []
    for b in morning["buys"]:
        base = _base_symbol(b.get("ticker"))
        lv = _pick_levels(store, base, today)
        ss = _pick_session(base, today)
        q = _quote(base)
        price = float(q["price"]) if q else (ss or {}).get("last")
        if not price:
            rows.append(f"<b>{_h(base)}</b> — no price yet")
            continue
        prev = float((q or {}).get("prev_close") or (lv or {}).get("y_close") or 0)
        line = f"<b>{_h(base)}</b>"
        if ss and prev:
            line += f" opened ₹{ss['open']:,.2f} ({(ss['open'] / prev - 1) * 100:+.1f}% vs yesterday)"
        if ss and ss.get("or_high"):
            line += f" · first 15 min ₹{ss['or_low']:,.2f}–₹{ss['or_high']:,.2f}"
        day = f" ({(price / prev - 1) * 100:+.1f}%)" if prev else ""
        rows.append(line + f"\n   Now ₹{price:,.2f}{day}"
                    + (f" · {position_vs_levels(price, lv)}" if lv else ""))

    lines = [f"🔔 <b>Opening update — today's picks</b> · {now:%H:%M}"] + rows
    if dispatch("\n".join(lines), subject="Opening update — NSE Smart Investor"):
        _mark_fired(state, key, today)
        return 1
    return 0


def check_pick_moves(state: dict, today: str) -> int:
    try:
        import trade_store as store
        from analysis.intraday_levels import position_vs_levels
    except Exception as e:
        print(f"[moves] import failed: {e}")
        return 0
    morning = _today_picks(store, today)
    if not morning:
        return 0

    sent = 0
    for b in morning["buys"]:
        base = _base_symbol(b.get("ticker"))
        q = _quote(base)
        if not q:
            print(f"[moves] {base}: no quote")
            continue
        chg = float(q.get("chg_pct") or 0.0)
        if abs(chg) < _MOVE_PCT:
            continue
        direction = "up" if chg > 0 else "down"
        key = f"mv_{direction}_{base}"
        if _already_fired(state, key, today):
            continue
        price = float(q["price"])
        prev = q.get("prev_close")
        ss = _pick_session(base, today)
        lv = _pick_levels(store, base, today)
        icon = "🟢" if direction == "up" else "🔴"
        msg = f"{icon} <b>{_h(base)} {direction} {abs(chg):.1f}% today</b> · ₹{price:,.2f}"
        if prev:
            msg += f" (yesterday ₹{float(prev):,.2f})"
        msg += f" · {_now_hm()}"
        detail = ["Digest pick"]
        if ss:
            detail.append(f"day range so far ₹{ss['low']:,.2f}–₹{ss['high']:,.2f}")
        if lv:
            detail.append(position_vs_levels(price, lv))
        msg += "\n   " + " · ".join(detail)
        if dispatch(msg):
            _mark_fired(state, key, today)
            sent += 1
    return sent


_VERDICT_ALERT_TIERS = ("STRONG BUY", "BUY")
_VERDICT_MAX_SNAPSHOT_AGE_H = 2      # the warmer refreshes every 45 min in market hours
_VERDICT_MAX_PER_RUN = 8
# Per-day ceiling across all runs. In a rising market the full scan held 70-84
# BUY / STRONG BUY names (9 Nov), and 8 per 15-min run became ~40 messages by
# 10:30 IST. Strongest names go first, so the cap keeps the best reads.
_VERDICT_MAX_PER_DAY = 10
_TOMORROW_MAX_SNAPSHOT_AGE_H = 3             # caps a burst now that the whole scan is read


def _verdict_of(b: dict):
    """(verdict, conviction) for a snapshot pick, computed exactly as the
    dashboard cards do. None if it can't be computed."""
    try:
        from dashboard.shared.pick_freshness import compose_finalverdict_for_card
        fv = compose_finalverdict_for_card(b, tqs=None, log_source=None)
        return str(fv.verdict).upper(), getattr(fv, "conviction", "?")
    except Exception as e:
        print(f"[verdicts] {b.get('ticker')}: verdict failed: {e}")
        return None


def _regime_note() -> str:
    """One short market line, only when it changes the meaning (a down market)."""
    try:
        from analysis.score import _BEAR_REGIMES, _live_regime_label
        lbl = _live_regime_label()
    except Exception:
        return ""
    return _MARKET_DOWN if lbl and str(lbl).lower() in _BEAR_REGIMES else ""


def _verdict_pick_lines(verdict: str, b: dict, *, reason: bool = True) -> list:
    """'STRONG BUY  <b>PNB</b>  ₹118.40 · stop ₹112.10 · target ₹131.00' + optional reason line."""
    price = b.get("price")
    line = _stock_line(verdict_display_label(verdict), _base_symbol(b.get("ticker")),
                       price if isinstance(price, (int, float)) else None, b.get("sl"), b.get("tp"))
    sector = (b.get("sector") or "").strip()
    why = " · ".join(x for x in (_h(sector[:30]) if sector else "", f"score {b.get('score')}/90") if x)
    if not reason:
        return [f"{line} · score {b.get('score')}/90"]
    return [line, f"   {why}"]


def _format_verdict_alert(verdict: str, b: dict, fv, regime: str, gen_at) -> list:
    lines = _verdict_pick_lines(verdict, b)
    if regime:
        lines.append(_h(regime))
    lines.append(_FOOTER)
    return lines


def check_verdict_alerts(state: dict, today: str) -> int:
    """Telegram/Gmail when a stock in the latest Top Picks scan carries a BUY or
    STRONG BUY verdict — the same verdict the dashboard pick cards show
    (dashboard.shared.pick_freshness.compose_finalverdict_for_card, composite
    score + action + horizon). Once per stock per verdict tier per day; an
    upgrade BUY → STRONG BUY fires again. Descriptive, not advice."""
    try:
        import trade_store as store
        from dashboard.shared.pick_freshness import compose_finalverdict_for_card
        from utils.snapshot_time import snapshot_age_seconds
    except Exception as e:
        print(f"[verdicts] import failed: {e}")
        return 0
    try:
        snap = store.kv_get("top_picks_snapshot", user_id="_system")
    except Exception as e:
        print(f"[verdicts] kv_get failed: {e}")
        return 0
    if not (snap and isinstance(snap, dict) and isinstance(snap.get("data"), dict)):
        print("[verdicts] no top-picks snapshot")
        return 0
    gen_at = snap.get("generated_at", "unknown")
    _age = snapshot_age_seconds(gen_at)
    if _age is None or _age / 3600 > _VERDICT_MAX_SNAPSHOT_AGE_H:
        print(f"[verdicts] snapshot is stale (generated_at={gen_at}) — skipping")
        return 0

    # The shortlist holds only the top 20 by score; the full scored map
    # (same scan, same generated_at) also carries BUY / STRONG BUY names
    # further down. Read it too so those reach Telegram.
    candidates = list(snap["data"].get("buys") or [])
    seen = {_base_symbol(b.get("ticker")) for b in candidates}
    try:
        full = store.kv_get("all_scored_snapshot", user_id="_system")
    except Exception as e:
        print(f"[verdicts] all-scored kv_get failed: {e}")
        full = None
    if (full and isinstance(full, dict) and isinstance(full.get("data"), dict)
            and full.get("generated_at") == gen_at):
        for s in full["data"].values():
            if not isinstance(s, dict):
                continue
            if str(s.get("action", "")).upper().replace("_", " ") not in _VERDICT_ALERT_TIERS:
                continue
            base = _base_symbol(s.get("ticker"))
            if base and base not in seen:
                seen.add(base)
                candidates.append(s)

    hits = []
    for b in candidates:
        try:
            fv = compose_finalverdict_for_card(b, tqs=None, log_source=None)
        except Exception as e:
            print(f"[verdicts] {b.get('ticker')}: verdict failed: {e}")
            continue
        verdict = str(getattr(fv, "verdict", "") or "").upper()
        if verdict in _VERDICT_ALERT_TIERS:
            hits.append((verdict, b, fv))
    print(f"[verdicts] {len(hits)} BUY/STRONG BUY in scan at {_snapshot_ist_label(gen_at)}")

    regime = _regime_note()
    sent_today = sum(1 for k, v in state.items() if k.startswith("verdict_") and v == today)
    room = min(_VERDICT_MAX_PER_RUN, max(0, _VERDICT_MAX_PER_DAY - sent_today))
    batch = []
    for verdict, b, fv in sorted(hits, key=lambda h: (h[0] != "STRONG BUY", -float(h[1].get("score") or 0))):
        key = f"verdict_{verdict.replace(' ', '_').lower()}_{_base_symbol(b.get('ticker'))}"
        if _already_fired(state, key, today):
            continue
        if len(batch) >= room:
            print(f"[verdicts] cap reached ({_VERDICT_MAX_PER_RUN}/run, {_VERDICT_MAX_PER_DAY}/day, "
                  f"{sent_today} already today); the rest are on Top Picks")
            break
        batch.append((key, verdict, b, fv))
    if not batch:
        return 0
    # One Telegram message per run, not one per stock (9 Nov: ~40 separate pings).
    lines = _format_verdict_batch(batch, regime, gen_at)
    if dispatch("\n".join(lines), subject=f"{len(batch)} new BUY call(s) — NSE Smart Investor"):
        for key, *_ in batch:
            _mark_fired(state, key, today)
        return len(batch)
    return 0


def _format_verdict_batch(batch: list, regime: str, gen_at) -> list:
    """One message for a run's new BUY / STRONG BUY calls, strongest first.
    A reason line per stock only while the message stays within 15 lines."""
    n = len(batch)
    lines = [f"🟢 <b>{n} new BUY call{'s' if n != 1 else ''}</b> · {_snapshot_ist_label(gen_at).replace(' IST', '')}"]
    if regime:
        lines.append(_h(regime))
    for _key, verdict, b, _fv in batch:
        lines += _verdict_pick_lines(verdict, b, reason=n <= 5)
    lines.append(_FOOTER)
    return lines


def check_picks_recap(state: dict, today: str, now: datetime.datetime | None = None) -> int:
    key = "picks_recap"
    if _already_fired(state, key, today):
        return 0
    now = (now or datetime.datetime.now(_IST)).astimezone(_IST)
    if now.time() < _RECAP_FROM:
        return 0
    try:
        import trade_store as store
    except Exception as e:
        print(f"[recap] import failed: {e}")
        return 0
    morning = _today_picks(store, today)
    if not morning:
        print("[recap] no Morning Digest picks for today — nothing to recap")
        return 0

    rows, moves = [], []
    for b in morning["buys"]:
        base = _base_symbol(b.get("ticker"))
        try:
            ref = float(b.get("price") or b.get("last_price") or 0)
        except (TypeError, ValueError):
            ref = 0.0
        q = _quote(base)
        if not q:
            rows.append(f"<b>{_h(base)}</b> — no live price")
            continue
        price = float(q["price"])
        day = q.get("chg_pct", 0.0) or 0.0
        if ref > 0:
            since = (price / ref - 1) * 100
            moves.append(since)
            rows.append(f"<b>{_h(base)}</b> ₹{ref:,.2f} → <b>₹{price:,.2f}</b> "
                        f"({since:+.1f}% since the scan · {day:+.2f}% today)")
        else:
            rows.append(f"<b>{_h(base)}</b> now <b>₹{price:,.2f}</b> ({day:+.2f}% today)")
        extra = []
        ss = _pick_session(base, today)
        if ss:
            extra.append(f"day range ₹{ss['low']:,.2f}–₹{ss['high']:,.2f}")
        extra += [f"{d} {_MOVE_PCT:g}%+ at one point"
                  for d in ("up", "down") if state.get(f"mv_{d}_{base}") == today]
        if extra:
            rows.append("   " + " · ".join(extra))

    lines = [f"📊 <b>Digest picks today</b> · {now:%H:%M} "
             f"(scan at {_snapshot_ist_label(morning.get('generated_at'))})"]
    lines += rows
    if moves:
        up = sum(m > 0 for m in moves)
        avg_move = round(sum(moves) / len(moves), 1) + 0.0     # + 0.0 turns -0.0 into 0.0
        lines += [f"Average {avg_move:+.1f}% · {up} up / {len(moves) - up} down or flat"]
    if dispatch("\n".join(lines), subject="Digest picks recap — NSE Smart Investor"):
        _mark_fired(state, key, today)
        return 1
    return 0


def check_vix_regime(state: dict, today: str) -> int:
    """Alert when India VIX is in a fear/panic regime."""
    try:
        from utils.vix import get_india_vix_regime
        info = get_india_vix_regime()
    except Exception as e:
        print(f"[vix] failed: {e}")
        return 0

    regime = str(info.get("regime", "unknown")).lower()
    vix    = info.get("vix")
    if regime == "unknown":
        # Fail-closed VIX (utils.vix): an outage is reported once a day,
        # not read as a calm market.
        key = "vix_unavailable"
        if _already_fired(state, key, today):
            return 0
        msg = (f"⚪ <b>India VIX unavailable</b> · {_now_hm()}\n"
               f"{_h(info.get('reason') or 'No reading from NSE / Yahoo')} — VIX filter treated as closed.")
        if dispatch(msg):
            _mark_fired(state, key, today)
            return 1
        return 0
    if regime not in ("fear", "panic"):
        return 0

    key = f"vix_{regime}"
    if _already_fired(state, key, today):
        return 0

    icon = "🚨" if regime == "panic" else "🔴"
    msg = (
        f"{icon} <b>India VIX {regime.upper()}" + (f" · {vix:.1f}" if vix else "") + f"</b> · {_now_hm()}\n"
        "Wider daily swings than usual, both ways.\n"
        "Market: high volatility — smaller size"
    )
    if dispatch(msg):
        _mark_fired(state, key, today)
        return 1
    return 0


def check_nifty_trend(state: dict, today: str) -> int:
    """Alert when Nifty 50 is in a confirmed downtrend (price < SMA20 < SMA50)."""
    try:
        from data.fetcher import fetch_single
        df = fetch_single("^NSEI", period="3mo")
    except Exception as e:
        print(f"[nifty] fetch failed: {e}")
        return 0
    if df is None or df.empty or len(df) < 50:
        return 0

    close = df["Close"]
    price = float(close.iloc[-1])
    sma20 = float(close.rolling(20).mean().iloc[-1])
    sma50 = float(close.rolling(50).mean().iloc[-1])
    if not (price < sma20 < sma50):
        return 0

    key = "nifty_downtrend"
    if _already_fired(state, key, today):
        return 0

    chg5 = (price / float(close.iloc[-6]) - 1) * 100 if len(close) >= 6 else 0.0
    msg = (
        f"📉 <b>Nifty 50 downtrend</b> · {_now_hm()}\n"
        f"Nifty {price:,.0f} ({chg5:+.1f}% 5d), below SMA20 ({sma20:,.0f}) and SMA50 ({sma50:,.0f}).\n"
        f"{_MARKET_DOWN}"
    )
    if dispatch(msg):
        _mark_fired(state, key, today)
        return 1
    return 0


# ─────────────────────────────────────────────────────────────────────────────
# Delivery digest — top positional picks from the pre-warmed snapshot
#
# Reads the ~745-ticker top-picks scan that scripts/warm_top_picks.py already
# writes every 15 min to trade_store KV, so this check does NOT rescan the
# universe. It only formats and sends. Fires ONCE per day, so the state key
# is date-only. Primary sender: warm-preopen-scan.yml, right after it writes
# a fresh snapshot. The 09:00 IST market-digest cron is a fallback only.
# ─────────────────────────────────────────────────────────────────────────────

_DIGEST_MAX_SNAPSHOT_AGE_H = 16

# The names the Morning Digest actually sent, so the 09:20 intraday watchlist
# reframes the same list instead of whatever the 15-min warmer wrote since.
_MORNING_PICKS_KEY = "morning_digest_picks"


def _snapshot_ist_label(gen_at, *, with_date: bool = False) -> str:
    """generated_at (UTC ISO) → 'HH:MM IST'; the raw stamp is UTC, not IST.
    with_date adds ', Thu 1 Oct' so a scan saved before a holiday or weekend
    isn't read as today's (the "this morning's …" follow-ups don't need it)."""
    from utils.snapshot_time import parse_snapshot_timestamp
    ts = parse_snapshot_timestamp(gen_at)
    if not ts:
        return "unknown time"
    ist = ts.astimezone(_IST)
    label = ist.strftime("%H:%M IST")
    # day without a leading zero; %-d is not portable to Windows
    return f"{label}, {ist:%a} {ist.day} {ist:%b}" if with_date else label


# Bullish names under this composite score are labelled "Watch only" in the
# digest: in the shadow ledger they beat Nifty over 5 days less often than
# not, while 70+ did better (see the Tomorrow's Watchlist scorecard, #253).
# Labelled, not hidden: in a bear regime scores cluster mid-range by design
# (#168/#198), so hiding would empty the digest and every follow-up alert
# that reuses its names (opening update, pick moves, recap, 09:20 watchlist).
_WATCH_FLOOR = 70.0
_BEARISH_ACTIONS = frozenset({"EXIT", "CAUTION", "AVOID", "SELL", "STRONG SELL"})


def _under_floor_record() -> "dict | None":
    """Settled 5-day record of bullish Top Picks names scoring under
    _WATCH_FLOOR (shadow ledger), as analysis.tw_scorecard.settle_stats; None
    when the ledger is unreachable or holds fewer than 20 settled names."""
    try:
        import pandas as pd
        from analysis.tw_scorecard import settle_stats
        from analysis.verdict_ledger import load_ledger
        df = load_ledger(source="shadow_auto", limit=5000)
        if df is None or df.empty or "ret_5d" not in df.columns:
            return None
        df = df.drop_duplicates(["logged_date", "ticker"])
        sc = pd.to_numeric(df["composite_score"], errors="coerce")
        bear = df["composite_action"].astype(str).str.strip().str.upper().isin(_BEARISH_ACTIONS)
        sub = df[(sc < _WATCH_FLOOR) & ~bear]
        s = settle_stats(list(zip([1] * len(sub), sub["ret_5d"], sub["nifty_ret_5d"])))
        return s if s["n"] >= 20 and s["beat_rate"] is not None else None
    except Exception as _e:
        _log.debug("under-floor record unavailable: %s", _e)
        return None


def _digest_lines(buys: list, gen_at, max_picks: int, header: "str | None" = None) -> list:
    """Message lines for the Morning Delivery Digest (shared by the real
    digest and --mode=test-digest). One line per pick, action word first;
    names under _WATCH_FLOOR read WATCH, not BUY."""
    lines = [(header or "📈 <b>Morning Delivery Digest</b>")
             + f" · scan at {_snapshot_ist_label(gen_at, with_date=True)}"]

    def _under(b) -> bool:
        try:
            return float(b.get("score") or 0) < _WATCH_FLOOR
        except (TypeError, ValueError):
            return True

    shown = buys[:max_picks]
    n_under = sum(1 for b in shown if _under(b))
    if n_under:
        rec = _under_floor_record()
        note = (f"⚠️ None scored {_WATCH_FLOOR:.0f}+ today — all WATCH, not BUY"
                if n_under == len(shown) else
                f"⚠️ {n_under} of {len(shown)} scored under {_WATCH_FLOOR:.0f} — WATCH, not BUY")
        if rec:
            note += (f" (under-{_WATCH_FLOOR:.0f} names beat Nifty {rec['beat_rate']:.0f}% of 5-day "
                     f"windows, n={rec['n']})")
        lines.append(note)
    for b in shown:
        price = b.get("price") or b.get("last_price") or b.get("current_price")
        price = price if isinstance(price, (int, float)) else None
        stop  = b.get("stop_loss") or b.get("stop") or b.get("sl")
        tgt   = b.get("target") or b.get("tp")
        sec   = _h(str(b.get("sector", "") or "").strip()[:30])
        tk    = _base_symbol(b.get("ticker", "?"))
        if _under(b):
            levels = " / ".join(_rs(x) for x in (stop, tgt) if x)
            lines.append(_stock_line("WATCH", tk, price, extra=f"levels {levels}" if levels else ""))
        else:
            v = _verdict_of(b)
            word = (verdict_display_label(v[0]) if v
                    else action_display_label(str(b.get("action", "")).replace("_", " ")))
            lines.append(_stock_line(word, tk, price, stop, tgt))
        lines.append("   " + " · ".join(x for x in (sec, f"score {b.get('score', 0)}/90") if x))

    # BUY / STRONG BUY verdicts further down the scan than the top max_picks
    extra = []
    for b in buys[max_picks:]:
        v = _verdict_of(b)
        if v and v[0] in _VERDICT_ALERT_TIERS and not _under(b):
            extra.append((v, b))
    if extra:
        extra.sort(key=lambda e: (e[0][0] != "STRONG BUY", -float(e[1].get("score") or 0)))
        names, used = [], 0
        for (verdict, _conv), b in extra:
            item = f"<b>{_h(_base_symbol(b.get('ticker', '?')))}</b>" + (" ★" if verdict == "STRONG BUY" else "")
            if used + len(_plain(item)) > 70:
                names.append(f"+{len(extra) - len(names)} more")
                break
            names.append(item)
            used += len(_plain(item)) + 3
        lines.append("Also BUY further down (★ strong): " + " · ".join(names))
    lines.append(_FOOTER)
    return lines


def check_delivery_digest(state: dict, today: str, *, max_picks: int = 5) -> int:
    """Read persisted Top Picks snapshot and email/Telegram the top delivery
    candidates for the day. One fire per day (state-deduplicated)."""
    key = "delivery_digest"
    if _already_fired(state, key, today):
        return 0

    try:
        import trade_store as store
    except Exception as _e:
        print(f"[digest] trade_store import failed: {_e}")
        return 0

    try:
        snap = store.kv_get("top_picks_snapshot", user_id="_system")
    except Exception as _e:
        print(f"[digest] kv_get failed: {_e}")
        return 0

    if not (snap and isinstance(snap, dict) and isinstance(snap.get("data"), dict)):
        print("[digest] no persisted top-picks snapshot yet — skipping")
        return 0

    gen_at = snap.get("generated_at", "unknown")
    # Don't present an old scan as "today's". snapshot_age_seconds() is
    # timezone-safe (warmer stamps aware UTC; legacy naive stamps read as UTC).
    # 16h still accepts last evening's post-close scan (same closing prices a
    # pre-open scan would see) but rejects Friday's snapshot on Monday. Not
    # marked fired, so a later run with a fresh snapshot can still send.
    from utils.snapshot_time import snapshot_age_seconds
    _age_s = snapshot_age_seconds(gen_at)
    _age_h = None if _age_s is None else _age_s / 3600
    if _age_h is None or _age_h > _DIGEST_MAX_SNAPSHOT_AGE_H:
        print(f"[digest] snapshot is stale (generated_at={gen_at}) — skipping")
        return 0

    buys = snap["data"].get("buys") or []
    if not buys:
        print("[digest] snapshot has 0 buys — nothing to send")
        return 0

    msg = "\n".join(_digest_lines(buys, gen_at, max_picks))

    if dispatch(msg, subject="Morning Delivery Digest — NSE Smart Investor"):
        _mark_fired(state, key, today)
        try:
            store.kv_set(_MORNING_PICKS_KEY,
                         {"date": today, "generated_at": gen_at, "buys": buys[:max_picks]},
                         user_id="_system")
        except Exception as _e:
            print(f"[digest] could not save today's picks for the intraday watchlist: {_e}")
        return 1
    return 0


# ─────────────────────────────────────────────────────────────────────────────
# Momentum opportunities — pure scanner + fetcher, fires every 30 min
# ─────────────────────────────────────────────────────────────────────────────

def check_momentum_opportunities(state: dict, today: str, *, top_n: int = 8) -> int:
    """Run the Donchian-55 momentum scan over the niftytotalmarket universe
    and send a digest. Deduped by (today + hour bucket) so we get at most 2
    fires per day from the every-30-min workflow trigger — one mid-morning
    push and one afternoon push, not the same list every 30 min.

    The 30-min cadence is intentional: momentum breakouts hold for hours,
    not minutes, and a 15-min ping would spam identical lists.
    """
    now_ist = datetime.datetime.now(_IST)
    # Bucket: "am" (before 12:30) vs "pm" — one digest per bucket per day
    bucket = "am" if now_ist.hour < 12 or (now_ist.hour == 12 and now_ist.minute < 30) else "pm"
    key = f"momentum_{bucket}"
    if _already_fired(state, key, today):
        return 0

    try:
        from analysis.momentum_scanner import (
            scan_momentum, format_momentum_message, MomentumConfig,
        )
        from data.fetcher import fetch_single
        from data.universe import get_universe
    except Exception as _e:
        print(f"[momentum] import failed: {_e}")
        return 0

    try:
        universe = get_universe("niftytotalmarket")
    except Exception as _e:
        print(f"[momentum] universe load failed: {_e}")
        return 0

    def _fetch(ticker: str):
        try:
            df = fetch_single(ticker, period="2y")
            return df
        except Exception as _fe:
            _log.debug("momentum fetch failed for %s: %s", ticker, _fe)
            return None

    try:
        nifty_df = fetch_single("^NSEI", period="2y")
    except Exception as _e:
        print(f"[momentum] nifty fetch failed (RS will fall back to absolute): {_e}")
        nifty_df = None

    cfg = MomentumConfig(top_n=top_n)
    print(f"[momentum] scanning {len(universe)} tickers ({bucket} bucket)...")
    candidates = scan_momentum(universe, _fetch, nifty_history=nifty_df, cfg=cfg)

    msg = format_momentum_message(candidates)
    subject = (
        f"Momentum Scan — {len(candidates)} setup(s) surfaced"
        if candidates else "Momentum Scan — quiet day"
    )
    if dispatch(msg, subject=subject):
        _mark_fired(state, key, today)
        return 1
    return 0


# ─────────────────────────────────────────────────────────────────────────────
# Diagnostic mode — proves end-to-end delivery
#
# check_test_alert unconditionally sends a "hello" message through EVERY
# configured channel, with per-channel success reporting printed to the
# workflow log. Use this to debug "I ran the workflow but nothing arrived":
# it will tell you exactly which channel is broken (or that both worked
# and the mail landed in Promotions / All Mail / a filter).
# ─────────────────────────────────────────────────────────────────────────────

def check_test_verdict_alert(state: dict, today: str) -> int:
    """Send ONE sample verdict alert, formatted by the real formatter, for a
    made-up ticker and clearly marked TEST. No dedup, no market data read."""
    class _FV:
        conviction = 88
    sample = {"ticker": "SAMPLE.NS", "score": 70.0, "price": 1234.50, "sl": 1180.00,
              "tp": 1340.00, "sector": "Pharma", "horizon": "Positional (2–4 weeks)"}
    now_utc = datetime.datetime.now(datetime.timezone.utc).isoformat()
    lines = [f"🧪 <b>TEST — sample STRONG BUY alert (not a real stock)</b> · {_now_hm()}"]
    lines += _format_verdict_alert("STRONG BUY", sample, _FV(), _MARKET_DOWN, now_utc)
    return 1 if dispatch("\n".join(lines), subject="NSE Smart Investor — sample BUY alert") else 0


def check_test_digest(state: dict, today: str, *, max_picks: int = 5) -> int:
    """Send the Morning Digest built from the latest saved scan, even if stale,
    under a TEST header. No dedup, no staleness gate, and it does NOT save
    today's picks, so the real digest and intraday checks are unaffected."""
    try:
        import trade_store as store
        snap = store.kv_get("top_picks_snapshot", user_id="_system")
    except Exception as _e:
        print(f"[test-digest] snapshot read failed: {_e}")
        return 0
    if not (snap and isinstance(snap, dict) and isinstance(snap.get("data"), dict)):
        print("[test-digest] no persisted top-picks snapshot")
        return 0
    gen_at = snap.get("generated_at", "unknown")
    buys = snap["data"].get("buys") or []
    if not buys:
        print("[test-digest] snapshot has 0 picks")
        return 0
    header = "🧪 <b>TEST — Morning Digest (last saved scan, may be stale)</b>"
    msg = "\n".join(_digest_lines(buys, gen_at, max_picks, header=header))
    return 1 if dispatch(msg, subject="NSE Smart Investor — TEST morning digest") else 0


def check_test_alert(state: dict, today: str) -> int:
    """Fire a one-shot diagnostic message via Telegram AND Gmail with per-
    channel success reporting. No dedup — every invocation attempts a send
    so you can retry until it works. Returns 1 if any channel succeeded.
    """
    now_ist = datetime.datetime.now(_IST).strftime("%Y-%m-%d %H:%M:%S")
    body_html = (
        f"🧪 <b>NSE Smart Investor — Test Alert</b> · {now_ist[11:16]}\n"
        "The send path works. Real alerts arrive on this same channel.\n"
        "No market data attached."
    )
    subject = f"NSE Smart Investor test alert — {now_ist} IST"

    # Report per-channel status BEFORE dispatch so the log tells the whole story
    _tg_env    = bool(os.environ.get("TELEGRAM_BOT_TOKEN") and os.environ.get("TELEGRAM_CHAT_ID"))
    _gmail_env = bool(
        os.environ.get("ALERT_GMAIL_ADDRESS")
        and os.environ.get("ALERT_GMAIL_APP_PASSWORD")
        and os.environ.get("ALERT_GMAIL_TO")
    )
    print(f"[test] TELEGRAM secrets present: {_tg_env}")
    print(f"[test]    ALERT_GMAIL_ADDRESS      set: {bool(os.environ.get('ALERT_GMAIL_ADDRESS'))}")
    print(f"[test]    ALERT_GMAIL_APP_PASSWORD set: {bool(os.environ.get('ALERT_GMAIL_APP_PASSWORD'))}")
    print(f"[test]    ALERT_GMAIL_TO           set: {bool(os.environ.get('ALERT_GMAIL_TO'))}")
    print(f"[test]    TELEGRAM_BOT_TOKEN       set: {bool(os.environ.get('TELEGRAM_BOT_TOKEN'))}")
    print(f"[test]    TELEGRAM_CHAT_ID         set: {bool(os.environ.get('TELEGRAM_CHAT_ID'))}")

    _tg_ok    = send_telegram(body_html)
    _gmail_ok = send_gmail(subject, body_html)

    print(f"[test] Telegram send returned: {_tg_ok}")
    print(f"[test] Gmail    send returned: {_gmail_ok}")

    if _tg_ok or _gmail_ok:
        print("[test] SUCCESS — at least one channel accepted the message. "
              "If you don't see it in Telegram/Gmail, check: (1) Gmail Spam / "
              "Promotions / All Mail folders, (2) that you sent your bot the "
              "initial 'hi' message so it can DM you, (3) the recipient "
              "address in ALERT_GMAIL_TO.")
        return 1

    print("[test] FAILURE — no channel accepted the message. "
          "Check the *_ok logs above: if send_telegram printed 'FAILED' the "
          "bot token or chat id is wrong; if send_gmail's GmailAlerter said "
          "console-fallback, one or more ALERT_GMAIL_* secrets are missing "
          "or misspelled.")
    return 0


# ─────────────────────────────────────────────────────────────────────────────
# Portfolio posture — analyse Angel One holdings + intraday positions
#
# Fires once per day (typically 14:00 IST via the market-digest workflow's
# 3rd cron) and sends a message listing only the holdings that need
# attention: EXIT_WATCH, TRIM_WATCH, ADD_WATCH, plus intraday STOP_HIT /
# TARGET_HIT / TRAIL_TIGHTER. If everything is HOLD/RUNNING, no message
# (only_actionable=True by default in format_portfolio_message).
# ─────────────────────────────────────────────────────────────────────────────

def _manual_holdings_for_posture() -> list:
    """My Portfolio holdings (KV manual_portfolio_holdings) in the shape
    analysis.portfolio_posture expects: symbol / qty / avg_price."""
    try:
        import trade_store as store
        rows = store.kv_get(_PF_HOLDINGS_KEY, None) or []
    except Exception as e:
        print(f"[portfolio] My Portfolio read failed: {e}")
        return []
    out = []
    for h in rows if isinstance(rows, list) else []:
        sym = str(h.get("ticker", "")).upper().replace(".NS", "").replace(".BO", "").strip()
        try:
            qty = int(float(h.get("quantity") or h.get("qty") or 0))
            avg = float(h.get("avg_buy_price") or h.get("avg_price") or 0)
        except (TypeError, ValueError):
            continue
        if sym and qty > 0:
            out.append({"symbol": sym, "qty": qty, "avg_price": avg})
    return out


def _short_skip_reason(reason: str) -> str:
    r = str(reason)
    if "could not be fetched" in r:
        return "price history unavailable"
    if "trading days" in r:
        return "too little history"
    return r[:40]


def _not_analysed_line(skipped: list) -> str:
    """'Not analysed: VEDL, PFC (price history unavailable)' — one line, grouped by reason."""
    groups: dict = {}
    for sk in skipped:
        groups.setdefault(_short_skip_reason(sk.get("reason", "")), []).append(_h(sk.get("symbol", "?")))
    return "Not analysed: " + " · ".join(f"{', '.join(v)} ({k})" for k, v in groups.items())


def check_portfolio_posture(state: dict, today: str, *, test: bool = False,
                            always: bool = False) -> int:
    """Fetch Angel One holdings + positions, run posture analysis, alert only
    on actionable rows. Requires ANGEL_* env vars — silently no-ops otherwise
    (Angel One is optional; we can't analyse a portfolio we can't see).

    test=True (--mode=test-posture): every row incl. HOLD, under a TEST
    header, no dedup read or write."""
    key = "portfolio_posture"
    if not test and _already_fired(state, key, today):
        return 0

    try:
        from analysis.portfolio_posture import (
            NO_FLAGGED_POSTURES, analyse_holdings, analyse_positions,
            format_portfolio_message,
        )
        from data.angel_fetcher import get_holdings, get_positions
        from data.fetcher import fetch_single
    except Exception as _e:
        print(f"[portfolio] import failed: {_e}")
        return 0

    # Holdings come from the My Portfolio page (owner's choice, 9 Nov); Angel
    # One is only the fallback when that list is empty. Intraday positions
    # exist only at the broker, so they still come from Angel when configured.
    holdings = _manual_holdings_for_posture()
    if holdings:
        print(f"[portfolio] using {len(holdings)} My Portfolio holding(s)")
    else:
        try:
            holdings = get_holdings() or []
        except Exception as _e:
            print(f"[portfolio] get_holdings failed (Angel One session issue?): {_e}")
            holdings = []
    try:
        positions = (get_positions() or {}).get("day", []) or []
    except Exception as _e:
        print(f"[portfolio] get_positions failed: {_e}")
        positions = []

    if not holdings and not positions:
        print("[portfolio] no holdings / positions — nothing to analyse")
        return 0

    def _fetch(sym):
        # Holdings carry bare NSE symbols (RELIANCE); the price tiers want RELIANCE.NS.
        s = str(sym).upper()
        if not s.endswith((".NS", ".BO")) and not s.startswith("^"):
            s += ".NS"
        try:
            return fetch_single(s, period="2y")
        except Exception:
            return None

    try:
        nifty_df = fetch_single("^NSEI", period="2y")
    except Exception:
        nifty_df = None

    print(f"[portfolio] analysing {len(holdings)} holdings + {len(positions)} intraday positions")
    skipped: list = []
    hpost = analyse_holdings(holdings, _fetch, nifty_history=nifty_df, skipped=skipped)
    ipost = analyse_positions(positions, _fetch)
    for sk in skipped:
        print(f"[portfolio] could not analyse {sk['symbol']}: {sk['reason']}")

    msg = format_portfolio_message(hpost, ipost, only_actionable=not test)
    # FIX POSTURE-SKIP (2026-10-03): holdings that produced no posture used to
    # vanish, so "couldn't analyse anything" read as "all HOLD". Say so instead.
    if skipped:
        skip_block = "\n" + _not_analysed_line(skipped)
        if NO_FLAGGED_POSTURES in msg and not hpost and not ipost:
            msg = (f"📋 <b>Portfolio Posture</b> · {_now_hm()}\n"
                   "No holding could be analysed." + skip_block)
        else:
            msg += skip_block
    if test:
        msg = "🧪 <b>TEST — Portfolio Posture (all rows, incl. HOLD)</b>\n" + msg
        return 1 if dispatch(msg, subject="NSE Smart Investor — TEST portfolio posture") else 0
    # Suppress the 'nothing to do' message from the daily digest — the whole
    # point of an alert is to surface something. If everything is HOLD,
    # count it as fired-successfully (dedup key set) so we don't keep polling.
    if NO_FLAGGED_POSTURES in msg and not skipped:
        if always:
            # After-close run (--always): the owner wants a daily portfolio
            # line even when nothing needs attention.
            steady = (f"📋 <b>Portfolio after the close</b> · {_now_hm()}\n"
                      f"HOLD all {len(hpost)} holding(s) — nothing needs attention today.")
            if dispatch(steady, subject="Portfolio after the close — all steady"):
                _mark_fired(state, key, today)
                return 1
            return 0
        _mark_fired(state, key, today)
        print("[portfolio] all HOLD/RUNNING — no message sent")
        return 0
    if not hpost and not ipost and skipped:
        # Nothing analysable: report it once a day rather than staying silent.
        if dispatch(msg, subject="Portfolio Posture — holdings could not be analysed"):
            _mark_fired(state, key, today)
            return 1
        return 0

    if dispatch(msg, subject=f"Portfolio Posture — {len(hpost)+len(ipost)} row(s) need attention"):
        _mark_fired(state, key, today)
        return 1
    return 0


# ─────────────────────────────────────────────────────────────────────────────
# Intraday morning watchlist — 09:20 IST
#
# The Morning Digest names with reference levels in plain words (no ORB /
# ATR / stop / target jargon — the user asked for clearer intraday language,
# 2026-10-02): yesterday's close ± half a typical day's move (ATR-14), and a
# next level 1.5 typical moves above the upside one. The levels are saved
# (KV intraday_levels) for the opening update and the ±2% move alerts.
# ─────────────────────────────────────────────────────────────────────────────

def check_intraday_watchlist(state: dict, today: str, *, max_picks: int = 5) -> int:
    """Reference levels for today's picks, in plain language. Once per day."""
    key = "intraday_watchlist"
    if _already_fired(state, key, today):
        return 0

    try:
        import trade_store as store
        from analysis.intraday_levels import daily_levels
        from data.fetcher import fetch_single
    except Exception as _e:
        print(f"[intraday] import failed: {_e}")
        return 0

    # Prefer the exact list this morning's digest sent; fall back to the
    # latest snapshot (and say so) if the digest didn't go out today.
    morning = _today_picks(store, today)
    if morning:
        buys = morning["buys"]
        source = (f"this morning's Delivery Digest "
                  f"(scan at {_snapshot_ist_label(morning.get('generated_at'))})")
    else:
        try:
            snap = store.kv_get("top_picks_snapshot", user_id="_system")
        except Exception as _e:
            print(f"[intraday] kv_get failed: {_e}")
            return 0

        if not (snap and isinstance(snap, dict) and isinstance(snap.get("data"), dict)):
            print("[intraday] no persisted top-picks snapshot — skipping")
            return 0

        buys = snap["data"].get("buys") or []
        source = f"the latest delivery scan (at {_snapshot_ist_label(snap.get('generated_at'))})"
    if not buys:
        print("[intraday] snapshot has 0 buys — nothing to reformat")
        return 0

    lines = [f"⚡ <b>Intraday Watchlist</b> · {_now_hm()}", f"From {source}"]
    saved: dict[str, dict] = {}
    for b in buys[:max_picks]:
        tk = b.get("ticker", "?")
        base = _base_symbol(tk)
        try:
            df = fetch_single(tk, period="3mo")
        except Exception as _fe:
            _log.debug("intraday fetch failed for %s: %s", tk, _fe)
            df = None
        lv = daily_levels(df)
        if lv is None:
            # Skip the levels for this row but still surface the name
            lines.append(f"<b>{_h(base)}</b> — not enough price history for levels")
            continue
        saved[base] = lv
        pct = lv["atr"] / lv["y_close"] * 100
        lines.append(f"<b>{_h(base)}</b> closed ₹{lv['y_close']:,.2f} yesterday · "
                     f"typical day's move ₹{lv['atr']:,.2f} ({pct:.1f}%)")
        lines.append(f"   ▲ Upside level ₹{lv['up']:,.2f} · next level above it ₹{lv['next_up']:,.2f}"
                     f" · ▼ Downside level ₹{lv['down']:,.2f}")

    lines.append("<i>Above ▲ = past its normal range up; below ▼ = past it down.</i>")

    if not saved:
        print("[intraday] no rows could be enriched — skipping send")
        return 0

    msg = "\n".join(lines)
    if dispatch(msg, subject="Intraday Watchlist — NSE Smart Investor"):
        _mark_fired(state, key, today)
        try:
            store.kv_set(_LEVELS_KEY, {"date": today, "levels": saved}, user_id="_system")
        except Exception as _e:
            print(f"[intraday] could not save today's levels: {_e}")
        return 1
    return 0


# ─────────────────────────────────────────────────────────────────────────────
# Sunday weekly digest — 09:00 IST Sunday
#
# Zooms out from the daily fires: current top-picks list, journal entries
# added this week, and any reviews due next week. Meant for the "how did
# my thesis basket evolve" question rather than "what's fresh today".
# ─────────────────────────────────────────────────────────────────────────────

def check_tomorrow_watchlist(state: dict, today: str, *, top_n: int = 5) -> int:
    """After-close message from the Tomorrow's Watchlist snapshot the 15:50
    warm-up just wrote: top breakout and reversal names for the next session.
    Once per day. Descriptive, not advice."""
    key = "tomorrow_watchlist"
    if _already_fired(state, key, today):
        return 0
    try:
        import trade_store as store
        from utils.snapshot_time import snapshot_age_seconds
        snap = store.kv_get("tomorrow_watchlist_snapshot", user_id="_system")
    except Exception as e:
        print(f"[tomorrow] snapshot read failed: {e}")
        return 0
    if not (snap and isinstance(snap, dict) and isinstance(snap.get("data"), dict)):
        print("[tomorrow] no Tomorrow's Watchlist snapshot")
        return 0
    gen_at = snap.get("generated_at", "unknown")
    _age = snapshot_age_seconds(gen_at)
    if _age is None or _age / 3600 > _TOMORROW_MAX_SNAPSHOT_AGE_H:
        print(f"[tomorrow] snapshot is stale (generated_at={gen_at}) — skipping")
        return 0
    lines = tomorrow_watchlist_lines(snap["data"], gen_at, top_n=top_n)
    if not lines:
        print("[tomorrow] breakout and reversal lists are empty — nothing to send")
        return 0
    if dispatch("\n".join(lines), subject="Tomorrow's Watchlist — NSE Smart Investor"):
        _mark_fired(state, key, today)
        return 1
    return 0


def _tomorrow_row(p: dict, word: str) -> str:
    """'BUY  <b>B1</b>  above ₹100.00 · stop ₹94.00 · score 70/90'."""
    sym = _base_symbol(p.get("ticker"))
    ref = p.get("entry")
    if word == "BUY":
        lead = f"above {_rs(ref)}" if ref else ""
    elif word == "SELL":
        lead = f"below {_rs(ref)}" if ref else ""
    else:
        lead = "— bounce setup"
    tail = [x for x in (f"stop {_rs(p['sl'])}" if p.get("sl") else "", f"score {p.get('score')}/90") if x]
    return f"{word}  <b>{_h(sym)}</b>  " + " · ".join([lead] + tail if lead else tail)


def tomorrow_watchlist_lines(data: dict, gen_at, *, top_n: int = 5) -> list:
    """Message body for check_tomorrow_watchlist; [] when there is nothing to show.
    Breakout -> BUY above ref; bullish reversal -> WATCH (bounce setup)."""
    sections = [("🚀 <b>Breakouts</b>", "BUY", data.get("breakout_candidates") or []),
                ("🔄 <b>Reversals</b>", "WATCH", data.get("reversal_watch") or [])]
    if not any(items for _, _, items in sections):
        return []
    lines = [f"🌙 <b>Tomorrow's Watchlist</b> · scan at {_snapshot_ist_label(gen_at, with_date=True)}"]
    for title, word, items in sections:
        if not items:
            if word == "BUY" and data.get("bear_scoring_active"):
                rg = str(data.get("regime_label") or "bear").replace("_", " ")
                lines.append(f"{title}: none — held back in the {_h(rg)} market until the trend turns")
            continue
        lines.append(title)
        lines += [_tomorrow_row(p, word) for p in items[:top_n]]
    lines.append(_FOOTER)
    return lines


def check_weekly_scorecard(state: dict, today: str, now: datetime.datetime | None = None) -> int:
    """Friday after the close: how this week's Top Picks and Tomorrow's
    Watchlist names moved since they were logged, against the Nifty over the
    same span, one section per list (watchlist down-setups judged as
    down-calls). Once per ISO week. Descriptive only — a record of past calls,
    not advice."""
    now = (now or datetime.datetime.now(_IST)).astimezone(_IST)
    if now.weekday() != 4:
        print(f"[scorecard] not Friday (weekday={now.weekday()}) — skipping")
        return 0
    key = f"weekly_scorecard_{now:%G-W%V}"
    if _already_fired(state, key, today):
        return 0
    try:
        from analysis import verdict_ledger as vl
        from data.fetcher import fetch_single
        ledger = vl.load_ledger(limit=1_000_000)
    except Exception as e:
        print(f"[scorecard] ledger read failed: {e}")
        return 0
    if vl.ledger_error(ledger) or ledger.empty:
        print("[scorecard] ledger empty or unreadable — nothing to send")
        return 0
    monday = (now - datetime.timedelta(days=now.weekday())).date().isoformat()
    week = ledger[(ledger["logged_date"].astype(str) >= monday)
                  & (ledger["logged_date"].astype(str) <= today)
                  & ledger["source"].isin(("shadow_auto", "tomorrow_watchlist"))]
    if week.empty:
        print("[scorecard] no Top Picks or Tomorrow's Watchlist names logged this week")
        return 0
    week = vl.with_list_buckets(week)
    prices = {}
    for tk in week["ticker"].unique():
        q = _quote(_base_symbol(tk))
        if q and q.get("price"):
            prices[tk] = float(q["price"])
    nifty_close, nifty_now = None, None
    try:
        nifty = fetch_single("^NSEI", period="1mo")
        nifty_close = nifty["Close"]
        nifty_now = float(nifty_close.dropna().iloc[-1])
    except Exception as e:
        print(f"[scorecard] Nifty history unavailable: {e}")
    sector_of = None
    try:
        from data.universe import get_sector as sector_of
    except Exception as e:
        print(f"[scorecard] sector map unavailable: {e}")
    cards = vl.week_scorecard_by_list(week, prices, nifty_close, nifty_now, sector_of=sector_of)
    if not cards:
        print("[scorecard] no prices for this week's names — nothing to send")
        return 0
    lines = weekly_scorecard_lines(cards, monday, today)
    if dispatch("\n".join(lines), subject="Weekly report card — NSE Smart Investor"):
        _mark_fired(state, key, today)
        return 1
    return 0


def _names_line(rows: list) -> str:
    return " · ".join(f"{_h(_base_symbol(r['ticker']))} {r['move']:+.1f}%" for r in rows)


def _n_names(n: int) -> str:
    return f"{n} name{'' if n == 1 else 's'}"


def _sector_lines(sectors: list) -> list:
    """'By sector' rows for the report card: the sectors whose names ran furthest
    ahead of the Nifty and those furthest behind (week_scorecard `sectors`,
    already ordered best first). Empty when fewer than two sectors qualify."""
    if len(sectors) < 2:
        return []

    def _fmt(rows: list) -> str:
        return " · ".join(f"{_h(r['sector'])} {r['mean_edge']:+.1f} pts ({r['n']})" for r in rows)

    top = sectors[:3]
    bottom = [r for r in sectors[::-1][:3] if r not in top]
    out = [f"By sector, vs the Nifty (names): {_fmt(top)}"]
    if bottom:
        out.append(f"Furthest behind: {_fmt(bottom)}")
    return out


def weekly_scorecard_lines(cards: dict, monday: str, today: str) -> list:
    """Message body for check_weekly_scorecard: a Top Picks section and a
    Tomorrow's Watchlist section (up-setups and down-setups kept apart)."""
    lines = [f"🧾 <b>Weekly report card</b> · {monday} → {today}",
             "Each name from its first logged price this week, vs the Nifty over the same days."]
    tp = cards.get("top_picks")
    if tp:
        lines += [f"⭐ <b>Top Picks</b> · {_n_names(tp['n'])}",
                  f"Average move <b>{tp['mean_move']:+.1f}%</b> · {tp['up']} up / "
                  f"{tp['n'] - tp['up']} down or flat"]
        if tp.get("mean_edge") is not None:
            lines.append(f"Vs the Nifty: <b>{tp['mean_edge']:+.1f} pts</b> · "
                         f"{tp['hits']} of {tp['n_edge']} ahead")
        if tp.get("median_move") is not None and tp["n"] >= 5:
            lines.append(f"Middle name (median): {tp['median_move']:+.1f}% — a few big moves can carry the average")
        if tp["best"]:
            lines.append(f"{'Most up' if tp['worst'] else 'Moves'}: {_names_line(tp['best'])}")
        if tp["worst"]:
            lines.append(f"Most down: {_names_line(tp['worst'])}")
        lines += _sector_lines(tp.get("sectors") or [])
    up, down = cards.get("watchlist_up"), cards.get("watchlist_down")
    if up or down:
        lines += ["🌙 <b>Tomorrow's Watchlist</b>"]
        for card, title, hit_word in ((up, "📈 BUY setups (breakout, bullish reversal)", "ahead of"),
                                      (down, "📉 SELL setups (breakdown, bearish reversal)", "lagged")):
            if not card:
                continue
            row = f"{title} · {_n_names(card['n'])} · avg {card['mean_move']:+.1f}%"
            if card.get("mean_edge") is not None:
                row += f" · {card['hits']} of {card['n_edge']} {hit_word} the Nifty ({card['mean_edge']:+.1f} pts)"
            lines += [row, f"   Moved most as flagged: {_names_line(card['best'])}"]
    lines += ["<i>One week is noise — the Verdict Calibration page keeps the longer record.</i>"]
    return lines


def check_weekly_digest(state: dict, today: str) -> int:
    """Sunday-only weekly summary. Once per week."""
    # Dedup by ISO week — one fire per week, not per day
    _week_id = datetime.datetime.strptime(today, "%Y-%m-%d").strftime("%G-W%V")
    key = f"weekly_digest_{_week_id}"
    if _already_fired(state, key, today):
        return 0

    now_ist = datetime.datetime.now(_IST)
    # Sunday guard — check_alerts.py's dispatcher gates the fire time but
    # the mode itself belt-and-braces refuses to run mid-week even if
    # someone workflow_dispatch's it (weekly ≠ daily).
    if now_ist.weekday() != 6:   # Monday=0 ... Sunday=6
        print(f"[weekly] not Sunday (weekday={now_ist.weekday()}) — skipping")
        return 0

    lines = [f"📆 <b>Weekly Digest — week ahead</b> · Sun {today}"]

    # Section 1 — current top-picks list (from the persisted snapshot)
    try:
        import trade_store as store
        snap = store.kv_get("top_picks_snapshot", user_id="_system")
        buys = (snap or {}).get("data", {}).get("buys", []) or []
    except Exception as _e:
        print(f"[weekly] snapshot read failed: {_e}")
        buys = []

    if buys:
        lines.append("<b>Top scores from the delivery scan</b>")
        for b in buys[:5]:
            act = action_display_label(str(b.get("action", "")).replace("_", " "))
            price = b.get("price") or b.get("last_price")
            lines.append(_stock_line(act, _base_symbol(b.get("ticker", "?")),
                                     price if isinstance(price, (int, float)) else None,
                                     b.get("stop_loss") or b.get("stop") or b.get("sl"),
                                     extra=f"score {b.get('score', 0)}/90"))
    else:
        lines.append("No top-picks snapshot this week.")

    # Section 2 — journal entries added this week
    try:
        from alerts.journal_store import read_entries
        entries = read_entries()
    except Exception as _e:
        print(f"[weekly] journal read failed: {_e}")
        entries = []

    _week_start = (now_ist - datetime.timedelta(days=7)).date().isoformat()
    recent = [e for e in entries if e.added_date >= _week_start]
    if recent:
        lines.append(f"<b>Journal entries this week — {len(recent)}</b>")
        for e in recent[:5]:
            lines.append(f"• <b>{_h(e.ticker)}</b> ({_h(e.status)}) — {_h(e.thesis[:60])}")

    # Section 3 — reviews due in the next 7 days
    _due_cutoff = (now_ist + datetime.timedelta(days=7)).date().isoformat()
    due = [
        e for e in entries
        if e.status == "open" and e.review_date and e.review_date <= _due_cutoff
    ]
    if due:
        lines.append(f"<b>Journal reviews due next week — {len(due)}</b>")
        for e in sorted(due, key=lambda x: x.review_date)[:5]:
            lines.append(f"• <b>{_h(e.ticker)}</b> — review by {e.review_date}: {_h(e.thesis[:50])}")

    if len(lines) <= 2:
        # Only the header + "no data" line landed — send a "quiet week" note.
        lines.append("Quiet week — no journal activity, nothing to review.")
    lines.append(_FOOTER)
    msg = "\n".join(lines)

    if dispatch(msg, subject=f"Weekly Digest — week of {today}"):
        _mark_fired(state, key, today)
        return 1
    return 0


# ─────────────────────────────────────────────────────────────────────────────
# Main — mode-based dispatch
#
# Modes:
#   default              — the original 15-min market-alerts cadence
#                          (price CSV + portfolio holdings + VIX + Nifty trend)
#   morning-digest       — 09:00 IST daily: delivery top-picks digest
#   intraday-watchlist   — 09:20 IST daily: intraday framing of top picks
#   momentum             — every 30 min market hours: momentum opportunities
#   portfolio-posture    — 14:00 IST daily: Angel One holdings posture
#   weekly-digest        — 09:00 IST Sunday: week-ahead summary
#   test                 — diagnostic; proves both channels deliver
#
# --force skips the market-hours guard for local/manual runs.
# ─────────────────────────────────────────────────────────────────────────────

def _catalyst_live(state: dict, today: str) -> int:
    """Results / announcement-driven BUY and SELL calls during market hours.
    Isolated so a failure here can never stop the other checks in the run."""
    try:
        from alerts.catalyst_alerts import check_catalyst_live
        return int(check_catalyst_live(state, today) or 0)
    except Exception as e:
        print(f"[catalyst] live check failed: {type(e).__name__}: {e}")
        return 0


def _parse_mode(argv: list[str]) -> str:
    for a in argv:
        if a.startswith("--mode="):
            return a.split("=", 1)[1].strip().lower()
    return "default"


def main() -> int:
    force        = "--force" in sys.argv
    clear_today  = "--clear-today" in sys.argv
    mode         = _parse_mode(sys.argv)

    # Propagate --force into the module-level dedup-bypass flag so every
    # _already_fired() call in this run returns False and every
    # _mark_fired() call is a no-op. See _FORCE_SEND above for why.
    global _FORCE_SEND
    _FORCE_SEND = force

    # --clear-today: wipe today's dedup entries from the state file BEFORE
    # this run's own state pruning. Use this exactly once after a stale
    # manual-test dedup entry has starved a real scheduled fire — after
    # which the fix above (dedup bypass on --force) prevents recurrence.
    if clear_today:
        try:
            _today_iso = datetime.datetime.now(_IST).strftime("%Y-%m-%d")
            _existing = _load_state()
            _wiped    = {k: v for k, v in _existing.items() if v != _today_iso}
            _dropped  = len(_existing) - len(_wiped)
            _save_state(_wiped)
            print(f"[clear-today] dropped {_dropped} state entries for {_today_iso}")
        except Exception as _e:
            print(f"[clear-today] failed: {_e}")

    # morning-digest fires pre-market (09:00 IST); portfolio-posture can also
    # run after-hours (holdings LTP is snapshot-based from Angel One's last
    # trade). Test mode must ALWAYS run — its whole purpose is diagnostics.
    # Other modes still enforce the market-hours guard unless --force.
    _bypass_market_hours = (
        "morning-digest", "portfolio-posture", "test", "test-verdict", "test-digest",
        "test-posture",
        "weekly-digest", "intraday-watchlist", "tomorrow-watchlist", "weekly-scorecard",
        "catalyst-preopen", "why-moved",
    )
    if mode not in _bypass_market_hours and not force and not _is_market_hours():
        print(f"[main mode={mode}] outside NSE market hours — nothing to do.")
        return 0
    if not force and not _in_send_window(mode):
        _lo, _hi = _SEND_WINDOWS[mode]
        print(f"[main mode={mode}] {datetime.datetime.now(_IST):%H:%M} IST is outside its "
              f"{_lo:%H:%M}–{_hi:%H:%M} send window — late trigger, skipping.")
        return 0

    today = datetime.datetime.now(_IST).strftime("%Y-%m-%d")
    state = _prune_state(_load_state(), today)

    total = 0
    if mode == "morning-digest":
        total += check_delivery_digest(state, today)
    elif mode == "intraday-watchlist":
        total += check_intraday_watchlist(state, today)
    elif mode == "momentum":
        total += check_momentum_opportunities(state, today)
    elif mode == "portfolio-posture":
        total += check_portfolio_posture(state, today, always="--always" in sys.argv)
    elif mode == "weekly-digest":
        total += check_weekly_digest(state, today)
    elif mode == "tomorrow-watchlist":
        total += check_tomorrow_watchlist(state, today)
    elif mode == "weekly-scorecard":
        total += check_weekly_scorecard(state, today)
    elif mode == "catalyst-preopen":
        from alerts.catalyst_alerts import check_catalyst_preopen
        total += check_catalyst_preopen(state, today)
    elif mode == "why-moved":
        from alerts.catalyst_alerts import check_why_moved
        total += check_why_moved(state, today)
    elif mode == "test":
        total += check_test_alert(state, today)
    elif mode == "test-verdict":
        total += check_test_verdict_alert(state, today)
    elif mode == "test-digest":
        total += check_test_digest(state, today)
    elif mode == "test-posture":
        total += check_portfolio_posture(state, today, test=True)
    else:   # default
        _counts = {
            "price":     check_price_alerts(state, today),
            "portfolio": check_portfolio_alerts(state, today) if _holding_alerts_on() else 0,
            "opening":   check_opening_update(state, today),
            "moves":     check_pick_moves(state, today),
            "recap":     check_picks_recap(state, today),
            "verdicts":  check_verdict_alerts(state, today),
            "vix":       check_vix_regime(state, today),
            "nifty":     check_nifty_trend(state, today),
            "catalyst":  _catalyst_live(state, today),
        }
        print("[main] per-check: " + ", ".join(f"{k}={v}" for k, v in _counts.items()))
        total += sum(_counts.values())

    _save_state(state)
    print(f"[main mode={mode}] done — {total} alert(s) sent.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
