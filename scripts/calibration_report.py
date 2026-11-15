"""Read-only report on how the model's logged calls have done.

Prints, for 5 and 20 sessions after each call, how the verdict ledger's rows
did against the Nifty: overall, by Nifty direction on the logging day, by
composite-score band, by verdict, by month and by list, plus the status of the
registered tests (DECISION_RULE, its Rising-Nifty copy, WATCHLIST_RULE).

It answers "is the scoring method working, and does that depend on the market
rising?" from the live ledger. It changes nothing: no rule, threshold or row is
written. The registered tests are reported as they stand; this report is not a
reason to retune them before their dates.

Usage:  python scripts/calibration_report.py
Needs DATABASE_URL (the production ledger) and Yahoo for the Nifty history, so
run it from GitHub Actions (provider_canary.yml, input calibration_report).
"""
from __future__ import annotations

import os
import sys
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np                                              # noqa: E402
import pandas as pd                                             # noqa: E402

HORIZONS = (5, 20)
SCORE_BANDS = ((None, 50, "under 50"), (50, 60, "50-59"), (60, 70, "60-69"),
               (70, 80, "70-79"), (80, None, "80 and over"))
BULLISH = ("BUY", "STRONG BUY")
BROAD_INDEX = "^CRSLDX"                 # Nifty 500 on Yahoo
BROAD_NAME = "Nifty 500"


def _wilson_lower(wins: int, n: int, z: float = 1.96) -> float:
    if n <= 0:
        return 0.0
    p = wins / n
    denom = 1 + z * z / n
    centre = p + z * z / (2 * n)
    margin = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5)
    return max(0.0, (centre - margin) / denom)


def score_band(score: Any) -> Optional[str]:
    try:
        s = float(score)
    except (TypeError, ValueError):
        return None
    if s != s:
        return None
    for lo, hi, label in SCORE_BANDS:
        if (lo is None or s >= lo) and (hi is None or s < hi):
            return label
    return None


def settled(df: pd.DataFrame, h: int) -> pd.DataFrame:
    """Rows with a stock and a Nifty return at horizon h, one per (day, ticker),
    with `ret`, `nifty` and `alpha` (stock minus Nifty, in % points). Pure."""
    rc, nc = f"ret_{h}d", f"nifty_ret_{h}d"
    if df is None or df.empty or rc not in df.columns or nc not in df.columns:
        return pd.DataFrame(columns=["logged_date", "ticker", "ret", "nifty", "alpha"])
    out = df[df[rc].notna() & df[nc].notna()].copy()
    out["ret"] = pd.to_numeric(out[rc], errors="coerce")
    out["nifty"] = pd.to_numeric(out[nc], errors="coerce")
    out = out.dropna(subset=["ret", "nifty"])
    out["alpha"] = out["ret"] - out["nifty"]
    out["logged_date"] = out["logged_date"].astype(str)
    return out


def bench_returns(index_df: Optional[pd.DataFrame], dates: List[str], h: int) -> Dict[str, float]:
    """% move of an index from the close of each logging session to the close h
    sessions later (the ledger's own basis). A date that is not a session uses
    the last close before it. Dates whose window has not finished are left out.
    Pure; returns {} when the index history is missing."""
    if index_df is None or getattr(index_df, "empty", True) or "Close" not in index_df.columns:
        return {}
    close = pd.to_numeric(index_df["Close"], errors="coerce").dropna()
    if close.empty:
        return {}
    days = [d.date().isoformat() for d in pd.to_datetime(close.index)]
    vals = [float(v) for v in close.values]
    out: Dict[str, float] = {}
    for d in dates:
        i = max((k for k, day in enumerate(days) if day <= str(d)), default=None)
        if i is None or i + h >= len(vals) or not vals[i]:
            continue
        out[str(d)] = (vals[i + h] / vals[i] - 1.0) * 100.0
    return out


def rebased(s: pd.DataFrame, bench: Dict[str, float]) -> pd.DataFrame:
    """`s` (from settled) measured against another index: `nifty` and `alpha`
    replaced by that index's move; rows with no index move dropped. Pure."""
    if s.empty or not bench:
        return s.iloc[0:0]
    out = s.copy()
    out["nifty"] = out["logged_date"].map(bench)
    out = out.dropna(subset=["nifty"])
    out["alpha"] = out["ret"] - out["nifty"]
    return out


