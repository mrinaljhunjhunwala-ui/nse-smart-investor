"""
data/nse_fno_bhavcopy.py – NSE F&O bhavcopy Open Interest tracker.

Feeds the OI-regime sub-score (3 pts of 10) inside Recommendation 6's
Positioning pillar. See docs/POSITIONING_INTEGRATION_2026-09.md.

WHY
───
Change in total Open Interest paired with the direction of the spot price
gives the classical four-way OI regime classification:

  price ↑ + OI ↑ = LONG BUILDUP    (fresh longs on rising price)     bullish
  price ↑ + OI ↓ = SHORT COVERING  (weak bears closing on rally)     mildly bullish
  price ↓ + OI ↑ = SHORT BUILDUP   (fresh shorts on falling price)   bearish
  price ↓ + OI ↓ = LONG UNWINDING  (longs booking on the way down)   mildly bearish

We aggregate OpnIntrst across every contract (futures + all strikes + all
expiries) for a symbol on each trading day, then the score consumer combines
today's-vs-prev-day OI with the equity's day-over-day close.

WHERE THE DATA COMES FROM
─────────────────────────
NSE archives. The current stable filename is
`BhavCopy_NSE_FO_0_0_0_{YYYYMMDD}_F_0000.csv` under
`https://nsearchives.nseindia.com/content/fo/`. NSE has renamed this file
several times (older names include `fo{DDMMYYYY}bhav.csv.zip` and
`fo_bhavdata_full_{DDMMYYYY}.csv`); if the current URL 404s, check the
recent NSE circular and update `_bhavcopy_url` below.

PIPELINE
────────
Same operational shape as data/nse_delivery.py:
  scripts/fetch_nse_fno_bhavcopy.py --days N   backfills/refreshes
  data.nse_fno_bhavcopy.get_oi_snapshot(sym)   reads today vs prev OI
  analysis.score.score_stock                   consumes for OI regime sub-score

MUST RUN FROM RESIDENTIAL IP — NSE WAF blocks cloud ranges. Same
constraint as nse_delivery + qualitative_flags.
"""
from __future__ import annotations

import csv
import datetime as _dt
import io
import logging
import zipfile
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

import pandas as pd
import requests

import trade_store as _store

_log = logging.getLogger("data.nse_fno_bhavcopy")

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/122.0 Safari/537.36")
_TIMEOUT = 20

# Columns we REQUIRE from the F&O bhavcopy CSV. Guardrail §14: missing
# any of these raises a named ValueError so provider drift is loud.
# The current NSE schema uses these header names — see the module docstring
# for filename evolution history.
_REQUIRED_COLS = {"TckrSymb", "FinInstrmTp", "OpnIntrst"}

# Instrument-type codes we care about. STF/STO = stock futures/options;
# IDF/IDO = index futures/options (kept for future FII-deriv wiring).
_STOCK_INSTR_TYPES  = {"STF", "STO"}
_INDEX_INSTR_TYPES  = {"IDF", "IDO"}

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
            CREATE TABLE IF NOT EXISTS nse_fno_oi_daily (
                symbol       TEXT NOT NULL,
                date         TEXT NOT NULL,
                total_oi     {real},
                n_contracts  INTEGER,
                fetched_at   TEXT,
                PRIMARY KEY (symbol, date)
            )
        """)
        conn.commit()
    _schema_ready_for = key


def _persist(rows: List[Dict]) -> int:
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
                        INSERT INTO nse_fno_oi_daily
                          (symbol,date,total_oi,n_contracts,fetched_at)
                        VALUES (?,?,?,?,?)
                        ON CONFLICT (symbol,date) DO UPDATE SET
                          total_oi=EXCLUDED.total_oi,
                          n_contracts=EXCLUDED.n_contracts,
                          fetched_at=EXCLUDED.fetched_at
                    """), (r["symbol"], r["date"], r.get("total_oi"),
                           r.get("n_contracts"), now))
                else:
                    cur.execute("""
                        INSERT INTO nse_fno_oi_daily
                          (symbol,date,total_oi,n_contracts,fetched_at)
                        VALUES (?,?,?,?,?)
                        ON CONFLICT(symbol,date) DO UPDATE SET
                          total_oi=excluded.total_oi,
                          n_contracts=excluded.n_contracts,
                          fetched_at=excluded.fetched_at
                    """, (r["symbol"], r["date"], r.get("total_oi"),
                          r.get("n_contracts"), now))
                n += 1
            except Exception as e:
                _log.debug("_persist row failed for %s %s: %s",
                           r.get("symbol"), r.get("date"), e)
        conn.commit()
    return n


