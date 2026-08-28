"""
scripts/warm_top_picks.py — Scheduled Top Picks pre-warm job.

FIX SPEED1. Runs on a schedule (GitHub Actions — see
.github/workflows/warm-top-picks.yml) and writes a fresh Top Picks scan
result to trade_store (shared Postgres, set via DATABASE_URL) so the
deployed app can read it instantly instead of paying the ~2-minute
cold-scan cost on whichever visit happens to hit an expired in-app cache.

Why this exists: dashboard/shared/cache.py's _home_top_picks() scans the
full niftytotalmarket universe (~745 tickers) and can take up to ~2 minutes
cold. It's cached with @st.cache_data(ttl=300), but that cache is
process-local to the running Streamlit Cloud container — it doesn't survive
a redeploy/restart, and on a low-traffic app it routinely expires between
visits. Whoever's browser session happens to hit the expired cache pays the
full cold scan.

This script runs the same scan headlessly and writes the result to
trade_store, which GitHub Actions and the deployed app both have real
network access to. The app's get_top_picks() reads this snapshot first and
only falls back to its own live scan if the snapshot is missing or older
than _TOP_PICKS_MAX_AGE_SECONDS — see dashboard/shared/cache.py.

NOTE: this deliberately imports dashboard.shared.cache and calls
_home_top_picks() directly (with the same vix_regime/sector_ranks inputs
get_top_picks() itself would use), plus reuses the module's own KV key
constants, rather than re-implementing the scan/persist logic here — so
there is exactly one place that logic lives and this can never drift from
what the app itself would compute. Same discipline as
warm_tomorrow_watchlist.py.

Exit codes: always 0 — a failed warm-up should not fail the workflow or
block the next scheduled attempt; the app already degrades gracefully to a
live scan if no fresh snapshot is available.
"""
from __future__ import annotations

import datetime
import logging
import os
import sys

_log = logging.getLogger("scripts.warm_top_picks")
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


def main() -> int:
    try:
        from dashboard.shared.cache import (
            _home_top_picks,
            _TOP_PICKS_KV_KEY,
            _TOP_PICKS_KV_USER,
            get_vix_info,
            _sector_ranks_tuple,
        )
        from dashboard.shared.market_hours import is_trading_day
        import trade_store as store
    except Exception as e:
        _log.error("warm_top_picks: import failed, aborting this run: %s", e)
        return 0

    # FIX HOL1: the workflow's cron is weekday-only (Mon-Fri), which does NOT
    # account for NSE holidays that fall on a weekday (Republic Day, Holi,
    # Diwali, etc. — see dashboard/shared/market_hours.py's NSE_HOLIDAYS,
    # the single canonical calendar every other market-hours check in this
    # repo already delegates to). Without this guard, a holiday still burns
    # a full ~745-ticker scan every 15 minutes for ~8 hours, producing an
    # unchanging snapshot (nothing traded) while writing a timestamp that
    # misleadingly looks freshly updated. Checks the DAY only (not
    # time-of-day) since this job deliberately also runs pre-open/post-close.
    if not is_trading_day():
        _log.info("warm_top_picks: not a trading day (weekend or NSE holiday) — skipping scan.")
        return 0

    _log.info("warm_top_picks: starting scan...")
    _t0 = datetime.datetime.now()
    try:
        _vix = get_vix_info()
        _sectors = _sector_ranks_tuple()
        result = _home_top_picks(
            vix_regime=_vix.get("regime", "normal"),
            n=20,
            sector_ranks=_sectors,
        )
    except Exception as e:
        _log.error("warm_top_picks: scan failed, nothing persisted this run: %s", e)
        return 0
    _elapsed = (datetime.datetime.now() - _t0).total_seconds()
    _log.info(
        "warm_top_picks: scan done in %.1fs — buys=%d sells=%d",
        _elapsed,
        len(result.get("buys", [])),
        len(result.get("sells", [])),
    )

    snapshot = {
        "data": result,
        "generated_at": datetime.datetime.now().isoformat(),
        "scan_seconds": round(_elapsed, 1),
    }
    ok = store.kv_set(_TOP_PICKS_KV_KEY, snapshot, user_id=_TOP_PICKS_KV_USER)
    if ok:
        _log.info("warm_top_picks: persisted snapshot to trade_store (backend=%s)",
                  store.backend_name())
    else:
        _log.error("warm_top_picks: kv_set FAILED — snapshot not persisted this run "
                   "(app will fall back to a live scan)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
