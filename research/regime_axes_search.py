"""
research/regime_axes_search.py — try three alternative regime axes.

The composite (trend+breadth+VIX) classifier in analysis/regime.py added only
a modest edge on the 2023-25 holdout (see regime_validation.py). This script
tests three alternative axes on the SAME 5y observations, so we can pick the
one that actually separates profitable from unprofitable BUY signals:

  A. CROSS-SECTIONAL DISPERSION
     Per-date variance of RECENT-20d-momentum across the whole universe.
     High dispersion = real winners and losers → good time to pick.
     Low dispersion = everything moves together → risk-off / passive index.

  B. DAYS-SINCE-NIFTY-52WK-HIGH
     A rolling "recent ATH" clock. Small = healthy trend. Large = ranging
     or in drawdown. Well-established equity regime marker.

  C. 20-DAY VIX CHANGE (dvix)
     Regime SHIFTS often matter more than regime LEVELS. Rising VIX =
     regime shift in progress → treat signals carefully. Falling VIX =
     regime settling → signals more reliable.

For each axis: bucket every observation into 5 equal-count bins on the axis
value, then report BUY hit rate + avg net return per bucket, HOLDOUT ONLY.
The winning axis is the one whose top vs bottom bucket has the largest
spread in pct_pos_net on holdout — that's the practical filter power.

Reads observations.csv (produced by score_efficacy) and does one Nifty +
VIX fetch. No re-scoring.
"""
from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from research.score_efficacy import COST_ROUNDTRIP_PCT

OUT_DIR = os.path.join(_ROOT, "research", "output")
OBS_PATH = os.path.join(OUT_DIR, "observations.csv")


def _fetch_series(sym: str, period: str = "5y") -> pd.Series:
    from data.fetcher import fetch_single
    df = fetch_single(sym, period=period)
    if df is None or df.empty:
        return pd.Series(dtype=float)
    s = df["Close"].astype(float).dropna()
    if getattr(s.index, "tz", None) is not None:
        s.index = s.index.tz_localize(None)
    return s


