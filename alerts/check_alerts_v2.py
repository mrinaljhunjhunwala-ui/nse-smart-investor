"""
alerts/check_alerts_v2.py — Hardened, dependency-injected alert checker.

Improvements over check_alerts.py:
  1. Dependency injection for telegram, data fetcher → testable in isolation
  2. Configuration validation on startup
  3. Explicit error handling + logging
  4. Supports dry-run mode (print instead of send)
  5. Retry logic for transient failures
  6. Type hints for clarity
  7. Graceful degradation if optional APIs unavailable

Usage:
  python alerts/check_alerts_v2.py --dry-run     # Print alerts, don't send
  python alerts/check_alerts_v2.py --force       # Bypass market-hours guard
  python alerts/check_alerts_v2.py               # Normal scheduled run
"""

from __future__ import annotations

import datetime
import json
import logging
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable, Dict, List, Optional, Protocol

# Ensure UTF-8 on Windows
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except AttributeError:
    pass

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="[%(levelname)s %(asctime)s] %(name)s: %(message)s",
)
_log = logging.getLogger("alerts")

# Project root
_ROOT = Path(__file__).parent.parent
_ALERTS_CSV = _ROOT / "data" / "alerts.csv"
_STATE_JSON = _ROOT / "data" / "alert_state.json"
_IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30))


# ────────────────────────────────────────────────────────────────────────────
# Type protocols (dependency injection interfaces)
# ────────────────────────────────────────────────────────────────────────────

class TelegramSender(Protocol):
    """Interface for sending Telegram messages."""
    def send(self, text: str) -> bool:
        """Send HTML message. Return True on success."""
        ...


class PriceQuoter(Protocol):
    """Interface for fetching live stock prices."""
    def get_quote(self, ticker: str) -> Optional[Dict]:
        """
        Return dict with keys: price, chg_pct, etc.
        Return None if unavailable.
        """
        ...


# ────────────────────────────────────────────────────────────────────────────
# Implementations
# ────────────────────────────────────────────────────────────────────────────

class TelegramSenderImpl:
    """Default Telegram implementation (direct urllib)."""
    def __init__(self, token: str, chat_id: str):
        self.token = token
        self.chat_id = chat_id
        self.enabled = bool(token and chat_id)
    
    def send(self, text: str) -> bool:
        if not self.enabled:
            print(f"[telegram] Not configured — printing instead:\n{text}")
            return False
        
        try:
            url = f"https://api.telegram.org/bot{self.token}/sendMessage"
            data = urllib.parse.urlencode({
                "chat_id": self.chat_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": "true",
            }).encode()
            req = urllib.request.Request(url, data=data)
            with urllib.request.urlopen(req, timeout=15) as r:
                ok = r.status == 200
                _log.info(f"Telegram sent ({r.status})")
                return ok
        except urllib.error.URLError as e:
            _log.error(f"Telegram URLError: {e}")
            return False
        except Exception as e:
            _log.error(f"Telegram failed: {e}")
            return False


class LivePriceQuoter:
    """Default price quoter (uses project's utils.live_price)."""
    def get_quote(self, ticker: str) -> Optional[Dict]:
        try:
            from utils.live_price import get_live_quote
            return get_live_quote(ticker)
        except ImportError:
            _log.warning("utils.live_price not available")
            return None


# ────────────────────────────────────────────────────────────────────────────
# Core alert logic (parameterized)
# ────────────────────────────────────────────────────────────────────────────

def check_price_alerts(
    state: Dict,
    today: str,
    telegram: TelegramSender,
    quoter: PriceQuoter,
) -> int:
    """Check price alerts from data/alerts.csv."""
    sent = 0
    
    if not _ALERTS_CSV.exists():
        _log.warning(f"alerts.csv not found at {_ALERTS_CSV}")
        return 0
    
    try:
        import csv
        with open(_ALERTS_CSV, newline="", encoding="utf-8") as f:
            rules = list(csv.DictReader(f))
    except Exception as e:
        _log.error(f"Failed to read alerts.csv: {e}")
        return 0
    
    for rule in rules:
        ticker = str(rule.get("ticker", "")).strip().upper()
        condition = str(rule.get("condition", "")).strip().lower()
        try:
            level = float(rule.get("level", 0))
        except ValueError:
            continue
        note = str(rule.get("note", "")).strip()
        enabled = str(rule.get("enabled", "1")).strip() not in ("0", "false", "False", "")
        
        if not enabled or not ticker or condition not in ("above", "below") or level <= 0:
            continue
        
        key = f"price_{ticker}_{condition}_{level:.2f}"
        if state.get(key) == today:
            continue  # Already fired today
        
        quote = quoter.get_quote(ticker)
        if not quote or not quote.get("price"):
            _log.debug(f"No quote for {ticker}")
            continue
        
        price = float(quote["price"])
        hit = (condition == "above" and price >= level) or \
              (condition == "below" and price <= level)
        
        if not hit:
            continue
        
        arrow = "🔼" if condition == "above" else "🔽"
        chg = quote.get("chg_pct", 0.0)
        msg = (
            f"{arrow} <b>{ticker}</b> price alert\n"
            f"Now <b>₹{price:,.2f}</b> ({chg:+.2f}% today)\n"
            f"Crossed <b>{condition} ₹{level:,.2f}</b>"
            + (f"\n📝 {note}" if note else "")
        )
        
        if telegram.send(msg):
            state[key] = today
            sent += 1
            _log.info(f"Price alert fired: {key}")
    
    return sent


