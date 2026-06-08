"""
analysis/portfolio_concentration.py — Position concentration & risk analytics.

Herfindahl-Hirschman Index (HHI):
  Standard market concentration metric. HHI = Σ (weight%)²
  HHI < 1500 = unconcentrated
  HHI 1500–2500 = moderately concentrated
  HHI > 2500 = highly concentrated

Usage:
  from analysis.portfolio_concentration import analyze_concentration
  result = analyze_concentration(holdings)  # holdings: [{"ticker": str, "weight_pct": float}, ...]
  print(result.hhi, result.top_5_weight, result.recommendation)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass
class ConcentrationResult:
    """Portfolio concentration analysis result."""
    total_holdings: int
    hhi: float  # Herfindahl-Hirschman Index (0–10000)
    hhi_category: str  # "Low", "Moderate", "High"
    top_1_weight: float  # Weight of largest position
    top_5_weight: float  # Sum of top 5
    top_10_weight: float  # Sum of top 10
    single_name_concentration: float  # % in top position
    sector_concentration: Optional[float]  # If available
    recommendation: str  # Plain English advice
    risk_level: str  # LOW / MEDIUM / HIGH


def calculate_hhi(weights: List[float]) -> float:
    """
    Herfindahl-Hirschman Index = Σ (weight%)²
    
    Range: 0–10000 (if weights are in %)
    < 1500  → unconcentrated
    1500–2500 → moderately concentrated
    > 2500  → highly concentrated
    """
    if not weights:
        return 0.0
    w = [max(0, min(100, w)) for w in weights]  # Clamp to [0, 100]
    return round(sum(x**2 for x in w), 2)


def analyze_concentration(holdings: List[Dict]) -> ConcentrationResult:
    """
    Analyze portfolio concentration across holdings.
    
    Args:
        holdings: list of dicts with keys:
            "ticker" (str, optional)
            "weight_pct" (float) — portfolio weight as %
            "sector" (str, optional)
    
    Returns:
        ConcentrationResult with HHI, top-N weights, risk level, and recommendations.
    """
    if not holdings:
        return ConcentrationResult(
            total_holdings=0, hhi=0, hhi_category="Unknown",
            top_1_weight=0, top_5_weight=0, top_10_weight=0,
            single_name_concentration=0,
            sector_concentration=None,
            recommendation="No holdings to analyze.",
            risk_level="N/A"
        )

    # Extract weights and sort descending
    weights = sorted(
        [float(h.get("weight_pct", 0)) for h in holdings if h.get("weight_pct")],
        reverse=True
    )
    
    if not weights:
        return ConcentrationResult(
            total_holdings=len(holdings), hhi=0, hhi_category="Unknown",
            top_1_weight=0, top_5_weight=0, top_10_weight=0,
            single_name_concentration=0,
            sector_concentration=None,
            recommendation="No valid weights found.",
            risk_level="N/A"
        )

    # Calculate HHI
    hhi = calculate_hhi(weights)
    if hhi < 1500:
        hhi_category = "Low"
        hhi_risk = "LOW"
    elif hhi < 2500:
        hhi_category = "Moderate"
        hhi_risk = "MEDIUM"
    else:
        hhi_category = "High"
        hhi_risk = "HIGH"

    # Top N concentrations
    top_1 = weights[0] if len(weights) > 0 else 0
    top_5 = sum(weights[:5]) if len(weights) > 0 else 0
    top_10 = sum(weights[:10]) if len(weights) > 0 else 0

    # Sector concentration (if available)
    sector_conc = None
    if all("sector" in h for h in holdings):
        sectors = {}
        for h in holdings:
            s = h["sector"]
            w = float(h.get("weight_pct", 0))
            sectors[s] = sectors.get(s, 0) + w
        if sectors:
            sector_weights = list(sectors.values())
            sector_conc = calculate_hhi(sector_weights)

    # Recommendation
    recs = []
    if top_1 > 30:
        recs.append(f"⚠️  Largest holding is {top_1:.1f}% — consider trimming to <25%.")
    if top_5 > 60:
        recs.append(f"Top 5 holdings account for {top_5:.1f}% — diversify beyond top positions.")
    if len(weights) < 5:
        recs.append(f"Only {len(weights)} holdings — add 2–3 more for better diversification.")
    if hhi > 2500:
        recs.append("HHI indicates high concentration risk. Rebalance toward more equal weights.")
    
    if not recs:
        recs.append("Concentration profile is healthy. Continue monitoring as weights shift.")

    recommendation = " ".join(recs)

    return ConcentrationResult(
        total_holdings=len(holdings),
        hhi=hhi,
        hhi_category=hhi_category,
        top_1_weight=round(top_1, 2),
        top_5_weight=round(top_5, 2),
        top_10_weight=round(top_10, 2),
        single_name_concentration=round(top_1, 2),
        sector_concentration=sector_conc,
        recommendation=recommendation,
        risk_level=hhi_risk,
    )


def concentration_grade(hhi: float) -> str:
    """Convert HHI to a letter grade for UI display."""
    if hhi < 1000:
        return "A"  # Excellent
    elif hhi < 1500:
        return "B"  # Good
    elif hhi < 2000:
        return "C"  # Acceptable
    elif hhi < 2500:
        return "D"  # Concerning
    else:
        return "F"  # High risk
