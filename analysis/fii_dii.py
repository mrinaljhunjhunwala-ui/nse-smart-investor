"""
analysis/fii_dii.py — FII / DII cash-market flow tracker.

WHY THIS MATTERS
────────────────
Foreign Institutional Investors (FIIs) and Domestic Institutional Investors
(DIIs) are the biggest single drivers of Nifty direction on any given day.
The daily cash-market net-buy/sell numbers correlate strongly with next-day
Nifty moves:

  * FII net-sell + DII net-buy = the classic "domestic-supported dip" — a
    tradeable pullback, not a trend break.
  * FII net-sell + DII net-sell = distribution; usually precedes weakness.
  * FII net-buy + DII net-buy = broad participation; a persistent rally.

WHERE THE DATA COMES FROM (all FREE)
────────────────────────────────────
Two sources, tried in order:

  1. NSE India `/api/fiidiiTradeReact` — official, current-day + prior day.
     Cloud IPs often blocked (403 / rate-limit) so this is only tried when
     we're not already sitting on a fresh cache row for today.
  2. Moneycontrol `stocks/marketstats/fii_dii_activity/index.php` — HTML
     table scrape (requires beautifulsoup4, already installed for the
     Screener fundamentals provider). Historical coverage is deep.

Everything successfully fetched is persisted to the same DB trade_store
manages (SQLite/Postgres), one row per date. On a fetch failure we surface
"last-known" data rather than an empty page — the trend chart continues
to render, and a status banner explains the freshness.
"""
from __future__ import annotations

import datetime as _dt
import logging
import re
from typing import Dict, List, Optional

import pandas as pd
import requests

import trade_store as _store

_log = logging.getLogger("analysis.fii_dii")

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/122.0 Safari/537.36")
_TIMEOUT = 12

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
            CREATE TABLE IF NOT EXISTS fii_dii_daily (
                date         TEXT PRIMARY KEY,
                fii_buy      {real},
                fii_sell     {real},
                fii_net      {real},
                dii_buy      {real},
                dii_sell     {real},
                dii_net      {real},
                source       TEXT,
                fetched_at   TEXT
            )
        """)
        conn.commit()
    _schema_ready_for = key


def _persist(rows: List[Dict], source: str) -> int:
    """Upsert rows into fii_dii_daily. Returns number of rows written."""
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
                        INSERT INTO fii_dii_daily
                          (date,fii_buy,fii_sell,fii_net,dii_buy,dii_sell,dii_net,source,fetched_at)
                        VALUES (?,?,?,?,?,?,?,?,?)
                        ON CONFLICT (date) DO UPDATE SET
                          fii_buy=EXCLUDED.fii_buy, fii_sell=EXCLUDED.fii_sell, fii_net=EXCLUDED.fii_net,
                          dii_buy=EXCLUDED.dii_buy, dii_sell=EXCLUDED.dii_sell, dii_net=EXCLUDED.dii_net,
                          source=EXCLUDED.source,   fetched_at=EXCLUDED.fetched_at
                    """), (r["date"], r.get("fii_buy"), r.get("fii_sell"), r.get("fii_net"),
                           r.get("dii_buy"), r.get("dii_sell"), r.get("dii_net"), source, now))
                else:
                    cur.execute("""
                        INSERT INTO fii_dii_daily
                          (date,fii_buy,fii_sell,fii_net,dii_buy,dii_sell,dii_net,source,fetched_at)
                        VALUES (?,?,?,?,?,?,?,?,?)
                        ON CONFLICT(date) DO UPDATE SET
                          fii_buy=excluded.fii_buy, fii_sell=excluded.fii_sell, fii_net=excluded.fii_net,
                          dii_buy=excluded.dii_buy, dii_sell=excluded.dii_sell, dii_net=excluded.dii_net,
                          source=excluded.source,   fetched_at=excluded.fetched_at
                    """, (r["date"], r.get("fii_buy"), r.get("fii_sell"), r.get("fii_net"),
                          r.get("dii_buy"), r.get("dii_sell"), r.get("dii_net"), source, now))
                n += 1
            except Exception as e:
                _log.debug("_persist row failed for %s: %s", r.get("date"), e)
        conn.commit()
    return n


def load_history(days: int = 90) -> pd.DataFrame:
    ensure_schema()
    try:
        with _store._get_conn() as conn:
            return pd.read_sql_query(_store._q("""
                SELECT * FROM fii_dii_daily
                ORDER BY date DESC LIMIT ?
            """), conn, params=(int(days),))
    except Exception as e:
        _log.warning("load_history failed: %s", e)
        return pd.DataFrame()


# ─────────────────────────────────────────────────────────────────────────────
# Fetchers
# ─────────────────────────────────────────────────────────────────────────────