def _split(obs: pd.DataFrame) -> pd.DataFrame:
    ds = pd.to_datetime(obs["date"]).sort_values().unique()
    split_date = ds[len(ds) // 2]
    obs = obs.copy()
    obs["split"] = np.where(pd.to_datetime(obs["date"]) < split_date, "train", "holdout")
    return obs


def _bucketise(obs: pd.DataFrame, axis: str, n_buckets: int = 5) -> pd.DataFrame:
    """Add a `bucket` column (1..n) based on quantile of `axis`."""
    obs = obs.copy()
    obs["bucket"] = pd.qcut(obs[axis], q=n_buckets, labels=False, duplicates="drop") + 1
    return obs


def _report_axis(obs_buy: pd.DataFrame, axis: str, description: str) -> pd.DataFrame:
    """Bucket table + top-vs-bottom spread on holdout, for a single axis."""
    print(f"\n═══════════════════════════════════════════════════════════════════")
    print(f"  AXIS: {axis}  —  {description}")
    print(f"═══════════════════════════════════════════════════════════════════")

    o = _bucketise(obs_buy, axis, n_buckets=5)

    # Full sample table
    def _stats(g):
        return pd.Series({
            "n":            len(g),
            "axis_min":     round(g[axis].min(), 3),
            "axis_max":     round(g[axis].max(), 3),
            "pct_pos_net":  round((g["fwd_20d_net"] > 0).mean() * 100, 1),
            "tp_hit_net":   round((g["outcome_net"] == "tp_first").mean() * 100, 1),
            "avg_ret_net":  round(g["fwd_20d_net"].mean(), 2),
        })

    for split_name in ("train", "holdout"):
        sub = o[o["split"] == split_name]
        print(f"\n  --- {split_name} half ({len(sub)} BUY samples) ---")
        tbl = sub.groupby("bucket", observed=True).apply(_stats, include_groups=False)
        if len(tbl) >= 2:
            spread_pct = float(tbl["pct_pos_net"].iloc[-1] - tbl["pct_pos_net"].iloc[0])
            spread_ret = float(tbl["avg_ret_net"].iloc[-1] - tbl["avg_ret_net"].iloc[0])
        else:
            spread_pct = spread_ret = float("nan")
        print(tbl.to_string())
        print(f"  → TOP − BOTTOM bucket:  pct_pos_net {spread_pct:+.1f} pp,  "
              f"avg_ret_net {spread_ret:+.2f} pp")

    return o


def main() -> int:
    if not os.path.exists(OBS_PATH):
        print(f"ERROR: {OBS_PATH} not found — run score_efficacy first."); return 1

    obs = pd.read_csv(OBS_PATH)
    obs = _split(obs)
    print(f"Loaded {len(obs)} observations, {obs['ticker'].nunique()} tickers")

    # Fetch Nifty + VIX (5y, one call each)
    print("Fetching Nifty + VIX (5y)…")
    nifty = _fetch_series("^NSEI",     "5y")
    vix   = _fetch_series("^INDIAVIX", "5y")
    print(f"Nifty: {len(nifty)} bars, VIX: {len(vix)} bars")

    dates = pd.to_datetime(obs["date"])

    # ── Axis B: days since Nifty 52wk high ────────────────────────────────
    rolling_max = nifty.rolling(252, min_periods=50).max()
    days_since_high = pd.Series(index=nifty.index, dtype=float)
    last_high_idx = 0
    for i, (idx, price) in enumerate(nifty.items()):
        rmax = rolling_max.iloc[i]
        if pd.notna(rmax) and price >= rmax * 0.999:   # within 0.1% of 252-bar high
            last_high_idx = i
        days_since_high.iloc[i] = i - last_high_idx
    obs["days_since_52wk_high"] = dates.map(days_since_high).astype(float)

    # ── Axis C: 20d VIX change (dvix) ─────────────────────────────────────
    vix_ma = vix.rolling(20, min_periods=5).mean()
    dvix = (vix_ma / vix_ma.shift(20) - 1.0) * 100.0
    obs["dvix_20d_pct"] = dates.map(dvix).astype(float)

    # ── Axis A: cross-sectional dispersion of 20d momentum ────────────────
    # bl_mom20 already lives in observations.csv (per-obs 20-day momentum),
    # so we can compute per-date std across all tickers directly.
    disp = obs.groupby("date")["bl_mom20"].std()
    obs["xs_dispersion_20d"] = obs["date"].map(disp).astype(float)

    # Focus on BUY / STRONG BUY signals for the axis test
    buy = obs[obs["action"].isin(["STRONG BUY", "BUY"])].dropna(
        subset=["fwd_20d_net", "outcome_net", "days_since_52wk_high",
                "dvix_20d_pct", "xs_dispersion_20d"])
    print(f"\nBUY/STRONG BUY samples with all axes available: {len(buy)}")
    pd.set_option("display.width", 220)
    pd.set_option("display.max_rows", 40)

    _report_axis(buy, "days_since_52wk_high",
                 "Small = trend intact / near ATH; large = ranging or drawdown")
    _report_axis(buy, "dvix_20d_pct",
                 "20d VIX moving-avg change (%). Rising = regime shift; falling = settling")
    _report_axis(buy, "xs_dispersion_20d",
                 "Std of 20-day momentum across the universe. High = winners+losers exist; "
                 "low = correlated moves / risk-off")

    # Combined save
    buy[["date", "ticker", "action", "regime", "fwd_20d_net", "outcome_net",
         "days_since_52wk_high", "dvix_20d_pct", "xs_dispersion_20d", "split"]] \
        .to_csv(os.path.join(OUT_DIR, "regime_axes_buy.csv"), index=False,
                encoding="utf-8")
    print(f"\nDone. Per-signal axis values saved to "
          f"{os.path.join(OUT_DIR, 'regime_axes_buy.csv')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
