"""
data/news_feed.py — QF4: recent news headlines via Google News RSS.

WHY THIS EXISTS
    analysis/qualitative_flags.py's auto-detectors (parse_announcement_flags,
    parse_corporate_action_flags, parse_shareholding_flags) only see what
    NSE's own top-corp-info payload contains — official filings and
    disclosures. A lot of decision-relevant "external factor" signal shows
    up in the press well before (or instead of) a formal NSE filing: a
    regulator show-cause notice reported by Moneycontrol, a credit-rating
    downgrade covered by ET, a brand JV announced in a press release. This
    module is the third independent input (alongside data/nse_corp_info.py
    and data/nse_rss_feeds.py) into that qualitative layer.

    Google News RSS search (news.google.com/rss/search) is used rather
    than scraping any single publisher directly — no login, no per-
    publisher WAF/robots concerns, and it aggregates across Moneycontrol,
    ET, Business Standard, etc. in one feed, with the originating
    publisher preserved in the <source> element of each item.

CACHING — per (ticker, query) pair, short TTL. News is much more time-
    sensitive than NSE's own corp-info payload (which changes on a filing
    cadence), so this uses a shorter TTL than nse_corp_info's 24h cache or
    nse_rss_feeds's 12h cache.

WHAT THIS DOES NOT DO
    * Does not raise on failure — same discipline as data/nse_corp_info.py
      and data/nse_rss_feeds.py; a broken feed must never block the rest
      of the qualitative-flags pipeline (see refresh_all_flags in
      analysis/qualitative_flags.py, which degrades each of its three
      sources independently).
    * Does not attempt sentiment analysis itself — that's
      analysis.qualitative_flags.parse_news_flags's job (conservative
      keyword classification). This module only fetches and normalizes
      headlines into a plain list of dicts.
"""
from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional
from urllib.parse import quote_plus

import requests

from analysis.fundamentals.cache import TTLCache

_log = logging.getLogger("data.news_feed")

_RSS_URL = "https://news.google.com/rss/search"
_TIMEOUT = 10
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/rss+xml, text/xml, */*",
}

# Short TTL — news moves faster than filings/disclosures.
_news_cache = TTLCache(ttl_seconds=2 * 60 * 60, name="news_feed")
_last_diagnostic: Dict[str, Dict[str, Any]] = {}


def get_last_diagnostic(ticker: str) -> Optional[Dict[str, Any]]:
    return _last_diagnostic.get(ticker)


def _build_query(company_name: Optional[str], ticker: str) -> str:
    """Prefer the company name (much better search precision than a bare
    NSE symbol, which is often ambiguous or unrecognized outside India),
    falling back to the ticker's symbol when no company name is known.
    "NSE" is appended in both cases to bias results toward Indian-market
    coverage of the company rather than an unrelated same-named entity.
    """
    symbol = ticker.replace(".NS", "").replace(".BO", "").strip()
    if company_name and company_name.strip():
        return f"{company_name.strip()} NSE"
    return f"{symbol} NSE"


def fetch_news(
    ticker: str,
    company_name: Optional[str] = None,
    use_cache: bool = True,
    max_items: int = 10,
) -> List[Dict[str, str]]:
    """Fetch recent news headlines for a ticker via Google News RSS search.

    Returns a list of {"title", "link", "pub_date", "source"} dicts, or []
    on any failure — never raises (mirrors data/nse_rss_feeds.py's
    fetch_feed and data/nse_corp_info.py's fetch discipline).
    """
    query = _build_query(company_name, ticker)
    cache_key = f"news|{ticker}|{query}"

    if use_cache:
        cached = _news_cache.get(cache_key)
        if cached is not None:
            return cached

    url = f"{_RSS_URL}?q={quote_plus(query)}&hl=en-IN&gl=IN&ceid=IN:en"
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=_TIMEOUT)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
    except requests.RequestException as e:
        status = getattr(getattr(e, "response", None), "status_code", None)
        _last_diagnostic[ticker] = {
            "ok": False, "status_code": status,
            "reason": f"news fetch failed: {type(e).__name__}: {e}",
        }
        _log.warning("fetch_news(%s): request failed: %s", ticker, e)
        return []
    except ET.ParseError as e:
        _last_diagnostic[ticker] = {
            "ok": False, "status_code": 200,
            "reason": f"got a response but couldn't parse RSS XML: {e}",
        }
        _log.warning("fetch_news(%s): RSS parse failed: %s", ticker, e)
        return []

    items: List[Dict[str, str]] = []
    for item in root.findall(".//item"):
        title = (item.findtext("title") or "").strip()
        if not title:
            continue
        items.append({
            "title": title,
            "link": item.findtext("link") or "",
            "pub_date": item.findtext("pubDate") or "",
            "source": (item.findtext("source") or "Google News").strip(),
        })
        if len(items) >= max_items:
            break

    _last_diagnostic[ticker] = {
        "ok": True, "status_code": 200, "reason": f"ok ({len(items)} items)",
    }
    if use_cache:
        _news_cache.set(cache_key, items)
    return items


def get_cache_stats() -> dict:
    return _news_cache.stats()
