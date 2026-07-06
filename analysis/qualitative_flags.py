"""
analysis/qualitative_flags.py — QF1

CompositeScore (technical/momentum/volume/sentiment — see analysis/score.py)
can only ever see price and volume. It structurally cannot know that a
company's promoter just increased pledging, that a state raised excise
duty overnight, or that a brand JV with a celebrity just launched. This
module adds that missing layer WITHOUT blending it into the composite
number — flags are shown alongside the score, not folded into it, so the
score stays honest about what it can and cannot see (same discipline as
dashboard/shared/disclosures.py's methodology notices).

Two flag sources:
  1. AUTO-DETECTED — parsed from data/nse_corp_info.py's top-corp-info
     payload (announcements, corporate actions, shareholding pattern).
     Conservative by design: keyword-matched, not NLP-classified, so
     sentiment defaults to AMBER unless a keyword is unambiguous.
  2. MANUAL — analyst-entered, for anything auto-detection can't reliably
     judge: celebrity JV / brand catalysts, premiumisation progress,
     state excise-policy watch, Union Budget sensitivity.

PERSISTENCE — uses the real trade_store signatures:
    kv_get(key: str, default: Any = None, user_id: str = "default") -> Any
    kv_set(key: str, value: Any, user_id: str = "default") -> bool
Pass the actual functions in from trade_store at the call site, e.g.:
    from trade_store import kv_get, kv_set
    flags = load_flags(ticker, kv_get)
    refresh_all_flags(ticker, kv_get, kv_set)

REFRESH CADENCE — daily, not real-time. These are announcement/filing-
driven events, not tick-driven. Run once at pre-open, e.g. alongside the
existing Top Picks background scan in 02_command_centre.py.

This module never touches analysis/score.py or CompositeScore.
"""

from __future__ import annotations

import datetime as _dt
import logging
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Callable, Optional

_log = logging.getLogger("analysis.qualitative_flags")

KvGet = Callable[..., Any]     # kv_get(key, default=None, user_id="default")
KvSet = Callable[..., bool]    # kv_set(key, value, user_id="default")


class FlagSentiment(str, Enum):
    GREEN = "green"    # positive factor
    RED = "red"        # negative / risk factor
    AMBER = "amber"    # mixed, unresolved, or "watch"


class FlagCategory(str, Enum):
    REGULATORY = "regulatory"              # excise policy, price approval cycles
    CORPORATE_ACTION = "corporate_action"  # QIP, buyback, debt repayment, rights issue
    GOVERNANCE = "governance"              # promoter holding / pledging changes
    NARRATIVE = "narrative"                # JV, celebrity tie-up, premium launch
    INPUT_COST = "input_cost"              # ENA/grain/glass/commodity pressure
    MACRO = "macro"                        # Union Budget, rural consumption, policy
    ANNOUNCEMENT = "announcement"          # keyword-matched NSE disclosure, uncategorized


@dataclass
class QualitativeFlag:
    ticker: str
    category: FlagCategory
    sentiment: FlagSentiment
    headline: str                 # short human-readable summary
    source: str                   # e.g. "NSE top-corp-info" or "Manual entry"
    date: str                     # ISO date the underlying event/filing occurred
    detected_at: str              # ISO datetime this flag was generated/refreshed
    expiry: Optional[str] = None  # ISO date after which this flag drops from view
    detail: Optional[str] = None  # optional longer note
    is_manual: bool = False       # True if hand-entered rather than auto-fetched

    def to_dict(self) -> dict:
        d = asdict(self)
        d["category"] = self.category.value
        d["sentiment"] = self.sentiment.value
        return d

    @staticmethod
    def from_dict(d: dict) -> "QualitativeFlag":
        d = dict(d)
        d["category"] = FlagCategory(d["category"])
        d["sentiment"] = FlagSentiment(d["sentiment"])
        return QualitativeFlag(**d)

    def is_active(self, as_of: Optional[_dt.date] = None) -> bool:
        if not self.expiry:
            return True
        as_of = as_of or _dt.date.today()
        try:
            return _dt.date.fromisoformat(self.expiry) >= as_of
        except ValueError:
            return True


