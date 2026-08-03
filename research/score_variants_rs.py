"""
research/score_variants_rs.py — confirmatory follow-up to
research/score_variants_untapped.py, testing ONLY the relative-strength
(RS_Score vs Nifty) variant that looked promising there, with a tighter
methodology built to survive scrutiny rather than just look good once.

WHY A SEPARATE SCRIPT INSTEAD OF JUST RE-RUNNING score_variants_untapped.py:

The exploratory pass answered "is anything here worth a second look" and RS
was the only clear yes. This script exists to answer the harder question —
"would it still look good if I stopped being generous with the methodology"
— by fixing four specific gaps the exploratory pass had:

 1. CALENDAR-ALIGNED, NEAR-NON-OVERLAPPING SAMPLING.
    score_variants_untapped.py samples every 5th row of EACH TICKER'S OWN
    index. Two problems: (a) different tickers land on different calendar
    dates, so "cross-sectional, same-day" comparisons (which is what
    Top Picks / Tomorrow's Watchlist actually do) only had ~10-20 tickers
    on a typical date out of a 480-name universe — thin and unrepresentative.
    (b) a 5-trading-day step against a 20-trading-day forward window means
    consecutive samples share 75% of their forward-return period — they are
    not independent draws, so a pooled Spearman's apparent precision
    (86,828 "observations") is substantially overstated.
    Fix: sample from ONE shared calendar grid (built off the ^NSEI trading
    calendar) spaced STEP=20 trading days apart — matching the fwd_20d
    horizon exactly, so those windows do not overlap at all — and every
    ticker is scored on the SAME dates (a ticker only drops out of a date
    if it genuinely lacks history there, e.g. a later listing).

 2. TRAIN/HOLDOUT SPLIT.
    The exploratory pass tested 6 variants on the full 5-year window and
    RS happened to win — a classic multiple-comparisons setup where the
    "winner" can just be the variant that got lucky on this particular
    history. This script reserves the most recent ~12 months
    (HOLDOUT_DAYS trading days) as a holdout that plays no role in the RS
    design (the bonus formula is unchanged from the exploratory pass — see
    _bonus_rs) and reports TRAIN and HOLDOUT metrics separately. Caveat,
    stated plainly: the exploratory pass already looked at the full window
    before RS was chosen for this follow-up, so this holdout is not a
    perfectly clean pre-registration — it is a "going forward, this slice
    doesn't get touched again" discipline marker, and the honest read is
    "does the edge survive being looked at a second, harder way" rather
    than "was this proven from a blank slate."

 3. CLUSTER-BOOTSTRAP CONFIDENCE INTERVALS.
    A single Spearman number invites over-reading small differences as
    signal. Resampling TICKERS (not rows) with replacement respects the
    fact that a ticker's own observations are correlated with each other —
    this is the standard fix for panel data, and it directly answers "is
    the gap between BASE and RS bigger than what noise alone would produce."

 4. TURNOVER AS A REPORTED NUMBER, NOT AN AD-HOC CHECK.
    Day-over-day top-decile membership overlap, now computed properly on
    the full shared-calendar universe (previously eyeballed on a thin
    same-day slice) — this is the real answer to "how much would my
    Top Picks list actually change."

STANDING CAVEAT THIS SCRIPT CANNOT FIX (documented, not silently ignored):
data/universe.py's get_universe() returns TODAY's Nifty constituent list,
applied retroactively across the past 5 years. Any stock that was dropped
from the index during that period (usually for underperforming) is invisible
to this study and to every sibling research script. This specifically tends
to inflate relative-strength-style findings, because today's survivors are,
almost by construction, stocks that didn't underperform badly enough to be
removed. Treat every number below as "promising, not proven" for that
reason — there is no free-tier fix for point-in-time index membership.

PRODUCTION SCORING IS NOT MODIFIED.

Run:
    py -m research.score_variants_rs                 # full universe (~2-3 min)
    py -m research.score_variants_rs --limit 20       # pipeline check

Outputs (research/output/):
    variant_rs_observations.csv   one row per ticker x sampled calendar date
    variant_rs_summary.csv        pooled + cross-sectional + bootstrap CI, by split
    variant_rs_by_regime.csv      spearman by split x market/VIX regime
    variant_rs_turnover.csv       day-over-day top-decile overlap, by split
    variant_rs_caveats.txt        the survivorship-bias note above, in one place
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
from scipy.stats import spearmanr

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from research.score_efficacy import (          # noqa: E402
    _prepare_ticker, _vix_regime_series, _regime_for, _NEUTRAL_VIX, _NEUTRAL_SECTOR_RANK,
)
from research.regime_study import _market_regime_series   # noqa: E402

OUT_DIR = os.path.join(_ROOT, "research", "output")

PERIOD        = "5y"
STEP_DAYS     = 20      # calendar-day spacing == fwd_20d horizon -> non-overlapping fwd20 windows
MAX_HORIZON   = 60
WARMUP_DAYS   = 330      # >= RS's 252-bar window + 63-bar momentum lookback + buffer
HOLDOUT_DAYS  = 252      # ~1 trading year reserved, untouched by the RS design
BENCH_TICKER  = "^NSEI"
RS_PERIOD     = 63
BONUS_MAX     = 8.0       # unchanged from score_variants_untapped.py — same bonus, harder test

VARIANTS = ["base", "var_rs", "gated_rs"]
VARIANT_LABELS = {
    "base":     "BASE (production 90-pt)",
    "var_rs":   "RS (unconditional, all regimes)",
    "gated_rs": "RS (regime-gated: zeroed in bear)",
}

SURVIVORSHIP_CAVEAT = (
    "SURVIVORSHIP BIAS CAVEAT: data/universe.py's get_universe() returns TODAY's "
    "Nifty constituent list, applied retroactively across the past 5 years. Any "
    "stock dropped from the index in that window (usually for underperforming) is "
    "invisible to this study. This specifically tends to inflate relative-strength "
    "findings, since today's survivors are, almost by construction, names that did "
    "not underperform badly enough to be removed. There is no free-tier fix for "
    "point-in-time index membership. Read every number in this study as "
    "'promising, not proven' for that reason.\n\n"
    "MULTIPLE-COMPARISONS CAVEAT: RS was selected as the one variant worth a "
    "follow-up after score_variants_untapped.py tested six candidates on this same "
    "5-year window. The TRAIN/HOLDOUT split below is a 'going forward, this slice "
    "is not touched again' discipline marker, not a from-a-blank-slate "
    "pre-registration — the exploratory pass had already seen the holdout period "
    "before this script existed."
)


def _bonus_rs(rs_score: float) -> float:
    """Identical to score_variants_untapped.py's _bonus_rs — the point of this
    script is to re-test the SAME formula more rigorously, not to re-tune it."""
    if rs_score is None or not np.isfinite(rs_score):
        return BONUS_MAX / 2.0
    return round(float(np.clip(rs_score, 0.0, 100.0)) / 100.0 * BONUS_MAX, 3)


def _prepare_ticker_rs(ticker: str, period: str,
                       bench_df: Optional[pd.DataFrame]) -> Optional[pd.DataFrame]:
    df = _prepare_ticker(ticker, period)
    if df is None:
        return None
    if bench_df is not None and len(bench_df) > 0:
        from utils.indicators import add_relative_strength
        try:
            df = add_relative_strength(df, bench_df, period=RS_PERIOD)
        except Exception:
            df["RS_Score"] = np.nan
    else:
        df["RS_Score"] = np.nan
    return df


def _canonical_dates(bench_df: pd.DataFrame, step: int, warmup: int,
                     max_horizon: int) -> pd.DatetimeIndex:
    """One shared calendar grid every ticker is scored on — this is what makes
    'today's top decile' comparisons meaningful instead of an artifact of
    whichever tickers happened to land on a per-ticker sample row."""
    idx = bench_df.index
    last = len(idx) - max_horizon
    if last <= warmup:
        return idx[0:0]
    return idx[warmup:last:step]


def _walk_forward_rs(ticker: str, df: pd.DataFrame, dates: pd.DatetimeIndex,
                     holdout_cutoff: pd.Timestamp,
                     vix_regimes: Optional[pd.Series],
                     mkt_regimes: Optional[pd.Series]) -> List[Dict]:
    from analysis.score import score_dataframe

    n = len(df)
    closes = df["Close"].astype(float).values
    sma20  = df["SMA_20"].astype(float).values if "SMA_20" in df.columns else np.full(n, np.nan)
    rs_score = df["RS_Score"].astype(float).values if "RS_Score" in df.columns else np.full(n, np.nan)
    pos = pd.Series(np.arange(n), index=df.index)

    if "SMA_200" in df.columns:
        valid = df["SMA_200"].notna().values
        start = int(np.argmax(valid)) if valid.any() else n
    else:
        start = 200
    start = max(start, WARMUP_DAYS - 30)   # a little slack vs. the shared-grid warmup
    last  = n - MAX_HORIZON - 1

    rows: List[Dict] = []
    ticker_dates = dates.intersection(df.index)
    for date in ticker_dates:
        i = int(pos.loc[date])
        if i < start or i > last:
            continue
        sub = df.iloc[: i + 1]
        try:
            cs = score_dataframe(sub, ticker, vix_info=_NEUTRAL_VIX,
                                 sector_rank=_NEUTRAL_SECTOR_RANK, sector="Other")
        except Exception:
            continue
        entry = closes[i]
        if entry <= 0 or not np.isfinite(entry):
            continue

        base = float(cs.score)
        b_rs = _bonus_rs(rs_score[i])
        mreg = _regime_for(date, mkt_regimes)
        gated = base + (0.0 if mreg == "bear" else b_rs)

        fwd20 = (closes[i + 20] / entry - 1.0) * 100.0
        fwd60 = (closes[i + 60] / entry - 1.0) * 100.0
        seg_c, seg_s = closes[i + 1: i + 21], sma20[i + 1: i + 21]
        ok = np.isfinite(seg_s)
        persist = float(np.mean(seg_c[ok] > seg_s[ok]) * 100) if ok.sum() >= 15 else np.nan

        rows.append({
            "ticker": ticker,
            "date": str(date)[:10],
            "split": "holdout" if date >= holdout_cutoff else "train",
            "vix_regime": _regime_for(date, vix_regimes),
            "mkt_regime": mreg,
            "rs_score": round(float(rs_score[i]), 2) if np.isfinite(rs_score[i]) else None,
            "base": base,
            "var_rs": base + b_rs,
            "gated_rs": gated,
            "fwd_20d": fwd20,
            "fwd_60d": fwd60,
            "trend_persist_20": persist,
        })
    return rows


# ─────────────────────────────────────────────────────────────────────────────
# Aggregation
# ─────────────────────────────────────────────────────────────────────────────

def _cross_sectional_spearman(sub: pd.DataFrame, col: str, target: str = "fwd_20d",
                              min_n: int = 15) -> "tuple[float, float, int]":
    rs = []
    for _, g in sub.groupby("date"):
        gg = g[[col, target]].dropna()
        if len(gg) < min_n:
            continue
        r, _ = spearmanr(gg[col], gg[target])
        if np.isfinite(r):
            rs.append(r)
    if not rs:
        return np.nan, np.nan, 0
    return round(float(np.mean(rs)), 4), round(float(np.median(rs)), 4), len(rs)


def _bootstrap_ci(sub: pd.DataFrame, col: str, target: str = "fwd_20d",
                  n_boot: int = 400, seed: int = 42) -> "tuple[float, float, float]":
    """Cluster bootstrap by TICKER (not by row) — resampling whole tickers with
    replacement respects that one ticker's observations aren't independent of
    each other, unlike resampling individual rows would assume."""
    groups = {t: g[[col, target]].dropna().values for t, g in sub.groupby("ticker")}
    groups = {t: v for t, v in groups.items() if len(v) > 0}
    tickers = list(groups.keys())
    if len(tickers) < 10:
        return np.nan, np.nan, np.nan
    rng = np.random.default_rng(seed)
    boots = []
    for _ in range(n_boot):
        samp = rng.choice(tickers, size=len(tickers), replace=True)
        arrs = [groups[t] for t in samp]
        allrows = np.vstack(arrs)
        if len(allrows) < 30:
            continue
        r, _ = spearmanr(allrows[:, 0], allrows[:, 1])
        if np.isfinite(r):
            boots.append(r)
    if not boots:
        return np.nan, np.nan, np.nan
    lo, hi = np.percentile(boots, [2.5, 97.5])
    return round(float(np.mean(boots)), 4), round(float(lo), 4), round(float(hi), 4)


def _decile_spread(sub: pd.DataFrame, col: str, target: str = "fwd_20d") -> "tuple[float, float]":
    d = sub.dropna(subset=[col, target]).copy()
    if len(d) < 100:
        return np.nan, np.nan
    d["decile"] = pd.qcut(d[col].rank(method="first"), 10, labels=list(range(1, 11)))
    g = d.groupby("decile", observed=True)[target].mean()
    idx = pd.Series(range(1, len(g) + 1), dtype=float)
    monotonicity = float(idx.rank().corr(g.reset_index(drop=True).rank()))
    spread = float(g.iloc[-1] - g.iloc[0])
    return round(monotonicity, 3), round(spread, 2)


def _turnover(sub: pd.DataFrame, col: str, base_col: str = "base",
             frac: float = 0.10, min_n: int = 30) -> "tuple[float, int]":
    """Day-over-day: of the names in today's top decile by BASE, what % are
    still in the top decile by `col`? Lower = more list churn if adopted."""
    overlaps = []
    for date, g in sub.groupby("date"):
        gg = g[["ticker", base_col, col]].dropna()
        if len(gg) < min_n:
            continue
        k = max(1, int(len(gg) * frac))
        top_base = set(gg.nlargest(k, base_col)["ticker"])
        top_alt = set(gg.nlargest(k, col)["ticker"])
        overlaps.append(len(top_base & top_alt) / k)
    if not overlaps:
        return np.nan, 0
    return round(float(np.mean(overlaps)) * 100, 1), len(overlaps)


def aggregate(obs: pd.DataFrame, n_boot: int) -> Dict[str, pd.DataFrame]:
    summary_rows, regime_rows, turnover_rows = [], [], []

    for split in ["train", "holdout"]:
        sub = obs[obs["split"] == split]
        if sub.empty:
            continue
        for v in VARIANTS:
            pooled_r, _ = spearmanr(sub[v], sub["fwd_20d"]) if sub[v].notna().any() else (np.nan, None)
            xs_mean, xs_med, n_dates = _cross_sectional_spearman(sub, v)
            boot_mean, boot_lo, boot_hi = _bootstrap_ci(sub, v, n_boot=n_boot)
            monotonicity, spread = _decile_spread(sub, v)
            summary_rows.append({
                "split": split,
                "variant": VARIANT_LABELS[v],
                "n_obs": int(sub[v].notna().sum()),
                "n_dates": n_dates,
                "pooled_spearman_fwd20": round(float(pooled_r), 4) if np.isfinite(pooled_r) else None,
                "cross_sectional_mean_fwd20": xs_mean,
                "cross_sectional_median_fwd20": xs_med,
                "bootstrap_mean": boot_mean,
                "bootstrap_ci_low": boot_lo,
                "bootstrap_ci_high": boot_hi,
                "decile_monotonicity": monotonicity,
                "d10_minus_d1_fwd20": spread,
            })
            if v != "base":
                overlap_pct, n_pairs = _turnover(sub, v)
                turnover_rows.append({
                    "split": split, "variant": VARIANT_LABELS[v],
                    "top_decile_overlap_pct_vs_base": overlap_pct, "n_dates": n_pairs,
                })

        for kind, col in [("market", "mkt_regime"), ("vix", "vix_regime")]:
            for reg, g in sub.groupby(col):
                if len(g) < 200:
                    continue
                row = {"split": split, "regime_type": kind, "regime": reg, "n": len(g)}
                for v in VARIANTS:
                    r, _ = spearmanr(g[v], g["fwd_20d"])
                    row[v] = round(float(r), 4) if np.isfinite(r) else None
                regime_rows.append(row)

    return {
        "summary": pd.DataFrame(summary_rows).set_index(["split", "variant"]),
        "by_regime": pd.DataFrame(regime_rows).set_index(["split", "regime_type", "regime"]) if regime_rows else pd.DataFrame(),
        "turnover": pd.DataFrame(turnover_rows).set_index(["split", "variant"]) if turnover_rows else pd.DataFrame(),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=10)
    ap.add_argument("--step", type=int, default=STEP_DAYS,
                    help="trading-day spacing between sample dates")
    ap.add_argument("--holdout-days", type=int, default=HOLDOUT_DAYS)
    ap.add_argument("--bootstrap-n", type=int, default=400)
    args = ap.parse_args()

    from data.universe import get_universe
    from data.fetcher import fetch_single

    universe = list(get_universe("nifty500"))
    if args.limit:
        universe = universe[: args.limit]

    os.makedirs(OUT_DIR, exist_ok=True)
    t0 = time.time()
    print(f"RS CONFIRMATORY STUDY | universe={len(universe)} | period={PERIOD} | "
          f"step={args.step}d | holdout={args.holdout_days}d")

    vix_regimes = _vix_regime_series(period=PERIOD)
    mkt_regimes = _market_regime_series()

    bench_df = fetch_single(BENCH_TICKER, period=PERIOD)
    if bench_df is None or len(bench_df) == 0:
        print(f"Benchmark ({BENCH_TICKER}) fetch failed — cannot build a shared "
              f"calendar grid or RS_Score. Aborting.")
        return 1
    print(f"Benchmark ({BENCH_TICKER}): OK, {len(bench_df)} bars")

    dates = _canonical_dates(bench_df, args.step, WARMUP_DAYS, MAX_HORIZON)
    if len(dates) == 0:
        print("No valid sample dates in range — aborting.")
        return 1
    holdout_cutoff = dates[-1] - pd.Timedelta(days=int(args.holdout_days * 1.45))
    n_holdout_dates = int((dates >= holdout_cutoff).sum())
    print(f"Sample dates: {len(dates)} ({dates[0].date()} -> {dates[-1].date()}), "
          f"{len(dates) - n_holdout_dates} train / {n_holdout_dates} holdout "
          f"(cutoff {holdout_cutoff.date()})")

    frames: Dict[str, pd.DataFrame] = {}
    prep_failures = 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(_prepare_ticker_rs, t, PERIOD, bench_df): t for t in universe}
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
            if done % 100 == 0:
                print(f"  fetched {done}/{len(universe)} [{time.time()-t0:.0f}s]")
    if prep_failures:
        print(f"  {prep_failures}/{len(universe)} tickers raised an exception during prepare/fetch")
    print(f"Usable tickers: {len(frames)}/{len(universe)} [{time.time()-t0:.0f}s]")

    all_rows: List[Dict] = []
    for k, (t, df) in enumerate(frames.items(), 1):
        all_rows.extend(_walk_forward_rs(t, df, dates, holdout_cutoff, vix_regimes, mkt_regimes))
        if k % 100 == 0:
            print(f"  scored {k}/{len(frames)} ({len(all_rows)} obs) [{time.time()-t0:.0f}s]")

    obs = pd.DataFrame(all_rows)
    if obs.empty:
        print("No observations — aborting.")
        return 1

    obs.to_csv(os.path.join(OUT_DIR, "variant_rs_observations.csv"), index=False, encoding="utf-8")
    n_train = int((obs["split"] == "train").sum())
    n_holdout = int((obs["split"] == "holdout").sum())
    print(f"Observations: {len(obs)} total ({n_train} train / {n_holdout} holdout) "
          f"from {obs['ticker'].nunique()} tickers [{time.time()-t0:.0f}s]")
    print(f"(For comparison: score_variants_untapped.py's exploratory pass produced "
          f"86,828 heavily-overlapping observations for the same signal — this run "
          f"trades that redundant volume for calendar-aligned, near-independent samples.)")

    aggs = aggregate(obs, args.bootstrap_n)
    aggs["summary"].to_csv(os.path.join(OUT_DIR, "variant_rs_summary.csv"), encoding="utf-8")
    if not aggs["by_regime"].empty:
        aggs["by_regime"].to_csv(os.path.join(OUT_DIR, "variant_rs_by_regime.csv"), encoding="utf-8")
    if not aggs["turnover"].empty:
        aggs["turnover"].to_csv(os.path.join(OUT_DIR, "variant_rs_turnover.csv"), encoding="utf-8")
    with open(os.path.join(OUT_DIR, "variant_rs_caveats.txt"), "w", encoding="utf-8") as fh:
        fh.write(SURVIVORSHIP_CAVEAT + "\n")

    pd.set_option("display.width", 220)
    pd.set_option("display.max_columns", 20)
    print("\n=== SUMMARY (train vs holdout) ==="); print(aggs["summary"])
    if not aggs["turnover"].empty:
        print("\n=== TURNOVER vs BASE ==="); print(aggs["turnover"])
    if not aggs["by_regime"].empty:
        print("\n=== BY REGIME ==="); print(aggs["by_regime"])
    print(f"\n{SURVIVORSHIP_CAVEAT}")
    print(f"\nDone in {time.time()-t0:.0f}s. CSVs in {OUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
