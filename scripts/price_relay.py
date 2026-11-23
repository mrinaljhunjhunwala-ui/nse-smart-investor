"""
scripts/price_relay.py — Angel One live-price relay (long-running service).

Why: Angel One SmartAPI is the only true real-time price source, but the
owner's SmartAPI app is locked to registered static IPs, so every call from
Streamlit Cloud and GitHub Actions is refused and the app's "live" prices come
from Yahoo (can lag ~15 min). This relay runs on a small always-on VM whose
reserved public IP is registered as the app's Secondary Static IP
(deploy/oracle-relay/README.md). It pulls quotes from Angel and stores them in
the shared database; utils/live_price.py reads them first.

What it does
  * Runs only in NSE market hours: trading days (utils.nse_holidays), 09:08 to
    15:35 IST, computed in IST explicitly (the VM's own time zone is ignored).
    Outside that it sleeps and checks again every minute, so systemd can keep
    it always on.
  * Symbol set (de-duplicated, capped at RELAY_MAX_SYMBOLS, default 250), in
    priority order: My Portfolio holdings, the watchlist, open paper trades,
    today's Morning Digest picks, today's BUY calls and intraday levels, the
    indices (^NSEI, ^NSEBANK, ^INDIAVIX), Top Picks, Tomorrow's Watchlist, then
    the NIFTY 50. Small keys are re-read every RELAY_SYMBOLS_REFRESH_S (300 s);
    the two large scan snapshots only every RELAY_SNAPSHOT_REFRESH_S (1800 s).
  * Every RELAY_INTERVAL_S (default 20 s): data.angel_fetcher.get_batch_quotes
    in 50-symbol chunks (it keeps its own 1 req/s pacing, breaker and
    rate-limit cooldown), then ONE compact KV document

        live_quotes (user _system) = {"ts": iso_utc, "source": "angel-relay",
            "quotes": {SYMBOL: {"ltp", "prev_close", "change_pct", "volume", "ts"}}}

    where each quote's "ts" is the epoch second it was fetched (a symbol whose
    fetch failed this tick keeps its previous quote and older ts for up to
    RELAY_CARRY_S, so readers judge freshness per quote), plus a tiny
    heartbeat, live_quotes_heartbeat = {ts, n_symbols, n_requested,
    last_error, key_slot}. A tick that gets no quotes at all leaves
    live_quotes untouched and only writes the heartbeat.
  * Never exits on an error: every failure is logged, the loop backs off
    (doubling up to 5 min) and carries on.

Database transfer (Neon free plan: 5 GB/month)
  One quote is ~97 bytes of compact JSON (symbol key included). A typical set
  (NIFTY 50 + holdings + watchlist + picks + indices) is ~110 symbols = ~10.5 KB
  per write; at the 250 cap, ~24 KB. A relay day is 09:08-15:35 = 23,220 s =
  ~1,160 ticks at 20 s, so writes are ~12 MB/day typical (~28 MB at the cap),
  i.e. ~0.27 GB / ~0.6 GB per month over 22 sessions; the heartbeat (~130 B)
  and the symbol refreshes (~3 MB/day with ~150 KB snapshots every 30 min) add
  little. App reads: utils/live_price caches the document for 10 s per process,
  so one browser kept on a live page all session reads at most ~2,300 docs/day
  (~24 MB typical; the Live Ticker's 30 s tick makes it ~8 MB). Whole system,
  typical: well under 1 GB/month even counting both directions (Neon bills
  transfer out of the database, i.e. mainly reads).

Run: python scripts/price_relay.py   (env: see deploy/oracle-relay/nse-price-relay.env.example)
Secrets come only from the environment; this file never logs them.
"""
from __future__ import annotations

import csv
import datetime
import json
import logging
import os
import sys
import time
import urllib.parse
import urllib.request
from typing import Callable, Dict, Iterable, List, Optional

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

_log = logging.getLogger("price_relay")

IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
KV_USER = "_system"
QUOTES_KEY = "live_quotes"
HEARTBEAT_KEY = "live_quotes_heartbeat"
SOURCE = "angel-relay"
INDEX_TICKERS = ("^NSEI", "^NSEBANK", "^INDIAVIX")
CHUNK = 50
WINDOW_START = datetime.time(9, 8)
WINDOW_END = datetime.time(15, 35)
_CONSTITUENTS_CSV = os.path.join(_ROOT, "data", "nse_index_constituents.csv")


def _env_float(name: str, default: float, lo: float) -> float:
    try:
        return max(lo, float(os.environ.get(name, "") or default))
    except ValueError:
        return default


def interval_s() -> float:
    return _env_float("RELAY_INTERVAL_S", 20.0, 5.0)


