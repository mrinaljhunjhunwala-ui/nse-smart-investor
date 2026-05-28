"""
analysis/hedging.py
Portfolio-level hedging analysis for Indian equity portfolios.

Functions
─────────
    calculate_stock_beta(ticker, period)           → float
    calculate_portfolio_beta(holdings, period)     → dict
    hedge_sizing(portfolio_value, beta)            → dict
    suggest_hedge(portfolio_value, holdings, vix)  → dict (full recommendation)

All data is fetched from yfinance (EOD daily bars).
Benchmark: Nifty 50 (^NSEI)
"""

from __future__ import annotations

import json
import urllib.request
import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple

from data.fetcher import fetch_single

# NSE Nifty 50 — hedge benchmark
_NIFTY = "^NSEI"

# Nifty futures lot size (standard)
_NIFTY_LOT = 25

# Approximate Nifty 50-lot notional for index hedge instruments
_NIFTY_FUTURE_LOT_VALUE_RS = 25 * 23_000  # ~5.75L per lot at Nifty ~23,000


# ─────────────────────────────────────────────────────────────────────────────
# Single-stock beta vs Nifty
# ─────────────────────────────────────────────────────────────────────────────

def calculate_stock_beta(
    ticker: str,
    period: str = "1y",
    nifty_df: Optional[pd.DataFrame] = None,
) -> float:
    """
    Compute rolling beta of a single stock vs Nifty 50.

    Beta = Cov(stock_returns, nifty_returns) / Var(nifty_returns)

    Args:
        ticker    : yfinance symbol (e.g. 'TCS.NS')
        period    : data window (default '1y')
        nifty_df  : pre-fetched Nifty daily close DataFrame (avoids re-fetch)

    Returns:
        beta (float), or np.nan on failure.
    """
    try:
        stock_df = fetch_single(ticker, period=period)
        if stock_df.empty or len(stock_df) < 50:
            return np.nan

        if nifty_df is None:
            nifty_df = fetch_single(_NIFTY, period=period)

        stock_ret = stock_df["Close"].pct_change().dropna()
        nifty_ret = nifty_df["Close"].pct_change().dropna()

        # Align on common dates
        common_idx = stock_ret.index.intersection(nifty_ret.index)
        if len(common_idx) < 30:
            return np.nan

        s = stock_ret.loc[common_idx]
        n = nifty_ret.loc[common_idx]

        cov_matrix = np.cov(s.values, n.values)
        beta = cov_matrix[0, 1] / cov_matrix[1, 1] if cov_matrix[1, 1] != 0 else np.nan
        return round(float(beta), 3)

    except Exception:
        return np.nan


# ─────────────────────────────────────────────────────────────────────────────
# Portfolio beta
# ─────────────────────────────────────────────────────────────────────────────

