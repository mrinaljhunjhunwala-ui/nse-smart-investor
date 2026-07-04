"""analysis/portfolio_risk.py — portfolio risk & performance analytics (Phase 1).

The keystone is the reconstructed NAV / equity curve (holdings × historical prices);
Max Drawdown, Sharpe, Sortino and Calmar all derive from it. Beta is delegated to the
existing analysis/hedging engine; correlation + risk-contribution come from the holdings'
return panel.

Reuses existing infrastructure:
  * data.fetcher.fetch_single  — tiered (Angel→Stooq→Yahoo), cached price history
  * analysis.hedging           — portfolio/stock beta vs Nifty (no re-implementation)

METHODOLOGY / LIMITATIONS (surfaced to users):
  * The NAV curve assumes TODAY's holdings were held CONSTANT over the lookback — it is a
    "what if you'd held this exact book over the past N days" curve, not your realised
    history. It ignores past additions/sells, dividends and transaction costs.
  * Metrics are annualised assuming 252 trading days; risk-free rate defaults to 6.5% p.a.
  * Names lacking sufficient price history are dropped (and listed) — a survivorship caveat.
  * Confidence is gated on lookback length (short windows → low confidence).
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import date
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

_log = logging.getLogger("portfolio_risk")

TRADING_DAYS = 252
DEFAULT_RF_ANNUAL = 0.065          # ~India 10Y G-Sec; configurable
_NIFTY = "^NSEI"


@dataclass
class PositionRisk:
    ticker: str
    weight_pct: float
    beta: Optional[float]
    risk_contribution_pct: Optional[float]   # share of portfolio variance from this name


@dataclass
class PortfolioRiskResult:
    period: str
    n_holdings: int
    holdings_used: List[str]
    holdings_dropped: List[str]                 # no/insufficient price history
    nav_curve: Optional[pd.Series] = None       # index=date, value=portfolio value (INR)
    daily_returns: Optional[pd.Series] = None
    n_days: int = 0
    start_value: Optional[float] = None
    end_value: Optional[float] = None
    total_return_pct: Optional[float] = None
    annualized_return_pct: Optional[float] = None
    annualized_vol_pct: Optional[float] = None
    max_drawdown_pct: Optional[float] = None
    max_dd_peak: Optional[date] = None
    max_dd_trough: Optional[date] = None
    sharpe: Optional[float] = None
    sortino: Optional[float] = None
    calmar: Optional[float] = None
    portfolio_beta: Optional[float] = None
    correlation_matrix: Optional[pd.DataFrame] = None
    risk_contributions: List[PositionRisk] = field(default_factory=list)
    rf_annual: float = DEFAULT_RF_ANNUAL
    confidence: str = "none"
    notes: List[str] = field(default_factory=list)
    # ── interpretation layer (IMPROVE: detect/disclose, no NAV change) ──────
    affected_weight_pct: Optional[float] = None   # % of weight bought within the lookback
    affected_holdings: List[str] = field(default_factory=list)
    n_affected: int = 0
    window_start: Optional[date] = None
    purchase_dates_known: bool = False
    disclosure: str = ""
    confidence_reason: str = ""
    error: Optional[str] = None

    # ── metric classification (display robust vs hypothetical separately) ───
    def performance_metrics(self):
        """HYPOTHETICAL performance metrics — biased by the constant-holdings curve."""
        return [("CAGR (Ann. Return)", self.annualized_return_pct, "%"),
                ("Total Return", self.total_return_pct, "%"),
                ("Sharpe", self.sharpe, ""), ("Sortino", self.sortino, ""),
                ("Calmar", self.calmar, ""), ("Max Drawdown", self.max_drawdown_pct, "%")]

    def risk_metrics(self):
        """ROBUST risk metrics — current-book snapshots, unaffected by the assumption."""
        return [("Portfolio Beta", self.portfolio_beta, ""),
                ("Annualised Volatility", self.annualized_vol_pct, "%")]


# Fixed taxonomy (per PORTFOLIO_NAV_ASSUMPTION_AUDIT.md severity findings)
ROBUST_RISK_METRICS = ("Portfolio Beta", "Annualised Volatility", "Correlation",
                       "Risk Contribution")
HYPOTHETICAL_PERF_METRICS = ("CAGR (Ann. Return)", "Total Return", "Sharpe", "Sortino",
                             "Calmar", "Max Drawdown")


# ── individual, unit-testable metric functions ─────────────────────────────────
def max_drawdown(nav: pd.Series) -> Tuple[Optional[float], Optional[date], Optional[date]]:
    """Worst peak-to-trough decline (as a negative %). Returns (dd_pct, peak, trough)."""
    if nav is None or len(nav) < 2:
        return None, None, None
    running_max = nav.cummax()
    drawdown = nav / running_max - 1.0
    trough_idx = drawdown.idxmin()
    dd = float(drawdown.loc[trough_idx])
    peak_idx = nav.loc[:trough_idx].idxmax()
    return round(dd * 100, 2), _as_date(peak_idx), _as_date(trough_idx)


def sharpe_ratio(daily_returns: pd.Series, rf_annual: float = DEFAULT_RF_ANNUAL) -> Optional[float]:
    if daily_returns is None or len(daily_returns) < 2:
        return None
    sd = daily_returns.std()
    if sd == 0 or math.isnan(sd):
        return None
    rf_daily = (1 + rf_annual) ** (1 / TRADING_DAYS) - 1
    return round((daily_returns.mean() - rf_daily) / sd * math.sqrt(TRADING_DAYS), 2)


def sortino_ratio(daily_returns: pd.Series, rf_annual: float = DEFAULT_RF_ANNUAL) -> Optional[float]:
    if daily_returns is None or len(daily_returns) < 2:
        return None
    rf_daily = (1 + rf_annual) ** (1 / TRADING_DAYS) - 1
    downside = np.minimum(0.0, daily_returns - rf_daily)
    dd = math.sqrt((downside ** 2).mean())
    if dd == 0 or math.isnan(dd):
        return None
    return round((daily_returns.mean() - rf_daily) / dd * math.sqrt(TRADING_DAYS), 2)


def calmar_ratio(annualized_return_pct: Optional[float],
                 max_dd_pct: Optional[float]) -> Optional[float]:
    if annualized_return_pct is None or not max_dd_pct:
        return None
    if abs(max_dd_pct) < 1e-9:
        return None
    return round(annualized_return_pct / abs(max_dd_pct), 2)


def correlation_matrix(returns_df: pd.DataFrame) -> Optional[pd.DataFrame]:
    if returns_df is None or returns_df.shape[1] < 2 or len(returns_df) < 5:
        return None
    return returns_df.corr().round(2)


def risk_contributions(returns_df: pd.DataFrame, weights: Dict[str, float]
                       ) -> Dict[str, float]:
    """Component contribution to portfolio VARIANCE, as % (sums to ~100)."""
    cols = [c for c in returns_df.columns if c in weights]
    if len(cols) == 0 or len(returns_df) < 5:
        return {}
    if len(cols) == 1:
        return {cols[0]: 100.0}
    w = np.array([weights[c] for c in cols], dtype=float)
    s = w.sum()
    if s <= 0:
        return {}
    w = w / s
    cov = returns_df[cols].cov().values
    port_var = float(w @ cov @ w)
    if port_var <= 0:
        return {}
    cctr = w * (cov @ w)                 # component contribution to variance
    return {c: round(float(cctr[i] / port_var * 100), 2) for i, c in enumerate(cols)}


# ── interpretation helpers (detect / classify / disclose — no NAV change) ──────
def _window_label(period: str) -> str:
    return {"6mo": "6-month", "1y": "1-year", "2y": "2-year", "3y": "3-year",
            "5y": "5-year"}.get(period, period)


def detect_recent_purchases(holdings_dates: Dict[str, Optional[date]],
                            window_start: Optional[date],
                            weights: Dict[str, float]) -> dict:
    """Which holdings were bought INSIDE the lookback window (date_bought > window_start),
    and what % of portfolio weight they represent. holdings_dates: ticker -> date_bought|None."""
    affected, affected_w, dated = [], 0.0, 0
    for tkr, w in weights.items():
        db = holdings_dates.get(tkr)
        if db is not None:
            dated += 1
            if window_start is not None and db > window_start:
                affected.append(tkr.replace(".NS", ""))
                affected_w += w
    return {"affected_holdings": affected, "n_affected": len(affected),
            "affected_weight_pct": round(affected_w * 100, 1) if dated else None,
            "dated_coverage": dated}


def adjust_confidence(base: str, affected_weight_pct: Optional[float]) -> Tuple[str, str]:
    """Downgrade confidence when a large weight was bought inside the window."""
    order = ["low", "medium", "high"]
    if affected_weight_pct is None:
        return base, "Purchase dates unavailable — confidence reflects lookback length only."
    if affected_weight_pct >= 50:
        return "low", (f"{affected_weight_pct:.0f}% of weight was bought within the lookback — "
                       "reward ratios are largely hypothetical, so confidence is capped at low.")
    if affected_weight_pct >= 25:
        downgraded = order[max(0, order.index(base) - 1)]
        return downgraded, (f"{affected_weight_pct:.0f}% of weight was bought within the lookback — "
                            f"reward ratios are partly hypothetical, so confidence reduced to "
                            f"{downgraded}.")
    return base, (f"Only {affected_weight_pct:.0f}% of weight was bought within the lookback — "
                  "reward ratios are largely representative of a held book.")


def build_disclosure(period: str, rec: dict) -> str:
    """Specific, weight-aware disclosure string."""
    wl = _window_label(period)
    awp = rec.get("affected_weight_pct")
    n = rec.get("n_affected", 0)
    if awp is None:
        return (f"Purchase dates unavailable — cannot verify how much of the book was held for the "
                f"full {wl} lookback. Treat the performance ratios (Sharpe / Sortino / Calmar / CAGR) "
                f"as hypothetical current-book analytics; risk metrics remain valid.")
    if awp <= 0.0:
        return (f"All holdings predate the {wl} lookback — the NAV matches a true buy-and-hold, so "
                f"the performance ratios are reliable for this book.")
    plural = "s" if n != 1 else ""
    return (f"{awp:.0f}% of portfolio weight ({n} holding{plural}) was purchased within the selected "
            f"{wl} lookback period. Performance ratios should be interpreted as hypothetical "
            f"current-book analytics rather than realized portfolio performance. Risk metrics "
            f"(beta, correlation, risk contribution, volatility) remain valid.")


def _parse_date(x) -> Optional[date]:
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return None
    if isinstance(x, date):
        return x
    try:
        return pd.Timestamp(x).date()
    except Exception as e:
        _log.debug("date coercion failed for %r: %s", x, e)
        return None


# ── orchestrator ────────────────────────────────────────────────────────────
def compute_portfolio_risk(holdings: List[Dict], period: str = "1y",
                           rf_annual: float = DEFAULT_RF_ANNUAL,
                           price_loader=None) -> PortfolioRiskResult:
    """holdings: list of {"ticker": str, "quantity": float}. price_loader is injectable
    for tests (defaults to data.fetcher.fetch_single)."""
    holds = []
    for h in holdings:
        t, q = h.get("ticker"), float(h.get("quantity") or 0)
        if t and q > 0:
            holds.append((t, q, _parse_date(h.get("date_bought"))))
    res = PortfolioRiskResult(period=period, n_holdings=len(holds), rf_annual=rf_annual,
                              holdings_used=[], holdings_dropped=[])
    if not holds:
        res.error = "no holdings with positive quantity"
        return res

    if price_loader is None:
        from data.fetcher import fetch_single as price_loader   # reuse tiered/cached fetch

    closes: Dict[str, pd.Series] = {}
    qty: Dict[str, float] = {}
    dates: Dict[str, Optional[date]] = {}
    for tkr, q, db in holds:
        try:
            df = price_loader(tkr, period=period)
            s = df["Close"].dropna() if df is not None and not df.empty else None
        except Exception as e:
            _log.warning("price fetch failed for %s: %s", tkr, e)
            s = None
        if s is None or len(s) < 30:
            res.holdings_dropped.append(tkr.replace(".NS", ""))
            continue
        closes[tkr] = s
        qty[tkr] = q
        dates[tkr] = db
        res.holdings_used.append(tkr.replace(".NS", ""))

    if not closes:
        res.error = "no holdings had usable price history"
        res.notes.append("Every holding lacked ≥30 days of price history.")
        return res

    # align on common dates → price panel
    panel = pd.DataFrame(closes).dropna()
    if len(panel) < 30:
        res.error = "insufficient overlapping price history across holdings"
        return res

    # NAV = Σ qty × close  (constant-quantity reconstruction)
    nav = sum(panel[t] * qty[t] for t in panel.columns)
    nav.name = "NAV"
    daily = nav.pct_change().dropna()
    res.nav_curve, res.daily_returns, res.n_days = nav, daily, len(nav)

    res.start_value, res.end_value = float(nav.iloc[0]), float(nav.iloc[-1])
    res.total_return_pct = round((res.end_value / res.start_value - 1) * 100, 2)
    yrs = max((len(nav) - 1) / TRADING_DAYS, 1e-6)
    res.annualized_return_pct = round(((res.end_value / res.start_value) ** (1 / yrs) - 1) * 100, 2)
    res.annualized_vol_pct = round(float(daily.std()) * math.sqrt(TRADING_DAYS) * 100, 2)

    res.max_drawdown_pct, res.max_dd_peak, res.max_dd_trough = max_drawdown(nav)
    res.sharpe = sharpe_ratio(daily, rf_annual)
    res.sortino = sortino_ratio(daily, rf_annual)
    res.calmar = calmar_ratio(res.annualized_return_pct, res.max_drawdown_pct)

    # weights (current value) for beta + risk contribution
    latest_val = {t: qty[t] * float(panel[t].iloc[-1]) for t in panel.columns}
    total_val = sum(latest_val.values()) or 1.0
    weights = {t: latest_val[t] / total_val for t in panel.columns}

    returns_panel = panel.pct_change().dropna()
    res.correlation_matrix = correlation_matrix(returns_panel)
    rc = risk_contributions(returns_panel, weights)

    # beta — reuse existing engine
    beta_by_ticker: Dict[str, Optional[float]] = {}
    try:
        from analysis.hedging import calculate_portfolio_beta
        beta_out = calculate_portfolio_beta(
            [{"ticker": t, "value_rs": latest_val[t]} for t in panel.columns], period=period)
        res.portfolio_beta = beta_out.get("portfolio_beta")
        for hb in beta_out.get("holdings_beta", []):
            b = hb.get("beta")
            beta_by_ticker[hb["ticker"]] = None if (b is None or (isinstance(b, float) and math.isnan(b))) else b
    except Exception as e:
        _log.warning("beta engine failed: %s", e)

    for t in panel.columns:
        res.risk_contributions.append(PositionRisk(
            ticker=t.replace(".NS", ""),
            weight_pct=round(weights[t] * 100, 2),
            beta=beta_by_ticker.get(t),
            risk_contribution_pct=rc.get(t)))
    res.risk_contributions.sort(key=lambda p: (p.risk_contribution_pct or -1), reverse=True)

    # ── interpretation: detect recent purchases, adjust confidence, disclose ──
    res.window_start = _as_date(nav.index[0])
    rec = detect_recent_purchases({t: dates.get(t) for t in panel.columns},
                                  res.window_start, weights)
    res.affected_weight_pct = rec["affected_weight_pct"]
    res.affected_holdings = rec["affected_holdings"]
    res.n_affected = rec["n_affected"]
    res.purchase_dates_known = rec["dated_coverage"] > 0
    res.disclosure = build_disclosure(period, rec)

    base_conf = "low" if res.n_days < 90 else "medium" if res.n_days < 180 else "high"
    res.confidence, res.confidence_reason = adjust_confidence(base_conf, res.affected_weight_pct)

    res.notes = [
        "NAV reconstructed from current holdings held constant over the lookback "
        "(ignores past buys/sells, dividends, costs) — a 'what-if you held this book' curve.",
        f"Annualised on {TRADING_DAYS} trading days; risk-free rate {rf_annual*100:.1f}% p.a.",
        "Beta is vs Nifty 50 (reused analysis/hedging engine).",
        f"Lookback: {res.n_days} trading days (base confidence "
        f"{'low' if res.n_days < 90 else 'medium' if res.n_days < 180 else 'high'}).",
        res.confidence_reason,
    ]
    if res.holdings_dropped:
        res.notes.append("Excluded (insufficient history): " + ", ".join(res.holdings_dropped))
    return res


# ── helpers ────────────────────────────────────────────────────────────────
def _as_date(idx) -> Optional[date]:
    try:
        return pd.Timestamp(idx).date()
    except Exception as e:
        _log.debug("_as_date: could not parse %r as a date: %s", idx, e)
        return None
