"""
dashboard.shared.ai.context_builder — Layer 2 of the co-pilot prompt.

Assembles the "current dashboard state" JSON block that gets prepended to
every turn. Two entry points:

    build_context(inputs: ContextInputs) -> str
        Pure. Take a dataclass of numbers, return the system-message string.
        The unit-testable half.

    collect_for_analyze_stock(symbol: str) -> ContextInputs
        Best-effort collector for the Analyze Stock page. Wraps every analysis
        call in try/except and populates whatever it can — a partial context
        is better than no panel. This is the impure half; it's what the panel
        actually calls at request time.

Design decision: the collector is a PLAIN FUNCTION, not a Streamlit-cached
one. Caching lives at the caller (dashboard/shared/cache.py conventions).
This keeps the module pure enough to unit-test with mocks.
"""
from __future__ import annotations

import datetime as _dt
import json
import logging
from dataclasses import dataclass, field, asdict
from typing import Any

_log = logging.getLogger(__name__)

# Round to 2 decimals for every number in the payload — anything more is noise
# for the LLM and just eats tokens.
_ROUND = 2


@dataclass
class Stock:
    symbol: str
    name: str | None = None
    sector: str | None = None
    ltp: float | None = None
    prev_close: float | None = None
    day_change_pct: float | None = None


@dataclass
class CompositeScore:
    total: float | None = None       # /90
    technical: float | None = None   # /40
    momentum: float | None = None    # /25
    volume: float | None = None      # /15
    sentiment: float | None = None   # /10


@dataclass
class Technicals:
    rsi_14: float | None = None
    macd_signal: str | None = None
    vwap_position: str | None = None
    sma_50_200: str | None = None
    cpr_stance: str | None = None


@dataclass
class Regime:
    india_vix: float | None = None
    vix_zone: str | None = None       # low / normal / elevated / high
    nifty_bias: str | None = None
    sector_rank: int | None = None    # 1..11


@dataclass
class Portfolio:
    avg_price: float | None = None
    quantity: int | None = None
    unrealised_pl_pct: float | None = None
    days_held: int | None = None


@dataclass
class RiskRules:
    max_position_pct: float | None = None
    atr_stop_multiplier: float | None = None
    min_rr: float | None = None


@dataclass
class ContextInputs:
    page: str
    stock: Stock
    composite_score: CompositeScore = field(default_factory=CompositeScore)
    technicals: Technicals = field(default_factory=Technicals)
    regime: Regime = field(default_factory=Regime)
    portfolio: Portfolio | None = None
    risk_rules: RiskRules = field(default_factory=RiskRules)
    user_note: str | None = None
    data_freshness: str | None = None  # "fresh" | "stale"


def _prune(obj: Any) -> Any:
    """Recursively drop None values and empty dicts. The LLM interprets
    empty blocks noisily; omission is cleaner."""
    if isinstance(obj, dict):
        pruned = {k: _prune(v) for k, v in obj.items()}
        return {k: v for k, v in pruned.items() if v not in (None, {}, [])}
    if isinstance(obj, list):
        return [_prune(x) for x in obj if x is not None]
    if isinstance(obj, float):
        return round(obj, _ROUND)
    return obj


def build_context(inputs: ContextInputs, *, now: _dt.datetime | None = None) -> str:
    """Assemble the per-turn system message. Pure. Deterministic given inputs+now."""
    ts = (now or _dt.datetime.now(_dt.timezone(_dt.timedelta(hours=5, minutes=30)))).isoformat(timespec="seconds")
    payload = _prune(asdict(inputs))
    body = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False)
    return f"CURRENT DASHBOARD STATE (as of {ts} IST):\n{body}"


# ── Best-effort collector for the Analyze Stock page ──────────────────────────

def _try(fn, *args, **kwargs):
    """Run fn; on any exception return None (with a debug log)."""
    try:
        return fn(*args, **kwargs)
    except Exception as e:  # broad by design — the collector must never crash the panel
        _log.debug("context collector: %s(%s) failed: %s", getattr(fn, "__name__", fn), args, e)
        return None


def _attr(obj: Any, name: str, default: Any = None) -> Any:
    """Fetch obj.name (dataclass) or obj[name] (dict), returning default on miss."""
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


# ── Narrative helpers - derive skill-spec strings from a scored dataframe ────
# These are pure functions kept in this module (not in analysis/) because they
# produce human-readable strings tuned for the LLM prompt, not scoring inputs.
# All best-effort: return None on any missing input rather than raise.

