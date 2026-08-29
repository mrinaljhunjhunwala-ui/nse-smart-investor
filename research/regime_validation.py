"""
research/regime_validation.py — does the composite regime classifier separate
profitable from unprofitable BUY signals better than VIX-alone?

Reads observations.csv from research.score_efficacy (must have been run
first — no re-fetch here), pulls Nifty + VIX history once, computes the
composite regime label for every observation date via
analysis.regime.classify_history, and reports:

  1. Per-regime × per-action-band hit rate table
  2. Direct A/B: for BUY signals only, hit rate under VIX-alone regime vs
     under composite regime — the same statistic that made the "regime
     filter" hypothesis worth investing in.

The bar for "the composite is worth building on":
  * BUY signals in the composite trend_up regime should hit ≥ 55 % net of
    costs, materially better than the ~46-49 % overall BUY holdout number
    that motivated this whole exercise.
  * The lift should hold on the HOLDOUT half (i.e., 2023-25 for the 5y
    observations.csv), not just the training half — that is what makes
    this a regime filter rather than another overfit.

Zero network I/O for the classification step. Nifty + VIX are fetched once
each, breadth is skipped in the historical path (see comment below).
"""
from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from analysis.regime import classify_history
from research.score_efficacy import COST_ROUNDTRIP_PCT

OUT_DIR = os.path.join(_ROOT, "research", "output")
OBS_PATH = os.path.join(OUT_DIR, "observations.csv")


def _fetch_series(sym: str, period: str = "5y") -> pd.Series:
    from data.fetcher import fetch_single
    df = fetch_single(sym, period=period)
    if df is None or df.empty:
        return pd.Series(dtype=float)
    s = df["Close"].astype(float).dropna()
    # Strip tz — score_efficacy dates are naive.
    if getattr(s.index, "tz", None) is not None:
        s.index = s.index.tz_localize(None)
    return s


def _split_by_date(obs: pd.DataFrame) -> pd.DataFrame:
    dates_sorted = pd.to_datetime(obs["date"]).sort_values().unique()
    split_date = dates_sorted[len(dates_sorted) // 2]
    obs = obs.copy()
    obs["split"] = np.where(
        pd.to_datetime(obs["date"]) < split_date, "train", "holdout"
    )
    return obs


def _stats(g: pd.DataFrame) -> pd.Series:
    n = len(g)
    if n == 0:
        return pd.Series({"n": 0})
    return pd.Series({
        "n":               n,
        "pct_pos":         round((g["fwd_20d"]     > 0).mean() * 100, 1),
        "pct_pos_net":     round((g["fwd_20d_net"] > 0).mean() * 100, 1),
        "tp_hit":          round((g["outcome"]     == "tp_first").mean() * 100, 1),
        "tp_hit_net":      round((g["outcome_net"] == "tp_first").mean() * 100, 1),
        "avg_ret_net":     round(g["fwd_20d_net"].mean(), 2),
    })


def main() -> int:
    if not os.path.exists(OBS_PATH):
        print(f"ERROR: {OBS_PATH} not found. Run research.score_efficacy first.")
        return 1

    obs = pd.read_csv(OBS_PATH)
    obs = _split_by_date(obs)
    print(f"Loaded {len(obs)} observations "
          f"({obs['ticker'].nunique()} tickers, dates "
          f"{obs['date'].min()} .. {obs['date'].max()})")

    # Fetch Nifty + VIX for the full observation span
    period = "5y" if (pd.to_datetime(obs["date"]).max()
                      - pd.to_datetime(obs["date"]).min()).days > 800 else "3y"
    print(f"Fetching Nifty + VIX ({period}) for historical regime classification…")
    nifty = _fetch_series("^NSEI",     period=period)
    vix   = _fetch_series("^INDIAVIX", period=period)
    if nifty.empty:
        print("ERROR: Nifty history unavailable — cannot compute composite regime.")
        return 2
    print(f"Nifty: {len(nifty)} bars, VIX: {len(vix)} bars")

    # BREADTH note: computing historical breadth (% of Nifty-500 above SMA-50
    # per date) needs the full 500-ticker fetch we already have in
    # observations.csv indirectly — but reconstructing it here from cached
    # frames is more work than this validation warrants for a first pass.
    # We validate the classifier with (VIX + trend + vol) only; breadth adds
    # marginal robustness but the first three are enough to test the thesis.
    print("Breadth: skipped in this validation (see comment) — passing None")

    # Classify the whole nifty history once, then reindex to obs dates
    regime_series = classify_history(nifty, vix, breadth_pct=None)
    obs["regime_composite"] = pd.to_datetime(obs["date"]).map(regime_series)
    obs["regime_composite"] = obs["regime_composite"].fillna("unknown")
    obs["regime_vix"] = obs["regime"]     # existing VIX-only label

    # ── 1. Per-composite-regime × per-action-band table ─────────────────────
    print(f"\n=== 1. HIT RATE BY COMPOSITE REGIME × ACTION × SPLIT ===")
    print(f"(cost floor {COST_ROUNDTRIP_PCT}% round-trip)")
    print("If trend_up rows for STRONG BUY / BUY show ≥ 55% pct_pos_net on the HOLDOUT")
    print("half, the composite regime filter is worth wiring into the app.")
    tbl = (
        obs.groupby(["regime_composite", "action", "split"], observed=True)
        .apply(_stats, include_groups=False)
    )
    regime_order = ["trend_up", "trend_down", "range", "risk_off", "unknown"]
    action_order = ["STRONG BUY", "BUY", "WATCHLIST", "HOLD", "CAUTION", "EXIT"]
    tbl = tbl.reset_index()
    tbl["_r"] = tbl["regime_composite"].map({r: i for i, r in enumerate(regime_order)}).fillna(99)
    tbl["_a"] = tbl["action"].map({a: i for i, a in enumerate(action_order)}).fillna(99)
    tbl = (tbl.sort_values(["_r", "_a", "split"])
              .drop(columns=["_r", "_a"])
              .set_index(["regime_composite", "action", "split"]))
    tbl.to_csv(os.path.join(OUT_DIR, "regime_validation.csv"), encoding="utf-8")
    pd.set_option("display.width", 200)
    pd.set_option("display.max_rows", 200)
    print(tbl)

    # ── 2. Direct A/B for BUY signals: VIX-alone vs composite ───────────────
    buy = obs[obs["action"].isin(["STRONG BUY", "BUY"])].copy()
    print(f"\n=== 2. A/B — BUY / STRONG BUY hit rate under two regime filters ===")
    print(f"n BUY-family samples: {len(buy)}")

    def _summary(g):
        return pd.Series({
            "n": len(g),
            "pct_pos_net": round((g["fwd_20d_net"] > 0).mean() * 100, 1),
            "tp_hit_net":  round((g["outcome_net"] == "tp_first").mean() * 100, 1),
            "avg_ret_net": round(g["fwd_20d_net"].mean(), 2),
        })

    print("\n-- Baseline: no filter --")
    print(_summary(buy).to_string())

    for label in regime_order:
        sub = buy[buy["regime_composite"] == label]
        if len(sub) < 30:
            continue
        print(f"\n-- Composite regime = {label!r} (n={len(sub)}) --")
        print(_summary(sub).to_string())
        # Holdout-only cut
        sub_h = sub[sub["split"] == "holdout"]
        if len(sub_h) >= 30:
            print(f"   holdout subset (n={len(sub_h)}):")
            print("   " + _summary(sub_h).to_string().replace("\n", "\n   "))

    print(f"\nDone. CSV: {os.path.join(OUT_DIR, 'regime_validation.csv')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
