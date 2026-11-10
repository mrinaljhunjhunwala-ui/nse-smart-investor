"""data/nse_filings_xbrl.py — latest annual results XBRL from NSE, parsed and stored.

NSE lists every financial-results filing for a symbol at
  /api/corporates-financial-results?index=equities&symbol=<SYM>&period=Annual
and each row links the XBRL instance (nsearchives.nseindia.com). We take the
newest audited annual filing (consolidated preferred, standalone otherwise),
parse it with analysis.fundamentals.xbrl_filing and store it as the
"exchange" filing source. Same browser-like session as nse_corp_info, because
NSE's WAF stalls non-browser agents. Never raises: returns a status dict.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

_log = logging.getLogger("data.nse_filings_xbrl")
_BASE = "https://www.nseindia.com"


def _xbrl_url(row: Dict[str, Any]) -> Optional[str]:
    for k, v in row.items():
        if "xbrl" in str(k).lower() and isinstance(v, str) and v.startswith("http") \
                and v.lower().endswith((".xml", ".xbrl")):
            return v
    return None


def _rank(row: Dict[str, Any]) -> tuple:
    """Newest first; audited and consolidated preferred on the same date."""
    txt = " ".join(str(row.get(k, "")) for k in ("consolidated", "audited", "period", "cumulative")).lower()
    to_date = str(row.get("toDate") or row.get("periodEnd") or row.get("filingDate") or "")
    return ("non-consolidated" not in txt and "consolidated" in txt,
            "un-audited" not in txt and "unaudited" not in txt, _sortable(to_date))


def _sortable(d: str) -> str:
    """'31-Mar-2026' / '2026-03-31' -> '2026-03-31' for ordering."""
    import datetime as _dt
    for fmt in ("%d-%b-%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            return _dt.datetime.strptime(d.strip()[:11], fmt).date().isoformat()
        except ValueError:
            continue
    return ""


def pick_latest_annual(rows: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """The filing row to use, or None. Pure — exercised by tests."""
    usable = [r for r in rows or [] if isinstance(r, dict) and _xbrl_url(r)]
    if not usable:
        return None
    newest = max(_sortable(str(r.get("toDate") or "")) for r in usable)
    same = [r for r in usable if _sortable(str(r.get("toDate") or "")) == newest] or usable
    return max(same, key=_rank)


def fetch_exchange_filing(symbol: str) -> Dict[str, Any]:
    """Fetch, parse and store the latest annual results XBRL for `symbol`.

    Returns {"ok": bool, "message": str, "record": dict | None, "reason": str}.
    reason: "saved" | "transport" (NSE unreachable / blocked) | "no_filing" | "parse"."""
    from analysis.fundamentals.providers.filing_fundamentals import save_filing
    from analysis.fundamentals.xbrl_filing import parse_xbrl
    from data.nse_corp_info import _ensure_session

    sym = str(symbol).upper().replace(".NS", "").replace(".BO", "").strip()
    try:
        session = _ensure_session()
        session.get(_BASE, timeout=10)                       # cookie warm-up
        resp = session.get(f"{_BASE}/api/corporates-financial-results",
                           params={"index": "equities", "symbol": sym, "period": "Annual"},
                           timeout=15)
        resp.raise_for_status()
        rows = resp.json()
    except Exception as e:
        _log.warning("NSE results list failed for %s: %s", sym, e)
        return {"ok": False, "message": f"NSE did not return the filings list ({type(e).__name__}). "
                                        "NSE often blocks cloud servers; try again later or upload "
                                        "the filing instead.", "record": None, "reason": "transport"}
    rows = rows.get("data", rows) if isinstance(rows, dict) else rows
    row = pick_latest_annual(rows if isinstance(rows, list) else [])
    if row is None:
        return {"ok": False, "message": f"No annual results XBRL listed on NSE for {sym}.", "record": None,
                "reason": "no_filing"}
    url = _xbrl_url(row)
    try:
        x = session.get(url, timeout=30)
        x.raise_for_status()
        parsed = parse_xbrl(x.content)
        rec = save_filing("exchange", sym, parsed, file_name=url.rsplit("/", 1)[-1])
    except Exception as e:
        _log.warning("NSE XBRL fetch/parse failed for %s (%s): %s", sym, url, e)
        return {"ok": False, "message": f"Could not read the NSE filing ({type(e).__name__}: {e}).",
                "record": None, "reason": "parse"}
    latest = rec["periods"][0]["period_end"]
    return {"ok": True, "record": rec, "reason": "saved",
            "message": f"Saved NSE annual filing for {sym} (year ending {latest}, "
                       f"{len(rec['periods'])} year(s) on record)."}
