"""
data/price_store.py — persistent daily-bar store (Angel One nightly warm-up).

Why: bulk scans (~750 names) can only use Yahoo live, because Angel One's
candle API answers 403 "exceeding access rate" above ~90 calls/min (FIX
AO-BULK in data/angel_fetcher.py) and Stooq is dead. Yahoo was a single point
of failure. scripts/warm_price_store.py fills this table from Angel One after
the close at a hard throttle, and data.fetcher.fetch_single reads it as
Tier 0.5 (before Yahoo) when it is fresh and long enough.

Table ``daily_bars(symbol, date, open, high, low, close, volume, source,
fetched_at)``, PK (symbol, date), in the same database as trade_store
(SQLite ``trades.db`` by default, Postgres when DATABASE_URL is set). It uses
trade_store's connection helper; dates are ISO ``YYYY-MM-DD`` text on both
backends (same convention as trade_store's timestamps), so range filters are
plain string comparisons.

ADJUSTMENT BASIS (assumption, not verified live): Angel One daily candles are
treated as UNADJUSTED for splits and bonuses, while Yahoo's v8 chart closes are
split-adjusted. Two guards keep a split from poisoning a 200-day SMA:

* ``trim_discontinuity`` (run by the warm job on every write): a session-to-
  session close move of more than 30% is treated as an unadjusted corporate
  action, and the rows before it are deleted, so the store only holds one
  price basis. NSE price bands cap normal moves at 20%; an F&O name with a
  genuine >30% day just gets served by Yahoo until enough history rebuilds —
  the safe direction. Index symbols (``^``) are exempt (VIX moves 30%+).
* ``price_store_split_check`` (run by fetch_single whenever Yahoo serves a
  daily frame): compares the store's close with Yahoo's on the latest and
  the oldest date they share; a >30% mismatch drops the symbol's rows, the
  next nightly run backfills it again and the trim above applies.

Bonus/split ratios under 1.3 (e.g. 5:4) are not caught by either guard.
Dividends are not adjusted by either source's close column.

Everything here is pure (no Streamlit) and never raises to callers: a missing
table or an unreachable database reads as an empty store.
"""
from __future__ import annotations

import datetime
import logging
import os
import threading
import time
from typing import Optional

import pandas as pd

_log = logging.getLogger("data.price_store")

_TABLE = "daily_bars"
_SPLIT_THRESHOLD = 0.30
_OHLCV = ["Open", "High", "Low", "Close", "Volume"]
_IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30))

_ready_for: Optional[str] = None
_ready_lock = threading.Lock()

# Read-path guards for the app: a store that is empty (job never ran) or a
# database that errors should cost one query per few minutes, not one per
# fetch_single call in a 750-name scan.
_HAS_ROWS_TTL = 600
_has_rows_cache: dict = {}          # db_key -> (bool, ts)


def _ts():
    import trade_store
    return trade_store


def _db_key() -> str:
    ts = _ts()
    return ts._database_url() or ts._SQLITE_PATH


def enabled() -> bool:
    """Tier 0.5 switch: ``NSE_PRICE_STORE=0`` turns the read path off."""
    return os.environ.get("NSE_PRICE_STORE", "1").strip().lower() not in ("0", "false", "no", "off")


def ensure_table() -> None:
    """Create daily_bars if needed (once per database path)."""
    global _ready_for
    key = _db_key()
    if _ready_for == key:
        return
    ts = _ts()
    with _ready_lock:
        if _ready_for == key:
            return
        with ts._get_conn() as conn:
            cur = conn.cursor()
            if ts._is_pg():
                cur.execute(f"""
                    CREATE TABLE IF NOT EXISTS {_TABLE} (
                        symbol     TEXT NOT NULL,
                        date       TEXT NOT NULL,
                        open       DOUBLE PRECISION,
                        high       DOUBLE PRECISION,
                        low        DOUBLE PRECISION,
                        close      DOUBLE PRECISION,
                        volume     BIGINT,
                        source     TEXT,
                        fetched_at TEXT,
                        PRIMARY KEY (symbol, date)
                    )
                """)
            else:
                cur.execute(f"""
                    CREATE TABLE IF NOT EXISTS {_TABLE} (
                        symbol     TEXT NOT NULL,
                        date       TEXT NOT NULL,
                        open       REAL,
                        high       REAL,
                        low        REAL,
                        close      REAL,
                        volume     INTEGER,
                        source     TEXT,
                        fetched_at TEXT,
                        PRIMARY KEY (symbol, date)
                    )
                """)
            conn.commit()
        _ready_for = key


