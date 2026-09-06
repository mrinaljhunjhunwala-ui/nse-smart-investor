"""
data/nse_delivery.py – NSE bhavcopy delivery-percentage tracker.

WHY THIS MATTERS
────────────────
NSE publishes per-symbol delivery percentage (delivered qty / traded qty) in
its daily security-wise bhavcopy. This is the closest thing retail India has
to a Level-2 institutional print:

  * High delivery % on a rising price  = institutional accumulation.
  * High delivery % on a falling price = distribution.
  * Divergence — price up sharply on LOW delivery % — is intraday froth,
    tends to unwind quickly.

Composite score Recommendation 4 of docs/COMPOSITE_SCORE_SHAPE_REVIEW.md
consumes today's delivery % and its 60-day distribution as a 4-pt sub-score
inside the Volume pillar (which stays 15 pts total — Guardrail §5).

WHERE THE DATA COMES FROM (FREE)
────────────────────────────────
NSE archives: `sec_bhavdata_full_DDMMYYYY.csv` at
`https://nsearchives.nseindia.com/products/content/`. One CSV per trading
day, ~2500 rows covering every equity. Contains SYMBOL, DELIV_PER,
DELIV_QTY, TTL_TRD_QNTY, CLOSE_PRICE and more per symbol.

Cloud IPs sometimes get 403 without a browser-like User-Agent; we set one.
On failure we surface the fetch error and log a Guardrail §14 WARNING so
drift is visible instead of showing "no delivery data" indefinitely.

STORAGE
───────
One row per (symbol, date) in the shared trade_store DB (SQLite locally,
Postgres in prod when DATABASE_URL is set). Follows exactly the fii_dii
schema pattern so the operational muscle memory is one code path, not two.

PIPELINE
────────
The daily cron / operator calls `fetch_and_persist_today()` once per
trading day. `load_symbol_history(symbol, days=60)` and `get_snapshot(symbol)`
are read-only consumers used by analysis.score.
"""
from __future__ import annotations

import csv
import datetime as _dt
import io
import logging
from typing import Dict, List, Optional

import pandas as pd
import requests

import trade_store as _store

_log = logging.getLogger("data.nse_delivery")

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/122.0 Safari/537.36")
_TIMEOUT = 20

# Columns we REQUIRE from the bhavcopy CSV — a missing one raises a named
# ValueError so provider drift is loud, not silent (Guardrail §14).
_REQUIRED_COLS = {"SYMBOL", "SERIES", "DATE1", "CLOSE_PRICE",
                  "TTL_TRD_QNTY", "DELIV_QTY", "DELIV_PER"}

_schema_ready_for: Optional[str] = None


# ─────────────────────────────────────────────────────────────────────────────
# Storage
# ─────────────────────────────────────────────────────────────────────────────

def ensure_schema() -> None:
    global _schema_ready_for
    key = _store._database_url() or _store._SQLITE_PATH
    if _schema_ready_for == key:
        return
    real = "DOUBLE PRECISION" if _store._is_pg() else "REAL"
    with _store._get_conn() as conn:
        cur = conn.cursor()
        cur.execute(f"""
            CREATE TABLE IF NOT EXISTS nse_delivery_daily (
                symbol       TEXT NOT NULL,
                date         TEXT NOT NULL,
                close        {real},
                traded_qty   {real},
                deliv_qty    {real},
                deliv_pct    {real},
                fetched_at   TEXT,
                PRIMARY KEY (symbol, date)
            )
        """)
        conn.commit()
    _schema_ready_for = key


