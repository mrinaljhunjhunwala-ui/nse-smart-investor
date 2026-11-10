"""
scripts/provider_canary.py — weekly live canary for every external data provider.

One small live query per provider, each judged by the same schema checks the
slow ``tests/test_provenance_*`` canaries use (those tests import the
``check_*`` functions below, so the two can't drift apart):

  provider           query                                   scoring path?
  yahoo_chart        RELIANCE.NS 5d daily bars               yes (prices)
  nse_all_indices    /api/allIndices, INDIA VIX row          no  (VIX tier 1; Yahoo backs it)
  nse_corp_info      /api/top-corp-info for RELIANCE         no  (qualitative flags)
  google_news        Google News RSS for RELIANCE            no  (news panel / flags)
  nse_rss            nsearchives RSS feeds (all categories)  no  (qualitative flags)
  screener           Screener.in top ratios for RELIANCE     no  (valuation fill-in)
  nse_bhavcopy       sec_bhavdata_full for the last session  yes (delivery %, price fallback)
  india_vix          utils.vix tiered fetch (NSE -> Yahoo)   yes (VIX regime / fear filter)

Each row is ``ok`` / ``degraded`` / ``FAILED`` with a one-line reason and the
schema check that failed. Prints a table; with ``--telegram`` also sends it via
``utils/telegram.py`` (🟢 one-liner when all ok, 🔴 with the non-ok rows
otherwise). A Telegram failure never raises.

Exit code 1 when any provider a *scoring* path depends on FAILED, else 0.

Pure: no Streamlit. Run by .github/workflows/provider_canary.yml (dispatched
by cron-job.org, Sundays 09:00 IST).
"""
from __future__ import annotations

import argparse
import datetime as _dt
import logging
import math
import os
import sys
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List, Optional

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

_log = logging.getLogger("scripts.provider_canary")

OK, DEGRADED, FAILED = "ok", "degraded", "FAILED"
CANARY_SYMBOL = "RELIANCE"
CANARY_COMPANY = "Reliance Industries"

# ── Schema checks (shared with tests/test_provenance_*) ─────────────────────
# Each returns None when the payload passes, else a one-line failure message.

YAHOO_REQUIRED_COLS = {"Open", "High", "Low", "Close", "Volume"}
CORP_INFO_KEYS = {
    "latest_announcements", "corporate_actions", "shareholdings_patterns",
    "financial_results", "borad_meeting",
}
SCREENER_PB_FIELDS = ("Market Cap", "Current Price", "Book Value")
VIX_REGIMES = {"complacency", "normal", "elevated", "fear", "panic"}


def check_yahoo_frame(df: Any) -> Optional[str]:
    """OHLCV frame: non-empty, five columns, positive last close and volume."""
    try:
        import pandas as pd
    except ImportError:                                   # pragma: no cover
        return "pandas missing"
    if not isinstance(df, pd.DataFrame):
        return f"expected DataFrame, got {type(df).__name__}"
    if df.empty:
        return "Yahoo returned empty frame - auth or shape drift"
    missing = YAHOO_REQUIRED_COLS - set(df.columns)
    if missing:
        return f"missing columns: {sorted(missing)}"
    last_close, last_volume = float(df["Close"].iloc[-1]), float(df["Volume"].iloc[-1])
    if not last_close > 0:
        return f"suspicious close: {last_close}"
    if not last_volume > 0:
        return f"suspicious volume: {last_volume}"
    return None


def check_corp_info(result: Any) -> Optional[str]:
    """top-corp-info dict carrying at least one key the flags pipeline reads."""
    if not isinstance(result, dict):
        return f"expected dict response, got {type(result).__name__}"
    if not CORP_INFO_KEYS & set(result):
        return (f"none of the expected keys {sorted(CORP_INFO_KEYS)} present; "
                f"got {sorted(result)[:8]}")
    return None


def check_news_items(items: Any) -> Optional[str]:
    """Non-empty list of dicts, the first with a title and a link."""
    if not isinstance(items, list):
        return f"expected list, got {type(items).__name__}"
    if not items:
        return "zero items for a common-name query - endpoint drift or geo-block"
    first = items[0]
    if not isinstance(first, dict):
        return f"expected item to be dict, got {type(first).__name__}"
    for field in ("title", "link"):
        if not first.get(field):
            return f"item missing/empty {field!r}"
    return None