def max_symbols() -> int:
    return int(_env_float("RELAY_MAX_SYMBOLS", 250, 10))


def now_ist() -> datetime.datetime:
    return datetime.datetime.now(IST)


def in_relay_window(now: Optional[datetime.datetime] = None) -> bool:
    """True on an NSE trading day between 09:08 and 15:35 IST (IST explicitly)."""
    n = (now or now_ist()).astimezone(IST)
    from utils.nse_holidays import is_trading_day
    try:
        if not is_trading_day(n.date()):
            return False
    except Exception:                                       # noqa: BLE001
        if n.weekday() >= 5:
            return False
    return WINDOW_START <= n.time() <= WINDOW_END


# ── Symbol set ──────────────────────────────────────────────────────────────

def base_symbol(t) -> str:
    """'RELIANCE.NS' -> 'RELIANCE'; '^NSEI' unchanged; '' for junk / BSE-only (.BO)."""
    s = str(t or "").strip().upper()
    if not s or s.endswith(".BO") or len(s) > 30 or " " in s:
        return ""
    return s[:-3] if s.endswith(".NS") else s


def tickers_in(obj, depth: int = 4) -> List[str]:
    """Every "ticker" / "symbol" value in nested lists / dicts, plus plain string items of
    lists, in order. Snapshot layouts differ ({"data": {"buys": [...]}}, {"levels": {SYM: ..}})."""
    out: List[str] = []
    if depth < 0 or obj is None:
        return out
    if isinstance(obj, str):
        return [obj]
    if isinstance(obj, dict):
        for k in ("ticker", "symbol"):
            if isinstance(obj.get(k), str):
                out.append(obj[k])
        for v in obj.values():
            if isinstance(v, (dict, list)):
                out.extend(tickers_in(v, depth - 1))
        return out
    if isinstance(obj, list):
        for v in obj:
            out.extend(tickers_in(v, depth - 1))
    return out


def nifty50_symbols(path: str = _CONSTITUENTS_CSV) -> List[str]:
    """NIFTY 50 constituents from the repo's constituent file (no network, no yfinance)."""
    try:
        with open(path, encoding="utf-8") as f:
            return [r["Symbol"].strip().upper() for r in csv.DictReader(f)
                    if (r.get("Index") or "").strip().upper() == "NIFTY50" and r.get("Symbol")]
    except Exception as e:                                  # noqa: BLE001
        _log.warning("NIFTY 50 list unavailable: %s", e)
        return []


def build_symbol_set(groups: Iterable[Iterable[str]], cap: int) -> List[str]:
    """Bare symbols from each group in order, de-duplicated, at most ``cap``."""
    seen: Dict[str, None] = {}
    for g in groups:
        for t in g or []:
            b = base_symbol(t)
            if b and b not in seen:
                seen[b] = None
                if len(seen) >= cap:
                    return list(seen)
    return list(seen)


class SymbolSource:
    """The relay's symbol set, re-read from the store on two cadences."""

    def __init__(self, store, *, small_every_s: Optional[float] = None,
                 snapshot_every_s: Optional[float] = None, clock: Callable[[], float] = time.monotonic):
        self.store = store
        self.small_every_s = small_every_s or _env_float("RELAY_SYMBOLS_REFRESH_S", 300, 30)
        self.snapshot_every_s = snapshot_every_s or _env_float("RELAY_SNAPSHOT_REFRESH_S", 1800, 60)
        self.clock = clock
        self._small: List[List[str]] = []
        self._snap: List[List[str]] = []
        self._small_at = self._snap_at = None
        self._nifty = nifty50_symbols()

    def _kv(self, key: str, user_id: str = "default"):
        try:
            return self.store.kv_get(key, None, user_id=user_id)
        except Exception as e:                              # noqa: BLE001
            _log.warning("symbol source: %s unreadable: %s", key, e)
            return None

    def _open_paper(self) -> List[str]:
        try:
            df = self.store.fetch_open()
            return [str(t) for t in df["ticker"].tolist()] if df is not None and "ticker" in df else []
        except Exception as e:                              # noqa: BLE001
            _log.debug("symbol source: open paper trades unreadable: %s", e)
            return []

    def _read_small(self, today: str) -> List[List[str]]:
        levels = self._kv("intraday_levels", KV_USER)
        lv = (list((levels.get("levels") or {}).keys())
              if isinstance(levels, dict) and levels.get("date") == today else [])
        digest = self._kv("morning_digest_picks", KV_USER)
        dg = tickers_in(digest.get("buys")) if isinstance(digest, dict) and digest.get("date") == today else []
        return [
            tickers_in(self._kv("manual_portfolio_holdings")),
            tickers_in(self._kv("watchlist")),
            tickers_in(self._kv("my_watchlist_rows")),
            self._open_paper(),
            dg,
            tickers_in(self._kv(f"buy_calls:{today}", KV_USER)),
            lv,
        ]

    def _read_snapshots(self) -> List[List[str]]:
        out = []
        for key in ("top_picks_snapshot", "tomorrow_watchlist_snapshot"):
            snap = self._kv(key, KV_USER)
            out.append(tickers_in(snap.get("data") if isinstance(snap, dict) else None, depth=3))
        return out

    def symbols(self, now: Optional[datetime.datetime] = None) -> List[str]:
        t = self.clock()
        today = (now or now_ist()).astimezone(IST).strftime("%Y-%m-%d")
        if self._small_at is None or t - self._small_at >= self.small_every_s:
            self._small, self._small_at = self._read_small(today), t
        if self._snap_at is None or t - self._snap_at >= self.snapshot_every_s:
            self._snap, self._snap_at = self._read_snapshots(), t
        return build_symbol_set([*self._small, list(INDEX_TICKERS), *self._snap, self._nifty],
                                max_symbols())


