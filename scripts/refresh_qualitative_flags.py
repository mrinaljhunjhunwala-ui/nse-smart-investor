"""
scripts/refresh_qualitative_flags.py — Manual/scheduled qualitative-flags
refresh. MUST be run from a NON-cloud machine (home broadband, a laptop,
etc.) — NOT GitHub Actions and NOT Streamlit Cloud.

WHY NOT GITHUB ACTIONS: see the "KNOWN OPERATIONAL LIMITATION" section of
data/nse_corp_info.py's module docstring. NSE's WAF blocks essentially all
cloud/datacenter IP ranges, and GitHub Actions runners sit on Azure ranges
just like Streamlit Cloud does — so scheduling this as a workflow (the
pattern used for scripts/warm_top_picks.py) would NOT dodge the block; it
would just fail from a different cloud IP. A residential/home connection is
the one thing that reliably isn't on that IP-reputation blocklist. Run this
manually, or from a home-machine cron/Task Scheduler entry, not from CI.

WHAT IT DOES: for each ticker in the target list, calls
analysis.qualitative_flags.refresh_all_flags(ticker, trade_store.kv_get,
trade_store.kv_set, company_name=...) — the exact same function the app
itself calls the first time a session views a ticker's flags — and writes
the result into the same shared Postgres (DATABASE_URL) the deployed app
reads from (dashboard.shared.flags_ui.get_cached_flags ->
analysis.qualitative_flags.load_flags). The deployed app still attempts its
own live fetch too on top of this (get_cached_flags always does), but on
Streamlit Cloud that live fetch keeps hitting the WAF block — this script is
what actually populates real NSE/RSS-derived flags for the app to fall back
to instead of an empty or manual-only list.

TARGET LIST (--source, default "active"):
  active    - union of: open paper-trade/portfolio tickers, the latest
              persisted Top Picks snapshot (buys+sells), and the latest
              persisted Tomorrow's Watchlist snapshot. This is "whatever the
              app is actually showing someone right now" — a few dozen
              names, not the full universe, so a run finishes in minutes.
  universe  - the full niftytotalmarket universe (~745 tickers). Much
              slower (expect 30-60+ min at a polite --delay) — meant for an
              occasional (e.g. weekly) home-machine run, not every time.
  --tickers TICKER1,TICKER2,... - explicit list, overrides --source.

USAGE:
  python scripts/refresh_qualitative_flags.py
  python scripts/refresh_qualitative_flags.py --source universe --delay 3
  python scripts/refresh_qualitative_flags.py --tickers RELIANCE,TCS,INFY
  python scripts/refresh_qualitative_flags.py --limit 5   # quick test run

Requires DATABASE_URL in the environment, pointing at the SAME Neon Postgres
instance configured in Streamlit Cloud's secrets (see dashboard/DB_SETUP.md).
Without it, trade_store falls back to a local SQLite file only this machine
can see, which makes the run pointless for the deployed app — this script
checks trade_store.backend_name() and warns loudly if it isn't Postgres.

Exit code: 0 if every ticker refreshed without error, 1 if any failed (so a
cron/Task Scheduler entry can alert on repeated failures — but note a single
ticker failing here is expected occasionally, e.g. NSE 5xx/timeout, and does
not itself indicate an IP block; refresh_all_flags degrades per-source
internally, so a "failure" logged here means the WHOLE call raised, which
is unusual — normally missing NSE data alone still returns news/RSS flags).
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time

_log = logging.getLogger("scripts.refresh_qualitative_flags")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


def _active_tickers() -> list:
    """(ticker, company_name) pairs from open positions + the latest
    persisted Top Picks / Tomorrow's Watchlist snapshots. company_name is
    best-effort (None if absent from a snapshot) — refresh_all_flags works
    fine without it, just slightly less accurate news/RSS matching.

    Reads snapshots directly via kv_get rather than going through
    dashboard.shared.cache.get_top_picks()/get_tomorrow_watchlist() on
    purpose — those functions fall back to running a LIVE scan when the
    persisted snapshot is missing/stale, which this script has no business
    triggering (that's Top Picks' / Tomorrow Watchlist's own job, on their
    own schedule). A stale or missing snapshot here just means fewer
    tickers get flag-refreshed this run, not an error.
    """
    import trade_store as store

    seen: dict = {}

    try:
        df = store.fetch_open()
        for _, row in df.iterrows():
            tkr = str(row.get("ticker") or "").strip()
            if tkr:
                seen.setdefault(tkr, None)
    except Exception as e:
        _log.warning("could not read open positions: %s", e)

    try:
        snap = store.kv_get("top_picks_snapshot", user_id="_system")
        if snap and isinstance(snap, dict):
            data = snap.get("data", {}) or {}
            for bucket in ("buys", "sells"):
                for pick in (data.get(bucket) or []):
                    tkr = str((pick or {}).get("ticker") or "").strip()
                    if tkr:
                        seen.setdefault(tkr, (pick or {}).get("company_name"))
    except Exception as e:
        _log.warning("could not read top_picks_snapshot: %s", e)

    try:
        snap = store.kv_get("tomorrow_watchlist_snapshot", user_id="_system")
        if snap and isinstance(snap, dict):
            for bucket in ("breakout_candidates", "breakdown_watch", "reversal_watch"):
                for item in (snap.get(bucket) or []):
                    tkr = str((item or {}).get("ticker") or "").strip()
                    if tkr:
                        seen.setdefault(tkr, (item or {}).get("company_name"))
    except Exception as e:
        _log.warning("could not read tomorrow_watchlist_snapshot: %s", e)

    return list(seen.items())


def _universe_tickers() -> list:
    from data.universe import get_universe
    return [(t, None) for t in get_universe("niftytotalmarket")]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Refresh qualitative flags from a non-cloud machine.")
    parser.add_argument("--source", choices=["active", "universe"], default="active")
    parser.add_argument("--tickers", default=None,
                        help="Comma-separated explicit ticker list, overrides --source")
    parser.add_argument("--delay", type=float, default=2.5,
                        help="Seconds to wait between tickers (politeness — default 2.5)")
    parser.add_argument("--limit", type=int, default=None,
                        help="Cap the number of tickers processed (for a quick test run)")
    args = parser.parse_args()

    import trade_store as store
    from analysis.qualitative_flags import refresh_all_flags

    backend = store.backend_name()
    _log.info("trade_store backend: %s", backend)
    if backend.lower() not in ("postgres", "postgresql", "pg"):
        _log.warning(
            "backend is NOT Postgres — this run's results will only be visible on THIS "
            "machine, not the deployed app. Set DATABASE_URL to the same Neon instance "
            "configured in Streamlit Cloud's secrets before running this for real."
        )

    if args.tickers:
        targets = [(t.strip().upper(), None) for t in args.tickers.split(",") if t.strip()]
        source_label = "explicit"
    elif args.source == "universe":
        targets = _universe_tickers()
        source_label = "universe"
    else:
        targets = _active_tickers()
        source_label = "active"

    if args.limit:
        targets = targets[: args.limit]

    _log.info("refreshing qualitative flags for %d ticker(s), source=%s",
              len(targets), source_label)

    if not targets:
        _log.warning("no tickers to refresh (empty target list) — nothing to do")
        return 0

    ok, failed = 0, []
    for i, (ticker, company_name) in enumerate(targets, 1):
        try:
            flags = refresh_all_flags(ticker, store.kv_get, store.kv_set,
                                      company_name=company_name)
            _log.info("[%d/%d] %s: %d flag(s)", i, len(targets), ticker, len(flags))
            ok += 1
        except Exception as e:
            _log.error("[%d/%d] %s: FAILED — %s", i, len(targets), ticker, e)
            failed.append(ticker)
        if i < len(targets) and args.delay > 0:
            time.sleep(args.delay)

    _log.info("done: %d ok, %d failed%s", ok, len(failed),
              f" ({', '.join(failed)})" if failed else "")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
