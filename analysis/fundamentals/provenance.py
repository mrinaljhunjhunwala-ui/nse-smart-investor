"""Where a company's fundamentals came from and how old they are, as one line.

Pure: no Streamlit, no network. Used next to fundamental figures on Analyze
Stock and Quality Watch so a number is never shown without its date and source.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, Optional

STALE_AFTER_DAYS = 550          # an annual statement older than ~18 months: a newer one should exist


def _d(x: Any) -> Optional[date]:
    if isinstance(x, datetime):
        return x.date()
    return x if isinstance(x, date) else None


def provenance(cf: Any, today: Optional[date] = None) -> Dict[str, Any]:
    """{"label", "statement_date", "age_days", "stale", "source", "fetched"} for a
    CompanyFundamentals-like object. Missing parts are None; never raises."""
    out: Dict[str, Any] = {"label": "", "statement_date": None, "age_days": None,
                           "stale": False, "source": None, "fetched": None}
    if cf is None:
        out["label"] = "No company financials found"
        return out
    today = today or date.today()
    sd = _d(getattr(cf, "statement_date", None))
    if sd is None:
        try:
            inc = cf.latest_income()
            sd = _d(getattr(inc, "period_end", None))
        except Exception:                                       # noqa: BLE001
            sd = None
    src = str(getattr(cf, "provider_name", "") or "").strip() or None
    fetched = _d(getattr(cf, "last_updated", None))
    parts = []
    if sd is not None:
        age = (today - sd).days
        out.update(statement_date=sd, age_days=age, stale=age > STALE_AFTER_DAYS)
        parts.append(f"Annual figures for the year ended {sd.day} {sd:%b %Y}")
        if out["stale"]:
            parts.append(f"about {age // 30} months old, a newer year may not be loaded")
    else:
        parts.append("Statement date not reported by the source")
    if src:
        parts.append(f"source {src}")
    if fetched is not None:
        parts.append(f"fetched {fetched.day} {fetched:%b}")
    out.update(source=src, fetched=fetched, label=" · ".join(parts))
    return out