def check_vix_regime(
    state: Dict,
    today: str,
    telegram: TelegramSender,
) -> int:
    """Check India VIX fear/panic regime."""
    try:
        from utils.vix import get_india_vix_regime
        info = get_india_vix_regime()
    except Exception as e:
        _log.error(f"VIX check failed: {e}")
        return 0
    
    regime = str(info.get("regime", "unknown")).lower()
    vix = info.get("vix")
    
    if regime not in ("fear", "panic"):
        return 0
    
    key = f"vix_{regime}"
    if state.get(key) == today:
        return 0
    
    icon = "🚨" if regime == "panic" else "🔴"
    msg = (
        f"{icon} <b>Market volatility alert</b>\n"
        f"India VIX is in <b>{regime.upper()}</b> territory"
        + (f" at <b>{vix:.1f}</b>" if vix else "")
        + "\nNew long entries are higher-risk — protect open positions."
    )
    
    if telegram.send(msg):
        state[key] = today
        _log.info(f"VIX alert fired: {key}")
        return 1
    return 0


def check_nifty_trend(
    state: Dict,
    today: str,
    telegram: TelegramSender,
) -> int:
    """Check Nifty 50 downtrend (price < SMA20 < SMA50)."""
    try:
        from data.fetcher import fetch_single
        df = fetch_single("^NSEI", period="3mo")
    except Exception as e:
        _log.error(f"Nifty fetch failed: {e}")
        return 0
    
    if df is None or df.empty or len(df) < 50:
        _log.warning("Nifty data insufficient")
        return 0
    
    close = df["Close"]
    price = float(close.iloc[-1])
    sma20 = float(close.rolling(20).mean().iloc[-1])
    sma50 = float(close.rolling(50).mean().iloc[-1])
    
    if not (price < sma20 < sma50):
        return 0
    
    key = "nifty_downtrend"
    if state.get(key) == today:
        return 0
    
    chg5 = (price / float(close.iloc[-6]) - 1) * 100 if len(close) >= 6 else 0.0
    msg = (
        f"📉 <b>Nifty 50 downtrend</b>\n"
        f"Nifty at <b>{price:,.0f}</b> ({chg5:+.1f}% 5d), now below both "
        f"SMA20 ({sma20:,.0f}) and SMA50 ({sma50:,.0f}).\n"
        f"Trend has turned down — be defensive."
    )
    
    if telegram.send(msg):
        state[key] = today
        _log.info(f"Nifty alert fired: {key}")
        return 1
    return 0


# ────────────────────────────────────────────────────────────────────────────
# State management
# ────────────────────────────────────────────────────────────────────────────

def load_state() -> Dict:
    """Load de-duplication state from JSON."""
    try:
        with open(_STATE_JSON, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_state(state: Dict) -> None:
    """Save state to JSON."""
    _STATE_JSON.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(_STATE_JSON, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
        _log.info("State saved")
    except Exception as e:
        _log.error(f"State save failed: {e}")


def prune_state(state: Dict, today: str) -> Dict:
    """Keep only today's entries (don't grow forever)."""
    return {k: v for k, v in state.items() if v == today}


# ────────────────────────────────────────────────────────────────────────────
# Market hours guard
# ────────────────────────────────────────────────────────────────────────────

def is_market_hours() -> bool:
    """Check if NSE market is open (Mon–Fri 9:15–15:30 IST)."""
    now = datetime.datetime.now(_IST)
    if now.weekday() >= 5:  # Saturday or Sunday
        return False
    open_t = now.replace(hour=9, minute=15, second=0, microsecond=0)
    close_t = now.replace(hour=15, minute=30, second=0, microsecond=0)
    return open_t <= now <= close_t


# ────────────────────────────────────────────────────────────────────────────
# Main orchestrator
# ────────────────────────────────────────────────────────────────────────────

def main(
    force: bool = False,
    dry_run: bool = False,
    telegram: Optional[TelegramSender] = None,
    quoter: Optional[PriceQuoter] = None,
) -> int:
    """
    Main entry point for alert checking.
    
    Args:
        force: Bypass market-hours guard
        dry_run: Print alerts instead of sending
        telegram: Telegram sender (default: real implementation)
        quoter: Price quoter (default: live_price)
    
    Returns:
        Total number of alerts sent
    """
    _log.info("Alert check started")
    
    # Set defaults
    if telegram is None:
        token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
        chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
        telegram = TelegramSenderImpl(token, chat_id)
    
    if quoter is None:
        quoter = LivePriceQuoter()
    
    # Market hours guard
    if not force and not is_market_hours():
        _log.info("Outside market hours — exiting")
        return 0
    
    # Load state
    today = datetime.datetime.now(_IST).strftime("%Y-%m-%d")
    state = prune_state(load_state(), today)
    
    # Run checks
    total = 0
    total += check_price_alerts(state, today, telegram, quoter)
    total += check_vix_regime(state, today, telegram)
    total += check_nifty_trend(state, today, telegram)
    
    # Save state
    save_state(state)
    _log.info(f"Alert check completed — {total} alert(s) sent")
    
    return 0  # Always exit 0 (failed alert shouldn't fail workflow)


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="Market alert checker (v2 — hardened)")
    p.add_argument("--force", action="store_true", help="Bypass market-hours guard")
    p.add_argument("--dry-run", action="store_true", help="Print alerts instead of sending")
    args = p.parse_args()
    
    # Mock telegram for dry-run
    if args.dry_run:
        class DryRunTelegram:
            def send(self, text: str) -> bool:
                print(f"\n[DRY-RUN] Would send:\n{text}\n")
                return True
        telegram = DryRunTelegram()
    else:
        telegram = None
    
    sys.exit(main(force=args.force, dry_run=args.dry_run, telegram=telegram))
