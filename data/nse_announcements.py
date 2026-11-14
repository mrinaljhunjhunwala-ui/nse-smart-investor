"""data/nse_announcements.py — market-wide corporate announcements, results filings, quarterly
figures and the pre-open snapshot, for the catalyst engine (analysis/catalysts.py).

Network lives here; parsing is split into small pure ``parse_*`` / ``normalise_*`` helpers so the
tests can feed fixture payloads. Contract for every public fetcher:
  * never raises — returns [] / {} / None on failure and logs once per (source, reason);
  * every request has a timeout (<= 15 s);
  * a per-source circuit breaker opens for 30 minutes after 3 consecutive failures;
  * a small in-process TTL cache (``clear_cache()`` for tests).

Session / cookie warm-up is shared with data/nse_corp_info.py (``_ensure_session``: Chrome UA,
Referer, homepage priming), because NSE's WAF stalls non-browser agents.

Payload shapes below were read from NSE's public pages but could NOT be verified from the
build sandbox (no network) — ``scripts/provider_canary.py`` probes them live. Every parser
codes against several candidate key names and skips rows it cannot parse.
"""
from __future__ import annotations

import datetime as _dt
import logging
import re
import threading
import time
from typing import Any, Callable, Dict, Iterable, List, Optional

_log = logging.getLogger("data.nse_announcements")

IST = _dt.timezone(_dt.timedelta(hours=5, minutes=30))
_BASE = "https://www.nseindia.com"
_TIMEOUT = 15
_WARM_EVERY_S = 600
_BREAKER_FAILS = 3
_BREAKER_OPEN_S = 30 * 60
_CACHE_TTL_S = 5 * 60
_QUARTERS_TTL_S = 6 * 60 * 60
_RSS_FILE = "Online_announcements.xml"      # nsearchives.nseindia.com/content/RSS/<file>
LAKH_PER_CRORE = 100.0

# ── breaker / cache / log-once ──────────────────────────────────────────────

_lock = threading.Lock()
_breaker: Dict[str, Dict[str, float]] = {}
_cache: Dict[str, tuple] = {}
_logged: set = set()
_last_warm = 0.0
_last_diag: Dict[str, Dict[str, Any]] = {}


def clear_cache() -> None:
    """Reset cache, breakers and log-once memory (tests)."""
    global _last_warm
    with _lock:
        _breaker.clear()
        _cache.clear()
        _logged.clear()
        _last_diag.clear()
        _last_warm = 0.0


def get_last_diagnostic(source: str) -> Optional[Dict[str, Any]]:
    return _last_diag.get(source)


def _log_once(source: str, reason: str) -> None:
    key = (source, reason[:60])
    if key not in _logged:
        _logged.add(key)
        _log.warning("nse_announcements[%s]: %s", source, reason)


def breaker_open(source: str, now: Optional[float] = None) -> bool:
    st = _breaker.get(source)
    return bool(st and st.get("until", 0) > (now or time.time()))


def _record(source: str, ok: bool, reason: str = "") -> None:
    with _lock:
        st = _breaker.setdefault(source, {"fails": 0, "until": 0.0})
        if ok:
            st["fails"], st["until"] = 0, 0.0
        else:
            st["fails"] += 1
            if st["fails"] >= _BREAKER_FAILS:
                st["until"] = time.time() + _BREAKER_OPEN_S
                st["fails"] = 0
                _log_once(source, f"circuit breaker open for 30 min after {_BREAKER_FAILS} failures ({reason})")
    _last_diag[source] = {"ok": ok, "reason": reason or "ok",
                          "at": _dt.datetime.now(IST).isoformat(timespec="seconds")}
    if not ok:
        _log_once(source, reason)


def _cache_get(key: str) -> Any:
    hit = _cache.get(key)
    if hit and hit[0] > time.time():
        return hit[1]
    return None


def _cache_set(key: str, value: Any, ttl: float = _CACHE_TTL_S) -> None:
    _cache[key] = (time.time() + ttl, value)


