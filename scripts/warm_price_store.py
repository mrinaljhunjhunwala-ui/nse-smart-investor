"""
scripts/warm_price_store.py — nightly Angel One → daily_bars price-store fill.

Runs after the close (.github/workflows/warm_price_store.yml, dispatched by
cron-job.org at 18:30 IST Mon–Fri). For every symbol in
get_universe("niftytotalmarket") plus the index symbols the app reads (^NSEI,
^INDIAVIX), it asks Angel One for daily candles from the day after the last
stored date to today, at a hard throttle, and upserts them into the
``daily_bars`` table (data/price_store.py). data.fetcher.fetch_single then
serves daily history from that table (Tier 0.5) before trying Yahoo.

* Throttle: ``ANGEL_BULK_RPS`` requests per second (default 1.4 = ~84/min,
  under the ~90/min level where Angel starts answering 403).
* First run per symbol backfills ``ANGEL_BACKFILL_DAYS`` (default 2000 — the
  most one ONE_DAY getCandleData request returns, so one call per symbol).
* Incremental and resume-safe: a symbol already holding the last completed
  session is skipped without a request, so a second run the same evening
  is a no-op.
* Rate limit: on Angel's "exceeding access rate" answer, sleep 65 s and retry
  once, then skip the symbol. Three symbols in a row failing that way end the
  run early (the rest count as skipped) so a blocked runner can't sleep for
  hours.
* Index tokens (^NSEI / ^INDIAVIX) are tried with the tokens in
  angel_fetcher.INDEX_TOKENS; unverified live — if Angel can't serve them they
  are skipped and the app keeps reading them from Yahoo.
* ``ANGEL_HIST_API_KEY`` (if set) replaces ANGEL_API_KEY for this script only.

Pure (no Streamlit UI), never raises; exit code is always 0. Final log line:
``price_store: N ok, M skipped, K new rows, took Ts``.
"""
from __future__ import annotations

import datetime
import logging
import os
import sys
import time
from typing import Callable, Iterable, Optional

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

_log = logging.getLogger("scripts.warm_price_store")

INDEX_SYMBOLS = ("^NSEI", "^INDIAVIX")
DEFAULT_RPS = 1.4
RATE_LIMIT_SLEEP_S = 65
MAX_CONSECUTIVE_RATE_LIMITED = 3


def _env_float(name: str, default: float) -> float:
    try:
        v = float(os.environ.get(name, "") or default)
        return v if v > 0 else default
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    try:
        v = int(os.environ.get(name, "") or default)
        return v if v > 0 else default
    except ValueError:
        return default


class Throttle:
    """At most ``rps`` calls per second: wait() sleeps until the next slot."""

    def __init__(self, rps: float, clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep):
        self.interval = 1.0 / rps
        self.clock, self.sleep = clock, sleep
        self._next = None

    def wait(self) -> None:
        now = self.clock()
        if self._next is not None and now < self._next:
            self.sleep(self._next - now)
            now = self._next
        self._next = now + self.interval


def fetch_window(latest: Optional[datetime.date], target: datetime.date,
                 backfill_days: int) -> Optional[tuple]:
    """(from, to) dates to request, or None when ``latest`` already covers
    ``target`` (the last completed session)."""
    if latest is None:
        return target - datetime.timedelta(days=backfill_days), target
    if latest >= target:
        return None
    return latest + datetime.timedelta(days=1), target


def _symbols() -> list:
    try:
        from data.universe import get_universe
        syms = [s for s in get_universe("niftytotalmarket") if str(s).endswith(".NS")]
    except Exception as e:
        _log.error("price_store: universe load failed: %s", e)
        syms = []
    return list(dict.fromkeys(syms + list(INDEX_SYMBOLS)))


def run(symbols: Optional[Iterable[str]] = None, *,
        fetch: Optional[Callable] = None,
        now: Optional[datetime.datetime] = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep) -> dict:
    """Fill the store. Returns {"ok", "skipped", "new_rows", "took", "line"}."""
    import pandas as pd

    from data import price_store as ps

    t0 = clock()
    ok = skipped = new_rows = 0
    rate_streak = 0
    try:
        if fetch is None:
            from data import angel_fetcher as af
            af.use_hist_api_key(True)
            fetch = af.fetch_daily_candles
        rps = _env_float("ANGEL_BULK_RPS", DEFAULT_RPS)
        backfill = _env_int("ANGEL_BACKFILL_DAYS", 2000)
        throttle = Throttle(rps, clock=clock, sleep=sleep)
        syms = list(symbols) if symbols is not None else _symbols()
        target = ps.last_completed_session(now)
        ps.ensure_table()
        latest_by_sym = ps.all_latest_dates()

        for i, sym in enumerate(syms):
            if rate_streak >= MAX_CONSECUTIVE_RATE_LIMITED:
                rest = len(syms) - i
                skipped += rest
                _log.error("price_store: %d symbols in a row rate-limited after retry — "
                           "stopping, %d left unfetched", rate_streak, rest)
                break
            window = fetch_window(latest_by_sym.get(sym), target, backfill)
            if window is None:
                ok += 1            # already current: no request
                continue
            df, status = None, "error"
            for attempt in range(2):
                throttle.wait()
                try:
                    df, status = fetch(sym, window[0], window[1])
                except Exception as e:          # fetch is meant not to raise; belt and braces
                    df, status = None, f"error:{type(e).__name__}"
                if status != "rate_limited" or attempt == 1:
                    break
                _log.warning("price_store: %s rate-limited, sleeping %ds then retrying once",
                             sym, RATE_LIMIT_SLEEP_S)
                sleep(RATE_LIMIT_SLEEP_S)
            if status == "rate_limited":
                rate_streak += 1
                skipped += 1
                _log.warning("price_store: %s skipped (still rate-limited)", sym)
                continue
            rate_streak = 0
            if status == "no_session":
                rest = len(syms) - i
                skipped += rest
                _log.error("price_store: Angel One login failed — stopping, %d symbols unfetched", rest)
                break
            if status == "empty" and sym in latest_by_sym:
                ok += 1            # a valid answer with no new sessions yet
                continue
            if status != "ok" or df is None:
                skipped += 1
                _log.warning("price_store: %s skipped (%s)", sym, status)
                continue
            df = df[df.index.normalize() <= pd.Timestamp(target)]
            if df.empty:
                ok += 1
                continue
            new_rows += ps.upsert_daily_bars(sym, df, "AngelOne")
            ps.trim_discontinuity(sym)
            ok += 1
    except Exception as e:
        _log.error("price_store: run aborted: %s: %s", type(e).__name__, e)

    took = clock() - t0
    line = f"price_store: {ok} ok, {skipped} skipped, {new_rows} new rows, took {took:.0f}s"
    _log.info(line)
    return {"ok": ok, "skipped": skipped, "new_rows": new_rows, "took": took, "line": line}


def _telegram(line: str) -> None:
    try:
        from utils.telegram import TelegramAlerter
        TelegramAlerter().send_text("🗄 " + line)
    except Exception as e:
        _log.warning("price_store: Telegram summary not sent: %s", e)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        import trade_store
        _log.info("price_store: backend=%s", trade_store.backend_name())
    except Exception as e:
        _log.warning("price_store: trade_store backend unknown: %s", e)
    result = run()
    if "--telegram" in sys.argv:
        _telegram(result["line"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
