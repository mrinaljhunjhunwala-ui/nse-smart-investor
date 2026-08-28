"""
research/score_variants_volume.py — comparative evaluation of two research-
only score variants against the production composite, through the same
5-year walk-forward framework as research/regime_study.py and
research/score_variants.py.

WHY THIS EXISTS: the July 2026 score_efficacy.py / regime_study.py runs
(docs/SCORE_EFFICACY_REPORT.md / docs/REGIME_STUDY_REPORT.md, post FIX EFF1) found the
volume component (15 of 90 pts) showing near-zero-to-negative Spearman
correlation with forward returns in EVERY regime breakdown in BOTH studies:

  component_by_regime.csv (5yr): bear +0.0043, bull +0.0113, sideways -0.0056
  factor_attribution.csv (1yr):  fwd5 -0.0007, fwd20 -0.0238, fwd60 -0.0332

That's the same shape of evidence (near-zero-to-negative across every
regime) that motivated the pattern component's removal
(docs/RESEARCH_SCORE_VARIANTS.md, docs/PATTERN_REMOVAL_MIGRATION.md) — but a
correlation number alone isn't sufficient grounds to change production
weights, per this codebase's own established discipline: test a variant
first, look at decile monotonicity + regime breakdown, THEN decide.
This script is that test, for volume specifically.

PRODUCTION SCORING IS NOT MODIFIED. Variants are derived arithmetically from
already-computed CompositeScore sub-scores at each walk-forward observation
(volume_score is a stored field — no reconstruction needed, unlike the
pattern/oversold-RSI variants in score_variants.py which had to rebuild
those sub-scores from raw inputs):

  BASE      : production 90-pt composite (sentiment neutralised, same
              convention as score_variants.py) = technical + momentum
              + volume + sentiment
  Variant D : BASE − volume                    (75-pt scale: drop volume
              entirely, don't reinvest its points anywhere)
  Variant E : technical and momentum scaled up to fill volume's vacated
              15 points, proportionally to their existing weights
              (40:25), sentiment unchanged — same 90-pt scale as BASE, so
              this tests "reinvest in what the regime study says has real
              signal" rather than just "remove and shrink"

Spearman/decile comparisons are rank-based, so the differing point scales
across variants (90 vs 75 vs 90) do not bias the comparison.

Run:
    py -m research.score_variants_volume            # full universe (~4 min)
    py -m research.score_variants_volume --limit 20 # pipeline check

Outputs:
    research/output/variant_volume_observations.csv
    research/output/variant_volume_summary.csv      (correlations + monotonicity)
    research/output/variant_volume_by_regime.csv     (bull/bear/sideways + VIX regimes)
    research/output/variant_volume_deciles_<V>.csv   (decile monotonicity per variant)
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Optional

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

# Production weight split among the three price-derived components
# (sentiment is neutralised/held constant, same convention as
# score_variants.py's "base" — see analysis/score.py's _score_technical /
# _score_momentum / _score_volume for the 40/25/15 max-point split).
_TECH_MAX = 40.0
_MOM_MAX  = 25.0
_VOL_MAX  = 15.0
_REDISTRIBUTE_SCALE = (_TECH_MAX + _MOM_MAX + _VOL_MAX) / (_TECH_MAX + _MOM_MAX)  # 80/65

VARIANTS = ["base", "var_d", "var_e"]
VARIANT_LABELS = {
    "base":  "BASE (production 90-pt)",
    "var_d": "D: no volume, not reinvested (75-pt)",
    "var_e": "E: no volume, reinvested into tech+momentum (90-pt)",
}


# ─────────────────────────────────────────────────────────────────────────────
# Walk-forward — production score, then derive volume variants from its
# already-computed sub-scores (no raw recomputation needed)
# ─────────────────────────────────────────────────────────────────────────────

def _walk_forward_variants(ticker: str, df: pd.DataFrame,
                           vix_regimes: Optional[pd.Series],
                           mkt_regimes: Optional[pd.Series]) -> "tuple[List[Dict], int]":
    from analysis.score import score_dataframe

    closes = df["Close"].astype(float).values
    n      = len(df)
    sma20  = (df["SMA_20"].astype(float).values
              if "SMA_20" in df.columns else np.full(n, np.nan))

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

        tech  = float(cs.technical_score)
        mom   = float(cs.momentum_score)
        vol   = float(cs.volume_score)
        sent  = float(cs.sentiment_score)
        base  = tech + mom + vol + sent

        var_d = tech + mom + sent
        var_e = (tech + mom) * _REDISTRIBUTE_SCALE + sent

        fwd20 = (closes[i + 20] / entry - 1.0) * 100.0
        fwd60 = (closes[i + 60] / entry - 1.0) * 100.0
        seg_c, seg_s = closes[i + 1: i + 21], sma20[i + 1: i + 21]
        ok = np.isfinite(seg_s)
        persist = float(np.mean(seg_c[ok] > seg_s[ok]) * 100) if ok.sum() >= 15 else np.nan

        date = df.index[i]
        rows.append({
            "ticker": ticker,
            "date":   str(date)[:10],
            "vix_regime": _regime_for(date, vix_regimes),
            "mkt_regime": _regime_for(date, mkt_regimes),
            "volume_score": round(vol, 2),
            "base":  base,
            "var_d": var_d,
            "var_e": var_e,
            "fwd_20d": fwd20,
            "fwd_60d": fwd60,
            "trend_persist_20": persist,
        })
    return rows, score_failures


# ─────────────────────────────────────────────────────────────────────────────
# Aggregations (identical shape to score_variants.py, for easy side-by-side
# comparison of both variant studies' summary tables)
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
    s = dec[col].reset_index(drop=True)
    idx = pd.Series(range(1, len(s) + 1), dtype=float)
    return round(float(idx.rank().corr(s.rank())), 3)


def aggregate(obs: pd.DataFrame) -> Dict[str, pd.DataFrame]:
    res: Dict[str, pd.DataFrame] = {}

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
    print(f"VOLUME VARIANT STUDY | universe={len(universe)} | period={PERIOD}")

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

    obs.to_csv(os.path.join(OUT_DIR, "variant_volume_observations.csv"),
               index=False, encoding="utf-8")
    print(f"Observations: {len(obs)} from {obs['ticker'].nunique()} tickers | "
          f"{obs['date'].min()} -> {obs['date'].max()}")
    print(f"Mean volume_score across all observations: {obs['volume_score'].mean():.2f} / 15.0")

    aggs = aggregate(obs)
    aggs["summary"].to_csv(os.path.join(OUT_DIR, "variant_volume_summary.csv"), encoding="utf-8")
    aggs["by_regime"].to_csv(os.path.join(OUT_DIR, "variant_volume_by_regime.csv"), encoding="utf-8")
    for v in VARIANTS:
        aggs[f"deciles_{v}"].to_csv(
            os.path.join(OUT_DIR, f"variant_volume_deciles_{v}.csv"), encoding="utf-8")

    pd.set_option("display.width", 200)
    print("\n=== VOLUME VARIANT SUMMARY ===");  print(aggs["summary"])
    print("\n=== FWD-20 SPEARMAN BY REGIME ==="); print(aggs["by_regime"])
    print(f"\nDone in {time.time()-t0:.0f}s. CSVs in {OUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
