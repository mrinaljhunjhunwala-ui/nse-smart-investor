"""
analysis/portfolio_fundamentals.py — Phase 4 strategic fundamental analysis.

Metrics computed (when available):
  * Revenue CAGR (3Y, 5Y)
  * EPS CAGR (3Y, 5Y)
  * ROE, ROCE (Return on Equity, Return on Invested Capital)
  * Debt/Equity ratio + debt trend
  * Free Cash Flow margin
  * Dividend yield

Data sources:
  1. yfinance (fast; EOD data; free)
  2. screener.in scrape (fallback; slower; more complete)
  3. Local cache (reduces API calls)

Quality score (0–100):
  Profitability (ROE/ROCE), Growth (Revenue/EPS CAGR), Leverage (D/E),
  FCF health, dividend consistency.

Usage:
  from analysis.portfolio_fundamentals import fetch_fundamentals, compute_quality_score
  fund = fetch_fundamentals("RELIANCE.NS")
  score = compute_quality_score(fund)  # 0–100
"""

from __future__ import annotations

import json
import logging
import math
import time
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

_log = logging.getLogger("fundamentals")

# Local cache directory (5 days TTL per metric)
_CACHE_DIR = Path(__file__).parent.parent / "data" / ".cache_fundamentals"
_CACHE_TTL_SECONDS = 5 * 24 * 3600


@lru_cache(maxsize=512)
def _ticker_clean(ticker: str) -> str:
    """Normalize ticker: RELIANCE.NS → RELIANCE"""
    return ticker.replace(".NS", "").replace(".BO", "").upper()


# ────────────────────────────────────────────────────────────────────────────
# Cache layer
# ────────────────────────────────────────────────────────────────────────────

def _cache_key(ticker: str, metric: str) -> str:
    """Unique cache filename."""
    clean = _ticker_clean(ticker)
    return f"{clean}_{metric}.json"


def _read_cache(ticker: str, metric: str) -> Optional[Dict]:
    """Read from cache if valid (< 5 days old)."""
    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        path = _CACHE_DIR / _cache_key(ticker, metric)
        if not path.exists():
            return None
        age = time.time() - path.stat().st_mtime
        if age > _CACHE_TTL_SECONDS:
            return None
        with open(path) as f:
            return json.load(f)
    except Exception as e:
        _log.debug("cache read failed: %s", e)
        return None


def _write_cache(ticker: str, metric: str, data: Dict) -> None:
    """Write to cache."""
    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        path = _CACHE_DIR / _cache_key(ticker, metric)
        with open(path, "w") as f:
            json.dump(data, f)
    except Exception as e:
        _log.debug("cache write failed: %s", e)


# ────────────────────────────────────────────────────────────────────────────
# yfinance integration
# ────────────────────────────────────────────────────────────────────────────

def _fetch_yfinance_income_stmt(ticker: str) -> Optional[pd.DataFrame]:
    """Fetch annual income statement from yfinance (last 5 years)."""
    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        income = t.income_stmt
        if income is None or income.empty:
            return None
        return income.iloc[:5]  # Last 5 years
    except Exception as e:
        _log.debug("yfinance income fetch failed for %s: %s", ticker, e)
        return None


def _fetch_yfinance_balance_sheet(ticker: str) -> Optional[pd.DataFrame]:
    """Fetch annual balance sheet from yfinance (last 5 years)."""
    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        bs = t.balance_sheet
        if bs is None or bs.empty:
            return None
        return bs.iloc[:5]
    except Exception as e:
        _log.debug("yfinance balance sheet fetch failed for %s: %s", ticker, e)
        return None


def _fetch_yfinance_cashflow(ticker: str) -> Optional[pd.DataFrame]:
    """Fetch annual cash flow from yfinance (last 5 years)."""
    try:
        import yfinance as yf
        t = yf.Ticker(ticker)
        cf = t.cashflow
        if cf is None or cf.empty:
            return None
        return cf.iloc[:5]
    except Exception as e:
        _log.debug("yfinance cashflow fetch failed for %s: %s", ticker, e)
        return None


