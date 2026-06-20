"""
research/revenue_growth_discovery.py — Revenue Growth Discovery Impact Audit.

Quantifies, BEFORE any screener change, what a Revenue-Growth column + filter
would actually do to discovery: coverage (overall / sector / cap bucket),
stocks remaining at each filter level, sector & cap concentration, the
missing-data-vs-negative-growth distinction, and interaction with Trend Quality.

Research only — no UI or screener changes.

Inputs:
  • Current Revenue CAGR per ticker via the canonical fundamentals engine
    (exactly what the screener column would show).
  • Trend Quality = each ticker's most recent production score from
    research/output/variant_observations.csv.
  • Market-cap proxy = last close × latest shares_diluted (statement data) —
    free-data approximation, used only for bucketing (Large = top 50 by proxy,
    Mid = next 100, Small = rest), disclosed.

Run:  py -m research.revenue_growth_discovery
Output: research/output/rg_discovery.csv + console tables for the audit doc.
"""
from __future__ import annotations

import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
import pandas as pd

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

OUT_DIR = os.path.join(_ROOT, "research", "output")
OBS_CSV = os.path.join(OUT_DIR, "variant_observations.csv")

THRESHOLDS = [0, 5, 10, 15, 20]


def main() -> int:
    t0 = time.time()
    from data.universe import get_universe, get_sector
    from analysis.fundamentals.service import default_service
    from analysis.fundamentals.analytics import revenue_cagr
    from data.fetcher import fetch_single

    universe = list(get_universe("nifty500"))
    svc = default_service()

    def one(t: str):
        rg, conf, shares = None, "", None
        err_fund, err_px = None, None
        try:
            cf = svc.get_fundamentals(t)
            if cf is not None:
                r = revenue_cagr(cf, years=5)
                if getattr(r, "available", False) and r.value is not None:
                    rg, conf = float(r.value), str(r.confidence)
                for s in cf.income_statements:
                    if getattr(s, "shares_diluted", None):
                        shares = float(s.shares_diluted)
                        break
        except Exception as e:
            err_fund = f"{type(e).__name__}: {e}"
        px = None
        try:
            df = fetch_single(t, period="1m")
            if df is not None and not df.empty:
                px = float(df["Close"].iloc[-1])
        except Exception as e:
            err_px = f"{type(e).__name__}: {e}"
        return t, rg, conf, shares, px, err_fund, err_px

    rows = []
    fund_failures, px_failures = [], []
    with ThreadPoolExecutor(max_workers=8) as ex:
        futs = [ex.submit(one, t) for t in universe]
        for k, f in enumerate(as_completed(futs), 1):
            t, rg, conf, shares, px, err_fund, err_px = f.result()
            if err_fund:
                fund_failures.append((t, err_fund))
            if err_px:
                px_failures.append((t, err_px))
            rows.append({"ticker": t, "rev_g": rg, "conf": conf,
                         "sector": get_sector(t),
                         "mcap": (px * shares) if (px and shares) else None})
            if k % 40 == 0:
                print(f"  {k}/{len(universe)} [{time.time()-t0:.0f}s]")
    if fund_failures:
        print(f"  fundamentals fetch raised an exception for {len(fund_failures)}/{len(universe)} "
              f"tickers (rev_g left None) — first 10: "
              f"{', '.join(f'{t} [{e}]' for t, e in fund_failures[:10])}")
    if px_failures:
        print(f"  price fetch raised an exception for {len(px_failures)}/{len(universe)} "
              f"tickers (mcap left None) — first 10: "
              f"{', '.join(f'{t} [{e}]' for t, e in px_failures[:10])}")

    df = pd.DataFrame(rows)

    # Trend Quality: latest production score per ticker from the research grid
    if os.path.exists(OBS_CSV):
        tq = pd.read_csv(OBS_CSV)[["ticker", "date", "var_a"]]
        tq = (tq.sort_values("date").groupby("ticker").tail(1)
                .rename(columns={"var_a": "tq"})[["ticker", "tq"]])
        df = df.merge(tq, on="ticker", how="left")
    else:
        df["tq"] = np.nan

    # Cap buckets by mcap-proxy rank (disclosed approximation)
    df["cap_rank"] = df["mcap"].rank(ascending=False)
    df["cap_bucket"] = np.where(df["cap_rank"] <= 50, "Large",
                       np.where(df["cap_rank"] <= 150, "Mid",
                       np.where(df["mcap"].notna(), "Small", "Unknown")))

    os.makedirs(OUT_DIR, exist_ok=True)
    df.to_csv(os.path.join(OUT_DIR, "rg_discovery.csv"), index=False, encoding="utf-8")

    pd.set_option("display.width", 200)
    n = len(df)
    cov = df["rev_g"].notna()
    print(f"\nUniverse: {n} | Revenue CAGR available: {cov.sum()} ({cov.mean()*100:.1f}%)")
    print("Confidence mix:", df.loc[cov, "conf"].value_counts().to_dict())

    print("\n=== Q1 COVERAGE BY SECTOR ===")
    sec = df.groupby("sector").agg(n=("ticker", "size"),
                                   with_rg=("rev_g", lambda s: s.notna().sum()))
    sec["pct"] = (sec["with_rg"] / sec["n"] * 100).round(0)
    print(sec.sort_values("pct"))

    print("\n=== Q1 COVERAGE BY CAP BUCKET (mcap proxy) ===")
    cap = df.groupby("cap_bucket").agg(n=("ticker", "size"),
                                       with_rg=("rev_g", lambda s: s.notna().sum()))
    cap["pct"] = (cap["with_rg"] / cap["n"] * 100).round(0)
    print(cap)

    print("\n=== Q2/Q4 FILTER IMPACT ===")
    tq_top_decile_cut = df["tq"].quantile(0.9)
    base_top = ((df["tq"] >= tq_top_decile_cut).sum())
    out = []
    for th in THRESHOLDS:
        kept = df[df["rev_g"] > th]
        secw = kept["sector"].value_counts(normalize=True) * 100
        capw = kept["cap_bucket"].value_counts(normalize=True) * 100
        hhi = float(((secw) ** 2).sum())
        top_kept = (kept["tq"] >= tq_top_decile_cut).sum()
        out.append({
            "filter": f">{th}%", "kept": len(kept),
            "kept_pct_of_universe": round(len(kept) / n * 100, 1),
            "avg_tq": round(kept["tq"].mean(), 1),
            "tq_top_decile_retained": f"{top_kept}/{base_top}",
            "top_sector": f"{secw.index[0]} {secw.iloc[0]:.0f}%" if len(secw) else "—",
            "sector_hhi": round(hhi, 0),
            "large_pct": round(capw.get("Large", 0), 0),
            "small_pct": round(capw.get("Small", 0), 0),
        })
    print(pd.DataFrame(out).to_string(index=False))

    print("\n=== Q3 MISSING vs NEGATIVE ===")
    print(f"missing (no data): {(~cov).sum()} ({(~cov).mean()*100:.1f}%)")
    print(f"negative growth:   {(df['rev_g'] <= 0).sum()} "
          f"({(df['rev_g'] <= 0).mean()*100:.1f}%)")
    print(f"positive growth:   {(df['rev_g'] > 0).sum()}")
    miss_by_sec = df[~cov]["sector"].value_counts().head(6).to_dict()
    print("missing concentrated in:", miss_by_sec)
    print("avg TQ of missing-data stocks:", round(df.loc[~cov, "tq"].mean(), 1),
          "| universe avg:", round(df["tq"].mean(), 1))

    print(f"\nDone in {time.time()-t0:.0f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
