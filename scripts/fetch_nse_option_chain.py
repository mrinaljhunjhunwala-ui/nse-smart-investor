"""
scripts/fetch_nse_option_chain.py — NSE options chain (PCR + max pain).

Feeds the last two positioning sub-scores inside Recommendation 6's
Positioning pillar. See docs/POSITIONING_INTEGRATION_2026-09.md.

MUST RUN FROM A RESIDENTIAL IP - the NSE options-chain API is
aggressively rate-limited from cloud IPs. Same constraint as the other
NSE-archives scrapers.

USAGE
    # Fetch a specific list
    py -m scripts.fetch_nse_option_chain --tickers RELIANCE INFY TCS

    # Fetch every F&O-eligible ticker in the starter universe (~60 names)
    py -m scripts.fetch_nse_option_chain --fno-all

    # Slower pause between calls (default 2s) - use 3-4s if you see 429s
    py -m scripts.fetch_nse_option_chain --fno-all --pause 3.5

Per-symbol call, so runtime scales with N. --fno-all at pause 2s is
~2 minutes for the starter universe.

EXIT CODES
    0  ran (individual symbol failures are logged, not fatal)
    1  no symbols supplied
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from typing import List

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from data.nse_option_chain import fetch_and_persist   # noqa: E402
from data.fno_universe    import list_fno_tickers     # noqa: E402

_log = logging.getLogger("scripts.fetch_nse_option_chain")


def _parse_args(argv: List[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Fetch NSE options-chain PCR + max pain per symbol."
    )
    p.add_argument("--tickers", nargs="+", default=None,
                   help="Explicit symbol list (no .NS suffix needed)")
    p.add_argument("--fno-all", action="store_true",
                   help="Every F&O-eligible ticker from data.fno_universe")
    p.add_argument("--pause", type=float, default=2.0,
                   help="Seconds between per-symbol calls (default 2.0)")
    p.add_argument("--verbose", "-v", action="store_true")
    return p.parse_args(argv)


def main(argv: List[str] | None = None) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])
    logging.basicConfig(
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        level=logging.DEBUG if args.verbose else logging.INFO,
    )
    if args.tickers:
        symbols = [t.upper().replace(".NS", "") for t in args.tickers]
    elif args.fno_all:
        symbols = sorted(list_fno_tickers())
    else:
        _log.error("supply --tickers SYM1 SYM2 ... or --fno-all")
        return 1

    _log.info("fetching option chain for %d symbol(s), pause=%.1fs",
              len(symbols), args.pause)
    written = fetch_and_persist(symbols, pause_seconds=args.pause)
    _log.info("done. rows persisted: %d", written)
    return 0


if __name__ == "__main__":
    sys.exit(main())
