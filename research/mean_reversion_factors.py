"""
research/mean_reversion_factors.py — do mean-reversion factors help?

Sprint A: The composite score is 100 % trend-following (see the 5y honest
report — 62 % hit rate on train 2020-22 trending, 46 % on holdout 2023-25
ranging). This walk-forward tests THREE mean-reversion candidate factors on
the same universe/window and asks: does any of them separate winning from
losing BUY opportunities BETTER than the composite score alone on holdout?

Factors tested (each at every sample bar per ticker):
  F1 BB_%B extreme + inside band     — "rubber band snapped" revert setup
  F2 |close − SMA20| / ATR > 2.5     — distance-from-mean revert candidate
  F3 5+ consecutive up-day counter   — consecutive-move exhaustion candidate
      (with low ADX < 20 = ranging regime filter)

For each factor, per (train / holdout) split:
  * fires_at_pct_pos_net   how often the factor's TRIGGER wins net of costs
  * fires_at_tp_hit_net    TP-before-SL net of costs
  * baseline_pct_pos_net   overall BUY hit rate (same window/regime split)
  * lift_pp                fires-when-triggered minus baseline (percentage-pt)

If ANY factor's holdout lift is ≥ +5 pp with n ≥ 200, it's a keeper — real
enough to wire into a mean-reversion composite parallel to the trend composite.

Reads observations.csv for date/ticker/split/outcome; re-fetches OHLCV per
ticker via data.fetcher (heavily cached — a full-universe pass is ~2-3 min
on a warm cache, ~10 min cold).
"""
from __future__ import annotations

import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
import pandas as pd

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from research.score_efficacy import COST_ROUNDTRIP_PCT

OUT_DIR  = os.path.join(_ROOT, "research", "output")
OBS_PATH = os.path.join(OUT_DIR, "observations.csv")


def _prep_frame(ticker: str) -> "pd.DataFrame | None":
    """Fetch OHLCV and enrich with the indicators the factors need."""
    try:
        from data.fetcher import fetch_single
        from utils.indicators import (add_bollinger_bands, add_moving_averages,
                                      add_atr, add_adx)
        df = fetch_single(ticker, period="5y")
        if df is None or df.empty or len(df) < 220:
            return None
        df = add_moving_averages(df)
        df = add_atr(df)
        df = add_adx(df)
        df = add_bollinger_bands(df)
        # tz strip so lookups match observations.csv naive dates
        if getattr(df.index, "tz", None) is not None:
            df.index = df.index.tz_localize(None)
        return df
    except Exception:
        return None


def _factor_values(df: pd.DataFrame) -> pd.DataFrame:
    """Compute the three candidate factors on the enriched frame."""
    out = pd.DataFrame(index=df.index)

    # F1: BB extreme (close within 1% of upper OR lower band) with %B < 0.1 or > 0.9
    bbu, bbl = df["BB_Upper"], df["BB_Lower"]
    band_width = (bbu - bbl).replace(0, np.nan)
    pct_b = (df["Close"] - bbl) / band_width
    near_upper = (df["Close"] >= bbu * 0.99) & (pct_b > 0.9)
    near_lower = (df["Close"] <= bbl * 1.01) & (pct_b < 0.1)
    out["F1_bb_extreme"] = (near_upper | near_lower).astype(int)

    # F2: distance from SMA20 in ATR units > 2.5
    atr = df["ATR"].replace(0, np.nan)
    dist_atr = (df["Close"] - df["SMA_20"]).abs() / atr
    out["F2_far_from_mean"] = (dist_atr > 2.5).astype(int)

    # F3: 5+ consecutive same-direction closes AND ADX < 20 (ranging regime)
    diff_sign = np.sign(df["Close"].diff()).fillna(0)
    # Run-length: reset when sign changes, otherwise increment
    run = pd.Series(0, index=df.index, dtype=int)
    for i in range(1, len(df)):
        if diff_sign.iloc[i] != 0 and diff_sign.iloc[i] == diff_sign.iloc[i - 1]:
            run.iloc[i] = run.iloc[i - 1] + 1
        else:
            run.iloc[i] = 0
    adx = df["ADX"].fillna(50)   # missing ADX → treat as trending, factor won't fire
    out["F3_run_exhausted"] = ((run >= 5) & (adx < 20)).astype(int)
    return out


def _worker(item):
    ticker, sub = item
    df = _prep_frame(ticker)
    if df is None:
        return None
    fac = _factor_values(df)
    # Reindex to the observation dates for this ticker
    sub = sub.copy()
    sub_dates = pd.to_datetime(sub["date"])
    for col in ("F1_bb_extreme", "F2_far_from_mean", "F3_run_exhausted"):
        sub[col] = sub_dates.map(fac[col]).astype("Int64")
    return sub