def _parse_num(txt: str) -> Optional[float]:
    if txt is None:
        return None
    s = str(txt).strip().replace(",", "").replace("–", "-").replace("−", "-")
    if not s or s in {"-", "--"}:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _fetch_nse() -> List[Dict]:
    """Primary source: NSE's own JSON. Often 403 from cloud IPs — that's fine."""
    session = requests.Session()
    session.headers.update({
        "User-Agent": _UA, "Accept": "application/json",
        "Referer": "https://www.nseindia.com/",
    })
    try:
        # Prime cookie
        session.get("https://www.nseindia.com/", timeout=_TIMEOUT)
        r = session.get("https://www.nseindia.com/api/fiidiiTradeReact",
                        timeout=_TIMEOUT)
        if r.status_code != 200:
            _log.info("NSE fii/dii returned %s — falling back to moneycontrol", r.status_code)
            return []
        payload = r.json()
        rows: List[Dict] = []
        # payload is a list of {"category":"FII/FPI *","date":"04-Sep-2026",
        # "buyValue":"12345.67","sellValue":"11111.11","netValue":"1234.56"}
        latest: Dict[str, Dict] = {}
        for entry in payload:
            cat = str(entry.get("category", "")).upper()
            date_raw = entry.get("date", "")
            try:
                d = _dt.datetime.strptime(date_raw, "%d-%b-%Y").date().isoformat()
            except Exception:
                continue
            side = "fii" if "FII" in cat or "FPI" in cat else ("dii" if "DII" in cat else None)
            if not side:
                continue
            row = latest.setdefault(d, {"date": d})
            row[f"{side}_buy"]  = _parse_num(entry.get("buyValue"))
            row[f"{side}_sell"] = _parse_num(entry.get("sellValue"))
            row[f"{side}_net"]  = _parse_num(entry.get("netValue"))
        rows = list(latest.values())
        return rows
    except Exception as e:
        _log.info("NSE fii/dii fetch failed: %s: %s", type(e).__name__, e)
        return []


_MC_URL = "https://www.moneycontrol.com/stocks/marketstats/fii_dii_activity/index.php"


def _fetch_moneycontrol() -> List[Dict]:
    """Fallback: scrape moneycontrol's public FII/DII activity table."""
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        _log.warning("beautifulsoup4 not available — moneycontrol scraper disabled")
        return []
    try:
        r = requests.get(_MC_URL, headers={"User-Agent": _UA}, timeout=_TIMEOUT)
        if r.status_code != 200:
            _log.info("moneycontrol fii/dii returned %s", r.status_code)
            return []
        soup = BeautifulSoup(r.text, "lxml")
        # The page lays out two tables (FII cash, DII cash) with an id or
        # a caption containing "FII" / "DII". Find them by header text.
        tables = soup.find_all("table")
        parsed: Dict[str, Dict] = {}
        for tbl in tables:
            caption = (tbl.find("caption").get_text(" ", strip=True)
                       if tbl.find("caption") else "")
            heads = " ".join(th.get_text(" ", strip=True)
                             for th in tbl.find_all("th"))
            blob = (caption + " " + heads).upper()
            side = "fii" if "FII" in blob else ("dii" if "DII" in blob else None)
            if not side:
                continue
            for tr in tbl.find_all("tr"):
                cells = [td.get_text(strip=True) for td in tr.find_all("td")]
                if len(cells) < 4:
                    continue
                # Row shape: date, buy, sell, net
                try:
                    d = _dt.datetime.strptime(cells[0], "%d-%b-%Y").date().isoformat()
                except Exception:
                    continue
                row = parsed.setdefault(d, {"date": d})
                row[f"{side}_buy"]  = _parse_num(cells[1])
                row[f"{side}_sell"] = _parse_num(cells[2])
                row[f"{side}_net"]  = _parse_num(cells[3])
        return list(parsed.values())
    except Exception as e:
        _log.info("moneycontrol fii/dii scrape failed: %s: %s", type(e).__name__, e)
        return []


def refresh(*, force: bool = False) -> Dict:
    """
    Fetch latest FII/DII, persist, and report status. Idempotent — if today's
    data is already stored (and force=False) we skip the network entirely.

    Returns {"rows_written": n, "source": "nse|moneycontrol|cache", "latest_date": …}.
    """
    ensure_schema()
    today = _dt.date.today().isoformat()

    if not force:
        existing = load_history(days=3)
        if not existing.empty and existing["date"].iloc[0] >= today:
            return {"rows_written": 0, "source": "cache",
                    "latest_date": existing["date"].iloc[0]}

    rows = _fetch_nse()
    src = "nse"
    if not rows:
        rows = _fetch_moneycontrol()
        src = "moneycontrol"
    if not rows:
        latest = load_history(days=1)
        return {"rows_written": 0, "source": "unavailable",
                "latest_date": (latest["date"].iloc[0] if not latest.empty else None)}
    n = _persist(rows, source=src)
    latest = max((r["date"] for r in rows), default=None)
    return {"rows_written": n, "source": src, "latest_date": latest}