# ---------------------------------------------------------------------------
# Curated, manually-maintained watch dict for state-level regulatory context.
# NOT auto-scraped — state excise policy news is not structured data
# anywhere. Update periodically, same spirit as the Vedanta/Tata Motors
# demerger entries added to STOCK_SEARCH_MAP in data/universe.py.
# ---------------------------------------------------------------------------
STATE_EXCISE_WATCH: dict[str, dict] = {
    # "ABDL.NS": {
    #     "state": "AP", "note": "Excise policy revision under review",
    #     "sentiment": FlagSentiment.AMBER, "date": "2026-06-01",
    # },
}


def build_regulatory_flags(ticker: str) -> list[QualitativeFlag]:
    """Curated state excise / regulatory watch entries for a ticker."""
    entry = STATE_EXCISE_WATCH.get(ticker)
    if not entry:
        return []
    now = _dt.datetime.now().isoformat()
    return [QualitativeFlag(
        ticker=ticker,
        category=FlagCategory.REGULATORY,
        sentiment=entry.get("sentiment", FlagSentiment.AMBER),
        headline=f"{entry['state']} excise/regulatory watch: {entry['note']}",
        source="Manual watchlist (analyst-curated)",
        date=entry.get("date", now[:10]),
        detected_at=now,
        is_manual=True,
    )]


def manual_flag(
    ticker: str,
    category: FlagCategory,
    sentiment: FlagSentiment,
    headline: str,
    source: str = "Manual entry",
    detail: Optional[str] = None,
    expiry: Optional[str] = None,
) -> QualitativeFlag:
    """Hand-add a narrative/catalyst flag from the UI — e.g. a celebrity JV
    announcement, or an update on a premium-launch's traction."""
    now = _dt.datetime.now()
    return QualitativeFlag(
        ticker=ticker, category=category, sentiment=sentiment, headline=headline,
        source=source, date=now.date().isoformat(), detected_at=now.isoformat(),
        detail=detail, expiry=expiry, is_manual=True,
    )


# ---------------------------------------------------------------------------
# Auto-detection from NSE's top-corp-info payload (data/nse_corp_info.py)
# ---------------------------------------------------------------------------

# Conservative keyword sentiment map for corporate actions / announcements.
# Deliberately short and unambiguous — anything not matched stays AMBER
# rather than guessing, per the codebase's no-silent-certainty discipline
# (see analysis/fundamentals/valuation_decision.py's confidence tiers).
_NEGATIVE_KEYWORDS = (
    "pledge", "encumbrance", "default", "resignation", "resign",
    "downgrade", "delay in payment", "delisting", "insolvency",
    "winding up", "fraud", "show cause", "penalty",
)
_POSITIVE_KEYWORDS = (
    "buyback", "bonus issue", "dividend", "credit rating upgrade",
    "upgrade", "stock split", "debt repayment", "debt reduction",
    "amalgamation approved",
)


def _classify_keyword_sentiment(text: str) -> FlagSentiment:
    low = text.lower()
    if any(k in low for k in _NEGATIVE_KEYWORDS):
        return FlagSentiment.RED
    if any(k in low for k in _POSITIVE_KEYWORDS):
        return FlagSentiment.GREEN
    return FlagSentiment.AMBER


def parse_announcement_flags(
    ticker: str, corp_info: dict, max_items: int = 5
) -> list[QualitativeFlag]:
    """Turn NSE's latest_announcements into flags. Keyword-classified only —
    treat AMBER results as "needs a human read", not "neutral"."""
    flags: list[QualitativeFlag] = []
    now = _dt.datetime.now().isoformat()
    items = (corp_info.get("latest_announcements") or {}).get("data") or []
    for item in items[:max_items]:
        subject = str(item.get("subject") or "").strip()
        if not subject:
            continue
        bdate = str(item.get("broadcastdate") or now[:10])
        flags.append(QualitativeFlag(
            ticker=ticker,
            category=FlagCategory.ANNOUNCEMENT,
            sentiment=_classify_keyword_sentiment(subject),
            headline=subject[:180],
            source="NSE top-corp-info: latest_announcements",
            date=bdate,
            detected_at=now,
        ))
    return flags