def one_per_day_ticker(df: pd.DataFrame) -> pd.DataFrame:
    """A name logged by several lists on one day is one observation."""
    if df.empty:
        return df
    return df.sort_values("logged_date").drop_duplicates(["logged_date", "ticker"], keep="first")


def group_stats(df: pd.DataFrame, key: str) -> List[Dict[str, Any]]:
    """Per group: picks, days, average return, Nifty and alpha, share of picks
    ahead of the Nifty, and the day-clustered share of days whose picks were
    ahead on average, with its Wilson 95% lower bound (same-day picks share one
    market move, so days are the independent observations). Pure."""
    rows: List[Dict[str, Any]] = []
    if df.empty or key not in df.columns:
        return rows
    for name, g in df.groupby(key, dropna=True, sort=False):
        daily = g.groupby("logged_date")["alpha"].mean()
        days, wins = int(len(daily)), int((daily > 0).sum())
        rows.append({
            "group": str(name), "picks": int(len(g)), "days": days,
            "avg_ret": float(g["ret"].mean()), "avg_nifty": float(g["nifty"].mean()),
            "avg_alpha": float(g["alpha"].mean()), "median_alpha": float(g["alpha"].median()),
            "pick_win_pct": float((g["alpha"] > 0).mean() * 100.0),
            "day_win_pct": (wins / days * 100.0) if days else None,
            "day_win_lower_pct": _wilson_lower(wins, days) * 100.0 if days else None,
        })
    return rows


def score_rank_corr(df: pd.DataFrame) -> Dict[str, Any]:
    """Does a higher score go with a better result? Average of each day's
    Spearman rank correlation between score and alpha (days with 5+ names), so
    a rising or falling market on one day cannot fake it. Pure."""
    if df.empty or "composite_score" not in df.columns:
        return {"days": 0, "mean_corr": None, "positive_days_pct": None}
    d = df.dropna(subset=["composite_score", "alpha"])
    corrs = []
    for _day, g in d.groupby("logged_date"):
        if len(g) >= 5 and g["composite_score"].nunique() > 1 and g["alpha"].nunique() > 1:
            c = g["composite_score"].rank().corr(g["alpha"].rank())
            if c == c:
                corrs.append(float(c))
    if not corrs:
        return {"days": 0, "mean_corr": None, "positive_days_pct": None}
    return {"days": len(corrs), "mean_corr": float(np.mean(corrs)),
            "positive_days_pct": float(np.mean([c > 0 for c in corrs]) * 100.0)}


def _f(x: Optional[float], unit: str = "%", plus: bool = True) -> str:
    if x is None or x != x:
        return "n/a"
    return f"{x:+.1f}{unit}" if plus else f"{x:.0f}{unit}"


def _table(title: str, rows: List[Dict[str, Any]], order: Optional[List[str]] = None) -> List[str]:
    out = [title]
    if not rows:
        return out + ["  (no settled rows)"]
    if order:
        rows = sorted(rows, key=lambda r: order.index(r["group"]) if r["group"] in order else len(order))
    out.append(f"  {'group':<22} {'picks':>5} {'days':>4} {'avg move':>8} {'Nifty':>7} {'vs Nifty':>8} "
               f"{'median':>7} {'picks ahead':>11} {'days ahead':>10} {'(95% low)':>9}")
    for r in rows:
        out.append(f"  {r['group'][:22]:<22} {r['picks']:>5} {r['days']:>4} {_f(r['avg_ret']):>8} "
                   f"{_f(r['avg_nifty']):>7} {_f(r['avg_alpha'], ' pts'):>8} {_f(r['median_alpha'], ''):>7} "
                   f"{_f(r['pick_win_pct'], '%', False):>11} {_f(r['day_win_pct'], '%', False):>10} "
                   f"{_f(r['day_win_lower_pct'], '%', False):>9}")
    return out