def calculate_portfolio_beta(
    holdings: List[Dict],
    period: str = "1y",
) -> Dict:
    """
    Compute the weighted-average beta of a portfolio vs Nifty 50.

    Args:
        holdings : list of dicts with keys:
                       ticker   (str)   — yfinance symbol
                       value_rs (float) — current market value in Rs
        period   : data lookback for beta calculation

    Returns dict:
        {
            "portfolio_beta" : float,
            "total_value_rs" : float,
            "holdings_beta"  : [{"ticker", "value_rs", "weight", "beta", "contrib"},...],
            "interpretation" : str,
            "needs_hedge"    : bool,
        }
    """
    if not holdings:
        return {"portfolio_beta": 1.0, "total_value_rs": 0.0,
                "holdings_beta": [], "interpretation": "Empty portfolio",
                "needs_hedge": False}

    # Fetch Nifty once and reuse
    try:
        nifty_df = fetch_single(_NIFTY, period=period)
    except Exception:
        nifty_df = None

    total_value = sum(h["value_rs"] for h in holdings if "value_rs" in h)
    if total_value <= 0:
        total_value = 1.0

    holding_details = []
    weighted_beta = 0.0

    for h in holdings:
        tkr    = h.get("ticker", "")
        val    = float(h.get("value_rs", 0))
        weight = val / total_value
        beta   = calculate_stock_beta(tkr, period=period, nifty_df=nifty_df)

        contrib = weight * beta if not np.isnan(beta) else 0.0
        weighted_beta += contrib

        holding_details.append({
            "ticker":  tkr,
            "value_rs": round(val, 0),
            "weight":   round(weight * 100, 2),   # as %
            "beta":     beta,
            "contrib":  round(contrib, 4),
        })

    pb = round(weighted_beta, 3)

    if pb < 0.5:
        interpretation = f"Low beta ({pb}) — portfolio is defensive / lower-volatility than market."
    elif pb < 0.9:
        interpretation = f"Moderate beta ({pb}) — portfolio moves slightly less than market."
    elif pb < 1.2:
        interpretation = f"Market beta ({pb}) — portfolio tracks Nifty closely."
    elif pb < 1.5:
        interpretation = f"High beta ({pb}) — portfolio amplifies market moves. Consider partial hedge."
    else:
        interpretation = f"Very high beta ({pb}) — portfolio is highly leveraged to market. Hedge recommended."

    needs_hedge = pb > 1.2

    return {
        "portfolio_beta":  pb,
        "total_value_rs":  round(total_value, 0),
        "holdings_beta":   holding_details,
        "interpretation":  interpretation,
        "needs_hedge":     needs_hedge,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Hedge sizing
# ─────────────────────────────────────────────────────────────────────────────

def hedge_sizing(
    portfolio_value: float,
    portfolio_beta:  float,
    hedge_ratio:     float = 0.5,     # hedge 50% of market exposure by default
    nifty_spot:      float = 23_000,  # approximate; fetched live if 0
) -> Dict:
    """
    Compute the number of Nifty Futures lots needed to hedge a portfolio.

    Hedge notional = portfolio_value × portfolio_beta × hedge_ratio
    Lots needed    = hedge_notional / (nifty_spot × _NIFTY_LOT)

    Args:
        portfolio_value : Total portfolio market value in Rs
        portfolio_beta  : Weighted portfolio beta vs Nifty
        hedge_ratio     : Fraction of beta exposure to hedge (0–1)
        nifty_spot      : Current Nifty 50 level (uses live fetch if 0)

    Returns dict:
        hedge_notional_rs, lots_needed, hedge_pct, description
    """
    # Live Nifty price if not provided
    if nifty_spot <= 0:
        try:
            nifty_df   = fetch_single(_NIFTY, period="5d")
            nifty_spot = float(nifty_df["Close"].iloc[-1])
        except Exception:
            nifty_spot = 23_000   # fallback

    lot_value      = nifty_spot * _NIFTY_LOT
    hedge_notional = portfolio_value * portfolio_beta * hedge_ratio
    lots_needed    = max(0, round(hedge_notional / lot_value))

    actual_hedge_pct = (lots_needed * lot_value) / max(portfolio_value, 1) * 100

    return {
        "nifty_spot":       round(nifty_spot, 0),
        "lot_size":         _NIFTY_LOT,
        "lot_value_rs":     round(lot_value, 0),
        "hedge_ratio":      hedge_ratio,
        "hedge_notional_rs": round(hedge_notional, 0),
        "lots_needed":      lots_needed,
        "hedge_value_rs":   round(lots_needed * lot_value, 0),
        "actual_hedge_pct": round(actual_hedge_pct, 1),
        "description":      (
            f"Short {lots_needed} Nifty Futures lot(s) to hedge "
            f"~{actual_hedge_pct:.0f}% of portfolio beta exposure "
            f"(portfolio beta={portfolio_beta}, hedge ratio={hedge_ratio*100:.0f}%)"
        ),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Full hedge recommendation
# ─────────────────────────────────────────────────────────────────────────────

def suggest_hedge(
    portfolio_value: float,
    holdings:        List[Dict],
    vix:             Optional[float] = None,
    period:          str = "1y",
) -> Dict:
    """
    End-to-end hedge recommendation for an Indian equity portfolio.

    Steps:
        1. Compute portfolio beta from holdings
        2. Compute VIX-adjusted hedge ratio (higher VIX → hedge more)
        3. Compute Nifty futures lots needed
        4. Return plain-English recommendation

    Args:
        portfolio_value : Total portfolio value in Rs
        holdings        : [{"ticker": str, "value_rs": float}, ...]
        vix             : India VIX level (fetched live if None)
        period          : Beta lookback window

    Returns:
        Full dict with beta_result, sizing_result, recommendation, urgency
    """
    # Fetch VIX if not provided — Yahoo Finance chart API with cookie+crumb
    if vix is None:
        try:
            from data.fetcher import _get_yf_crumb
            import urllib.parse as _up
            _opener, _crumb = _get_yf_crumb()
            _cqs = f"&crumb={_up.quote(_crumb)}" if _crumb else ""
            _url = (f"https://query1.finance.yahoo.com/v8/finance/chart/%5EINDIAVIX"
                    f"?interval=1d&range=5d&includePrePost=false{_cqs}")
            _req = urllib.request.Request(
                _url, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
            with _opener.open(_req, timeout=8) as _r:
                _d = json.loads(_r.read())
            _closes = _d["chart"]["result"][0]["indicators"]["quote"][0]["close"]
            _valid  = [v for v in _closes if v is not None]
            vix = float(_valid[-1]) if _valid else 16.0
        except Exception:
            vix = 16.0

    beta_result = calculate_portfolio_beta(holdings, period=period)
    pb          = beta_result["portfolio_beta"]

    # VIX-adjusted hedge ratio
    #   VIX < 14 → hedge 25%  (calm market, minimal insurance)
    #   VIX 14-18 → hedge 40%
    #   VIX 18-22 → hedge 60%
    #   VIX > 22  → hedge 80% (elevated fear, hedge aggressively)
    if vix < 14:
        hedge_ratio = 0.25
        urgency     = "Low"
    elif vix < 18:
        hedge_ratio = 0.40
        urgency     = "Moderate"
    elif vix < 22:
        hedge_ratio = 0.60
        urgency     = "High"
    else:
        hedge_ratio = 0.80
        urgency     = "Urgent"

    sizing = hedge_sizing(
        portfolio_value=portfolio_value,
        portfolio_beta=pb,
        hedge_ratio=hedge_ratio,
    )

    # Build recommendation
    if pb <= 0.8:
        recommendation = (
            f"Portfolio beta {pb} is defensive — no hedge needed. "
            "Monitor if beta rises above 1.2 after new additions."
        )
        action = "HOLD — No hedge required"
    elif pb <= 1.2 and urgency in ("Low", "Moderate"):
        recommendation = (
            f"Portfolio beta {pb} is near market. "
            f"VIX={vix:.1f} ({urgency}). Consider optional {sizing['lots_needed']} lot hedge "
            f"if you expect volatility."
        )
        action = "OPTIONAL hedge"
    else:
        recommendation = (
            f"Portfolio beta {pb} is elevated. VIX={vix:.1f} ({urgency} risk). "
            f"Recommend: Short {sizing['lots_needed']} Nifty Futures lot(s) — "
            f"hedges ~{sizing['actual_hedge_pct']:.0f}% of beta exposure. "
            f"Cost: ~Rs {sizing['hedge_value_rs']:,.0f} margin required."
        )
        action = f"HEDGE: Short {sizing['lots_needed']} Nifty Futures"

    return {
        "action":          action,
        "urgency":         urgency,
        "recommendation":  recommendation,
        "vix":             round(vix, 1),
        "hedge_ratio_pct": round(hedge_ratio * 100, 0),
        "beta_result":     beta_result,
        "sizing":          sizing,
    }
