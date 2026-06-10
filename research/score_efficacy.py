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
    price-derived score (technical+momentum+volume+pattern). VIX regime is used
    as a BREAKDOWN label (reconstructed from the historical ^INDIAVIX series),
    not as a score input.
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

OUT_DIR = os.path.join(_ROOT, "research", "output")

# Sampling / horizon parameters
SAMPLE_STEP   = 5      # every 5th trading day (weekly) — independence
MAX_HORIZON   = 60     # longest forward window measured
HORIZONS      = (5, 20, 60)

# Neutral sentiment inputs — sentiment is studied separately, so we hold the
# production scorer's sentiment inputs constant across all observations.
_NEUTRAL_VIX = {"regime": "normal", "vix": None, "allow_buy": True}
_NEUTRAL_SECTOR_RANK = 7


# ─────────────────────────────────────────────────────────────────────────────
# Historical VIX regime labels (breakdown only — not a score input)
# ─────────────────────────────────────────────────────────────────────────────

def _vix_regime_series() -> Optional[pd.Series]:
    """Daily ^INDIAVIX close → regime label, for tagging each sample date."""
    try:
        from data.fetcher import fetch_single
        vdf = fetch_single("^INDIAVIX", period="2y")
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
    except Exception:
        return None


def _regime_for(date, regimes: Optional[pd.Series]) -> str:
    if regimes is None:
        return "unknown"
    try:
        idx = regimes.index.asof(pd.Timestamp(date))
        if pd.isna(idx):
            return "unknown"
        return str(regimes.loc[idx])
    except Exception:
        return "unknown"


# ─────────────────────────────────────────────────────────────────────────────
# Per-ticker walk-forward
# ─────────────────────────────────────────────────────────────────────────────

def _prepare_ticker(ticker: str) -> Optional[pd.DataFrame]:
    """Fetch 2y daily bars and enrich with the production indicator set.

    Indicators are rolling/causal, so computing them once on the full frame and
    then slicing df.iloc[:i+1] is identical to recomputing on each slice — no
    look-ahead is introduced.
    """
    try:
        from data.fetcher import fetch_single
        from utils.indicators import add_all_indicators
        df = fetch_single(ticker, period="2y")
        if df is None or df.empty or len(df) < 280:
            return None
        df = add_all_indicators(df)
        df = df.dropna(subset=["RSI", "ATR"])
        return df if len(df) >= 280 else None
    except Exception:
        return None


def _walk_forward(ticker: str, df: pd.DataFrame, sector: str,
                  regimes: Optional[pd.Series]) -> List[Dict]:
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
    for i in range(start, last, SAMPLE_STEP):
        sub = df.iloc[: i + 1]
        try:
            cs = score_dataframe(sub, ticker, vix_info=_NEUTRAL_VIX,
                                 sector_rank=_NEUTRAL_SECTOR_RANK, sector=sector)
        except Exception:
            continue

        entry = closes[i]
        if entry <= 0 or not np.isfinite(entry):
            continue

        # Forward returns
        fwd = {}
        for h in HORIZONS:
            fwd[f"fwd_{h}d"] = (closes[i + h] / entry - 1.0) * 100.0

        # TP/SL path walk over the next MAX_HORIZON bars
        sl, tp = float(cs.stop_loss), float(cs.target)
        outcome, days_to = "neither", None
        ambiguous = False
        if sl > 0 and tp > entry:
            for j in range(i + 1, i + 1 + MAX_HORIZON):
                hit_tp = highs[j] >= tp
                hit_sl = lows[j] <= sl
                if hit_tp and hit_sl:
                    outcome, ambiguous, days_to = "sl_first", True, j - i
                    break
                if hit_sl:
                    outcome, days_to = "sl_first", j - i
                    break
                if hit_tp:
                    outcome, days_to = "tp_first", j - i
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
            "pattern":   float(cs.pattern_score),
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
            # outcomes
            **fwd,
            "outcome":    outcome,
            "ambiguous":  ambiguous,
            "days_to_outcome": days_to,
        })
    return rows


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
        except Exception:
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
    args = ap.parse_args()

    from data.universe import get_universe, get_sector

    universe = list(get_universe("nifty500"))
    if args.limit:
        universe = universe[: args.limit]

    os.makedirs(OUT_DIR, exist_ok=True)
    t0 = time.time()
    print(f"Universe: {len(universe)} tickers | step={SAMPLE_STEP}d | "
          f"horizons={HORIZONS} | max_horizon={MAX_HORIZON}d")

    regimes = _vix_regime_series()
    print(f"VIX regime series: {'OK' if regimes is not None else 'UNAVAILABLE (regime=unknown)'}")

    # Fetch + indicator-enrich in parallel (network bound)
    frames: Dict[str, pd.DataFrame] = {}
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(_prepare_ticker, t): t for t in universe}
        done = 0
        for f in as_completed(futs):
            t = futs[f]
            try:
                df = f.result()
                if df is not None:
                    frames[t] = df
            except Exception:
                pass
            done += 1
            if done % 25 == 0:
                print(f"  fetched {done}/{len(universe)} "
                      f"({len(frames)} usable) [{time.time()-t0:.0f}s]")

    print(f"Usable tickers: {len(frames)}/{len(universe)} [{time.time()-t0:.0f}s]")

    # Walk-forward scoring (CPU bound, fast)
    all_rows: List[Dict] = []
    for k, (t, df) in enumerate(frames.items(), 1):
        sector = "Other"
        try:
            sector = get_sector(t)
        except Exception:
            pass
        all_rows.extend(_walk_forward(t, df, sector, regimes))
        if k % 25 == 0:
            print(f"  scored {k}/{len(frames)} tickers "
                  f"({len(all_rows)} obs) [{time.time()-t0:.0f}s]")

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
    print(f"\nDone in {time.time()-t0:.0f}s. CSVs in {OUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