def build_report(df: pd.DataFrame, regimes: Optional[Dict[str, Optional[str]]] = None,
                 broad: Optional[pd.DataFrame] = None, nifty: Optional[pd.DataFrame] = None) -> List[str]:
    """Report lines from ledger rows. `regimes` maps a logged_date string to
    'Rising' / 'Falling' (Nifty's trailing 20 sessions before that day).
    `broad` is the daily history of a broad index (Nifty 500): when given, the
    main tables are repeated against it, because the picks come from ~750
    names and a rally led by the 50 largest reads as the model lagging.
    `nifty` (Nifty 50 history) is only used to check that method. Pure."""
    regimes = regimes or {}
    lines: List[str] = []
    if df is None or df.empty:
        return ["CALIBRATION REPORT", "The verdict ledger is empty or could not be read."]
    d0, d1 = str(df["logged_date"].min()), str(df["logged_date"].max())
    lines += [f"CALIBRATION REPORT  ledger {d0} -> {d1}  ({len(df)} rows, "
              f"{df['logged_date'].nunique()} logging days)",
              "vs Nifty = stock move minus Nifty move over the same sessions, in % points. 'days ahead' = "
              "share of logging days whose picks beat the Nifty on average; (95% low) is its Wilson lower "
              "bound: above 50% means better than chance.", ""]
    if "source" in df.columns:
        lines.append("Rows by source: " + ", ".join(f"{k} {v}" for k, v in df["source"].value_counts().items()))
    if "verdict" in df.columns:
        lines.append("Rows by verdict: " + ", ".join(f"{k} {v}" for k, v in df["verdict"].value_counts().items()))
    for h in HORIZONS:
        s = settled(df, h)
        lines += ["", f"=== {h} sessions after the call: {len(s)} settled rows, "
                      f"{s['logged_date'].nunique() if len(s) else 0} days ==="]
        if s.empty:
            lines.append("  nothing has settled at this horizon yet")
            continue
        s["regime"] = s["logged_date"].map(regimes).fillna("Unknown")
        s["month"] = s["logged_date"].str[:7]
        bull = one_per_day_ticker(s[s["verdict"].isin(BULLISH)]) if "verdict" in s.columns else s.iloc[0:0]
        lines += _table("BUY / STRONG BUY calls, all:", group_stats(bull.assign(all="all bullish calls"), "all"))
        lines += _table("BUY / STRONG BUY calls, by Nifty direction on the day of the call:",
                        group_stats(bull, "regime"), ["Rising", "Falling", "Unknown"])
        lines += _table("BUY / STRONG BUY calls, by month of the call:",
                        sorted(group_stats(bull, "month"), key=lambda r: r["group"]))
        if "verdict" in s.columns:
            lines += _table("Every call, by verdict:", group_stats(one_per_day_ticker(s), "verdict"),
                            ["STRONG BUY", "BUY", "WATCH", "HOLD", "AVOID"])
        if "composite_score" in s.columns:
            sc = one_per_day_ticker(s.dropna(subset=["composite_score"])).copy()
            sc["band"] = sc["composite_score"].map(score_band)
            order = [b[2] for b in SCORE_BANDS]
            lines += _table("Every scored name, by composite score (0-90):", group_stats(sc, "band"), order)
            for reg in ("Rising", "Falling"):
                part = sc[sc["regime"] == reg]
                if len(part):
                    lines += _table(f"  ... the same, calls made while the Nifty was {reg.lower()}:",
                                    group_stats(part, "band"), order)
        b_ret = bench_returns(broad, sorted(s["logged_date"].unique()), h)
        if b_ret:
            sb = rebased(s, b_ret)
            lines += ["", f"--- The same calls against the {BROAD_NAME} (the broad market the picks come from); "
                          f"the 'Nifty' column is the {BROAD_NAME} here ---"]
            chk = bench_returns(nifty, sorted(s["logged_date"].unique()), h)
            if chk:
                both = s.assign(re=s["logged_date"].map(chk)).dropna(subset=["re"])
                if len(both):
                    gap = float((both["re"] - both["nifty"]).abs().mean())
                    lines.append(f"(method check: the Nifty 50 recomputed this way differs from the ledger's own "
                                 f"Nifty move by {gap:.2f} pts on average)")
            bullb = one_per_day_ticker(sb[sb["verdict"].isin(BULLISH)]) if "verdict" in sb.columns else sb.iloc[0:0]
            lines += _table(f"BUY / STRONG BUY calls vs the {BROAD_NAME}, all:",
                            group_stats(bullb.assign(all="all bullish calls"), "all"))
            lines += _table(f"BUY / STRONG BUY calls vs the {BROAD_NAME}, by Nifty direction on the day:",
                            group_stats(bullb, "regime"), ["Rising", "Falling", "Unknown"])
            if "composite_score" in sb.columns:
                scb = one_per_day_ticker(sb.dropna(subset=["composite_score"])).copy()
                scb["band"] = scb["composite_score"].map(score_band)
                lines += _table(f"Every scored name vs the {BROAD_NAME}, by composite score:",
                                group_stats(scb, "band"), [b[2] for b in SCORE_BANDS])
        elif broad is not None:
            lines += ["", f"--- {BROAD_NAME} history has no finished window for these days ---"]
        if "composite_score" in s.columns:
            rc = score_rank_corr(sc)
            if rc["days"]:
                lines.append(f"Score vs result, within each day: average rank correlation "
                             f"{rc['mean_corr']:+.2f} over {rc['days']} days "
                             f"({rc['positive_days_pct']:.0f}% of days positive). 0 = the score does not "
                             f"sort winners from losers; +0.05 to +0.10 is a usable signal.")
    return lines


