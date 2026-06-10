"""
analysis/score.py
Composite Stock Score — 0 to 100 — with grade, action verdict,
entry/SL/TP levels, and a plain-English narrative for non-traders.

Score breakdown (90 pts max):
    Technical   40 pts  — RSI, MACD, SMA stack, ADX
    Momentum    25 pts  — 5d / 20d / 60d returns
    Volume      15 pts  — Volume ratio, OBV trend
    Sentiment   10 pts  — India VIX regime + sector rank

Candlestick patterns are detected and shown in the narrative but are NOT
scored. The 5-year variant study (RESEARCH_SCORE_VARIANTS.md, 40,663
observations) found the 10-pt pattern component contributed zero-to-negative
ranking power in every market regime; removing it improved return correlation
and decile monotonicity. The freed points are deliberately NOT redistributed
(that reweighting would need its own evidence) — the composite now tops out
at 90, which makes high grades/actions slightly stricter by design.
See PATTERN_REMOVAL_MIGRATION.md for the measured behavioural impact.

Grades:   A+ (≥88) | A (≥75) | B (≥62) | C (≥48) | D (≥32) | F (<32)
Actions:  STRONG BUY | BUY | WATCHLIST | HOLD | CAUTION | EXIT
"""

from __future__ import annotations

import sys, os
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    os.environ.setdefault("PYTHONUTF8", "1")

import warnings
import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple
from datetime import datetime

warnings.filterwarnings("ignore")


