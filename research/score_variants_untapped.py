"""
research/score_variants_untapped.py — comparative evaluation of five
"untapped" indicator-family variants against the production composite,
through the same 5-year walk-forward framework as research/score_variants.py,
research/score_variants_volume.py and research/score_variants_regime.py.

WHY THIS EXISTS: MJ asked what's out there beyond RSI/MACD/momentum, sorted
by category (volume-based, trend/structure, volatility, statistical/quant,
other), and asked whether they could be combined into a testable structure.
A repo audit found the answer is mostly "already computed, never scored":
utils/indicators.py's add_all_indicators() — which research/score_efficacy.py's
_prepare_ticker() already calls for every walk-forward frame — unconditionally
computes VWAP_20/VWAP_Pct, BB_Pct/BB_Width, Stoch_K/Stoch_D, Supertrend/
ST_Direction, Price_vs_CPR, and Fib_Zone on every ticker. None of these reach
analysis/score.py's CompositeScore. add_relative_strength() (RS_Score, a
0-100 percentile rank vs a benchmark — the IBD-style "statistical/quant"
factor) exists too, but isn't even wired into add_all_indicators — it takes
a benchmark frame as a second argument and has never been called from
anywhere in the codebase.

This script tests one candidate bonus factor per category, each derived from
columns that already exist on the walk-forward frame (RS_Score needs exactly
one extra network call — fetching ^NSEI once, not per ticker):

  Category            | Column(s) used         | Variant
  ---------------------|------------------------|----------
  Volume-based          | VWAP_Pct               | var_vwap
  Trend/structure        | ST_Direction           | var_st
  Volatility             | BB_Pct                 | var_bbw
  Statistical/quant      | RS_Score               | var_rs
  Other (oscillator)     | Stoch_K, Stoch_D       | var_stoch
  Combined                | all five bonuses summed | var_all

PRODUCTION SCORING IS NOT MODIFIED. Each variant is BASE (production 90-pt
composite, cs.score — sentiment held constant via the same
_NEUTRAL_VIX/_NEUTRAL_SECTOR_RANK convention as the sibling scripts, so it
doesn't bias rank comparisons) PLUS a bonus factor scaled to 0-8 points —
roughly the size of one existing sub-factor (e.g. OBV's 5pts inside the
volume block) — so no single new signal can dominate the composite the way
a careless full-weight bolt-on would. var_all sums all five bonuses
(0-40 extra points) specifically to test MJ's "can these combine into a
structure" question as its own hypothesis, distinct from any one factor
alone.

Each bonus function is a first-pass, deliberately simple mapping (documented
inline) — the point of this script is to find out whether the RAW signal in
each already-computed column has any forward-return power at all before
spending effort refining the mapping. A near-zero-to-negative result here
should be treated exactly like the volume-component finding that motivated
score_variants_volume.py: evidence, not a verdict, but not something to keep
refining either.

Spearman/decile comparisons are rank-based, so the differing point scales
across variants do not bias the comparison.

Run:
    py -m research.score_variants_untapped            # full universe (~5 min)
    py -m research.score_variants_untapped --limit 20 # pipeline check

Outputs:
    research/output/variant_untapped_observations.csv
    research/output/variant_untapped_summary.csv      (correlations + monotonicity)
    research/output/variant_untapped_by_regime.csv     (bull/bear/sideways + VIX regimes)
    research/output/variant_untapped_deciles_<V>.csv   (decile monotonicity per variant)
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

PERIOD       = "5y"
SAMPLE_STEP  = 5
MAX_HORIZON  = 60
BENCH_TICKER = "^NSEI"   # same benchmark used by regime_study._market_regime_series
RS_PERIOD    = 63        # IBD-convention RS momentum lookback (matches add_relative_strength default)
BONUS_MAX    = 8.0        # per-factor bonus scale — see module docstring for why 8

VARIANTS = ["base", "var_rs", "var_vwap", "var_st", "var_bbw", "var_stoch", "var_all"]
VARIANT_LABELS = {
    "base":      "BASE (production 90-pt)",
    "var_rs":    "RS: + relative strength vs Nifty (statistical/quant)",
    "var_vwap":  "VWAP: + 20d VWAP deviation (volume-based)",
    "var_st":    "ST: + Supertrend direction (trend/structure)",
    "var_bbw":   "BBW: + Bollinger %B position (volatility)",
    "var_stoch": "STOCH: + Stochastic K/D cross (other/oscillator)",
    "var_all":   "ALL: five bonuses combined (kitchen sink)",
}


# ─────────────────────────────────────────────────────────────────────────────
# Bonus factors — each a simple, documented, first-pass mapping from an
# already-computed column to a 0-8 point bonus. Neutral (4.0, the midpoint)
# whenever the underlying column is unavailable/NaN, so missing data doesn't
# arbitrarily help or hurt a variant's ranking relative to BASE.
# ─────────────────────────────────────────────────────────────────────────────

def _bonus_rs(rs_score: float) -> float:
    """Statistical/quant: RS_Score is already a 0-100 percentile rank of the
    stock's relative-strength line vs Nifty within its own trailing 252-day
    range (add_relative_strength, IBD RS Rating convention). Linear rescale
    to 0-8 — no additional judgement layered on top."""
    if rs_score is None or not np.isfinite(rs_score):
        return BONUS_MAX / 2.0
    return round(float(np.clip(rs_score, 0.0, 100.0)) / 100.0 * BONUS_MAX, 3)


def _bonus_vwap(vwap_pct: float) -> float:
    """Volume-based: VWAP_Pct is % deviation of Close from the 20-day
    volume-weighted average price (institutional fair-value reference).
    Trend-following read: further above VWAP = more bonus, symmetric around
    0, clipped at +/-10% so a single extreme gap-up day can't saturate it."""
    if vwap_pct is None or not np.isfinite(vwap_pct):
        return BONUS_MAX / 2.0
    clipped = float(np.clip(vwap_pct, -10.0, 10.0))
    return round((clipped + 10.0) / 20.0 * BONUS_MAX, 3)


