"""Live check of the Upstox market-data source. Never prints the token.

    set UPSTOX_ANALYTICS_TOKEN=...      (PowerShell: $env:UPSTOX_ANALYTICS_TOKEN="...")
    py tools/upstox_check.py

Fetches 3 quotes (RELIANCE, TCS, Nifty 50) and 5 days of RELIANCE daily candles.
Exit code 0 = both worked, 1 = something failed, 2 = no token configured.
"""
from __future__ import annotations

import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main() -> int:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    from data import upstox_fetcher as up

    if not up.is_configured():
        print("Upstox: not configured (set UPSTOX_ANALYTICS_TOKEN). Nothing fetched.")
        return 2
    ok = True
    syms = ["RELIANCE.NS", "TCS.NS", "^NSEI"]
    print("Instrument keys:", {s: up.instrument_key(s) for s in syms})
    quotes = up.get_batch_quotes(syms)
    for s in syms:
        q = quotes.get(s)
        if q:
            print(f"  {s:12s} {q['price']:>10.2f}  prev {q['prev_close']:>10.2f}  "
                  f"{q['chg_pct']:+.2f}%  vol {q.get('volume', '-')}  at {q.get('as_of', '-')}")
        else:
            ok = False
            print(f"  {s:12s} no quote")
    df = up.fetch_historical("RELIANCE.NS", period="5d", interval="1d")
    if df is None or df.empty:
        ok = False
        print("RELIANCE candles: none")
    else:
        print("RELIANCE last 5 daily candles:")
        print(df.tail(5).to_string())
    st = up.status()
    print("Status:", {k: v for k, v in st.items() if k != "configured"})
    print("RESULT:", "OK" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
