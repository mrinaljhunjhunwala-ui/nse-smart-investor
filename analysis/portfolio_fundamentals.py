"""
analysis/portfolio_fundamentals.py — Portfolio fundamental-quality wrapper.

Thin adapter over analysis/fundamentals/ — the established, provider-agnostic,
sector-aware fundamentals engine (single source of truth, unit-tested). This
module exists ONLY to preserve the dict-based public API consumed by
dashboard/pages/03_my_portfolio.py, so that page needs zero changes.

DO NOT add provider / fetching logic here. All fetching and metric computation
is delegated to FundamentalsService + analysis.fundamentals.analytics. The
previous version of this file re-implemented its own data fetching and ratio
math independently, which risked two engines returning different answers for
the same ticker.

Unit note — the analytics functions already return:
  • PERCENT for ROE, ROCE and the CAGRs   (e.g. 18.0 means 18 %)
  • a plain ratio ("x") for Debt/Equity    (e.g. 0.45)
so this wrapper performs NO unit conversion. (A common mistake is to ×100 the
ROE/ROCE here — that double-counts, because the engine already scaled them.)
"""
from __future__ import annotations

import logging
from typing import Dict, List, Optional

_log = logging.getLogger("analysis.portfolio_fundamentals")


def _val(ar) -> Optional[float]:
    """Numeric value of an AnalyticResult, or None when the metric is unavailable.

    The engine never substitutes 0 for missing data — it sets available=False and
    value=None — so we surface None rather than a misleading zero.
    """
    try:
        if getattr(ar, "available", False) and ar.value is not None:
            return float(ar.value)
    except Exception:
        pass
    return None


def fetch_fundamentals(ticker: str) -> Dict:
    """
    Fundamentals for a single ticker, delegated to the canonical engine.

    Returns a dict with exactly the keys the portfolio page expects:
        ticker, roe, roce, debt_to_equity,
        revenue_cagr_5y, revenue_cagr_3y, eps_cagr_5y, eps_cagr_3y

    ROE/ROCE/CAGR values are in percent; debt_to_equity is a ratio. Any metric
    the engine can't compute for this ticker/sector is None (never 0).
    """
    out: Dict = {"ticker": ticker}
    try:
        from analysis.fundamentals.service import default_service
        from analysis.fundamentals.analytics import (
            roe as _roe, roce as _roce, debt_to_equity as _de,
            revenue_cagr as _rev, eps_cagr as _eps,
        )
        cf = default_service().get_fundamentals(ticker)
        if cf is None:
            return out

        out["roe"]             = _val(_roe(cf))
        out["roce"]            = _val(_roce(cf))
        out["debt_to_equity"]  = _val(_de(cf))
        out["revenue_cagr_5y"] = _val(_rev(cf, years=5))
        out["revenue_cagr_3y"] = _val(_rev(cf, years=3))
        out["eps_cagr_5y"]     = _val(_eps(cf, years=5))
        out["eps_cagr_3y"]     = _val(_eps(cf, years=3))
        return out

    except Exception as _e:
        _log.warning("portfolio_fundamentals.fetch_fundamentals(%s) failed: %s", ticker, _e)
        return out


def batch_fetch_fundamentals(tickers: List[str]) -> List[Dict]:
    """Fundamentals for a list of tickers; per-ticker failures degrade to {'ticker': t}."""
    return [fetch_fundamentals(t) for t in tickers]


def compute_quality_score(fund: Dict) -> int:
    """
    0–100 fundamental-quality score from whatever metrics are available.

    Weights: ROE 30, ROCE 30, Revenue CAGR 20, EPS CAGR 20. The score is scaled
    by the weight of the metrics actually present, so a stock with only partial
    data isn't unfairly penalised. Returns 0 when nothing is available.

    Inputs are already in percent (ROE/ROCE/CAGR), matching the engine's output.
    """
    score = 0.0
    weight_used = 0.0

    roe_val = fund.get("roe")
    if roe_val is not None:
        score += min(30.0, max(0.0, roe_val * 2.0))   # 15% ROE → full 30 pts
        weight_used += 30.0

    roce_val = fund.get("roce")
    if roce_val is not None:
        score += min(30.0, max(0.0, roce_val * 2.0))  # 15% ROCE → full 30 pts
        weight_used += 30.0

    rev_cagr = fund.get("revenue_cagr_5y")
    if rev_cagr is None:
        rev_cagr = fund.get("revenue_cagr_3y")
    if rev_cagr is not None:
        score += min(20.0, max(0.0, rev_cagr))         # 20% CAGR → full 20 pts
        weight_used += 20.0

    eps_cagr = fund.get("eps_cagr_5y")
    if eps_cagr is None:
        eps_cagr = fund.get("eps_cagr_3y")
    if eps_cagr is not None:
        score += min(20.0, max(0.0, eps_cagr))
        weight_used += 20.0

    if weight_used == 0:
        return 0
    return round(score * 100.0 / weight_used)