# ── One tick ────────────────────────────────────────────────────────────────

def _angel_ticker(sym: str) -> str:
    return sym if sym.startswith("^") else f"{sym}.NS"


def _compact_quote(q: dict, ts: int) -> Optional[dict]:
    try:
        ltp = float(q.get("price"))
        pc = float(q.get("prev_close") or ltp)
    except (TypeError, ValueError):
        return None
    if not (ltp > 0) or ltp != ltp:
        return None
    if not (pc > 0) or pc != pc:
        pc = ltp
    out = {"ltp": round(ltp, 2), "prev_close": round(pc, 2),
           "change_pct": round((ltp / pc - 1) * 100, 2), "ts": ts}
    try:
        vol = int(q.get("volume") or 0)
    except (TypeError, ValueError):
        vol = 0
    if vol > 0:
        out["volume"] = vol
    return out


def fetch_quotes(symbols: List[str], batch_fn: Callable[[List[str]], dict],
                 now_epoch: Optional[int] = None) -> Dict[str, dict]:
    """{SYMBOL: compact quote} via batch_fn in CHUNK-symbol calls. A failing chunk is skipped."""
    ts = int(now_epoch if now_epoch is not None else time.time())
    out: Dict[str, dict] = {}
    for i in range(0, len(symbols), CHUNK):
        chunk = symbols[i:i + CHUNK]
        tick_map = {_angel_ticker(s): s for s in chunk}
        try:
            res = batch_fn(list(tick_map)) or {}
        except Exception as e:                              # noqa: BLE001
            _log.warning("quote chunk %d failed: %s", i // CHUNK, e)
            continue
        for t, q in res.items():
            sym = tick_map.get(t) or base_symbol(t)
            if sym in chunk and isinstance(q, dict):
                cq = _compact_quote(q, ts)
                if cq:
                    out[sym] = cq
    return out


def _angel_reason() -> str:
    try:
        from data.angel_fetcher import last_candle_error
        return last_candle_error() or ""
    except Exception:                                       # noqa: BLE001
        return ""


def _key_slot() -> str:
    try:
        from data.angel_fetcher import _key_slot as ks
        return ks()
    except Exception:                                       # noqa: BLE001
        return "unknown"


class Relay:
    def __init__(self, store, batch_fn: Callable[[List[str]], dict], source: Optional[SymbolSource] = None,
                 notify: Optional[Callable[[str], bool]] = None):
        self.store = store
        self.batch_fn = batch_fn
        self.source = source or SymbolSource(store)
        self.notify = notify
        self.last_quotes: Dict[str, dict] = {}
        self.fail_streak = 0
        self.notified_day: Optional[str] = None
        self.carry_s = _env_float("RELAY_CARRY_S", 300, 0)

    def tick(self, now: Optional[datetime.datetime] = None) -> dict:
        """One fetch + write. Returns a small status dict (never raises for Angel / store errors)."""
        now = now or now_ist()
        epoch = int(now.timestamp())
        t0 = time.monotonic()
        symbols = self.source.symbols(now)
        fresh = fetch_quotes(symbols, self.batch_fn, epoch)
        quotes = dict(fresh)
        for s in symbols:                    # carry a recent quote over a one-off miss
            old = self.last_quotes.get(s)
            if s not in quotes and old and epoch - int(old.get("ts", 0)) <= self.carry_s:
                quotes[s] = old
        err = "" if fresh else (_angel_reason() or "no quotes returned")
        iso = now.astimezone(datetime.timezone.utc).isoformat(timespec="seconds")
        size = 0
        wrote = False
        if fresh:
            doc = {"ts": iso, "source": SOURCE, "quotes": quotes}
            size = len(json.dumps(doc, separators=(",", ":")))
            wrote = bool(self.store.kv_set(QUOTES_KEY, doc, user_id=KV_USER, compact=True))
            if not wrote:
                err = "database write failed"
            self.last_quotes = quotes
        hb = {"ts": iso, "n_symbols": len(fresh), "n_requested": len(symbols),
              "last_error": err[:200], "key_slot": _key_slot()}
        self.store.kv_set(HEARTBEAT_KEY, hb, user_id=KV_USER, compact=True)
        self.fail_streak = 0 if (fresh and wrote) else self.fail_streak + 1
        st = {"n_requested": len(symbols), "n_fresh": len(fresh), "n_written": len(quotes) if wrote else 0,
              "bytes": size, "secs": round(time.monotonic() - t0, 1), "error": err}
        _log.info("tick %s IST · %d/%d quotes · %.1f s · %.1f KB%s", now.astimezone(IST).strftime("%H:%M:%S"),
                  st["n_fresh"], st["n_requested"], st["secs"], size / 1024, f" · {err}" if err else "")
        self._maybe_notify(now, err)
        return st

    def _maybe_notify(self, now: datetime.datetime, err: str) -> None:
        """One Telegram note a day when ~5 minutes of ticks in a row got nothing."""
        day = now.astimezone(IST).strftime("%Y-%m-%d")
        if not self.notify or self.fail_streak < max(3, int(300 / interval_s())) or self.notified_day == day:
            return
        self.notified_day = day
        try:
            self.notify(f"⚠️ Price relay gets no Angel One quotes since ~{now.astimezone(IST):%H:%M} IST"
                        f" ({err or 'unknown'}). The app falls back to Yahoo prices.")
        except Exception as e:                              # noqa: BLE001
            _log.debug("notify failed: %s", e)


def telegram_notify(text: str) -> bool:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat:
        return False
    data = urllib.parse.urlencode({"chat_id": chat, "text": text}).encode()
    req = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=data)
    with urllib.request.urlopen(req, timeout=15) as r:
        return r.status == 200


