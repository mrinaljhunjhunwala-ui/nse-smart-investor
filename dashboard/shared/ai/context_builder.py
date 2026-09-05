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


def collect_for_analyze_stock(symbol: str) -> ContextInputs:
    """Best-effort collector. Every field is optional; the LLM handles gaps.

    The Analyze Stock page symbol comes in as "RELIANCE" (no .NS suffix).
    `score_stock()` takes the .NS-suffixed ticker.
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

    yf_ticker = symbol if symbol.endswith(".NS") else f"{symbol}.NS"

    score_obj = _try(score_stock, yf_ticker) if score_stock else None
    vix_row = _try(get_india_vix_regime) if get_india_vix_regime else {}
    if not isinstance(vix_row, dict):
        vix_row = {}

    return ContextInputs(
        page="analyze_stock",
        stock=Stock(
            symbol=symbol,
            sector=_attr(score_obj, "sector"),
            ltp=_attr(score_obj, "price"),
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
        ),
        regime=Regime(
            india_vix=vix_row.get("vix"),
            vix_zone=(_attr(score_obj, "vix_regime") or vix_row.get("regime")),
            sector_rank=_attr(score_obj, "sector_rank"),
        ),
        portfolio=None,
        risk_rules=RiskRules(),
    )