def parse_corporate_action_flags(
    ticker: str, corp_info: dict, max_items: int = 5
) -> list[QualitativeFlag]:
    """Turn NSE's corporate_actions (buyback/rights/QIP/dividend/etc.) into
    flags. `purpose` is NSE's own free-text field for the action type."""
    flags: list[QualitativeFlag] = []
    now = _dt.datetime.now().isoformat()
    items = (corp_info.get("corporate_actions") or {}).get("data") or []
    for item in items[:max_items]:
        purpose = str(item.get("purpose") or "").strip()
        if not purpose:
            continue
        exdate = str(item.get("exdate") or now[:10])
        flags.append(QualitativeFlag(
            ticker=ticker,
            category=FlagCategory.CORPORATE_ACTION,
            sentiment=_classify_keyword_sentiment(purpose),
            headline=purpose[:180],
            source="NSE top-corp-info: corporate_actions",
            date=exdate,
            detected_at=now,
        ))
    return flags


def parse_shareholding_flags(ticker: str, corp_info: dict) -> list[QualitativeFlag]:
    """Compare the two most recent shareholding-pattern dates for promoter
    holding / pledge-related fields.

    shareholdings_patterns is {date_str: [ {field: value, ...}, ... ]} with
    NSE-defined field names that are not guaranteed stable across endpoint
    versions. Rather than hardcode one field name, this searches every
    field name in each record for "promoter" or "pledg" (case-insensitive)
    and compares values across the two newest dates. If neither substring
    is found in the payload, this returns [] — it does NOT invent a flag
    from absent data (see module docstring: pledge % may not be present in
    this endpoint at all; that's a known, documented gap, not a bug here).
    """
    flags: list[QualitativeFlag] = []
    now = _dt.datetime.now().isoformat()
    patterns = (corp_info.get("shareholdings_patterns") or {}).get("data") or {}
    if not isinstance(patterns, dict) or len(patterns) < 2:
        return flags

    # Dates as given by NSE — sort descending, assume ISO-ish or DD-MM-YYYY
    # strings; fall back to raw string sort if unparseable.
    def _parse_date(s: str) -> _dt.date:
        for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d-%b-%Y"):
            try:
                return _dt.datetime.strptime(s, fmt).date()
            except ValueError:
                continue
        return _dt.date.min

    dates_sorted = sorted(patterns.keys(), key=_parse_date, reverse=True)
    latest_date, prior_date = dates_sorted[0], dates_sorted[1]
    latest_rows = patterns.get(latest_date) or []
    prior_rows = patterns.get(prior_date) or []
    if not latest_rows or not prior_rows:
        return flags

    def _extract(rows: list[dict], needles: tuple[str, ...]) -> Optional[float]:
        for row in rows:
            for k, v in row.items():
                kl = k.lower()
                if any(n in kl for n in needles):
                    try:
                        return float(str(v).replace("%", "").strip())
                    except (ValueError, TypeError):
                        continue
        return None

    # NSE's actual field naming is inconsistent across endpoints/versions —
    # "pr_and_prgrp" (the confirmed real field for promoter+promoter-group
    # holding %) does not contain the substring "promoter", so match on
    # both the human word and NSE's own abbreviation.
    _PROMOTER_NEEDLES = ("promoter", "pr_and_prgrp", "pr_grp")
    _PLEDGE_NEEDLES = ("pledg", "encumbra")

    for needles, label, is_pledge in (
        (_PROMOTER_NEEDLES, "Promoter holding", False),
        (_PLEDGE_NEEDLES, "Promoter pledge", True),
    ):
        cur = _extract(latest_rows, needles)
        prior = _extract(prior_rows, needles)
        if cur is None or prior is None:
            continue
        delta = cur - prior
        if abs(delta) < 0.5:
            continue
        if is_pledge:
            sentiment = FlagSentiment.RED if delta > 0 else FlagSentiment.GREEN
        else:  # promoter holding: rising is good, falling is a caution
            sentiment = FlagSentiment.GREEN if delta > 0 else FlagSentiment.RED
        flags.append(QualitativeFlag(
            ticker=ticker,
            category=FlagCategory.GOVERNANCE,
            sentiment=sentiment,
            headline=f"{label} moved {prior:.1f}% -> {cur:.1f}% "
                     f"({prior_date} -> {latest_date})",
            source="NSE top-corp-info: shareholdings_patterns",
            date=latest_date,
            detected_at=now,
        ))
    return flags