def _bonus_supertrend(st_direction: float) -> float:
    """Trend/structure: ST_Direction is already a clean discrete signal
    (1 = bullish, -1 = bearish, 0 = warm-up/undefined) — no rescaling
    judgement needed, just map to the same 0-8 scale as the other bonuses."""
    if st_direction is None or not np.isfinite(st_direction):
        return BONUS_MAX / 2.0
    if st_direction > 0:
        return BONUS_MAX
    if st_direction < 0:
        return 0.0
    return BONUS_MAX / 2.0


def _bonus_bbw(bb_pct: float) -> float:
    """Volatility: BB_Pct (%B) is where Close sits within the Bollinger Band,
    0 = at the lower band, 1 = at the upper band (can exceed [0,1] on a
    breakout). Clipped to [0,1] and rescaled — a direct test of
    volatility-relative positioning distinct from RSI's own overbought/
    oversold read, which is unbounded and mean-reverting rather than
    band-relative."""
    if bb_pct is None or not np.isfinite(bb_pct):
        return BONUS_MAX / 2.0
    clipped = float(np.clip(bb_pct, 0.0, 1.0))
    return round(clipped * BONUS_MAX, 3)


def _bonus_stoch(stoch_k: float, stoch_d: float) -> float:
    """Other/oscillator: Stochastic K/D cross — deliberately distinct from
    the production RSI map (different lookback convention, band-relative
    rather than smoothed-momentum). Full bonus for a bullish, not-yet-
    overbought cross; half credit for bullish-but-overbought (still in an
    uptrend, but the easy move may be behind it); zero for bearish."""
    if (stoch_k is None or stoch_d is None
            or not np.isfinite(stoch_k) or not np.isfinite(stoch_d)):
        return BONUS_MAX / 2.0
    if stoch_k > stoch_d:
        return (BONUS_MAX / 2.0) if stoch_k > 80 else BONUS_MAX
    return 0.0


# ─────────────────────────────────────────────────────────────────────────────
# Ticker prep — reuse score_efficacy's _prepare_ticker (already runs
# add_all_indicators, which unconditionally computes VWAP/BB/Stochastic/
# Supertrend/CPR/Fibonacci), then layer on RS_Score against one pre-fetched
# benchmark frame (add_relative_strength is not part of add_all_indicators —
# it takes a second benchmark-frame argument, so it can't be auto-included).
# ─────────────────────────────────────────────────────────────────────────────

