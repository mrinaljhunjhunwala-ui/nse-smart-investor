"""Pure statistics on verdict-ledger rows: how logged calls did against the
Nifty. Shared by scripts/calibration_report.py (the full report) and the
Friday "longer record" Telegram message. No Streamlit, no I/O.

Descriptive only: nothing here changes a rule, a threshold or a score, and the
registered tests (DECISION_RULE, WATCHLIST_RULE) are evaluated elsewhere.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import pandas as pd

BULLISH = ("BUY", "STRONG BUY")
SCORE_FLOOR = 70.0


def _wilson_lower(wins: int, n: int, z: float = 1.96) -> float:
    if n <= 0:
        return 0.0
    p = wins / n
    denom = 1 + z * z / n
    centre = p + z * z / (2 * n)
    margin = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5)
    return max(0.0, (centre - margin) / denom)


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


SCORE_BANDS = ((None, 50, "under 50"), (50, 60, "50-59"), (60, 70, "60-69"),
               (70, 80, "70-79"), (80, None, "80 and over"))
MIN_BAND_PICKS = 20


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


def band_record(df: Optional[pd.DataFrame], score: Any, h: int = 20,
                min_picks: int = MIN_BAND_PICKS) -> Optional[Dict[str, Any]]:
    """How every logged name in this composite-score band did `h` sessions on
    (the group_stats row plus "band" and "h"); None when the score has no band
    or fewer than `min_picks` names have settled. Past calls only. Pure."""
    band = score_band(score)
    if band is None or df is None or df.empty or "composite_score" not in df.columns:
        return None
    s = settled(df, h)
    if s.empty:
        return None
    sc = one_per_day_ticker(s.dropna(subset=["composite_score"])).copy()
    sc["band"] = sc["composite_score"].map(score_band)
    for r in group_stats(sc, "band"):
        if r["group"] == band and r["picks"] >= min_picks:
            return dict(r, band=band, h=h)
    return None


def record_summary(df: Optional[pd.DataFrame], horizons: tuple = (5, 20),
                   floor: float = SCORE_FLOOR) -> Dict[str, Any]:
    """Compact record for a short message. Per horizon h: `bullish_{h}` (the
    group_stats row for all BUY / STRONG BUY calls) and `at_floor_{h}` /
    `under_floor_{h}` (every scored name at or above / below `floor`); a key is
    None when nothing has settled. `since` is the first logging date. Pure."""
    out: Dict[str, Any] = {"since": None}
    if df is None or df.empty or "logged_date" not in df.columns:
        return out
    out["since"] = str(df["logged_date"].astype(str).min())
    for h in horizons:
        s = settled(df, h)
        bull = one_per_day_ticker(s[s["verdict"].isin(BULLISH)]) if "verdict" in s.columns else s.iloc[0:0]
        rows = group_stats(bull.assign(all="all"), "all")
        out[f"bullish_{h}"] = rows[0] if rows else None
        hi = lo = None
        if "composite_score" in s.columns:
            sc = one_per_day_ticker(s.dropna(subset=["composite_score"])).copy()
            sc["band"] = (pd.to_numeric(sc["composite_score"], errors="coerce") >= floor).map(
                {True: "at", False: "under"})
            by = {r["group"]: r for r in group_stats(sc, "band")}
            hi, lo = by.get("at"), by.get("under")
        out[f"at_floor_{h}"], out[f"under_floor_{h}"] = hi, lo
    return out
