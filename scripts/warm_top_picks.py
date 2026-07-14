"""
scripts/warm_top_picks.py — Scheduled Top Picks pre-warm job.

FIX SPEED1. Runs on a schedule (GitHub Actions, every 15 min during NSE
market hours — see .github/workflows/warm-top-picks.yml) and writes a fresh
Top Picks scan result to trade_store (shared Postgres, set via DATABASE_URL).

Why this exists: dashboard/shared/cache.py's _home_top_picks() scans the
full liquid NSE universe (~500 tickers) and takes ~2 minutes cold. It's
cached with @st.cache_data(ttl=300), but that cache is process-local to the
running Streamlit Cloud container — it doesn't survive a redeploy/restart,
and on a low-traffic app it routinely expires between visits. Whoever's
browser session happens to hit the expired cache pays the full 2-minute
scan. That made every "cold" Command Centre visit feel broken.

This script runs the same scan (or a cheaper walk-forward-safe copy of it,
see NOTE below) headlessly and writes the result to trade_store, which
GitHub Actions and the deployed app both have real network access to. The
app's cache.get_top_picks() reads this snapshot first and only falls back to
its own live scan if the snapshot is missing or older than 20 minutes — see
dashboard/shared/cache.py.

NOTE: this deliberately imports dashboard.shared.cache and calls
_home_top_picks() directly rather than re-implementing the scan/selection
logic here, so there is exactly one place that logic lives and this can
never drift from what the app itself would compute. That does mean
`streamlit` must be installed in this job (unlike alerts/check_alerts.py,
which is intentionally dependency-light) — see the workflow file.

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

_KV_KEY  = "top_picks_snapshot"
_KV_USER = "_system"


def main() -> int:
    try:
        from dashboard.shared.cache import _home_top_picks, get_vix_info, _sector_ranks_tuple
        import trade_store as store
    except Exception as e:
        _log.error("warm_top_picks: import failed, aborting this run: %s", e)
        return 0

    try:
        vix_info = get_vix_info()
        vix_regime = vix_info.get("regime", "normal")
    except Exception as e:
        _log.warning("warm_top_picks: get_vix_info() failed, defaulting to 'normal': %s", e)
        vix_regime = "normal"

    try:
        sector_tuple = _sector_ranks_tuple()
    except Exception as e:
        _log.warning("warm_top_picks: _sector_ranks_tuple() failed, defaulting to (): %s", e)
        sector_tuple = ()

    _log.info("warm_top_picks: starting scan (vix_regime=%s, sectors=%d)...",
              vix_regime, len(sector_tuple))
    _t0 = datetime.datetime.now()
    try:
        result = _home_top_picks(vix_regime=vix_regime, n=10, sector_ranks=sector_tuple)
    except Exception as e:
        _log.error("warm_top_picks: scan failed, nothing persisted this run: %s", e)
        return 0
    _elapsed = (datetime.datetime.now() - _t0).total_seconds()
    _log.info("warm_top_picks: scan done in %.1fs — %d buys, %d sells",
              _elapsed, len(result.get("buys", [])), len(result.get("sells", [])))

    snapshot = {
        "data": result,
        "generated_at": datetime.datetime.now().isoformat(),
        "scan_seconds": round(_elapsed, 1),
    }
    ok = store.kv_set(_KV_KEY, snapshot, user_id=_KV_USER)
    if ok:
        _log.info("warm_top_picks: persisted snapshot to trade_store (backend=%s)",
                  store.backend_name())
    else:
        _log.error("warm_top_picks: kv_set FAILED — snapshot not persisted this run "
                   "(app will fall back to a live scan)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
