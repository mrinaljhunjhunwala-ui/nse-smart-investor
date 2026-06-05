"""analysis/fundamentals/valuation.py — Valuation Context (Phase C1).

Surfaces valuation MULTIPLES that already exist in the fundamentals schema (P/E, P/B,
EV/EBITDA) as a small, typed `ValuationContext`. This is a factual surfacing layer ONLY:

  * NO peer-relative valuation, NO historical bands, NO cheap/expensive judgment.
  * `None` when a multiple is unavailable — values are NEVER fabricated.
  * EV/EBITDA is taken from the Yahoo `info["enterpriseToEbitda"]` we already fetch
    (mapped into `RatioSnapshot.ev_ebitda`); no new data provider.

Confidence is a simple coverage signal: how many of the three multiples are present.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from .models import CompanyFundamentals

# A valid multiple must be a positive finite number; a non-positive P/E (loss-making) or
# zero is reported as unavailable rather than as a misleading number.
_FIELDS = ("pe", "pb", "ev_ebitda")
_LABELS = {"pe": "P/E", "pb": "P/B", "ev_ebitda": "EV/EBITDA"}


@dataclass
class ValuationContext:
    pe: Optional[float] = None
    pb: Optional[float] = None
    ev_ebitda: Optional[float] = None
    confidence: str = "none"            # high | medium | low | none
    missing_fields: List[str] = field(default_factory=list)
    source: Optional[str] = None        # provider name, for provenance
    # ── sector awareness (Phase D1) ──
    ev_ebitda_applicable: bool = True   # False for financials (not meaningful)
    preferred_valuation: Optional[str] = None   # e.g. "P/B + ROE" for banks
    notes: List[str] = field(default_factory=list)

    def available_count(self) -> int:
        return sum(1 for v in (self.pe, self.pb, self.ev_ebitda) if v is not None)

    def to_dict(self) -> dict:
        return {"pe": self.pe, "pb": self.pb, "ev_ebitda": self.ev_ebitda,
                "confidence": self.confidence, "missing_fields": list(self.missing_fields),
                "source": self.source, "ev_ebitda_applicable": self.ev_ebitda_applicable,
                "preferred_valuation": self.preferred_valuation, "notes": list(self.notes)}


def _clean(v) -> Optional[float]:
    """Accept only a positive, finite multiple; else None (never fabricate)."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f != f or f in (float("inf"), float("-inf")):   # NaN / inf
        return None
    if f <= 0:                                          # negative/zero P/E etc. → not meaningful
        return None
    return round(f, 2)


def build_valuation_context(cf: Optional[CompanyFundamentals],
                            sector_profile=None) -> ValuationContext:
    """Map the already-fetched multiples into a ValuationContext. Pure; no network.

    Sector-aware (Phase D1): for financials, EV/EBITDA is **not meaningful** — it is
    suppressed (not shown, not counted as "missing") and replaced with explanatory context;
    P/B + ROE is flagged as the right lens.
    """
    ratios = getattr(cf, "ratios", None) if cf is not None else None
    vals = {f: _clean(getattr(ratios, f, None)) if ratios is not None else None for f in _FIELDS}

    ev_applicable = sector_profile is None or getattr(sector_profile, "ev_ebitda_meaningful", True)
    notes: List[str] = []
    preferred = getattr(sector_profile, "preferred_valuation", None) if sector_profile else None

    if not ev_applicable:
        vals["ev_ebitda"] = None
        notes.append("EV/EBITDA is not meaningful for financial companies — assessed on "
                     "P/B and ROE instead.")

    # Confidence + missing are computed over the APPLICABLE fields only, so suppressing an
    # inapplicable metric never penalises coverage.
    applicable = [f for f in _FIELDS if f != "ev_ebitda" or ev_applicable]
    missing = [_LABELS[f] for f in applicable if vals[f] is None]
    present = len(applicable) - len(missing)
    n = len(applicable)
    confidence = ("high" if present == n and n > 0 else "medium" if present >= 2
                  else "low" if present == 1 else "none")

    return ValuationContext(
        pe=vals["pe"], pb=vals["pb"], ev_ebitda=vals["ev_ebitda"],
        confidence=confidence, missing_fields=missing,
        source=getattr(cf, "provider_name", None) if cf is not None else None,
        ev_ebitda_applicable=ev_applicable, preferred_valuation=preferred, notes=notes,
    )
