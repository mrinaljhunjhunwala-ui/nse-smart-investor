"""
analysis/portfolio_manager.py
Portfolio mark-to-market, health scoring, and plain-English recommendations
for non-traders.

CSV format (portfolio.csv):
    ticker, quantity, avg_buy_price, date_bought
    RELIANCE,10,1350.00,2024-01-15
    TCS,5,3800.00,2024-03-10
    ...

Usage:
    from analysis.portfolio_manager import PortfolioManager
    pm = PortfolioManager("portfolio.csv")
    summary = pm.mark_to_market()
    pm.print_summary(summary)
    pm.export_summary_csv(summary)
"""

from __future__ import annotations

import csv
import warnings
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")


# ─────────────────────────────────────────────────────────────────────────────
# Result dataclasses
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class HoldingResult:
    ticker:         str
    quantity:       float
    avg_buy_price:  float
    date_bought:    str
    current_price:  float
    invested:       float          # quantity × avg_buy_price
    current_value:  float          # quantity × current_price
    pnl:            float          # current_value - invested
    pnl_pct:        float          # pnl / invested × 100
    days_held:      int
    score:          float          # 0–100 composite score
    grade:          str            # A+…F
    action:         str            # STRONG BUY…EXIT
    signal:         str            # 🟢 BUY MORE / 🟡 HOLD / 🔴 CONSIDER SELLING
    headline:       str            # one-liner for UI card
    narrative:      str            # full paragraph
    sector:         str
    stop_loss:      float
    target:         float
    risk_reward:    float
    error:          str = ""       # non-empty if scoring failed


@dataclass
class PortfolioDiversification:
    sector_weights:     Dict[str, float]   # sector → % of portfolio
    top_sector:         str
    top_sector_pct:     float
    n_sectors:          int
    concentration_risk: str    # LOW / MEDIUM / HIGH / VERY HIGH
    advice:             str


@dataclass
class PortfolioSummary:
    generated_at:       str
    holdings:           List[HoldingResult]
    total_invested:     float
    total_current_value: float
    total_pnl:          float
    total_pnl_pct:      float
    portfolio_score:    float    # weighted average composite score
    portfolio_grade:    str
    best_holding:       Optional[HoldingResult]
    worst_holding:      Optional[HoldingResult]
    diversification:    PortfolioDiversification
    vix_regime:         str
    summary_narrative:  str      # 2–3 sentence overall take for non-traders


# ─────────────────────────────────────────────────────────────────────────────
# Traffic light helper
# ─────────────────────────────────────────────────────────────────────────────

def _traffic_light(action: str, pnl_pct: float) -> str:
    """Return 🟢 / 🟡 / 🔴 signal with a short label."""
    if action in ("STRONG BUY", "BUY"):
        return "🟢 ADD / BUY MORE"
    elif action in ("WATCHLIST",):
        return "🟡 HOLD — watching"
    elif action in ("HOLD",):
        return "🟡 HOLD"
    elif action in ("CAUTION",):
        if pnl_pct > 15:
            return "🟡 CONSIDER TRIMMING"
        return "🔴 REDUCE POSITION"
    else:  # EXIT
        return "🔴 CONSIDER SELLING"


# ─────────────────────────────────────────────────────────────────────────────
# Diversification analyser
# ─────────────────────────────────────────────────────────────────────────────

