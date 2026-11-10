"""analysis/fundamentals/service.py — the provider-agnostic facade.

The UI and analytics call ONLY this (and read CompanyFundamentals). It:
  * holds an ordered provider list (Yahoo → Screener.in fallback + fill),
  * merges results: Yahoo is primary, Screener.in fills every field Yahoo left None
    (closes the small/mid-cap gap without changing any downstream module),
  * Auto cascade (default_service): Yahoo → Screener.in → stored exchange filing →
    stored ROC filing, each later provider filling only what earlier ones left None.
    When latest revenue / net income / total equity are still missing after that,
    the NSE annual-results XBRL is fetched once per symbol per day (short timeout,
    never raises; NSE_AUTO_FILING_FETCH=0 turns it off) and the result re-merged,
  * caches normalized CompanyFundamentals for 24 h (raw responses are cached inside
    each provider), logging hits/misses,
  * stamps per-field provenance and computes is_partial / missing_fields from the
    inputs the analytics actually need — failures are surfaced, never silently
    zero-filled.
"""
from __future__ import annotations

import datetime as _dt
import logging
import os
import threading
import time
from dataclasses import replace
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple

from .cache import TTLCache
from .models import (  # noqa: F401  (missing_core_fields / sources_caption re-exported)
    BalanceSheet, CashFlow, CompanyFundamentals, IncomeStatement, PeriodType,
    RatioSnapshot, missing_core_fields, sources_caption,
)
from .provider import FundamentalProvider

_log = logging.getLogger("fundamentals.service")