def _persist(rows: List[Dict]) -> int:
    """Upsert rows into nse_delivery_daily. Returns rows written."""
    if not rows:
        return 0
    ensure_schema()
    now = _dt.datetime.now().isoformat(timespec="seconds")
    n = 0
    with _store._get_conn() as conn:
        cur = conn.cursor()
        for r in rows:
            try:
                if _store._is_pg():
                    cur.execute(_store._q("""
                        INSERT INTO nse_delivery_daily
                          (symbol,date,close,traded_qty,deliv_qty,deliv_pct,fetched_at)
                        VALUES (?,?,?,?,?,?,?)
                        ON CONFLICT (symbol,date) DO UPDATE SET
                          close=EXCLUDED.close, traded_qty=EXCLUDED.traded_qty,
                          deliv_qty=EXCLUDED.deliv_qty, deliv_pct=EXCLUDED.deliv_pct,
                          fetched_at=EXCLUDED.fetched_at
                    """), (r["symbol"], r["date"], r.get("close"),
                           r.get("traded_qty"), r.get("deliv_qty"),
                           r.get("deliv_pct"), now))
                else:
                    cur.execute("""
                        INSERT INTO nse_delivery_daily
                          (symbol,date,close,traded_qty,deliv_qty,deliv_pct,fetched_at)
                        VALUES (?,?,?,?,?,?,?)
                        ON CONFLICT(symbol,date) DO UPDATE SET
                          close=excluded.close, traded_qty=excluded.traded_qty,
                          deliv_qty=excluded.deliv_qty, deliv_pct=excluded.deliv_pct,
                          fetched_at=excluded.fetched_at
                    """, (r["symbol"], r["date"], r.get("close"),
                          r.get("traded_qty"), r.get("deliv_qty"),
                          r.get("deliv_pct"), now))
                n += 1
            except Exception as e:
                _log.debug("_persist row failed for %s %s: %s",
                           r.get("symbol"), r.get("date"), e)
        conn.commit()
    return n


# ─────────────────────────────────────────────────────────────────────────────
# Fetcher
# ─────────────────────────────────────────────────────────────────────────────

def _bhavcopy_url(date: _dt.date) -> str:
    return (f"https://nsearchives.nseindia.com/products/content/"
            f"sec_bhavdata_full_{date.strftime('%d%m%Y')}.csv")


def _parse_bhavcopy(csv_text: str, filter_series: Optional[set] = None) -> List[Dict]:
    """
    Parse the bhavcopy CSV. Guardrail §14: named ValueError on schema drift.

    filter_series limits to EQ + BE by default (regular delivery series).
    """
    if not csv_text or not csv_text.strip():
        raise ValueError("bhavcopy: empty response body")

    reader = csv.DictReader(io.StringIO(csv_text))
    fieldnames = {(fn or "").strip() for fn in (reader.fieldnames or [])}
    missing = _REQUIRED_COLS - fieldnames
    if missing:
        raise ValueError(
            f"NSE bhavcopy schema drift: required columns missing {sorted(missing)}. "
            f"Provider may have renamed fields. Got columns: {sorted(fieldnames)[:12]}"
        )

    series_filter = filter_series or {"EQ", "BE"}
    out: List[Dict] = []
    for raw in reader:
        # Every field the DictReader hands back is padded with spaces in this
        # CSV — strip once at the boundary.
        row = {(k or "").strip(): (v or "").strip() for k, v in raw.items()}
        series = row.get("SERIES", "").upper()
        if series not in series_filter:
            continue

        # DELIV_PER can be blank or literal '-' on the first day a symbol
        # trades in a series or on some derivative rows; treat both as missing.
        deliv_pct_raw = row.get("DELIV_PER", "")
        if deliv_pct_raw in {"", "-"}:
            continue
        try:
            deliv_pct = float(deliv_pct_raw)
        except ValueError:
            continue

        # DATE1 comes as "DD-MMM-YYYY" — normalise to ISO for consistent
        # ordering with the rest of the store.
        try:
            date_iso = _dt.datetime.strptime(row["DATE1"], "%d-%b-%Y").date().isoformat()
        except ValueError as e:
            raise ValueError(
                f"NSE bhavcopy schema drift: DATE1 not in DD-MMM-YYYY format "
                f"(got {row.get('DATE1')!r}): {e}"
            )

        def _f(k: str) -> Optional[float]:
            v = row.get(k, "")
            if v in {"", "-"}:
                return None
            try:
                return float(v)
            except ValueError:
                return None

        out.append({
            "symbol":     row["SYMBOL"].upper(),
            "date":       date_iso,
            "close":      _f("CLOSE_PRICE"),
            "traded_qty": _f("TTL_TRD_QNTY"),
            "deliv_qty":  _f("DELIV_QTY"),
            "deliv_pct":  deliv_pct,
        })

    # Guardrail §15: silent-empty is worse than a crash. Warn loudly.
    if not out:
        _log.warning(
            "bhavcopy: parsed 0 rows despite required columns being present — "
            "series filter %s may not have matched any row, or all DELIV_PER "
            "values were blank. Sample field names: %s",
            sorted(series_filter), sorted(fieldnames)[:12],
        )
    return out


