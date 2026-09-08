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

import datetime
import json
import logging
import os
import sys
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

_ALERTS_CSV  = os.path.join(_ROOT, "data", "alerts.csv")
_STATE_JSON  = os.path.join(_ROOT, "data", "alert_state.json")
_IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30))


# ─────────────────────────────────────────────────────────────────────────────
# Telegram
# ─────────────────────────────────────────────────────────────────────────────

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


def _already_fired(state: dict, key: str, today: str) -> bool:
    return state.get(key) == today


def _mark_fired(state: dict, key: str, today: str) -> None:
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
            f"{arrow} <b>{ticker}</b> price alert\n"
            f"Now <b>₹{price:,.2f}</b> ({chg:+.2f}% today)\n"
            f"Crossed <b>{condition} ₹{level:,.2f}</b>"
            + (f"\n📝 {note}" if note else "")
        )
        if dispatch(msg):
            _mark_fired(state, key, today)
            sent += 1
    return sent


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
    if regime not in ("fear", "panic"):
        return 0

    key = f"vix_{regime}"
    if _already_fired(state, key, today):
        return 0

    icon = "🚨" if regime == "panic" else "🔴"
    msg = (
        f"{icon} <b>Market volatility alert</b>\n"
        f"India VIX is in <b>{regime.upper()}</b> territory"
        + (f" at <b>{vix:.1f}</b>" if vix else "")
        + "\nNew long entries are higher-risk — protect open positions, "
          "tighten stops, avoid fresh leverage."
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
        f"📉 <b>Nifty 50 downtrend</b>\n"
        f"Nifty at <b>{price:,.0f}</b> ({chg5:+.1f}% 5d), now below both "
        f"SMA20 ({sma20:,.0f}) and SMA50 ({sma50:,.0f}).\n"
        f"Trend has turned down — be defensive with new buys."
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
# universe. It only formats and sends. Fires ONCE per day (pre-market at
# 09:00 IST via the market-digest workflow), so the state key is date-only.
# ─────────────────────────────────────────────────────────────────────────────

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

    buys = snap["data"].get("buys") or []
    if not buys:
        print("[digest] snapshot has 0 buys — nothing to send")
        return 0

    gen_at = snap.get("generated_at", "unknown")
    lines = [
        "📈 <b>Morning Delivery Digest</b>",
        f"<i>Top {min(max_picks, len(buys))} positional candidates from today's scan "
        f"(snapshot {gen_at[:16] if isinstance(gen_at, str) else 'unknown'} IST)</i>",
        "",
    ]
    for i, b in enumerate(buys[:max_picks], start=1):
        tk    = b.get("ticker", "?")
        score = b.get("score", 0)
        act   = b.get("action", "").replace("_", " ")
        price = b.get("price") or b.get("last_price") or b.get("current_price")
        entry = b.get("entry_zone") or b.get("entry")
        stop  = b.get("stop_loss")  or b.get("stop")
        tgt   = b.get("target")
        sec   = b.get("sector", "").strip()

        price_str = f"₹{float(price):,.2f}" if isinstance(price, (int, float)) else "n/a"
        head = f"{i}. <b>{tk}</b> — {act} · Score {score}/90 · {price_str}"
        if sec:
            head += f" · {sec}"
        lines.append(head)
        detail = []
        if entry:
            detail.append(f"Entry {entry}")
        if stop:
            detail.append(f"Stop {stop}")
        if tgt:
            detail.append(f"Target {tgt}")
        if detail:
            lines.append("   " + " · ".join(str(x) for x in detail))

    lines.extend([
        "",
        "<i>Descriptive scan of composite-score leaders — not advice. "
        "Verify each name on the Analyze Stock page before any action.</i>",
    ])
    msg = "\n".join(lines)

    if dispatch(msg, subject="Morning Delivery Digest — NSE Smart Investor"):
        _mark_fired(state, key, today)
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
# Portfolio posture — analyse Angel One holdings + intraday positions
#
# Fires once per day (typically 14:00 IST via the market-digest workflow's
# 3rd cron) and sends a message listing only the holdings that need
# attention: EXIT_WATCH, TRIM_WATCH, ADD_WATCH, plus intraday STOP_HIT /
# TARGET_HIT / TRAIL_TIGHTER. If everything is HOLD/RUNNING, no message
# (only_actionable=True by default in format_portfolio_message).
# ─────────────────────────────────────────────────────────────────────────────

def check_portfolio_posture(state: dict, today: str) -> int:
    """Fetch Angel One holdings + positions, run posture analysis, alert only
    on actionable rows. Requires ANGEL_* env vars — silently no-ops otherwise
    (Angel One is optional; we can't analyse a portfolio we can't see)."""
    key = "portfolio_posture"
    if _already_fired(state, key, today):
        return 0

    try:
        from analysis.portfolio_posture import (
            analyse_holdings, analyse_positions, format_portfolio_message,
        )
        from data.angel_fetcher import get_holdings, get_positions
        from data.fetcher import fetch_single
    except Exception as _e:
        print(f"[portfolio] import failed: {_e}")
        return 0

    try:
        holdings = get_holdings() or []
    except Exception as _e:
        print(f"[portfolio] get_holdings failed (Angel One session issue?): {_e}")
        return 0
    try:
        positions = (get_positions() or {}).get("day", []) or []
    except Exception as _e:
        print(f"[portfolio] get_positions failed: {_e}")
        positions = []

    if not holdings and not positions:
        print("[portfolio] no holdings / positions — nothing to analyse")
        return 0

    def _fetch(sym):
        try:
            return fetch_single(sym, period="2y")
        except Exception:
            return None

    try:
        nifty_df = fetch_single("^NSEI", period="2y")
    except Exception:
        nifty_df = None

    print(f"[portfolio] analysing {len(holdings)} holdings + {len(positions)} intraday positions")
    hpost = analyse_holdings(holdings, _fetch, nifty_history=nifty_df)
    ipost = analyse_positions(positions, _fetch)

    msg = format_portfolio_message(hpost, ipost, only_actionable=True)
    # Suppress the 'nothing to do' message from the daily digest — the whole
    # point of an alert is to surface something. If everything is HOLD,
    # count it as fired-successfully (dedup key set) so we don't keep polling.
    if "Nothing to do" in msg:
        _mark_fired(state, key, today)
        print("[portfolio] all HOLD/RUNNING — no message sent")
        return 0

    if dispatch(msg, subject=f"Portfolio Posture — {len(hpost)+len(ipost)} row(s) need attention"):
        _mark_fired(state, key, today)
        return 1
    return 0


# ─────────────────────────────────────────────────────────────────────────────
# Main — mode-based dispatch
#
# Modes:
#   default          — the original 15-min market-alerts cadence
#                      (price CSV + VIX + Nifty trend)
#   morning-digest   — 09:00 IST daily: delivery top-picks digest
#   momentum         — every 30 min market hours: momentum opportunities
#
# --force skips the market-hours guard for local/manual runs.
# ─────────────────────────────────────────────────────────────────────────────

def _parse_mode(argv: list[str]) -> str:
    for a in argv:
        if a.startswith("--mode="):
            return a.split("=", 1)[1].strip().lower()
    return "default"


def main() -> int:
    force = "--force" in sys.argv
    mode  = _parse_mode(sys.argv)

    # morning-digest fires pre-market (09:00 IST); portfolio-posture can also
    # run after-hours (holdings LTP is snapshot-based from Angel One's last
    # trade). So both bypass the market-hours guard. Other modes still enforce.
    if mode not in ("morning-digest", "portfolio-posture") and not force \
            and not _is_market_hours():
        print(f"[main mode={mode}] outside NSE market hours — nothing to do.")
        return 0

    today = datetime.datetime.now(_IST).strftime("%Y-%m-%d")
    state = _prune_state(_load_state(), today)

    total = 0
    if mode == "morning-digest":
        total += check_delivery_digest(state, today)
    elif mode == "momentum":
        total += check_momentum_opportunities(state, today)
    elif mode == "portfolio-posture":
        total += check_portfolio_posture(state, today)
    else:   # default
        total += check_price_alerts(state, today)
        total += check_vix_regime(state, today)
        total += check_nifty_trend(state, today)

    _save_state(state)
    print(f"[main mode={mode}] done — {total} alert(s) sent.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
