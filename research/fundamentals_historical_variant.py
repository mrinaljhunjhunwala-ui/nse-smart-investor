"""
research/fundamentals_historical_variant.py — Option B of the fundamentals
scoring study (see PROJECT.md/chat history: "quantitative + qualitative
fundamentals for Top Picks"). This is the QUANTITATIVE half only — see the
module docstring's "WHAT THIS DOES NOT COVER" section below for why.

WHY A SEPARATE STUDY, NOT JUST WALK-FORWARD LIKE THE OTHERS: score_efficacy.py
/ regime_study.py / score_variants_*.py replay real historical OHLCV, where
"what the price was on date X" is unambiguous. Fundamentals ratios (P/E, ROE,
debt/equity) don't have that property here — Yahoo's `info` dict is a
CURRENT snapshot only, not a historical time series. Naively scoring every
past return with TODAY's P/E would be look-ahead bias, silently invalidating
the study while still producing plausible-looking numbers.

WHAT THIS SCRIPT DOES INSTEAD: reconstructs APPROXIMATE point-in-time ratios
from the ~4-10 years of raw annual financial statements Yahoo does provide
(these DO carry real historical fiscal-year-end dates) combined with the
actual historical share price on each statement date (from this repo's own
OHLCV fetcher, which is genuinely historical). For each fiscal-year-end,
this truncates the ticker's CompanyFundamentals to only the statements
available "as of" that date, so revenue_cagr()/eps_cagr()/roe()/roce() in
analysis/fundamentals/analytics.py — REAL PRODUCTION CODE, not reimplemented
here — see only what would have been reportable then. P/E, P/B, and
EV/EBITDA are reconstructed manually (price × shares, from the same
statement) since those need the period's true point-in-time price, which
Yahoo's ratio fields can't give us. assess_valuation() — also real
production code — is then called for real to get a posture label, which is
mapped to a numeric quant_score for correlation testing.

WHAT THIS DOES NOT COVER (this is Option B, not the full picture):
  * Qualitative flags (analysis/qualitative_flags.py) read LIVE corporate
    announcements / RSS news — there is no historical archive of past
    announcements to replay, so a "qualitative score as of 2022" can't be
    reconstructed at all. That side of the study is Option A
    (research/fundamentals_prospective_*.py — tracks live qualitative +
    quantitative scores forward in real time starting today; results
    accumulate over the coming weeks, not retroactively).
  * Sector classification uses classify_sector(None) — a neutral profile —
    rather than the ticker's real sector, since pulling live sector/industry
    strings for 745 tickers doubles the network cost of this study for a
    refinement that mainly affects a few sector-specific guard rails
    (financials' EV/EBITDA suppression, cyclical peak/trough checks). A
    clear caveat, not a silent gap.
  * Coverage is inherently shallower than the OHLCV studies: annual
    statements only (no quarterly-granularity history reused here), and
    Yahoo's own coverage is patchy for smaller caps (documented in
    providers/yahoo_fundamentals.py's own module docstring).
  * KNOWN APPROXIMATION RISKS, stated plainly: shares_diluted at the
    statement date may not exactly match shares outstanding on the exact
    trading day priced (buybacks/splits between the two); EPS figures may
    be trailing-twelve-month rather than strictly fiscal-year; income/
    balance/cash-flow statement lists are assumed index-aligned by
    reporting date (true for the vast majority of NSE annual filers, not
    guaranteed for all).

Run:
    py -m research.fundamentals_historical_variant             # full universe
    py -m research.fundamentals_historical_variant --limit 30   # pipeline check

Outputs:
    research/output/fundamentals_hist_observations.csv
    research/output/fundamentals_hist_summary.csv
    research/output/fundamentals_hist_deciles.csv
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

from analysis.fundamentals.service import default_service          # noqa: E402
from analysis.fundamentals.models import CompanyFundamentals, RatioSnapshot  # noqa: E402
from analysis.fundamentals.analytics import compute_all             # noqa: E402
from analysis.fundamentals.valuation import build_valuation_context  # noqa: E402
from analysis.fundamentals.valuation_decision import assess_valuation  # noqa: E402
from analysis.sector_classification import classify_sector          # noqa: E402
from research.score_efficacy import _spearman                       # noqa: E402

OUT_DIR = os.path.join(_ROOT, "research", "output")

PRICE_PERIOD  = "10y"    # need headroom: oldest statement + 1y forward lookahead
HORIZONS      = {"fwd_120d": 120, "fwd_252d": 252}   # ~6mo / ~1y — fundamentals is a longer-horizon question than the daily technical studies

# Posture -> numeric score. A labelled POLICY mapping (like this codebase's
# other conviction/reweight multipliers), NOT itself backtested — that's
# what this whole script exists to test. INSUFFICIENT_EVIDENCE is excluded
# (NaN), not zeroed, since "we don't know" isn't the same as "bearish".
POSTURE_SCORE = {
    "SUPPORTED_BY_GROWTH_AND_QUALITY": 90.0,
    "SUPPORTED_BY_GROWTH":             75.0,
    "SUPPORTED_BY_QUALITY":            75.0,
    "SUPPORTED_BY_ROE":                70.0,
    "REASONABLE":                      55.0,
    "DEMANDING_VS_GROWTH":             35.0,
    "DEMANDING_VS_RETURNS":            30.0,
    "DEMANDING_VS_ROE":                30.0,
    "INSUFFICIENT_EVIDENCE":           np.nan,
}


def _nearest_price_idx(price_df: pd.DataFrame, target_date) -> Optional[int]:
    """First trading-day index on/after target_date (statements land on
    non-trading days often; walk forward up to 5 sessions, never backward —
    walking backward would leak pre-statement price into a post-statement
    ratio)."""
    idx = price_df.index
    pos = idx.searchsorted(pd.Timestamp(target_date))
    for offset in range(6):
        j = pos + offset
        if j < len(idx):
            return j
    return None


def _truncate_cf(cf_full: CompanyFundamentals, i: int) -> Optional[CompanyFundamentals]:
    inc = cf_full.income_statements[i:]
    bal = cf_full.balance_sheets[i:]
    cfw = cf_full.cash_flows[i:]
    if not inc or not bal:
        return None
    return CompanyFundamentals(
        symbol=cf_full.symbol, company_name=cf_full.company_name,
        provider_name=cf_full.provider_name, statement_date=inc[0].period.period_end,
        last_updated=cf_full.last_updated, currency=cf_full.currency,
        income_statements=inc, balance_sheets=bal, cash_flows=cfw,
    )


def _reconstruct_point(ticker: str, cf_full: CompanyFundamentals, i: int,
                       price_df: pd.DataFrame) -> Optional[Dict]:
    inc0 = cf_full.income_statements[i]
    bal0 = cf_full.balance_sheets[i] if i < len(cf_full.balance_sheets) else None
    period_end = inc0.period.period_end
    if period_end is None or bal0 is None:
        return None

    j = _nearest_price_idx(price_df, period_end)
    if j is None:
        return None
    price = float(price_df["Close"].iloc[j])
    if not np.isfinite(price) or price <= 0:
        return None

    cf_t = _truncate_cf(cf_full, i)
    if cf_t is None:
        return None

    eps    = inc0.eps_diluted or inc0.eps_basic
    shares = inc0.shares_diluted
    equity = bal0.total_equity
    debt   = bal0.total_debt if bal0.total_debt is not None else (
        (bal0.short_term_debt or 0) + (bal0.long_term_debt or 0))
    cash   = bal0.cash_and_equivalents
    ebitda = inc0.ebitda

    pe = (price / eps) if (eps and eps > 0) else None
    pb = (price * shares / equity) if (shares and equity and equity > 0) else None
    ev_ebitda = None
    if shares and ebitda and ebitda > 0:
        ev = price * shares + (debt or 0) - (cash or 0)
        if ev > 0:
            ev_ebitda = ev / ebitda

    cf_t.ratios = RatioSnapshot(as_of=period_end, pe=pe, pb=pb, ev_ebitda=ev_ebitda)
    sector_profile = classify_sector(None)   # neutral — see module docstring caveat

    try:
        analytics  = compute_all(cf_t)
        vctx       = build_valuation_context(cf_t, sector_profile)
        assessment = assess_valuation(vctx, analytics, sector_profile, cf=cf_t)
    except Exception:
        return None

    row = {
        "ticker": ticker, "period_end": str(period_end),
        "price_at_period_end": round(price, 2),
        "pe": round(pe, 2) if pe else None,
        "pb": round(pb, 2) if pb else None,
        "ev_ebitda": round(ev_ebitda, 2) if ev_ebitda else None,
        "posture": assessment.posture, "confidence": assessment.confidence,
        "quant_score": POSTURE_SCORE.get(assessment.posture, np.nan),
    }
    for label, h in HORIZONS.items():
        if j + h < len(price_df):
            entry = float(price_df["Close"].iloc[j])
            fwd   = float(price_df["Close"].iloc[j + h])
            row[label] = (fwd / entry - 1.0) * 100.0 if entry > 0 else np.nan
        else:
            row[label] = np.nan
    return row


def _process_ticker(ticker: str) -> List[Dict]:
    from data.fetcher import fetch_single
    svc = default_service()
    try:
        cf_full = svc.get_fundamentals(ticker, period="annual", years=10)
    except Exception:
        return []
    if not cf_full.income_statements or not cf_full.balance_sheets:
        return []

    try:
        price_df = fetch_single(ticker, period=PRICE_PERIOD)
    except Exception:
        return []
    if price_df is None or price_df.empty or len(price_df) < 60:
        return []
    price_df = price_df.sort_index()

    n_periods = min(len(cf_full.income_statements), len(cf_full.balance_sheets))
    rows = []
    for i in range(n_periods):
        r = _reconstruct_point(ticker, cf_full, i, price_df)
        if r is not None:
            rows.append(r)
    return rows


# ─────────────────────────────────────────────────────────────────────────────
# Aggregation
# ─────────────────────────────────────────────────────────────────────────────

def aggregate(obs: pd.DataFrame) -> Dict[str, pd.DataFrame]:
    scored = obs.dropna(subset=["quant_score"])

    rows = []
    for label in HORIZONS:
        sub = scored.dropna(subset=[label])
        rows.append({
            "horizon": label,
            "n_scored": len(sub),
            "spearman": round(_spearman(sub["quant_score"], sub[label]), 4) if len(sub) >= 50 else np.nan,
        })
    summary = pd.DataFrame(rows).set_index("horizon")

    dec = scored.dropna(subset=["quant_score", "fwd_120d"]).copy()
    if len(dec) >= 50:
        dec["decile"] = pd.qcut(dec["quant_score"].rank(method="first"), 10,
                                labels=list(range(1, 11)))
        deciles = (dec.groupby("decile", observed=True)
                      .agg(n=("ticker", "size"),
                           fwd_120d=("fwd_120d", "mean"),
                           fwd_252d=("fwd_252d", "mean"))
                      .round(2))
    else:
        deciles = pd.DataFrame()

    posture_counts = scored["posture"].value_counts()

    return {"summary": summary, "deciles": deciles, "posture_counts": posture_counts}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()

    from data.universe import get_universe
    universe = list(get_universe("nifty500"))
    if args.limit:
        universe = universe[: args.limit]

    os.makedirs(OUT_DIR, exist_ok=True)
    t0 = time.time()
    print(f"FUNDAMENTALS HISTORICAL VARIANT (Option B, quantitative-only) | "
          f"universe={len(universe)}")

    all_rows: List[Dict] = []
    failures = 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(_process_ticker, t): t for t in universe}
        done = 0
        for f in as_completed(futs):
            try:
                all_rows.extend(f.result())
            except Exception:
                failures += 1
            done += 1
            if done % 50 == 0:
                print(f"  {done}/{len(universe)} tickers processed "
                      f"({len(all_rows)} statement-points so far) [{time.time()-t0:.0f}s]")
    if failures:
        print(f"  {failures}/{len(universe)} tickers raised an exception during processing")

    obs = pd.DataFrame(all_rows)
    if obs.empty:
        print("No observations — aborting (check network access to Yahoo).")
        return 1

    obs.to_csv(os.path.join(OUT_DIR, "fundamentals_hist_observations.csv"),
               index=False, encoding="utf-8")
    n_scored = obs["quant_score"].notna().sum()
    print(f"Statement-points: {len(obs)} from {obs['ticker'].nunique()} tickers | "
          f"scored (posture != INSUFFICIENT_EVIDENCE): {n_scored} "
          f"({n_scored/len(obs)*100:.1f}%)")

    aggs = aggregate(obs)
    aggs["summary"].to_csv(os.path.join(OUT_DIR, "fundamentals_hist_summary.csv"), encoding="utf-8")
    if not aggs["deciles"].empty:
        aggs["deciles"].to_csv(os.path.join(OUT_DIR, "fundamentals_hist_deciles.csv"), encoding="utf-8")

    pd.set_option("display.width", 200)
    print("\n=== POSTURE DISTRIBUTION ===")
    print(aggs["posture_counts"])
    print("\n=== SPEARMAN: quant_score vs forward return ===")
    print(aggs["summary"])
    if not aggs["deciles"].empty:
        print("\n=== DECILE BREAKDOWN (quant_score deciles vs forward returns) ===")
        print(aggs["deciles"])
    print(f"\nDone in {time.time()-t0:.0f}s. CSVs in {OUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