def _stats(g: pd.DataFrame) -> pd.Series:
    n = len(g)
    if n == 0:
        return pd.Series({"n": 0, "pct_pos_net": 0.0, "tp_hit_net": 0.0,
                          "avg_ret_net": 0.0})
    return pd.Series({
        "n":            n,
        "pct_pos_net":  round((g["fwd_20d_net"] > 0).mean() * 100, 1),
        "tp_hit_net":   round((g["outcome_net"] == "tp_first").mean() * 100, 1),
        "avg_ret_net":  round(g["fwd_20d_net"].mean(), 2),
    })


def main() -> int:
    if not os.path.exists(OBS_PATH):
        print(f"ERROR: {OBS_PATH} missing — run research.score_efficacy first."); return 1

    obs = pd.read_csv(OBS_PATH)
    print(f"Loaded {len(obs)} observations, {obs['ticker'].nunique()} tickers")

    # Train/holdout split by date
    ds = pd.to_datetime(obs["date"]).sort_values().unique()
    split_date = ds[len(ds) // 2]
    obs["split"] = np.where(pd.to_datetime(obs["date"]) < split_date, "train", "holdout")

    # Focus on BUY / STRONG BUY signals — that's what a user actually acts on
    buy = obs[obs["action"].isin(["BUY", "STRONG BUY"])].copy()
    print(f"BUY / STRONG BUY samples: {len(buy)}")

    t0 = time.time()
    groups = list(buy.groupby("ticker"))
    print(f"Fetching + enriching {len(groups)} tickers…")

    enriched: list = []
    with ThreadPoolExecutor(max_workers=10) as ex:
        futs = {ex.submit(_worker, g): g[0] for g in groups}
        done = 0
        for f in as_completed(futs):
            r = f.result()
            if r is not None:
                enriched.append(r)
            done += 1
            if done % 50 == 0:
                print(f"  {done}/{len(groups)} [{time.time()-t0:.0f}s]")

    buy_e = pd.concat(enriched, ignore_index=True) if enriched else buy.iloc[:0]
    print(f"Enriched samples: {len(buy_e)} [{time.time()-t0:.0f}s]")

    # Baseline hit rate per split
    print(f"\n=== BASELINE (all BUY / STRONG BUY, split) ===")
    baseline = buy_e.groupby("split", observed=True).apply(_stats, include_groups=False)
    print(baseline)

    # Per-factor: rows where factor == 1
    print(f"\n=== PER-FACTOR TRIGGER STATS (cost floor {COST_ROUNDTRIP_PCT}%) ===")
    print("Rows shown are the samples where the factor FIRED (== 1). Compare to baseline above.")
    for f_col in ("F1_bb_extreme", "F2_far_from_mean", "F3_run_exhausted"):
        print(f"\n-- {f_col} --")
        fires = buy_e[buy_e[f_col] == 1]
        tbl = fires.groupby("split", observed=True).apply(_stats, include_groups=False)
        print(tbl)
        # Lift vs baseline per split
        for split in ("train", "holdout"):
            if split in tbl.index and split in baseline.index:
                lift_pct = tbl.loc[split, "pct_pos_net"] - baseline.loc[split, "pct_pos_net"]
                lift_ret = tbl.loc[split, "avg_ret_net"] - baseline.loc[split, "avg_ret_net"]
                print(f"  {split}: lift {lift_pct:+.1f} pp pct_pos_net, "
                      f"{lift_ret:+.2f} pp avg_ret_net  (n={int(tbl.loc[split, 'n'])})")

    # Combined: any factor firing at all
    buy_e["any_factor"] = ((buy_e["F1_bb_extreme"] == 1) |
                          (buy_e["F2_far_from_mean"] == 1) |
                          (buy_e["F3_run_exhausted"] == 1)).astype(int)
    print(f"\n=== COMBINED (any of F1/F2/F3 firing) ===")
    tbl_any = buy_e[buy_e["any_factor"] == 1].groupby("split", observed=True).apply(
        _stats, include_groups=False)
    print(tbl_any)

    buy_e.to_csv(os.path.join(OUT_DIR, "mean_reversion_factors.csv"), index=False,
                 encoding="utf-8")
    print(f"\nDone [{time.time()-t0:.0f}s]. Data: {os.path.join(OUT_DIR, 'mean_reversion_factors.csv')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