def _guarded(source: str, fn: Callable[[], Any]) -> Any:
    """Run one source call under its breaker; None on failure (recorded)."""
    if breaker_open(source):
        return None
    try:
        out = fn()
    except Exception as e:                                   # noqa: BLE001 — never raise to callers
        _record(source, False, f"{type(e).__name__}: {str(e)[:120]}")
        return None
    if out is None:
        _record(source, False, "no usable payload")
        return None
    _record(source, True)
    return out


# ── NSE transport ───────────────────────────────────────────────────────────

def _session():
    from data.nse_corp_info import _ensure_session
    return _ensure_session()


def _nse_json(path: str, params: Optional[dict] = None) -> Any:
    """GET an NSE API path with cookie warm-up; raises on HTTP / JSON failure (caught by _guarded)."""
    global _last_warm
    s = _session()
    if time.time() - _last_warm > _WARM_EVERY_S:
        try:
            s.get(_BASE + "/", timeout=10)
        except Exception:                                   # noqa: BLE001
            pass
        _last_warm = time.time()
    resp = s.get(_BASE + path, params=params or {}, timeout=_TIMEOUT)
    code = getattr(resp, "status_code", None)
    if code != 200:
        raise RuntimeError(f"HTTP {code} from {path}")
    return resp.json()


# ── parsing helpers (pure) ──────────────────────────────────────────────────

_DT_FORMATS = ("%d-%b-%Y %H:%M:%S", "%d-%b-%Y %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S",
               "%Y-%m-%dT%H:%M:%S.%f", "%d-%m-%Y %H:%M:%S", "%d-%m-%Y %H:%M", "%d/%m/%Y %H:%M:%S",
               "%d %b %Y %H:%M:%S", "%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S %Z",
               "%d-%b-%Y", "%d-%B-%Y", "%Y-%m-%d", "%d-%m-%Y", "%d %b %Y")


def parse_when(raw: Any) -> Optional[_dt.datetime]:
    """NSE / BSE / RSS timestamp -> IST-aware datetime, or None. Naive values are IST."""
    if raw is None or raw == "":
        return None
    if isinstance(raw, _dt.datetime):
        t = raw
    elif isinstance(raw, _dt.date):
        t = _dt.datetime.combine(raw, _dt.time(0, 0))
    else:
        s = re.sub(r"\s+", " ", str(raw)).strip()
        t = None
        for fmt in _DT_FORMATS:
            try:
                t = _dt.datetime.strptime(s, fmt)
                break
            except ValueError:
                continue
        if t is None:
            try:
                t = _dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
            except ValueError:
                return None
    return t.replace(tzinfo=IST) if t.tzinfo is None else t.astimezone(IST)


def parse_date(raw: Any) -> Optional[_dt.date]:
    t = parse_when(raw)                     # strptime month names are case-insensitive ("30-SEP-2026")
    return t.date() if t else None


def num(x: Any) -> Optional[float]:
    """'1,234.5' / '(45)' / '-' / 12 -> float or None."""
    if x is None or isinstance(x, bool):
        return None
    if isinstance(x, (int, float)):
        v = float(x)
    else:
        s = str(x).strip().replace(",", "").replace("₹", "").replace("−", "-")
        if s in {"", "-", "--", "NA", "N/A", "nan", "None", "null"}:
            return None
        if s.startswith("(") and s.endswith(")"):
            s = "-" + s[1:-1]
        try:
            v = float(s)
        except ValueError:
            return None
    return v if v == v and abs(v) != float("inf") else None


def _first(row: dict, keys: Iterable[str]) -> Any:
    for k in keys:
        v = row.get(k)
        if v not in (None, "", "-"):
            return v
    return None


def _rows(payload: Any, keys: Iterable[str] = ("data", "rows", "Table")) -> Optional[List[dict]]:
    if isinstance(payload, list):
        return [r for r in payload if isinstance(r, dict)]
    if isinstance(payload, dict):
        for k in keys:
            if isinstance(payload.get(k), list):
                return [r for r in payload[k] if isinstance(r, dict)]
    return None


