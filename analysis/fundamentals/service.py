"""analysis/fundamentals/service.py — the provider-agnostic facade.

The UI and analytics call ONLY this (and read CompanyFundamentals). It:
  * holds an ordered provider list (Yahoo → Screener.in fallback + fill),
  * merges results: Yahoo is primary, Screener.in fills every field Yahoo left None
    (closes the small/mid-cap gap without changing any downstream module),
  * caches normalized CompanyFundamentals for 24 h (raw responses are cached inside
    each provider), logging hits/misses,
  * stamps per-field provenance and computes is_partial / missing_fields from the
    inputs the analytics actually need — failures are surfaced, never silently
    zero-filled.
"""
from __future__ import annotations

import logging
from dataclasses import replace
from datetime import datetime
from typing import List, Optional

from .cache import TTLCache
from .models import (
    BalanceSheet, CashFlow, CompanyFundamentals, IncomeStatement, PeriodType,
    RatioSnapshot,
)
from .provider import FundamentalProvider

_log = logging.getLogger("fundamentals.service")


class FundamentalsService:
    def __init__(self, providers: Optional[List[FundamentalProvider]] = None,
                 cache: Optional[TTLCache] = None, ttl_hours: int = 24):
        if providers is None:
            from .providers.yahoo_fundamentals import YahooFundamentalProvider
            from .providers.screener_fundamentals import ScreenerFundamentalProvider
            # Yahoo first (fast, cached, richer margins/GP). Screener fills every gap.
            providers = [YahooFundamentalProvider(), ScreenerFundamentalProvider()]
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
        assembled: List[CompanyFundamentals] = []
        for p in self.providers:
            try:
                if not p.is_available():
                    _log.info("provider %s unavailable — skipping", p.name)
                    continue
                cf = self._assemble(p, symbol, period, years)
                if cf.has_any_data():
                    assembled.append(cf)
            except Exception as e:                     # transport failure — try the next
                _log.warning("provider %s failed for %s: %s: %s",
                             p.name, symbol, type(e).__name__, e)
                continue
        if not assembled:
            # nothing resolved — return an explicit empty, fully flagged
            return CompanyFundamentals(
                symbol=symbol, provider_name=None, last_updated=datetime.now(),
                is_partial=True,
                missing_fields=["income_statements", "balance_sheets", "cash_flows", "ratios"],
            )
        # Merge: first provider is primary, later ones fill None fields only.
        merged = assembled[0]
        for follower in assembled[1:]:
            merged = self._merge(merged, follower)
        self._stamp(merged)
        return merged

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
