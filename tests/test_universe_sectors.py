"""
Regression guard for data/universe.py's sector mapping.

Context: a research run (score_efficacy.py + regime_study.py, July 2026)
found 243 of 504 nifty500 tickers (48%) had no entry in SECTOR_MAP and
silently fell back to a catch-all "Other" bucket — this both degraded the
score's own sector_rank sub-component for those tickers (ranked against a
huge, heterogeneous "Other" peer group instead of real peers) and hid any
real sector-level pattern in backtests behind a 45%-of-observations "Other"
bucket. Fixed by completing the mapping for all 243. This test exists so
the gap can't silently reopen as the universe grows — any newly-added
ticker without a sector assignment should fail CI, not fail silently.

FIX TEST1 (this revision): the original version of
test_no_ticker_assigned_to_two_sectors below iterated SECTOR_MAP (the
already-flattened ticker→sector dict) rather than _SECTOR_ASSIGNMENTS (the
per-sector source lists SECTOR_MAP is built from). By the time a ticker
reaches SECTOR_MAP, dict construction has already silently collapsed any
duplicate down to a single winner (whichever sector's list was processed
last) — so the old test could never detect a duplicate no matter how many
existed in the source data; it was checking data from which the bug had
already been erased. This actually happened: LXCHEM.NS and HAWKINCOOK.NS
were both listed under two sectors each in a previous revision of
_SECTOR_ASSIGNMENTS, and the old version of this test passed anyway. The
fixed version below checks _SECTOR_ASSIGNMENTS directly.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from data.universe import get_universe, get_sector, SECTOR_MAP, _SECTOR_ASSIGNMENTS


def test_full_nifty500_universe_has_no_unmapped_tickers():
    universe = list(get_universe("nifty500"))
    unmapped = [t for t in universe if t not in SECTOR_MAP]
    assert unmapped == [], (
        f"{len(unmapped)} tickers in the nifty500 universe have no sector "
        f"mapping and will silently fall back to 'Other': {unmapped}. "
        "Add them to _SECTOR_ASSIGNMENTS in data/universe.py."
    )


def test_get_sector_never_returns_other_for_mapped_universe():
    """get_sector() falling back to 'Other' is the exact failure mode this
    test guards against — assert it never happens for the real universe."""
    universe = list(get_universe("nifty500"))
    other_count = sum(1 for t in universe if get_sector(t) == "Other")
    assert other_count == 0, (
        f"{other_count} tickers resolved to the 'Other' fallback sector."
    )


def test_no_ticker_assigned_to_two_sectors():
    """A ticker listed under two sectors in _SECTOR_ASSIGNMENTS would have
    its resolved sector silently determined by dict-construction order
    (last sector processed wins) rather than by an actual data decision —
    catch that at the source, not after SECTOR_MAP has already collapsed it
    away. See FIX TEST1 docstring above: checking SECTOR_MAP itself (the
    post-collapse result) cannot detect this class of bug by construction."""
    seen: dict[str, str] = {}
    dupes = []
    for sector, tickers in _SECTOR_ASSIGNMENTS.items():
        for ticker in tickers:
            if ticker in seen and seen[ticker] != sector:
                dupes.append((ticker, seen[ticker], sector))
            else:
                seen[ticker] = sector
    assert dupes == [], (
        f"Tickers assigned to multiple sectors in _SECTOR_ASSIGNMENTS: {dupes}. "
        "Each ticker should appear in exactly one sector's list."
    )
