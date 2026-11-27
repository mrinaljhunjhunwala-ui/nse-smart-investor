"""
scripts/warm_tomorrow_watchlist.py — Scheduled Tomorrow's Watchlist pre-warm job.

FIX W-SPEED. Runs once after NSE market close (GitHub Actions — see
.github/workflows/warm-tomorrow-watchlist.yml) and writes a fresh
Tomorrow's Watchlist scan result to trade_store (shared Postgres, set via
DATABASE_URL).

Why this exists: dashboard/shared/cache.py's _tomorrow_watchlist() scans the
full Nifty Total Market universe (~750) and can take up to ~2 minutes cold. It's cached with
@st.cache_data(ttl=3600), but that cache is process-local to the running
Streamlit Cloud container — it doesn't survive a redeploy/restart, and on a
low-traffic app it routinely expires between visits. Whoever's browser
session happens to hit the expired cache pays the full cold scan — this is
the exact same problem scripts/warm_top_picks.py already solved for Command
Centre's Top Picks (FIX SPEED1), just never extended to this page.

This script runs the same scan headlessly and writes the result to
trade_store, which GitHub Actions and the deployed app both have real
network access to. The app's cache.get_tomorrow_watchlist() reads this
snapshot first and only falls back to its own live scan if the snapshot is
missing or older than 6 hours — see dashboard/shared/cache.py.

NOTE: this deliberately imports dashboard.shared.cache and calls
_tomorrow_watchlist() directly rather than re-implementing the scan/bucket
logic here, so there is exactly one place that logic lives and this can
never drift from what the app itself would compute — same discipline as
warm_top_picks.py.

Backfill (FIX TW-BACKFILL, 27 Nov 2026): with AS_OF_DATES="2026-11-25,2026-11-26"
in the environment (the workflow's as_of_dates input) or --as-of <dates>, the job
only rebuilds those past sessions point-in-time and logs them to the verdict
ledger as backfilled rows (see backfill()); no live scan, no snapshot overwrite,
no breadth snapshot.

Exit codes: always 0 — a failed warm-up should not fail the workflow or
block the next scheduled attempt; the app already degrades gracefully to a
live scan if no fresh snapshot is available.
"""
from __future__ import annotations

import datetime
import logging
import os
import sys

_log = logging.getLogger("scripts.warm_tomorrow_watchlist")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception as _enc_e:
    print(f"[startup] stdout reconfigure skipped: {_enc_e}")

# Make project root importable (script lives in <root>/scripts/)
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

_KV_KEY  = "tomorrow_watchlist_snapshot"
_KV_USER = "_system"


def parse_as_of_dates(raw: "str | None") -> "list[datetime.date]":
    """'2026-11-25, 2026-11-26' -> [date, date] (sorted, deduplicated). Empty or
    None -> []. Raises ValueError on a malformed entry."""
    out = set()
    for part in (raw or "").replace(";", ",").split(","):
        part = part.strip()
        if part:
            out.add(datetime.date.fromisoformat(part))
    return sorted(out)


def backfill(dates: "list[datetime.date]") -> int:
    """Rebuild Tomorrow's Watchlist for each past session in `dates` from data up
    to that day's close and log it to the verdict ledger as backfilled rows
    (dashboard/shared/cache.build_tomorrow_watchlist_as_of). Weekends, NSE
    holidays and sessions not yet closed are skipped with a log line. Never
    sends anything and never replaces the live snapshot; re-running a date adds
    nothing and never touches rows that were logged live. Returns the number of
    ledger rows added."""
    try:
        from analysis.verdict_ledger import last_closed_session
        from dashboard.shared.cache import build_tomorrow_watchlist_as_of
        from utils.nse_holidays import is_trading_day
        import trade_store as store
    except Exception as e:
        _log.error("backfill: import failed, aborting: %s", e)
        return 0
    added = 0
    for d in dates:
        if not is_trading_day(d):
            _log.info("backfill %s: skipped, not an NSE trading day (weekend or holiday)", d)
            continue
        if d > last_closed_session():
            _log.info("backfill %s: skipped, that session has not closed yet", d)
            continue
        _t0 = datetime.datetime.now()
        try:
            result = build_tomorrow_watchlist_as_of(d, n=15)
        except Exception as e:
            _log.warning("backfill %s: not rebuilt, nothing written: %s", d, e)
            continue
        pit = result.get("point_in_time") or {}
        added += int(pit.get("ledger_rows_added") or 0)
        _log.info(
            "backfill %s: done in %.1fs, scored %s of %s, breakout=%d breakdown=%d reversal=%d, "
            "ledger rows added=%s%s; VIX %s (%s); not point-in-time: %s",
            d, (datetime.datetime.now() - _t0).total_seconds(),
            result.get("n_scored"), result.get("n_universe"),
            len(result.get("breakout_candidates", [])), len(result.get("breakdown_watch", [])),
            len(result.get("reversal_watch", [])), pit.get("ledger_rows_added"),
            f" (SKIPPED: {pit['ledger_skipped']})" if pit.get("ledger_skipped") else "",
            pit.get("vix"), pit.get("vix_source"), "; ".join(pit.get("not_point_in_time") or []))
        # A record of the rebuilt list and what it could not see, one key per day.
        # The live snapshot (tomorrow_watchlist_snapshot) is left alone.
        store.kv_set(f"{_KV_KEY}:backfill:{d.isoformat()}",
                     {"data": result, "generated_at": store.snapshot_timestamp(),
                      "as_of": d.isoformat(), "backfilled": True}, user_id=_KV_USER)
    return added


