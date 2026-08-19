"""
data/nse_corp_info.py

Utilities to fetch corporate/company information from NSE and capture diagnostic
information (including HTTP status codes) into module-level diagnostics so tests
can assert on blocking status (e.g., status_code == 403).

Public:
 - get_corp_info(symbol) -> dict (empty dict on failure)
 - _last_diagnostics dict holding last failure info per symbol
"""

from __future__ import annotations
import re
from datetime import datetime
import logging
from typing import Optional, Dict, Any
import requests

_log = logging.getLogger("data.nse_corp_info")

_last_diagnostics: Dict[str, Dict[str, Any]] = {}


def _extract_status_code_from_exception(e: Exception) -> Optional[int]:
    """
    Extract an HTTP status code from common exception shapes:
      - requests.HTTPError with .response.status_code
      - exceptions that have .response or .status_code attributes
      - numeric status codes embedded in the textual message

    Returns status code int or None.
    """
    # requests exceptions often have .response
    resp = getattr(e, "response", None)
    if resp is not None:
        try:
            sc = getattr(resp, "status_code", None)
            if sc is not None:
                return int(sc)
        except Exception:
            pass

    # direct attribute (some libs attach status_code)
    sc_attr = getattr(e, "status_code", None)
    if sc_attr is not None:
        try:
            return int(sc_attr)
        except Exception:
            pass

    # Search text for 3-digit code
    m = re.search(r"\b(\d{3})\b", str(e))
    if m:
        try:
            return int(m.group(1))
        except Exception:
            pass

    return None


def get_corp_info(symbol: str) -> dict:
    """
    Fetch corporate/company info for a ticker symbol from NSE.

    On success returns a dict of parsed data (shape depends on NSE API).
    On failure returns {} and records diagnostics in _last_diagnostics[symbol]
    with keys: ok (bool), status_code (int|None), reason (str), at (iso timestamp).
    """
    symbol = (symbol or "").strip().upper()
    if not symbol:
        raise ValueError("symbol required")

    url = f"https://www.nseindia.com/api/corporate-info/{symbol}"
    headers = {
        "User-Agent": "nse-smart-investor/1.0 (+https://example.invalid)",
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://www.nseindia.com/",
    }

    try:
        resp = requests.get(url, headers=headers, timeout=10)
        # Raise for HTTP error to unify handling (requests raises HTTPError on raise_for_status)
        try:
            resp.raise_for_status()
        except requests.HTTPError as http_err:
            # Extract status code and record diagnostics, then return {}
            sc = _extract_status_code_from_exception(http_err)
            _last_diagnostics[symbol] = {
                "ok": False,
                "status_code": sc,
                "reason": str(http_err),
                "at": datetime.now().isoformat(),
            }
            _log.debug("nse_corp_info: request failed for %s: status=%s reason=%s", symbol, sc, http_err)
            return {}

        # Try parse response JSON defensively
        try:
            parsed = resp.json()
        except Exception:
            # Some endpoints return text: fall back to text parse attempt
            txt = resp.text
            try:
                import json as _json
                parsed = _json.loads(txt)
            except Exception:
                parsed = None

        if not parsed:
            _last_diagnostics[symbol] = {
                "ok": False,
                "status_code": getattr(resp, "status_code", None),
                "reason": "failed to parse response body",
                "at": datetime.now().isoformat(),
            }
            _log.debug("nse_corp_info: parsed empty for %s; text len=%d", symbol, len(resp.text or ""))
            return {}

        # On success, clear/update diagnostics
        _last_diagnostics[symbol] = {
            "ok": True,
            "status_code": getattr(resp, "status_code", None),
            "reason": "ok",
            "at": datetime.now().isoformat(),
        }
        return parsed if isinstance(parsed, dict) else {"result": parsed}

    except Exception as e:
        sc = _extract_status_code_from_exception(e)
        _last_diagnostics[symbol] = {
            "ok": False,
            "status_code": sc,
            "reason": str(e),
            "at": datetime.now().isoformat(),
        }
        _log.debug("nse_corp_info: fetch failed for %s: %s (extracted_status=%s)", symbol, e, sc)
        return {}