def _prepare_ticker_untapped(ticker: str, period: str,
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


# ─────────────────────────────────────────────────────────────────────────────
# Walk-forward — production score, then derive the five candidate variants
# from columns already sitting on the frame (no raw recomputation needed,
# except benchmark-relative RS_Score which was layered on in prep above)
# ─────────────────────────────────────────────────────────────────────────────

def _walk_forward_variants(ticker: str, df: pd.DataFrame,
                           vix_regimes: Optional[pd.Series],
                           mkt_regimes: Optional[pd.Series]) -> "tuple[List[Dict], int]":
    from analysis.score import score_dataframe

    closes = df["Close"].astype(float).values
    n      = len(df)
    sma20  = (df["SMA_20"].astype(float).values
              if "SMA_20" in df.columns else np.full(n, np.nan))

    def _col(name: str) -> np.ndarray:
        return (df[name].astype(float).values
                if name in df.columns else np.full(n, np.nan))

    vwap_pct = _col("VWAP_Pct")
    bb_pct   = _col("BB_Pct")
    st_dir   = _col("ST_Direction")
    stoch_k  = _col("Stoch_K")
    stoch_d  = _col("Stoch_D")
    rs_score = _col("RS_Score")

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

        base = float(cs.score)

        b_rs    = _bonus_rs(rs_score[i])
        b_vwap  = _bonus_vwap(vwap_pct[i])
        b_st    = _bonus_supertrend(st_dir[i])
        b_bbw   = _bonus_bbw(bb_pct[i])
        b_stoch = _bonus_stoch(stoch_k[i], stoch_d[i])

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
            "rs_score":  round(float(rs_score[i]), 2) if np.isfinite(rs_score[i]) else None,
            "vwap_pct":  round(float(vwap_pct[i]), 2) if np.isfinite(vwap_pct[i]) else None,
            "st_dir":    int(st_dir[i]) if np.isfinite(st_dir[i]) else None,
            "bb_pct":    round(float(bb_pct[i]), 3) if np.isfinite(bb_pct[i]) else None,
            "base":      base,
            "var_rs":    base + b_rs,
            "var_vwap":  base + b_vwap,
            "var_st":    base + b_st,
            "var_bbw":   base + b_bbw,
            "var_stoch": base + b_stoch,
            "var_all":   base + b_rs + b_vwap + b_st + b_bbw + b_stoch,
            "fwd_20d": fwd20,
            "fwd_60d": fwd60,
            "trend_persist_20": persist,
        })
    return rows, score_failures


# ─────────────────────────────────────────────────────────────────────────────
# Aggregations (identical shape to the sibling variant scripts, for easy
# side-by-side comparison of every variant study's summary tables)
# ─────────────────────────────────────────────────────────────────────────────

def _decile_fwd20(obs: pd.DataFrame, col: str) -> pd.DataFrame:
    d = obs.dropna(subset=[col]).copy()
    d["decile"] = pd.qcut(d[col].rank(method="first"), 10,
                          labels=list(range(1, 11)))
    return (d.groupby("decile", observed=True)
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
    from data.fetcher import fetch_single

    universe = list(get_universe("nifty500"))
    if args.limit:
        universe = universe[: args.limit]

    os.makedirs(OUT_DIR, exist_ok=True)
    t0 = time.time()
    print(f"UNTAPPED-INDICATOR VARIANT STUDY | universe={len(universe)} | period={PERIOD}")

    vix_regimes = _vix_regime_series(period=PERIOD)
    mkt_regimes = _market_regime_series()

    bench_df = None
    try:
        bench_df = fetch_single(BENCH_TICKER, period=PERIOD)
        print(f"Benchmark ({BENCH_TICKER}): OK, {len(bench_df)} bars"
              if bench_df is not None and len(bench_df) else "Benchmark: EMPTY")
    except Exception as e:
        print(f"Benchmark ({BENCH_TICKER}) fetch failed — RS_Score will be neutral for all "
              f"observations: {e}")

    frames: Dict[str, pd.DataFrame] = {}
    prep_failures = 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(_prepare_ticker_untapped, t, PERIOD, bench_df): t for t in universe}
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

    obs.to_csv(os.path.join(OUT_DIR, "variant_untapped_observations.csv"),
               index=False, encoding="utf-8")
    print(f"Observations: {len(obs)} from {obs['ticker'].nunique()} tickers | "
          f"{obs['date'].min()} -> {obs['date'].max()}")
    rs_coverage = float(obs["rs_score"].notna().mean() * 100)
    print(f"RS_Score coverage: {rs_coverage:.1f}% of observations "
          f"(needs >= {RS_PERIOD + 10} overlapping benchmark bars)")

    aggs = aggregate(obs)
    aggs["summary"].to_csv(os.path.join(OUT_DIR, "variant_untapped_summary.csv"), encoding="utf-8")
    aggs["by_regime"].to_csv(os.path.join(OUT_DIR, "variant_untapped_by_regime.csv"), encoding="utf-8")
    for v in VARIANTS:
        aggs[f"deciles_{v}"].to_csv(os.path.join(OUT_DIR, f"variant_untapped_deciles_{v}.csv"),
                                    encoding="utf-8")

    pd.set_option("display.width", 200)
    print("\n=== VARIANT SUMMARY ===");  print(aggs["summary"])
    print("\n=== FWD-20 SPEARMAN BY REGIME ==="); print(aggs["by_regime"])
    print(f"\nDone in {time.time()-t0:.0f}s. CSVs in {OUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
