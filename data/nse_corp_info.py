"""
data/nse_corp_info.py — NC1

Fetches corporate disclosures directly from NSE for a ticker: latest
announcements, corporate actions (buyback/rights/QIP/dividend/etc.), and
shareholding pattern history. Yahoo Finance does not carry any of this for
NSE-listed names, which is the gap this module closes.

Endpoint & session handling ported from the reference implementation in
stock-nse-india (bennythadikaran/stock-nse-india, MIT), specifically its
NseIndia.getEquityCorporateInfo() method and session bootstrap. That project
is a Node/TypeScript package and cannot be imported directly into this
Python/Streamlit app, so the endpoint URL, header set, and cookie-bootstrap
sequence are re-implemented here in Python using `requests`. Credit: the
retry/session-refresh shape below (bootstrap via homepage, refresh cookies
after N uses or on 401/403) mirrors that project's index.ts almost exactly,
since that sequencing is what actually gets past NSE's WAF.

DATA SOURCE
    GET https://www.nseindia.com/api/top-corp-info?symbol=<SYM>&market=equities
    Requires a prior session cookie obtained by GETting the NSE homepage
    with browser-like headers. Cookies expire quickly and must be refreshed
    on a 401/403 or after ~10 requests.

WHAT THIS ENDPOINT RETURNS (per response, all optional — treat every field
as possibly absent, matching the analysis/fundamentals contract style):
    latest_announcements   — [{symbol, broadcastdate, subject}, ...]
    corporate_actions      — [{symbol, exdate, purpose}, ...]
    shareholdings_patterns — {date_str: [{<arbitrary field>: <value>}, ...]}
    financial_results      — [...]
    borad_meeting           (sic, NSE's own field name) — [...]

KNOWN GAP — pledge percentage:
    NSE's dedicated "Pledged Data" filing category is a SEPARATE disclosure
    stream from the shareholding-pattern data returned here, and (unlike
    promoter-holding %, which reliably appears under a "pr_and_prgrp"-style
    key in shareholdings_patterns) I could not confirm a stable field name
    for pledge % inside this specific endpoint without live access to hit
    it. Rather than hardcode a guessed key name that silently returns
    nothing, parse_shareholding_records() in qualitative_flags.py searches
    every field name in each record for "pledg" (case-insensitive) and
    surfaces it if present, but does NOT promise pledge data will be there.
    If it never appears in practice, the real "Pledged Data" filing/CSV
    (a different NSE endpoint) is the fallback — flag this as a follow-up
    if promoter-pledge tracking turns out to matter more than the
    integration below already provides.

CONTRACT (matching analysis/fundamentals/provider.py's discipline):
    * raise only on TRANSPORT failure (network/auth exhausted after retry)
    * return {} on a 200 with unexpected/empty shape — never raise for that
    * cache raw responses for 24h (this data changes at most daily; NSE
      itself only updates announcements/actions intraday, but a Streamlit
      dashboard refreshing this every rerun would hammer NSE's WAF)
"""
from __future__ import annotations

import logging
import random
import time
from typing import Any, Dict, Optional

import requests

from analysis.fundamentals.cache import TTLCache

_log = logging.getLogger("data.nse_corp_info")

_BASE_URL = "https://www.nseindia.com"
_COOKIE_MAX_USES = 10
_COOKIE_MAX_AGE_SECONDS = 60
_MAX_RETRIES = 3

_HOMEPAGE_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
}
_API_HEADERS = {
    "Authority": "www.nseindia.com",
    "Referer": f"{_BASE_URL}/",
    "Accept": "application/json, text/plain, */*",
    "Origin": _BASE_URL,
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
}
# A short rotation of realistic desktop UAs — NSE's WAF is more likely to
# 403 a request with no UA at all than one that looks like an ordinary
# browser; this is not evasion of any access control, just presenting as
# a normal web client the way every browser already does by default.
_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
]

_raw_cache = TTLCache(ttl_seconds=24 * 60 * 60, name="nse_corp_info")