def _now_ist_iso() -> str:
    return datetime.datetime.now(_IST).replace(tzinfo=None).isoformat(timespec="seconds")


def _num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if f != f else f


def upsert_daily_bars(symbol: str, df: pd.DataFrame, source: str) -> int:
    """Insert/replace one symbol's daily bars. Returns the number of rows that
    did not exist before (0 on failure; never raises)."""
    if df is None or df.empty or not isinstance(df.index, pd.DatetimeIndex):
        return 0
    try:
        ensure_table()
        ts = _ts()
        fetched = _now_ist_iso()
        rows = []
        for d, r in df.iterrows():
            close = _num(r.get("Close"))
            if close is None:
                continue
            vol = _num(r.get("Volume"))
            rows.append((symbol, d.strftime("%Y-%m-%d"), _num(r.get("Open")), _num(r.get("High")),
                         _num(r.get("Low")), close, int(vol) if vol is not None else None,
                         source, fetched))
        if not rows:
            return 0
        with ts._get_conn() as conn:
            cur = conn.cursor()
            cur.execute(ts._q(f"SELECT COUNT(*) FROM {_TABLE} WHERE symbol=?"), (symbol,))
            before = int(cur.fetchone()[0])
            if ts._is_pg():
                # execute_values: one round trip per 1000 rows. executemany is
                # one per row — a 2000-day backfill x 750 names over a remote
                # Neon/Supabase link would take hours.
                from psycopg2.extras import execute_values
                execute_values(
                    cur,
                    f"INSERT INTO {_TABLE} (symbol, date, open, high, low, close, volume, source, "
                    "fetched_at) VALUES %s "
                    "ON CONFLICT (symbol, date) DO UPDATE SET open=EXCLUDED.open, "
                    "high=EXCLUDED.high, low=EXCLUDED.low, close=EXCLUDED.close, "
                    "volume=EXCLUDED.volume, source=EXCLUDED.source, fetched_at=EXCLUDED.fetched_at",
                    rows, page_size=1000,
                )
            else:
                cur.executemany(
                    f"INSERT OR REPLACE INTO {_TABLE} (symbol, date, open, high, low, close, volume, "
                    "source, fetched_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    rows,
                )
            cur.execute(ts._q(f"SELECT COUNT(*) FROM {_TABLE} WHERE symbol=?"), (symbol,))
            after = int(cur.fetchone()[0])
            conn.commit()
        _has_rows_cache.clear()
        return max(0, after - before)
    except Exception as e:
        _log.warning("price_store.upsert_daily_bars(%s) failed: %s", symbol, e)
        return 0


def _rows_to_frame(rows) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=_OHLCV)
    df = pd.DataFrame(rows, columns=["Date"] + _OHLCV)
    df["Date"] = pd.to_datetime(df["Date"])
    df = df.set_index("Date").sort_index()
    return df.apply(pd.to_numeric, errors="coerce")


def period_start(period: str, today: Optional[datetime.date] = None) -> datetime.date:
    """First calendar date a fetch_single(period=...) request asks for — same
    table data.fetcher uses for Stooq."""
    from data.fetcher import _PERIOD_DAYS
    today = today or datetime.datetime.now(_IST).date()
    p = str(period).lower()
    if p == "ytd":
        return datetime.date(today.year, 1, 1)
    return today - datetime.timedelta(days=_PERIOD_DAYS.get(p, 370))


def load_daily_bars(symbol: str, period: Optional[str] = None) -> pd.DataFrame:
    """Stored bars for ``symbol`` (all of them when ``period`` is None), as a
    flat Open/High/Low/Close/Volume frame on a naive DatetimeIndex. Empty frame
    if the table is missing or the read fails."""
    try:
        ts = _ts()
        sql = f"SELECT date, open, high, low, close, volume FROM {_TABLE} WHERE symbol=?"
        params: tuple = (symbol,)
        if period:
            sql += " AND date >= ?"
            params = (symbol, period_start(period).isoformat())
        with ts._get_conn() as conn:
            cur = conn.cursor()
            cur.execute(ts._q(sql + " ORDER BY date"), params)
            rows = cur.fetchall()
        return _rows_to_frame(rows)
    except Exception as e:
        _log.debug("price_store.load_daily_bars(%s) unavailable: %s", symbol, e)
        return pd.DataFrame(columns=_OHLCV)