def check_screener_top(top: Any) -> Optional[str]:
    """Market Cap / Current Price / Book Value parse to positive numbers (P/B inputs)."""
    if not isinstance(top, dict) or not top:
        return "top-ratios block missing from parsed page"
    for field in SCREENER_PB_FIELDS:
        if field not in top:
            return f"{field!r} missing from top-ratios - Screener HTML may have changed"
        v = top[field]
        if v is None:
            return f"{field!r} parsed to None - currency prefix/suffix stripping broken"
        if not isinstance(v, (int, float)):
            return f"{field!r} parsed to {type(v).__name__}, expected number"
        if not v > 0:
            return f"{field!r} parsed to {v} - suspiciously non-positive"
    return None


def check_vix_row(row: Any) -> Optional[str]:
    """VIX dict: plausible positive vix, documented regime, bool allow_buy."""
    if not isinstance(row, dict):
        return f"expected dict, got {type(row).__name__}"
    vix = row.get("vix")
    if vix is None:
        return "VIX value missing - every source failed"
    try:
        vix_f = float(vix)
    except (TypeError, ValueError):
        return f"VIX not numeric: {vix!r}"
    if not (math.isfinite(vix_f) and 5.0 < vix_f < 100.0):
        return f"VIX {vix_f} outside plausible band [5, 100]"
    if row.get("regime") not in VIX_REGIMES:
        return f"regime {row.get('regime')!r} not in {sorted(VIX_REGIMES)}"
    if not isinstance(row.get("allow_buy"), bool):
        return f"allow_buy must be a bool, got {type(row.get('allow_buy')).__name__}"
    return None


def check_bhavcopy_text(text: str, min_rows: int = 500) -> Optional[str]:
    """Delivery + OHLCV parsers accept the CSV (Guardrail 14) and it has enough rows."""
    from data.nse_bhavcopy_prices import parse_ohlcv
    from data.nse_delivery import _parse_bhavcopy
    try:
        rows = _parse_bhavcopy(text)
        frame = parse_ohlcv(text)
    except ValueError as e:
        return str(e)
    if len(rows) < min_rows or len(frame) < min_rows:
        return f"only {len(rows)} delivery / {len(frame)} OHLCV rows (expected >= {min_rows})"
    return None


# ── Probes ──────────────────────────────────────────────────────────────────

@dataclass
class ProbeResult:
    provider: str
    status: str                 # ok | degraded | FAILED
    reason: str                 # one line
    check: str = ""             # the schema check that failed ("" when ok)
    scoring: bool = False       # a composite-score path depends on it

    def as_row(self) -> Dict[str, Any]:
        return {"provider": self.provider, "status": self.status, "reason": self.reason,
                "check": self.check, "scoring": self.scoring}


def _probe_yahoo() -> ProbeResult:
    from data.fetcher import _fetch_yahoo_direct
    df = _fetch_yahoo_direct(f"{CANARY_SYMBOL}.NS", period="5d")
    fail = check_yahoo_frame(df)
    if fail:
        return ProbeResult("yahoo_chart", FAILED, fail, "check_yahoo_frame")
    return ProbeResult("yahoo_chart", OK, f"{len(df)} bars, last close {float(df['Close'].iloc[-1]):,.2f}")


def _probe_nse_all_indices() -> ProbeResult:
    import utils.vix as V
    try:
        vix, _pct = V.parse_nse_all_indices(V._nse_all_indices_payload())
    except ValueError as e:
        chk = "parse_nse_all_indices" if "drift" in str(e) or "plausible" in str(e) else "HTTP"
        return ProbeResult("nse_all_indices", FAILED, str(e), chk)
    return ProbeResult("nse_all_indices", OK, f"INDIA VIX row present, last {vix:.2f}")


def _probe_corp_info() -> ProbeResult:
    from data.nse_corp_info import get_corp_info, get_last_diagnostic
    result = get_corp_info(CANARY_SYMBOL, use_cache=False)
    diag = get_last_diagnostic(CANARY_SYMBOL) or {}
    if not diag.get("ok"):
        return ProbeResult("nse_corp_info", FAILED, str(diag.get("reason") or "no diagnostic"),
                           "HTTP 200 + JSON object")
    fail = check_corp_info(result)
    if fail:
        return ProbeResult("nse_corp_info", FAILED, fail, "check_corp_info")
    return ProbeResult("nse_corp_info", OK, f"keys: {', '.join(sorted(CORP_INFO_KEYS & set(result)))}")