def _sym(x: Any) -> str:
    return re.sub(r"\.(NS|BO)$", "", str(x or "").strip().upper())


_ANN_SYMBOL = ("symbol", "SYMBOL", "sm_symbol")
_ANN_CATEGORY = ("desc", "category", "subject", "CATEGORYNAME", "smIndustry")
_ANN_DETAIL = ("attchmntText", "details", "description", "HEADLINE")
_ANN_WHEN = ("an_dt", "sort_date", "dt", "broadcastdate", "exchdisstime", "DissemDT", "NEWS_DT")
_ANN_URL = ("attchmntFile", "attachment", "link", "url")


def normalise_nse_announcement(row: dict) -> Optional[dict]:
    if not isinstance(row, dict):
        return None
    sym = _sym(_first(row, _ANN_SYMBOL))
    when = parse_when(_first(row, _ANN_WHEN))
    if not sym or when is None:
        return None
    cat = str(_first(row, _ANN_CATEGORY) or "").strip()
    detail = str(_first(row, _ANN_DETAIL) or "").strip()
    return {"symbol": sym, "when": when, "category": cat, "headline": cat or detail[:120], "detail": detail,
            "url": str(_first(row, _ANN_URL) or ""), "source": "nse_api",
            "company": str(row.get("sm_name") or row.get("companyName") or "")}


_RSS_SYM = re.compile(r"/([A-Z0-9&\-]{2,20})_\d{6,}")


def normalise_rss_item(item: dict) -> Optional[dict]:
    """NSE Online_announcements RSS item. Symbol from the attachment link (…/SYMBOL_ddmmyyyy…pdf) or
    a 'Company - SYMBOL' / '(SYMBOL)' title; subject from 'SUBJECT:' in the description when present."""
    if not isinstance(item, dict):
        return None
    title, link, desc = (str(item.get(k) or "") for k in ("title", "link", "description"))
    m = _RSS_SYM.search(link)
    sym = m.group(1) if m else ""
    if not sym:
        m2 = re.search(r"\(([A-Z0-9&\-]{2,20})\)\s*$", title) or re.search(r"\s-\s([A-Z0-9&\-]{2,20})\s*$", title)
        sym = m2.group(1) if m2 else ""
    when = parse_when(item.get("pub_date"))
    if not sym or when is None:
        return None
    subj = re.search(r"SUBJECT\s*:\s*([^|]+)", desc, re.I)
    cat = subj.group(1).strip() if subj else ""
    return {"symbol": _sym(sym), "when": when, "category": cat, "headline": cat or desc[:120],
            "detail": desc, "url": link, "source": "nse_rss", "company": title}


_BSE_SYM = re.compile(r"/stock-share-price/[^/]+/([^/]+)/\d+/?", re.I)


def normalise_bse_row(row: dict) -> Optional[dict]:
    """BSE announcements row. BSE has no NSE symbol: taken from NSURL
    (…/stock-share-price/<name>/<bse-symbol>/<scripcode>/), which matches the NSE symbol for most names."""
    if not isinstance(row, dict):
        return None
    m = _BSE_SYM.search(str(row.get("NSURL") or ""))
    sym = _sym(m.group(1)) if m else ""
    when = parse_when(_first(row, ("DissemDT", "NEWS_DT", "News_submission_dt", "DT_TM")))
    if not sym or when is None:
        return None
    head = str(row.get("NEWSSUB") or row.get("HEADLINE") or "").strip()
    att = str(row.get("ATTACHMENTNAME") or "")
    return {"symbol": sym, "when": when, "category": str(row.get("CATEGORYNAME") or row.get("SUBCATNAME") or ""),
            "headline": head, "detail": str(row.get("MORE") or row.get("HEADLINE") or ""),
            "url": f"https://www.bseindia.com/xml-data/corpfiling/AttachLive/{att}" if att else "",
            "source": "bse", "company": str(row.get("SLONGNAME") or "")}


