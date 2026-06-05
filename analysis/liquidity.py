"""analysis/liquidity.py — Liquidity Context (Phase C1).

Computes tradability signals from EXISTING OHLCV data only (`data.fetcher.fetch_single`
already returns a Volume column on every tier). No new data provider.

Outputs (a `LiquidityContext`):
  * Average Daily Volume (30d)         — shares
  * Average Daily Turnover (30d)       — ₹ (mean of Close × Volume)
  * Volume Trend (30d vs 90d)          — ratio + label
  * Liquidity Tier                     — High | Medium | Low | Illiquid

Turnover tiers are calibrated for NSE equities (₹, daily):
  High ≥ ₹25 cr · Medium ≥ ₹5 cr · Low ≥ ₹50 lakh · else Illiquid.

`compute_liquidity(df)` is PURE (takes a price frame); `liquidity_for_ticker` is the
integration seam that fetches via the existing tiered loader.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

# Turnover tier thresholds, in ₹ (daily average).
CR = 1e7                       # 1 crore = 10,000,000
TIER_HIGH = 25 * CR            # ≥ ₹25 cr/day
TIER_MEDIUM = 5 * CR          # ≥ ₹5 cr/day
TIER_LOW = 0.5 * CR           # ≥ ₹50 lakh/day
SHORT_WINDOW = 30
LONG_WINDOW = 90

TIERS = ("High", "Medium", "Low", "Illiquid")


def format_turnover(x: Optional[float]) -> str:
    """Human ₹ turnover, e.g. '₹42.3 cr' / '₹85 lakh' / '—'."""
    if x is None:
        return "—"
    if x >= CR:
        return f"₹{x / CR:,.1f} cr"
    if x >= 1e5:
        return f"₹{x / 1e5:,.0f} lakh"
    return f"₹{x:,.0f}"


@dataclass
class LiquidityContext:
    avg_daily_volume_30d: Optional[float] = None      # shares
    avg_daily_turnover_30d: Optional[float] = None    # ₹
    volume_trend_ratio: Optional[float] = None        # 30d avg vol / 90d avg vol
    volume_trend: Optional[str] = None                # "rising" | "stable" | "falling"
    liquidity_tier: str = "Unknown"                   # High | Medium | Low | Illiquid | Unknown
    n_days: int = 0
    reason: str = ""

    def to_dict(self) -> dict:
        return {"avg_daily_volume_30d": self.avg_daily_volume_30d,
                "avg_daily_turnover_30d": self.avg_daily_turnover_30d,
                "volume_trend_ratio": self.volume_trend_ratio,
                "volume_trend": self.volume_trend,
                "liquidity_tier": self.liquidity_tier,
                "n_days": self.n_days, "reason": self.reason}


def _tier_from_turnover(turnover: Optional[float]) -> str:
    if turnover is None:
        return "Unknown"
    if turnover >= TIER_HIGH:
        return "High"
    if turnover >= TIER_MEDIUM:
        return "Medium"
    if turnover >= TIER_LOW:
        return "Low"
    return "Illiquid"


def _trend_label(ratio: Optional[float]) -> Optional[str]:
    if ratio is None:
        return None
    if ratio >= 1.20:
        return "rising"
    if ratio <= 0.80:
        return "falling"
    return "stable"


def compute_liquidity(df) -> LiquidityContext:
    """Pure: compute liquidity context from a price frame with Close + Volume columns."""
    ctx = LiquidityContext()
    if df is None or getattr(df, "empty", True):
        ctx.reason = "no price data"
        return ctx
    if "Close" not in df.columns or "Volume" not in df.columns:
        ctx.reason = "price frame missing Close/Volume"
        return ctx

    sub = df[["Close", "Volume"]].dropna()
    sub = sub[(sub["Close"] > 0) & (sub["Volume"] >= 0)]
    ctx.n_days = len(sub)
    if ctx.n_days < SHORT_WINDOW:
        ctx.reason = f"need ≥{SHORT_WINDOW} days of volume; have {ctx.n_days}"
        return ctx

    last30 = sub.tail(SHORT_WINDOW)
    ctx.avg_daily_volume_30d = round(float(last30["Volume"].mean()), 2)
    ctx.avg_daily_turnover_30d = round(float((last30["Close"] * last30["Volume"]).mean()), 2)
    ctx.liquidity_tier = _tier_from_turnover(ctx.avg_daily_turnover_30d)

    # 30d vs 90d volume trend (needs the longer window)
    if ctx.n_days >= LONG_WINDOW:
        long_avg = float(sub.tail(LONG_WINDOW)["Volume"].mean())
        if long_avg > 0:
            ctx.volume_trend_ratio = round(float(last30["Volume"].mean()) / long_avg, 2)
            ctx.volume_trend = _trend_label(ctx.volume_trend_ratio)

    ctx.reason = (f"30d avg turnover ₹{ctx.avg_daily_turnover_30d:,.0f} → {ctx.liquidity_tier}")
    return ctx


def liquidity_for_ticker(ticker: str, *, period: str = "6mo", price_loader=None
                         ) -> LiquidityContext:
    """Integration seam: fetch via the existing tiered loader, then compute. Wrapped."""
    if price_loader is None:
        try:
            from data.fetcher import fetch_single as price_loader
        except Exception:
            return LiquidityContext(reason="price loader unavailable")
    try:
        df = price_loader(ticker, period=period)
    except Exception as e:
        return LiquidityContext(reason=f"price fetch failed: {e}")
    return compute_liquidity(df)