def _probe_google_news() -> ProbeResult:
    from data.news_feed import fetch_news, get_last_diagnostic
    items = fetch_news(CANARY_SYMBOL, company_name=CANARY_COMPANY, max_items=5, use_cache=False)
    diag = get_last_diagnostic(CANARY_SYMBOL) or {}
    if not diag.get("ok"):
        return ProbeResult("google_news", FAILED, str(diag.get("reason") or "no diagnostic"),
                           "HTTP 200 + RSS XML")
    fail = check_news_items(items)
    if fail:
        # HTTP + XML fine, just nothing listed: degraded, not dead.
        status = DEGRADED if isinstance(items, list) and not items else FAILED
        return ProbeResult("google_news", status, fail, "check_news_items")
    return ProbeResult("google_news", OK, f"{len(items)} items")


def _probe_nse_rss() -> ProbeResult:
    from data.nse_rss_feeds import FEEDS, fetch_feed, get_last_diagnostic
    statuses: Dict[str, str] = {}
    for cat in FEEDS:
        fetch_feed(cat, use_cache=False)
        statuses[cat] = str((get_last_diagnostic(cat) or {}).get("status") or "error")
    ok = [c for c, s in statuses.items() if s == "ok"]
    errors = [c for c, s in statuses.items() if s == "error"]
    others = [f"{c}={s}" for c, s in statuses.items() if s != "ok"]
    if not ok:
        return ProbeResult("nse_rss", FAILED, f"no feed returned fresh items ({'; '.join(others)})",
                           "items[].title present and fresh")
    if errors or len(ok) * 2 < len(statuses):
        return ProbeResult("nse_rss", DEGRADED, f"{len(ok)}/{len(statuses)} ok; {'; '.join(others)}",
                           "items[].title present and fresh")
    tail = f"; {'; '.join(others)}" if others else ""
    return ProbeResult("nse_rss", OK, f"{len(ok)}/{len(statuses)} feeds ok{tail}")


def _probe_screener() -> ProbeResult:
    from analysis.fundamentals.providers.screener_fundamentals import ScreenerFundamentalProvider
    provider = ScreenerFundamentalProvider()
    if not provider.is_available():
        return ProbeResult("screener", DEGRADED, "beautifulsoup4 not installed", "is_available")
    raw = provider._raw(CANARY_SYMBOL)
    if not raw:
        return ProbeResult("screener", FAILED, "no page parsed for RELIANCE", "page fetch")
    fail = check_screener_top(raw.get("top"))
    if fail:
        return ProbeResult("screener", FAILED, fail, "check_screener_top")
    top = raw["top"]
    return ProbeResult("screener", OK, f"P/B inputs ok (price {top['Current Price']:,.0f}, "
                                       f"book {top['Book Value']:,.0f})")


def _previous_session(d: _dt.date) -> _dt.date:
    from utils.nse_holidays import is_trading_day
    d -= _dt.timedelta(days=1)
    while not is_trading_day(d):
        d -= _dt.timedelta(days=1)
    return d


def _probe_bhavcopy() -> ProbeResult:
    from data.nse_bhavcopy_prices import last_published_session
    from data.nse_delivery import _fetch_bhavcopy
    session = last_published_session()
    try:
        text = _fetch_bhavcopy(session)
        lag = ""
    except ValueError as e:
        if "404" not in str(e):
            raise
        # Not yet published: one session back is a publish lag, not an outage.
        prev = _previous_session(session)
        text = _fetch_bhavcopy(prev)
        lag = f"{session.isoformat()} not published yet; served {prev.isoformat()}"
    fail = check_bhavcopy_text(text)
    if fail:
        return ProbeResult("nse_bhavcopy", FAILED, fail, "check_bhavcopy_text")
    if lag:
        return ProbeResult("nse_bhavcopy", DEGRADED, lag, "last session published")
    return ProbeResult("nse_bhavcopy", OK, f"{session.isoformat()} parsed")


def _probe_vix() -> ProbeResult:
    import utils.vix as V
    row = V.fetch_vix_tiered()
    fail = check_vix_row(row)
    if fail:
        tiers = "; ".join(f"{a['source']}: {a['reason']}" for a in row.get("attempts") or [])
        return ProbeResult("india_vix", FAILED, f"{fail} ({tiers})" if tiers else fail, "check_vix_row")
    if row.get("source") != V.SOURCES[0]:
        return ProbeResult("india_vix", DEGRADED,
                           f"{row['vix']:.2f} from {row.get('source')} (NSE tier down)", "tier 1 answered")
    return ProbeResult("india_vix", OK, f"{row['vix']:.2f} {row['regime']} from {row.get('source')}")