def _fetch_bhavcopy(date: _dt.date) -> str:
    """Fetch raw bhavcopy CSV for the given date. Named ValueError on failure."""
    url = _bhavcopy_url(date)
    headers = {
        "User-Agent": _UA,
        "Accept": "text/csv,application/csv,*/*",
        "Referer": "https://www.nseindia.com/",
    }
    r = requests.get(url, headers=headers, timeout=_TIMEOUT)
    if r.status_code == 404:
        raise ValueError(f"bhavcopy not available for {date.isoformat()} (404). "
                         f"Likely a market holiday or not yet published.")
    r.raise_for_status()
    text = r.text or ""
    if text.lstrip().startswith("<"):
        raise ValueError(
            f"NSE returned HTML (not CSV) for {url} — probable rate-limit or "
            f"WAF challenge. Body starts: {text[:120]!r}"
        )
    return text


def fetch_and_persist_today(as_of: Optional[_dt.date] = None) -> int:
    """
    Fetch and persist today's bhavcopy. Returns rows written.

    Best-effort: caller should try_the_previous trading day when today's file
    is not yet published (typical before ~7 PM IST).
    """
    date = as_of or _dt.date.today()
    try:
        csv_text = _fetch_bhavcopy(date)
        rows = _parse_bhavcopy(csv_text)
        written = _persist(rows)
        _log.info("nse_delivery: persisted %d rows for %s", written, date.isoformat())
        _record_last_diagnostic(
            ok=True, at=_dt.datetime.now().isoformat(),
            reason=f"persisted {written} rows for {date.isoformat()}",
        )
        return written
    except Exception as e:
        _record_last_diagnostic(
            ok=False, at=_dt.datetime.now().isoformat(),
            reason=f"{type(e).__name__}: {e}",
        )
        raise


# FIX DIAG-DELIVERY (Task 2.3 follow-up C): expose a last-diagnostic getter
# for data_health.py's Command Centre panel. Same shape as other providers.
_last_diagnostic: dict = {}


def _record_last_diagnostic(*, ok: bool, at: str, reason: str = "") -> None:
    prior_warns = int(_last_diagnostic.get("warnings", 0))
    _last_diagnostic.update({
        "ok": ok, "at": at, "reason": reason,
        "warnings": prior_warns + (0 if ok else 1),
    })


def get_last_diagnostic() -> dict:
    """Return the diagnostic recorded on the most recent fetch_and_persist_today
    call. Empty dict if the fetcher hasn't been exercised this process."""
    return dict(_last_diagnostic)


# ─────────────────────────────────────────────────────────────────────────────
# Read API used by analysis.score
# ─────────────────────────────────────────────────────────────────────────────

def load_symbol_history(symbol: str, days: int = 60) -> pd.DataFrame:
    """Return the last `days` rows for one symbol, newest first."""
    ensure_schema()
    sym = (symbol or "").upper().replace(".NS", "")
    try:
        with _store._get_conn() as conn:
            return pd.read_sql_query(_store._q("""
                SELECT date, close, deliv_pct, traded_qty, deliv_qty
                FROM nse_delivery_daily
                WHERE symbol = ?
                ORDER BY date DESC LIMIT ?
            """), conn, params=(sym, int(days)))
    except Exception as e:
        _log.warning("load_symbol_history failed for %s: %s", sym, e)
        return pd.DataFrame()


def get_snapshot(symbol: str, lookback: int = 60) -> Optional[Dict]:
    """
    Return the delivery snapshot for one symbol, or None when we have too few
    rows to say anything meaningful. Score consumer falls back to legacy
    volume-only mode when this returns None.
    """
    hist = load_symbol_history(symbol, days=lookback)
    if hist is None or hist.empty or len(hist) < 5:
        return None
    pct = pd.to_numeric(hist["deliv_pct"], errors="coerce").dropna()
    if len(pct) < 5:
        return None
    today = float(pct.iloc[0])
    mean  = float(pct.mean())
    std   = float(pct.std())
    return {
        "today":  round(today, 2),
        "mean":   round(mean, 2),
        "std":    round(std, 2),
        "n":      int(len(pct)),
        # zscore is None when std=0 (pathological, but avoid ZeroDivisionError)
        "zscore": round((today - mean) / std, 2) if std > 0 else None,
    }
