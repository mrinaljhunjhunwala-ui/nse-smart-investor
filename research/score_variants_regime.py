"""
research/score_variants_regime.py — comparative evaluation of regime-
conditional score-reweighting variants against the production composite,
through the same 5-year walk-forward framework as research/regime_study.py,
research/score_variants.py and research/score_variants_volume.py.

WHY THIS EXISTS: REGIME_STUDY_REPORT.md (86,589 obs, 2026-07-15) found the
composite score's ranking power flips sign by market regime — positive in
bull (+0.061, beating naive momentum there), inverted in bear (-0.062 at
fwd20, -0.104 at fwd60), near-flat in sideways (+0.014). Its Q4 component
breakdown showed WHY: momentum is the component that swings hardest by
regime (bull +0.068 best performer, bear -0.095 worst performer), while
technical is comparatively regime-stable (bull +0.059, bear -0.030,
sideways +0.019). The report's own "What this licenses" section #4 is
explicit that this evidence does NOT license shipping a regime-conditional
scorer yet: "nothing here licenses building or shipping a bear-regime
mean-reversion variant... would need its own dedicated variant study first,
matching this codebase's established discipline." This script is that
study.

PRODUCTION SCORING IS NOT MODIFIED. Variants are derived from each walk-
forward observation's already-computed CompositeScore sub-scores (tech/mom/
vol/sent — same convention as score_variants_volume.py) PLUS that
observation's market regime label (bull/bear/sideways, from
regime_study._market_regime_series — same regime rule used to produce
REGIME_STUDY_REPORT.md, so results are directly comparable to it):

  BASE   : production 90-pt composite (sentiment neutralised, same
           convention as the other variant scripts) = tech + mom + vol + sent,
           UNCHANGED across all regimes — what production does today.
  Var G  : "Gate" — in bear regime only, momentum's contribution is zeroed
           and NOT reinvested (bear obs score on a 65-pt scale: tech+vol+
           sent). Bull/sideways obs are identical to BASE. Tests the
           simplest possible regime-conditional change: stop trusting the
           one component the evidence says is actively wrong in bear,
           don't try to be clever about what replaces it.
  Var W  : "Reweight" — in bear regime only, momentum's 25 vacated points
           are reinvested into technical (scaled 40->65, i.e. *1.625),
           since technical is the only price-derived component with a
           comparatively small (not inverted) regime-bear correlation.
           Bull/sideways unchanged. 90-pt scale throughout, unlike Var G.
           Tests "replace the bad signal with the least-bad one" rather
           than just removing it.
  Var M  : "Mean-reversion" — EXPLORATORY, most speculative of the three.
           In bear regime only, momentum_score is replaced (not blended)
           by a reversal score: the stock's trailing-5-day return's
           percentile rank within its own trailing 252-day distribution of
           5-day returns, inverted (low recent 5d return -> high reversal
           score) and scaled to momentum's 0-25 point range. This directly
           tests REGIME_STUDY_REPORT.md's Q5 finding of a real bear-regime
           reversal edge (+0.106 Spearman, vs momentum's own -0.020 there)
           — but per the report's explicit caveat, a positive result here
           is grounds for FURTHER study, not for shipping a mean-reversion
           feature outright. Self-normalised per-ticker (no cross-sectional
           lookahead). Bull/sideways obs are identical to BASE.

Spearman/decile comparisons are rank-based, so Var G's differing point
scale (65 vs 90 for bear obs) does not bias the comparison.

Run:
    py -m research.score_variants_regime            # full universe (~4 min)
    py -m research.score_variants_regime --limit 20 # pipeline check

Outputs:
    research/output/variant_regime_observations.csv
    research/output/variant_regime_summary.csv       (correlations + monotonicity, pooled)
    research/output/variant_regime_by_regime.csv      (bull/bear/sideways breakdown per variant)
    research/output/variant_regime_deciles_<V>.csv    (decile monotonicity per variant)
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

# Production weight split among the three price-derived components (see
# analysis/score.py's _score_technical / _score_momentum / _score_volume).
_TECH_MAX = 40.0
_MOM_MAX  = 25.0
_VOL_MAX  = 15.0
_BEAR_REINVEST_SCALE = (_TECH_MAX + _MOM_MAX) / _TECH_MAX   # 65/40, Var W only

# Var M: trailing window for the self-normalised reversal percentile.
# 252 trading days ~ 1 year, consistent with this repo's other 1y-lookback
# conventions (e.g. 52-week high/low elsewhere in the codebase).
_REVERSAL_LOOKBACK = 252

VARIANTS = ["base", "var_g", "var_w", "var_m"]
VARIANT_LABELS = {
    "base":  "BASE (production 90-pt, regime-blind)",
    "var_g": "G: gate momentum in bear, not reinvested (65-pt in bear)",
    "var_w": "W: bear momentum reinvested into technical (90-pt)",
    "var_m": "M: bear momentum -> reversal proxy (EXPLORATORY, 90-pt)",
}


# ─────────────────────────────────────────────────────────────────────────────
# Walk-forward — production score, then derive regime variants from its
# already-computed sub-scores + that observation's own market regime label
# ─────────────────────────────────────────────────────────────────────────────

def _reversal_percentile(closes: np.ndarray, i: int) -> float:
    """Trailing-5d-return percentile rank vs. this ticker's own trailing
    252-day distribution of 5d returns, as of index i (no lookahead:
    uses only closes[.. i]). Inverted so a LOW recent 5d return (bear-y,
    "oversold" style) maps to a HIGH reversal score, then scaled 0-25 to
    match momentum's point range. Returns np.nan if insufficient history."""
    lo = i - _REVERSAL_LOOKBACK - 5
    if lo < 0:
        return np.nan
    window = closes[lo: i + 1]
    if len(window) < 60:
        return np.nan
    rets5 = window[5:] / window[:-5] - 1.0
    cur = rets5[-1]
    if not np.isfinite(cur) or not np.all(np.isfinite(rets5)):
        rets5 = rets5[np.isfinite(rets5)]
        if len(rets5) < 30:
            return np.nan
    pct = float((rets5 < cur).mean())      # 0 = most negative 5d return seen
    return (1.0 - pct) * 25.0               # invert: most negative -> 25


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
    start = max(start, 65, _REVERSAL_LOOKBACK + 5)
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

        date = df.index[i]
        regime = _regime_for(date, mkt_regimes)
        is_bear = (regime == "bear")

        if is_bear:
            var_g = tech + vol + sent                              # momentum dropped, not reinvested
            var_w = tech * _BEAR_REINVEST_SCALE + vol + sent        # momentum reinvested into tech
            rev = _reversal_percentile(closes, i)
            var_m = (tech + rev + vol + sent) if np.isfinite(rev) else np.nan
        else:
            var_g = base
            var_w = base
            var_m = base

        fwd20 = (closes[i + 20] / entry - 1.0) * 100.0
        fwd60 = (closes[i + 60] / entry - 1.0) * 100.0
        seg_c, seg_s = closes[i + 1: i + 21], sma20[i + 1: i + 21]
        ok = np.isfinite(seg_s)
        persist = float(np.mean(seg_c[ok] > seg_s[ok]) * 100) if ok.sum() >= 15 else np.nan

        rows.append({
            "ticker": ticker,
            "date":   str(date)[:10],
            "vix_regime": _regime_for(date, vix_regimes),
            "mkt_regime": regime,
            "momentum_score": round(mom, 2),
            "base":  base,
            "var_g": var_g,
            "var_w": var_w,
            "var_m": var_m,
            "fwd_20d": fwd20,
            "fwd_60d": fwd60,
            "trend_persist_20": persist,
        })
    return rows, score_failures