def _window(items: List[dict], since: _dt.datetime, until: Optional[_dt.datetime]) -> List[dict]:
    s = parse_when(since)
    u = parse_when(until) if until else None
    out = [i for i in items if i and (s is None or i["when"] >= s) and (u is None or i["when"] <= u)]
    seen, uniq = set(), []
    for i in sorted(out, key=lambda r: r["when"], reverse=True):
        k = (i["symbol"], i["when"].isoformat(), (i.get("headline") or "")[:40])
        if k not in seen:
            seen.add(k)
            uniq.append(i)
    return uniq


# ── 1. announcements ────────────────────────────────────────────────────────

def _nse_announcements(since: _dt.datetime, until: _dt.datetime) -> Optional[List[dict]]:
    payload = _nse_json("/api/corporate-announcements",
                        {"index": "equities", "from_date": since.strftime("%d-%m-%Y"),
                         "to_date": until.strftime("%d-%m-%Y")})
    rows = _rows(payload)
    if rows is None:
        raise ValueError(f"unexpected payload type {type(payload).__name__}")
    items = [x for x in (normalise_nse_announcement(r) for r in rows) if x]
    if rows and not items:
        raise ValueError(f"{len(rows)} rows but none parsed — schema drift? keys={sorted(rows[0])[:10]}")
    return items


def _rss_announcements() -> Optional[List[dict]]:
    from data.nse_rss_feeds import _fetch_one
    raw, diag = _fetch_one("announcements", _RSS_FILE)
    if not raw:
        raise RuntimeError(str(diag.get("reason") or "empty feed"))
    items = [x for x in (normalise_rss_item(r) for r in raw) if x]
    if not items:
        raise ValueError(f"{len(raw)} RSS items but no symbol/date parsed")
    return items


def _bse_announcements(since: _dt.datetime, until: _dt.datetime, max_pages: int = 5) -> Optional[List[dict]]:
    from data.bse_corp_info import _get_client
    client = _get_client()
    if client is None:
        raise RuntimeError("`bse` package unavailable")
    out: List[dict] = []
    for page in range(1, max_pages + 1):
        raw = client.announcements(page_no=page, from_date=since.replace(tzinfo=None),
                                   to_date=until.replace(tzinfo=None))
        rows = _rows(raw, ("Table",)) or []
        out.extend(x for x in (normalise_bse_row(r) for r in rows) if x)
        if len(rows) < 50:
            break
    return out


def fetch_announcements(since: _dt.datetime, until: Optional[_dt.datetime] = None) -> List[dict]:
    """Market-wide announcements in [since, until], newest first. Tiers: NSE API -> NSE RSS -> BSE.
    Rows: {symbol, when (IST), category, headline, detail, url, source}. [] on total failure."""
    try:
        s = parse_when(since)
        u = parse_when(until) if until else _dt.datetime.now(IST)
        if s is None or u is None:
            return []
        key = f"ann|{s:%Y%m%d%H%M}|{u:%Y%m%d%H%M}"
        hit = _cache_get(key)
        if hit is not None:
            return list(hit)
        for source, fn in (("nse_api", lambda: _nse_announcements(s, u)),
                           ("nse_rss", _rss_announcements),
                           ("bse", lambda: _bse_announcements(s, u))):
            items = _guarded(source, fn)
            if items is None:
                continue
            out = _window(items, s, u)
            _cache_set(key, out)
            return list(out)
        return []
    except Exception as e:                                  # noqa: BLE001
        _log_once("fetch_announcements", f"{type(e).__name__}: {e}")
        return []


# ── 2. results filed ────────────────────────────────────────────────────────

_RESULT_CAT = re.compile(r"financial result|outcome of board meeting", re.I)