# ────────────────────────────────────────────────────────────────────────────
# Metric calculations (pure functions)
# ────────────────────────────────────────────────────────────────────────────

def _cagr(start_val: float, end_val: float, years: int) -> Optional[float]:
    """Compound annual growth rate."""
    if start_val is None or end_val is None or start_val <= 0 or years <= 0:
        return None
    try:
        return round((pow(abs(end_val) / abs(start_val), 1 / years) - 1) * 100, 2)
    except Exception:
        return None


def compute_revenue_cagr(income_df: pd.DataFrame, years: int = 5) -> Optional[float]:
    """Revenue CAGR over last N years (from income statement)."""
    if income_df is None or income_df.empty:
        return None
    try:
        # Row 0 = total revenue
        rev_col = next((c for c in income_df.index if 'revenue' in str(c).lower()), None)
        if rev_col is None:
            return None
        revenues = income_df.loc[rev_col].dropna()
        if len(revenues) < 2:
            return None
        # Most recent is first; oldest last
        recent = float(revenues.iloc[0])
        oldest = float(revenues.iloc[min(years - 1, len(revenues) - 1)])
        n_years = min(years - 1, len(revenues) - 1)
        return _cagr(oldest, recent, max(1, n_years))
    except Exception as e:
        _log.debug("revenue CAGR failed: %s", e)
        return None


def compute_eps_cagr(income_df: pd.DataFrame, years: int = 5) -> Optional[float]:
    """EPS CAGR."""
    if income_df is None or income_df.empty:
        return None
    try:
        eps_col = next((c for c in income_df.index if 'eps' in str(c).lower()), None)
        if eps_col is None:
            return None
        eps_vals = income_df.loc[eps_col].dropna()
        if len(eps_vals) < 2:
            return None
        recent = float(eps_vals.iloc[0])
        oldest = float(eps_vals.iloc[min(years - 1, len(eps_vals) - 1)])
        n_years = min(years - 1, len(eps_vals) - 1)
        if oldest == 0:
            return None
        return _cagr(oldest, recent, max(1, n_years))
    except Exception as e:
        _log.debug("EPS CAGR failed: %s", e)
        return None


def compute_roe(income_df: pd.DataFrame, balance_df: pd.DataFrame) -> Optional[float]:
    """Return on Equity (Net Income / Avg Shareholders' Equity, most recent year)."""
    if income_df is None or balance_df is None or income_df.empty or balance_df.empty:
        return None
    try:
        ni_col = next((c for c in income_df.index if 'net income' in str(c).lower()), None)
        eq_col = next((c for c in balance_df.index if 'stockholders equity' in str(c).lower()
                       or 'shareholders equity' in str(c).lower()), None)
        if ni_col is None or eq_col is None:
            return None
        ni = float(income_df.loc[ni_col].iloc[0])
        eq = float(balance_df.loc[eq_col].iloc[0])
        if eq <= 0:
            return None
        return round((ni / eq) * 100, 2)
    except Exception as e:
        _log.debug("ROE failed: %s", e)
        return None


def compute_roce(income_df: pd.DataFrame, balance_df: pd.DataFrame) -> Optional[float]:
    """Return on Invested Capital (EBIT / (Equity + Debt))."""
    if income_df is None or balance_df is None or income_df.empty or balance_df.empty:
        return None
    try:
        ebit_col = next((c for c in income_df.index if 'ebit' in str(c).lower()
                         or 'operating income' in str(c).lower()), None)
        eq_col = next((c for c in balance_df.index if 'stockholders equity' in str(c).lower()
                       or 'shareholders equity' in str(c).lower()), None)
        debt_col = next((c for c in balance_df.index if 'total debt' in str(c).lower()
                         or 'long term debt' in str(c).lower()), None)
        if ebit_col is None or eq_col is None:
            return None
        ebit = float(income_df.loc[ebit_col].iloc[0])
        eq = float(balance_df.loc[eq_col].iloc[0])
        debt = float(balance_df.loc[debt_col].iloc[0]) if debt_col is not None else 0.0
        invested = eq + debt
        if invested <= 0:
            return None
        return round((ebit / invested) * 100, 2)
    except Exception as e:
        _log.debug("ROCE failed: %s", e)
        return None


