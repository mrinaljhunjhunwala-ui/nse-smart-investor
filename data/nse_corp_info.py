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

KNOWN OPERATIONAL LIMITATION — read this before assuming a code bug:
    If flags never populate in a deployed environment (Streamlit Cloud,
    Render, Railway, any cloud VM) but a manual entry works fine, the most
    likely cause is NOT a parsing bug — it's that NSE's WAF is rejecting
    requests from that server's IP outright (401/403), regardless of how
    correct the headers/cookies/session flow are. This is the single most
    common cause of scraper failures for exactly this class of site when
    run from cloud/datacenter infrastructure (AWS/GCP/Azure ranges are
    blocked by default on many WAFs, NSE's included) — it is an IP-
    reputation problem, not a code problem, and no amount of header-tuning
    fixes it. Use get_last_diagnostic(ticker) to check: a status_code of
    401/403 confirms this; a timeout or None status means something else
    (DNS/egress firewall) is going on instead.

    Three real remedies, in order of practicality for a personal project:
      1. DECOUPLE fetch from serving. Run the fetch on a schedule from a
         non-cloud location (home broadband, a residential connection, or
         any machine that isn't a flagged datacenter IP) and write results
         into the shared kv store (Neon Postgres) via
         analysis.qualitative_flags.refresh_all_flags(). The deployed
         Streamlit app then only ever READS from kv_get — it never calls
         NSE directly, so it can't be blocked. This is the standard fix and
         costs nothing beyond running a small script periodically.
      2. Try BSE as a second, independent source. BSE (bseindia.com) has
         its own separate WAF — being blocked on NSE says nothing about
         whether BSE is also blocked from the same IP. The community-
         maintained `bse` package (PyPI: `bse`, github.com/BennyThadikaran/
         BseIndiaApi) exposes `.actions(scripcode)` for corporate actions,
         and most NSE-listed large-caps are also BSE-listed. Would need a
         parallel data/bse_corp_info.py fetcher and an NSE-symbol → BSE-
         scrip-code lookup table — not built here, flagging as an option.
      3. Paid residential-proxy service (ScraperAPI, ZenRows, BrightData,
         etc.) routes the request through a non-datacenter IP. Most
         reliable, but has an ongoing cost — probably overkill unless (1)
         turns out to be impractical for the deployment setup in use.
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
        last_status: Optional[int] = None
        session_refreshed = False
        for _attempt in range(_MAX_RETRIES):
            try:
                self.ensure(force=session_refreshed)
                headers = {**_API_HEADERS, "User-Agent": self._user_agent}
                if referer:
                    headers["Referer"] = referer
                resp = self._session.get(f"{_BASE_URL}{path}", headers=headers, timeout=10)
                last_status = resp.status_code
                if resp.status_code in (401, 403) and not session_refreshed:
                    session_refreshed = True
                    continue
                resp.raise_for_status()
                return resp.json()
            except requests.RequestException as e:
                last_error = e
                last_status = getattr(getattr(e, "response", None), "status_code", last_status)
                if not session_refreshed:
                    session_refreshed = True
                    continue
                break
        raise _NseFetchError(
            f"NSE request failed after {_MAX_RETRIES} attempts for {path}: {last_error}",
            status_code=last_status,
        )


class _NseFetchError(ConnectionError):
    """ConnectionError subclass that carries the last HTTP status seen, so
    callers/diagnostics can distinguish 'blocked' (401/403 — most often a
    cloud/datacenter IP block, see module docstring "KNOWN OPERATIONAL
    LIMITATION" below) from a plain timeout or DNS failure (status_code=None).
    """
    def __init__(self, message: str, status_code: Optional[int] = None) -> None:
        super().__init__(message)
        self.status_code = status_code


# ---------------------------------------------------------------------------
# Fetch diagnostics — last attempt per symbol, for surfacing in the UI.
# This does NOT retry or fix anything; it just makes failures visible instead
# of silently collapsing to "no flags", per the "no silent failures" rule
# this codebase applies everywhere else.
# ---------------------------------------------------------------------------
_last_diagnostic: Dict[str, Dict[str, Any]] = {}


def _classify(status_code: Optional[int], error: Optional[Exception]) -> str:
    if status_code in (401, 403):
        return (
            "blocked (401/403) — NSE most likely rejected this server's IP. "
            "This is overwhelmingly the #1 cause of NSE-scraper failures when "
            "hosted on cloud/datacenter infrastructure (AWS/GCP/Azure/Streamlit "
            "Cloud/Render/etc all fall in this bucket) — NSE's WAF filters "
            "known datacenter IP ranges regardless of headers/cookies being "
            "otherwise correct. See get_corp_info's module docstring for options."
        )
    if isinstance(error, requests.Timeout):
        return "timeout — NSE did not respond in time (transient, or the IP is being silently rate-limited)"
    if isinstance(error, requests.ConnectionError):
        return "connection error — could not reach nseindia.com at all (DNS/firewall/egress block)"
    if status_code and status_code >= 500:
        return f"NSE server error ({status_code}) — transient, likely not IP-related"
    if error is not None:
        return f"unexpected error: {type(error).__name__}: {error}"
    return "unknown"


def get_last_diagnostic(ticker: str) -> Optional[Dict[str, Any]]:
    """Returns {"ok": bool, "status_code": int|None, "reason": str, "at": iso}
    for the most recent fetch attempt for this ticker, or None if never
    attempted this process lifetime. UI-facing — see dashboard/shared/flags_ui.py.
    """
    return _last_diagnostic.get(_normalize_symbol(ticker))


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

    Returns {} (never raises) if NSE returns an unexpected/empty shape, or if
    the network/session retries are exhausted — matching the
    FundamentalProvider contract of "missing data is not an error", so a
    flags-panel failure never blocks the rest of the analysis page.

    Every attempt (success or failure) is recorded via get_last_diagnostic()
    so the UI can tell the difference between "NSE has nothing to say about
    this stock today" and "NSE blocked this request" — those look identical
    if you only check whether flags list is empty, and conflating them was
    the original problem (silent {} on failure, no way to tell why).
    """
    symbol = _normalize_symbol(ticker)
    now_iso = __import__("datetime").datetime.now().isoformat()
    if not symbol:
        return {}

    cache_key = f"corp_info|{symbol}"
    if use_cache:
        cached = _raw_cache.get(cache_key)
        if cached is not None:
            _last_diagnostic[symbol] = {
                "ok": True, "status_code": 200, "reason": "cached", "at": now_iso,
            }
            return cached

    referer = f"{_BASE_URL}/get-quotes/equity?symbol={symbol}"
    path = f"/api/top-corp-info?symbol={symbol}&market=equities"

    try:
        data = _get_session().get_json(path, referer=referer)
    except _NseFetchError as e:
        reason = _classify(e.status_code, e)
        _last_diagnostic[symbol] = {
            "ok": False, "status_code": e.status_code, "reason": reason, "at": now_iso,
        }
        _log.warning("get_corp_info(%s): NSE fetch failed (%s), returning empty", symbol, reason)
        return {}
    except ConnectionError as e:
        # Any other ConnectionError not raised as _NseFetchError (shouldn't
        # normally happen, but don't let an unclassified error crash the page).
        reason = _classify(None, e)
        _last_diagnostic[symbol] = {
            "ok": False, "status_code": None, "reason": reason, "at": now_iso,
        }
        _log.warning("get_corp_info(%s): NSE fetch failed (%s), returning empty", symbol, reason)
        return {}

    if not isinstance(data, dict):
        _last_diagnostic[symbol] = {
            "ok": False, "status_code": 200,
            "reason": "got a 200 but response shape was not a dict — NSE may "
                      "have changed this endpoint's schema",
            "at": now_iso,
        }
        _log.info("get_corp_info(%s): unexpected response shape, returning empty", symbol)
        return {}

    _last_diagnostic[symbol] = {"ok": True, "status_code": 200, "reason": "ok", "at": now_iso}
    if use_cache:
        _raw_cache.set(cache_key, data)
    return data


def get_cache_stats() -> dict:
    return _raw_cache.stats()