def build_auto_flags(ticker: str, corp_info: dict) -> list[QualitativeFlag]:
    """Run all auto-detectors against one fetched corp_info payload."""
    if not corp_info:
        return []
    flags: list[QualitativeFlag] = []
    flags.extend(parse_shareholding_flags(ticker, corp_info))
    flags.extend(parse_corporate_action_flags(ticker, corp_info))
    flags.extend(parse_announcement_flags(ticker, corp_info))
    return flags


# ---------------------------------------------------------------------------
# Persistence — matches trade_store.kv_get / kv_set exactly.
# ---------------------------------------------------------------------------

def _flags_key(ticker: str) -> str:
    return f"qualitative_flags:{ticker}"


def save_flags(ticker: str, flags: list[QualitativeFlag], kv_set: KvSet,
               user_id: str = "default") -> bool:
    payload = [f.to_dict() for f in flags]
    return kv_set(_flags_key(ticker), payload, user_id)


def load_flags(ticker: str, kv_get: KvGet, as_of: Optional[_dt.date] = None,
                user_id: str = "default") -> list[QualitativeFlag]:
    """Returns only currently-active (non-expired) flags."""
    raw = kv_get(_flags_key(ticker), [], user_id)
    if not raw:
        return []
    try:
        flags = [QualitativeFlag.from_dict(d) for d in raw]
    except (KeyError, ValueError) as e:
        _log.warning("load_flags(%s): corrupt stored payload, discarding: %s", ticker, e)
        return []
    return [f for f in flags if f.is_active(as_of)]


def refresh_all_flags(
    ticker: str, kv_get: KvGet, kv_set: KvSet,
    corp_info: Optional[dict] = None, user_id: str = "default",
) -> list[QualitativeFlag]:
    """Rebuild the flag set for a ticker: fetch fresh auto-flags, merge with
    any existing manual flags (manual flags are preserved, not overwritten —
    they're analyst judgment calls, not something a refresh should clobber).

    If corp_info is not passed in, fetches it via data/nse_corp_info.py.
    Fetch failures degrade to [] auto-flags rather than raising — a flag
    refresh failing should never block the rest of the analysis page.
    """
    existing = load_flags(ticker, kv_get, user_id=user_id)
    manual = [f for f in existing if f.is_manual]

    if corp_info is None:
        try:
            from data.nse_corp_info import get_corp_info
            corp_info = get_corp_info(ticker)
        except Exception as e:
            _log.warning("refresh_all_flags(%s): nse_corp_info fetch failed: %s", ticker, e)
            corp_info = {}

    fresh: list[QualitativeFlag] = []
    fresh.extend(build_regulatory_flags(ticker))
    fresh.extend(build_auto_flags(ticker, corp_info))

    merged = manual + fresh
    save_flags(ticker, merged, kv_set, user_id=user_id)
    return merged


def summarize_flags(flags: list[QualitativeFlag]) -> dict:
    """Quick counts for a badge/summary row, e.g. '2 green, 1 red, 1 amber'."""
    out = {"green": 0, "red": 0, "amber": 0}
    for f in flags:
        out[f.sentiment.value] += 1
    return out
