"""scripts/build_movers_evidence.py — rebuild the "similar past moves" table for the movers radar.

For every name in the scan universe: each up-day of 3%+ in its stored daily history, bucketed by
market-cap tier, move size and volume vs the prior 20 sessions, with the stock's return 5 sessions
later minus the Nifty's (analysis.movers.build_chase_table). The table goes to KV
``movers_evidence`` (user "_system"); the intraday radar quotes the closest bucket.

History comes from the nightly price store when it holds the symbol, else data.fetcher (Yahoo).
Read-only apart from that one KV write. Run weekly (movers-evidence.yml) or on demand:
    py scripts/build_movers_evidence.py            # build and store
    py scripts/build_movers_evidence.py --dry-run  # build and print, store nothing
"""
from __future__ import annotations

import argparse
import datetime as _dt
import os
import sys
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

PERIOD = "5y"
_IST = _dt.timezone(_dt.timedelta(hours=5, minutes=30))


def _history(sym: str):
    try:
        from data import price_store
        df = price_store.load_daily_bars(sym)
        if df is not None and len(df) > 250:
            return df
    except Exception:                                       # noqa: BLE001
        pass
    try:
        from data.fetcher import fetch_single
        return fetch_single(sym, period=PERIOD)
    except Exception:                                       # noqa: BLE001
        return None


def build(limit: int = 0) -> dict:
    from analysis.movers import band_map, build_chase_table, cap_band
    from data.fetcher import fetch_index
    from data.universe import _CONSTITUENTS, get_universe

    nifty = fetch_index("^NSEI", period=PERIOD)
    if nifty is None or nifty.empty:
        raise SystemExit("Nifty history unavailable — nothing built")
    bands = band_map(_CONSTITUENTS)
    syms = get_universe("all")
    if limit:
        syms = syms[:limit]
    history, t0 = {}, time.time()
    for i, s in enumerate(syms, 1):
        df = _history(s)
        if df is not None and len(df) > 60:
            history[s] = df
        if i % 100 == 0:
            print(f"  {i}/{len(syms)} symbols read ({time.time() - t0:.0f}s)")
    table = build_chase_table(history, nifty["Close"], lambda s: cap_band(s, bands))
    return {"table": table, "symbols": len(history),
            "built_at": _dt.datetime.now(_IST).isoformat(timespec="seconds"),
            "horizon": 5, "nifty_from": str(nifty.index[0])[:10], "nifty_to": str(nifty.index[-1])[:10]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=0, help="first N symbols only (testing)")
    args = ap.parse_args()
    out = build(args.limit)
    from analysis.movers import BANDS, MOVE_BUCKETS
    print(f"movers evidence: {out['symbols']} symbols, {out['nifty_from']} -> {out['nifty_to']}")
    for band in BANDS:
        for m, (lo, hi) in enumerate(MOVE_BUCKETS):
            s = out["table"].get(f"{band}|{m}|any")
            if s:
                rng = f"+{lo:g}% and up" if hi == float("inf") else f"+{lo:g}–{hi:g}%"
                print(f"  {band:6s} {rng:>12s}: n={s['n']:5d}  median {s['median_excess']:+.2f} pts vs Nifty "
                      f"5 sessions later, {s['beat_pct']:.0f}% beat it")
    if args.dry_run:
        return 0
    import trade_store as store
    ok = store.kv_set("movers_evidence", out, user_id="_system")
    print("stored to KV movers_evidence" if ok is not False else "KV write failed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