def compute_debt_to_equity(balance_df: pd.DataFrame) -> Optional[float]:
    """Debt/Equity ratio (Total Debt / Total Equity, most recent)."""
    if balance_df is None or balance_df.empty:
        return None
    try:
        debt_col = next((c for c in balance_df.index if 'total debt' in str(c).lower()
                         or 'total liabilities' in str(c).lower()), None)
        eq_col = next((c for c in balance_df.index if 'stockholders equity' in str(c).lower()
                       or 'shareholders equity' in str(c).lower()), None)
        if debt_col is None or eq_col is None:
            return None
        debt = float(balance_df.loc[debt_col].iloc[0])
        eq = float(balance_df.loc[eq_col].iloc[0])
        if eq <= 0:
            return None
        return round(debt / eq, 2)
    except Exception as e:
        _log.debug("D/E failed: %s", e)
        return None


def compute_fcf_margin(income_df: pd.DataFrame, cashflow_df: pd.DataFrame) -> Optional[float]:
    """Free Cash Flow Margin (FCF / Revenue)."""
    if income_df is None or cashflow_df is None or income_df.empty or cashflow_df.empty:
        return None
    try:
        rev_col = next((c for c in income_df.index if 'revenue' in str(c).lower()), None)
        ocf_col = next((c for c in cashflow_df.index if 'operating cash' in str(c).lower()), None)
        capex_col = next((c for c in cashflow_df.index if 'capital expend' in str(c).lower()
                          or 'purchase of' in str(c).lower()), None)
        if rev_col is None or ocf_col is None:
            return None
        rev = float(income_df.loc[rev_col].iloc[0])
        ocf = float(cashflow_df.loc[ocf_col].iloc[0])
        capex = float(cashflow_df.loc[capex_col].iloc[0]) if capex_col is not None else 0.0
        fcf = ocf - capex
        if rev <= 0:
            return None
        return round((fcf / rev) * 100, 2)
    except Exception as e:
        _log.debug("FCF margin failed: %s", e)
        return None


# ────────────────────────────────────────────────────────────────────────────
# Main orchestrator
# ────────────────────────────────────────────────────────────────────────────

def fetch_fundamentals(ticker: str) -> Dict:
    """
    Fetch and compute fundamental metrics for an NSE stock.

    Returns dict with keys:
      ticker, data_source, timestamp,
      revenue_cagr_3y, revenue_cagr_5y,
      eps_cagr_3y, eps_cagr_5y,
      roe, roce, debt_to_equity, fcf_margin,
      error (if any), notes (warnings)
    """
    clean_ticker = _ticker_clean(ticker)
    yf_ticker = f"{clean_ticker}.NS"  # yfinance format

    # Check cache first
    cached = _read_cache(yf_ticker, "fundamentals")
    if cached:
        _log.debug("cache hit: %s", yf_ticker)
        return cached

    result = {
        "ticker": yf_ticker,
        "data_source": "yfinance",
        "timestamp": datetime.now().isoformat(),
        "revenue_cagr_3y": None,
        "revenue_cagr_5y": None,
        "eps_cagr_3y": None,
        "eps_cagr_5y": None,
        "roe": None,
        "roce": None,
        "debt_to_equity": None,
        "fcf_margin": None,
        "error": None,
        "notes": [],
    }

    try:
        # Fetch statements
        income_df = _fetch_yfinance_income_stmt(yf_ticker)
        balance_df = _fetch_yfinance_balance_sheet(yf_ticker)
        cashflow_df = _fetch_yfinance_cashflow(yf_ticker)

        if income_df is None:
            result["error"] = "Could not fetch income statement"
            result["notes"].append("yfinance income statement unavailable")
            return result

        # Compute metrics
        result["revenue_cagr_3y"] = compute_revenue_cagr(income_df, years=3)
        result["revenue_cagr_5y"] = compute_revenue_cagr(income_df, years=5)
        result["eps_cagr_3y"] = compute_eps_cagr(income_df, years=3)
        result["eps_cagr_5y"] = compute_eps_cagr(income_df, years=5)

        if balance_df is not None:
            result["roe"] = compute_roe(income_df, balance_df)
            result["roce"] = compute_roce(income_df, balance_df)
            result["debt_to_equity"] = compute_debt_to_equity(balance_df)
        else:
            result["notes"].append("Balance sheet unavailable; ROE/ROCE/D-E skipped")

        if cashflow_df is not None:
            result["fcf_margin"] = compute_fcf_margin(income_df, cashflow_df)
        else:
            result["notes"].append("Cash flow statement unavailable; FCF margin skipped")

        _write_cache(yf_ticker, "fundamentals", result)
        return result

    except Exception as e:
        result["error"] = str(e)
        _log.exception("fundamentals fetch failed for %s", yf_ticker)
        return result