def _macd_signal_narrative(df: Any) -> str | None:
    """Return a one-liner describing the MACD state, or None if unavailable.

    Uses MACD - MACD_Signal (the histogram). Positive and rising = bullish.
    Sign change within the last 5 bars = "crossover N sessions ago".
    """
    try:
        macd = df["MACD"].astype(float)
        sig  = df["MACD_Signal"].astype(float)
        hist = (macd - sig).dropna()
        if len(hist) < 6:
            return None
        cur  = float(hist.iloc[-1])
        sign_now = 1 if cur > 0 else -1 if cur < 0 else 0
        # Look back up to 10 bars for a sign flip
        for i in range(2, min(11, len(hist) + 1)):
            prev = float(hist.iloc[-i])
            prev_sign = 1 if prev > 0 else -1 if prev < 0 else 0
            if prev_sign != 0 and prev_sign != sign_now:
                dir_word = "bullish" if sign_now > 0 else "bearish"
                return f"{dir_word} crossover {i - 1} session{'s' if i - 1 != 1 else ''} ago"
        # No recent crossover
        if sign_now > 0:
            return "MACD positive, no recent crossover"
        if sign_now < 0:
            return "MACD negative, no recent crossover"
        return "MACD flat"
    except Exception:
        return None


def _sma_50_200_narrative(df: Any) -> str | None:
    """Return a one-liner describing the SMA-50 vs SMA-200 stance."""
    try:
        s50  = df["SMA_50"].astype(float).dropna()
        s200 = df["SMA_200"].astype(float).dropna()
        if len(s50) < 2 or len(s200) < 2:
            return None
        # Align on last common index
        common = s50.index.intersection(s200.index)
        if len(common) < 2:
            return None
        a = s50.reindex(common)
        b = s200.reindex(common)
        cur_above = bool(a.iloc[-1] > b.iloc[-1])
        prev_above = bool(a.iloc[-2] > b.iloc[-2])
        # Detect a recent cross (in last ~60 bars) for context
        recent = (a > b).iloc[-60:] if len(a) >= 60 else (a > b)
        first_state = bool(recent.iloc[0])
        crossed_this_window = bool((recent != first_state).any())
        state = "50 above 200" if cur_above else "50 below 200"
        if crossed_this_window and cur_above:
            return f"{state} (golden cross regime, recent)"
        if crossed_this_window and not cur_above:
            return f"{state} (death cross regime, recent)"
        if cur_above:
            return f"{state} (established uptrend regime)"
        return f"{state} (established downtrend regime)"
    except Exception:
        return None


def _nifty_bias_narrative(label: str | None) -> str | None:
    """Map a RegimeSnapshot.label to the skill spec's nifty_bias phrasing."""
    if not label:
        return None
    return {
        "trend_up":   "trending up",
        "trend_down": "trending down",
        "range":      "range-bound",
        "risk_off":   "risk-off",
    }.get(label)


def _data_freshness(ts_iso: str | None, *, now: _dt.datetime | None = None,
                    stale_after_min: int = 15) -> str | None:
    """'fresh' if the score timestamp is within stale_after_min of now;
    'stale' otherwise; None if the timestamp isn't parseable."""
    if not ts_iso:
        return None
    try:
        ts = _dt.datetime.fromisoformat(ts_iso)
    except (TypeError, ValueError):
        return None
    ref = now or _dt.datetime.now(ts.tzinfo) if ts.tzinfo else (now or _dt.datetime.now())
    # Normalise both to naive-or-both-aware to avoid TypeError on subtract
    if ts.tzinfo and ref.tzinfo is None:
        ref = ref.replace(tzinfo=ts.tzinfo)
    if ref.tzinfo and ts.tzinfo is None:
        ts = ts.replace(tzinfo=ref.tzinfo)
    delta_min = abs((ref - ts).total_seconds()) / 60.0
    return "stale" if delta_min > stale_after_min else "fresh"


