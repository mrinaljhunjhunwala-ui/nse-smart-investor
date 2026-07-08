#!/usr/bin/env python
"""tools/refresh_flags_batch.py — QF-remedy-1: decoupled qualitative-flag fetch.

WHY THIS EXISTS
    If the deployed app (Streamlit Cloud / Render / any cloud host) can't
    pull qualitative flags because NSE's WAF blocks that server's IP (see
    data/nse_corp_info.py's "KNOWN OPERATIONAL LIMITATION" docstring), the
    fix isn't a code change — it's running the FETCH from somewhere that
    isn't a flagged datacenter IP (a home connection, a residential VPS,
    a laptop), and writing the result into the SAME shared kv store
    (Neon Postgres, via DATABASE_URL) the deployed app already reads from.

    The deployed app never talks to NSE directly for this — it only calls
    analysis.qualitative_flags.load_flags(), which just reads kv_get(). So
    once this script has populated the store, flags show up in the app
    immediately, with zero risk of the app itself getting blocked.

USAGE
    Run this from a machine NOT hosted on cloud infrastructure (your laptop
    on home broadband is fine), with the SAME DATABASE_URL the deployed app
    uses (set it in your environment or .streamlit/secrets.toml equivalent),
    then just:

        python tools/refresh_flags_batch.py                    # shortlist only (default)
        python tools/refresh_flags_batch.py --tickers ABDL.NS RELIANCE.NS
        python tools/refresh_flags_batch.py --universe nifty100 --limit 40

    Schedule it (cron / Task Scheduler) to run once daily before market
    open, e.g.:
        0 8 * * 1-5  cd /path/to/repo && python tools/refresh_flags_batch.py

WHAT IT DOES NOT DO
    It does not touch analysis/score.py, CompositeScore, or any ranking.
    It only refreshes analysis/qualitative_flags.py entries via the real
    NSE fetch (data/nse_corp_info.py) and writes them through the same
    trade_store.kv_set the rest of the app uses — so this is safe to run
    against production data.

SCOPE — do not point this at the full universe casually. NSE's WAF is
    sensitive to request VOLUME too, not just IP reputation — a home
    connection making 500 rapid requests can still get itself flagged.
    Default is a small, sane shortlist; --universe/--limit are there for
    deliberate, occasional bigger runs, not a daily habit.
"""
from __future__ import annotations

import argparse
import os
import sys
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

# Default shortlist — your portfolio + watchlist, not the wide universe.
# Overridable via --tickers / --universe.
_DEFAULT_SOURCE = "portfolio_and_watchlist"


def _default_tickers() -> list[str]:
    """Portfolio holdings + saved watchlist — the tickers you actually
    hold or are watching, which is exactly where qualitative context
    matters most. Falls back to an empty list (with a warning) if neither
    is available rather than silently guessing a universe.
    """
    tickers: list[str] = []
    try:
        from dashboard.shared.trade_utils import load_manual_holdings
        holdings = load_manual_holdings()
        tickers.extend(h["ticker"] for h in holdings if h.get("ticker"))
    except Exception as e:
        print(f"  (portfolio holdings unavailable: {e})")
    try:
        import trade_store as _store
        wl = _store.kv_get("watchlist", [])
        tickers.extend(w["ticker"] for w in (wl or []) if isinstance(w, dict) and w.get("ticker"))
    except Exception as e:
        print(f"  (watchlist unavailable: {e})")
    # de-dupe, preserve order
    seen = set()
    out = []
    for t in tickers:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tickers", nargs="*", default=None,
                     help="explicit ticker list, e.g. ABDL.NS RELIANCE.NS")
    ap.add_argument("--universe", default=None,
                     help="use a universe level instead (e.g. nifty50) — "
                          "combine with --limit; NOT recommended for daily use")
    ap.add_argument("--limit", type=int, default=30,
                     help="cap tickers when using --universe (default 30)")
    ap.add_argument("--delay", type=float, default=1.5,
                     help="seconds to sleep between tickers (politeness delay, default 1.5s)")
    args = ap.parse_args()

    import trade_store as _store
    from analysis.qualitative_flags import refresh_all_flags
    from data.nse_corp_info import get_last_diagnostic

    if args.tickers:
        tickers = args.tickers
    elif args.universe:
        from data.universe import get_universe
        tickers = list(get_universe(args.universe))[: args.limit]
    else:
        tickers = _default_tickers()
        if not tickers:
            print("No portfolio holdings or watchlist tickers found, and no "
                  "--tickers/--universe given. Nothing to do.")
            return 1

    print(f"Refreshing qualitative flags for {len(tickers)} ticker(s): {tickers}")
    ok, blocked, other_fail = 0, 0, 0
    t0 = time.time()
    for i, ticker in enumerate(tickers, 1):
        try:
            flags = refresh_all_flags(ticker, _store.kv_get, _store.kv_set)
            diag = get_last_diagnostic(ticker)
            if diag and diag.get("ok"):
                ok += 1
                print(f"  [{i}/{len(tickers)}] {ticker}: OK "
                      f"({len(flags)} active flags)")
            elif diag and diag.get("status_code") in (401, 403):
                blocked += 1
                print(f"  [{i}/{len(tickers)}] {ticker}: BLOCKED — {diag.get('reason')}")
            elif diag:
                other_fail += 1
                print(f"  [{i}/{len(tickers)}] {ticker}: FAILED — {diag.get('reason')}")
            else:
                print(f"  [{i}/{len(tickers)}] {ticker}: no diagnostic recorded "
                      f"({len(flags)} flags from cache/manual)")
        except Exception as e:
            other_fail += 1
            print(f"  [{i}/{len(tickers)}] {ticker}: EXCEPTION — {type(e).__name__}: {e}")
        if i < len(tickers):
            time.sleep(args.delay)

    elapsed = time.time() - t0
    print(f"\nDone in {elapsed:.0f}s — ok={ok} blocked={blocked} other_fail={other_fail}")
    if blocked > 0 and ok == 0:
        print(
            "\nEvery attempt was blocked (401/403). This confirms the fetch "
            "location itself is the problem, not the code — try running "
            "this script from a different network (home broadband, mobile "
            "hotspot) rather than the same host/VPS."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
