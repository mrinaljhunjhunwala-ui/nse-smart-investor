"""
research/fundamental_quality.py — Fundamental Quality Efficacy Study.

Question: do the platform's fundamental metrics (Revenue growth, EPS growth,
ROE, Debt/Equity) contain predictive information about 6- and 12-month forward
returns — individually, as a composite, and beyond Trend Quality?

READ-ONLY research. Uses the canonical analysis/fundamentals engine's dated
statements; no production changes.

Point-in-time discipline (the crux — fundamentals are NOT naturally
point-in-time):
  • At sample date t, only statements with period_end ≤ t − 180 days are used
    (conservative reporting/audit lag for Indian annual results). Restatement
    risk remains and is disclosed — yfinance serves current statement values.
  • Growth metrics require ≥2 usable annual statements spanning ≥1.5 years, so
    their coverage starts later than ROE/D-E. All metrics are None when not
    computable — never zero-filled.

Sampling: MONTHLY (every 21st trading day), deliberately NOT weekly — annual
fundamentals change ~once a year; weekly sampling would multiply rows with no
new information and inflate apparent significance.

Window: first sample ≥ 2022-10 (first usable FY2022 statements + lag) through
last date − 252 trading days (room for the 12-month forward return).

Trend Quality at each date is taken from research/output/variant_observations.csv
(var_a == current production score) at the nearest weekly date ≤ t.

Outputs:
  research/output/fundamental_quality_observations.csv
  research/output/fq_metric_quintiles_<metric>.csv
  research/output/fq_factor_ranking.csv
  research/output/fq_double_sort.csv
  research/output/fq_by_regime.csv

Run:  py -m research.fundamental_quality [--limit 30]
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from research.score_efficacy import _spearman                       # noqa: E402
from research.portfolio_fit_efficacy import _fetch_closes           # noqa: E402
from research.regime_study import _market_regime_series             # noqa: E402

OUT_DIR = os.path.join(_ROOT, "research", "output")
OBS_CSV = os.path.join(OUT_DIR, "variant_observations.csv")

LAG_DAYS    = 180          # statement usable only after this reporting lag
SAMPLE_STEP = 21           # monthly
H6, H12     = 126, 252     # forward horizons (trading days)
METRICS     = ["roe", "de", "rev_g", "eps_g", "composite"]


# ─────────────────────────────────────────────────────────────────────────────
# Fundamentals: dated statement series per ticker
# ─────────────────────────────────────────────────────────────────────────────

def _fetch_statements(tickers: List[str], workers: int = 6) -> Dict[str, List[Dict]]:
    """Per ticker: chronological list of dicts
    {pe(date), revenue, eps, net_income, equity, debt} from the canonical engine."""
    from analysis.fundamentals.service import default_service
    svc = default_service()

    def one(t: str):
        try:
            cf = svc.get_fundamentals(t)
            if cf is None:
                return t, None
            inc = {s.period.period_end: s for s in cf.income_statements
                   if s.period and s.period.period_end}
            bal = {s.period.period_end: s for s in cf.balance_sheets
                   if s.period and s.period.period_end}
            rows = []
            for pe in sorted(set(inc) | set(bal)):
                i, b = inc.get(pe), bal.get(pe)
                rows.append({
                    "pe": pd.Timestamp(pe),
                    "revenue":    getattr(i, "revenue", None) if i else None,
                    "eps":        (getattr(i, "eps_diluted", None)
                                   or getattr(i, "eps_basic", None)) if i else None,
                    "net_income": getattr(i, "net_income", None) if i else None,
                    "equity":     getattr(b, "total_equity", None) if b else None,
                    "debt":       getattr(b, "total_debt", None) if b else None,
                })
            return t, rows if rows else None
        except Exception:
            return t, None

    out: Dict[str, List[Dict]] = {}
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(one, t) for t in tickers]
        for k, f in enumerate(as_completed(futs), 1):
            t, rows = f.result()
            if rows:
                out[t] = rows
            if k % 25 == 0:
                print(f"  fundamentals {k}/{len(tickers)} ({len(out)} usable)")
    return out


def _growth_cagr(points: List[Tuple[pd.Timestamp, float]]) -> Optional[float]:
    """Annualised growth % from oldest to newest positive values.

    Span ≥ 0.9y — two consecutive annual statements (1.0y apart) qualify as
    YoY growth; longer windows annualise to CAGR. (yfinance's oldest year is
    often field-sparse, so requiring 3 valid points would gut coverage.)"""
    pts = [(d, v) for d, v in points if v is not None and np.isfinite(v)]
    if len(pts) < 2:
        return None
    (d0, v0), (d1, v1) = pts[0], pts[-1]
    span = (d1 - d0).days / 365.25
    if span < 0.9 or v0 <= 0 or v1 <= 0:
        return None
    return float(((v1 / v0) ** (1 / span) - 1) * 100)


def _metrics_at(stmts: List[Dict], t: pd.Timestamp) -> Dict[str, Optional[float]]:
    """Point-in-time metrics at t using statements with pe ≤ t − LAG_DAYS."""
    cutoff = t - pd.Timedelta(days=LAG_DAYS)
    usable = [s for s in stmts if s["pe"] <= cutoff]
    out: Dict[str, Optional[float]] = {"roe": None, "de": None,
                                       "rev_g": None, "eps_g": None}
    if not usable:
        return out
    last = usable[-1]
    prev = usable[-2] if len(usable) >= 2 else None

    ni, eq = last.get("net_income"), last.get("equity")
    if ni is not None and eq is not None:
        eq_avg = eq
        if prev and prev.get("equity"):
            eq_avg = (eq + prev["equity"]) / 2.0
        if eq_avg and eq_avg > 0:
            out["roe"] = float(ni / eq_avg * 100)

    debt = last.get("debt")
    if debt is not None and eq is not None and eq > 0:
        out["de"] = float(debt / eq)

    out["rev_g"] = _growth_cagr([(s["pe"], s.get("revenue")) for s in usable])
    out["eps_g"] = _growth_cagr([(s["pe"], s.get("eps"))     for s in usable])
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

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
    # Per-ticker grids: each ticker's walk-forward sampled its OWN weekly dates,
    # so asof-lookup must be done per ticker, not against a global date union.
    tq_series: Dict[str, pd.Series] = {
        t: g.set_index("date")["var_a"].sort_index()
        for t, g in tq_obs.groupby("ticker")
    }

    from data.universe import get_universe
    tickers = sorted(set(tq_obs["ticker"]))
    if args.limit:
        tickers = tickers[: args.limit]
    print(f"FUNDAMENTAL QUALITY STUDY | {len(tickers)} tickers | lag={LAG_DAYS}d | monthly")

    stmts = _fetch_statements(tickers, workers=args.workers)
    print(f"Fundamentals coverage: {len(stmts)}/{len(tickers)} [{time.time()-t0:.0f}s]")

    closes = _fetch_closes(tickers, workers=12)
    print(f"Price matrix: {closes.shape} [{time.time()-t0:.0f}s]")
    didx = closes.index

    mkt_regimes = _market_regime_series()

    # Monthly sample positions
    start_ts = pd.Timestamp("2022-10-01")
    start_pos = int(didx.searchsorted(start_ts))
    last_pos = len(didx) - H12 - 1
    positions = list(range(start_pos, last_pos, SAMPLE_STEP))
    print(f"Sample dates: {len(positions)} ({didx[positions[0]].date()} -> {didx[positions[-1]].date()})")

    def _tq_at(ticker: str, t: pd.Timestamp) -> Optional[float]:
        s = tq_series.get(ticker)
        if s is None or s.empty:
            return None
        try:
            d = s.index.asof(t)
        except Exception:
            return None
        if pd.isna(d) or (t - d).days > 12:
            return None
        return float(s.loc[d])

    rows: List[Dict] = []
    for pos in positions:
        t = didx[pos]
        reg = "unknown"
        if mkt_regimes is not None:
            try:
                ridx = mkt_regimes.index.asof(t)
                reg = str(mkt_regimes.loc[ridx]) if pd.notna(ridx) else "unknown"
            except Exception:
                pass
        for tk, s in stmts.items():
            if tk not in closes.columns:
                continue
            c0 = closes[tk].iloc[pos]
            if not np.isfinite(c0) or c0 <= 0:
                continue
            m = _metrics_at(s, t)
            if all(v is None for v in m.values()):
                continue
            c6 = closes[tk].iloc[pos + H6]
            c12 = closes[tk].iloc[pos + H12]
            rows.append({
                "date": str(t)[:10], "ticker": tk, "mkt_regime": reg,
                **m,
                "tq": _tq_at(tk, t),
                "fwd_6m":  (c6 / c0 - 1) * 100 if np.isfinite(c6) else np.nan,
                "fwd_12m": (c12 / c0 - 1) * 100 if np.isfinite(c12) else np.nan,
            })

    df = pd.DataFrame(rows)
    if df.empty:
        print("No observations.")
        return 1

    # Composite: mean of available metric ranks (D/E inverted), per date cross-section
    def _xsec_composite(g: pd.DataFrame) -> pd.Series:
        parts = []
        for col, sign in [("roe", 1), ("rev_g", 1), ("eps_g", 1), ("de", -1)]:
            r = g[col].rank(pct=True) * sign
            parts.append(r)
        return pd.concat(parts, axis=1).mean(axis=1, skipna=True)

    df["composite"] = (df.groupby("date", group_keys=False)
                         .apply(_xsec_composite, include_groups=False))

    os.makedirs(OUT_DIR, exist_ok=True)
    df.to_csv(os.path.join(OUT_DIR, "fundamental_quality_observations.csv"),
              index=False, encoding="utf-8")
    print(f"Observations: {len(df)} | coverage roe {df['roe'].notna().mean()*100:.0f}% "
          f"rev_g {df['rev_g'].notna().mean()*100:.0f}% eps_g {df['eps_g'].notna().mean()*100:.0f}% "
          f"de {df['de'].notna().mean()*100:.0f}% tq {df['tq'].notna().mean()*100:.0f}%")

    # Q1 — quintile tables per metric
    SIGN = {"roe": 1, "rev_g": 1, "eps_g": 1, "de": -1, "composite": 1}
    for met in METRICS:
        d = df.dropna(subset=[met, "fwd_6m"]).copy()
        if len(d) < 500:
            continue
        ranked = d[met] * SIGN[met]
        d["q"] = pd.qcut(ranked.rank(method="first"), 5, labels=[1, 2, 3, 4, 5])
        qt = (d.groupby("q", observed=True)
                .agg(n=("ticker", "size"), avg=(met, "mean"),
                     fwd6=("fwd_6m", "mean"), fwd12=("fwd_12m", "mean"))
                .round(2))
        qt.to_csv(os.path.join(OUT_DIR, f"fq_metric_quintiles_{met}.csv"),
                  encoding="utf-8")

    # Q2 — factor ranking (Spearman, better-is-higher orientation)
    rank_rows = []
    for met in METRICS:
        s = df[met] * SIGN[met]
        rank_rows.append({
            "metric": met,
            "sp_fwd6":  round(_spearman(s, df["fwd_6m"]), 4),
            "sp_fwd12": round(_spearman(s, df["fwd_12m"]), 4),
            "coverage_pct": round(df[met].notna().mean() * 100, 1),
        })
    ranking = pd.DataFrame(rank_rows).set_index("metric")
    ranking.to_csv(os.path.join(OUT_DIR, "fq_factor_ranking.csv"), encoding="utf-8")

    # Q3 — double sort: TQ median × composite median (within date cross-sections)
    d3 = df.dropna(subset=["tq", "composite", "fwd_6m"]).copy()
    d3["tq_hi"] = d3.groupby("date")["tq"].transform(lambda s: s > s.median())
    d3["fq_hi"] = d3.groupby("date")["composite"].transform(lambda s: s > s.median())
    cell = (d3.groupby(["tq_hi", "fq_hi"])
              .agg(n=("ticker", "size"),
                   fwd6=("fwd_6m", "mean"), fwd12=("fwd_12m", "mean"))
              .round(2))
    cell.to_csv(os.path.join(OUT_DIR, "fq_double_sort.csv"), encoding="utf-8")

    # Q4 — metric survival by market regime
    reg_rows = []
    for reg, g in df.groupby("mkt_regime"):
        if len(g) < 800:
            continue
        row = {"mkt_regime": reg, "n": len(g)}
        for met in METRICS:
            row[met] = round(_spearman(g[met] * SIGN[met], g["fwd_6m"]), 4)
        reg_rows.append(row)
    by_reg = (pd.DataFrame(reg_rows).set_index("mkt_regime")
              if reg_rows else pd.DataFrame())
    by_reg.to_csv(os.path.join(OUT_DIR, "fq_by_regime.csv"), encoding="utf-8")

    pd.set_option("display.width", 200)
    print("\n=== Q2 FACTOR RANKING (Spearman, oriented better=higher) ===")
    print(ranking)
    print("\n=== Q3 DOUBLE SORT (TQ median x Fundamental composite median) ===")
    print(cell)
    print("\n=== Q4 BY MARKET REGIME (Spearman vs fwd 6m) ===")
    print(by_reg)
    print(f"\nDone in {time.time()-t0:.0f}s. CSVs in {OUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