# ─────────────────────────────────────────────────────────────────────────────
# Fetcher / parser
# ─────────────────────────────────────────────────────────────────────────────

def _bhavcopy_url(date: _dt.date) -> str:
    """Current NSE F&O bhavcopy filename (verified 2026-09-04).

    Note: this is a .zip containing a single .csv, not a bare .csv.
    _fetch_bhavcopy unzips in memory before returning the CSV text.

    NSE has renamed this file several times. If it 404s across recent
    weekdays, check the latest NSE archives page and update. Legacy
    formats attempted historically:
      * .../BhavCopy_NSE_FO_0_0_0_{ymd}_F_0000.csv          (no .zip)
      * .../fo_bhavdata_full_{ddmmyyyy}.csv                 (retired)
      * .../fo{DDMMYYYY}bhav.csv.zip                         (pre-2024)
      * archives.nseindia.com/content/historical/DERIVATIVES/YYYY/MON/  (deep)
    """
    ymd = date.strftime("%Y%m%d")
    return (f"https://nsearchives.nseindia.com/content/fo/"
            f"BhavCopy_NSE_FO_0_0_0_{ymd}_F_0000.csv.zip")


def _parse_bhavcopy(csv_text: str, target_date: _dt.date) -> List[Dict]:
    """
    Parse the F&O bhavcopy, aggregating OpnIntrst per symbol across every
    contract (fut + all option strikes + all expiries).

    Returns rows shaped {symbol, date (ISO), total_oi, n_contracts}.
    Raises named ValueError on empty body or schema drift (Guardrail §14).
    """
    if not csv_text or not csv_text.strip():
        raise ValueError("fno bhavcopy: empty response body")

    reader = csv.DictReader(io.StringIO(csv_text))
    fieldnames = {(fn or "").strip() for fn in (reader.fieldnames or [])}
    missing = _REQUIRED_COLS - fieldnames
    if missing:
        raise ValueError(
            f"NSE F&O bhavcopy schema drift: required columns missing "
            f"{sorted(missing)}. Provider may have renamed fields. "
            f"Got columns: {sorted(fieldnames)[:12]}"
        )

    # Aggregate per (symbol) — sum OpnIntrst across every stock-derivative row
    agg_oi:    Dict[str, float] = defaultdict(float)
    agg_count: Dict[str, int]   = defaultdict(int)

    for raw in reader:
        row = {(k or "").strip(): (v or "").strip() for k, v in raw.items()}
        instr = row.get("FinInstrmTp", "").upper()
        if instr not in _STOCK_INSTR_TYPES:
            continue
        symbol = row.get("TckrSymb", "").upper()
        if not symbol:
            continue
        oi_raw = row.get("OpnIntrst", "")
        if oi_raw in {"", "-"}:
            continue
        try:
            oi = float(oi_raw)
        except ValueError:
            continue
        agg_oi[symbol]    += oi
        agg_count[symbol] += 1

    date_iso = target_date.isoformat()
    out = [
        {"symbol": s, "date": date_iso, "total_oi": agg_oi[s],
         "n_contracts": agg_count[s]}
        for s in sorted(agg_oi)
    ]

    if not out:
        # Guardrail §15: silent-empty is worse than a crash. Warn loudly.
        _log.warning(
            "fno bhavcopy: aggregated 0 stock-derivative rows for %s. "
            "FinInstrmTp filter %s may have missed the intended types. "
            "Sample fields: %s",
            date_iso, sorted(_STOCK_INSTR_TYPES), sorted(fieldnames)[:12],
        )
    return out


