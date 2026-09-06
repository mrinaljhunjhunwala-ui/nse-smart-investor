"""
dashboard/shared/data_health.py - unified provider health snapshot for the
Command Centre `data_health` panel. Ships Task 2.3 from tasks/plan.md.

Design decision: read the state each provider already exposes (is_configured,
get_last_diagnostic, circuit-breaker registers) rather than launching live
probes on every render. Rationale:

  * Command Centre re-runs on every Streamlit interaction. Live probes would
    burn 8-12 network calls per interaction and would themselves become the
    slow page. Users care about "did fetches THAT HAVE RUN succeed", not
    "is every provider alive right now".
  * The moment a page actually needs a provider, it calls the fetcher, the
    fetcher populates its diagnostic, and this panel picks it up on the next
    render. That's the honest signal.
  * Providers with no captured activity render as "no recent activity"
    rather than fake-healthy.

Streamlit-free (Guardrail 11): the collector and render helper are both pure.
The Command Centre call site wraps the returned HTML with st.markdown.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Callable, Dict, List, Optional


# Status vocabulary (kept tiny on purpose - grows only when a check needs it):
#   healthy       - last diagnostic ok, or provider is configured/ready
#   stale         - last diagnostic present but old (> 30 min)
#   degraded      - non-fatal issue (e.g., Stooq circuit breaker tripped)
#   unavailable   - provider not configured / dependency missing
#   idle          - no captured activity this session (not necessarily bad)
STATUS_HEALTHY     = "healthy"
STATUS_STALE       = "stale"
STATUS_DEGRADED    = "degraded"
STATUS_UNAVAILABLE = "unavailable"
STATUS_IDLE        = "idle"

_HEALTHY_STATUSES = {STATUS_HEALTHY}
_DOWN_STATUSES    = {STATUS_STALE, STATUS_DEGRADED, STATUS_UNAVAILABLE}

_STALE_MINUTES = 30


@dataclass
class ProviderCheck:
    """One provider's current health snapshot."""
    name:            str                    # display name
    group:           str                    # "market" / "corp_info" / "news" / "options"
    status:          str                    # one of STATUS_*
    last_success_at: Optional[str] = None   # ISO string or None
    warnings:        int = 0
    note:            str = ""


# ─── individual probes (each returns a ProviderCheck; never raises) ──────────

def _parse_iso(iso: Optional[str]) -> Optional[datetime]:
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso)
    except (TypeError, ValueError):
        return None


def _status_from_diagnostic(diag: Optional[dict],
                            *, unavailable_reason: str = "") -> tuple[str, Optional[str], int, str]:
    """Fold a get_last_diagnostic()-style dict into (status, iso_at, warnings, note)."""
    if not diag:
        if unavailable_reason:
            return STATUS_UNAVAILABLE, None, 0, unavailable_reason
        return STATUS_IDLE, None, 0, "no recent activity"

    at = str(diag.get("at") or "") or None
    ok = bool(diag.get("ok"))
    warnings = int(diag.get("warnings", 0) or 0)
    note = str(diag.get("reason") or diag.get("note") or "")

    if not ok:
        # any recorded non-ok call, however recent, reads as degraded
        return STATUS_DEGRADED, at, warnings, note

    ts = _parse_iso(at)
    if ts is not None:
        ref = datetime.now(ts.tzinfo) if ts.tzinfo else datetime.now()
        if abs((ref - ts).total_seconds()) > _STALE_MINUTES * 60:
            return STATUS_STALE, at, warnings, note
    return STATUS_HEALTHY, at, warnings, note