def collect_for_analyze_stock(symbol: str) -> ContextInputs:
    """Best-effort collector. Every field is optional; the LLM handles gaps.

    The Analyze Stock page symbol comes in as "RELIANCE" (no .NS suffix).
    `score_stock()` takes the .NS-suffixed ticker.

    Populates (from score_stock + a supplementary fetch_single call which is
    warm in the fetcher's in-process cache):
      stock: symbol, name (best-effort), sector, ltp, prev_close, day_change_pct
      composite_score: total + 4 sub-scores
      technicals: rsi_14, macd_signal, sma_50_200 (vwap_position and
                  cpr_stance are session-level intraday concepts left as None
                  for the daily-context path)
      regime: india_vix, vix_zone, nifty_bias, sector_rank
      data_freshness: from score.timestamp

    Does NOT populate:
      portfolio, risk_rules - these belong to the CALLER of render_chat_panel
        (see panel.py's portfolio= and risk_rules= kwargs). Pages that have
        holdings state pass them in; keeps this collector free of persistence
        coupling.
    """
    # Local imports so this module can be imported in test environments that
    # don't have the whole app installed.
    try:
        from analysis.score import score_stock  # type: ignore
    except ImportError:
        score_stock = None  # type: ignore
    try:
        from utils.vix import get_india_vix_regime  # type: ignore
    except ImportError:
        get_india_vix_regime = None  # type: ignore
    try:
        from data.fetcher import fetch_single  # type: ignore
    except ImportError:
        fetch_single = None  # type: ignore
    try:
        from utils.indicators import add_all_indicators  # type: ignore
    except ImportError:
        add_all_indicators = None  # type: ignore
    try:
        from analysis.regime import snapshot_live as _regime_snapshot  # type: ignore
    except ImportError:
        _regime_snapshot = None  # type: ignore
    try:
        from analysis.fundamentals.service import default_service as _fund_default  # type: ignore
    except ImportError:
        _fund_default = None  # type: ignore

    yf_ticker = symbol if symbol.endswith(".NS") else f"{symbol}.NS"

    score_obj = _try(score_stock, yf_ticker) if score_stock else None
    vix_row   = _try(get_india_vix_regime) if get_india_vix_regime else {}
    if not isinstance(vix_row, dict):
        vix_row = {}

    # Warm-cached df for prev_close + tech narrative
    df = None
    if fetch_single is not None:
        df = _try(fetch_single, yf_ticker, "2y")
        if df is not None and add_all_indicators is not None and not df.empty:
            df = _try(add_all_indicators, df) or df

    prev_close = None
    day_change_pct = None
    if df is not None and not df.empty and "Close" in df.columns and len(df) >= 2:
        try:
            closes = df["Close"].astype(float)
            prev_close = float(closes.iloc[-2])
            ltp_val    = float(closes.iloc[-1])
            if prev_close > 0:
                day_change_pct = (ltp_val / prev_close - 1.0) * 100.0
        except Exception:
            pass

    macd_signal   = _macd_signal_narrative(df) if df is not None else None
    sma_50_200    = _sma_50_200_narrative(df)  if df is not None else None

    # Regime snapshot for nifty_bias. Bounded work - snapshot_live has its
    # own caching per analysis.regime.
    regime_snap = _try(_regime_snapshot) if _regime_snapshot else None
    nifty_bias  = _nifty_bias_narrative(_attr(regime_snap, "label"))

    # Company name from fundamentals service (best-effort, may return None
    # for tickers without a fundamentals record).
    stock_name = None
    if _fund_default is not None:
        _cf = _try(lambda: _fund_default().get_fundamentals(yf_ticker))
        stock_name = _attr(_cf, "name") or _attr(_cf, "company_name")

    freshness = _data_freshness(_attr(score_obj, "timestamp"))

    return ContextInputs(
        page="analyze_stock",
        stock=Stock(
            symbol=symbol,
            name=stock_name,
            sector=_attr(score_obj, "sector"),
            ltp=_attr(score_obj, "price"),
            prev_close=prev_close,
            day_change_pct=day_change_pct,
        ),
        composite_score=CompositeScore(
            total=_attr(score_obj, "score"),
            technical=_attr(score_obj, "technical_score"),
            momentum=_attr(score_obj, "momentum_score"),
            volume=_attr(score_obj, "volume_score"),
            sentiment=_attr(score_obj, "sentiment_score"),
        ),
        technicals=Technicals(
            rsi_14=_attr(score_obj, "rsi"),
            macd_signal=macd_signal,
            sma_50_200=sma_50_200,
            # vwap_position and cpr_stance are session-level intraday concepts;
            # the daily-context path leaves them None so _prune omits them.
        ),
        regime=Regime(
            india_vix=vix_row.get("vix"),
            vix_zone=(_attr(score_obj, "vix_regime") or vix_row.get("regime")),
            nifty_bias=nifty_bias,
            sector_rank=_attr(score_obj, "sector_rank"),
        ),
        portfolio=None,       # caller supplies via render_chat_panel(portfolio=...)
        risk_rules=RiskRules(), # caller supplies via render_chat_panel(risk_rules=...)
        data_freshness=freshness,
    )
