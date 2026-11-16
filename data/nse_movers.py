"""data/nse_movers.py — today's gainers across the whole NSE market, for the movers radar.

Tier 1: NSE's own "Top gainers" feed (``/api/live-analysis-variations?index=gainers``), whose
``allSec`` group covers every listed security, so names outside the scan universe (e.g. a
recently listed retailer) are seen. Volume vs the 1-week average comes from NSE's
``/api/live-analysis-volume-gainers`` when it answers (enrichment only).
Tier 2 (fallback): the warm Top Picks scan's ``all_scored_snapshot`` (``return_1d``), which
covers the ~750-name scan universe only.

Never raises; returns [] when nothing usable is reachable. Parsing is tolerant of the field
names NSE has used for this feed (``perChange`` / ``pChange`` / ``net_price``, ``ltp`` /
``lastPrice``, ``turnover`` in ₹ lakh).
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Iterable, List, Optional

from data.nse_announcements import _cache_get, _cache_set, _guarded, _nse_json, num

_log = logging.getLogger("data.nse_movers")

GAINERS_PATH = "/api/live-analysis-variations"
VOLUME_PATH = "/api/live-analysis-volume-gainers"
_TTL_S = 4 * 60
_SERIES_OK = {"EQ", "BE", "BZ", "SM", "ST", ""}

_F_SYMBOL = ("symbol", "SYMBOL")
_F_PCT = ("perChange", "pChange", "net_price", "per_change")
_F_PRICE = ("ltp", "lastPrice", "last_price", "ltP")
_F_PREV = ("prev_price", "previousClose", "prevClose")
_F_TURN = ("turnover", "totalTradedValue", "trade_value")
_F_SERIES = ("series", "SERIES")


def _first(row: dict, keys: Iterable[str]) -> Any:
    for k in keys:
        if k in row and row[k] not in (None, "", "-"):
            return row[k]
    return None


def parse_gainers(payload: Any) -> List[dict]:
    """Rows of {symbol, pct, price, prev, turnover_cr, series} from the gainers payload.
    Prefers the ``allSec`` group; otherwise merges every group it finds."""
    if not isinstance(payload, dict):
        return []
    groups: List[Any] = []
    if isinstance(payload.get("allSec"), dict):
        groups = [payload["allSec"]]
    else:
        groups = [v for v in payload.values() if isinstance(v, dict)]
    out: Dict[str, dict] = {}
    for g in groups:
        for r in g.get("data") or []:
            if not isinstance(r, dict):
                continue
            sym = str(_first(r, _F_SYMBOL) or "").strip().upper()
            series = str(_first(r, _F_SERIES) or "").strip().upper()
            if not sym or series not in _SERIES_OK:
                continue
            price, prev = num(_first(r, _F_PRICE)), num(_first(r, _F_PREV))
            pct = num(_first(r, _F_PCT))
            if pct is None and price and prev:
                pct = (price / prev - 1) * 100
            if pct is None or price is None:
                continue
            turn = num(_first(r, _F_TURN))
            row = {"symbol": sym, "pct": round(pct, 2), "price": price, "prev": prev,
                   "turnover_cr": None if turn is None else round(turn / 100.0, 2),   # ₹ lakh -> crore
                   "series": series, "source": "NSE"}
            if sym not in out or row["pct"] > out[sym]["pct"]:
                out[sym] = row
    return sorted(out.values(), key=lambda r: -r["pct"])


def parse_volume_gainers(payload: Any) -> Dict[str, float]:
    """{SYMBOL: volume / 1-week average volume} from NSE's volume-gainers payload."""
    rows = payload.get("data") if isinstance(payload, dict) else payload
    out: Dict[str, float] = {}
    for r in rows or []:
        if not isinstance(r, dict):
            continue
        sym = str(_first(r, _F_SYMBOL) or "").strip().upper()
        ratio = num(_first(r, ("week1volChange", "week1AvgVolChange", "volChange")))
        if ratio is None:
            vol, avg = num(_first(r, ("volume", "totalTradedVolume"))), num(_first(r, ("week1AvgVolume",)))
            ratio = vol / avg if vol and avg else None
        if sym and ratio is not None and ratio > 0:
            out[sym] = round(ratio, 2)
    return out


def fetch_nse_gainers() -> List[dict]:
    hit = _cache_get("nse_gainers")
    if hit is not None:
        return hit
    rows = _guarded("nse_gainers", lambda: parse_gainers(_nse_json(GAINERS_PATH, {"index": "gainers"})) or None)
    if rows:
        _cache_set("nse_gainers", rows, ttl=_TTL_S)
    return rows or []


def fetch_volume_ratios() -> Dict[str, float]:
    hit = _cache_get("nse_volume_gainers")
    if hit is not None:
        return hit
    out = _guarded("nse_volume_gainers", lambda: parse_volume_gainers(_nse_json(VOLUME_PATH)) or None)
    if out:
        _cache_set("nse_volume_gainers", out, ttl=_TTL_S)
    return out or {}


def snapshot_gainers(snapshot: Optional[dict]) -> List[dict]:
    """Fallback rows from the warm scan's all_scored_snapshot (scan universe only)."""
    data = snapshot.get("data") if isinstance(snapshot, dict) else None
    out = []
    for k, v in (data or {}).items():
        if not isinstance(v, dict):
            continue
        pct, price = num(v.get("return_1d")), num(v.get("price"))
        sym = str(v.get("ticker") or k).upper().replace(".NS", "").strip()
        if sym and pct is not None and price:
            out.append({"symbol": sym, "pct": round(pct, 2), "price": price, "prev": None,
                        "turnover_cr": None, "series": "EQ", "source": "scan"})
    return sorted(out, key=lambda r: -r["pct"])


def fetch_gainers(snapshot: Optional[dict] = None) -> List[dict]:
    """NSE all-market gainers, enriched with volume ratios; scan snapshot when NSE is down."""
    rows = fetch_nse_gainers()
    if not rows:
        rows = snapshot_gainers(snapshot)
        if rows:
            _log.info("nse_movers: NSE gainers unavailable — using the scan snapshot (%d rows)", len(rows))
    if rows and rows[0].get("source") == "NSE":
        ratios = fetch_volume_ratios()
        for r in rows:
            if r["symbol"] in ratios:
                r["vol_ratio"] = ratios[r["symbol"]]
    return rows