def _try(fn: Callable, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except Exception:
        return None


def probe_angel() -> ProviderCheck:
    """Angel One: configured or not. No network."""
    try:
        from data.angel_fetcher import is_configured
    except ImportError:
        return ProviderCheck("Angel One SmartAPI", "market", STATUS_UNAVAILABLE,
                             note="module import failed")
    if _try(is_configured):
        return ProviderCheck("Angel One SmartAPI", "market", STATUS_HEALTHY,
                             note="credentials present")
    return ProviderCheck("Angel One SmartAPI", "market", STATUS_UNAVAILABLE,
                         note="no ANGEL_* env / secret")


def probe_stooq() -> ProviderCheck:
    """Stooq: circuit-breaker state from fetcher module."""
    try:
        from data.fetcher import _STOOQ_BREAKER, _STOOQ_BREAKER_COOLDOWN
    except ImportError:
        return ProviderCheck("Stooq CSV", "market", STATUS_UNAVAILABLE,
                             note="module import failed")
    fails = int(_STOOQ_BREAKER.get("consecutive_failures", 0))
    tripped_until = float(_STOOQ_BREAKER.get("tripped_until", 0.0))
    now = time.time()
    if tripped_until and now < tripped_until:
        remain = int(tripped_until - now)
        return ProviderCheck("Stooq CSV", "market", STATUS_DEGRADED,
                             warnings=fails,
                             note=f"circuit breaker open, retries in {remain}s")
    if fails > 0:
        return ProviderCheck("Stooq CSV", "market", STATUS_HEALTHY,
                             warnings=fails,
                             note=f"{fails} recent failure(s), breaker not tripped")
    return ProviderCheck("Stooq CSV", "market", STATUS_IDLE,
                         note="no recent activity")


def _probe_diagnostic_provider(display: str, group: str,
                               getter: Callable, canary_key: str,
                               unavailable_reason: str = "") -> ProviderCheck:
    diag = _try(getter, canary_key)
    status, at, warnings, note = _status_from_diagnostic(diag, unavailable_reason=unavailable_reason)
    return ProviderCheck(display, group, status, at, warnings, note)


def probe_nse_corp_info() -> ProviderCheck:
    try:
        from data.nse_corp_info import get_last_diagnostic
    except ImportError:
        return ProviderCheck("NSE corp-info", "corp_info", STATUS_UNAVAILABLE,
                             note="module import failed")
    return _probe_diagnostic_provider("NSE corp-info", "corp_info",
                                      get_last_diagnostic, "RELIANCE.NS")


def probe_bse_corp_info() -> ProviderCheck:
    try:
        from data.bse_corp_info import get_last_diagnostic
    except ImportError:
        return ProviderCheck("BSE corp-info", "corp_info", STATUS_UNAVAILABLE,
                             note="module import failed")
    diag = _try(get_last_diagnostic, "500325")
    if diag is None:
        # Package may not be installed; that's the dependency-gated deferral
        # documented in the audit (finding #5).
        return ProviderCheck("BSE corp-info", "corp_info", STATUS_UNAVAILABLE,
                             note="bse package not installed (GPLv3 pending)")
    status, at, warnings, note = _status_from_diagnostic(diag)
    return ProviderCheck("BSE corp-info", "corp_info", status, at, warnings, note)


def probe_news_feed() -> ProviderCheck:
    try:
        from data.news_feed import get_last_diagnostic
    except ImportError:
        return ProviderCheck("Google News RSS", "news", STATUS_UNAVAILABLE,
                             note="module import failed")
    return _probe_diagnostic_provider("Google News RSS", "news",
                                      get_last_diagnostic, "RELIANCE")


def probe_nse_rss() -> ProviderCheck:
    try:
        from data.nse_rss_feeds import get_last_diagnostic
    except ImportError:
        return ProviderCheck("NSE RSS feeds", "news", STATUS_UNAVAILABLE,
                             note="module import failed")
    # Poll all documented categories; if any populated, pick most-recent.
    categories = ("related_party_transactions", "reason_for_encumbrance",
                  "sast_regulation_29", "sast_regulation_31",
                  "corporate_governance", "insider_trading")
    latest_at: Optional[str] = None
    best_diag: Optional[dict] = None
    for cat in categories:
        diag = _try(get_last_diagnostic, cat)
        if not diag:
            continue
        at = str(diag.get("at") or "")
        if latest_at is None or at > latest_at:
            latest_at = at
            best_diag = diag
    status, at, warnings, note = _status_from_diagnostic(best_diag)
    return ProviderCheck("NSE RSS feeds", "news", status, at, warnings, note)


def collect_all_health() -> List[ProviderCheck]:
    """Every probe. Pure: no network, no Streamlit."""
    return [
        probe_angel(),
        probe_stooq(),
        probe_nse_corp_info(),
        probe_bse_corp_info(),
        probe_news_feed(),
        probe_nse_rss(),
    ]


# ─── rendering (pure HTML string; caller stamps via st.markdown) ─────────────

def _pill(status: str) -> str:
    """Small colored pill matching the status."""
    tone = {
        STATUS_HEALTHY:     ("--bull",   "✓ healthy"),
        STATUS_STALE:       ("--amber",  "○ stale"),
        STATUS_DEGRADED:    ("--bear",   "▲ degraded"),
        STATUS_UNAVAILABLE: ("--dim",    "✗ offline"),
        STATUS_IDLE:        ("--dim",    "· idle"),
    }.get(status, ("--dim", status))
    color, label = tone
    return (
        f'<span style="display:inline-flex;align-items:center;'
        f'padding:2px 8px;border-radius:999px;font-size:11px;font-weight:700;'
        f'letter-spacing:.3px;background:color-mix(in srgb, var({color}) 14%, transparent);'
        f'color:var({color});border:1px solid var({color})">{label}</span>'
    )


def _relative_time(iso: Optional[str]) -> str:
    ts = _parse_iso(iso)
    if ts is None:
        return "-"
    ref = datetime.now(ts.tzinfo) if ts.tzinfo else datetime.now()
    delta = ref - ts
    secs = int(abs(delta.total_seconds()))
    if secs < 60:
        return f"{secs}s ago"
    if secs < 3600:
        return f"{secs // 60}m ago"
    if secs < 86400:
        return f"{secs // 3600}h ago"
    return f"{secs // 86400}d ago"


def render_data_health_html(checks: Optional[List[ProviderCheck]] = None) -> str:
    """Compose the two-row `data_health` block: providers up / providers stale.

    Uses panel() from ui_components. Returns raw HTML; Streamlit caller
    should st.markdown(..., unsafe_allow_html=True).
    """
    from dashboard.shared.ui_components import panel

    if checks is None:
        checks = collect_all_health()

    up   = [c for c in checks if c.status in _HEALTHY_STATUSES]
    down = [c for c in checks if c.status in _DOWN_STATUSES]
    idle = [c for c in checks if c.status == STATUS_IDLE]

    def _row(c: ProviderCheck) -> str:
        rel = _relative_time(c.last_success_at)
        w_str = f' &middot; <span style="color:var(--amber)">{c.warnings} warn</span>' if c.warnings else ""
        note_html = f' &middot; <span style="color:var(--dim);font-size:11px">{c.note}</span>' if c.note else ""
        return (
            f'<div style="display:flex;align-items:center;justify-content:space-between;'
            f'gap:12px;padding:6px 0;border-bottom:1px solid var(--hairline-soft)">'
            f'<div style="display:flex;align-items:center;gap:10px;min-width:0">'
            f'  <span style="color:var(--ink);font-weight:600;font-size:13px">{c.name}</span>'
            f'  <span style="color:var(--dim);font-size:11px">[{c.group}]</span>'
            f'</div>'
            f'<div style="display:flex;align-items:center;gap:10px;font-size:12px;color:var(--ink-mid)">'
            f'  {_pill(c.status)}'
            f'  <span style="font-family:var(--font-mono);color:var(--dim)">{rel}</span>'
            f'  {w_str}{note_html}'
            f'</div>'
            f'</div>'
        )

    def _section(title: str, tone: str, rows: List[ProviderCheck]) -> str:
        if not rows:
            return ""
        body = "".join(_row(c) for c in rows)
        return panel(
            f'<div style="font-family:var(--font-mono);font-size:10px;'
            f'letter-spacing:1.2px;text-transform:uppercase;color:var(--dim);'
            f'font-weight:600;margin-bottom:6px">{title} &middot; {len(rows)}</div>'
            f'{body}',
            kind="flat", tone=tone, margin="6px 0",
        )

    parts = [
        _section("providers up",       "bull",    up),
        _section("providers degraded", "bear",    down),
        _section("providers idle",     "neutral", idle),
    ]
    if not any(parts):
        # Nothing to show; render an empty-state panel for symmetry.
        return panel(
            '<div style="color:var(--dim);font-size:12px">No provider health signal captured yet '
            '(nothing has been fetched this session).</div>',
            kind="flat", tone="neutral", margin="6px 0",
        )
    return "".join(p for p in parts if p)
