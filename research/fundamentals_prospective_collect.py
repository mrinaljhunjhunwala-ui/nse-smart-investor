"""
research/fundamentals_prospective_collect.py — Option A of the fundamentals
scoring study: prospective (forward-only) tracking, run daily via GitHub
Actions. See research/fundamentals_historical_variant.py's module docstring
for why this exists alongside Option B (historical reconstruction can't
cover qualitative flags at all, and is only an approximation for
quantitative fundamentals; this script has neither limitation, at the cost
of taking real calendar weeks to accumulate a usable sample).

WHAT THIS DOES EACH RUN:
  1. QUANTITATIVE + TECHNICAL, full universe: for every ticker, fetch
     TODAY's real fundamentals (no reconstruction needed — .info's ratios
     ARE today's ratios, this is exactly what they're valid for) through
     the same production assess_valuation() pipeline used in Analyze Stock,
     plus today's technical CompositeScore (for later comparison — does
     blending help vs. technical alone?). Persisted via
     analysis/fundamentals/prospective_tracker.py.
  2. QUALITATIVE FLAGS, focus subset only: refresh_all_flags() hits THREE
     separate live sources per ticker (NSE corp-info JSON, Google News RSS,
     NSE's own RSS feeds) — running that for the full ~500-745-ticker
     universe daily would be a lot of load against WAF-prone endpoints for
     questionable benefit. Scoped instead to the day's top N tickers by
     technical score (a natural, self-contained "what's actually being
     considered" focus list — no external dependency on the dashboard's
     Top Picks cache). Tickers outside this subset get qual_score=None
     (missing, not zero — do not treat as neutral).
  3. EVALUATE DUE SNAPSHOTS: for previously-recorded snapshots old enough
     that fwd_20d/fwd_60d/fwd_120d could now be computed, fetch each
     ticker's price history and locate the EXACT trading day at
     snapshot_index + horizon (not a calendar-day approximation), fill in
     the real forward return. Rows not old enough yet in real trading days
     (despite clearing the calendar-day pre-filter) are simply left for a
     later run.

REQUIRES DATABASE_URL to be set as a GitHub Actions repository secret
(same Neon instance already used for paper trades) — see
prospective_tracker.py's module docstring. Without it, every run starts
from an empty local SQLite file and nothing ever accumulates.

Run:
    py -m research.fundamentals_prospective_collect               # full universe
    py -m research.fundamentals_prospective_collect --limit 30    # pipeline check
    py -m research.fundamentals_prospective_collect --qual-top-n 40
"""
from __future__ import annotations

import argparse
import datetime as dt
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

from analysis.fundamentals.service import default_service           # noqa: E402
from analysis.fundamentals.analytics import compute_all              # noqa: E402
from analysis.fundamentals.valuation import build_valuation_context  # noqa: E402
from analysis.fundamentals.valuation_decision import assess_valuation  # noqa: E402
from analysis.sector_classification import classify_sector           # noqa: E402
from analysis.score import score_stock                               # noqa: E402
from analysis.qualitative_flags import refresh_all_flags, summarize_flags  # noqa: E402
from analysis.fundamentals import prospective_tracker as pt          # noqa: E402
from research.fundamentals_historical_variant import POSTURE_SCORE   # noqa: E402 — single source of truth for the posture->score policy map
from trade_store import kv_get, kv_set                               # noqa: E402

OUT_DIR = os.path.join(_ROOT, "research", "output")

HORIZONS = {"fwd_20d": 20, "fwd_60d": 60, "fwd_120d": 120}
# Generous calendar-day pre-filters (trading days are ~5/7 of calendar days,
# plus NSE holidays) — the real trading-day offset is still checked exactly
# in _evaluate_one below; this is only a cheap "don't even bother querying
# yet" filter.
MIN_AGE_CALENDAR_DAYS = {"fwd_20d": 30, "fwd_60d": 90, "fwd_120d": 175}


# ─────────────────────────────────────────────────────────────────────────────
# Step 1+2: today's snapshot
# ─────────────────────────────────────────────────────────────────────────────

def _snapshot_one(ticker: str) -> Optional[Dict]:
    quant_score = posture = None
    try:
        cf = default_service().get_fundamentals(ticker)
        if cf.income_statements and cf.balance_sheets:
            sector_profile = classify_sector(None)  # neutral — see historical-variant docstring caveat
            analytics = compute_all(cf)
            vctx = build_valuation_context(cf, sector_profile)
            assessment = assess_valuation(vctx, analytics, sector_profile, cf=cf)
            posture = assessment.posture
            quant_score = POSTURE_SCORE.get(posture)
    except Exception:
        pass

    technical_score = price = None
    try:
        cs = score_stock(ticker)
        technical_score = float(cs.score)
        price = float(cs.price)
    except Exception:
        pass

    if price is None or price <= 0:
        return None  # no usable price -> can't compute forward returns later, skip entirely

    return {"ticker": ticker, "price": price, "quant_score": quant_score,
            "posture": posture, "technical_score": technical_score}


def _qualitative_one(ticker: str) -> Dict:
    try:
        flags = refresh_all_flags(ticker, kv_get, kv_set)
        counts = summarize_flags(flags)
        g, r, a = counts["green"], counts["red"], counts["amber"]
        # Labelled policy mapping, same spirit as this codebase's other
        # conviction/reweight multipliers: NOT itself backtested (that's
        # what this whole study is for). Neutral amber contributes 0.
        qual_score = max(0.0, min(100.0, 50.0 + 15.0 * g - 15.0 * r))
        return {"qual_score": qual_score, "qual_green": g, "qual_red": r, "qual_amber": a}
    except Exception:
        return {"qual_score": None, "qual_green": None, "qual_red": None, "qual_amber": None}