def symbol_bounds(symbol: str) -> tuple:
    """(oldest, latest) stored date for one symbol as datetime.date, or (None, None)."""
    try:
        ts = _ts()
        with ts._get_conn() as conn:
            cur = conn.cursor()
            cur.execute(ts._q(f"SELECT MIN(date), MAX(date) FROM {_TABLE} WHERE symbol=?"), (symbol,))
            lo, hi = cur.fetchone() or (None, None)
        if not hi:
            return None, None
        return (datetime.date.fromisoformat(str(lo)[:10]), datetime.date.fromisoformat(str(hi)[:10]))
    except Exception as e:
        _log.debug("price_store.symbol_bounds(%s) unavailable: %s", symbol, e)
        return None, None


def all_latest_dates() -> dict:
    """{symbol: latest stored date} for every stored symbol (one query)."""
    try:
        ensure_table()
        ts = _ts()
        with ts._get_conn() as conn:
            cur = conn.cursor()
            cur.execute(f"SELECT symbol, MAX(date) FROM {_TABLE} GROUP BY symbol")
            return {s: datetime.date.fromisoformat(str(d)[:10]) for s, d in cur.fetchall() if d}
    except Exception as e:
        _log.warning("price_store.all_latest_dates failed: %s", e)
        return {}


def delete_symbol(symbol: str, before: Optional[str] = None) -> int:
    """Delete a symbol's rows (only those dated before ``before`` when given)."""
    try:
        ts = _ts()
        with ts._get_conn() as conn:
            cur = conn.cursor()
            if before:
                cur.execute(ts._q(f"DELETE FROM {_TABLE} WHERE symbol=? AND date < ?"), (symbol, before))
            else:
                cur.execute(ts._q(f"DELETE FROM {_TABLE} WHERE symbol=?"), (symbol,))
            n = cur.rowcount or 0
            conn.commit()
        _has_rows_cache.clear()
        return int(n)
    except Exception as e:
        _log.warning("price_store.delete_symbol(%s) failed: %s", symbol, e)
        return 0


def price_store_status() -> dict:
    """{symbols, latest_date, oldest_date, rows}; zeros/None when empty or missing."""
    out = {"symbols": 0, "latest_date": None, "oldest_date": None, "rows": 0}
    try:
        ts = _ts()
        with ts._get_conn() as conn:
            cur = conn.cursor()
            cur.execute(f"SELECT COUNT(DISTINCT symbol), MAX(date), MIN(date), COUNT(*) FROM {_TABLE}")
            sym, hi, lo, n = cur.fetchone()
        out.update(symbols=int(sym or 0), latest_date=str(hi)[:10] if hi else None,
                   oldest_date=str(lo)[:10] if lo else None, rows=int(n or 0))
    except Exception as e:
        _log.debug("price_store_status unavailable: %s", e)
    return out


# ── Trading-session helpers (utils.nse_holidays) ─────────────────────────────

def _ist_naive(now: Optional[datetime.datetime] = None) -> datetime.datetime:
    """``now`` (default: the clock) as naive IST wall time."""
    now = now or datetime.datetime.now(_IST)
    return now.astimezone(_IST).replace(tzinfo=None) if now.tzinfo else now


def last_completed_session(now: Optional[datetime.datetime] = None) -> datetime.date:
    """Latest NSE session whose close (15:30 IST) has passed at ``now``."""
    from utils.nse_holidays import is_trading_day
    now = _ist_naive(now)
    d = now.date()
    if not (is_trading_day(d) and now.time() >= datetime.time(15, 30)):
        d -= datetime.timedelta(days=1)
    while not is_trading_day(d):
        d -= datetime.timedelta(days=1)
    return d


def sessions_after(latest: datetime.date, upto: datetime.date) -> int:
    """Number of NSE sessions in (latest, upto]."""
    from utils.nse_holidays import is_trading_day
    n, d = 0, latest + datetime.timedelta(days=1)
    while d <= upto:
        n += is_trading_day(d)
        d += datetime.timedelta(days=1)
    return n