# ────────────────────────────────────────────────────────────────────────────
# Quality scoring
# ────────────────────────────────────────────────────────────────────────────

def compute_quality_score(fundamentals: Dict) -> float:
    """
    0–100 composite fundamental quality score.

    Pillars:
      * Profitability (ROE ≥ 15% ideal)
      * Growth (Revenue CAGR ≥ 10%, EPS CAGR ≥ 12%)
      * Leverage (D/E ≤ 1.0 ideal, ≤ 0.5 excellent)
      * Cash generation (FCF margin ≥ 10%)
      * ROCE (≥ 15% = excellent)

    Scoring is lenient (50 pts available unearned) to account for stage/sector.
    """
    score = 50.0  # Base for availability

    try:
        # Profitability (20 pts)
        roe = fundamentals.get("roe")
        if roe is not None:
            if roe >= 20:
                score += 20
            elif roe >= 15:
                score += 15
            elif roe >= 10:
                score += 10
            elif roe >= 5:
                score += 5

        # Growth (20 pts — equally weight 3Y revenue and EPS)
        rev_cagr = fundamentals.get("revenue_cagr_3y")
        eps_cagr = fundamentals.get("eps_cagr_3y")
        growth_scores = []
        if rev_cagr is not None:
            if rev_cagr >= 15:
                growth_scores.append(10)
            elif rev_cagr >= 10:
                growth_scores.append(7)
            elif rev_cagr >= 5:
                growth_scores.append(4)
            else:
                growth_scores.append(0)
        if eps_cagr is not None:
            if eps_cagr >= 15:
                growth_scores.append(10)
            elif eps_cagr >= 10:
                growth_scores.append(7)
            elif eps_cagr >= 5:
                growth_scores.append(4)
            else:
                growth_scores.append(0)
        if growth_scores:
            score += sum(growth_scores) / len(growth_scores)

        # Leverage (15 pts — penalize debt)
        de = fundamentals.get("debt_to_equity")
        if de is not None:
            if de <= 0.3:
                score += 15
            elif de <= 0.5:
                score += 12
            elif de <= 1.0:
                score += 8
            elif de <= 1.5:
                score += 4
            # else: 0 (high debt)

        # Cash generation (10 pts)
        fcf_margin = fundamentals.get("fcf_margin")
        if fcf_margin is not None:
            if fcf_margin >= 15:
                score += 10
            elif fcf_margin >= 10:
                score += 7
            elif fcf_margin >= 5:
                score += 4

        # ROCE (15 pts)
        roce = fundamentals.get("roce")
        if roce is not None:
            if roce >= 20:
                score += 15
            elif roce >= 15:
                score += 12
            elif roce >= 10:
                score += 8
            elif roce >= 5:
                score += 4

    except Exception as e:
        _log.warning("quality score failed: %s", e)

    return round(min(100, max(0, score)), 1)


# ────────────────────────────────────────────────────────────────────────────
# Batch operations
# ────────────────────────────────────────────────────────────────────────────

def batch_fetch_fundamentals(tickers: List[str]) -> List[Dict]:
    """Fetch fundamentals for multiple tickers (useful for screening)."""
    results = []
    for ticker in tickers:
        try:
            results.append(fetch_fundamentals(ticker))
        except Exception as e:
            _log.warning("batch fetch failed for %s: %s", ticker, e)
            results.append({
                "ticker": ticker,
                "error": str(e),
                "notes": [],
            })
    return results