def _analyse_diversification(
    holdings: List[HoldingResult],
) -> PortfolioDiversification:
    sector_values: Dict[str, float] = {}
    total = sum(h.current_value for h in holdings if not h.error)
    if total <= 0:
        return PortfolioDiversification(
            sector_weights={}, top_sector="N/A", top_sector_pct=0,
            n_sectors=0, concentration_risk="UNKNOWN",
            advice="Could not compute diversification — pricing data missing.",
        )
    for h in holdings:
        if h.error:
            continue
        sector_values[h.sector] = sector_values.get(h.sector, 0) + h.current_value

    sector_weights = {s: round(v / total * 100, 1) for s, v in sector_values.items()}
    top_sector = max(sector_weights, key=sector_weights.__getitem__)
    top_pct = sector_weights[top_sector]
    n_sectors = len(sector_weights)

    if top_pct > 60:
        risk = "VERY HIGH"
        advice = (
            f"Over 60% of your portfolio is in {top_sector}. "
            "A single sector event can hurt significantly. Consider spreading across 5–8 sectors."
        )
    elif top_pct > 45:
        risk = "HIGH"
        advice = (
            f"{top_sector} makes up {top_pct:.0f}% of your portfolio. "
            "Aim to bring any single sector below 40%."
        )
    elif top_pct > 30 or n_sectors < 4:
        risk = "MEDIUM"
        advice = (
            f"Reasonable diversification but {top_sector} is dominant at {top_pct:.0f}%. "
            "Adding 1–2 stocks from other sectors would reduce risk."
        )
    else:
        risk = "LOW"
        advice = (
            f"Good diversification across {n_sectors} sectors. "
            "Continue monitoring sector weights as markets move."
        )

    return PortfolioDiversification(
        sector_weights=sector_weights,
        top_sector=top_sector,
        top_sector_pct=top_pct,
        n_sectors=n_sectors,
        concentration_risk=risk,
        advice=advice,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Overall portfolio narrative
# ─────────────────────────────────────────────────────────────────────────────

def _portfolio_narrative(
    summary: PortfolioSummary,
    holdings: List[HoldingResult],
) -> str:
    pnl_word = "gained" if summary.total_pnl >= 0 else "lost"
    pnl_abs = abs(summary.total_pnl)
    pnl_pct = abs(summary.total_pnl_pct)

    buy_count = sum(1 for h in holdings if "BUY" in h.action)
    sell_count = sum(1 for h in holdings if h.action in ("CAUTION", "EXIT"))

    parts = [
        f"Your portfolio of ₹{summary.total_invested:,.0f} has {pnl_word} "
        f"₹{pnl_abs:,.0f} ({pnl_pct:.1f}%) since you invested.",
    ]
    if buy_count:
        parts.append(
            f"{buy_count} of your holdings look strong right now "
            f"— our model suggests they could be added to."
        )
    if sell_count:
        parts.append(
            f"{sell_count} holdings are showing weakness "
            f"— consider reviewing those positions."
        )

    # VIX context — compare uppercase so "fear"/"FEAR" both match
    _vix_upper = summary.vix_regime.upper()
    if "FEAR" in _vix_upper or "PANIC" in _vix_upper:
        parts.append(
            "Markets are currently fearful (VIX elevated). "
            "This is often a better time to hold or buy carefully, not to sell in panic."
        )
    elif "COMPLACENCY" in _vix_upper:
        parts.append(
            "Market volatility is very low right now — a good time to review "
            "your stops, as sharp moves can catch investors off guard."
        )
    else:
        parts.append(
            "Market conditions are broadly normal. "
            "Follow the individual stock signals below for actionable decisions."
        )

    return " ".join(parts)


# ─────────────────────────────────────────────────────────────────────────────
# Main PortfolioManager class
# ─────────────────────────────────────────────────────────────────────────────

class PortfolioManager:
    """
    Load a portfolio CSV, score every holding, and produce a plain-English
    summary suitable for non-traders.

    CSV must have columns: ticker, quantity, avg_buy_price, date_bought
    (date_bought is optional — defaults to today if missing)
    """

    def __init__(self, csv_path: str | Path):
        self.csv_path = Path(csv_path)
        self.holdings_raw = self._load_csv()

    # ── loader ────────────────────────────────────────────────────────────────

    def _load_csv(self) -> List[Dict]:
        rows = []
        with open(self.csv_path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                ticker = row.get("ticker", "").strip().upper()
                if not ticker:
                    continue
                # Normalise ticker suffix
                if not ticker.endswith(".NS") and not ticker.endswith(".BO"):
                    ticker = ticker + ".NS"
                rows.append({
                    "ticker": ticker,
                    "quantity": float(row.get("quantity", 0)),
                    "avg_buy_price": float(row.get("avg_buy_price", 0)),
                    "date_bought": row.get("date_bought", "").strip() or datetime.today().strftime("%Y-%m-%d"),
                })
        return rows

    # ── mark to market ────────────────────────────────────────────────────────

    def mark_to_market(self, parallel: bool = False) -> PortfolioSummary:
        """
        Score every holding and return a PortfolioSummary.
        Set parallel=True for faster processing (uses ThreadPoolExecutor).
        """
        from analysis.score import score_stock

        # VIX fetch via utils.vix (cookie+crumb auth, no yfinance, cloud-safe)
        try:
            from utils.vix import get_india_vix_regime
            vix_info = get_india_vix_regime()
        except Exception:
            vix_info = {"vix": None, "regime": "normal",
                        "allow_buy": True, "vix_pct_chg": 0.0}

        vix_regime = vix_info.get("regime", "normal")

        holdings: List[HoldingResult] = []

        if parallel:
            from concurrent.futures import ThreadPoolExecutor, wait as _wait
            pool = ThreadPoolExecutor(max_workers=4)
            try:
                futs = {pool.submit(self._score_holding, raw, vix_info): raw["ticker"]
                        for raw in self.holdings_raw}
                done, _ = _wait(list(futs.keys()), timeout=120)
                for fut in done:
                    try:
                        holdings.append(fut.result(timeout=0))
                    except Exception as e:
                        # A holding that fails here is retried by the sequential pass
                        # below (it won't be in scored_tickers). Log so a holding that
                        # fails BOTH paths — and silently drops out of the portfolio
                        # total/P&L — is at least diagnosable.
                        import logging as _lg
                        _lg.getLogger("portfolio").warning(
                            "parallel score failed for %s: %s (retrying sequentially)",
                            futs.get(fut, "?"), e)
            finally:
                pool.shutdown(wait=False)
            # Fall back to sequential for any that timed out
            scored_tickers = {h.ticker for h in holdings}
            for raw in self.holdings_raw:
                if raw["ticker"] not in scored_tickers:
                    holdings.append(self._score_holding(raw, vix_info))
        else:
            for raw in self.holdings_raw:
                holdings.append(self._score_holding(raw, vix_info))

        # Sort by portfolio weight (largest first)
        total_invested = sum(h.invested for h in holdings)
        if total_invested > 0:
            holdings.sort(key=lambda h: h.invested, reverse=True)

        total_current = sum(h.current_value for h in holdings)
        total_pnl = total_current - total_invested
        total_pnl_pct = (total_pnl / total_invested * 100) if total_invested > 0 else 0.0

        # Portfolio-level composite score (weighted by current value)
        scored = [h for h in holdings if not h.error]
        if scored:
            weights = np.array([h.current_value for h in scored])
            scores = np.array([h.score for h in scored])
            portfolio_score = float(np.average(scores, weights=weights))
        else:
            portfolio_score = 0.0

        portfolio_grade = _score_to_grade(portfolio_score)
        diversification = _analyse_diversification(holdings)

        best = max(scored, key=lambda h: h.pnl_pct) if scored else None
        worst = min(scored, key=lambda h: h.pnl_pct) if scored else None

        summary = PortfolioSummary(
            generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            holdings=holdings,
            total_invested=total_invested,
            total_current_value=total_current,
            total_pnl=total_pnl,
            total_pnl_pct=total_pnl_pct,
            portfolio_score=round(portfolio_score, 1),
            portfolio_grade=portfolio_grade,
            best_holding=best,
            worst_holding=worst,
            diversification=diversification,
            vix_regime=vix_regime,
            summary_narrative="",
        )
        summary.summary_narrative = _portfolio_narrative(summary, holdings)
        return summary

    # ── score single holding ──────────────────────────────────────────────────

    def _score_holding(self, raw: Dict, vix_info: Dict) -> HoldingResult:
        from analysis.score import score_stock

        ticker = raw["ticker"]
        qty = raw["quantity"]
        avg_price = raw["avg_buy_price"]
        date_bought = raw["date_bought"]

        invested = qty * avg_price

        # Days held
        try:
            bought_dt = datetime.strptime(date_bought, "%Y-%m-%d")
            days_held = (datetime.today() - bought_dt).days
        except Exception:
            days_held = 0

        try:
            cs = score_stock(ticker, period="1y", vix_info=vix_info)
            # Try to get a more current price (NSE live → yfinance fast_info → EOD)
            try:
                from utils.live_price import get_live_price
                live = get_live_price(ticker)
                current_price = live if (live and live > 0) else cs.price
            except Exception:
                current_price = cs.price
            current_value = qty * current_price
            pnl = current_value - invested
            pnl_pct = (pnl / invested * 100) if invested > 0 else 0.0
            signal = _traffic_light(cs.action, pnl_pct)

            return HoldingResult(
                ticker=ticker,
                quantity=qty,
                avg_buy_price=avg_price,
                date_bought=date_bought,
                current_price=current_price,
                invested=invested,
                current_value=current_value,
                pnl=pnl,
                pnl_pct=pnl_pct,
                days_held=days_held,
                score=cs.score,
                grade=cs.grade,
                action=cs.action,
                signal=signal,
                headline=cs.headline,
                narrative=cs.narrative,
                sector=cs.sector,
                stop_loss=cs.stop_loss,
                target=cs.target,
                risk_reward=cs.risk_reward,
                error="",
            )
        except Exception as e:
            return HoldingResult(
                ticker=ticker,
                quantity=qty,
                avg_buy_price=avg_price,
                date_bought=date_bought,
                current_price=0.0,
                invested=invested,
                current_value=invested,   # assume break-even if error
                pnl=0.0,
                pnl_pct=0.0,
                days_held=days_held,
                score=50.0,
                grade="C",
                action="HOLD",
                signal="🟡 HOLD",
                headline=f"Data unavailable for {ticker}",
                narrative=f"Could not fetch live data for {ticker}. Please check the ticker symbol.",
                sector="Unknown",
                stop_loss=avg_price * 0.92,
                target=avg_price * 1.15,
                risk_reward=1.875,
                error=str(e),
            )

    # ── pretty printer ────────────────────────────────────────────────────────

    def print_summary(self, summary: PortfolioSummary) -> None:
        pnl_sign = "+" if summary.total_pnl >= 0 else ""
        print("\n" + "═" * 60)
        print("  PORTFOLIO HEALTH REPORT")
        print(f"  {summary.generated_at}  |  VIX Regime: {summary.vix_regime}")
        print("═" * 60)
        print(f"  Invested       : ₹{summary.total_invested:>12,.0f}")
        print(f"  Current Value  : ₹{summary.total_current_value:>12,.0f}")
        print(f"  Total P&L      : {pnl_sign}₹{summary.total_pnl:>11,.0f}  "
              f"({pnl_sign}{summary.total_pnl_pct:.1f}%)")
        print(f"  Portfolio Score: {summary.portfolio_score:.0f}/100  [{summary.portfolio_grade}]")
        print()
        print(f"  {summary.summary_narrative}")
        print()
        print("─" * 60)
        print(f"  {'TICKER':<12} {'QTY':>6} {'BUY':>8} {'NOW':>8} {'P&L%':>7} "
              f"{'SCORE':>6} {'SIGNAL':<28}")
        print("─" * 60)
        for h in summary.holdings:
            pnl_str = f"{'+' if h.pnl_pct >= 0 else ''}{h.pnl_pct:.1f}%"
            score_str = f"{h.score:.0f} [{h.grade}]"
            print(f"  {h.ticker.replace('.NS',''):<12} {h.quantity:>6.0f} "
                  f"₹{h.avg_buy_price:>7,.0f} ₹{h.current_price:>7,.0f} "
                  f"{pnl_str:>7} {score_str:>8}  {h.signal}")
        print("─" * 60)
        if summary.best_holding:
            bh = summary.best_holding
            print(f"  Best:  {bh.ticker.replace('.NS','')} {'+' if bh.pnl_pct>=0 else ''}"
                  f"{bh.pnl_pct:.1f}%")
        if summary.worst_holding:
            wh = summary.worst_holding
            print(f"  Worst: {wh.ticker.replace('.NS','')} {'+' if wh.pnl_pct>=0 else ''}"
                  f"{wh.pnl_pct:.1f}%")
        print()
        div = summary.diversification
        print(f"  Diversification: {div.concentration_risk}")
        print(f"  {div.advice}")
        print("═" * 60 + "\n")

    # ── CSV export ────────────────────────────────────────────────────────────

    def export_summary_csv(
        self,
        summary: PortfolioSummary,
        output_path: Optional[str] = None,
    ) -> str:
        if output_path is None:
            output_path = str(Path.home() / "portfolio_summary.csv")

        fieldnames = [
            "ticker", "quantity", "avg_buy_price", "date_bought",
            "current_price", "invested", "current_value", "pnl", "pnl_pct",
            "days_held", "score", "grade", "action", "signal",
            "stop_loss", "target", "risk_reward", "sector", "headline",
        ]

        with open(output_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for h in summary.holdings:
                writer.writerow({
                    "ticker": h.ticker,
                    "quantity": h.quantity,
                    "avg_buy_price": round(h.avg_buy_price, 2),
                    "date_bought": h.date_bought,
                    "current_price": round(h.current_price, 2),
                    "invested": round(h.invested, 2),
                    "current_value": round(h.current_value, 2),
                    "pnl": round(h.pnl, 2),
                    "pnl_pct": round(h.pnl_pct, 2),
                    "days_held": h.days_held,
                    "score": round(h.score, 1),
                    "grade": h.grade,
                    "action": h.action,
                    "signal": h.signal.replace("🟢", "GREEN").replace("🟡", "YELLOW").replace("🔴", "RED"),
                    "stop_loss": round(h.stop_loss, 2),
                    "target": round(h.target, 2),
                    "risk_reward": round(h.risk_reward, 2),
                    "sector": h.sector,
                    "headline": h.headline,
                })

        print(f"Portfolio summary exported to: {output_path}")
        return output_path


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _score_to_grade(score: float) -> str:
    if score >= 88:
        return "A+"
    elif score >= 75:
        return "A"
    elif score >= 62:
        return "B"
    elif score >= 48:
        return "C"
    elif score >= 32:
        return "D"
    else:
        return "F"


# ─────────────────────────────────────────────────────────────────────────────
# Quick standalone usage
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    csv_file = sys.argv[1] if len(sys.argv) > 1 else "portfolio.csv"
    pm = PortfolioManager(csv_file)
    summary = pm.mark_to_market()
    pm.print_summary(summary)
    pm.export_summary_csv(summary)