def collect(universe: List[str], qual_top_n: int, workers: int) -> None:
    t0 = time.time()
    today = dt.date.today()
    print(f"[collect] snapshotting {len(universe)} tickers as of {today}")

    base_rows: Dict[str, Dict] = {}
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(_snapshot_one, t): t for t in universe}
        done = 0
        for f in as_completed(futs):
            t = futs[f]
            try:
                r = f.result()
                if r is not None:
                    base_rows[t] = r
            except Exception:
                pass
            done += 1
            if done % 100 == 0:
                print(f"  quant+technical: {done}/{len(universe)} [{time.time()-t0:.0f}s]")

    print(f"[collect] usable quant+technical rows: {len(base_rows)}/{len(universe)}")

    # Focus subset for qualitative flags: top N by technical score, computed
    # from THIS run's own data (self-contained, no dashboard dependency).
    ranked = sorted(base_rows.items(),
                     key=lambda kv: (kv[1]["technical_score"] or -1), reverse=True)
    focus = [t for t, _ in ranked[:qual_top_n]]
    print(f"[collect] qualitative-flags focus subset: {len(focus)} tickers "
          f"(top {qual_top_n} by technical score)")

    qual_rows: Dict[str, Dict] = {}
    with ThreadPoolExecutor(max_workers=min(workers, 5)) as ex:
        # Lower concurrency here on purpose — refresh_all_flags hits
        # WAF-prone NSE endpoints; the quant/technical pass above is Yahoo-
        # only and tolerates more parallelism fine.
        futs = {ex.submit(_qualitative_one, t): t for t in focus}
        for f in as_completed(futs):
            t = futs[f]
            try:
                qual_rows[t] = f.result()
            except Exception:
                qual_rows[t] = {"qual_score": None, "qual_green": None,
                                "qual_red": None, "qual_amber": None}

    recorded = 0
    for ticker, row in base_rows.items():
        q = qual_rows.get(ticker, {"qual_score": None, "qual_green": None,
                                   "qual_red": None, "qual_amber": None})
        ok = pt.record_snapshot(
            ticker, today, row["price"], row["quant_score"], row["posture"],
            q["qual_score"], q["qual_green"], q["qual_red"], q["qual_amber"],
            row["technical_score"])
        recorded += 1 if ok else 0

    print(f"[collect] recorded {recorded}/{len(base_rows)} snapshots "
          f"[{time.time()-t0:.0f}s]. Table now has {pt.row_count()} rows total.")


# ─────────────────────────────────────────────────────────────────────────────
# Step 3: evaluate snapshots that are now old enough
# ─────────────────────────────────────────────────────────────────────────────

def _evaluate_horizon(horizon_col: str, horizon_days: int) -> int:
    from data.fetcher import fetch_single

    due = pt.fetch_due_for_evaluation(horizon_col, MIN_AGE_CALENDAR_DAYS[horizon_col])
    if due.empty:
        print(f"[evaluate:{horizon_col}] nothing due")
        return 0

    print(f"[evaluate:{horizon_col}] {len(due)} snapshot(s) old enough to check")
    filled = 0
    for _, r in due.iterrows():
        ticker = r["ticker"]
        try:
            price_df = fetch_single(ticker, period="1y")
            if price_df is None or price_df.empty:
                continue
            price_df = price_df.sort_index()
            snap_date = pd.Timestamp(r["snapshot_date"])
            pos = price_df.index.searchsorted(snap_date)
            j = pos + horizon_days
            if j >= len(price_df):
                continue  # not enough real trading days yet — retry next run
            entry = float(r["price_at_snapshot"])
            fwd   = float(price_df["Close"].iloc[j])
            if entry <= 0:
                continue
            ret = (fwd / entry - 1.0) * 100.0
            pt.update_forward_return(int(r["id"]), horizon_col, ret)
            filled += 1
        except Exception:
            continue
    print(f"[evaluate:{horizon_col}] filled {filled}/{len(due)}")
    return filled


def evaluate_all() -> None:
    for col, days in HORIZONS.items():
        _evaluate_horizon(col, days)


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--qual-top-n", type=int, default=40)
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--skip-collect", action="store_true",
                    help="only run the evaluation pass (useful for a separate schedule)")
    ap.add_argument("--skip-evaluate", action="store_true")
    args = ap.parse_args()

    from data.universe import get_universe
    universe = list(get_universe("nifty500"))
    if args.limit:
        universe = universe[: args.limit]

    os.makedirs(OUT_DIR, exist_ok=True)

    if not args.skip_collect:
        collect(universe, args.qual_top_n, args.workers)
    if not args.skip_evaluate:
        evaluate_all()

    export = pt.fetch_all()
    export.to_csv(os.path.join(OUT_DIR, "fundamentals_prospective_export.csv"),
                  index=False, encoding="utf-8")
    n_eval = export[["fwd_20d", "fwd_60d", "fwd_120d"]].notna().any(axis=1).sum()
    print(f"\nTable total: {len(export)} rows | with >=1 horizon evaluated: {n_eval}")
    if n_eval >= 50:
        for col in ("fwd_20d", "fwd_60d", "fwd_120d"):
            sub = export.dropna(subset=["quant_score", col])
            if len(sub) >= 30:
                sp = sub["quant_score"].corr(sub[col], method="spearman")
                print(f"  quant_score vs {col}: Spearman={sp:.4f} (n={len(sub)})")
            sub2 = export.dropna(subset=["qual_score", col])
            if len(sub2) >= 30:
                sp2 = sub2["qual_score"].corr(sub2[col], method="spearman")
                print(f"  qual_score  vs {col}: Spearman={sp2:.4f} (n={len(sub2)})")
    else:
        print("  Not enough evaluated rows yet for a meaningful correlation read "
              "— check back after a few more weeks of daily runs.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