def normalise_result_row(row: dict) -> Optional[dict]:
    if not isinstance(row, dict):
        return None
    sym = _sym(_first(row, ("symbol", "SYMBOL")))
    when = parse_when(_first(row, ("broadCastDate", "broadcastDate", "filingDate", "exchdisstime", "creation_Date",
                                   "re_create_dt")))
    if not sym or when is None:
        return None
    cons_txt = str(_first(row, ("consolidated", "resultType", "re_res_type")) or "").lower()
    xbrl = next((v for k, v in row.items() if "xbrl" in str(k).lower() and isinstance(v, str)
                 and v.startswith("http")), "")
    return {"symbol": sym, "when": when, "period_end": parse_date(_first(row, ("toDate", "periodEnd", "to_date"))),
            "consolidated": "consolidated" in cons_txt and "non" not in cons_txt, "xbrl": xbrl,
            "category": "Financial Results", "headline": "Financial results filed",
            "detail": str(_first(row, ("period", "relatingTo", "audited")) or ""), "source": "nse_results"}


def fetch_results_filed(since: _dt.datetime) -> List[dict]:
    """Companies that filed financial results since `since` (one row per symbol, newest first,
    consolidated preferred). NSE results list -> announcements feed (category match) fallback."""
    try:
        s = parse_when(since)
        if s is None:
            return []
        now = _dt.datetime.now(IST)
        key = f"res|{s:%Y%m%d%H%M}"
        hit = _cache_get(key)
        if hit is not None:
            return list(hit)

        def _nse():
            payload = _nse_json("/api/corporates-financial-results",
                                {"index": "equities", "period": "Quarterly",
                                 "from_date": s.strftime("%d-%m-%Y"), "to_date": now.strftime("%d-%m-%Y")})
            rows = _rows(payload)
            if rows is None:
                raise ValueError(f"unexpected payload type {type(payload).__name__}")
            items = [x for x in (normalise_result_row(r) for r in rows) if x]
            if rows and not items:
                raise ValueError(f"{len(rows)} rows but none parsed — keys={sorted(rows[0])[:10]}")
            return items

        items = _guarded("nse_results", _nse)
        if items is None:
            items = [dict(a, source=a["source"] + "+category") for a in fetch_announcements(s, now)
                     if _RESULT_CAT.search(f"{a.get('category')} {a.get('headline')}")
                     and re.search(r"result", f"{a.get('category')} {a.get('headline')} {a.get('detail')}", re.I)]
        items = [i for i in items if i["when"] >= s]
        best: Dict[str, dict] = {}
        for i in sorted(items, key=lambda r: (r["when"], bool(r.get("consolidated"))), reverse=True):
            cur = best.get(i["symbol"])
            if cur is None or (i.get("consolidated") and not cur.get("consolidated")
                               and i["when"].date() == cur["when"].date()):
                best[i["symbol"]] = i
        out = sorted(best.values(), key=lambda r: r["when"], reverse=True)
        _cache_set(key, out)
        return list(out)
    except Exception as e:                                  # noqa: BLE001
        _log_once("fetch_results_filed", f"{type(e).__name__}: {e}")
        return []


# ── 3. quarterly figures ────────────────────────────────────────────────────

_Q_DATE = ("re_to_dt", "toDate", "to_date", "period_end")
_Q_REV = ("re_net_sale", "re_total_inc", "re_tot_inc", "re_revenue", "netSales", "revenue")
_Q_TOTINC = ("re_total_inc", "re_tot_inc", "re_totinc", "totalIncome")
_Q_NP = ("re_con_pro_loss", "re_net_profit", "re_pro_loss_aft_tax", "re_proloss_ord_act", "netProfit")
_Q_EPS = ("re_basic_eps_for_cont_dic_opr", "re_basic_eps", "re_eps", "re_dil_eps", "eps")
_Q_PBT = ("re_pro_loss_bef_tax", "re_pbt", "profitBeforeTax")
_Q_OP = ("re_oper_profit", "re_operating_profit", "operatingProfit")


def _month_end(d: _dt.date) -> _dt.date:
    nxt = (d.replace(day=28) + _dt.timedelta(days=4))
    return nxt - _dt.timedelta(days=nxt.day)