class FundamentalsService:
    def __init__(self, providers: Optional[List[FundamentalProvider]] = None,
                 cache: Optional[TTLCache] = None, ttl_hours: int = 24,
                 auto_fetcher: Optional[Callable[[str], Dict[str, Any]]] = None):
        if providers is None:
            from .providers.yahoo_fundamentals import YahooFundamentalProvider
            from .providers.screener_fundamentals import ScreenerFundamentalProvider
            # Yahoo first (fast, cached, richer margins/GP). Screener fills every gap.
            providers = [YahooFundamentalProvider(), ScreenerFundamentalProvider()]
        self.providers = providers
        self.cache = cache or TTLCache(ttl_seconds=ttl_hours * 3600, name="fundamentals")
        # Called with a base symbol when core fields are still missing after the
        # cascade (see _maybe_auto_fetch). None = never auto-fetch.
        self.auto_fetcher = auto_fetcher

    def get_fundamentals(self, symbol: str, period: PeriodType = "annual",
                         years: int = 10) -> CompanyFundamentals:
        key = f"fund|{symbol}|{period}|{years}"
        cached = self.cache.get(key)
        if cached is not None:
            return cached
        cf = self._build(symbol, period, years)
        self.cache.set(key, cf)
        return cf

    def forget(self, symbol: str) -> None:
        """Drop this symbol's cached results (after a filing for it was saved)."""
        base = _base_symbol(symbol)
        self.cache.drop_where(
            lambda k: k.count("|") >= 3 and _base_symbol(k.split("|")[1]) == base)

    # ── internal ─────────────────────────────────────────────────────────────
    def _collect(self, symbol: str, period: PeriodType, years: int,
                 only: Optional[List[FundamentalProvider]] = None,
                 ) -> List[Tuple[FundamentalProvider, CompanyFundamentals]]:
        out = []
        for p in (self.providers if only is None else only):
            try:
                if not p.is_available():
                    _log.info("provider %s unavailable — skipping", p.name)
                    continue
                cf = self._assemble(p, symbol, period, years)
                if cf.has_any_data():
                    out.append((p, cf))
            except Exception as e:                     # transport failure — try the next
                _log.warning("provider %s failed for %s: %s: %s",
                             p.name, symbol, type(e).__name__, e)
                continue
        return out

    def _merge_all(self, symbol: str,
                   assembled: List[Tuple[FundamentalProvider, CompanyFundamentals]],
                   ) -> CompanyFundamentals:
        if not assembled:
            # nothing resolved — return an explicit empty, fully flagged
            return CompanyFundamentals(
                symbol=symbol, provider_name=None, last_updated=datetime.now(),
                is_partial=True,
                missing_fields=["income_statements", "balance_sheets", "cash_flows", "ratios"],
            )
        # Merge: first provider is primary, later ones fill None fields only.
        # _merge mutates its primary, so start from a copy: `assembled` is
        # reused when the auto-fetch re-merges.
        first = assembled[0][1]
        merged = replace(first, provenance=dict(first.provenance),
                         missing_fields=list(first.missing_fields))
        for _, follower in assembled[1:]:
            merged = self._merge(merged, follower)
        self._stamp(merged)
        return merged

    def _build(self, symbol: str, period: PeriodType, years: int) -> CompanyFundamentals:
        assembled = self._collect(symbol, period, years)
        merged = self._merge_all(symbol, assembled)
        if period != "annual" or not missing_core_fields(merged):
            return merged
        refetch = [p for p in self.providers if getattr(p, "source", None) == "exchange"]
        if not refetch or not self._maybe_auto_fetch(symbol):
            return merged
        # A new exchange filing was saved: re-read only the filing provider
        # (Yahoo / Screener results are reused) and merge in cascade order.
        fresh = {id(p): cf for p, cf in self._collect(symbol, period, years, only=refetch)}
        rebuilt = []
        for p in self.providers:
            if id(p) in fresh:
                rebuilt.append((p, fresh[id(p)]))
            else:
                rebuilt.extend(x for x in assembled if x[0] is p)
        return self._merge_all(symbol, rebuilt)

    def _maybe_auto_fetch(self, symbol: str) -> bool:
        """Try the official filing once per symbol per day. True = a filing was saved."""
        if self.auto_fetcher is None or not auto_fetch_enabled():
            return False
        if not _claim_daily_attempt(symbol):
            return False
        ok = _run_with_timeout(self.auto_fetcher, symbol, AUTO_FETCH_TIMEOUT_S)
        _log.info("auto filing fetch for %s: %s", symbol, "saved" if ok else "nothing saved")
        return ok

    def _assemble(self, provider: FundamentalProvider, symbol: str,
                  period: PeriodType, years: int) -> CompanyFundamentals:
        # Providers that define batch() (stored filings) read once per assembly.
        # Class-level check so mock providers don't sprout one.
        if callable(getattr(type(provider), "batch", None)):
            with provider.batch(symbol):
                return self._assemble_now(provider, symbol, period, years)
        return self._assemble_now(provider, symbol, period, years)

    def _assemble_now(self, provider: FundamentalProvider, symbol: str,
                      period: PeriodType, years: int) -> CompanyFundamentals:
        inc = provider.get_income_statement(symbol, period, years)
        bal = provider.get_balance_sheet(symbol, period, years)
        cfl = provider.get_cash_flow(symbol, period, years)
        rat = provider.get_ratios(symbol)

        name = sector = None
        currency = "INR"
        info_fn = getattr(provider, "company_info", None)
        if callable(info_fn):
            try:
                info = provider.company_info(symbol)
                name, sector = info.get("company_name"), info.get("sector")
                currency = info.get("currency") or "INR"
            except Exception as e:
                # Optional metadata — name/sector/currency stay None/default,
                # but log so a broken company_info() call isn't invisible.
                _log.debug("company_info failed for %s via %s: %s: %s",
                           symbol, provider.name, type(e).__name__, e)

        stmt_date = None
        if inc and inc[0].period:
            stmt_date = inc[0].period.period_end
        elif bal and bal[0].period:
            stmt_date = bal[0].period.period_end

        cf = CompanyFundamentals(
            symbol=symbol, company_name=name, provider_name=provider.name,
            statement_date=stmt_date, last_updated=datetime.now(), currency=currency,
            income_statements=inc, balance_sheets=bal, cash_flows=cfl, ratios=rat,
        )
        self._stamp(cf)
        return cf

    # ── merge (primary + fill) ───────────────────────────────────────────────
    @staticmethod
    def _fill_dataclass(primary, follower):
        """Return a copy of `primary` with every None field replaced by follower's value."""
        if primary is None:
            return follower
        if follower is None:
            return primary
        patch = {}
        for f_name in primary.__dataclass_fields__:
            if getattr(primary, f_name) is None:
                v = getattr(follower, f_name, None)
                if v is not None:
                    patch[f_name] = v
        return replace(primary, **patch) if patch else primary

    @classmethod
    def _merge_series(cls, primary_list, follower_list, key_getter):
        """Fill primary rows by period_end match; append follower-only rows (deeper history)."""
        by_key = {key_getter(x): x for x in primary_list}
        for row in follower_list:
            k = key_getter(row)
            if k in by_key:
                by_key[k] = cls._fill_dataclass(by_key[k], row)
            else:
                by_key[k] = row
        # newest-first
        return sorted(by_key.values(),
                      key=lambda r: (key_getter(r) or datetime(1900, 1, 1).date()),
                      reverse=True)

    @classmethod
    def _merge(cls, primary: CompanyFundamentals,
               follower: CompanyFundamentals) -> CompanyFundamentals:
        period_key = lambda row: (row.period.period_end if row and row.period else None)

        primary.income_statements = cls._merge_series(
            primary.income_statements, follower.income_statements, period_key)
        primary.balance_sheets = cls._merge_series(
            primary.balance_sheets, follower.balance_sheets, period_key)
        primary.cash_flows = cls._merge_series(
            primary.cash_flows, follower.cash_flows, period_key)
        primary.ratios = cls._fill_dataclass(primary.ratios, follower.ratios)

        if not primary.company_name and follower.company_name:
            primary.company_name = follower.company_name
        if not primary.statement_date and follower.statement_date:
            primary.statement_date = follower.statement_date

        # Record every provider that contributed something
        names = [n for n in (primary.provider_name, follower.provider_name) if n]
        primary.provider_name = " + ".join(dict.fromkeys(names)) or primary.provider_name

        # Provenance: keep primary's stamps, add follower.name where primary lacked
        for k, v in (follower.provenance or {}).items():
            primary.provenance.setdefault(k, v)
        return primary

    @staticmethod
    def _stamp(cf: CompanyFundamentals) -> None:
        prov = cf.provider_name
        for group in ("income_statements", "balance_sheets", "cash_flows"):
            if getattr(cf, group):
                cf.provenance.setdefault(group, prov)
        if cf.ratios:
            cf.provenance.setdefault("ratios", prov)

        li, lb = cf.latest_income(), cf.latest_balance()
        checks = {
            "income.revenue":      bool(li and li.revenue is not None),
            "income.eps":          bool(li and (li.eps_diluted is not None
                                                or li.eps_basic is not None)),
            "income.net_income":   bool(li and li.net_income is not None),
            "balance.total_equity": bool(lb and lb.total_equity is not None),
            "balance.total_debt":  bool(lb and lb.total_debt is not None),
        }
        for k, present in checks.items():
            if present:
                cf.provenance.setdefault(k, prov)
        r = cf.ratios
        for k, present in (("ratios.pe", bool(r and r.pe is not None)),
                           ("ratios.pb", bool(r and r.pb is not None))):
            if present:
                cf.provenance.setdefault(k, prov)
        missing = [k for k, present in checks.items() if not present]
        if len([s for s in cf.income_statements if s.revenue is not None]) < 2:
            missing.append("revenue_history(<2y)")
        cf.missing_fields = missing
        cf.is_partial = bool(missing)


