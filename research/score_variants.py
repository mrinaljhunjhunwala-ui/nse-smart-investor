"""
research/score_variants.py — comparative evaluation of three research-only
score variants against the production composite, through the same 5-year
walk-forward framework as research/regime_study.py.

PRODUCTION SCORING IS NOT MODIFIED. Variants are derived arithmetically from
the production score at each observation:

  BASE      : production 90-pt price-derived score (sentiment neutralised)
  Variant A : BASE − pattern component            (remove candlesticks)
  Variant B : BASE − oversold-RSI bonus           (remove the contrarian RSI credit)
  Variant C : BASE − pattern − oversold-RSI bonus (remove both)

NOTE (post pattern-removal): candlestick patterns are no longer a scored
component in production at all (PATTERN_REMOVAL_MIGRATION.md) — this
script's own original run is what motivated that removal. BASE therefore
already has zero pattern contribution, which makes Variant A mathematically
identical to BASE, and Variant C identical to Variant B. They're kept in the
variant list for continuity with the historical report in
RESEARCH_SCORE_VARIANTS.md, but only Variant B (oversold-RSI bonus removal)
tests a question that's still actually open.

Definition of "remove the oversold-RSI bonus" (documented design decision):
the production RSI map awards 10 pts for RSI<30 and 8 pts for RSI 30–40 —
contrarian "bounce candidate" credit inside an otherwise trend-following
factor. Variant B re-scores those zones at the same minimal 1.0 pt the map
gives RSI>80, making the RSI factor purely trend-consistent. The RSI map below
mirrors analysis/score._score_technical verbatim (kept in sync by
tests-free research convention: verify against score.py lines ~101-108 when
the production map changes).

Spearman/decile comparisons are rank-based, so the differing point scales of
the variants (90 vs 80 vs 79 vs 69 max) do not bias the comparison.

Run:
    py -m research.score_variants            # full universe (~4 min)
    py -m research.score_variants --limit 20 # pipeline check

Outputs:
    research/output/variant_observations.csv
    research/output/variant_summary.csv        (correlations: persistence + returns)
    research/output/variant_deciles_<V>.csv    (decile monotonicity per variant)
    research/output/variant_by_regime.csv      (bull/bear/sideways + VIX regimes)
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from research.score_efficacy import (          # noqa: E402
    _prepare_ticker, _vix_regime_series, _regime_for, _spearman,
    _NEUTRAL_VIX, _NEUTRAL_SECTOR_RANK,
)
from research.regime_study import _market_regime_series   # noqa: E402

OUT_DIR = os.path.join(_ROOT, "research", "output")

PERIOD      = "5y"
SAMPLE_STEP = 5
MAX_HORIZON = 60

VARIANTS = ["base", "var_a", "var_b", "var_c"]
VARIANT_LABELS = {
    "base":  "BASE (production 90-pt)",
    "var_a": "A: no pattern",
    "var_b": "B: no oversold-RSI bonus",
    "var_c": "C: no pattern + no oversold bonus",
}


def _rsi_pts_production(rsi: float) -> float:
    """Mirror of the production RSI map (analysis/score._score_technical)."""
    if 60 <= rsi <= 70:  return 12.0
    if 50 <= rsi < 60:   return 9.0
    if 70 < rsi <= 80:   return 7.0
    if 40 <= rsi < 50:   return 6.0
    if 30 <= rsi < 40:   return 8.0
    if rsi < 30:         return 10.0
    return 1.0


def _rsi_oversold_delta(rsi: float) -> float:
    """Points the production map awards ABOVE the trend-consistent minimum (1.0)
    in the oversold zones. Zero outside RSI<40."""
    if rsi < 30:
        return 10.0 - 1.0
    if 30 <= rsi < 40:
        return 8.0 - 1.0
    return 0.0


# ─────────────────────────────────────────────────────────────────────────────
# Walk-forward — production score + the inputs needed to derive variants
# ─────────────────────────────────────────────────────────────────────────────

def _walk_forward_variants(ticker: str, df: pd.DataFrame,
                           vix_regimes: Optional[pd.Series],
                           mkt_regimes: Optional[pd.Series]) -> "Tuple[List[Dict], int]":
    from analysis.score import score_dataframe

    closes = df["Close"].astype(float).values
    n      = len(df)
    sma20  = (df["SMA_20"].astype(float).values
              if "SMA_20" in df.columns else np.full(n, np.nan))
    rsis   = (df["RSI"].astype(float).values
              if "RSI" in df.columns else np.full(n, 50.0))

    if "SMA_200" in df.columns:
        valid = df["SMA_200"].notna().values
        start = int(np.argmax(valid)) if valid.any() else n
    else:
        start = 200
    start = max(start, 65)
    last  = n - MAX_HORIZON - 1

    rows: List[Dict] = []
    score_failures = 0
    for i in range(start, last, SAMPLE_STEP):
        sub = df.iloc[: i + 1]
        try:
            cs = score_dataframe(sub, ticker, vix_info=_NEUTRAL_VIX,
                                 sector_rank=_NEUTRAL_SECTOR_RANK, sector="Other")
        except Exception:
            score_failures += 1
            continue
        entry = closes[i]
        if entry <= 0 or not np.isfinite(entry):
            continue

        base   = float(cs.score) - float(cs.sentiment_score)
        # FIX EFF1 (companion fix, same root cause as score_efficacy.py /
        # regime_study.py) — cs.pattern_score no longer exists on
        # CompositeScore. Unlike those two scripts, this one isn't just
        # broken by the removal — its whole original purpose was to test
        # "does removing the pattern component improve the score," and that
        # question was already answered (pattern hurts) and already acted on:
        # PATTERN_REMOVAL_MIGRATION.md confirms it's gone from production for
        # good. So `base` (cs.score minus sentiment) is now ALREADY the
        # "no pattern" score — pattern's point contribution is definitionally
        # 0 in the current model. Reconstructing a nonzero synthetic value
        # here (e.g. from patterns_detected) would misrepresent this as a
        # still-open comparison when it's a settled, already-implemented one.
        pat    = 0.0
        rsi    = float(rsis[i]) if np.isfinite(rsis[i]) else 50.0
        os_del = _rsi_oversold_delta(rsi)

        fwd20 = (closes[i + 20] / entry - 1.0) * 100.0
        fwd60 = (closes[i + 60] / entry - 1.0) * 100.0
        # Trend persistence: share of next 20 days above SMA-20
        seg_c, seg_s = closes[i + 1: i + 21], sma20[i + 1: i + 21]
        ok = np.isfinite(seg_s)
        persist = float(np.mean(seg_c[ok] > seg_s[ok]) * 100) if ok.sum() >= 15 else np.nan

        date = df.index[i]
        rows.append({
            "ticker": ticker,
            "date":   str(date)[:10],
            "vix_regime": _regime_for(date, vix_regimes),
            "mkt_regime": _regime_for(date, mkt_regimes),
            "rsi": round(rsi, 1),
            "base":  base,
            "var_a": base - pat,
            "var_b": base - os_del,
            "var_c": base - pat - os_del,
            "fwd_20d": fwd20,
            "fwd_60d": fwd60,
            "trend_persist_20": persist,
        })
    return rows, score_failures


# ─────────────────────────────────────────────────────────────────────────────
# Aggregations
# ─────────────────────────────────────────────────────────────────────────────

def _decile_fwd20(obs: pd.DataFrame, col: str) -> pd.DataFrame:
    df = obs.dropna(subset=[col]).copy()
    df["decile"] = pd.qcut(df[col].rank(method="first"), 10,
                           labels=list(range(1, 11)))
    return (df.groupby("decile", observed=True)
              .agg(n=("ticker", "size"),
                   fwd20=("fwd_20d", "mean"),
                   fwd60=("fwd_60d", "mean"),
                   persist=("trend_persist_20", "mean"))
              .round(2))


def _monotonicity(dec: pd.DataFrame, col: str = "fwd20") -> float:
    """Spearman of decile index vs decile-mean forward return — 1.0 = perfectly
    monotone increasing."""
    s = dec[col].reset_index(drop=True)
    idx = pd.Series(range(1, len(s) + 1), dtype=float)
    return round(float(idx.rank().corr(s.rank())), 3)


def aggregate(obs: pd.DataFrame) -> Dict[str, pd.DataFrame]:
    res: Dict[str, pd.DataFrame] = {}

    # Headline summary: correlations + monotonicity + decile spread, per variant
    rows = []
    for v in VARIANTS:
        dec = _decile_fwd20(obs, v)
        rows.append({
            "variant": VARIANT_LABELS[v],
            "sp_trend_persist": round(_spearman(obs[v], obs["trend_persist_20"]), 4),
            "sp_fwd20":         round(_spearman(obs[v], obs["fwd_20d"]), 4),
            "sp_fwd60":         round(_spearman(obs[v], obs["fwd_60d"]), 4),
            "decile_monotonicity_fwd20": _monotonicity(dec, "fwd20"),
            "d10_minus_d1_fwd20": round(float(dec.loc[10, "fwd20"]) - float(dec.loc[1, "fwd20"]), 2),
            "d10_minus_d1_fwd60": round(float(dec.loc[10, "fwd60"]) - float(dec.loc[1, "fwd60"]), 2),
        })
    res["summary"] = pd.DataFrame(rows).set_index("variant")

    # Per-regime fwd20 Spearman for each variant (market + VIX regimes)
    reg_rows = []
    for kind, col in [("market", "mkt_regime"), ("vix", "vix_regime")]:
        for reg, g in obs.groupby(col):
            if len(g) < 500:
                continue
            row = {"regime_type": kind, "regime": reg, "n": len(g)}
            for v in VARIANTS:
                row[v] = round(_spearman(g[v], g["fwd_20d"]), 4)
            reg_rows.append(row)
    res["by_regime"] = pd.DataFrame(reg_rows).set_index(["regime_type", "regime"])

    # Decile tables per variant
    for v in VARIANTS:
        res[f"deciles_{v}"] = _decile_fwd20(obs, v)

    return res


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=10)
    args = ap.parse_args()

    from data.universe import get_universe

    universe = list(get_universe("nifty500"))
    if args.limit:
        universe = universe[: args.limit]

    os.makedirs(OUT_DIR, exist_ok=True)
    t0 = time.time()
    print(f"SCORE VARIANT STUDY | universe={len(universe)} | period={PERIOD}")

    vix_regimes = _vix_regime_series(period=PERIOD)
    mkt_regimes = _market_regime_series()

    frames: Dict[str, pd.DataFrame] = {}
    prep_failures = 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(_prepare_ticker, t, PERIOD): t for t in universe}
        done = 0
        for f in as_completed(futs):
            t = futs[f]
            try:
                df = f.result()
                if df is not None:
                    frames[t] = df
            except Exception:
                prep_failures += 1
            done += 1
            if done % 50 == 0:
                print(f"  fetched {done}/{len(universe)} [{time.time()-t0:.0f}s]")
    if prep_failures:
        print(f"  {prep_failures}/{len(universe)} tickers raised an exception during "
              f"prepare/fetch (excluded from frames)")

    print(f"Usable tickers: {len(frames)}/{len(universe)} [{time.time()-t0:.0f}s]")

    all_rows: List[Dict] = []
    total_score_failures = 0
    for k, (t, df) in enumerate(frames.items(), 1):
        rows, score_failures = _walk_forward_variants(t, df, vix_regimes, mkt_regimes)
        all_rows.extend(rows)
        total_score_failures += score_failures
        if k % 50 == 0:
            print(f"  scored {k}/{len(frames)} ({len(all_rows)} obs) [{time.time()-t0:.0f}s]")
    if total_score_failures:
        print(f"  score_dataframe raised an exception {total_score_failures} times "
              f"across all walk-forward samples (those sample points were skipped)")

    obs = pd.DataFrame(all_rows)
    if obs.empty:
        print("No observations — aborting.")
        return 1

    obs.to_csv(os.path.join(OUT_DIR, "variant_observations.csv"),
               index=False, encoding="utf-8")
    print(f"Observations: {len(obs)} from {obs['ticker'].nunique()} tickers | "
          f"{obs['date'].min()} -> {obs['date'].max()}")
    # How often does each removal actually change the score?
    chg_a = float((obs['base'] != obs['var_a']).mean() * 100)
    chg_b = float((obs['base'] != obs['var_b']).mean() * 100)
    print(f"Observations where pattern != 0: {chg_a:.1f}% | oversold bonus active: {chg_b:.1f}%")

    aggs = aggregate(obs)
    aggs["summary"].to_csv(os.path.join(OUT_DIR, "variant_summary.csv"), encoding="utf-8")
    aggs["by_regime"].to_csv(os.path.join(OUT_DIR, "variant_by_regime.csv"), encoding="utf-8")
    for v in VARIANTS:
        aggs[f"deciles_{v}"].to_csv(os.path.join(OUT_DIR, f"variant_deciles_{v}.csv"),
                                    encoding="utf-8")

    pd.set_option("display.width", 200)
    print("\n=== VARIANT SUMMARY ===");  print(aggs["summary"])
    print("\n=== FWD-20 SPEARMAN BY REGIME ==="); print(aggs["by_regime"])
    print(f"\nDone in {time.time()-t0:.0f}s. CSVs in {OUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