def is_fresh(latest: Optional[datetime.date], now: Optional[datetime.datetime] = None,
             max_lag: int = 1) -> bool:
    """True when ``latest`` is at most ``max_lag`` completed sessions behind."""
    if latest is None:
        return False
    return sessions_after(latest, last_completed_session(now)) <= max_lag


# ── Read path used by data.fetcher (Tier 0.5) ────────────────────────────────

def _has_rows() -> bool:
    key = _db_key()
    hit = _has_rows_cache.get(key)
    if hit and time.time() - hit[1] < _HAS_ROWS_TTL:
        return hit[0]
    ok = price_store_status()["rows"] > 0
    _has_rows_cache[key] = (ok, time.time())
    return ok


def serve(symbol: str, period: str, now: Optional[datetime.datetime] = None) -> Optional[pd.DataFrame]:
    """Stored frame for fetch_single, or None when the store can't serve it:
    disabled, empty/unreachable, not reaching back to the period's start
    (7-day grace for weekends/holidays), or more than one session stale."""
    if not enabled() or not _has_rows():
        return None
    now = _ist_naive(now)
    start = period_start(period, now.date())
    df = load_daily_bars(symbol, None)
    if df is None or df.empty:
        return None
    if df.index[0].date() > start + datetime.timedelta(days=7):
        return None
    if not is_fresh(df.index[-1].date(), now):
        return None
    return df[df.index >= pd.Timestamp(start)]


def price_store_split_check(symbol: str, df: pd.DataFrame) -> bool:
    """Compare stored closes with a (split-adjusted) Yahoo frame ``df`` on the
    most recent and the oldest date both have. On a >30% mismatch the symbol's
    rows are dropped (logged) and True is returned. Never raises."""
    try:
        if (df is None or df.empty or "Close" not in df.columns or str(symbol).startswith("^")
                or not _has_rows()):
            return False
        stored = load_daily_bars(symbol, None)
        if stored.empty:
            return False
        yc = df["Close"].copy()
        yc.index = pd.DatetimeIndex(yc.index).normalize()
        common = stored.index.normalize().intersection(yc.index)
        if len(common) == 0:
            return False
        sc = stored["Close"].copy()
        sc.index = sc.index.normalize()
        for d in {common[-1], common[0]}:
            s, y = float(sc.loc[d]), float(yc.loc[d])
            if s > 0 and y > 0 and abs(s / y - 1) > _SPLIT_THRESHOLD:
                n = delete_symbol(symbol)
                _log.warning("price_store: %s stored close %.2f vs Yahoo %.2f on %s (>%d%%) — "
                             "likely unadjusted split/bonus; dropped %d rows, next run re-backfills",
                             symbol, s, y, d.date(), int(_SPLIT_THRESHOLD * 100), n)
                return True
        return False
    except Exception as e:
        _log.debug("price_store_split_check(%s) skipped: %s", symbol, e)
        return False


def discontinuity_date(df: pd.DataFrame) -> Optional[pd.Timestamp]:
    """Date of the LAST session whose close moved >30% from the previous
    session's close (an unadjusted corporate action), or None."""
    if df is None or len(df) < 2 or "Close" not in df.columns:
        return None
    c = pd.to_numeric(df["Close"], errors="coerce")
    ratio = (c / c.shift(1) - 1).abs()
    hits = ratio[ratio > _SPLIT_THRESHOLD]
    return hits.index[-1] if len(hits) else None


def trim_discontinuity(symbol: str) -> int:
    """Delete stored rows before the last >30% close-to-close jump so only one
    price basis remains. Index symbols are exempt. Returns rows deleted."""
    if str(symbol).startswith("^"):
        return 0
    stored = load_daily_bars(symbol, None)
    cut = discontinuity_date(stored)
    if cut is None:
        return 0
    n = delete_symbol(symbol, before=cut.strftime("%Y-%m-%d"))
    _log.warning("price_store: %s jumped >%d%% on %s (unadjusted split/bonus?) — dropped %d "
                 "earlier rows", symbol, int(_SPLIT_THRESHOLD * 100), cut.date(), n)
    return n