def main() -> int:
    # AS_OF_DATES (workflow_dispatch input as_of_dates) or --as-of: backfill only.
    raw = os.environ.get("AS_OF_DATES", "")
    if "--as-of" in sys.argv[1:]:
        i = sys.argv.index("--as-of")
        raw = sys.argv[i + 1] if i + 1 < len(sys.argv) else ""
    if raw.strip():
        try:
            dates = parse_as_of_dates(raw)
        except ValueError as e:
            _log.error("backfill: bad as_of_dates %r (want YYYY-MM-DD, comma-separated): %s", raw, e)
            return 0
        _log.info("backfill: rebuilding Tomorrow's Watchlist for %s",
                  ", ".join(d.isoformat() for d in dates))
        backfill(dates)
        return 0
    try:
        from dashboard.shared.cache import _tomorrow_watchlist
        import trade_store as store
    except Exception as e:
        _log.error("warm_tomorrow_watchlist: import failed, aborting this run: %s", e)
        return 0

    _log.info("warm_tomorrow_watchlist: starting scan...")
    _t0 = datetime.datetime.now()
    try:
        result = _tomorrow_watchlist(n=15)
    except Exception as e:
        _log.error("warm_tomorrow_watchlist: scan failed, nothing persisted this run: %s", e)
        return 0
    _elapsed = (datetime.datetime.now() - _t0).total_seconds()
    _log.info(
        "warm_tomorrow_watchlist: scan done in %.1fs — breakout=%d breakdown=%d reversal=%d",
        _elapsed,
        len(result.get("breakout_candidates", [])),
        len(result.get("breakdown_watch", [])),
        len(result.get("reversal_watch", [])),
    )

    # FIX SNAPSHOT-GUARD: a mostly-failed scan must not replace a good snapshot.
    from utils.snapshot_time import scan_too_degraded
    _health = result.get("scan_health") or {}
    if scan_too_degraded(result.get("n_universe"), result.get("n_scored")):
        _log.error(
            "warm_tomorrow_watchlist: scan too degraded to persist (scored %s of %s; first "
            "unscored: %s; reasons: %s) — keeping the previous snapshot",
            result.get("n_scored"), result.get("n_universe"),
            ", ".join(_health.get("unavailable_sample") or []) or "n/a",
            _health.get("unavailable_reasons") or "n/a")
        return 0

    snapshot = {
        "data": result,
        "generated_at": store.snapshot_timestamp(),
        "scan_seconds": round(_elapsed, 1),
    }
    ok = store.kv_set(_KV_KEY, snapshot, user_id=_KV_USER)
    if ok:
        _log.info("warm_tomorrow_watchlist: persisted snapshot to trade_store (backend=%s)",
                  store.backend_name())
    else:
        _log.error("warm_tomorrow_watchlist: kv_set FAILED — snapshot not persisted this run "
                   "(app will fall back to a live scan)")
    _persist_breadth()
    return 0


def _persist_breadth() -> None:
    """Market-breadth snapshot from the price frames the scan just fetched
    (fetcher cache only, no network), persisted for the Command Centre panel
    and the verdict-ledger shadow label. Best-effort; never raises."""
    try:
        from data.market_breadth_loader import persist_snapshot, snapshot_from_scan
        from data.universe import get_universe
        _t0 = datetime.datetime.now()
        snap = snapshot_from_scan(get_universe("niftytotalmarket"), "niftytotalmarket")
        ok = persist_snapshot(snap)
        _log.info("warm_tomorrow_watchlist: breadth snapshot %s in %.1fs (%s)",
                  "persisted" if ok else "NOT persisted",
                  (datetime.datetime.now() - _t0).total_seconds(),
                  {k: (snap or {}).get(k) for k in ("date", "universe_size", "breadth_label")})
    except Exception as e:
        _log.error("warm_tomorrow_watchlist: breadth snapshot failed: %s", e)


if __name__ == "__main__":
    sys.exit(main())
