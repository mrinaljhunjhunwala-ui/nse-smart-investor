"""
research/portfolio_fit_efficacy.py — Portfolio Fit Efficacy Study.

Question: if two stocks have similar Trend Quality, does Portfolio Fit help
identify which one belongs in the portfolio?

READ-ONLY: calls the PRODUCTION assess_fit() (analysis/thesis/portfolio_fit)
verbatim — it is pure and deterministic, so the exact production fit logic is
replayed historically with inputs assembled from trailing price data only.
No production code, fit logic, thesis logic, scoring or thresholds modified.

Design (disclosed):
  • Reference book: at each weekly sample date, the synthetic portfolio is the
    TOP-10 Trend-Quality stocks (equal weight) — the book a pure TQ-follower
    would hold. The user's real historical book does not exist as data.
  • Candidates: TQ ranks 11–40 at that date — the "similar trend quality"
    cohort the success question asks about.
  • Fit inputs per candidate (all trailing, no look-ahead):
      avg/max correlation vs the 10 book names (120d daily returns),
      candidate beta vs ^NSEI (252d), candidate vol (60d annualised),
      candidate sector + book sector weights, portfolio beta (mean book beta).
  • Dimensions NOT replayed (disclosed): thesis verdict (needs fundamentals
    history → None; the rule simply doesn't fire) and concentration (constant
    LOW in an equal-weight 10-name book). The study therefore tests the
    correlation / sector / beta / vol dimensions of production fit.
  • Trend-Quality scores come from research/output/variant_observations.csv
    (var_a column == current production score, sentiment-neutral) — run
    `py -m research.score_variants` first if missing.

Outputs:
  research/output/portfolio_fit_observations.csv
  research/output/fit_rating_outcomes.csv      (Q1/Q2: outcomes by fit rating)
  research/output/fit_dimension_attribution.csv (Q3)
  research/output/fit_portfolio_sim.csv        (Q4: Portfolio A vs B)
  research/output/fit_by_regime.csv            (Q5)

Run:  py -m research.portfolio_fit_efficacy [--dates 40]   (pilot: first 40 dates)
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

from research.score_efficacy import _spearman                     # noqa: E402
from analysis.thesis.portfolio_fit import (                        # noqa: E402
    assess_fit, PortfolioFitInputs,
)

OUT_DIR   = os.path.join(_ROOT, "research", "output")
OBS_CSV   = os.path.join(OUT_DIR, "variant_observations.csv")

BOOK_N        = 10     # synthetic book size (top TQ)
CAND_RANKS    = (11, 40)   # candidate cohort by TQ rank
CORR_WIN      = 120    # days for pairwise correlation
BETA_WIN      = 252    # days for beta vs ^NSEI
VOL_WIN       = 60     # days for candidate vol
MAX_H         = 60     # forward horizon


def _fetch_closes(tickers: List[str], workers: int = 12) -> pd.DataFrame:
    """Wide Close-price frame (date × ticker), 5y daily."""
    from data.fetcher import fetch_single

    def one(t):
        try:
            df = fetch_single(t, period="5y")
            if df is None or df.empty:
                return t, None
            s = df["Close"].astype(float)
            s.index = pd.to_datetime(s.index)
            return t, s[~s.index.duplicated(keep="last")]
        except Exception:
            return t, None

    out = {}
    failed = []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for f in as_completed([ex.submit(one, t) for t in tickers]):
            t, s = f.result()
            if s is not None and len(s) > 300:
                out[t] = s
            else:
                failed.append(t)
    if failed:
        print(f"  _fetch_closes: {len(failed)}/{len(tickers)} tickers failed or had "
              f"insufficient history (< 300 rows) and were dropped: {failed[:10]}"
              f"{' ...' if len(failed) > 10 else ''}")
    return pd.DataFrame(out).sort_index()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dates", type=int, default=0, help="cap sample dates (pilot)")
    ap.add_argument("--workers", type=int, default=12)
    args = ap.parse_args()

    t0 = time.time()
    if not os.path.exists(OBS_CSV):
        print("variant_observations.csv missing — run `py -m research.score_variants` first.")
        return 1

    obs = pd.read_csv(OBS_CSV)
    # var_a == current production score (post pattern removal), sentiment-neutral
    obs = obs[["ticker", "date", "mkt_regime", "vix_regime", "var_a"]].rename(
        columns={"var_a": "tq"})
    dates = sorted(obs["date"].unique())
    if args.dates:
        dates = dates[: args.dates]
    tickers = sorted(obs["ticker"].unique())
    print(f"PORTFOLIO FIT STUDY | {len(tickers)} tickers | {len(dates)} sample dates")

    from data.universe import get_sector
    sectors = {t: (get_sector(t) if True else "Other") for t in tickers}

    closes = _fetch_closes(tickers + ["^NSEI"], workers=args.workers)
    if "^NSEI" not in closes.columns:
        print("No ^NSEI data — aborting.")
        return 1
    rets = closes.pct_change()
    print(f"Price matrix: {closes.shape} [{time.time()-t0:.0f}s]")

    score_by_date = {d: g.set_index("ticker")["tq"].to_dict()
                     for d, g in obs.groupby("date")}
    regime_by_date = {d: (g["mkt_regime"].iloc[0], g["vix_regime"].iloc[0])
                      for d, g in obs.groupby("date")}

    rows: List[Dict] = []
    sim_rows: List[Dict] = []
    date_index = closes.index

    for di, d in enumerate(dates):
        ts = pd.Timestamp(d)
        # position of the sample date in the daily index
        pos_arr = date_index.searchsorted(ts, side="right") - 1
        if pos_arr < CORR_WIN or pos_arr + MAX_H + 1 >= len(date_index):
            continue
        pos = int(pos_arr)

        sc = score_by_date.get(d, {})
        ranked = [t for t, _ in sorted(sc.items(), key=lambda kv: -kv[1])
                  if t in closes.columns]
        if len(ranked) < CAND_RANKS[1]:
            continue
        book = ranked[:BOOK_N]
        cands = ranked[CAND_RANKS[0] - 1: CAND_RANKS[1]]

        # Trailing windows (no look-ahead: rows strictly up to and incl. pos)
        w_corr = rets.iloc[pos - CORR_WIN + 1: pos + 1]
        w_beta = rets.iloc[max(0, pos - BETA_WIN + 1): pos + 1]
        w_vol  = rets.iloc[pos - VOL_WIN + 1: pos + 1]
        nifty_b = w_beta["^NSEI"]
        var_n  = float(nifty_b.var())

        def beta_of(t: str) -> Optional[float]:
            r = w_beta[t]
            m = r.notna() & nifty_b.notna()
            if m.sum() < 100 or var_n <= 0:
                return None
            return float(np.cov(r[m], nifty_b[m])[0, 1] / var_n)

        book_betas = [b for b in (beta_of(t) for t in book) if b is not None]
        pf_beta = float(np.mean(book_betas)) if book_betas else None
        sec_w: Dict[str, float] = {}
        for t in book:
            sec_w[sectors.get(t, "Other")] = sec_w.get(sectors.get(t, "Other"), 0.0) + 10.0
        top_sec = max(sec_w, key=sec_w.get)

        bookR = w_corr[book]
        mkt_reg, vix_reg = regime_by_date.get(d, ("unknown", "unknown"))

        for cand in cands:
            cr = w_corr[cand]
            if cr.notna().sum() < 60:
                continue
            cors = bookR.corrwith(cr).dropna()
            if len(cors) < 5:
                continue
            avg_c, max_c = float(cors.mean()), float(cors.max())
            most_like = str(cors.idxmax())
            cvol_r = w_vol[cand].dropna()
            cvol = float(cvol_r.std(ddof=1) * np.sqrt(252) * 100) if len(cvol_r) >= 40 else None
            cbeta = beta_of(cand)

            fit = assess_fit(PortfolioFitInputs(
                candidate_ticker=cand,
                candidate_sector=sectors.get(cand, "Other"),
                candidate_beta=cbeta,
                candidate_vol_pct=cvol,
                candidate_verdict=None,                  # not replayable (disclosed)
                avg_correlation=avg_c, max_correlation=max_c,
                most_correlated_with=most_like,
                n_holdings=BOOK_N, portfolio_beta=pf_beta,
                sector_weights=dict(sec_w), top_sector=top_sec,
                top_sector_pct=sec_w[top_sec],
                concentration_risk="LOW",                # equal-weight book (disclosed)
            ))

            # Forward outcomes from daily closes
            c0 = closes[cand].iloc[pos]
            seg = closes[cand].iloc[pos + 1: pos + 1 + MAX_H]
            if not np.isfinite(c0) or c0 <= 0 or seg.isna().all():
                continue
            c20 = closes[cand].iloc[pos + 20] if pos + 20 < len(date_index) else np.nan
            c60 = closes[cand].iloc[pos + 60] if pos + 60 < len(date_index) else np.nan
            r20 = (c20 / c0 - 1) * 100 if np.isfinite(c20) else np.nan
            r60 = (c60 / c0 - 1) * 100 if np.isfinite(c60) else np.nan
            seg20 = closes[cand].iloc[pos + 1: pos + 21]
            dd20 = float((seg20 / c0 - 1).min() * 100) if seg20.notna().sum() >= 15 else np.nan
            fr = rets[cand].iloc[pos + 1: pos + 21].dropna()
            fvol = float(fr.std(ddof=1) * np.sqrt(252) * 100) if len(fr) >= 15 else np.nan
            sharpe = (r20 / fvol) if (fvol and np.isfinite(fvol) and fvol > 0
                                      and np.isfinite(r20)) else np.nan

            rows.append({
                "date": d, "ticker": cand, "tq": sc[cand],
                "mkt_regime": mkt_reg, "vix_regime": vix_reg,
                "fit_score": fit.fit_score, "fit_rating": fit.fit_rating,
                "avg_corr": round(avg_c, 3), "max_corr": round(max_c, 3),
                "cand_beta": None if cbeta is None else round(cbeta, 3),
                "cand_vol": None if cvol is None else round(cvol, 1),
                "new_sector_pct": round(sec_w.get(sectors.get(cand, "Other"), 0.0)
                                        * (1 - 1 / (BOOK_N + 1)) + 100 / (BOOK_N + 1), 1),
                "fwd_20d": r20, "fwd_60d": r60,
                "fwd_vol_20": fvol, "fwd_dd_20": dd20, "fwd_sharpe_20": sharpe,
            })

        # ── Q4 portfolio simulation step: A = top-10 TQ; B = TQ + fit filter ──
        next_pos = None
        if di + 1 < len(dates):
            np_arr = date_index.searchsorted(pd.Timestamp(dates[di + 1]), side="right") - 1
            next_pos = int(np_arr) if np_arr > pos else None
        if next_pos:
            def period_ret(names: List[str]) -> float:
                p0 = closes[names].iloc[pos]
                p1 = closes[names].iloc[next_pos]
                rr = (p1 / p0 - 1).dropna()
                return float(rr.mean()) if len(rr) else 0.0

            # Portfolio B: walk down TQ ranks, accept names that FIT the book
            # built so far (greedy, production assess_fit, fit_score >= 1)
            b_names: List[str] = [ranked[0]]
            for t in ranked[1:]:
                if len(b_names) >= BOOK_N:
                    break
                bw = w_corr[b_names]
                cr = w_corr[t]
                if cr.notna().sum() < 60:
                    continue
                cors = bw.corrwith(cr).dropna()
                if cors.empty:
                    continue
                swb: Dict[str, float] = {}
                for x in b_names:
                    swb[sectors.get(x, "Other")] = (swb.get(sectors.get(x, "Other"), 0.0)
                                                    + 100.0 / max(len(b_names), 1))
                bb = [b for b in (beta_of(x) for x in b_names) if b is not None]
                f = assess_fit(PortfolioFitInputs(
                    candidate_ticker=t, candidate_sector=sectors.get(t, "Other"),
                    candidate_beta=beta_of(t),
                    avg_correlation=float(cors.mean()), max_correlation=float(cors.max()),
                    n_holdings=len(b_names),
                    portfolio_beta=float(np.mean(bb)) if bb else None,
                    sector_weights=swb,
                    top_sector=max(swb, key=swb.get), top_sector_pct=max(swb.values()),
                    concentration_risk="LOW",
                ))
                if f.fit_score >= 1:
                    b_names.append(t)
            # fill if the filter was too strict (disclosed in report)
            for t in ranked:
                if len(b_names) >= BOOK_N:
                    break
                if t not in b_names:
                    b_names.append(t)

            # diversification: avg pairwise corr of the held names
            def avg_pair_corr(names):
                cm = w_corr[names].corr().values
                iu = np.triu_indices_from(cm, k=1)
                v = cm[iu]
                return float(np.nanmean(v)) if len(v) else np.nan

            sim_rows.append({
                "date": d, "mkt_regime": mkt_reg,
                "ret_A": period_ret(book), "ret_B": period_ret(b_names),
                "paircorr_A": avg_pair_corr(book), "paircorr_B": avg_pair_corr(b_names),
                "overlap": len(set(book) & set(b_names)),
            })

        if (di + 1) % 25 == 0:
            print(f"  {di+1}/{len(dates)} dates ({len(rows)} obs) [{time.time()-t0:.0f}s]")

    df = pd.DataFrame(rows)
    if df.empty:
        print("No observations.")
        return 1
    os.makedirs(OUT_DIR, exist_ok=True)
    df.to_csv(os.path.join(OUT_DIR, "portfolio_fit_observations.csv"),
              index=False, encoding="utf-8")
    print(f"Observations: {len(df)} | dates {df['date'].min()} -> {df['date'].max()}")
    print("fit_rating counts:", df["fit_rating"].value_counts().to_dict())

    # Q1/Q2 — outcomes by fit rating (within the similar-TQ cohort)
    by_rating = df.groupby("fit_rating").agg(
        n=("ticker", "size"), tq=("tq", "mean"),
        fwd20=("fwd_20d", "mean"), fwd60=("fwd_60d", "mean"),
        fwd_vol=("fwd_vol_20", "mean"), fwd_dd=("fwd_dd_20", "mean"),
        sharpe=("fwd_sharpe_20", "mean"),
    ).round(2)
    by_rating.to_csv(os.path.join(OUT_DIR, "fit_rating_outcomes.csv"), encoding="utf-8")

    # Q3 — dimension attribution
    dim_rows = []
    for name, col, sign in [("avg_correlation", "avg_corr", -1),
                            ("candidate_beta", "cand_beta", -1),
                            ("candidate_vol", "cand_vol", -1),
                            ("sector_post_weight", "new_sector_pct", -1),
                            ("fit_score (composite)", "fit_score", +1)]:
        dim_rows.append({
            "dimension": name,
            "sp_fwd20":  round(_spearman(df[col].astype(float), df["fwd_20d"]), 4),
            "sp_fwd_vol": round(_spearman(df[col].astype(float), df["fwd_vol_20"]), 4),
            "sp_fwd_dd": round(_spearman(df[col].astype(float), df["fwd_dd_20"]), 4),
            "sp_sharpe": round(_spearman(df[col].astype(float), df["fwd_sharpe_20"]), 4),
        })
    dims = pd.DataFrame(dim_rows).set_index("dimension")
    dims.to_csv(os.path.join(OUT_DIR, "fit_dimension_attribution.csv"), encoding="utf-8")

    # Q5 — regime breakdown of fit_score vs outcomes
    reg_rows = []
    for kind, col in [("market", "mkt_regime"), ("vix", "vix_regime")]:
        for reg, g in df.groupby(col):
            if len(g) < 300:
                continue
            reg_rows.append({
                "regime_type": kind, "regime": reg, "n": len(g),
                "sp_fit_fwd20": round(_spearman(g["fit_score"].astype(float), g["fwd_20d"]), 4),
                "sp_fit_vol":   round(_spearman(g["fit_score"].astype(float), g["fwd_vol_20"]), 4),
                "sp_fit_sharpe": round(_spearman(g["fit_score"].astype(float), g["fwd_sharpe_20"]), 4),
            })
    regs = (pd.DataFrame(reg_rows).set_index(["regime_type", "regime"])
            if reg_rows else pd.DataFrame())
    regs.to_csv(os.path.join(OUT_DIR, "fit_by_regime.csv"), encoding="utf-8")

    # Q4 — portfolio simulation summary
    sim = pd.DataFrame(sim_rows)
    sim.to_csv(os.path.join(OUT_DIR, "fit_portfolio_sim.csv"), index=False, encoding="utf-8")
    summary = {}
    if not sim.empty:
        for p in ("A", "B"):
            r = sim[f"ret_{p}"]
            eq = (1 + r).cumprod()
            yrs = len(r) / 52.0
            cagr = (eq.iloc[-1] ** (1 / yrs) - 1) * 100 if yrs > 0 and eq.iloc[-1] > 0 else np.nan
            vol = r.std(ddof=1) * np.sqrt(52) * 100
            dd = ((eq / eq.cummax()) - 1).min() * 100
            sh = (r.mean() / r.std(ddof=1)) * np.sqrt(52) if r.std(ddof=1) > 0 else np.nan
            summary[p] = dict(cagr=round(float(cagr), 2), vol=round(float(vol), 2),
                              maxdd=round(float(dd), 2), sharpe=round(float(sh), 2),
                              avg_paircorr=round(float(sim[f"paircorr_{p}"].mean()), 3))
        summary["avg_overlap"] = round(float(sim["overlap"].mean()), 1)

    pd.set_option("display.width", 200)
    print("\n=== Q1/Q2 OUTCOMES BY FIT RATING (similar-TQ cohort) ===")
    print(by_rating)
    print("\n=== Q3 DIMENSION ATTRIBUTION ===")
    print(dims)
    print("\n=== Q5 FIT BY REGIME ===")
    print(regs)
    print("\n=== Q4 PORTFOLIO SIM (A=top-10 TQ, B=TQ+fit filter, weekly) ===")
    print(summary)
    print(f"\nDone in {time.time()-t0:.0f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