def parse_results_comparison(payload: Any, unit: str = "lakh") -> List[dict]:
    """NSE results-comparision payload -> quarters newest first, in ₹ crore.

    ASSUMPTION (unverified offline): the list sits under ``resCmpData`` (else data / rows) and values
    are ₹ lakh, as on NSE's "Financial Results Comparison" page; ``unit='crore'`` skips the scaling."""
    rows = _rows(payload, ("resCmpData", "data", "rows")) or []
    div = LAKH_PER_CRORE if unit == "lakh" else 1.0
    by_period: Dict[_dt.date, dict] = {}
    for r in rows:
        d = parse_date(_first(r, _Q_DATE))
        np_ = num(_first(r, _Q_NP))
        rev = num(_first(r, _Q_REV))
        if d is None or (np_ is None and rev is None):
            continue
        cons_txt = str(_first(r, ("re_res_type", "consolidated", "re_seg_type")) or "").lower()
        cons = ("con" in cons_txt and "non" not in cons_txt and "standalone" not in cons_txt)
        rec = {"period_end": d, "revenue": None if rev is None else rev / div,
               "total_income": (lambda t: None if t is None else t / div)(num(_first(r, _Q_TOTINC))),
               "net_profit": None if np_ is None else np_ / div, "eps": num(_first(r, _Q_EPS)),
               "operating_profit": (lambda t: None if t is None else t / div)(num(_first(r, _Q_OP))),
               "profit_before_tax": (lambda t: None if t is None else t / div)(num(_first(r, _Q_PBT))),
               "consolidated": cons, "unit": "cr", "source": "nse_results_comparison", "raw_unit": unit}
        cur = by_period.get(d)
        if cur is None or (cons and not cur["consolidated"]):
            by_period[d] = rec
    return sorted(by_period.values(), key=lambda q: q["period_end"], reverse=True)[:8]


def _from_statements(stmts: Any, source: str, consolidated: Optional[bool]) -> List[dict]:
    out = []
    for st in stmts or []:
        per = getattr(st, "period", None)
        d = getattr(per, "period_end", None)
        if d is None:
            continue
        if source == "screener":
            d = _month_end(d)            # Screener columns are "Sep 2026" -> stored as day 28

        def cr(v):
            return None if v is None else float(v) / 1e7
        out.append({"period_end": d, "revenue": cr(getattr(st, "revenue", None)),
                    "net_profit": cr(getattr(st, "net_income", None)),
                    "eps": getattr(st, "eps_basic", None),
                    "operating_profit": cr(getattr(st, "operating_income", None)),
                    "consolidated": consolidated, "unit": "cr", "source": source})
    out = [q for q in out if q["net_profit"] is not None or q["revenue"] is not None]
    return sorted(out, key=lambda q: q["period_end"], reverse=True)[:8]


def _tier_nse(sym: str) -> List[dict]:
    return parse_results_comparison(_nse_json("/api/results-comparision", {"symbol": sym}))


def _tier_screener(sym: str) -> List[dict]:
    from analysis.fundamentals.providers.screener_fundamentals import ScreenerFundamentalProvider
    p = ScreenerFundamentalProvider()
    if not p.is_available():
        raise RuntimeError("beautifulsoup4 not installed")
    # Screener serves the consolidated page first when it exists; which one answered is not exposed.
    return _from_statements(p.get_income_statement(sym, period="quarterly", limit=8), "screener", None)


def _tier_yahoo(sym: str) -> List[dict]:
    from analysis.fundamentals.providers.yahoo_fundamentals import YahooFundamentalProvider
    return _from_statements(YahooFundamentalProvider().get_income_statement(f"{sym}.NS", period="quarterly",
                                                                            limit=8), "yahoo", True)


def latest_reportable_quarter_end(today: Optional[_dt.date] = None) -> _dt.date:
    """Most recent fiscal quarter end strictly before today (Mar / Jun / Sep / Dec)."""
    t = today or _dt.datetime.now(IST).date()
    ends = [_month_end(_dt.date(y, m, 1)) for y in (t.year - 1, t.year) for m in (3, 6, 9, 12)]
    return max(d for d in ends if d < t)


