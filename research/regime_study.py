"""
research/regime_study.py — 5-Year Regime Study of the production score.

READ-ONLY: replays analysis/score.py over ~5 years of daily history. Does NOT
alter weights, thresholds, grades, actions, or create a new score. The goal is
understanding what the current score actually measures — not optimization.

Questions answered (agreed spec):
  Q1. Does predictive power vary by VIX regime?
  Q2. Does it vary by market regime (bull / bear / sideways, from ^NSEI)?
  Q3. Is the score measuring future return, trend quality, risk, or
      risk-adjusted return?  (correlates score vs four distinct outcomes)
  Q4. Which component performs best in each regime?
  Q5. Is there evidence of a trend-following edge, a mean-reversion edge,
      or neither?  (momentum vs 5-day-reversal baselines, per regime)

Market-regime labels (causal, from ^NSEI daily):
  bull     : Close > SMA200  and  SMA50 > SMA200
  bear     : Close < SMA200  and  SMA50 < SMA200
  sideways : everything else

Extra per-observation outcomes beyond the efficacy study:
  fwd_vol_20      : annualised stdev (%) of next 20 daily returns  → risk
  fwd_sharpe_20   : fwd_20d return / fwd_vol_20                     → risk-adj
  trend_persist_20: share of next 20 days with Close above SMA_20   → trend quality

Run (from repo root; ~4-6 min, network for ~220 tickers × 5y):
    py -m research.regime_study
    py -m research.regime_study --limit 30   # pipeline check

Outputs:
    research/output/regime_observations.csv
    research/output/regime_vix.csv          (Q1)
    research/output/regime_market.csv       (Q2)
    research/output/what_score_measures.csv (Q3)
    research/output/component_by_regime.csv (Q4)
    research/output/edge_by_regime.csv      (Q5)
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

from research.score_efficacy import (          # noqa: E402 — shared harness
    _prepare_ticker, _vix_regime_series, _regime_for, _spearman,
    _NEUTRAL_VIX, _NEUTRAL_SECTOR_RANK,
)

OUT_DIR = os.path.join(_ROOT, "research", "output")

PERIOD       = "5y"
SAMPLE_STEP  = 5
MAX_HORIZON  = 60
HORIZONS     = (5, 20, 60)


# ─────────────────────────────────────────────────────────────────────────────
# Market regime labels from ^NSEI (causal)
# ─────────────────────────────────────────────────────────────────────────────

def _market_regime_series() -> Optional[pd.Series]:
    try:
        from data.fetcher import fetch_single
        ndf = fetch_single("^NSEI", period=PERIOD)
        if ndf is None or ndf.empty:
            return None
        c      = ndf["Close"].astype(float)
        sma50  = c.rolling(50).mean()
        sma200 = c.rolling(200).mean()
        lab = pd.Series("sideways", index=c.index)
        lab[(c > sma200) & (sma50 > sma200)] = "bull"
        lab[(c < sma200) & (sma50 < sma200)] = "bear"
        lab[sma200.isna()] = "unknown"
        return lab
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Walk-forward with extended outcomes
# ─────────────────────────────────────────────────────────────────────────────

def _walk_forward_5y(ticker: str, df: pd.DataFrame, sector: str,
                     vix_regimes: Optional[pd.Series],
                     mkt_regimes: Optional[pd.Series]) -> List[Dict]:
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
    start = max(start, 65)
    last  = n - MAX_HORIZON - 1

    # Daily simple returns for forward-vol windows
    rets = np.empty(n)
    rets[0] = np.nan
    rets[1:] = closes[1:] / closes[:-1] - 1.0

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

        fwd = {f"fwd_{h}d": (closes[i + h] / entry - 1.0) * 100.0 for h in HORIZONS}

        # Risk: annualised stdev of the next 20 daily returns (%)
        w = rets[i + 1: i + 21]
        vol20 = float(np.nanstd(w, ddof=1) * np.sqrt(252) * 100) if len(w) == 20 else np.nan
        # Risk-adjusted: 20d return per unit of that vol (crude forward Sharpe)
        sharpe20 = fwd["fwd_20d"] / vol20 if vol20 and np.isfinite(vol20) and vol20 > 0 else np.nan
        # Trend quality: share of next 20 days the stock holds above its SMA20
        seg_c, seg_s = closes[i + 1: i + 21], sma20[i + 1: i + 21]
        ok = np.isfinite(seg_s)
        persist = float(np.mean(seg_c[ok] > seg_s[ok]) * 100) if ok.sum() >= 15 else np.nan

        date = df.index[i]
        rows.append({
            "ticker": ticker,
            "date":   str(date)[:10],
            "sector": sector,
            "vix_regime": _regime_for(date, vix_regimes),
            "mkt_regime": _regime_for(date, mkt_regimes),
            "score":     float(cs.score),
            "score90":   float(cs.score) - float(cs.sentiment_score),
            "technical": float(cs.technical_score),
            "momentum":  float(cs.momentum_score),
            "volume":    float(cs.volume_score),
            "pattern":   float(cs.pattern_score),
            "action":    cs.action,
            # baselines
            "bl_mom20": (closes[i] / closes[i - 20] - 1.0) * 100.0 if i >= 20 else np.nan,
            "bl_rev5":  -((closes[i] / closes[i - 5] - 1.0) * 100.0) if i >= 5 else np.nan,
            # outcomes
            **fwd,
            "fwd_vol_20": vol20,
            "fwd_sharpe_20": sharpe20,
            "trend_persist_20": persist,
        })
    return rows


# ─────────────────────────────────────────────────────────────────────────────
# Aggregations — one table per study question
# ─────────────────────────────────────────────────────────────────────────────

def aggregate(obs: pd.DataFrame) -> Dict[str, pd.DataFrame]:
    res: Dict[str, pd.DataFrame] = {}

    def _per_regime(col: str) -> pd.DataFrame:
        rows = []
        for reg, g in obs.groupby(col):
            if len(g) < 200:
                continue
            rows.append({
                col: reg, "n": len(g),
                "sp_score_fwd5":  round(_spearman(g["score90"], g["fwd_5d"]), 4),
                "sp_score_fwd20": round(_spearman(g["score90"], g["fwd_20d"]), 4),
                "sp_score_fwd60": round(_spearman(g["score90"], g["fwd_60d"]), 4),
                "avg_fwd20": round(g["fwd_20d"].mean(), 2),
            })
        return pd.DataFrame(rows).set_index(col) if rows else pd.DataFrame()

    res["regime_vix"]    = _per_regime("vix_regime")     # Q1
    res["regime_market"] = _per_regime("mkt_regime")     # Q2

    # Q3 — what is the score measuring?
    rows = []
    for name, col in [("future_return_20d", "fwd_20d"),
                      ("future_return_60d", "fwd_60d"),
                      ("trend_quality_20d", "trend_persist_20"),
                      ("future_risk_vol20", "fwd_vol_20"),
                      ("risk_adjusted_sharpe20", "fwd_sharpe_20")]:
        rows.append({"outcome": name,
                     "spearman_vs_score90": round(_spearman(obs["score90"], obs[col]), 4)})
    res["what_score_measures"] = pd.DataFrame(rows).set_index("outcome")

    # Q4 — component × market regime (Spearman vs fwd_20d)
    comp_rows = []
    for reg, g in obs.groupby("mkt_regime"):
        if len(g) < 200:
            continue
        row = {"mkt_regime": reg, "n": len(g)}
        for comp in ["technical", "momentum", "volume", "pattern", "score90"]:
            row[comp] = round(_spearman(g[comp], g["fwd_20d"]), 4)
        comp_rows.append(row)
    res["component_by_regime"] = (pd.DataFrame(comp_rows).set_index("mkt_regime")
                                  if comp_rows else pd.DataFrame())

    # Q5 — trend vs reversal edge per market regime
    edge_rows = []
    for reg, g in obs.groupby("mkt_regime"):
        if len(g) < 200:
            continue
        edge_rows.append({
            "mkt_regime": reg, "n": len(g),
            "trend_edge_mom20":  round(_spearman(g["bl_mom20"], g["fwd_20d"]), 4),
            "reversal_edge_rev5": round(_spearman(g["bl_rev5"], g["fwd_20d"]), 4),
            "score_edge":         round(_spearman(g["score90"], g["fwd_20d"]), 4),
        })
    res["edge_by_regime"] = (pd.DataFrame(edge_rows).set_index("mkt_regime")
                             if edge_rows else pd.DataFrame())

    return res


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=10)
    args = ap.parse_args()

    from data.universe import get_universe, get_sector

    universe = list(get_universe("nifty500"))
    if args.limit:
        universe = universe[: args.limit]

    os.makedirs(OUT_DIR, exist_ok=True)
    t0 = time.time()
    print(f"5-YEAR REGIME STUDY | universe={len(universe)} | period={PERIOD} | "
          f"step={SAMPLE_STEP}d")

    vix_regimes = _vix_regime_series(period=PERIOD)
    mkt_regimes = _market_regime_series()
    print(f"VIX regimes: {'OK' if vix_regimes is not None else 'MISSING'} | "
          f"Market regimes (^NSEI): {'OK' if mkt_regimes is not None else 'MISSING'}")
    if mkt_regimes is not None:
        print("Market regime day-counts:",
              mkt_regimes.value_counts().to_dict())

    frames: Dict[str, pd.DataFrame] = {}
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
                pass
            done += 1
            if done % 50 == 0:
                print(f"  fetched {done}/{len(universe)} "
                      f"({len(frames)} usable) [{time.time()-t0:.0f}s]")

    print(f"Usable tickers: {len(frames)}/{len(universe)} [{time.time()-t0:.0f}s]")

    all_rows: List[Dict] = []
    for k, (t, df) in enumerate(frames.items(), 1):
        sector = "Other"
        try:
            sector = get_sector(t)
        except Exception:
            pass
        all_rows.extend(_walk_forward_5y(t, df, sector, vix_regimes, mkt_regimes))
        if k % 50 == 0:
            print(f"  scored {k}/{len(frames)} ({len(all_rows)} obs) "
                  f"[{time.time()-t0:.0f}s]")

    obs = pd.DataFrame(all_rows)
    if obs.empty:
        print("No observations — aborting.")
        return 1

    obs.to_csv(os.path.join(OUT_DIR, "regime_observations.csv"),
               index=False, encoding="utf-8")
    print(f"Observations: {len(obs)} from {obs['ticker'].nunique()} tickers | "
          f"dates {obs['date'].min()} -> {obs['date'].max()}")

    aggs = aggregate(obs)
    for key, df_out in aggs.items():
        df_out.to_csv(os.path.join(OUT_DIR, f"{key}.csv"), encoding="utf-8")

    pd.set_option("display.width", 160)
    print("\n=== Q1. VIX REGIME ===");        print(aggs["regime_vix"])
    print("\n=== Q2. MARKET REGIME ===");     print(aggs["regime_market"])
    print("\n=== Q3. WHAT THE SCORE MEASURES ==="); print(aggs["what_score_measures"])
    print("\n=== Q4. COMPONENT x REGIME (Spearman vs fwd20) ===")
    print(aggs["component_by_regime"])
    print("\n=== Q5. TREND vs REVERSAL EDGE BY REGIME ===")
    print(aggs["edge_by_regime"])
    print(f"\nDone in {time.time()-t0:.0f}s. CSVs in {OUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
