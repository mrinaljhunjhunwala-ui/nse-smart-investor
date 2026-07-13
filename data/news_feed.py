"""
data/news_feed.py — QF4: news-based qualitative signal (automatic, no manual
script required).

WHY THIS EXISTS
    data/nse_corp_info.py is frequently blocked from cloud-hosted deployments
    (NSE's WAF filters datacenter IP ranges — see that module's "KNOWN
    OPERATIONAL LIMITATION" docstring). Running a decoupled batch script to
    work around that (tools/refresh_flags_batch.py) requires the operator to
    run Python locally, which isn't always possible.

    This module is a second, INDEPENDENT qualitative signal that runs
    automatically inside the deployed app itself, with no separate script:
    Google News RSS. It has a completely different (much less aggressive)
    blocking profile than NSE — it's free, unauthenticated, and widely used
    from cloud-hosted hobby projects without issue. It cannot replace NSE's
    structured shareholding-pattern/corporate-action data (news headlines
    are unstructured text), but for regulatory/narrative/governance
    SIGNALS — the exact category that's hardest to get anywhere else — a
    recent headline is often the fastest real-world indicator available.

DATA SOURCE
    https://news.google.com/rss/search?q=<query>&hl=en-IN&gl=IN&ceid=IN:en
    Undocumented by Google (no official API, no SLA, no auth) but stable in
    practice for years. Returns up to ~100 items, deep-but-can-be-stale
    (median item age can be several days for a search feed — this is a
    trend/signal source, not a breaking-news wire).

WHAT THIS DOES NOT DO
    * Does not classify sentiment with NLP/LLM — same conservative keyword
      approach as analysis/qualitative_flags.py's NSE-announcement parsing,
      for the same reason: an unmatched headline should stay AMBER ("needs
      a human read"), not get a confident guess.
    * Does not replace NSE's structured governance data (pledge %, exact
      shareholding deltas) — those need a real number, not a headline.
    * Does not raise on failure — a broken news fetch must never block the
      rest of the qualitative-flags pipeline or an analysis page.
"""
from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional
from urllib.parse import quote_plus

import requests

from analysis.fundamentals.cache import TTLCache

_log = logging.getLogger("data.news_feed")

_RSS_BASE = "https://news.google.com/rss/search"
_TIMEOUT = 10
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/rss+xml, text/xml, */*",
}

_cache = TTLCache(ttl_seconds=6 * 60 * 60, name="news_feed")
_last_diagnostic: Dict[str, Dict[str, Any]] = {}


def _normalize_symbol(ticker: str) -> str:
    return ticker.replace(".NS", "").replace(".BO", "").upper()


def get_last_diagnostic(ticker: str) -> Optional[Dict[str, Any]]:
    """Same pattern as data/nse_corp_info.py's diagnostic — lets the UI
    distinguish 'no relevant news right now' from 'the fetch itself failed'.
    """
    return _last_diagnostic.get(_normalize_symbol(ticker))


def _build_query(company_name: Optional[str], ticker: str) -> str:
    """Prefer the real company name (from fundamentals data — more precise
    than a bare ticker, which can collide with unrelated tickers/words on
    other exchanges). Falls back to the bare NSE symbol if no name is known.
    Always scopes to India context to cut down on unrelated foreign-market
    noise for common-word company names.
    """
    symbol = _normalize_symbol(ticker)
    base = (company_name or symbol).strip()
    return f'{base} NSE India'


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text or "").strip()


def fetch_news(
    ticker: str, company_name: Optional[str] = None,
    max_items: int = 12, use_cache: bool = True,
) -> List[Dict[str, str]]:
    """Fetch recent news headlines for a ticker via Google News RSS.

    Returns a list of {"title", "link", "pub_date", "source"} dicts, most
    recent first (as Google orders them), or [] on any failure — never
    raises. Check get_last_diagnostic(ticker) to see why, if empty.
    """
    symbol = _normalize_symbol(ticker)
    if not symbol:
        return []

    query = _build_query(company_name, ticker)
    cache_key = f"news|{symbol}|{query}"
    if use_cache:
        cached = _cache.get(cache_key)
        if cached is not None:
            return cached

    url = f"{_RSS_BASE}?q={quote_plus(query)}&hl=en-IN&gl=IN&ceid=IN:en"

    try:
        resp = requests.get(url, headers=_HEADERS, timeout=_TIMEOUT)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
    except requests.RequestException as e:
        status = getattr(getattr(e, "response", None), "status_code", None)
        _last_diagnostic[symbol] = {
            "ok": False, "status_code": status,
            "reason": f"news fetch failed: {type(e).__name__}: {e}",
        }
        _log.warning("fetch_news(%s): request failed: %s", symbol, e)
        return []
    except ET.ParseError as e:
        _last_diagnostic[symbol] = {
            "ok": False, "status_code": 200,
            "reason": f"got a response but couldn't parse RSS XML: {e}",
        }
        _log.warning("fetch_news(%s): RSS parse failed: %s", symbol, e)
        return []

    items: List[Dict[str, str]] = []
    for item in root.findall(".//item")[:max_items]:
        title = _strip_html(item.findtext("title") or "")
        if not title:
            continue
        link = item.findtext("link") or ""
        pub_date = item.findtext("pubDate") or ""
        source_el = item.find("source")
        source = (source_el.text if source_el is not None else "") or "Google News"
        items.append({
            "title": title, "link": link, "pub_date": pub_date, "source": source,
        })

    _last_diagnostic[symbol] = {
        "ok": True, "status_code": 200,
        "reason": f"ok ({len(items)} items)" if items else "ok (no items returned)",
    }
    if use_cache:
        _cache.set(cache_key, items)
    return items


def get_cache_stats() -> dict:
    return _cache.stats()