def choose_tier(results: List[tuple]) -> List[dict]:
    """[(source, quarters)] in tier order -> the quarters whose newest period_end is latest
    (ties keep the earlier tier). Pure; exercised by tests."""
    best, best_key = [], None
    for _src, qs in results:
        if not qs:
            continue
        key = max(q["period_end"] for q in qs)
        if best_key is None or key > best_key:
            best, best_key = qs, key
    return best


def fetch_quarterly_figures(symbol: str, tiers: Optional[List[tuple]] = None) -> List[dict]:
    """Last 5-8 quarters {period_end, revenue, net_profit, eps, operating_profit, consolidated, unit='cr',
    source}, newest first. Tiers NSE -> Screener -> Yahoo; a tier missing the just-reported quarter does
    not mask a later tier that has it (stops early once the latest reportable quarter is found)."""
    try:
        sym = _sym(symbol)
        if not sym:
            return []
        key = f"q|{sym}"
        hit = _cache_get(key)
        if hit is not None:
            return list(hit)
        tiers = tiers or [("nse_results_cmp", _tier_nse), ("screener", _tier_screener), ("yahoo", _tier_yahoo)]
        target = latest_reportable_quarter_end()
        got: List[tuple] = []
        for source, fn in tiers:
            qs = _guarded(source, lambda fn=fn: fn(sym))
            if qs:
                got.append((source, qs))
                if max(q["period_end"] for q in qs) >= target:
                    break
        out = choose_tier(got)
        if out:
            _cache_set(key, out, _QUARTERS_TTL_S)
        return list(out)
    except Exception as e:                                  # noqa: BLE001
        _log_once("fetch_quarterly_figures", f"{type(e).__name__}: {e}")
        return []


# ── 4. pre-open ─────────────────────────────────────────────────────────────

def parse_preopen(payload: Any) -> Dict[str, dict]:
    """market-data-pre-open payload -> {symbol: {iep, prev_close, gap_pct, qty}}.
    ASSUMPTION: {"data": [{"metadata": {symbol, iep, previousClose, pChange, finalQuantity}, "detail": …}]}."""
    out: Dict[str, dict] = {}
    for row in _rows(payload) or []:
        md = row.get("metadata") if isinstance(row.get("metadata"), dict) else row
        po = ((row.get("detail") or {}).get("preOpenMarket") or {}) if isinstance(row.get("detail"), dict) else {}
        sym = _sym(_first(md, ("symbol", "SYMBOL")))
        iep = num(_first(md, ("iep", "IEP", "lastPrice"))) or num(po.get("IEP"))
        prev = num(_first(md, ("previousClose", "prevClose", "previous_close"))) or num(po.get("prevClose"))
        if not sym or not iep or iep <= 0:
            continue
        gap = (iep / prev - 1) * 100 if prev and prev > 0 else num(_first(md, ("pChange", "perChange")))
        qty = num(_first(md, ("finalQuantity", "totalTradedVolume", "quantity"))) or num(po.get("finalQuantity"))
        out[sym] = {"iep": iep, "prev_close": prev, "gap_pct": None if gap is None else round(gap, 2), "qty": qty}
    return out


def fetch_preopen() -> Dict[str, dict]:
    """NSE pre-open snapshot (all F&O + equity names in the call auction). {} on failure.
    No other module in the repo fetches this endpoint (checked 2026-11), so it lives here."""
    try:
        hit = _cache_get("preopen")
        if hit is not None:
            return dict(hit)

        def _fetch():
            out = parse_preopen(_nse_json("/api/market-data-pre-open", {"key": "ALL"}))
            if not out:
                raise ValueError("pre-open payload had no parsable rows")
            return out
        out = _guarded("nse_preopen", _fetch)
        if out is None:
            return {}
        _cache_set("preopen", out, 120)
        return dict(out)
    except Exception as e:                                  # noqa: BLE001
        _log_once("fetch_preopen", f"{type(e).__name__}: {e}")
        return {}
