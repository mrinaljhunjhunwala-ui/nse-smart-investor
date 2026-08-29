"""
research/accuracy_deepdive.py — regime-conditional + threshold-recalibration.

Reads the observations.csv produced by research.score_efficacy and answers the
two follow-up questions the honest-accuracy report opened:

  1. REGIME-CONDITIONAL ACCURACY: is the BUY signal actually right in some
     regimes (elevated/fear) and wrong in others (complacency/normal)?  If yes,
     we have a live edge conditional on filtering by regime — not a rewrite.

  2. THRESHOLD RECALIBRATION: where on the score axis do TP/SL outcomes and
     forward-return signs ACTUALLY flip?  The current thresholds
     (BUY ≥ 65, STRONG BUY ≥ 80) look miscalibrated in the honest report;
     this walks the score axis and reports the score bucket where net-of-cost
     hit rate ACTUALLY crosses 50%.

Zero network I/O — reads the CSV the main study already produced.  Run:
    py -m research.accuracy_deepdive
"""
from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

OUT_DIR = os.path.join(_ROOT, "research", "output")
OBS_PATH = os.path.join(OUT_DIR, "observations.csv")

# Same cost model as research.score_efficacy — keep the two in sync
from research.score_efficacy import COST_ROUNDTRIP_PCT