# ─────────────────────────────────────────────────────────────────────────────
# Result dataclass
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class CompositeScore:
    ticker:           str
    price:            float
    score:            float        # 0–100
    grade:            str          # A+ … F
    action:           str          # STRONG BUY … EXIT
    technical_score:  float        # /40
    momentum_score:   float        # /25
    volume_score:     float        # /15
    pattern_score:    float        # /10
    sentiment_score:  float        # /10
    entry:            float
    stop_loss:        float
    target:           float
    risk_reward:      float
    headline:         str
    narrative:        str
    sector:           str
    vix_regime:       str
    sector_rank:      int
    timestamp:        str          = field(default_factory=lambda: datetime.now().isoformat())

    def as_dict(self) -> Dict:
        return {
            "ticker": self.ticker, "price": self.price,
            "score": self.score, "grade": self.grade, "action": self.action,
            "technical": self.technical_score, "momentum": self.momentum_score,
            "volume": self.volume_score, "pattern": self.pattern_score,
            "sentiment": self.sentiment_score,
            "entry": self.entry, "sl": self.stop_loss, "tp": self.target,
            "rr": self.risk_reward, "headline": self.headline,
            "sector": self.sector, "vix_regime": self.vix_regime,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Sub-scorer: Technical  (40 pts)
# ─────────────────────────────────────────────────────────────────────────────

def _score_technical(df: pd.DataFrame) -> Tuple[float, Dict]:
    cur  = df.iloc[-1]
    prev = df.iloc[-2] if len(df) > 1 else cur

    rsi    = float(cur.get("RSI",   50))
    macd   = float(cur.get("MACD",  0))
    sig    = float(cur.get("MACD_Signal", 0))
    macd_p = float(prev.get("MACD", 0))
    sig_p  = float(prev.get("MACD_Signal", 0))
    hist   = float(cur.get("MACD_Hist", 0))
    hist_p = float(prev.get("MACD_Hist", 0))
    adx    = float(cur.get("ADX",   15))
    price  = float(cur["Close"])
    sma20  = float(cur.get("SMA_20",  price * 0.95))
    sma50  = float(cur.get("SMA_50",  price * 0.90))
    sma200 = float(cur.get("SMA_200", price * 0.80))

    pts: Dict[str, float] = {}

    # RSI zone — 12 pts
    if 60 <= rsi <= 70:      pts["rsi"] = 12.0   # sweet spot: trending up
    elif 50 <= rsi < 60:     pts["rsi"] = 9.0
    elif 70 < rsi <= 80:     pts["rsi"] = 7.0    # overbought but still ok
    elif 40 <= rsi < 50:     pts["rsi"] = 6.0    # neutral
    elif 30 <= rsi < 40:     pts["rsi"] = 8.0    # oversold — potential reversal
    elif rsi < 30:           pts["rsi"] = 10.0   # deeply oversold (bounce candidate)
    else:                    pts["rsi"] = 1.0    # RSI > 80: overbought

    # MACD — 10 pts
    macd_cross_up = (macd > sig) and (macd_p <= sig_p)
    hist_expanding = (abs(hist) > abs(hist_p)) and hist > 0
    if macd > sig:
        pts["macd"] = 8.0 + (2.0 if macd_cross_up else 0) + (1.0 if hist_expanding else 0)
        pts["macd"] = min(pts["macd"], 10.0)
    elif macd < sig and (macd_p >= sig_p):   # just crossed down
        pts["macd"] = 2.0
    else:
        pts["macd"] = 4.0 if (sig - macd) < abs(sig * 0.1) else 1.0  # narrowing = 4

    # SMA Stack — 10 pts
    if price > sma20 > sma50 > sma200:   pts["sma"] = 10.0
    elif price > sma50 > sma200:          pts["sma"] = 7.0
    elif price > sma200:                  pts["sma"] = 4.0
    else:                                 pts["sma"] = 0.0

    # ADX — 8 pts
    if adx > 40:    pts["adx"] = 8.0
    elif adx > 28:  pts["adx"] = 6.0
    elif adx > 20:  pts["adx"] = 3.0
    else:           pts["adx"] = 1.0

    total = sum(pts.values())
    return round(min(total, 40.0), 2), pts


# ─────────────────────────────────────────────────────────────────────────────
# Sub-scorer: Momentum  (25 pts)
# ─────────────────────────────────────────────────────────────────────────────

def _score_momentum(df: pd.DataFrame) -> Tuple[float, Dict]:
    if len(df) < 25:   # lowered from 65 — 2Y fetch gives ~250 rows after dropna
        return 12.5, {"note": "insufficient history"}

    close = df["Close"]
    r5d  = float(close.pct_change(5).iloc[-1])  * 100
    r20d = float(close.pct_change(20).iloc[-1]) * 100
    r60d = float(close.pct_change(60).iloc[-1]) * 100

    pts: Dict[str, float] = {}

    # 5-day return  — 5 pts
    if r5d >  3:    pts["r5d"] = 5.0
    elif r5d > 1:   pts["r5d"] = 4.0
    elif r5d > 0:   pts["r5d"] = 3.0
    elif r5d > -2:  pts["r5d"] = 2.0
    else:           pts["r5d"] = 0.0

    # 20-day return — 10 pts
    if r20d > 15:   pts["r20d"] = 10.0
    elif r20d > 8:  pts["r20d"] = 8.0
    elif r20d > 4:  pts["r20d"] = 7.0
    elif r20d > 2:  pts["r20d"] = 5.0
    elif r20d > 0:  pts["r20d"] = 4.0
    elif r20d > -5: pts["r20d"] = 2.0
    else:           pts["r20d"] = 0.0

    # 60-day return — 10 pts
    if r60d > 25:    pts["r60d"] = 10.0
    elif r60d > 15:  pts["r60d"] = 8.0
    elif r60d > 8:   pts["r60d"] = 6.0
    elif r60d > 3:   pts["r60d"] = 5.0
    elif r60d > 0:   pts["r60d"] = 3.0
    elif r60d > -10: pts["r60d"] = 1.0
    else:            pts["r60d"] = 0.0

    pts["_r5d"] = round(r5d, 2)
    pts["_r20d"] = round(r20d, 2)
    pts["_r60d"] = round(r60d, 2)

    total = pts["r5d"] + pts["r20d"] + pts["r60d"]
    return round(min(total, 25.0), 2), pts


# ─────────────────────────────────────────────────────────────────────────────
# Sub-scorer: Volume  (15 pts)
# ─────────────────────────────────────────────────────────────────────────────

def _score_volume(df: pd.DataFrame) -> Tuple[float, Dict]:
    cur = df.iloc[-1]
    vol_ratio  = float(cur.get("Volume_Ratio", 1.0))
    close      = float(cur["Close"])
    open_price = float(cur.get("Open", close))
    up_day     = close >= open_price   # green candle = buying pressure

    pts: Dict[str, float] = {}

    # Volume ratio — 10 pts, but halved on red (distribution) days
    if vol_ratio > 2.5:   raw_vol = 10.0
    elif vol_ratio > 1.8: raw_vol = 8.0
    elif vol_ratio > 1.2: raw_vol = 6.0
    elif vol_ratio > 0.8: raw_vol = 4.0
    else:                 raw_vol = 1.0
    # High volume on a red candle = distribution (bearish) — penalise
    pts["vol_ratio"] = raw_vol if up_day else max(1.0, raw_vol * 0.4)

    # OBV trend — 5 pts (slope of OBV over last 10 bars)
    if "OBV" in df.columns and len(df) >= 10:
        obv_recent = df["OBV"].iloc[-10:].values.astype(float)
        slope = float(np.polyfit(range(10), obv_recent, 1)[0])
        pts["obv"] = 5.0 if slope > 0 else (2.0 if abs(slope) < abs(obv_recent.mean()) * 0.001 else 0.0)
    else:
        pts["obv"] = 2.0  # neutral if not available

    total = pts["vol_ratio"] + pts["obv"]
    return round(min(total, 15.0), 2), pts


# ─────────────────────────────────────────────────────────────────────────────
# Pattern detection — INFORMATIONAL ONLY (excluded from the composite score;
# the detected patterns still feed the narrative). See RESEARCH_SCORE_VARIANTS.md.
# ─────────────────────────────────────────────────────────────────────────────

def _score_pattern(df: pd.DataFrame) -> Tuple[float, Dict]:
    # Scan last 3 bars so a pattern from 1-2 days ago still counts
    recent = df.iloc[-3:] if len(df) >= 3 else df
    pts = 0.0
    found = []

    bull_pat_cols = [
        ("Pat_MorningStar",   9.0, "MorningStar"),
        ("Pat_BullEngulfing", 8.0, "BullEngulfing"),
        ("Pat_Hammer",        6.0, "Hammer"),
        ("Pat_BullMarubozu",  5.0, "BullMarubozu"),
        ("Pat_Doji",          3.0, "Doji"),
    ]
    bear_pat_cols = [
        ("Pat_EveningStar",   7.0, "EveningStar⚠️"),
        ("Pat_BearEngulfing", 6.0, "BearEngulfing⚠️"),
        ("Pat_ShootingStar",  4.0, "ShootingStar⚠️"),
    ]

    for col, add, label in bull_pat_cols:
        if recent[col].any() if col in recent.columns else False:
            # Weight by recency: today=full, yesterday=60%, 2 days ago=30%
            day_idx = recent[col].values[::-1].tolist()
            recency = 1.0 if day_idx[0] else (0.6 if len(day_idx) > 1 and day_idx[1] else 0.3)
            pts += add * recency
            found.append(label)
            break  # only count the strongest bullish pattern

    for col, sub, label in bear_pat_cols:
        if recent[col].any() if col in recent.columns else False:
            day_idx = recent[col].values[::-1].tolist()
            recency = 1.0 if day_idx[0] else (0.6 if len(day_idx) > 1 and day_idx[1] else 0.3)
            pts -= sub * recency
            found.append(label)
            break

    # RSI divergence (additive — check current bar only)
    cur = df.iloc[-1]
    if cur.get("RSI_Bull_Div", 0): pts += 4.0; found.append("RSI_BullDiv")
    if cur.get("RSI_Bear_Div", 0): pts -= 3.0; found.append("RSI_BearDiv⚠️")

    return round(max(0.0, min(pts, 10.0)), 2), {"patterns": found}


# ─────────────────────────────────────────────────────────────────────────────
# Sub-scorer: Sentiment  (10 pts)
# ─────────────────────────────────────────────────────────────────────────────

def _score_sentiment(vix_info: Dict, sector_rank: int, n_sectors: int = 15) -> Tuple[float, Dict]:
    regime = (vix_info or {}).get("regime", "normal")
    pts: Dict[str, float] = {}

    # VIX — 6 pts
    vix_pts_map = {
        "complacency": 5.0,
        "normal":      6.0,
        "elevated":    4.0,
        "fear":        2.0,
        "panic":       0.0,
        "unknown":     3.0,
    }
    pts["vix"] = vix_pts_map.get(regime, 3.0)

    # Sector rank — 4 pts
    if sector_rank <= n_sectors // 3:
        pts["sector"] = 4.0       # top third
    elif sector_rank <= 2 * n_sectors // 3:
        pts["sector"] = 2.0       # middle third
    else:
        pts["sector"] = 0.0       # bottom third

    total = pts["vix"] + pts["sector"]
    return round(min(total, 10.0), 2), pts


# ─────────────────────────────────────────────────────────────────────────────
# Entry / SL / TP
# ─────────────────────────────────────────────────────────────────────────────

def _compute_entry_levels(df: pd.DataFrame, score: float) -> Tuple[float, float, float, float]:
    """
    Structure-aware stop + conviction-scaled target.

    Stop: placed just below the most recent swing low (last 10 bars) so it sits
    under real support, but bounded to 1.2–3.0× ATR of risk so it's neither too
    tight (noise) nor too wide (over-risking). Falls back to a pure 2× ATR stop
    when structure is unavailable.

    Target: set as a multiple of the actual risk (entry − stop), so the
    risk:reward is explicit and never drops below 1.5:1 for any quoted setup —
    higher conviction (score) earns a wider target.
    """
    cur   = df.iloc[-1]
    price = float(cur["Close"])
    atr   = float(cur.get("ATR", price * 0.02))
    if atr <= 0 or pd.isna(atr):
        atr = price * 0.02

    # ── Structure-based stop (recent swing low) with ATR bounds ──────────────
    lows      = df["Low"].tail(10).dropna()
    swing_low = float(lows.min()) if len(lows) else price - 2.0 * atr
    sl        = swing_low - 0.25 * atr            # small buffer below support

    max_risk = 3.0 * atr                          # never risk more than 3 ATR
    min_risk = 1.2 * atr                          # always give at least 1.2 ATR room
    if price - sl > max_risk:
        sl = price - 2.0 * atr                    # support too far → fall back to ATR stop
    if price - sl < min_risk:
        sl = price - min_risk                     # support too close → widen for breathing room

    risk = max(price - sl, 0.01)

    # ── Conviction-scaled target as a multiple of risk (R:R is explicit) ─────
    if   score >= 72: rr_mult = 3.0
    elif score >= 60: rr_mult = 2.5
    elif score >= 48: rr_mult = 2.0
    else:             rr_mult = 1.5               # floor: even weak setups quoted at min viable R:R
    tp   = price + rr_mult * risk
    rr   = round((tp - price) / risk, 2)

    return round(price, 2), round(sl, 2), round(tp, 2), rr


# ─────────────────────────────────────────────────────────────────────────────
# Grade + Action
# ─────────────────────────────────────────────────────────────────────────────

def _grade(score: float) -> str:
    if score >= 88: return "A+"
    if score >= 75: return "A"
    if score >= 62: return "B"
    if score >= 48: return "C"
    if score >= 32: return "D"
    return "F"

def _action(score: float) -> str:
    if score >= 80: return "STRONG BUY"
    if score >= 65: return "BUY"
    if score >= 52: return "WATCHLIST"
    if score >= 40: return "HOLD"
    if score >= 25: return "CAUTION"
    return "EXIT"


# ─────────────────────────────────────────────────────────────────────────────
# Plain-English Narrative  (non-trader friendly)
# ─────────────────────────────────────────────────────────────────────────────

def _build_narrative(
    ticker: str, df: pd.DataFrame, score: float, grade: str, action: str,
    tech_pts: Dict, mom_pts: Dict, vol_pts: Dict, pat_pts: Dict,
    entry: float, sl: float, tp: float, rr: float,
    sector: str, vix_regime: str, sector_rank: int,
) -> Tuple[str, str]:

    cur   = df.iloc[-1]
    price = float(cur["Close"])
    rsi   = float(cur.get("RSI", 50))
    adx   = float(cur.get("ADX", 15))
    sma20 = float(cur.get("SMA_20",  price))
    sma200= float(cur.get("SMA_200", price * 0.8))
    vol   = float(cur.get("Volume_Ratio", 1.0))

    r20d  = mom_pts.get("_r20d", 0.0)
    r60d  = mom_pts.get("_r60d", 0.0)
    patterns = pat_pts.get("patterns", [])
    bull_pats = [p for p in patterns if "⚠️" not in p]
    bear_pats = [p for p in patterns if "⚠️" in p]

    short_name = ticker.replace(".NS", "")

    # ── Headline ─────────────────────────────────────────────────────────────
    if score >= 80:
        headline = "Strong uptrend — all indicators aligned"
    elif score >= 65:
        headline = "Healthy setup — good risk-reward opportunity"
    elif score >= 52:
        headline = "Mixed signals — worth watching for entry"
    elif score >= 40:
        headline = "Consolidating — no clear edge right now"
    elif score >= 25:
        headline = "Caution — momentum fading, consider reducing"
    else:
        headline = "Weak — downtrend with no reversal signal"

    if rsi < 30 and score > 40:
        headline = "Deeply oversold — potential reversal setup"
    if bull_pats:
        headline += f" ({bull_pats[0]} pattern)"

    # ── Narrative sentences ───────────────────────────────────────────────────
    parts = []

    # Sentence 1: Trend / SMA context
    pct_above_200 = (price / sma200 - 1) * 100
    if price > sma20 and price > sma200:
        parts.append(
            f"{short_name} is trading at Rs.{price:,.2f}, above both its "
            f"20-day average (Rs.{sma20:,.2f}) and 200-day average — the uptrend is intact."
        )
    elif price > sma200:
        pct_below_20 = (sma20 / price - 1) * 100
        parts.append(
            f"{short_name} at Rs.{price:,.2f} is in an overall uptrend (above 200-day average) "
            f"but has pulled back {abs(pct_below_20):.1f}% below its 20-day average."
        )
    else:
        parts.append(
            f"{short_name} at Rs.{price:,.2f} is below its long-term 200-day average "
            f"— the broader trend is currently down."
        )

    # Sentence 2: RSI interpretation (non-jargon)
    if rsi < 30:
        parts.append(
            f"The stock has become deeply oversold (momentum indicator at {rsi:.0f}/100), "
            f"which often precedes a recovery bounce — but wait for a clear green candle to confirm."
        )
    elif rsi < 45:
        parts.append(
            f"The stock is in oversold territory (momentum at {rsi:.0f}/100), "
            f"which means selling pressure may be exhausted — a good zone for long-term buyers."
        )
    elif rsi <= 65:
        parts.append(
            f"Momentum is healthy at {rsi:.0f}/100 — neither overbought nor oversold, "
            f"suggesting the move has room to continue."
        )
    elif rsi <= 75:
        parts.append(
            f"Momentum is elevated ({rsi:.0f}/100) — the stock is running hot. "
            f"Wait for a small pullback before adding new positions."
        )
    else:
        parts.append(
            f"Momentum is very high ({rsi:.0f}/100 — overbought zone). "
            f"Existing holders can stay, but new buyers should wait for a pullback."
        )

    # Sentence 3: Recent performance
    if r20d > 10:
        parts.append(
            f"The stock has gained {r20d:.1f}% in the last month and {r60d:.1f}% "
            f"over 3 months — strong institutional interest."
        )
    elif r20d > 3:
        parts.append(
            f"Returns over the last month: +{r20d:.1f}%. Steady accumulation phase."
        )
    elif r20d > -3:
        parts.append(
            f"The stock has been largely flat over the past month ({r20d:+.1f}%), "
            f"consolidating after a prior move."
        )
    else:
        parts.append(
            f"The stock is down {abs(r20d):.1f}% over the past month — "
            f"sellers are currently in control."
        )

    # Sentence 4: Volume + pattern
    if vol > 1.5 and bull_pats:
        parts.append(
            f"Notably, today's volume is {vol:.1f}× the 20-day average with a "
            f"{bull_pats[0]} candlestick pattern — a positive confirmation signal."
        )
    elif vol > 1.5:
        parts.append(
            f"Trading volume is {vol:.1f}× the normal level, indicating above-average "
            f"buyer activity."
        )
    elif bear_pats:
        parts.append(
            f"A {bear_pats[0].replace('⚠️','')} pattern appeared recently — "
            f"a warning sign that some selling may follow."
        )

    # Sentence 5: Entry / SL / TP
    sl_pct = (sl / price - 1) * 100
    tp_pct = (tp / price - 1) * 100
    parts.append(
        f"Suggested entry around Rs.{entry:,.2f} with a protective stop at "
        f"Rs.{sl:,.2f} ({sl_pct:.1f}%) and target Rs.{tp:,.2f} ({tp_pct:+.1f}%) "
        f"— risk-reward ratio {rr:.1f}:1."
    )

    # Sentence 6: VIX + sector
    vix_sentence_map = {
        "complacency": "Market is calm (low VIX) — good environment for equities but complacency risk.",
        "normal":      "Overall market conditions are normal (VIX in healthy range).",
        "elevated":    "Market fear is elevated (VIX rising) — consider smaller position size.",
        "fear":        "Market fear is high (VIX above 22) — use strict stop-losses.",
        "panic":       "Market is in panic mode (VIX above 28) — exercise extreme caution.",
    }
    vix_txt = vix_sentence_map.get(vix_regime, "Market conditions are uncertain.")
    sector_txt = (
        f"The {sector} sector is currently ranked #{sector_rank} — "
        + ("a tailwind for this stock." if sector_rank <= 5 else
           "neutral sector backdrop." if sector_rank <= 10 else
           "a headwind — sector is underperforming.")
    )
    parts.append(f"{vix_txt} {sector_txt}")

    narrative = " ".join(parts)
    return headline, narrative


# ─────────────────────────────────────────────────────────────────────────────
# Main scoring functions
# ─────────────────────────────────────────────────────────────────────────────

def score_dataframe(
    df:                pd.DataFrame,
    ticker:            str,
    vix_info:          Optional[Dict] = None,
    sector_rank:       int = 7,
    sector:            str = "Other",
    n_sectors:         int = 15,
) -> CompositeScore:
    """
    Score from a pre-fetched, indicator-enriched DataFrame.
    Call this when you already have the df to avoid redundant fetches.
    """
    if vix_info is None:
        vix_info = {"regime": "normal", "vix": None, "allow_buy": True}

    tech_pts,  tech_detail  = _score_technical(df)
    mom_pts,   mom_detail   = _score_momentum(df)
    vol_pts,   vol_detail   = _score_volume(df)
    # Patterns: detected for the narrative only — excluded from the composite
    # (variant study: zero-to-negative ranking power in every regime).
    _pat_pts_info, pat_detail = _score_pattern(df)
    sent_pts,  sent_detail  = _score_sentiment(vix_info, sector_rank, n_sectors)

    total = tech_pts + mom_pts + vol_pts + sent_pts
    total = round(min(max(total, 0), 100), 1)

    grade  = _grade(total)
    action = _action(total)

    entry, sl, tp, rr = _compute_entry_levels(df, total)

    headline, narrative = _build_narrative(
        ticker=ticker, df=df, score=total, grade=grade, action=action,
        tech_pts=tech_detail, mom_pts=mom_detail, vol_pts=vol_detail,
        pat_pts=pat_detail,
        entry=entry, sl=sl, tp=tp, rr=rr,
        sector=sector, vix_regime=vix_info.get("regime", "normal"),
        sector_rank=sector_rank,
    )

    return CompositeScore(
        ticker          = ticker,
        price           = entry,
        score           = total,
        grade           = grade,
        action          = action,
        technical_score = tech_pts,
        momentum_score  = mom_pts,
        volume_score    = vol_pts,
        pattern_score   = 0.0,   # informational only — not part of the composite
        sentiment_score = sent_pts,
        entry           = entry,
        stop_loss       = sl,
        target          = tp,
        risk_reward     = rr,
        headline        = headline,
        narrative       = narrative,
        sector          = sector,
        vix_regime      = vix_info.get("regime", "normal"),
        sector_rank     = sector_rank,
    )


def score_stock(
    ticker:            str,
    period:            str = "2y",
    vix_info:          Optional[Dict] = None,
    sector_scores_df:  Optional["pd.DataFrame"] = None,
) -> CompositeScore:
    """
    Full end-to-end scoring for any NSE stock.

    Fetches data, runs all indicators, computes composite score, returns
    CompositeScore dataclass with narrative.

    Pass vix_info and sector_scores_df when scoring many stocks to avoid
    repeated network calls.
    """
    import sys, os
    sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

    from data.fetcher import fetch_single
    from data.universe import get_sector, resolve_ticker, list_sectors
    from utils.indicators import add_all_indicators

    # Resolve ticker
    try:
        canonical = resolve_ticker(ticker)
    except ValueError:
        canonical = ticker if ticker.endswith(".NS") else ticker + ".NS"

    # Fetch VIX via utils.vix (cookie+crumb auth, 10-min TTL, cloud-safe)
    if vix_info is None:
        try:
            from utils.vix import get_india_vix_regime
            vix_info = get_india_vix_regime()
        except Exception:
            vix_info = {"regime": "normal", "vix": None, "allow_buy": True}

    # Get sector
    sector = get_sector(canonical)

    # Get sector rank
    sector_rank = 7   # default: mid-table
    n_sectors   = len(list_sectors())
    if sector_scores_df is not None and not sector_scores_df.empty:
        if sector in sector_scores_df.index:
            sector_rank = int(sector_scores_df.loc[sector, "Rank"]) if "Rank" in sector_scores_df.columns else 7

    # Fetch price data
    try:
        df = fetch_single(canonical, period=period)
        df = add_all_indicators(df)
        df.dropna(subset=["RSI", "ATR"], inplace=True)
        if len(df) < 30:
            raise ValueError(f"Insufficient data for {canonical}")
    except Exception as e:
        # Return a sentinel score when data is unavailable
        return CompositeScore(
            ticker=canonical, price=0.0, score=0.0, grade="F",
            action="DATA_UNAVAILABLE",
            technical_score=0, momentum_score=0, volume_score=0,
            pattern_score=0, sentiment_score=0,
            entry=0, stop_loss=0, target=0, risk_reward=0,
            headline=f"Data unavailable: {e}",
            narrative=f"Could not fetch data for {canonical}. Please check the ticker symbol.",
            sector=sector, vix_regime="unknown", sector_rank=sector_rank,
        )

    return score_dataframe(
        df=df, ticker=canonical,
        vix_info=vix_info,
        sector_rank=sector_rank,
        sector=sector,
        n_sectors=n_sectors,
    )