# ── Auto filing fetch (once per symbol per day) ───────────────────────────────
AUTO_FETCH_ENV = "NSE_AUTO_FILING_FETCH"
AUTO_FETCH_TIMEOUT_S = 15.0
_BREAKER_SECONDS = 30 * 60            # NSE unreachable → stop trying for 30 min
_ATTEMPTS: Dict[str, str] = {}        # base symbol -> ISO date of the last attempt
_ATTEMPTS_LOCK = threading.Lock()
_breaker_until = 0.0
_KV_USER = "_system"


def _base_symbol(symbol: str) -> str:
    return str(symbol).upper().replace(".NS", "").replace(".BO", "").strip()


def auto_fetch_enabled() -> bool:
    """Opt-out switch: NSE_AUTO_FILING_FETCH=0 (or false/no/off) disables it."""
    return os.environ.get(AUTO_FETCH_ENV, "1").strip().lower() not in ("0", "false", "no", "off")


def _claim_daily_attempt(symbol: str) -> bool:
    """Record today's attempt for `symbol`. False when one was already made today
    (in this process, or by another process via the KV store) or when NSE was
    just found unreachable (breaker open)."""
    if time.time() < _breaker_until:
        return False
    base, today = _base_symbol(symbol), _dt.date.today().isoformat()
    with _ATTEMPTS_LOCK:
        if _ATTEMPTS.get(base) == today:
            return False
        _ATTEMPTS[base] = today
    key = f"filing_autofetch:{base}"
    try:
        import trade_store as store
        if store.kv_get(key, None, user_id=_KV_USER) == today:
            return False
        store.kv_set(key, today, user_id=_KV_USER)
    except Exception as e:                       # KV down — the process memo still holds
        _log.debug("auto-fetch memo unavailable for %s: %s", base, e)
    return True


