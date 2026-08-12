"""analysis/price_bands.py — helpers for price banding and within-band normalization.

Simple, deterministic quantile banding over a list of prices and an in-place
normaliser that writes a score_norm key to each result dict so selection can
be made fair across low/medium/high-priced names without extra network IO.
"""
from __future__ import annotations

from typing import Iterable, List, Optional, Sequence
import math


def compute_quantile_thresholds(prices: Sequence[float], n_bands: int = 4) -> List[float]:
    """
    Compute upper thresholds for n_bands using simple quantiles.
    Returns list of length (n_bands - 1) of ascending thresholds.
    Example: n_bands=4 returns [q25, q50, q75]
    """
    vals = [float(p) for p in prices if p is not None and not math.isnan(p) and p > 0]
    if not vals:
        return []
    vals_sorted = sorted(vals)
    n = len(vals_sorted)
    thresholds: List[float] = []
    for i in range(1, n_bands):
        # target rank (1-based) in the sorted array
        pos = i * (n / n_bands)
        # convert to 0-based indices for interpolation
        lo = max(0, min(int(math.floor(pos)) - 1, n - 1))
        hi = max(0, min(int(math.ceil(pos)) - 1, n - 1))
        if lo == hi:
            q = vals_sorted[lo]
        else:
            # fractional interpolation between lo and hi
            frac = pos - (lo + 1)
            q = vals_sorted[lo] * (1 - frac) + vals_sorted[hi] * frac
        thresholds.append(float(q))
    return thresholds


def assign_band(price: Optional[float], thresholds: List[float]) -> int:
    """
    Assigns price to a band index [0..len(thresholds)].
    If price is None/invalid, returns -1 to indicate unknown.
    """
    try:
        p = float(price)
        if p <= 0 or math.isnan(p):
            return -1
    except Exception:
        return -1
    for i, t in enumerate(thresholds):
        if p <= t:
            return i
    return len(thresholds)


def normalize_within_bands(results: Iterable[dict], band_key: str = "band", score_key: str = "score") -> None:
    """
    In-place add a 'score_norm' key to each result dict representing its
    0..1 normalised rank within its band. Unknown band (-1) gets score_norm=0.
    Ties handled by stable ranking (higher raw score -> higher normalized).
    """
    from collections import defaultdict

    groups = defaultdict(list)
    for r in (results or []):
        b = r.get(band_key, -1)
        groups[b].append(r)

    for b, items in groups.items():
        if b == -1 or not items:
            for it in items:
                it["score_norm"] = 0.0
            continue
        # sort descending by raw score (higher is better)
        items_sorted = sorted(items, key=lambda x: (x.get(score_key) or 0), reverse=True)
        L = len(items_sorted)
        if L == 1:
            items_sorted[0]["score_norm"] = 1.0
            continue
        for idx, it in enumerate(items_sorted):
            # normalized rank: 1.0 (best) down to ~0.0
            it["score_norm"] = 1.0 - (idx / (L - 1))
