"""analysis/fundamentals/service.py — the provider-agnostic facade.

The UI and analytics call ONLY this (and read CompanyFundamentals). It:
  * holds an ordered provider list (Phase 0: Yahoo only; loop is ready for tiering),
  * caches normalized CompanyFundamentals for 24 h (raw responses are cached inside the
    provider), logging hits/misses,
  * stamps per-field provenance and computes is_partial / missing_fields from the inputs
    the analytics actually need — failures are surfaced, never silently zero-filled.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import List, Optional

from .cache import TTLCache
from .models import CompanyFundamentals, PeriodType
from .provider import FundamentalProvider

_log = logging.getLogger("fundamentals.service")


class FundamentalsService:
    def __init__(self, providers: Optional[List[FundamentalProvider]] = None,
                 cache: Optional[TTLCache] = None, ttl_hours: int = 24):
        if providers is None:
            from .providers.yahoo_fundamentals import YahooFundamentalProvider
            providers = [YahooFundamentalProvider()]      # Phase 0: Yahoo only
        self.providers = providers
        self.cache = cache or TTLCache(ttl_seconds=ttl_hours * 3600, name="fundamentals")

    def get_fundamentals(self, symbol: str, period: PeriodType = "annual",
                         years: int = 10) -> CompanyFundamentals:
        key = f"fund|{symbol}|{period}|{years}"
        cached = self.cache.get(key)
        if cached is not None:
            return cached
        cf = self._build(symbol, period, years)
        self.cache.set(key, cf)
        return cf

    # ── internal ─────────────────────────────────────────────────────────────
    def _build(self, symbol: str, period: PeriodType, years: int) -> CompanyFundamentals:
        for p in self.providers:
            try:
                if not p.is_available():
                    _log.info("provider %s unavailable — skipping", p.name)
                    continue
                cf = self._assemble(p, symbol, period, years)
                if cf.has_any_data():
                    return cf
                _log.info("provider %s returned no data for %s", p.name, symbol)
            except Exception as e:   # transport failure — try the next tier
                _log.warning("provider %s failed for %s: %s: %s",
                             p.name, symbol, type(e).__name__, e)
                continue
        # nothing resolved — return an explicit empty, fully flagged (not a silent blank)
        return CompanyFundamentals(
            symbol=symbol, provider_name=None, last_updated=datetime.now(),
            is_partial=True,
            missing_fields=["income_statements", "balance_sheets", "cash_flows", "ratios"],
        )

    def _assemble(self, provider: FundamentalProvider, symbol: str,
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
            except Exception:
                pass

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

    @staticmethod
    def _stamp(cf: CompanyFundamentals) -> None:
        prov = cf.provider_name
        for group in ("income_statements", "balance_sheets", "cash_flows"):
            if getattr(cf, group):
                cf.provenance[group] = prov
        if cf.ratios:
            cf.provenance["ratios"] = prov

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
                cf.provenance[k] = prov
        missing = [k for k, present in checks.items() if not present]
        if len([s for s in cf.income_statements if s.revenue is not None]) < 2:
            missing.append("revenue_history(<2y)")
        cf.missing_fields = missing
        cf.is_partial = bool(missing)


# ── module-level singleton so the 24h cache survives Streamlit reruns ──────────
_DEFAULT: Optional[FundamentalsService] = None


def default_service() -> FundamentalsService:
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = FundamentalsService()
    return _DEFAULT