def _trip_breaker() -> None:
    global _breaker_until
    _breaker_until = time.time() + _BREAKER_SECONDS


def _run_with_timeout(fetcher: Callable[[str], Dict[str, Any]], symbol: str,
                      timeout: float) -> bool:
    """Run `fetcher(base_symbol)` in a daemon thread and wait at most `timeout`
    seconds. Never raises. A timeout or an unreachable NSE opens the breaker; a
    filing that lands after the timeout is still saved (save_filing then drops
    the cached merge, so the next read picks it up)."""
    box: Dict[str, Any] = {}

    def _go():
        try:
            box["res"] = fetcher(_base_symbol(symbol))
        except Exception as e:                   # contract: never raise
            box["res"] = {"ok": False, "reason": "error", "message": str(e)}

    t = threading.Thread(target=_go, daemon=True,
                         name=f"filing-autofetch-{_base_symbol(symbol)}")
    t.start()
    t.join(timeout)
    if t.is_alive():
        _log.info("auto filing fetch for %s timed out after %.0fs", symbol, timeout)
        _trip_breaker()
        return False
    res = box.get("res") or {}
    if not res.get("ok") and res.get("reason") == "transport":
        _trip_breaker()
    return bool(res.get("ok"))


def _default_auto_fetcher(symbol: str) -> Dict[str, Any]:
    from data.nse_filings_xbrl import fetch_exchange_filing
    return fetch_exchange_filing(symbol)


def reset_auto_fetch_state() -> None:
    """Forget today's in-process attempts and close the breaker (tests / retry)."""
    global _breaker_until
    with _ATTEMPTS_LOCK:
        _ATTEMPTS.clear()
    _breaker_until = 0.0


def auto_providers() -> List[FundamentalProvider]:
    """The Auto cascade, in fill order."""
    from .providers.filing_fundamentals import FilingFundamentalProvider
    from .providers.yahoo_fundamentals import YahooFundamentalProvider
    from .providers.screener_fundamentals import ScreenerFundamentalProvider
    return [YahooFundamentalProvider(), ScreenerFundamentalProvider(),
            FilingFundamentalProvider("exchange"), FilingFundamentalProvider("roc")]


# ── module-level singleton so the 24h cache survives Streamlit reruns ──────────
_DEFAULT: Optional[FundamentalsService] = None


def default_service() -> FundamentalsService:
    """Auto: Yahoo → Screener → stored exchange filing → stored ROC filing, plus
    the once-a-day NSE filing fetch when core fields are still missing."""
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = FundamentalsService(providers=auto_providers(),
                                       auto_fetcher=_default_auto_fetcher)
    return _DEFAULT


# ── Official-filing sources (Analyze Stock "Fundamentals source" picker) ───────
_BY_SOURCE: dict = {}


def service_for_source(source: Optional[str]) -> FundamentalsService:
    """Service whose PRIMARY provider is a stored official filing ("roc" = MCA
    upload, "exchange" = NSE XBRL); Yahoo then Screener fill only the fields the
    filing lacks (price ratios, older years). None / "auto" = the default service."""
    if source in (None, "", "auto"):
        return default_service()
    if source not in _BY_SOURCE:
        from .providers.filing_fundamentals import FilingFundamentalProvider
        from .providers.yahoo_fundamentals import YahooFundamentalProvider
        from .providers.screener_fundamentals import ScreenerFundamentalProvider
        _BY_SOURCE[source] = FundamentalsService(providers=[
            FilingFundamentalProvider(source), YahooFundamentalProvider(),
            ScreenerFundamentalProvider()])
    return _BY_SOURCE[source]


def forget_source(source: Optional[str] = None) -> None:
    """Drop cached filing-backed services (after a new filing is saved)."""
    if source is None:
        _BY_SOURCE.clear()
    else:
        _BY_SOURCE.pop(source, None)


def forget_symbol(symbol: str) -> None:
    """A filing for `symbol` was saved: drop its cached merge in the Auto service
    and every filing-first service so the next read includes it."""
    for svc in [_DEFAULT, *_BY_SOURCE.values()]:
        if svc is None:
            continue
        try:
            svc.forget(symbol)
        except Exception as e:
            _log.debug("forget %s failed: %s", symbol, e)
