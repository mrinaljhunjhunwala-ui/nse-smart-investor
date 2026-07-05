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
# ─────────────────────────────────────────────────────────────────────────────

def _is_market_hours() -> bool:
    now = datetime.datetime.now(_IST)
    if now.weekday() >= 5:                      # Sat/Sun
        return False
    open_t  = now.replace(hour=9,  minute=15, second=0, microsecond=0)
    close_t = now.replace(hour=15, minute=30, second=0, microsecond=0)
    return open_t <= now <= close_t


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
        if send_telegram(msg):
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
    if send_telegram(msg):
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
    if send_telegram(msg):
        _mark_fired(state, key, today)
        return 1
    return 0


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main() -> int:
    force = "--force" in sys.argv      # bypass market-hours guard for testing
    if not force and not _is_market_hours():
        print("[main] outside NSE market hours — nothing to do.")
        return 0

    today = datetime.datetime.now(_IST).strftime("%Y-%m-%d")
    state = _prune_state(_load_state(), today)

    total = 0
    total += check_price_alerts(state, today)
    total += check_vix_regime(state, today)
    total += check_nifty_trend(state, today)

    _save_state(state)
    print(f"[main] done — {total} alert(s) sent.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