def _registered_lines(vl: Any, df: pd.DataFrame, nifty: Optional[pd.DataFrame]) -> List[str]:
    out = ["", "=== Registered tests (reported as they stand; not to be retuned) ==="]
    for name, rule in (("DECISION_RULE", vl.DECISION_RULE), ("DECISION_RULE_RISING", vl.DECISION_RULE_RISING)):
        try:
            r = vl.evaluate_decision_rule(rule, nifty_df=nifty)
            out.append(f"  {name}: {r['status']} · {r['n_alpha']} verdicts (need {rule['min_verdicts']}) over "
                       f"{r['alpha_days']} days (need {rule['min_days']}) · days ahead of the Nifty "
                       f"{_f(r['day_win_vs_nifty'], '%', False)} · 95% low "
                       f"{_f(r['wilson_lower_days_vs_nifty'], '%', False)} · average vs Nifty "
                       f"{_f(r['mean_alpha'], ' pts')}")
        except Exception as e:                                  # noqa: BLE001
            out.append(f"  {name}: could not be evaluated ({type(e).__name__}: {e})")
    try:
        rows = vl.with_list_buckets(df)
        w = vl.evaluate_watchlist_rule(rows)
        out.append(f"  WATCHLIST_RULE: {w['status']} · {w['picks']} picks over {w['days']} days · hit "
                   f"{_f(w.get('hit_pct'), '%', False)} · 95% low {_f(w.get('hit_lower_pct'), '%', False)} · "
                   f"net vs Nifty {_f(w.get('avg_vs_nifty_net'), ' pts')}")
        by = vl.results_by_list(rows)
        if by is not None and not by.empty:
            out += ["", "=== Results by list (direction-aware, after a 0.25% round trip) ==="]
            with pd.option_context("display.width", 250, "display.max_columns", 40,
                                   "display.float_format", lambda v: f"{v:.1f}"):
                out += ["  " + ln for ln in by.to_string(index=False).splitlines()]
    except Exception as e:                                      # noqa: BLE001
        out.append(f"  list results could not be evaluated ({type(e).__name__}: {e})")
    return out


def main() -> int:
    import analysis.verdict_ledger as vl
    try:
        df = vl._load_full_ledger()
    except Exception as e:                                      # noqa: BLE001
        print(f"[calibration] ledger unavailable: {type(e).__name__}: {e}")
        return 1
    nifty = broad = None
    try:
        from data.fetcher import fetch_index
        nifty = fetch_index("^NSEI", period="2y")
    except Exception as e:                                      # noqa: BLE001
        print(f"[calibration] Nifty history unavailable ({type(e).__name__}: {e}); "
              f"regime split is 'Unknown'")
    try:
        from data.fetcher import fetch_index
        broad = fetch_index(BROAD_INDEX, period="2y")
    except Exception as e:                                      # noqa: BLE001
        print(f"[calibration] {BROAD_NAME} history unavailable ({type(e).__name__}: {e}); "
              f"the broad-market tables are left out")
    regimes: Dict[str, Optional[str]] = {}
    if not df.empty:
        import datetime as _dt
        for d in df["logged_date"].astype(str).unique():
            try:
                regimes[d] = vl.nifty_regime_at(nifty, _dt.date.fromisoformat(d))
            except ValueError:
                regimes[d] = None
    lines = build_report(df, regimes, broad=broad, nifty=nifty)
    if not df.empty:
        lines += _registered_lines(vl, df, nifty)
    print("\n".join(lines))
    step = os.environ.get("GITHUB_STEP_SUMMARY")
    if step:
        with open(step, "a", encoding="utf-8") as fh:
            fh.write("```\n" + "\n".join(lines) + "\n```\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