def run_forever(relay: Relay, *, sleep: Callable[[float], None] = time.sleep,
                now_fn: Callable[[], datetime.datetime] = now_ist,
                max_loops: Optional[int] = None) -> None:
    """The service loop. Never returns unless max_loops is given (tests)."""
    loops = 0
    errors = 0
    was_open: Optional[bool] = None
    closed_logged_at = 0.0
    while max_loops is None or loops < max_loops:
        loops += 1
        started = time.monotonic()
        try:
            now = now_fn()
            if not in_relay_window(now):
                if was_open is not False or time.monotonic() - closed_logged_at > 3600:
                    _log.info("market closed (%s IST) — sleeping, checking every minute",
                              now.astimezone(IST).strftime("%a %H:%M"))
                    closed_logged_at = time.monotonic()
                was_open = False
                sleep(60)
                continue
            if was_open is not True:
                _log.info("market window open — relaying every %.0f s (Angel key slot: %s)",
                          interval_s(), _key_slot())
            was_open = True
            relay.tick(now)
            errors = 0
            sleep(max(1.0, interval_s() - (time.monotonic() - started)))
        except Exception as e:                              # noqa: BLE001
            errors += 1
            back = min(300.0, interval_s() * (2 ** min(errors, 5)))
            _log.exception("relay loop error #%d (%s); retrying in %.0f s", errors, e, back)
            try:
                sleep(back)
            except Exception:                               # noqa: BLE001
                pass


def main() -> int:
    logging.basicConfig(level=os.environ.get("RELAY_LOG_LEVEL", "INFO").upper(),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    for noisy in ("urllib3", "trade_store"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    import trade_store as store
    from data import angel_fetcher
    if not angel_fetcher.is_configured():
        _log.error("Angel One credentials missing (ANGEL_API_KEY / ANGEL_CLIENT_ID / ANGEL_PASSWORD / "
                   "ANGEL_TOTP_SECRET); the relay keeps running and retries every tick")
    if store.backend_name() != "postgres":
        _log.warning("DATABASE_URL is not set: quotes go to a local SQLite file the app cannot see")
    _log.info("price relay starting · interval %.0f s · cap %d symbols · Angel key slot: %s",
              interval_s(), max_symbols(), _key_slot())
    run_forever(Relay(store, angel_fetcher.get_batch_quotes, notify=telegram_notify))
    return 0


if __name__ == "__main__":
    sys.exit(main())