def _train_holdout_split(obs: pd.DataFrame) -> pd.DataFrame:
    dates_sorted = pd.to_datetime(obs["date"]).sort_values().unique()
    split_date = dates_sorted[len(dates_sorted) // 2]
    obs = obs.copy()
    obs["split"] = np.where(
        pd.to_datetime(obs["date"]) < split_date, "train", "holdout"
    )
    return obs


# ─────────────────────────────────────────────────────────────────────────────
# 1. Regime-conditional accuracy
# ─────────────────────────────────────────────────────────────────────────────

def regime_conditional(obs: pd.DataFrame) -> pd.DataFrame:
    """
    Per-regime × per-action-band accuracy table.

    If regime is the decisive factor, we should see BUY hit rates in fear/
    elevated regimes materially exceed BUY hit rates in complacency/normal.
    That would say: the model's signal is real, but the FILTER (VIX regime)
    is what turns it live vs dead — a big result.
    """
    obs = _train_holdout_split(obs)

    def stats(g: pd.DataFrame) -> pd.Series:
        n = len(g)
        if n == 0:
            return pd.Series({"n": 0})
        return pd.Series({
            "n":                 n,
            "pct_fwd20_pos":     round((g["fwd_20d"]     > 0).mean() * 100, 1),
            "pct_fwd20_pos_net": round((g["fwd_20d_net"] > 0).mean() * 100, 1),
            "tp_hit_rate":       round((g["outcome"]     == "tp_first").mean() * 100, 1),
            "tp_hit_rate_net":   round((g["outcome_net"] == "tp_first").mean() * 100, 1),
            "avg_fwd20_gross":   round(g["fwd_20d"].mean(),     2),
            "avg_fwd20_net":     round(g["fwd_20d_net"].mean(), 2),
        })

    tbl = (
        obs.groupby(["regime", "action", "split"], observed=True)
        .apply(stats, include_groups=False)
        .reset_index()
    )
    # Sort by regime severity, then action band severity, then split
    regime_order = ["complacency", "normal", "elevated", "fear", "panic", "unknown"]
    action_order = ["STRONG BUY", "BUY", "WATCHLIST", "HOLD", "CAUTION", "EXIT"]
    tbl["_r"] = tbl["regime"].map({r: i for i, r in enumerate(regime_order)}).fillna(99)
    tbl["_a"] = tbl["action"].map({a: i for i, a in enumerate(action_order)}).fillna(99)
    tbl = tbl.sort_values(["_r", "_a", "split"]).drop(columns=["_r", "_a"])
    return tbl.set_index(["regime", "action", "split"])


# ─────────────────────────────────────────────────────────────────────────────
# 2. Threshold recalibration
# ─────────────────────────────────────────────────────────────────────────────

def threshold_recalibration(obs: pd.DataFrame, buckets: int = 20) -> pd.DataFrame:
    """
    Walk the score axis in `buckets` equal-count bins.  For each bin report:
      - score range
      - n
      - pct fwd_20d > 0 (gross AND net)
      - pct TP-first (gross AND net)
      - avg fwd_20d gross AND net

    This lets us see where along the score axis the model actually FLIPS from
    money-losing to money-making — the honest replacement for the arbitrary
    thresholds hard-coded in analysis/score._action().
    """
    obs = obs.copy()
    obs["bucket"] = pd.qcut(obs["score"], q=buckets, duplicates="drop")

    def stats(g: pd.DataFrame) -> pd.Series:
        n = len(g)
        return pd.Series({
            "n":                 n,
            "score_min":         round(g["score"].min(), 1),
            "score_max":         round(g["score"].max(), 1),
            "pct_fwd20_pos":     round((g["fwd_20d"]     > 0).mean() * 100, 1),
            "pct_fwd20_pos_net": round((g["fwd_20d_net"] > 0).mean() * 100, 1),
            "tp_hit_rate":       round((g["outcome"]     == "tp_first").mean() * 100, 1),
            "tp_hit_rate_net":   round((g["outcome_net"] == "tp_first").mean() * 100, 1),
            "avg_fwd20_gross":   round(g["fwd_20d"].mean(),     2),
            "avg_fwd20_net":     round(g["fwd_20d_net"].mean(), 2),
        })

    return (
        obs.groupby("bucket", observed=True)
        .apply(stats, include_groups=False)
        .reset_index(drop=True)
        .assign(bucket=lambda d: range(1, len(d) + 1))
        .set_index("bucket")
    )


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main() -> int:
    if not os.path.exists(OBS_PATH):
        print(f"ERROR: {OBS_PATH} not found. Run research.score_efficacy first.")
        return 1

    obs = pd.read_csv(OBS_PATH)
    print(f"Loaded {len(obs)} observations from {obs['ticker'].nunique()} tickers")
    print(f"Cost floor: {COST_ROUNDTRIP_PCT:.2f}% round-trip")

    print("\n=== 1. REGIME-CONDITIONAL ACCURACY (regime × action × split) ===")
    print("If fear/elevated BUY hit rates >> complacency/normal, the signal is")
    print("real but needs a regime filter to be live.")
    reg = regime_conditional(obs)
    reg.to_csv(os.path.join(OUT_DIR, "accuracy_by_regime.csv"), encoding="utf-8")
    pd.set_option("display.width", 200)
    pd.set_option("display.max_rows", 100)
    print(reg)

    print("\n=== 2. THRESHOLD RECALIBRATION (20 equal-count score buckets) ===")
    print("Where along the score axis does hit-rate ACTUALLY cross 50% net?")
    thr = threshold_recalibration(obs, buckets=20)
    thr.to_csv(os.path.join(OUT_DIR, "threshold_recalibration.csv"), encoding="utf-8")
    print(thr)

    # Highlight the answer to the recalibration question
    print("\n=== THRESHOLD RECOMMENDATION ===")
    win_net = thr[thr["pct_fwd20_pos_net"] >= 50.0]
    if not win_net.empty:
        cutoff_row = win_net.iloc[0]
        print(
            f"First bucket whose NET fwd_20d hit rate ≥ 50%: score ≥ "
            f"{cutoff_row['score_min']:.1f}  (bucket {win_net.index[0]}, n={int(cutoff_row['n'])})"
        )
    else:
        print("No score bucket beats 50% NET fwd_20d hit rate on this sample.")
    win_tp = thr[thr["tp_hit_rate_net"] >= 50.0]
    if not win_tp.empty:
        cutoff_row = win_tp.iloc[0]
        print(
            f"First bucket whose NET TP-hit rate ≥ 50%: score ≥ "
            f"{cutoff_row['score_min']:.1f}  (bucket {win_tp.index[0]}, n={int(cutoff_row['n'])})"
        )
    else:
        print("No score bucket beats 50% NET TP-hit rate on this sample.")

    print(f"\nDone. CSVs saved to {OUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
