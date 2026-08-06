"""
research/score_variants_rs.py — v2, confirmatory follow-up to
research/score_variants_untapped.py, testing ONLY the relative-strength
(RS_Score vs Nifty) variant that looked promising there.

WHY THIS FILE WAS REWRITTEN (v1 -> v2):

v1 sampled one calendar date every 20 trading days (== the fwd_20d horizon,
so forward-return windows never overlapped) to get honestly-independent
observations. It worked as designed, but a live run exposed the cost: over
5 years that's only 43 total calendar dates. Two consequences, both visible
in the v1 output:

  1. BASE's headline fwd20 correlation flipped sign between the dense
     exploratory pass (+0.04) and v1's sparse pass (-0.01 to -0.04, train
     and holdout). With only 43 independent time-snapshots, a result this
     small (already known to be ~0.02-0.04 from the dense studies) is well
     within what pure date-placement luck can produce.
  2. The by-regime breakdown was outright unusable: v1's "holdout bear"
     correlation was built from exactly 2 distinct calendar dates. Digging
     further (counting contiguous regime runs, not just sampled dates) found
     the deeper reason: the underlying 5-year history only contains ~3
     sustained bear episodes and ~3 sustained bull legs. That is a data-
     availability ceiling, not a sampling-density bug — no amount of
     resampling manufactures market history that didn't happen. v2 does not
     try to fix this; see REGIME CAVEAT below.

v2's fix, scoped only to the part that IS fixable — the split-level
train/holdout point estimates:

  - STEP_DAYS dropped from 20 to 5 (still one shared calendar grid across
    every ticker, unlike score_variants_untapped.py's per-ticker-index
    sampling). This quadruples the raw date count (43 -> ~170), which
    directly stabilises the point estimate: instead of one date's noise
    deciding a whole block, each ~20-trading-day BLOCK now averages over
    ~4 dates x ~480 tickers before contributing to the headline number.
  - BLOCK_DAYS=20 groups those denser samples back into ~43 non-overlapping
    time blocks (unchanged from v1's date count) for the CONFIDENCE
    INTERVAL. This is the honest part: the underlying number of independent
    ~20-trading-day market windows in 5 years hasn't changed just because
    we sample more densely inside each one. v1's ticker-only bootstrap
    ignored this and was almost certainly overconfident (too narrow) about
    time-dimension uncertainty; v2's block bootstrap resamples BLOCKS, not
    tickers, and directly answers "would this conclusion survive different
    market windows happening to fall in the sample" rather than "would it
    survive different stocks being in the universe."
  - Net effect: sturdier, less date-placement-sensitive POINT ESTIMATES,
    and a CI that may well be WIDER than v1 reported, because it is now
    measuring the real bottleneck instead of the wrong one. A wider-but-
    honest interval is the intended outcome here, not a regression.

REGIME CAVEAT (this is why the by-regime table below is directional only):
the ~3 real bear episodes and ~3 real bull legs in this 5-year window are
each counted once as an "episode" alongside their date/observation counts.
Read n_episodes, not n (observation count) or a Spearman decimal, as the
true sample size for any regime-specific claim. No fix in this script raises
that number — only more calendar time or a longer history would.

STANDING CAVEAT THIS SCRIPT CANNOT FIX: data/universe.py's get_universe()
returns TODAY's Nifty constituent list applied retroactively across 5 years.
Stocks dropped from the index in that period (usually for underperforming)
are invisible here, which specifically tends to inflate relative-strength
findings. There is no free-tier fix for point-in-time index membership.

PRODUCTION SCORING IS NOT MODIFIED.

Run:
    py -m research.score_variants_rs                 # full universe (~5-7 min)
    py -m research.score_variants_rs --limit 20       # pipeline check

Outputs (research/output/):
    variant_rs_observations.csv   one row per ticker x sampled date (+ block_id)
    variant_rs_summary.csv        pooled + cross-sectional + block-bootstrap CI, by split
    variant_rs_verdict.txt        plain-language read of whether BASE/RS's CI excludes zero
    variant_rs_by_regime.csv      DIRECTIONAL ONLY — see REGIME CAVEAT above
    variant_rs_turnover.csv       day-over-day top-decile overlap, by split
    variant_rs_caveats.txt        the two caveats above, in one place
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
STEP_DAYS     = 5        # dense enough to average out single-date noise within a block
BLOCK_DAYS    = 20        # == fwd_20d horizon; the unit the bootstrap treats as independent
MAX_HORIZON   = 60
WARMUP_DAYS   = 330        # >= RS's 252-bar window + 63-bar momentum lookback + buffer
HOLDOUT_DAYS  = 252        # ~1 trading year reserved, untouched by the RS design
BENCH_TICKER  = "^NSEI"
RS_PERIOD     = 63
BONUS_MAX     = 8.0         # unchanged from score_variants_untapped.py — same bonus, harder test

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
    "point-in-time index membership."
)
REGIME_CAVEAT = (
    "REGIME TABLE CAVEAT: the by-regime breakdown is DIRECTIONAL ONLY, not a "
    "statistical claim. This 5-year window contains roughly 3 sustained bear "
    "episodes and 3 sustained bull legs (see n_episodes column) — every date "
    "inside one episode is a correlated draw from the same market event, not a "
    "fresh independent sample. No amount of denser date sampling raises that "
    "count; only more calendar time or a longer history would. Treat n_episodes, "
    "not the observation count or the correlation's decimal places, as the real "
    "sample size here."
)


def _bonus_rs(rs_score: float) -> float:
    """Identical to score_variants_untapped.py's _bonus_rs — re-testing the SAME
    formula more rigorously, not re-tuning it."""
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


def _canonical_grid(bench_df: pd.DataFrame, step: int, block_days: int, warmup: int,
                    max_horizon: int) -> "tuple[pd.DatetimeIndex, Dict[pd.Timestamp, int]]":
    """One shared calendar grid every ticker is scored on, plus a date -> block_id
    map (block_id = which non-overlapping ~block_days-trading-day window a date
    falls in). Same block map is reused for both the bootstrap and the regime-
    episode count, so 'how many independent time units do we have' means the
    same thing everywhere in this script."""
    idx = bench_df.index
    last = len(idx) - max_horizon
    if last <= warmup:
        return idx[0:0], {}
    dates = idx[warmup:last:step]
    block_of = {d: int((pos - warmup) // block_days)
                for pos, d in zip(range(warmup, last, step), dates)}
    return dates, block_of


def _walk_forward_rs(ticker: str, df: pd.DataFrame, dates: pd.DatetimeIndex,
                     block_of: Dict[pd.Timestamp, int], holdout_cutoff: pd.Timestamp,
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
    start = max(start, WARMUP_DAYS - 30)
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
            "block_id": block_of.get(date, -1),
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


def _block_bootstrap_ci(sub: pd.DataFrame, col: str, target: str = "fwd_20d",
                        n_boot: int = 400, seed: int = 42) -> "tuple[float, float, float, int]":
    """Resample TIME BLOCKS (not tickers, not individual dates) with replacement.
    This is the fix for v1's flaw: a block (~20 trading days) is the actual unit
    of independent market history here, since forward-return windows within a
    block overlap by construction. Ticker count was never the bottleneck --
    ~470 tickers per date is already plenty -- so this replaces v1's ticker
    bootstrap rather than supplementing it."""
    blocks = {b: g[[col, target]].dropna().values for b, g in sub.groupby("block_id")}
    blocks = {b: v for b, v in blocks.items() if len(v) > 0}
    block_ids = list(blocks.keys())
    if len(block_ids) < 5:
        return np.nan, np.nan, np.nan, len(block_ids)
    rng = np.random.default_rng(seed)
    boots = []
    for _ in range(n_boot):
        samp = rng.choice(block_ids, size=len(block_ids), replace=True)
        allrows = np.vstack([blocks[b] for b in samp])
        if len(allrows) < 30:
            continue
        r, _ = spearmanr(allrows[:, 0], allrows[:, 1])
        if np.isfinite(r):
            boots.append(r)
    if not boots:
        return np.nan, np.nan, np.nan, len(block_ids)
    lo, hi = np.percentile(boots, [2.5, 97.5])
    return round(float(np.mean(boots)), 4), round(float(lo), 4), round(float(hi), 4), len(block_ids)


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


def _regime_episodes(obs: pd.DataFrame, split: str, kind_col: str) -> pd.DataFrame:
    """Count contiguous regime RUNS (episodes), not sampled dates or rows --
    this is the number that actually bounds statistical confidence here."""
    dr = (obs[obs["split"] == split][["date", kind_col]]
          .drop_duplicates().sort_values("date").reset_index(drop=True))
    if dr.empty:
        return pd.DataFrame(columns=["regime", "n_episodes"])
    dr["ep"] = (dr[kind_col] != dr[kind_col].shift()).cumsum()
    return (dr.groupby("ep")[kind_col].first().value_counts()
              .rename_axis("regime").reset_index(name="n_episodes"))


def aggregate(obs: pd.DataFrame, n_boot: int) -> Dict[str, pd.DataFrame]:
    summary_rows, regime_rows, turnover_rows = [], [], []
    verdict_lines = []

    for split in ["train", "holdout"]:
        sub = obs[obs["split"] == split]
        if sub.empty:
            continue
        verdict_lines.append(f"\n[{split.upper()}]")
        for v in VARIANTS:
            pooled_r, _ = spearmanr(sub[v], sub["fwd_20d"]) if sub[v].notna().any() else (np.nan, None)
            xs_mean, xs_med, n_dates = _cross_sectional_spearman(sub, v)
            boot_mean, boot_lo, boot_hi, n_blocks = _block_bootstrap_ci(sub, v, n_boot=n_boot)
            monotonicity, spread = _decile_spread(sub, v)
            summary_rows.append({
                "split": split, "variant": VARIANT_LABELS[v],
                "n_obs": int(sub[v].notna().sum()), "n_dates": n_dates, "n_blocks": n_blocks,
                "pooled_spearman_fwd20": round(float(pooled_r), 4) if np.isfinite(pooled_r) else None,
                "cross_sectional_mean_fwd20": xs_mean,
                "block_bootstrap_mean": boot_mean,
                "block_bootstrap_ci_low": boot_lo,
                "block_bootstrap_ci_high": boot_hi,
                "decile_monotonicity": monotonicity,
                "d10_minus_d1_fwd20": spread,
            })
            if np.isfinite(boot_lo) and np.isfinite(boot_hi):
                if boot_lo > 0:
                    read = f"reliably POSITIVE (CI [{boot_lo:+.4f}, {boot_hi:+.4f}], {n_blocks} blocks)"
                elif boot_hi < 0:
                    read = f"reliably NEGATIVE (CI [{boot_lo:+.4f}, {boot_hi:+.4f}], {n_blocks} blocks)"
                else:
                    read = f"NOT distinguishable from zero (CI [{boot_lo:+.4f}, {boot_hi:+.4f}], {n_blocks} blocks)"
            else:
                read = "too few blocks to estimate a CI"
            verdict_lines.append(f"  {VARIANT_LABELS[v]:42s} {read}")

            if v != "base":
                overlap_pct, n_pairs = _turnover(sub, v)
                turnover_rows.append({"split": split, "variant": VARIANT_LABELS[v],
                                      "top_decile_overlap_pct_vs_base": overlap_pct, "n_dates": n_pairs})

        for kind, col in [("market", "mkt_regime"), ("vix", "vix_regime")]:
            ep = _regime_episodes(sub, split, col).set_index("regime")["n_episodes"].to_dict()
            for reg, g in sub.groupby(col):
                if len(g) < 200:
                    continue
                row = {"split": split, "regime_type": kind, "regime": reg,
                      "n_episodes": ep.get(reg, None), "n_obs": len(g)}
                for v in VARIANTS:
                    r, _ = spearmanr(g[v], g["fwd_20d"])
                    row[v] = round(float(r), 4) if np.isfinite(r) else None
                regime_rows.append(row)

    return {
        "summary": pd.DataFrame(summary_rows).set_index(["split", "variant"]),
        "by_regime": pd.DataFrame(regime_rows).set_index(["split", "regime_type", "regime"]) if regime_rows else pd.DataFrame(),
        "turnover": pd.DataFrame(turnover_rows).set_index(["split", "variant"]) if turnover_rows else pd.DataFrame(),
        "verdict": "\n".join(verdict_lines),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=10)
    ap.add_argument("--step", type=int, default=STEP_DAYS)
    ap.add_argument("--block-days", type=int, default=BLOCK_DAYS)
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
    print(f"RS CONFIRMATORY STUDY v2 | universe={len(universe)} | period={PERIOD} | "
          f"step={args.step}d | block={args.block_days}d | holdout={args.holdout_days}d")

    vix_regimes = _vix_regime_series(period=PERIOD)
    mkt_regimes = _market_regime_series()

    bench_df = fetch_single(BENCH_TICKER, period=PERIOD)
    if bench_df is None or len(bench_df) == 0:
        print(f"Benchmark ({BENCH_TICKER}) fetch failed — aborting.")
        return 1
    print(f"Benchmark ({BENCH_TICKER}): OK, {len(bench_df)} bars")

    dates, block_of = _canonical_grid(bench_df, args.step, args.block_days, WARMUP_DAYS, MAX_HORIZON)
    if len(dates) == 0:
        print("No valid sample dates in range — aborting.")
        return 1
    n_blocks_total = len(set(block_of.values()))
    holdout_cutoff = dates[-1] - pd.Timedelta(days=int(args.holdout_days * 1.45))
    n_holdout_dates = int((dates >= holdout_cutoff).sum())
    print(f"Sample dates: {len(dates)} across {n_blocks_total} time blocks "
          f"({dates[0].date()} -> {dates[-1].date()}), "
          f"{len(dates) - n_holdout_dates} train dates / {n_holdout_dates} holdout dates "
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
        all_rows.extend(_walk_forward_rs(t, df, dates, block_of, holdout_cutoff, vix_regimes, mkt_regimes))
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

    aggs = aggregate(obs, args.bootstrap_n)
    aggs["summary"].to_csv(os.path.join(OUT_DIR, "variant_rs_summary.csv"), encoding="utf-8")
    if not aggs["by_regime"].empty:
        aggs["by_regime"].to_csv(os.path.join(OUT_DIR, "variant_rs_by_regime.csv"), encoding="utf-8")
    if not aggs["turnover"].empty:
        aggs["turnover"].to_csv(os.path.join(OUT_DIR, "variant_rs_turnover.csv"), encoding="utf-8")
    with open(os.path.join(OUT_DIR, "variant_rs_verdict.txt"), "w", encoding="utf-8") as fh:
        fh.write("Plain-language read of each variant's block-bootstrap CI vs zero:\n" + aggs["verdict"] + "\n")
    with open(os.path.join(OUT_DIR, "variant_rs_caveats.txt"), "w", encoding="utf-8") as fh:
        fh.write(SURVIVORSHIP_CAVEAT + "\n\n" + REGIME_CAVEAT + "\n")

    pd.set_option("display.width", 220)
    pd.set_option("display.max_columns", 20)
    print("\n=== SUMMARY (train vs holdout) ==="); print(aggs["summary"])
    print("\n=== VERDICT ==="); print(aggs["verdict"])
    if not aggs["turnover"].empty:
        print("\n=== TURNOVER vs BASE ==="); print(aggs["turnover"])
    if not aggs["by_regime"].empty:
        print("\n=== BY REGIME (directional only — see caveat) ==="); print(aggs["by_regime"])
    print(f"\n{SURVIVORSHIP_CAVEAT}\n\n{REGIME_CAVEAT}")
    print(f"\nDone in {time.time()-t0:.0f}s. CSVs in {OUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