# ─────────────────────────────────────────────────────────────────────────────
# Aggregations (identical shape to score_variants_volume.py, for easy
# side-by-side comparison of both variant studies' summary tables)
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
        sub = obs.dropna(subset=[v])
        dec = _decile_fwd20(sub, v)
        rows.append({
            "variant": VARIANT_LABELS[v],
            "n_scored": len(sub),
            "sp_trend_persist": round(_spearman(sub[v], sub["trend_persist_20"]), 4),
            "sp_fwd20":         round(_spearman(sub[v], sub["fwd_20d"]), 4),
            "sp_fwd60":         round(_spearman(sub[v], sub["fwd_60d"]), 4),
            "decile_monotonicity_fwd20": _monotonicity(dec, "fwd20"),
            "d10_minus_d1_fwd20": round(float(dec.loc[10, "fwd20"]) - float(dec.loc[1, "fwd20"]), 2),
            "d10_minus_d1_fwd60": round(float(dec.loc[10, "fwd60"]) - float(dec.loc[1, "fwd60"]), 2),
        })
    res["summary"] = pd.DataFrame(rows).set_index("variant")

    # THE key table for this study: fwd20 Spearman by market regime, per
    # variant — this is where a regime-conditional change should show its
    # improvement (bear row) without degrading the bull/sideways rows,
    # which are constructed to equal BASE for var_g/var_w and should closely
    # track it for var_m too (bull/sideways obs are literally `base` there).
    reg_rows = []
    for reg, g in obs.groupby("mkt_regime"):
        if len(g) < 500:
            continue
        row = {"regime": reg, "n": len(g)}
        for v in VARIANTS:
            sub = g.dropna(subset=[v])
            row[v] = round(_spearman(sub[v], sub["fwd_20d"]), 4) if len(sub) >= 200 else np.nan
        reg_rows.append(row)
    res["by_regime"] = pd.DataFrame(reg_rows).set_index("regime")

    for v in VARIANTS:
        res[f"deciles_{v}"] = _decile_fwd20(obs.dropna(subset=[v]), v)

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
    print(f"REGIME VARIANT STUDY | universe={len(universe)} | period={PERIOD}")

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

    obs.to_csv(os.path.join(OUT_DIR, "variant_regime_observations.csv"),
               index=False, encoding="utf-8")
    n_bear = int((obs["mkt_regime"] == "bear").sum())
    n_m_nan = int(obs["var_m"].isna().sum())
    print(f"Observations: {len(obs)} from {obs['ticker'].nunique()} tickers | "
          f"{obs['date'].min()} -> {obs['date'].max()}")
    print(f"Bear-regime observations: {n_bear} ({n_bear/len(obs)*100:.1f}%)")
    print(f"var_m unavailable (insufficient reversal-lookback history): {n_m_nan} obs")

    aggs = aggregate(obs)
    aggs["summary"].to_csv(os.path.join(OUT_DIR, "variant_regime_summary.csv"), encoding="utf-8")
    aggs["by_regime"].to_csv(os.path.join(OUT_DIR, "variant_regime_by_regime.csv"), encoding="utf-8")
    for v in VARIANTS:
        aggs[f"deciles_{v}"].to_csv(
            os.path.join(OUT_DIR, f"variant_regime_deciles_{v}.csv"), encoding="utf-8")

    pd.set_option("display.width", 200)
    print("\n=== REGIME VARIANT SUMMARY (pooled, all regimes) ===");  print(aggs["summary"])
    print("\n=== FWD-20 SPEARMAN BY MARKET REGIME (the key table) ===\n"
          "    (bear row is where var_g/var_w/var_m should improve on base;\n"
          "     bull/sideways rows should barely move from base)");  print(aggs["by_regime"])
    print(f"\nDone in {time.time()-t0:.0f}s. CSVs in {OUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