# (provider name, probe, scoring path depends on it)
PROBES: List[tuple] = [
    ("yahoo_chart", _probe_yahoo, True),
    ("nse_all_indices", _probe_nse_all_indices, False),
    ("nse_corp_info", _probe_corp_info, False),
    ("google_news", _probe_google_news, False),
    ("nse_rss", _probe_nse_rss, False),
    ("screener", _probe_screener, False),
    ("nse_bhavcopy", _probe_bhavcopy, True),
    ("india_vix", _probe_vix, True),
]


def run_probes(probes: Optional[Iterable[tuple]] = None) -> List[ProbeResult]:
    """Run every probe; an exception inside one becomes that row's FAILED reason."""
    out: List[ProbeResult] = []
    for name, fn, scoring in (PROBES if probes is None else probes):
        try:
            res = fn()
        except Exception as e:
            res = ProbeResult(name, FAILED, f"{type(e).__name__}: {e}", "probe raised")
        res.provider, res.scoring = name, scoring
        res.reason = " ".join(str(res.reason).split())[:160]
        out.append(res)
    return out


def exit_code(results: Iterable[ProbeResult]) -> int:
    """1 when any provider a scoring path depends on FAILED, else 0."""
    return 1 if any(r.scoring and r.status == FAILED for r in results) else 0


def format_table(results: List[ProbeResult]) -> str:
    """Fixed-width text table for the Actions log."""
    w = max([len(r.provider) for r in results] + [8])
    lines = [f"{'provider':<{w}}  {'status':<8}  {'score':<5}  reason [failed check]",
             f"{'-' * w}  {'-' * 8}  {'-' * 5}  {'-' * 30}"]
    for r in results:
        chk = f" [{r.check}]" if r.status != OK and r.check else ""
        lines.append(f"{r.provider:<{w}}  {r.status:<8}  {'yes' if r.scoring else '':<5}  {r.reason}{chk}")
    return "\n".join(lines)


def format_telegram(results: List[ProbeResult], today: Optional[_dt.date] = None) -> str:
    """🟢 one-liner when all ok; 🔴 header + the non-ok rows otherwise (Markdown)."""
    day = (today or _dt.date.today()).strftime("%a %d %b %Y")
    bad = [r for r in results if r.status != OK]
    if not bad:
        return f"🟢 *Provider canary* {day}: all {len(results)} providers ok."
    n_fail = sum(r.status == FAILED for r in bad)
    scoring = [r.provider for r in bad if r.scoring and r.status == FAILED]
    head = (f"🔴 *Provider canary* {day}: {n_fail} FAILED, {len(bad) - n_fail} degraded "
            f"of {len(results)}")
    if scoring:
        # Outside the code block: escape legacy-Markdown specials ("yahoo_chart").
        from utils.telegram import TelegramAlerter
        head += f"\nScoring inputs down: {TelegramAlerter._escape_md(', '.join(scoring))}"
    rows = []
    for r in bad:
        chk = f" [{r.check}]" if r.check else ""
        rows.append(f"{r.status:<8} {r.provider}: {r.reason}{chk}".replace("`", "'"))
    return head + "\n```\n" + "\n".join(rows) + "\n```"


def send_telegram(text: str, alerter_factory: Optional[Callable[[], Any]] = None) -> bool:
    """Send via utils.telegram; never raises (False on any failure)."""
    try:
        if alerter_factory is None:
            from utils.telegram import TelegramAlerter
            alerter_factory = TelegramAlerter
        return bool(alerter_factory().send_text(text))
    except Exception as e:
        print(f"[provider_canary] Telegram send failed (ignored): {type(e).__name__}: {e}")
        return False


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Live canary for every external data provider.")
    ap.add_argument("--telegram", action="store_true", help="also send the result to Telegram")
    args = ap.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    results = run_probes()
    print(format_table(results))
    code = exit_code(results)
    print(f"\nexit {code}: " + ("a scoring provider FAILED" if code else "no scoring provider FAILED"))
    if args.telegram:
        send_telegram(format_telegram(results))
    return code


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(levelname)s %(message)s")
    sys.exit(main())