def _fetch_bhavcopy(date: _dt.date) -> str:
    url = _bhavcopy_url(date)
    headers = {
        "User-Agent": _UA,
        "Accept": "text/csv,application/csv,*/*",
        "Referer": "https://www.nseindia.com/",
    }
    r = requests.get(url, headers=headers, timeout=_TIMEOUT)
    if r.status_code == 404:
        raise ValueError(
            f"fno bhavcopy not available for {date.isoformat()} (404). "
            f"Likely a market holiday, not yet published, or NSE has renamed "
            f"the filename again — see _bhavcopy_url docstring."
        )
    r.raise_for_status()

    # FIX FNO-ZIP (2026-09-04): NSE serves this bhavcopy as a .zip
    # containing a single .csv. Older versions of this fetcher expected a
    # bare .csv and returned r.text, which was raw zip bytes decoded as
    # latin-1 — the parser then saw garbage and aggregated 0 rows.
    body = r.content or b""
    if body[:2] == b"PK":
        try:
            with zipfile.ZipFile(io.BytesIO(body)) as zf:
                names = [n for n in zf.namelist()
                         if n.lower().endswith(".csv")]
                if not names:
                    raise ValueError(
                        f"NSE fno bhavcopy zip for {date.isoformat()} contains "
                        f"no CSV entry (members: {zf.namelist()[:5]})"
                    )
                with zf.open(names[0]) as inner:
                    return inner.read().decode("utf-8", errors="replace")
        except zipfile.BadZipFile as e:
            raise ValueError(
                f"NSE fno bhavcopy for {date.isoformat()}: PK header but "
                f"bad zip: {e}"
            )
    # Non-zip response — sniff for CSV vs HTML challenge
    text = body.decode("utf-8", errors="replace")
    if text.lstrip().startswith("<"):
        raise ValueError(
            f"NSE returned HTML (not CSV/zip) for {url} — probable "
            f"rate-limit or WAF challenge. Body starts: {text[:120]!r}"
        )
    return text


def fetch_and_persist(date: Optional[_dt.date] = None) -> int:
    date = date or _dt.date.today()
    csv_text = _fetch_bhavcopy(date)
    rows = _parse_bhavcopy(csv_text, date)
    written = _persist(rows)
    _log.info("nse_fno_bhavcopy: persisted %d symbols for %s",
              written, date.isoformat())
    return written


# ─────────────────────────────────────────────────────────────────────────────
# Read API used by analysis.score
# ─────────────────────────────────────────────────────────────────────────────

def load_symbol_history(symbol: str, days: int = 5) -> pd.DataFrame:
    """Return the last `days` rows for one symbol, newest first."""
    ensure_schema()
    sym = (symbol or "").upper().replace(".NS", "")
    try:
        with _store._get_conn() as conn:
            return pd.read_sql_query(_store._q("""
                SELECT date, total_oi, n_contracts
                FROM nse_fno_oi_daily
                WHERE symbol = ?
                ORDER BY date DESC LIMIT ?
            """), conn, params=(sym, int(days)))
    except Exception as e:
        _log.warning("nse_fno_bhavcopy.load_symbol_history failed for %s: %s",
                     sym, e)
        return pd.DataFrame()


def get_oi_snapshot(symbol: str) -> Optional[Dict]:
    """Return {today_oi, prev_oi, pct_change} or None when we lack 2 rows."""
    hist = load_symbol_history(symbol, days=2)
    if hist is None or hist.empty or len(hist) < 2:
        return None
    today_oi = float(pd.to_numeric(hist["total_oi"].iloc[0], errors="coerce"))
    prev_oi  = float(pd.to_numeric(hist["total_oi"].iloc[1], errors="coerce"))
    if pd.isna(today_oi) or pd.isna(prev_oi) or prev_oi <= 0:
        return None
    return {
        "today_oi":   today_oi,
        "prev_oi":    prev_oi,
        "pct_change": round((today_oi - prev_oi) / prev_oi * 100, 2),
    }


def classify_oi_regime(oi_pct_change: float,
                       price_pct_change: float,
                       flat_threshold: float = 0.2) -> Optional[str]:
    """
    Classify into {long_buildup, short_covering, short_buildup, long_unwinding}
    or None when either signal is within its flat threshold (regime is
    inconclusive when everything's still).

    flat_threshold is in percent (0.2 = 0.2 pct). Applies to price only —
    the OI-change threshold is scaled to 5x flat_threshold since OI moves
    tend to be larger and less noisy than price at the daily frequency.
    """
    if oi_pct_change is None or price_pct_change is None:
        return None
    if abs(price_pct_change) < flat_threshold:
        return None
    if abs(oi_pct_change) < flat_threshold * 5:
        return None
    price_up = price_pct_change > 0
    oi_up    = oi_pct_change > 0
    if price_up and oi_up:      return "long_buildup"
    if price_up and not oi_up:  return "short_covering"
    if not price_up and oi_up:  return "short_buildup"
    return "long_unwinding"


def get_oi_regime_for_ticker(symbol: str,
                             price_pct_change: Optional[float]) -> Optional[str]:
    """
    Convenience wrapper for analysis.score — takes the symbol + today's
    equity price change % (which score already has) and returns the
    classified regime or None when data is insufficient.
    """
    if price_pct_change is None:
        return None
    snap = get_oi_snapshot(symbol)
    if snap is None:
        return None
    return classify_oi_regime(snap["pct_change"], price_pct_change)