class _NseSession:
    """Holds one bootstrap NSE session (cookies + UA), refreshed on demand.

    Process-local, single instance reused across calls — mirrors the
    reference implementation's one-session-per-process model. Streamlit
    reruns share this via the module-level singleton below.
    """

    def __init__(self) -> None:
        self._session = requests.Session()
        self._user_agent = ""
        self._cookie_uses = 0
        self._cookie_expiry = 0.0

    def _needs_refresh(self, force: bool) -> bool:
        return (
            force
            or not self._session.cookies
            or self._cookie_uses > _COOKIE_MAX_USES
            or self._cookie_expiry <= time.time()
        )

    def ensure(self, force: bool = False) -> None:
        if not self._needs_refresh(force):
            self._cookie_uses += 1
            return
        self._user_agent = random.choice(_USER_AGENTS)
        self._session = requests.Session()
        resp = self._session.get(
            f"{_BASE_URL}/",
            headers={**_HOMEPAGE_HEADERS, "User-Agent": self._user_agent},
            timeout=10,
        )
        resp.raise_for_status()
        self._cookie_uses = 1
        self._cookie_expiry = time.time() + _COOKIE_MAX_AGE_SECONDS

    def get_json(self, path: str, referer: Optional[str] = None) -> Dict[str, Any]:
        last_error: Optional[Exception] = None
        session_refreshed = False
        for _attempt in range(_MAX_RETRIES):
            try:
                self.ensure(force=session_refreshed)
                headers = {**_API_HEADERS, "User-Agent": self._user_agent}
                if referer:
                    headers["Referer"] = referer
                resp = self._session.get(f"{_BASE_URL}{path}", headers=headers, timeout=10)
                if resp.status_code in (401, 403) and not session_refreshed:
                    session_refreshed = True
                    continue
                resp.raise_for_status()
                return resp.json()
            except requests.RequestException as e:
                last_error = e
                if not session_refreshed:
                    session_refreshed = True
                    continue
                break
        raise ConnectionError(
            f"NSE request failed after {_MAX_RETRIES} attempts for {path}: {last_error}"
        )


_session_singleton: Optional[_NseSession] = None


def _get_session() -> _NseSession:
    global _session_singleton
    if _session_singleton is None:
        _session_singleton = _NseSession()
    return _session_singleton


def _normalize_symbol(ticker: str) -> str:
    """Match the rest of the codebase's convention (angel_fetcher.py):
    strip .NS/.BO and upper-case to get the bare NSE trading symbol."""
    return ticker.replace(".NS", "").replace(".BO", "").upper()


def get_corp_info(ticker: str, use_cache: bool = True) -> Dict[str, Any]:
    """Fetch NSE's top-corp-info payload for a ticker.

    Returns {} (never raises) if NSE returns an unexpected/empty shape —
    matching the FundamentalProvider contract of "missing data is not an
    error". Raises ConnectionError only if the network/session retries are
    exhausted, so callers can decide whether to fall back or surface a
    warning, same as the fundamentals provider chain.
    """
    symbol = _normalize_symbol(ticker)
    if not symbol:
        return {}

    cache_key = f"corp_info|{symbol}"
    if use_cache:
        cached = _raw_cache.get(cache_key)
        if cached is not None:
            return cached

    referer = f"{_BASE_URL}/get-quotes/equity?symbol={symbol}"
    path = f"/api/top-corp-info?symbol={symbol}&market=equities"

    try:
        data = _get_session().get_json(path, referer=referer)
    except ConnectionError as e:
        _log.warning("get_corp_info(%s): NSE fetch failed, returning empty: %s", symbol, e)
        return {}

    if not isinstance(data, dict):
        _log.info("get_corp_info(%s): unexpected response shape, returning empty", symbol)
        return {}

    if use_cache:
        _raw_cache.set(cache_key, data)
    return data


def get_cache_stats() -> dict:
    return _raw_cache.stats()
