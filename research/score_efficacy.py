"""
research/score_efficacy.py — Score Efficacy Research Framework.

Determines whether the PRODUCTION composite score has predictive power.
READ-ONLY with respect to the model: imports analysis.score and replays it
walk-forward over history. Does NOT modify weights, thresholds, grades or
actions anywhere.

Methodology (agreed spec):
  • Weekly sampling — every 5th trading day, to avoid overlapping-window bias.
  • Survivorship disclosure — universe is CURRENT constituents; conclusions are
    framed as ranking power *within surviving* liquid NSE names.
  • Sentiment handled separately — the primary metric is the 90-point
    price-derived score (technical+momentum+volume). Candlestick patterns are
    no longer a scored component in production (see docs/PATTERN_REMOVAL_MIGRATION.md);
    "pattern" here is tracked as a binary any-pattern-detected flag for factor
    attribution, not a point value. VIX regime is used as a BREAKDOWN label
    (reconstructed from the historical ^INDIAVIX series), not as a score input.
  • TP/SL ambiguity rule — if a single daily bar touches both TP and SL, count
    it SL-first (conservative) and tally it separately as ambiguous.
  • Baselines — 20-day momentum rank, RSI rank, SMA200-distance rank, evaluated
    on the SAME observations, so the composite must beat trivial alternatives.

Run (from repo root; takes a few minutes — network for ~220 tickers):
    py -m research.score_efficacy            # full universe
    py -m research.score_efficacy --limit 30 # quick pipeline check

Outputs:
    research/output/observations.csv      one row per (ticker, sample-date)
    research/output/decile_returns.csv    score-decile forward-return table
    research/output/decile_tpsl.csv       score-decile TP/SL outcome table
    research/output/factor_attribution.csv  per-component rank correlations
    research/output/baselines.csv         composite vs naive-ranking comparison
    research/output/sector_breakdown.csv
    research/output/regime_breakdown.csv
    research/output/accuracy_report.csv   honest hit-rate table, train/holdout
                                          split, gross + net-of-cost.  FIX EFF-ACC.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

_log = logging.getLogger("research.score_efficacy")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

OUT_DIR = os.path.join(_ROOT, "research", "output")

# Sampling / horizon parameters
SAMPLE_STEP   = 5      # every 5th trading day (weekly) — independence
MAX_HORIZON   = 60     # longest forward window measured
HORIZONS      = (5, 20, 60)

# ── FIX EFF-COST — realistic NSE round-trip cost floor ───────────────────────
# The original walk-forward measured gross forward returns and gross TP/SL
# hit rates — i.e. "accuracy" numbers that a live account can never realise.
# On NSE delivery-equity the round-trip cost floor circa 2026 is:
#
#   Brokerage         ~ 0.03% × 2 sides                     = 0.06%
#   STT               ~ 0.10% on sell side                  = 0.10%
#   Exchange txn      ~ 0.00325% × 2                        = 0.0065%
#   Stamp             ~ 0.015% on buy side                  = 0.015%
#   SEBI + GST on above (18% on brok+txn)                   ~ 0.014%
#   Slippage          ~ 0.05% × 2 (bid-ask + market impact) = 0.10%
#   ─────────────────────────────────────────────────────────────────
#   TOTAL round-trip  ≈ 0.30% of trade value
#
# Any forward-return number that ignores this is overstated by ~0.30 pct
# points; any "hit rate" that counts a trade as a win the moment TP is
# TOUCHED (even by 0.01%) counts many trades that actually netted zero or
# less. Every "net" column added below subtracts this cost floor once per
# round trip, so the reported accuracy is what a real broker account would
# have booked, not the paper-perfect version. Kept as a single tunable so we
# can revisit (e.g. discount brokers zero the brokerage line, but stamp/STT/
# exchange charges are non-negotiable; institutional slippage is smaller).
COST_ROUNDTRIP_PCT = 0.30

# Neutral sentiment inputs — sentiment is studied separately, so we hold the
# production scorer's sentiment inputs constant across all observations.
_NEUTRAL_VIX = {"regime": "normal", "vix": None, "allow_buy": True}
_NEUTRAL_SECTOR_RANK = 7


# ─────────────────────────────────────────────────────────────────────────────
# Historical VIX regime labels (breakdown only — not a score input)
# ─────────────────────────────────────────────────────────────────────────────

def _vix_regime_series(period: str = "2y") -> Optional[pd.Series]:
    """Daily ^INDIAVIX close → regime label, for tagging each sample date."""
    try:
        from data.fetcher import fetch_single
        vdf = fetch_single("^INDIAVIX", period=period)
        if vdf is None or vdf.empty:
            return None
        v = vdf["Close"].astype(float)

        def lab(x: float) -> str:
            if x < 13:  return "complacency"
            if x < 17:  return "normal"
            if x < 22:  return "elevated"
            if x < 28:  return "fear"
            return "panic"

        return v.map(lab)
    except Exception as e:
        print(f"  VIX regime series unavailable ({type(e).__name__}: {e}) — "
              f"regime will be 'unknown' for all rows")
        return None


_regime_for_failures = 0


def _regime_for(date, regimes: Optional[pd.Series]) -> str:
    global _regime_for_failures
    if regimes is None:
        return "unknown"
    try:
        idx = regimes.index.asof(pd.Timestamp(date))
        if pd.isna(idx):
            return "unknown"
        return str(regimes.loc[idx])
    except Exception:
        _regime_for_failures += 1
        return "unknown"


# ─────────────────────────────────────────────────────────────────────────────
# Per-ticker walk-forward
# ─────────────────────────────────────────────────────────────────────────────

_prepare_ticker_exceptions = 0


_STUDY_PERIOD_ENV = os.environ.get("SCORE_EFFICACY_PERIOD", "").strip()


def _prepare_ticker(ticker: str, period: str = "2y") -> Optional[pd.DataFrame]:
    """Fetch daily bars (default 2y) and enrich with the production indicators.

    Indicators are rolling/causal, so computing them once on the full frame and
    then slicing df.iloc[:i+1] is identical to recomputing on each slice — no
    look-ahead is introduced.
    """
    global _prepare_ticker_exceptions
    try:
        from data.fetcher import fetch_single
        from utils.indicators import add_all_indicators
        df = fetch_single(ticker, period=period)
        if df is None or df.empty or len(df) < 280:
            return None  # benign: just not enough history, not a real failure
        df = add_all_indicators(df)
        df = df.dropna(subset=["RSI", "ATR"])
        return df if len(df) >= 280 else None
    except Exception as e:
        # NOTE: this swallows the real exception on purpose so the caller's
        # ThreadPoolExecutor `f.result()` never raises — but that means the
        # caller's own `except Exception: prep_failures += 1` can NEVER fire
        # for a genuine crash in here, silently undercounting real failures
        # as if they were just "insufficient data." Track separately so
        # main()'s summary print reflects reality.
        _prepare_ticker_exceptions += 1
        _log.debug("_prepare_ticker: %s raised during prep, treated as no-data: %s", ticker, e)
        return None


def _walk_forward(ticker: str, df: pd.DataFrame, sector: str,
                  regimes: Optional[pd.Series]) -> "Tuple[List[Dict], int]":
    """Score the production model at weekly sample points; measure forward."""
    from analysis.score import score_dataframe

    closes = df["Close"].astype(float).values
    highs  = df["High"].astype(float).values
    lows   = df["Low"].astype(float).values
    n      = len(df)

    # First index where SMA_200 is valid (the scorer leans on the full stack)
    if "SMA_200" in df.columns:
        valid = df["SMA_200"].notna().values
        start = int(np.argmax(valid)) if valid.any() else n
    else:
        start = 200
    start = max(start, 65)                      # momentum lookback comfort
    last  = n - MAX_HORIZON - 1                 # need a full 60-day forward path

    rows: List[Dict] = []
    score_failures = 0
    for i in range(start, last, SAMPLE_STEP):
        sub = df.iloc[: i + 1]
        try:
            cs = score_dataframe(sub, ticker, vix_info=_NEUTRAL_VIX,
                                 sector_rank=_NEUTRAL_SECTOR_RANK, sector=sector)
        except Exception:
            score_failures += 1
            continue

        entry = closes[i]
        if entry <= 0 or not np.isfinite(entry):
            continue

        # Forward returns — gross AND net of realistic round-trip cost (FIX EFF-COST)
        fwd = {}
        for h in HORIZONS:
            gross = (closes[i + h] / entry - 1.0) * 100.0
            fwd[f"fwd_{h}d"]     = gross
            fwd[f"fwd_{h}d_net"] = gross - COST_ROUNDTRIP_PCT

        # TP/SL path walk over the next MAX_HORIZON bars.
        # `outcome` = TP hit before SL, treating a touch as a fill (paper-perfect).
        # `outcome_net` = same, but requires the TP margin over entry to exceed
        # the round-trip cost floor — a "TP" that barely clears entry is booked
        # as `neither` here, because in a real broker account it netted nothing.
        sl, tp = float(cs.stop_loss), float(cs.target)
        outcome, days_to = "neither", None
        outcome_net = "neither"
        ambiguous = False
        tp_gain_pct = ((tp - entry) / entry * 100.0) if entry > 0 else 0.0
        tp_clears_costs = tp_gain_pct > COST_ROUNDTRIP_PCT
        if sl > 0 and tp > entry:
            for j in range(i + 1, i + 1 + MAX_HORIZON):
                hit_tp = highs[j] >= tp
                hit_sl = lows[j] <= sl
                if hit_tp and hit_sl:
                    outcome, ambiguous, days_to = "sl_first", True, j - i
                    outcome_net = "sl_first"
                    break
                if hit_sl:
                    outcome, days_to = "sl_first", j - i
                    outcome_net = "sl_first"
                    break
                if hit_tp:
                    outcome, days_to = "tp_first", j - i
                    outcome_net = "tp_first" if tp_clears_costs else "neither"
                    break

        cur = df.iloc[i]
        sma200 = float(cur.get("SMA_200", np.nan))
        rows.append({
            "ticker":   ticker,
            "date":     str(df.index[i])[:10],
            "sector":   sector,
            "regime":   _regime_for(df.index[i], regimes),
            # production outputs (verbatim)
            "score":     float(cs.score),
            "score90":   float(cs.score) - float(cs.sentiment_score),
            "technical": float(cs.technical_score),
            "momentum":  float(cs.momentum_score),
            "volume":    float(cs.volume_score),
            # FIX EFF1 — cs.pattern_score no longer exists: analysis/score.py
            # removed it in favor of patterns_detected: List[str] (informational
            # only, no longer scored — see docs/PATTERN_REMOVAL_MIGRATION.md). This
            # line previously raised AttributeError on every single walk-forward
            # sample, meaning this script has never actually completed a run.
            # Track pattern presence as a binary flag (any pattern detected at
            # this bar, y/n) so the factor-attribution question survives in a
            # form that still makes sense post-removal, rather than mixing
            # bullish/bearish pattern counts into one ambiguous number.
            "pattern":   float(bool(cs.patterns_detected)),
            "grade":     cs.grade,
            "action":    cs.action,
            "entry":     round(entry, 2),
            "sl":        sl,
            "tp":        tp,
            "rr":        float(cs.risk_reward),
            # baselines (same instant, same data)
            "bl_mom20":   (closes[i] / closes[i - 20] - 1.0) * 100.0 if i >= 20 else np.nan,
            "bl_rsi":     float(cur.get("RSI", np.nan)),
            "bl_sma200d": (entry / sma200 - 1.0) * 100.0 if sma200 and np.isfinite(sma200) and sma200 > 0 else np.nan,
            # outcomes (gross AND net-of-cost — FIX EFF-COST)
            **fwd,
            "outcome":       outcome,
            "outcome_net":   outcome_net,
            "ambiguous":     ambiguous,
            "days_to_outcome": days_to,
            "tp_gain_pct":   round(tp_gain_pct, 3),
            "tp_clears_costs": tp_clears_costs,
        })
    return rows, score_failures


# ─────────────────────────────────────────────────────────────────────────────
# Aggregations
# ─────────────────────────────────────────────────────────────────────────────

def _spearman(a: pd.Series, b: pd.Series) -> float:
    """Spearman rank correlation without scipy."""
    m = a.notna() & b.notna()
    if m.sum() < 30:
        return float("nan")
    return float(a[m].rank().corr(b[m].rank()))


def _decile_table(obs: pd.DataFrame, rank_col: str) -> pd.DataFrame:
    """Decile table of forward returns + TP/SL outcomes for a ranking column."""
    df = obs.dropna(subset=[rank_col]).copy()
    df["decile"] = pd.qcut(df[rank_col].rank(method="first"), 10,
                           labels=list(range(1, 11)))
    g = df.groupby("decile", observed=True)
    out = g.agg(
        n=("ticker", "size"),
        avg_rank_val=(rank_col, "mean"),
        fwd5=("fwd_5d", "mean"),
        fwd20=("fwd_20d", "mean"),
        fwd60=("fwd_60d", "mean"),
        win20=("fwd_20d", lambda s: (s > 0).mean() * 100),
    ).round(2)
    tp = g["outcome"].apply(lambda s: (s == "tp_first").mean() * 100).round(1)
    sl = g["outcome"].apply(lambda s: (s == "sl_first").mean() * 100).round(1)
    amb = g["ambiguous"].mean().mul(100).round(1)
    out["tp_first_%"] = tp
    out["sl_first_%"] = sl
    out["ambiguous_%"] = amb
    return out


def accuracy_report(obs: pd.DataFrame) -> pd.DataFrame:
    """
    FIX EFF-ACC — the honest accuracy table that answers "is the model X% right".

    Reports for each action band (STRONG BUY / BUY / WATCHLIST / HOLD / etc.):
      n                  — sample size in that band
      pct_fwd20_pos      — % of samples where the 20-day forward return > 0 (GROSS)
      pct_fwd20_pos_net  — same, requiring return to beat COST_ROUNDTRIP_PCT
      tp_hit_rate        — % where TP hit before SL within 60 bars (GROSS)
      tp_hit_rate_net    — same, but requires TP margin to clear costs first
      avg_fwd20_gross    — mean 20d return in that band
      avg_fwd20_net      — mean 20d return minus round-trip costs

    Split into TRAIN (older half of sample dates) and HOLDOUT (newer half) so a
    number that only holds in-sample can't hide. If train and holdout disagree
    materially, the "60-70% accuracy" reading is coming from overfit / regime
    luck and any downstream weight-tuning is compounding a fiction.
    """
    if obs.empty:
        return pd.DataFrame()

    # Deterministic train/holdout split by DATE (not row order) — the test
    # sample must not have influenced any part of the model configuration.
    dates_sorted = pd.to_datetime(obs["date"]).sort_values().unique()
    split_date   = dates_sorted[len(dates_sorted) // 2]
    obs = obs.copy()
    obs["split"] = np.where(pd.to_datetime(obs["date"]) < split_date, "train", "holdout")

    def _band_stats(g: pd.DataFrame) -> pd.Series:
        n = len(g)
        return pd.Series({
            "n":                 n,
            "pct_fwd20_pos":     round((g["fwd_20d"]     > 0).mean() * 100, 1),
            "pct_fwd20_pos_net": round((g["fwd_20d_net"] > 0).mean() * 100, 1),
            "tp_hit_rate":       round((g["outcome"]     == "tp_first").mean() * 100, 1),
            "tp_hit_rate_net":   round((g["outcome_net"] == "tp_first").mean() * 100, 1),
            "avg_fwd20_gross":   round(g["fwd_20d"].mean(),     2),
            "avg_fwd20_net":     round(g["fwd_20d_net"].mean(), 2),
        })

    grp = obs.groupby(["split", "action"], observed=True).apply(_band_stats, include_groups=False)
    return grp.reset_index().sort_values(["split", "action"]).set_index(["split", "action"])


def aggregate(obs: pd.DataFrame) -> Dict[str, pd.DataFrame]:
    res: Dict[str, pd.DataFrame] = {}

    res["decile_returns"] = _decile_table(obs, "score90")

    # Action-band outcomes (the labels users actually see)
    act = obs.groupby("action", observed=True).agg(
        n=("ticker", "size"),
        fwd20=("fwd_20d", "mean"),
        fwd60=("fwd_60d", "mean"),
        tp_first=("outcome", lambda s: (s == "tp_first").mean() * 100),
        sl_first=("outcome", lambda s: (s == "sl_first").mean() * 100),
    ).round(2)
    res["action_bands"] = act

    # Factor attribution — rank correlation of each component vs forward returns
    rows = []
    for comp in ["score90", "score", "technical", "momentum", "volume", "pattern"]:
        rows.append({
            "component": comp,
            "spearman_fwd5":  round(_spearman(obs[comp], obs["fwd_5d"]), 4),
            "spearman_fwd20": round(_spearman(obs[comp], obs["fwd_20d"]), 4),
            "spearman_fwd60": round(_spearman(obs[comp], obs["fwd_60d"]), 4),
        })
    res["factor_attribution"] = pd.DataFrame(rows).set_index("component")

    # Baselines — decile-10-minus-decile-1 spread on fwd_20d for each ranking
    rows = []
    for name, col in [("composite_score90", "score90"),
                      ("momentum20_rank", "bl_mom20"),
                      ("rsi_rank", "bl_rsi"),
                      ("sma200_distance_rank", "bl_sma200d")]:
        t = _decile_table(obs, col)
        try:
            spread20 = float(t.loc[10, "fwd20"]) - float(t.loc[1, "fwd20"])
            spread60 = float(t.loc[10, "fwd60"]) - float(t.loc[1, "fwd60"])
        except Exception as e:
            print(f"  decile spread calc failed for ranking '{name}' "
                  f"({type(e).__name__}: {e}) — spread set to NaN")
            spread20 = spread60 = float("nan")
        rows.append({
            "ranking": name,
            "spearman_fwd20": round(_spearman(obs[col], obs["fwd_20d"]), 4),
            "d10_minus_d1_fwd20_pct": round(spread20, 2),
            "d10_minus_d1_fwd60_pct": round(spread60, 2),
        })
    res["baselines"] = pd.DataFrame(rows).set_index("ranking")

    # Sector breakdown — does score rank within sector?
    sec_rows = []
    for sec, g in obs.groupby("sector"):
        if len(g) < 150:
            continue
        sec_rows.append({"sector": sec, "n": len(g),
                         "spearman_fwd20": round(_spearman(g["score90"], g["fwd_20d"]), 4),
                         "avg_fwd20": round(g["fwd_20d"].mean(), 2)})
    res["sector_breakdown"] = (pd.DataFrame(sec_rows).set_index("sector")
                               if sec_rows else pd.DataFrame())

    # Regime breakdown
    reg_rows = []
    for reg, g in obs.groupby("regime"):
        if len(g) < 100:
            continue
        reg_rows.append({"regime": reg, "n": len(g),
                         "spearman_fwd20": round(_spearman(g["score90"], g["fwd_20d"]), 4),
                         "avg_fwd20": round(g["fwd_20d"].mean(), 2)})
    res["regime_breakdown"] = (pd.DataFrame(reg_rows).set_index("regime")
                               if reg_rows else pd.DataFrame())

    return res


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0,
                    help="cap the number of tickers (0 = full universe)")
    ap.add_argument("--workers", type=int, default=10)
    ap.add_argument("--period", default="2y",
                    help="Historical window: 2y (default), 3y, 5y, max. "
                         "Longer windows cover more regimes → disambiguate whether "
                         "any inversion in the score is regime-specific or universal.")
    args = ap.parse_args()

    from data.universe import get_universe, get_sector

    universe = list(get_universe("nifty500"))
    if args.limit:
        universe = universe[: args.limit]

    os.makedirs(OUT_DIR, exist_ok=True)
    t0 = time.time()
    print(f"Universe: {len(universe)} tickers | period={args.period} | "
          f"step={SAMPLE_STEP}d | horizons={HORIZONS} | max_horizon={MAX_HORIZON}d")

    regimes = _vix_regime_series(period=args.period)
    print(f"VIX regime series: {'OK' if regimes is not None else 'UNAVAILABLE (regime=unknown)'}")

    # Fetch + indicator-enrich in parallel (network bound)
    frames: Dict[str, pd.DataFrame] = {}
    prep_failures = 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(_prepare_ticker, t, args.period): t for t in universe}
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
            if done % 25 == 0:
                print(f"  fetched {done}/{len(universe)} "
                      f"({len(frames)} usable) [{time.time()-t0:.0f}s]")
    if prep_failures:
        print(f"  {prep_failures}/{len(universe)} tickers raised an exception during "
              f"prepare/fetch (excluded from frames)")
    if _prepare_ticker_exceptions:
        print(f"  {_prepare_ticker_exceptions}/{len(universe)} tickers raised an exception "
              f"INSIDE _prepare_ticker itself (fetch/indicator error, not just insufficient "
              f"history) — see debug logs for details")

    print(f"Usable tickers: {len(frames)}/{len(universe)} [{time.time()-t0:.0f}s]")

    # Walk-forward scoring (CPU bound, fast)
    all_rows: List[Dict] = []
    total_score_failures = 0
    sector_failures = 0
    for k, (t, df) in enumerate(frames.items(), 1):
        sector = "Other"
        try:
            sector = get_sector(t)
        except Exception:
            sector_failures += 1
        rows, score_failures = _walk_forward(t, df, sector, regimes)
        all_rows.extend(rows)
        total_score_failures += score_failures
        if k % 25 == 0:
            print(f"  scored {k}/{len(frames)} tickers "
                  f"({len(all_rows)} obs) [{time.time()-t0:.0f}s]")
    if sector_failures:
        print(f"  sector lookup failed for {sector_failures}/{len(frames)} tickers "
              f"(defaulted to 'Other')")
    if total_score_failures:
        print(f"  score_dataframe raised an exception {total_score_failures} times "
              f"across all walk-forward samples (those sample points were skipped)")
    if _regime_for_failures:
        print(f"  regime lookup raised an exception {_regime_for_failures} times "
              f"(treated as 'unknown')")

    obs = pd.DataFrame(all_rows)
    if obs.empty:
        print("No observations produced — aborting.")
        return 1

    obs.to_csv(os.path.join(OUT_DIR, "observations.csv"), index=False,
               encoding="utf-8")
    print(f"Observations: {len(obs)} rows from {obs['ticker'].nunique()} tickers")

    aggs = aggregate(obs)
    name_map = {
        "decile_returns":     "decile_returns.csv",
        "action_bands":       "decile_tpsl.csv",
        "factor_attribution": "factor_attribution.csv",
        "baselines":          "baselines.csv",
        "sector_breakdown":   "sector_breakdown.csv",
        "regime_breakdown":   "regime_breakdown.csv",
    }
    for key, fname in name_map.items():
        aggs[key].to_csv(os.path.join(OUT_DIR, fname), encoding="utf-8")

    # FIX EFF-ACC — the honest "60-70%?" table, train/holdout split.
    acc = accuracy_report(obs)
    if not acc.empty:
        acc.to_csv(os.path.join(OUT_DIR, "accuracy_report.csv"), encoding="utf-8")

    # Console summary
    pd.set_option("display.width", 160)
    print("\n=== SCORE-90 DECILES (1=lowest score, 10=highest) ===")
    print(aggs["decile_returns"])
    print("\n=== ACTION BANDS ===")
    print(aggs["action_bands"])
    print("\n=== FACTOR ATTRIBUTION (Spearman vs forward returns) ===")
    print(aggs["factor_attribution"])
    print("\n=== BASELINE COMPARISON ===")
    print(aggs["baselines"])
    print("\n=== REGIME BREAKDOWN ===")
    print(aggs["regime_breakdown"])

    # FIX EFF-ACC — surface the honest accuracy read up front.
    if not acc.empty:
        print(f"\n=== HONEST ACCURACY REPORT (cost floor {COST_ROUNDTRIP_PCT:.2f}% round-trip) ===")
        print("(pct_fwd20_pos_net and tp_hit_rate_net are what a REAL account books.")
        print(" A large gap between 'train' and 'holdout' rows = the number is fragile.)")
        print(acc)

    print(f"\nDone in {time.time()-t0:.0f}s. CSVs in {OUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
