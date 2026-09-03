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
scored. The 5-year variant study (docs/RESEARCH_SCORE_VARIANTS.md, 40,663
observations) found the 10-pt pattern component contributed zero-to-negative
ranking power in every market regime. See docs/PATTERN_REMOVAL_MIGRATION.md.

Grades:   A+ (≥88) | A (≥75) | B (≥62) | C (≥48) | D (≥32) | F (<32)
Actions:  STRONG BUY | BUY | WATCHLIST | HOLD | CAUTION | EXIT

Fixes applied vs previous version:
  - sys.path.insert moved to module level (was inside score_stock — ran on every call)
  - All heavy imports moved to module level with _DEPS_LOADED guard
  - _score_pattern renamed _detect_patterns: returns Dict only (no phantom numeric score)
  - CompositeScore.pattern_score removed; patterns_detected: List[str] added
  - resolve_ticker now catches Exception (was ValueError only — other errors crashed page)
  - Score cap corrected to 90 (was 100 — unreachable, misleading)
  - Sector rank thresholds now derived from n_sectors (were hardcoded 5/10)
  - Momentum fallback now sets is_fallback=True flag so narrative can note it
  - Windows UTF-8 fix moved out of module body into _setup_encoding() called once
"""

from __future__ import annotations

import os
import sys
import logging
import warnings
import math
import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta

# FIX WARN1 — narrowed from a blanket `filterwarnings("ignore")` so numpy's
# RuntimeWarnings (invalid value / divide by zero / all-NaN slice) stay visible.
warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=DeprecationWarning)
warnings.filterwarnings("ignore", category=PendingDeprecationWarning)

_log = logging.getLogger("analysis.score")

# ── Ensure project root is on sys.path (one-time, at import — not per call) ──
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

# ── Lazy-load heavy project deps once at module level ─────────────────────────
# Keeps score_stock() clean and avoids repeated import overhead on screener scans.
_DEPS_LOADED = False
_fetch_single          = None
_get_sector            = None
_resolve_ticker        = None
_list_sectors          = None
_add_all_indicators    = None
_get_india_vix_regime  = None

# FIX LAZY1 — score_stock() previously called add_all_indicators() with no
# argument, computing all 14 indicator groups (82 columns) even though this
# function only ever reads columns from 6 of them. Do NOT add groups here
# speculatively — if score_stock() is changed to read a new indicator column,
# add that column's group here at the same time, or it will KeyError at the
# dropna/read site.
#
# FIX SCORE-PAT — "patterns" and "divergence" were MISSING from this tuple even
# though score_dataframe() calls _detect_patterns(), which reads Pat_Doji,
# Pat_Hammer, Pat_ShootingStar, Pat_BullMarubozu, Pat_BearMarubozu,
# Pat_BullEngulfing, Pat_BearEngulfing, Pat_MorningStar, Pat_EveningStar,
# RSI_Bull_Div and RSI_Bear_Div. Because _detect_patterns() guards every read
# with `if col in recent.columns` / `cur.get(col, 0)`, the omission did not
# raise — it silently returned an EMPTY pattern list for every stock scored
# through score_stock(), which is the entry point behind Top Picks, the
# screener, Analyze Stock, Watchlist and Quality Watch. Downstream that meant:
#   * CompositeScore.patterns_detected was always []
#   * the headline never got its "(BullEngulfing pattern)" suffix
#   * _build_narrative()'s sentence 4 could never take the pattern branch, so
#     the "volume × pattern confirmation" line and the bearish-pattern warning
#     were dead code for the main path
# i.e. a documented, user-facing feature was switched off by an optimisation
# that only audited the *numeric* score's column reads and missed the narrative
# layer's. The tests didn't catch it because test_smoke_score_indicators.py only
# asserts `isinstance(cs.patterns_detected, list)` — [] satisfies that.
#
# Both groups are cheap enough to restore: "patterns" is fully vectorised, and
# "divergence" is now vectorised too (FIX IND5 in utils/indicators.py replaced
# its per-bar Python loop with sliding_window_view), so this no longer
# reintroduces the per-ticker cost that motivated FIX LAZY1.
_SCORE_INDICATOR_GROUPS = (
    "ma", "rsi", "macd", "adx", "volume", "atr", "patterns", "divergence",
)


def _num(row: "pd.Series", key: str, default: float) -> float:
    """
    Read a numeric field from an indicator row, falling back to `default` when
    the value is missing OR NaN.

    FIX SCORE-NAN — the scorers used `float(cur.get("SMA_200", price * 0.80))`.
    `Series.get(key, default)` only returns the default when the KEY IS ABSENT;
    when the column exists but the value is NaN — the normal case during an
    indicator's warm-up — it returns NaN, and `float(nan)` propagates. Every
    subsequent comparison against NaN is False under IEEE-754, so the intended
    fallback never applied and the value silently fell through to the LAST
    branch of each ladder:
      * _score_technical()'s SMA stack awarded 0.0 / 10 whenever SMA_200 was
        NaN (a stock with under 200 bars of history — recent listings, and any
        caller passing a shorter period to score_dataframe()), scoring it
        identically to a stock genuinely trading below its 200-day average.
      * the same pattern applied to RSI, ADX, MACD and Volume_Ratio.
    Reading through this helper makes the documented default actually take
    effect, so "unknown" no longer silently reads as "bearish".
    """
    val = row.get(key, default)
    try:
        f = float(val)
    except (TypeError, ValueError):
        return default
    return default if math.isnan(f) else f


def _load_deps() -> bool:
    global _DEPS_LOADED, _fetch_single, _get_sector, _resolve_ticker
    global _list_sectors, _add_all_indicators, _get_india_vix_regime
    if _DEPS_LOADED:
        return True
    try:
        from data.fetcher   import fetch_single
        from data.universe  import get_sector, resolve_ticker, list_sectors
        from utils.indicators import add_all_indicators
        _fetch_single       = fetch_single
        _get_sector         = get_sector
        _resolve_ticker     = resolve_ticker
        _list_sectors       = list_sectors
        _add_all_indicators = add_all_indicators
        try:
            from utils.vix import get_india_vix_regime
            _get_india_vix_regime = get_india_vix_regime
        except Exception as e:
            # Optional dependency — VIX regime sentiment falls back to "normal"
            # when unavailable (see score_stock), but log so a real import
            # break in utils.vix isn't invisible.
            _log.debug("utils.vix unavailable, VIX regime sentiment disabled: %s: %s",
                       type(e).__name__, e)
        _DEPS_LOADED = True
        return True
    except Exception as e:
        _log.warning("analysis.score core dependencies failed to load: %s: %s",
                     type(e).__name__, e)
        return False


def _setup_encoding() -> None:
    """Set UTF-8 output on Windows — called once at startup, not at import."""
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
            sys.stderr.reconfigure(encoding="utf-8")
        except AttributeError as e:
            # Older Python / non-standard stream wrappers may lack reconfigure();
            # harmless, but log so it's visible during diagnosis.
            _log.debug("stdout/stderr reconfigure unavailable: %s", e)
        os.environ.setdefault("PYTHONUTF8", "1")


# ─────────────────────────────────────────────────────────────────────────────
# Result dataclass
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class CompositeScore:
    ticker:             str
    price:              float
    score:              float        # 0–90 (90 pt max composite)
    grade:              str          # A+ … F
    action:             str          # STRONG BUY … EXIT
    technical_score:    float        # /40
    momentum_score:     float        # /25
    volume_score:       float        # /15
    sentiment_score:    float        # /10
    entry:              float
    stop_loss:          float
    target:             float
    risk_reward:        float
    headline:           str
    narrative:          str
    sector:             str
    vix_regime:         str
    sector_rank:        int
    patterns_detected:  List[str]    = field(default_factory=list)   # informational only
    momentum_fallback:  bool         = False   # True when < 25 bars of history
    horizon:            str          = ""      # FIX HZ1: e.g. "Swing (3–10 trading days)"
    valid_until:        str          = ""      # FIX HZ1: ISO date — pick considered stale after this
    rsi:                float        = 50.0    # FIX WL1: raw RSI(14), already computed — just unsurfaced
    return_1d:          float        = 0.0     # FIX WL1: 1-day % change, already available from df
    rs_score:           Optional[float] = None # FIX RS1: RS_Score vs Nifty (0-100 percentile), None when benchmark unavailable
    timestamp:          str          = field(default_factory=lambda: datetime.now().isoformat())

    def as_dict(self) -> Dict:
        return {
            "ticker": self.ticker, "price": self.price,
            "score": self.score, "grade": self.grade, "action": self.action,
            "technical": self.technical_score, "momentum": self.momentum_score,
            "volume": self.volume_score, "sentiment": self.sentiment_score,
            "patterns": self.patterns_detected,
            "entry": self.entry, "sl": self.stop_loss, "tp": self.target,
            "rr": self.risk_reward, "headline": self.headline,
            "sector": self.sector, "vix_regime": self.vix_regime,
            "momentum_fallback": self.momentum_fallback,
            "horizon": self.horizon, "valid_until": self.valid_until,
            "rsi": self.rsi, "return_1d": self.return_1d,
            "rs_score": self.rs_score,
        }


# ─────────────────────────────────────────────────────────────────────────────
# Sub-scorer: Technical  (40 pts)
# ─────────────────────────────────────────────────────────────────────────────

def _score_technical(df: pd.DataFrame) -> Tuple[float, Dict]:
    cur  = df.iloc[-1]
    prev = df.iloc[-2] if len(df) > 1 else cur

    # FIX SCORE-NAN: read through _num() so an indicator still in its warm-up
    # (NaN, not missing) uses the documented default instead of poisoning every
    # comparison below into False. See _num()'s docstring.
    rsi    = _num(cur,  "RSI",         50)
    macd   = _num(cur,  "MACD",         0)
    sig    = _num(cur,  "MACD_Signal",  0)
    macd_p = _num(prev, "MACD",         0)
    sig_p  = _num(prev, "MACD_Signal",  0)
    hist   = _num(cur,  "MACD_Hist",    0)
    hist_p = _num(prev, "MACD_Hist",    0)
    adx    = _num(cur,  "ADX",         15)
    price  = float(cur["Close"])
    sma20  = _num(cur, "SMA_20",  price * 0.95)
    sma50  = _num(cur, "SMA_50",  price * 0.90)
    sma200 = _num(cur, "SMA_200", price * 0.80)

    pts: Dict[str, float] = {}

    # RSI zone — 12 pts
    # NOTE: Intentionally non-monotonic — oversold (RSI<30) scores 10 pts as a
    # bounce candidate, which outranks a neutral (RSI 50-60 = 9 pts) but not a
    # trending sweet spot (RSI 60-70 = 12 pts). Documented here to avoid
    # confusion during code review.
    if 60 <= rsi <= 70:      pts["rsi"] = 12.0
    elif 50 <= rsi < 60:     pts["rsi"] = 9.0
    elif 70 < rsi <= 80:     pts["rsi"] = 7.0
    elif 40 <= rsi < 50:     pts["rsi"] = 6.0
    elif 30 <= rsi < 40:     pts["rsi"] = 8.0
    elif rsi < 30:           pts["rsi"] = 10.0   # deeply oversold — bounce candidate
    else:                    pts["rsi"] = 1.0    # RSI > 80: overbought

    # MACD — 10 pts
    macd_cross_up   = (macd > sig) and (macd_p <= sig_p)
    hist_expanding  = (abs(hist) > abs(hist_p)) and hist > 0
    if macd > sig:
        pts["macd"] = min(8.0 + (2.0 if macd_cross_up else 0) + (1.0 if hist_expanding else 0), 10.0)
    elif macd < sig and (macd_p >= sig_p):
        pts["macd"] = 2.0
    else:
        pts["macd"] = 4.0 if (sig - macd) < abs(sig * 0.1) else 1.0

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
    if len(df) < 25:
        # Not enough history — return neutral 50% and flag it so the caller
        # can add a disclaimer to the narrative.
        return 12.5, {"note": "insufficient history", "is_fallback": True}

    close = df["Close"]
    r5d   = float(close.pct_change(5).iloc[-1])  * 100
    r20d  = float(close.pct_change(20).iloc[-1]) * 100

    # FIX SCORE-R60 — when fewer than 60 bars were available this used to set
    # r60d = 0.0 and score it like any other number. 0.0 does not land in a
    # neutral bucket: it falls past `r60d > 0` (0 is not > 0) into the
    # `r60d > -10` branch, which pays 1.0 of 10 points. So "we have no 3-month
    # history for this stock" was scored as "this stock is slightly DOWN over
    # 3 months" — a 9-point penalty out of a 25-point momentum budget, applied
    # to every recent listing and every caller passing a short frame to
    # score_dataframe(). Same defect family as FIX SCORE-NAN: absence of
    # evidence read as evidence of weakness. Unknown now scores the neutral
    # midpoint of that component and says so, rather than quietly convicting.
    has_r60 = len(df) >= 61
    r60d    = float(close.pct_change(60).iloc[-1]) * 100 if has_r60 else float("nan")

    pts: Dict[str, float] = {}

    # 5-day return — 5 pts
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
    if not has_r60:
        # FIX SCORE-R60: unknown ≠ weak. Neutral midpoint of this component,
        # flagged so the narrative can disclose it instead of silently
        # presenting a penalised score as a considered one.
        pts["r60d"] = 5.0
    elif r60d > 25:  pts["r60d"] = 10.0
    elif r60d > 15:  pts["r60d"] = 8.0
    elif r60d > 8:   pts["r60d"] = 6.0
    elif r60d > 3:   pts["r60d"] = 5.0
    elif r60d > 0:   pts["r60d"] = 3.0
    elif r60d > -10: pts["r60d"] = 1.0
    else:            pts["r60d"] = 0.0

    pts["_r5d"]  = round(r5d,  2)
    pts["_r20d"] = round(r20d, 2)
    pts["_r60d"] = round(r60d, 2) if has_r60 else None
    pts["r60d_available"] = has_r60

    abs_total = pts["r5d"] + pts["r20d"] + pts["r60d"]

    # ── FIX RS1 (2026-09-03) — Relative Strength vs Nifty ───────────────────
    # Absolute returns reward beta in bull tapes and punish defensives in
    # bear tapes. The 5-year efficacy study (docs/SCORE_EFFICACY_REPORT.md)
    # tied the 62 → 46% BUY-hit-rate drop between train (trending) and
    # holdout (mean-reverting) partly to this. IBD-style RS_Score (0-100
    # percentile rank of the stock/Nifty ratio's 52-week distribution) is
    # already computed by utils.indicators.add_relative_strength() and
    # written to the df as RS_Score before this function is called (see
    # score_stock). When present, the Momentum pillar's 25 pts split as
    # abs_returns:15 + rs_vs_nifty:10 — same total, same shape (Guardrail
    # §5 unchanged). When absent (test frames with synthetic data, single-
    # ticker ad-hoc scoring without a benchmark fetch), the full 25 pts
    # stay on absolute momentum for backwards-compat.
    #
    # This lands Task 3.1 from tasks/plan.md and Recommendation 1 from
    # docs/COMPOSITE_SCORE_SHAPE_REVIEW.md.
    rs_score = _num(df.iloc[-1], "RS_Score", float("nan"))
    if math.isnan(rs_score):
        pts["rs_available"] = False
        total = abs_total
    else:
        # Scale absolute component 25 → 15
        abs_scaled = abs_total * (15.0 / 25.0)
        # RS component: linear map 0-100 → 0-10, per _bonus_rs() convention
        # in research/score_variants_rs.py which studied exactly this shape.
        rs_pts = round(float(np.clip(rs_score, 0.0, 100.0)) / 100.0 * 10.0, 2)
        pts["rs_available"] = True
        pts["rs_score"]     = round(rs_score, 1)
        pts["rs_pts"]       = rs_pts
        pts["abs_scaled"]   = round(abs_scaled, 2)
        total = abs_scaled + rs_pts

    return round(min(total, 25.0), 2), pts


# ─────────────────────────────────────────────────────────────────────────────
# Sub-scorer: Volume  (15 pts)
# ─────────────────────────────────────────────────────────────────────────────

def _score_volume(df: pd.DataFrame) -> Tuple[float, Dict]:
    cur        = df.iloc[-1]
    vol_ratio  = _num(cur, "Volume_Ratio", 1.0)   # FIX SCORE-NAN
    close      = float(cur["Close"])
    open_price = _num(cur, "Open", close)
    up_day     = close >= open_price

    pts: Dict[str, float] = {}

    if vol_ratio > 2.5:   raw_vol = 10.0
    elif vol_ratio > 1.8: raw_vol = 8.0
    elif vol_ratio > 1.2: raw_vol = 6.0
    elif vol_ratio > 0.8: raw_vol = 4.0
    else:                 raw_vol = 1.0
    pts["vol_ratio"] = raw_vol if up_day else max(1.0, raw_vol * 0.4)

    if "OBV" in df.columns and len(df) >= 10:
        obv_recent = df["OBV"].iloc[-10:].values.astype(float)
        slope      = float(np.polyfit(range(10), obv_recent, 1)[0])
        pts["obv"] = 5.0 if slope > 0 else (2.0 if abs(slope) < abs(obv_recent.mean()) * 0.001 else 0.0)
    else:
        pts["obv"] = 2.0

    total = pts["vol_ratio"] + pts["obv"]
    return round(min(total, 15.0), 2), pts


# ─────────────────────────────────────────────────────────────────────────────
# Pattern detection — INFORMATIONAL ONLY (feeds narrative, not the composite)
# ─────────────────────────────────────────────────────────────────────────────

def _detect_patterns(df: pd.DataFrame) -> Dict:
    """
    Detect candlestick patterns in the last 3 bars.
    Returns {"patterns": List[str]} — no numeric score.
    Patterns excluded from composite (variant study: zero-to-negative ranking power).
    """
    recent = df.iloc[-3:] if len(df) >= 3 else df
    found: List[str] = []

    bull_pat_cols = [
        ("Pat_MorningStar",   "MorningStar"),
        ("Pat_BullEngulfing", "BullEngulfing"),
        ("Pat_Hammer",        "Hammer"),
        ("Pat_BullMarubozu",  "BullMarubozu"),
        ("Pat_Doji",          "Doji"),
    ]
    bear_pat_cols = [
        ("Pat_EveningStar",   "EveningStar⚠️"),
        ("Pat_BearEngulfing", "BearEngulfing⚠️"),
        ("Pat_ShootingStar",  "ShootingStar⚠️"),
    ]

    for col, label in bull_pat_cols:
        if col in recent.columns and recent[col].any():
            found.append(label)
            break  # strongest bullish only

    for col, label in bear_pat_cols:
        if col in recent.columns and recent[col].any():
            found.append(label)
            break  # strongest bearish only

    cur = df.iloc[-1]
    if cur.get("RSI_Bull_Div", 0): found.append("RSI_BullDiv")
    if cur.get("RSI_Bear_Div", 0): found.append("RSI_BearDiv⚠️")

    return {"patterns": found}


# ─────────────────────────────────────────────────────────────────────────────
# Sub-scorer: Sentiment  (10 pts)
# ─────────────────────────────────────────────────────────────────────────────

def _score_sentiment(vix_info: Dict, sector_rank: int, n_sectors: int = 15,
                     flows_info: Optional[Dict] = None) -> Tuple[float, Dict]:
    """Sentiment pillar (10 pts).

    Two modes, gated on `flows_info` availability:

    Legacy (backwards-compat, flows_info is None) — the 10 pts split as
        vix:6 + sector_rank:4
    which is how every caller before FIX FLOWS1 (2026-09-03) worked.

    With flows (flows_info dict from analysis.fii_dii.load_history) — the
    10 pts split as
        vix:5 + sector_rank:3 + fii_dii_flows:2
    Rationale: FII/DII cash-market net-buy/sell is the single largest
    driver of same-week Nifty direction on Indian equities — the app
    already computes and displays it on Analyze Stock's market-context
    strip, but the composite score was blind to it. Guardrail 5 shape
    unchanged (Sentiment stays 10 pts of the 90).

    Ships Recommendation 2 from docs/COMPOSITE_SCORE_SHAPE_REVIEW.md.
    """
    regime = (vix_info or {}).get("regime", "normal")
    pts: Dict[str, float] = {}

    _flows_available = (
        isinstance(flows_info, dict)
        and flows_info.get("fii_5d") is not None
        and flows_info.get("dii_5d") is not None
    )

    if _flows_available:
        # Split 5/3/2 — see docstring. VIX map preserves the old 6-pt map's
        # relative shape then rescales so the max is 5 (normal) instead of 6.
        vix_pts_map = {
            "complacency": 4.0, "normal": 5.0, "elevated": 3.0,
            "fear":        1.5, "panic":  0.0, "unknown":  2.5,
        }
        pts["vix"] = vix_pts_map.get(regime, 2.5)

        top_third = n_sectors // 3
        mid_third = 2 * n_sectors // 3
        if sector_rank <= top_third:   pts["sector"] = 3.0
        elif sector_rank <= mid_third: pts["sector"] = 1.5
        else:                           pts["sector"] = 0.0

        # Flows: sign of 5-day (FII + DII) net cash-market
        _fii = float(flows_info.get("fii_5d") or 0.0)
        _dii = float(flows_info.get("dii_5d") or 0.0)
        if _fii > 0 and _dii > 0:
            pts["flows"] = 2.0   # broad participation — persistent rallies
        elif _fii < 0 and _dii < 0:
            pts["flows"] = 0.0   # distribution — usually precedes weakness
        elif _fii < 0 and _dii > 0:
            pts["flows"] = 1.5   # domestic-supported dip — tradeable pullback
        elif _fii > 0 and _dii < 0:
            pts["flows"] = 1.0   # DII profit-taking rally — shallower legs
        else:
            pts["flows"] = 1.0   # mixed / one leg is zero
        pts["flows_available"] = True
        pts["fii_5d"] = round(_fii, 1)
        pts["dii_5d"] = round(_dii, 1)

        total = pts["vix"] + pts["sector"] + pts["flows"]
    else:
        # Legacy mode — unchanged from pre-2026-09-03 behavior
        vix_pts_map = {
            "complacency": 5.0, "normal": 6.0, "elevated": 4.0,
            "fear":        2.0, "panic":  0.0, "unknown":  3.0,
        }
        pts["vix"] = vix_pts_map.get(regime, 3.0)

        top_third = n_sectors // 3
        mid_third = 2 * n_sectors // 3
        if sector_rank <= top_third:   pts["sector"] = 4.0
        elif sector_rank <= mid_third: pts["sector"] = 2.0
        else:                           pts["sector"] = 0.0

        pts["flows_available"] = False
        total = pts["vix"] + pts["sector"]

    return round(min(total, 10.0), 2), pts


# ─────────────────────────────────────────────────────────────────────────────
# Entry / SL / TP
# ─────────────────────────────────────────────────────────────────────────────

def _compute_entry_levels(df: pd.DataFrame, score: float) -> Tuple[float, float, float, float]:
    """
    Structure-aware stop + volatility-calibrated target.
    Entry = current close (live price injected later in score_stock if Angel One connected).

    FIX RR1: the target used to come from a fixed 4-bucket score ladder
    (score>=72 -> 3.0x risk, >=60 -> 2.5x, >=48 -> 2.0x, else 1.5x) — the
    same multiplier for every stock in a band regardless of how that stock
    actually moves. The stop was already stock-specific (ATR + swing-low);
    the target wasn't, which is the "fixed, not genuine" feeling flagged
    against this page. The target multiplier is now anchored to THIS
    stock's own realized volatility — a ~10-trading-day expected move,
    scaled from its trailing daily-return std-dev via sqrt-time scaling —
    expressed in ATR units. Score still nudges the target (higher
    conviction reaches a bit further), but it no longer overrides what's
    realistic for that specific stock: a calm large-cap and a choppy
    small-cap in the same score band no longer get an identical target.
    """
    cur   = df.iloc[-1]
    price = float(cur["Close"])
    atr   = float(cur.get("ATR", price * 0.02))
    if atr <= 0 or pd.isna(atr):
        atr = price * 0.02

    lows      = df["Low"].tail(10).dropna()
    swing_low = float(lows.min()) if len(lows) else price - 2.0 * atr
    sl        = swing_low - 0.25 * atr

    max_risk = 3.0 * atr
    min_risk = 1.2 * atr
    if price - sl > max_risk:
        sl = price - 2.0 * atr
    if price - sl < min_risk:
        sl = price - min_risk

    risk = max(price - sl, 0.01)

    # ── FIX RR1: stock-specific expected move, in ATR units ──
    # 10 trading days ≈ 2 calendar weeks — matches the "Swing" horizon
    # bucket in _pick_horizon() below, so the target and the holding-period
    # label describe the same window rather than two unrelated numbers.
    _HOLD_DAYS = 10
    closes = df["Close"].tail(120).dropna()
    expected_move_atr = None
    if len(closes) >= 20:
        daily_ret = closes.pct_change().dropna()
        daily_vol = float(daily_ret.std())
        if daily_vol > 0 and not pd.isna(daily_vol):
            expected_move_price = price * daily_vol * math.sqrt(_HOLD_DAYS)
            expected_move_atr = expected_move_price / atr

    if   score >= 72: conviction = 1.25
    elif score >= 60: conviction = 1.10
    elif score >= 48: conviction = 0.95
    else:             conviction = 0.80

    if expected_move_atr is not None and expected_move_atr > 0:
        rr_mult = expected_move_atr * conviction
        # Bounds keep targets sane at either extreme — under 1.2x risk isn't
        # a real trade idea, and past 4x risk the volatility estimate is
        # more noise than signal (short history, thin trading, a recent gap).
        rr_mult = max(1.2, min(rr_mult, 4.0))
    else:
        # FIX RR1 fallback: not enough price history for a volatility
        # estimate (e.g. a recent listing) — use the old fixed ladder
        # rather than guessing off too little data.
        if   score >= 72: rr_mult = 3.0
        elif score >= 60: rr_mult = 2.5
        elif score >= 48: rr_mult = 2.0
        else:             rr_mult = 1.5

    tp = price + rr_mult * risk
    rr = round((tp - price) / risk, 2)
    return round(price, 2), round(sl, 2), round(tp, 2), rr


def _pick_horizon(tech_pts: float, mom_pts: float) -> Tuple[str, int]:
    """
    FIX HZ1: every score-driven page (Top Picks, Analyze Stock, Watchlist,
    Quality Watch) handed back an action label (STRONG BUY / BUY / etc.)
    with no sense of how long that setup is actually good for — flagged as
    "too vague" when deciding when to book or walk away. A momentum-heavy
    score describes a shorter-lived push that tends to mean-revert; a
    technical/trend-heavy score (higher structural weight, less reliance on
    the momentum sub-score) describes a more durable setup. This doesn't
    invent new signals — it just labels which of the two the composite
    score is already leaning on, using the same tech_pts/mom_pts already
    computed for this ticker.

    Returns (label, calendar_days_until_stale) — the latter feeds
    CompositeScore.valid_until so a pick can visibly go stale instead of
    sitting on screen looking current indefinitely.
    """
    if mom_pts >= tech_pts:
        return "Swing (3–10 trading days)", 14
    return "Positional (2–6 weeks)", 42


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
# Plain-English Narrative
# ─────────────────────────────────────────────────────────────────────────────

def _build_narrative(
    ticker: str, df: pd.DataFrame, score: float, grade: str, action: str,
    tech_pts: Dict, mom_pts: Dict, vol_pts: Dict, patterns: List[str],
    entry: float, sl: float, tp: float, rr: float,
    sector: str, vix_regime: str, sector_rank: int, n_sectors: int,
    momentum_fallback: bool,
    sent_pts: Optional[Dict] = None,   # FIX FLOWS1: flow sentence gated on this
) -> Tuple[str, str]:
    if sent_pts is None:
        sent_pts = {}

    cur        = df.iloc[-1]
    price      = float(cur["Close"])
    rsi        = _num(cur, "RSI",          50)          # FIX SCORE-NAN
    sma20      = _num(cur, "SMA_20",       price)
    sma200     = _num(cur, "SMA_200",      price * 0.8)
    vol        = _num(cur, "Volume_Ratio", 1.0)
    r20d       = mom_pts.get("_r20d", 0.0)
    # FIX SCORE-R60: _r60d is None when there is under 60 bars of history — the
    # sentence below must say so rather than format None or print a fake 0.0%.
    r60d       = mom_pts.get("_r60d")
    has_r60    = r60d is not None
    bull_pats  = [p for p in patterns if "⚠️" not in p]
    bear_pats  = [p for p in patterns if "⚠️" in p]
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

    # ── Narrative ─────────────────────────────────────────────────────────────
    parts = []

    # Sentence 1: Trend / SMA context
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

    # Sentence 2: RSI
    if rsi < 30:
        parts.append(
            f"The stock has become deeply oversold (momentum indicator at {rsi:.0f}/100), "
            f"which often precedes a recovery bounce — but wait for a clear green candle to confirm."
        )
    elif rsi < 45:
        parts.append(
            f"The stock is in oversold territory (momentum at {rsi:.0f}/100), "
            f"suggesting selling pressure may be exhausted — a good zone for long-term buyers."
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

    # Sentence 3: Recent performance (or fallback note)
    if momentum_fallback:
        parts.append(
            "Momentum data is limited (fewer than 25 trading days of history available) "
            "— treat the momentum score as indicative only."
        )
    elif r20d > 10:
        if has_r60:
            parts.append(
                f"The stock has gained {r20d:.1f}% in the last month and {r60d:.1f}% "
                f"over 3 months — strong institutional interest."
            )
        else:
            parts.append(
                f"The stock has gained {r20d:.1f}% in the last month — strong buying "
                f"interest. Under 3 months of price history is available, so the "
                f"3-month momentum component is scored neutral rather than measured."
            )
    elif r20d > 3:
        parts.append(f"Returns over the last month: +{r20d:.1f}%. Steady accumulation phase.")
    elif r20d >= -3:
        parts.append(
            f"The stock has been largely flat over the past month ({r20d:+.1f}%), "
            f"consolidating after a prior move."
        )
    else:
        parts.append(
            f"The stock is down {abs(r20d):.1f}% over the past month — "
            f"sellers are currently in control."
        )

    # Sentence 3b: Relative Strength vs Nifty (FIX RS1) — only rendered when
    # RS_Score is present on the df (i.e. score_stock fetched a benchmark).
    _rs_val = mom_pts.get("rs_score")
    if _rs_val is not None:
        if _rs_val >= 80:
            parts.append(
                f"Relative strength vs Nifty is exceptional ({_rs_val:.0f}/100 percentile) "
                f"— outperforming the broad market decisively over the trailing year."
            )
        elif _rs_val >= 60:
            parts.append(
                f"Relative strength vs Nifty is strong ({_rs_val:.0f}/100 percentile) "
                f"— leading the broader market."
            )
        elif _rs_val >= 40:
            parts.append(
                f"Relative strength vs Nifty is neutral ({_rs_val:.0f}/100 percentile) "
                f"— tracking the broad market rather than leading it."
            )
        else:
            parts.append(
                f"Relative strength vs Nifty is weak ({_rs_val:.0f}/100 percentile) "
                f"— lagging the broad market; any absolute-return uptick here is beta, not skill."
            )

    # Sentence 4: Volume + pattern
    if vol > 1.5 and bull_pats:
        parts.append(
            f"Notably, today's volume is {vol:.1f}× the 20-day average with a "
            f"{bull_pats[0]} candlestick pattern — a positive confirmation signal."
        )
    elif vol > 1.5:
        parts.append(
            f"Trading volume is {vol:.1f}× the normal level, indicating above-average buyer activity."
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

    # Sentence 6: VIX + sector (thresholds derived from n_sectors)
    vix_sentence_map = {
        "complacency": "Market is calm (low VIX) — good environment for equities but complacency risk.",
        "normal":      "Overall market conditions are normal (VIX in healthy range).",
        "elevated":    "Market fear is elevated (VIX rising) — consider smaller position size.",
        "fear":        "Market fear is high (VIX above 22) — use strict stop-losses.",
        "panic":       "Market is in panic mode (VIX above 28) — exercise extreme caution.",
    }
    vix_txt    = vix_sentence_map.get(vix_regime, "Market conditions are uncertain.")
    top_third  = n_sectors // 3
    mid_third  = 2 * n_sectors // 3
    sector_txt = (
        f"The {sector} sector is currently ranked #{sector_rank} — "
        + ("a tailwind for this stock." if sector_rank <= top_third else
           "neutral sector backdrop."   if sector_rank <= mid_third else
           "a headwind — sector is underperforming.")
    )
    parts.append(f"{vix_txt} {sector_txt}")

    # Sentence 7: FII/DII 5-day flows (FIX FLOWS1) — only when available.
    # The sub-scorer records the two sums on `pts["fii_5d"] / dii_5d`; we
    # read them off the sentiment detail dict passed via `sent_pts` in
    # score_dataframe. Keep this to one sentence so the narrative stays
    # readable; the full flow analysis lives on the FII/DII Flows page.
    if sent_pts.get("flows_available"):
        _f = sent_pts.get("fii_5d", 0.0)
        _d = sent_pts.get("dii_5d", 0.0)
        if _f > 0 and _d > 0:
            _flow_txt = ("FII and DII are both net buyers over the last 5 sessions "
                         "— broad institutional participation, a tailwind.")
        elif _f < 0 and _d < 0:
            _flow_txt = ("FII and DII are both net sellers over the last 5 sessions "
                         "— institutional distribution, a headwind.")
        elif _f < 0 and _d > 0:
            _flow_txt = ("FII selling absorbed by DII buying (5-day) — a domestic-supported "
                         "dip, historically a tradeable pullback rather than a trend break.")
        elif _f > 0 and _d < 0:
            _flow_txt = ("FII buying with DII taking profits (5-day) — rallies in this regime "
                         "tend to be shallower; keep stops tight.")
        else:
            _flow_txt = None
        if _flow_txt:
            parts.append(_flow_txt)

    return headline, " ".join(parts)


# ─────────────────────────────────────────────────────────────────────────────
# Main scoring functions
# ─────────────────────────────────────────────────────────────────────────────

def score_dataframe(
    df:           pd.DataFrame,
    ticker:       str,
    vix_info:     Optional[Dict] = None,
    sector_rank:  int = 7,
    sector:       str = "Other",
    n_sectors:    int = 15,
    dispersion:   Optional[float] = None,
    flows_info:   Optional[Dict] = None,
) -> "CompositeScore":
    """
    Score from a pre-fetched, indicator-enriched DataFrame.
    Call this when you already have the df to avoid redundant fetches.

    `dispersion` is the current cross-sectional 20-day return dispersion
    across the universe, as produced by
    analysis.regime.cross_sectional_dispersion_20d. When passed and below
    the low-dispersion threshold, the narrative for BUY/STRONG BUY signals
    gets a warning suffix — see FIX REGIME-DISP-SCORE below. Optional;
    callers that don't have it (e.g. single-stock ad-hoc scoring) can
    still pass None and get the previous behavior unchanged.
    """
    if vix_info is None:
        vix_info = {"regime": "normal", "vix": None, "allow_buy": True}

    tech_pts,  tech_detail = _score_technical(df)
    mom_pts,   mom_detail  = _score_momentum(df)
    vol_pts,   vol_detail  = _score_volume(df)
    pat_detail             = _detect_patterns(df)
    sent_pts,  sent_detail = _score_sentiment(vix_info, sector_rank, n_sectors,
                                              flows_info=flows_info)

    momentum_fallback = mom_detail.get("is_fallback", False)
    patterns          = pat_detail.get("patterns", [])

    total  = round(min(max(tech_pts + mom_pts + vol_pts + sent_pts, 0), 90.0), 1)
    grade  = _grade(total)
    action = _action(total)

    entry, sl, tp, rr = _compute_entry_levels(df, total)
    horizon_label, horizon_days = _pick_horizon(tech_pts, mom_pts)
    valid_until = (datetime.now() + timedelta(days=horizon_days)).date().isoformat()

    # FIX WL1: RSI/1-day-return were never exposed on CompositeScore, even
    # though RSI is already computed inside _score_technical() and both are
    # cheap to derive from the df already in scope here — no extra fetch.
    _cur = df.iloc[-1]
    rsi_val = float(_cur.get("RSI", 50))
    # FIX RS1: surface RS_Score on CompositeScore when present. None keeps
    # backwards-compat for callers that never enriched with a benchmark.
    _rs_raw = _cur.get("RS_Score")
    try:
        _rs_val = float(_rs_raw) if _rs_raw is not None else None
        if _rs_val is not None and math.isnan(_rs_val):
            _rs_val = None
    except (TypeError, ValueError):
        _rs_val = None
    _closes_1d = df["Close"].tail(2)
    return_1d_val = (
        float(_closes_1d.pct_change().iloc[-1]) * 100
        if len(_closes_1d) == 2 else 0.0
    )

    headline, narrative = _build_narrative(
        ticker=ticker, df=df, score=total, grade=grade, action=action,
        tech_pts=tech_detail, mom_pts=mom_detail, vol_pts=vol_detail,
        patterns=patterns,
        entry=entry, sl=sl, tp=tp, rr=rr,
        sector=sector, vix_regime=vix_info.get("regime", "normal"),
        sector_rank=sector_rank, n_sectors=n_sectors,
        momentum_fallback=momentum_fallback,
        sent_pts=sent_detail,   # FIX FLOWS1: flow sentence needs the detail dict
    )

    # FIX REGIME-DISP-SCORE — append the low-dispersion caution to the
    # narrative when the market is in a correlated (low-dispersion) regime
    # AND this is a BUY/STRONG BUY signal. That is the ONE stable filter
    # the Path B axis search produced (see analysis/regime.py). Kept as a
    # narrative append rather than a score deduction on purpose: the finding
    # is a hit-rate CAUTION, not a scoring re-weight (train/holdout show
    # different directions on the axis magnitude — see FIX REGIME-DISP for
    # the deliberate design choice not to overfit the effect direction).
    if dispersion is not None and action in ("BUY", "STRONG BUY"):
        try:
            from analysis.regime import dispersion_verdict as _dv
            _v = _dv(dispersion)
            if _v.get("zone") == "low" and _v.get("note"):
                narrative = narrative + " " + _v["note"]
        except Exception as _dispersion_e:
            _log.debug("dispersion narrative append skipped: %s", _dispersion_e)

    return CompositeScore(
        ticker            = ticker,
        price             = entry,
        score             = total,
        grade             = grade,
        action            = action,
        technical_score   = tech_pts,
        momentum_score    = mom_pts,
        volume_score      = vol_pts,
        sentiment_score   = sent_pts,
        patterns_detected = patterns,
        momentum_fallback = momentum_fallback,
        horizon           = horizon_label,
        valid_until       = valid_until,
        rsi               = rsi_val,
        return_1d         = return_1d_val,
        rs_score          = _rs_val,
        entry             = entry,
        stop_loss         = sl,
        target            = tp,
        risk_reward       = rr,
        headline          = headline,
        narrative         = narrative,
        sector            = sector,
        vix_regime        = vix_info.get("regime", "normal"),
        sector_rank       = sector_rank,
    )


def score_stock(
    ticker:           str,
    period:           str = "2y",
    vix_info:         Optional[Dict] = None,
    sector_scores_df: Optional["pd.DataFrame"] = None,
) -> "CompositeScore":
    """
    Full end-to-end scoring for any NSE stock.
    Fetches data, adds indicators, computes composite score, returns CompositeScore.
    Pass vix_info and sector_scores_df when scoring many stocks to reuse shared data.
    """
    _setup_encoding()

    if not _load_deps():
        return CompositeScore(
            ticker=ticker, price=0.0, score=0.0, grade="F",
            action="DATA_UNAVAILABLE",
            technical_score=0, momentum_score=0, volume_score=0, sentiment_score=0,
            entry=0, stop_loss=0, target=0, risk_reward=0,
            headline="Engine dependencies unavailable",
            narrative="Could not load required modules. Check your Python path setup.",
            sector="Unknown", vix_regime="unknown", sector_rank=7,
        )

    # Resolve ticker — catches all exception types, not just ValueError
    try:
        canonical = _resolve_ticker(ticker)
    except Exception as e:
        canonical = ticker if ticker.endswith(".NS") else ticker + ".NS"
        _log.debug("ticker resolution failed for %r, falling back to %r: %s",
                   ticker, canonical, e)

    # VIX
    if vix_info is None:
        try:
            vix_info = _get_india_vix_regime() if _get_india_vix_regime else None
        except Exception as e:
            vix_info = None
            _log.debug("VIX regime lookup failed, defaulting to 'normal': %s", e)
        if vix_info is None:
            vix_info = {"regime": "normal", "vix": None, "allow_buy": True}

    # Sector + rank
    sector     = _get_sector(canonical)
    n_sectors  = len(_list_sectors())
    sector_rank = 7
    if sector_scores_df is not None and not sector_scores_df.empty:
        if sector in sector_scores_df.index and "Rank" in sector_scores_df.columns:
            sector_rank = int(sector_scores_df.loc[sector, "Rank"])

    # Fetch + indicators
    try:
        df = _fetch_single(canonical, period=period)
        df = _add_all_indicators(df, groups=_SCORE_INDICATOR_GROUPS)

        # FIX RS1 (2026-09-03) — enrich with RS vs Nifty so _score_momentum
        # can use the abs:15 + RS:10 split. Best-effort: a benchmark-fetch
        # failure leaves the df without RS_Score, and momentum falls back
        # to the 25-pt absolute mode (documented in _score_momentum).
        try:
            from utils.indicators import add_relative_strength
            _bench = _fetch_single("^NSEI", period=period)
            if _bench is not None and not _bench.empty:
                df = add_relative_strength(df, _bench)
        except Exception as _rs_e:
            _log.debug("RS enrichment skipped for %s: %s: %s",
                       canonical, type(_rs_e).__name__, _rs_e)

        df.dropna(subset=["RSI", "ATR"], inplace=True)
        if len(df) < 30:
            raise ValueError(f"Insufficient data for {canonical}")
    except Exception as e:
        return CompositeScore(
            ticker=canonical, price=0.0, score=0.0, grade="F",
            action="DATA_UNAVAILABLE",
            technical_score=0, momentum_score=0, volume_score=0, sentiment_score=0,
            entry=0, stop_loss=0, target=0, risk_reward=0,
            headline=f"Data unavailable: {e}",
            narrative=f"Could not fetch data for {canonical}. Please check the ticker symbol.",
            sector=sector, vix_regime="unknown", sector_rank=sector_rank,
        )

    # FIX FLOWS1 (2026-09-03) — load FII/DII 5-day cash-market flows so the
    # Sentiment pillar can consume the sign. load_history() reads from the
    # trade_store cache the fii_dii cron populates; a miss here (no data yet,
    # DB unreachable) is best-effort: flows_info stays None and _score_sentiment
    # falls back to its legacy 6/4 split (documented in that function).
    flows_info: Optional[Dict] = None
    try:
        from analysis.fii_dii import load_history as _fd_load
        _fd = _fd_load(days=5)
        if _fd is not None and not _fd.empty and len(_fd) >= 3:
            flows_info = {
                "fii_5d": float(_fd["fii_net"].fillna(0).sum()),
                "dii_5d": float(_fd["dii_net"].fillna(0).sum()),
                "n_days": int(len(_fd)),
            }
    except Exception as _fl_e:
        _log.debug("FII/DII flows unavailable for scoring: %s: %s",
                   type(_fl_e).__name__, _fl_e)

    result = score_dataframe(
        df=df, ticker=canonical,
        vix_info=vix_info,
        sector_rank=sector_rank,
        sector=sector,
        n_sectors=n_sectors,
        flows_info=flows_info,
    )

    # Update entry to live price if Angel One is configured
    try:
        from data.angel_fetcher import get_live_quote, is_configured
        if is_configured():
            live = get_live_quote(canonical)
            if live and live["price"] > 0:
                live_price = live["price"]
                # FIX (entry/SL/TP staleness): stop_loss/target were computed
                # by _compute_entry_levels() against the previous CLOSE price.
                # Overwriting only entry/price with the live quote and leaving
                # SL/TP untouched could leave the displayed entry below its
                # own stop-loss, or a risk:reward ratio that no longer matches
                # the displayed numbers, any time the live price has moved
                # from the close (the normal case during market hours).
                # Preserve the ATR-based stop distance and conviction-scaled
                # target distance already computed, and re-anchor both to
                # the live price rather than recomputing from scratch (which
                # would need a fresh fetch + indicator pass).
                close_entry = result.entry
                risk_dist   = close_entry - result.stop_loss
                reward_dist = result.target - close_entry
                result.entry     = live_price
                result.price     = live_price
                result.stop_loss = round(live_price - risk_dist, 2)
                result.target    = round(live_price + reward_dist, 2)
                # risk_reward is a ratio of the two distances above, which
                # are unchanged — only re-anchored — so it stays valid as-is.
    except Exception as e:
        # live price update is best-effort — never fail the score, but log
        # so a broken Angel One connection isn't invisible during diagnosis.
        _log.debug("live price update skipped for %s: %s: %s",
                   canonical, type(e).__name__, e)

    return result
