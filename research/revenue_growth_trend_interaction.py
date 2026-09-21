"""
research/revenue_growth_trend_interaction.py — Revenue Growth × Trend Quality
Interaction Study.

The capstone question of the research program: do Revenue Growth and Trend
Quality work better TOGETHER than either works alone — or is Revenue Growth
simply an independent lens?

READ-ONLY research. No production, scoring, screener, picks, thesis or
portfolio changes. Reuses the established infrastructure:
  • Point-in-time Revenue Growth — same 180-day reporting-lag discipline as
    FUNDAMENTAL_QUALITY_REPORT (research/fundamental_quality.py helpers).
  • Trend Quality — the CURRENT production scorer (post pattern-removal),
    via each ticker's weekly research grid in variant_observations.csv.
  • Monthly sampling (annual fundamentals — weekly adds no information).
  • Market regimes from ^NSEI (SMA50/200), VIX regimes from ^INDIAVIX.

Design:
  • Buckets are WITHIN-DATE terciles (cross-sectional), so a cell never just
    reflects "what the market did that month".
  • Outcomes per observation: 6m / 12m forward return, 6m forward volatility
    (annualised), 6m max drawdown from entry, Sharpe-like = fwd6m / vol.
  • Interaction effect (per outcome): observed High-High cell minus the
    additive expectation (rowHigh mean + colHigh mean − grand mean).
    Significance: cluster bootstrap over sample DATES (1,000 resamples) —
    observations within a date are correlated, so dates are the unit.

Run:  py -m research.revenue_growth_trend_interaction [--limit 30]
Outputs:
  research/output/revenue_growth_trend_interaction.csv   (observations)
  research/output/rgti_matrix_<outcome>.csv              (3×3 tables)
  research/output/rgti_interaction.csv                   (effects + bootstrap CI)
  research/output/rgti_by_regime.csv
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from research.score_efficacy import _spearman, _vix_regime_series   # noqa: E402
from research.regime_study import _market_regime_series             # noqa: E402
from research.portfolio_fit_efficacy import _fetch_closes           # noqa: E402
from research.fundamental_quality import (                          # noqa: E402
    _fetch_statements, _metrics_at,
)

OUT_DIR = os.path.join(_ROOT, "research", "output")
OBS_CSV = os.path.join(OUT_DIR, "variant_observations.csv")

SAMPLE_STEP = 21          # monthly
H6, H12     = 126, 252
MIN_XSEC    = 45          # min names with rev_g per date for tercile bucketing
N_BOOT      = 1000

OUTCOMES = ["fwd_6m", "fwd_12m", "vol_6m", "dd_6m", "sharpe_6m"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()

    t0 = time.time()
    if not os.path.exists(OBS_CSV):
        print("variant_observations.csv missing — run `py -m research.score_variants` first.")
        return 1

    tq_obs = pd.read_csv(OBS_CSV)[["ticker", "date", "var_a"]]
    tq_obs["date"] = pd.to_datetime(tq_obs["date"])
    tq_series: Dict[str, pd.Series] = {
        t: g.set_index("date")["var_a"].sort_index()
        for t, g in tq_obs.groupby("ticker")
    }
    tickers = sorted(tq_series)
    if args.limit:
        tickers = tickers[: args.limit]
    print(f"RG × TQ INTERACTION STUDY | {len(tickers)} tickers | monthly")

    stmts = _fetch_statements(tickers, workers=args.workers)
    print(f"Fundamentals: {len(stmts)}/{len(tickers)} [{time.time()-t0:.0f}s]")

    closes = _fetch_closes(tickers, workers=12)
    rets = closes.pct_change()
    didx = closes.index
    print(f"Prices: {closes.shape} [{time.time()-t0:.0f}s]")

    vix_reg = _vix_regime_series(period="5y")
    mkt_reg = _market_regime_series()

    def _reg(series: Optional[pd.Series], t: pd.Timestamp) -> str:
        if series is None:
            return "unknown"
        try:
            i = series.index.asof(t)
            return str(series.loc[i]) if pd.notna(i) else "unknown"
        except Exception:
            return "unknown"

    def _tq_at(tk: str, t: pd.Timestamp) -> Optional[float]:
        s = tq_series.get(tk)
        if s is None or s.empty:
            return None
        try:
            d = s.index.asof(t)
        except Exception:
            return None
        if pd.isna(d) or (t - d).days > 12:
            return None
        return float(s.loc[d])

    start_pos = int(didx.searchsorted(pd.Timestamp("2022-10-01")))
    positions = list(range(start_pos, len(didx) - H12 - 1, SAMPLE_STEP))

    rows: List[Dict] = []
    for pos in positions:
        t = didx[pos]
        mreg, vreg = _reg(mkt_reg, t), _reg(vix_reg, t)
        for tk, s in stmts.items():
            if tk not in closes.columns:
                continue
            c0 = closes[tk].iloc[pos]
            if not np.isfinite(c0) or c0 <= 0:
                continue
            rg = _metrics_at(s, t).get("rev_g")
            tq = _tq_at(tk, t)
            if rg is None or tq is None:
                continue
            c6, c12 = closes[tk].iloc[pos + H6], closes[tk].iloc[pos + H12]
            seg = closes[tk].iloc[pos + 1: pos + 1 + H6]
            fr = rets[tk].iloc[pos + 1: pos + 1 + H6].dropna()
            vol6 = float(fr.std(ddof=1) * np.sqrt(252) * 100) if len(fr) >= 80 else np.nan
            dd6 = float((seg / c0 - 1).min() * 100) if seg.notna().sum() >= 80 else np.nan
            f6 = (c6 / c0 - 1) * 100 if np.isfinite(c6) else np.nan
            rows.append({
                "date": str(t)[:10], "ticker": tk,
                "mkt_regime": mreg, "vix_regime": vreg,
                "rev_g": rg, "tq": tq,
                "fwd_6m": f6,
                "fwd_12m": (c12 / c0 - 1) * 100 if np.isfinite(c12) else np.nan,
                "vol_6m": vol6, "dd_6m": dd6,
                "sharpe_6m": (f6 / vol6) if (np.isfinite(f6) and vol6 and vol6 > 0) else np.nan,
            })

    df = pd.DataFrame(rows)
    if df.empty:
        print("No observations.")
        return 1

    # Within-date terciles (only dates with a wide enough cross-section)
    def _bucket(g: pd.DataFrame) -> pd.DataFrame:
        if len(g) < MIN_XSEC:
            return g.assign(rg_b=np.nan, tq_b=np.nan)
        lab = ["Low", "Mid", "High"]
        g = g.assign(
            rg_b=pd.qcut(g["rev_g"].rank(method="first"), 3, labels=lab),
            tq_b=pd.qcut(g["tq"].rank(method="first"), 3, labels=lab),
        )
        return g

    df = (df.groupby("date", group_keys=False)
            .apply(_bucket, include_groups=False)
            .join(df[["date"]]))
    df = df.dropna(subset=["rg_b", "tq_b"])

    os.makedirs(OUT_DIR, exist_ok=True)
    df.to_csv(os.path.join(OUT_DIR, "revenue_growth_trend_interaction.csv"),
              index=False, encoding="utf-8")
    n_dates = df["date"].nunique()
    print(f"Observations: {len(df)} | bucketed dates: {n_dates} | "
          f"{df['date'].min()} -> {df['date'].max()}")

    # Q1 — independent confirmations on this dataset
    print("\n=== Q1 INDEPENDENT SIGNALS (this dataset) ===")
    for col in ["rev_g", "tq"]:
        print(f"  {col:6s} sp_fwd6 = {_spearman(df[col], df['fwd_6m']):.4f}  "
              f"sp_fwd12 = {_spearman(df[col], df['fwd_12m']):.4f}")

    # Q2/Q5 — 3×3 matrices per outcome
    order = ["Low", "Mid", "High"]
    mats: Dict[str, pd.DataFrame] = {}
    for oc in OUTCOMES:
        m = (df.pivot_table(index="tq_b", columns="rg_b", values=oc,
                            aggfunc="mean", observed=True)
               .reindex(index=order, columns=order).round(2))
        mats[oc] = m
        m.to_csv(os.path.join(OUT_DIR, f"rgti_matrix_{oc}.csv"), encoding="utf-8")
    counts = (df.pivot_table(index="tq_b", columns="rg_b", values="ticker",
                             aggfunc="size", observed=True)
                .reindex(index=order, columns=order))
    counts.to_csv(os.path.join(OUT_DIR, "rgti_matrix_counts.csv"), encoding="utf-8")

    pd.set_option("display.width", 200)
    print("\n=== Q2 COUNTS (rows=TQ tercile, cols=RevGrowth tercile) ===")
    print(counts)
    for oc in OUTCOMES:
        print(f"\n=== {oc} ===")
        print(mats[oc])

    # Q3 — interaction effect + date-cluster bootstrap
    def _interaction(sub: pd.DataFrame, oc: str) -> Optional[float]:
        s = sub.dropna(subset=[oc])
        if s.empty:
            return None
        grand = s[oc].mean()
        hh = s[(s.tq_b == "High") & (s.rg_b == "High")][oc].mean()
        rh = s[s.tq_b == "High"][oc].mean()
        ch = s[s.rg_b == "High"][oc].mean()
        if any(pd.isna(x) for x in (hh, rh, ch, grand)):
            return None
        return float(hh - (rh + ch - grand))

    rng = np.random.default_rng(42)
    dates = df["date"].unique()
    inter_rows = []
    for oc in ["fwd_6m", "fwd_12m", "sharpe_6m"]:
        obs_eff = _interaction(df, oc)
        boots = []
        groups = {d: g for d, g in df.groupby("date")}
        for _ in range(N_BOOT):
            pick = rng.choice(dates, size=len(dates), replace=True)
            bs = pd.concat([groups[d] for d in pick], ignore_index=True)
            e = _interaction(bs, oc)
            if e is not None:
                boots.append(e)
        lo, hi = (np.percentile(boots, [2.5, 97.5]) if boots else (np.nan, np.nan))
        s = df.dropna(subset=[oc])
        inter_rows.append({
            "outcome": oc,
            "grand_mean": round(s[oc].mean(), 2),
            "high_high_observed": round(
                s[(s.tq_b == "High") & (s.rg_b == "High")][oc].mean(), 2),
            "additive_expectation": round(
                s[s.tq_b == "High"][oc].mean() + s[s.rg_b == "High"][oc].mean()
                - s[oc].mean(), 2),
            "interaction": round(obs_eff, 2) if obs_eff is not None else None,
            "boot_ci_lo": round(float(lo), 2), "boot_ci_hi": round(float(hi), 2),
            "significant": bool(lo > 0 or hi < 0) if boots else False,
        })
    inter = pd.DataFrame(inter_rows).set_index("outcome")
    inter.to_csv(os.path.join(OUT_DIR, "rgti_interaction.csv"), encoding="utf-8")
    print("\n=== Q3 INTERACTION (HighHigh vs additive expectation; date-cluster bootstrap 95% CI) ===")
    print(inter)

    # Q4 — regime breakdown of the corner cells + interaction
    reg_rows = []
    df["_vix2"] = np.where(df["vix_regime"].isin(["elevated", "fear", "panic"]),
                           "high_vix", "low_vix")
    for kind, col in [("market", "mkt_regime"), ("vix", "_vix2")]:
        for reg, g in df.groupby(col):
            if len(g) < 400:
                continue
            s = g.dropna(subset=["fwd_6m"])
            cell = lambda tqb, rgb: s[(s.tq_b == tqb) & (s.rg_b == rgb)]["fwd_6m"].mean()
            reg_rows.append({
                "regime_type": kind, "regime": reg, "n": len(g),
                "HH_fwd6": round(cell("High", "High"), 2),
                "HL_fwd6": round(cell("High", "Low"), 2),
                "LH_fwd6": round(cell("Low", "High"), 2),
                "LL_fwd6": round(cell("Low", "Low"), 2),
                "interaction_fwd6": (round(_interaction(g, "fwd_6m"), 2)
                                     if _interaction(g, "fwd_6m") is not None else None),
                "sp_rg_fwd6": round(_spearman(g["rev_g"], g["fwd_6m"]), 4),
                "sp_tq_fwd6": round(_spearman(g["tq"], g["fwd_6m"]), 4),
            })
    by_reg = (pd.DataFrame(reg_rows).set_index(["regime_type", "regime"])
              if reg_rows else pd.DataFrame())
    by_reg.to_csv(os.path.join(OUT_DIR, "rgti_by_regime.csv"), encoding="utf-8")
    print("\n=== Q4 BY REGIME (fwd 6m; corner cells + interaction) ===")
    print(by_reg)

    print(f"\nDone in {time.time()-t0:.0f}s. CSVs in {OUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
