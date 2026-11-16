"""analysis/movers.py — pure logic for the intraday movers radar and the holding guard.

What the radar answers, during market hours:
  * which stocks are up big today, split by NSE market-cap tier (index membership is NSE's own
    free-float market-cap ranking: Nifty 100 = large, Midcap 150 = mid, Smallcap 250 = small,
    everything else = micro / other), so a +4% large cap is not drowned out by +18% micro caps;
  * whether a mover was on last evening's Tomorrow's Watchlist, at any rank (the Telegram list
    only shows its top 5, so a #14 that runs 12% used to pass unseen);
  * how similar past moves did over the next 5 sessions against the Nifty ("is it worth chasing?"),
    from a table built offline over the stored daily history (``build_chase_table``).

The holding guard answers one narrower question for long-term holdings: did something go badly
wrong today (a sharp fall, or a negative filing / weak results)? Ordinary daily wiggles stay quiet.

Pure: no Streamlit, no network, no DB. Inputs are plain dicts / DataFrames.
"""
from __future__ import annotations

import math
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import pandas as pd

# ── Market-cap tiers ────────────────────────────────────────────────────────────────────────────

BANDS: Tuple[str, ...] = ("Large", "Mid", "Small", "Micro")
BAND_LABEL = {
    "Large": "Large cap",
    "Mid": "Mid cap",
    "Small": "Small cap",
    "Micro": "Micro / other",
}
_INDEX_BAND = {
    "NIFTY50": "Large", "NEXT50": "Large",
    "MIDCAP150": "Mid",
    "SMALLCAP250": "Small",
    "MICROCAP250": "Micro", "TOTALMARKET": "Micro",
}

# A move has to be this big (in %, vs the previous close) to count, per tier: a 3% day is large
# for a Nifty 100 name and ordinary for a micro cap.
THRESHOLD_PCT: Dict[str, float] = {"Large": 3.0, "Mid": 5.0, "Small": 7.0, "Micro": 8.0}
# Names on last evening's Tomorrow's Watchlist (any rank) qualify from this move.
WATCHLIST_MIN_PCT = 4.0
PER_BAND = 5
MIN_PRICE = 10.0              # penny stocks out
MIN_TURNOVER_CR = 1.0         # ₹1 crore traded today, when the feed gives turnover

# Holding guard: a fall this sharp in one day, or a negative filing / weak results.
GUARD_DROP_PCT: Dict[str, float] = {"Large": -5.0, "Mid": -7.0, "Small": -8.0, "Micro": -8.0}

WATCHLIST_BUCKETS = (
    ("breakout_candidates", "Breakout", +1),
    ("reversal_watch", "Reversal", +1),
    ("breakdown_watch", "Breakdown risk", -1),
)


def base_symbol(t: Any) -> str:
    return str(t or "").upper().replace(".NS", "").replace(".BO", "").strip()


def band_map(constituents: Iterable[Mapping[str, Any]]) -> Dict[str, str]:
    """{SYMBOL: band} from rows of data/nse_index_constituents.csv (Symbol, Index)."""
    out: Dict[str, str] = {}
    for r in constituents or []:
        sym = base_symbol(r.get("Symbol"))
        band = _INDEX_BAND.get(str(r.get("Index") or "").strip().upper())
        if sym and band and sym not in out:
            out[sym] = band
    return out


def cap_band(symbol: Any, bands: Mapping[str, str]) -> str:
    """Tier of a symbol; anything outside the official lists is Micro / other."""
    return bands.get(base_symbol(symbol), "Micro")


def watchlist_ranks(data: Optional[Mapping[str, Any]]) -> Dict[str, Tuple[str, int, int]]:
    """{SYMBOL: (bucket label, rank 1-based, direction)} from a Tomorrow's Watchlist snapshot's
    ``data``. The first bucket a symbol appears in wins."""
    out: Dict[str, Tuple[str, int, int]] = {}
    if not isinstance(data, Mapping):
        return out
    for key, label, direction in WATCHLIST_BUCKETS:
        for i, p in enumerate(data.get(key) or [], start=1):
            sym = base_symbol(p.get("ticker") if isinstance(p, Mapping) else p)
            if sym and sym not in out:
                out[sym] = (label, i, direction)
    return out


def _num(x: Any) -> Optional[float]:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def gainers_and_losers(rows: Iterable[Tuple[str, float, float]], n: int = 5
                       ) -> Tuple[List[Tuple[str, float, float]], List[Tuple[str, float, float]]]:
    """Top ``n`` gainers (biggest first) and top ``n`` losers (worst first) from
    (symbol, price, change %) rows. A flat or red market can give fewer than n gainers;
    nothing is backfilled."""
    clean = [(s, float(p), float(c)) for s, p, c in rows or []
             if s and _num(p) is not None and _num(c) is not None]
    up = sorted([r for r in clean if r[2] > 0], key=lambda r: -r[2])[:n]
    down = sorted([r for r in clean if r[2] < 0], key=lambda r: r[2])[:n]
    return up, down


def list_moves(sources: Mapping[str, Mapping[str, str]], quotes: Mapping[str, Mapping[str, Any]],
               threshold_pct: float = 1.5) -> List[dict]:
    """Stocks from the owner's lists that moved at least ``threshold_pct`` today.

    sources: {source label: {SYMBOL: detail}}, e.g. {"Tomorrow's Watchlist": {"DHANBANK": "#14
    Breakout"}, "My Portfolio": {"PFC": "avg ₹410"}}. quotes: {SYMBOL or SYMBOL.NS: {price,
    chg_pct}}. One row per symbol (sources joined), biggest absolute move first.
    """
    merged: Dict[str, dict] = {}
    for label, items in (sources or {}).items():
        for sym, detail in (items or {}).items():
            b = base_symbol(sym)
            if not b:
                continue
            row = merged.setdefault(b, {"symbol": b, "sources": [], "details": []})
            if label not in row["sources"]:
                row["sources"].append(label)
            if detail:
                row["details"].append(f"{label}: {detail}")
    out = []
    for b, row in merged.items():
        q = quotes.get(b) or quotes.get(f"{b}.NS") or {}
        pct, price = _num(q.get("chg_pct")), _num(q.get("price"))
        if pct is None or price is None or abs(pct) < threshold_pct:
            continue
        out.append({**row, "pct": round(pct, 2), "price": price})
    return sorted(out, key=lambda r: -abs(r["pct"]))


def sector_moves(scored: Mapping[str, Mapping[str, Any]], min_names: int = 3) -> List[dict]:
    """Median one-day move per sector from the scan's all-scored map, best first."""
    by: Dict[str, List[float]] = {}
    for v in (scored or {}).values():
        if not isinstance(v, Mapping):
            continue
        sec, r = str(v.get("sector") or "").strip(), _num(v.get("return_1d"))
        if sec and r is not None:
            by.setdefault(sec, []).append(r)
    out = [{"sector": k, "median_pct": round(float(pd.Series(xs).median()), 2), "names": len(xs),
            "up": sum(1 for x in xs if x > 0)} for k, xs in by.items() if len(xs) >= min_names]
    return sorted(out, key=lambda r: -r["median_pct"])


def band_gainers_losers(scored: Mapping[str, Mapping[str, Any]], bands: Mapping[str, str],
                        n: int = 5) -> Dict[str, Tuple[List[dict], List[dict]]]:
    """{band: (top n gainers, top n losers)} from the scan's all-scored map."""
    rows: Dict[str, List[Tuple[str, float, float]]] = {b: [] for b in BANDS}
    for k, v in (scored or {}).items():
        if not isinstance(v, Mapping):
            continue
        sym = base_symbol(v.get("ticker") or k)
        r, px = _num(v.get("return_1d")), _num(v.get("price"))
        if sym and r is not None and px:
            rows[cap_band(sym, bands)].append((sym, px, r))
    out = {}
    for b, rs in rows.items():
        up, down = gainers_and_losers(rs, n=n)
        out[b] = ([{"symbol": s, "price": p, "pct": c} for s, p, c in up],
                  [{"symbol": s, "price": p, "pct": c} for s, p, c in down])
    return out


# ── Choosing the movers to send ────────────────────────────────────────────────────────────────

def qualifies(row: Mapping[str, Any], band: str, on_watchlist: bool) -> bool:
    pct, price = _num(row.get("pct")), _num(row.get("price"))
    if pct is None or price is None or price < MIN_PRICE:
        return False
    turnover = _num(row.get("turnover_cr"))
    if turnover is not None and turnover < MIN_TURNOVER_CR:
        return False
    if on_watchlist and pct >= WATCHLIST_MIN_PCT:
        return True
    return pct >= THRESHOLD_PCT.get(band, THRESHOLD_PCT["Micro"])


def select_movers(
    rows: Iterable[Mapping[str, Any]],
    *,
    bands: Mapping[str, str],
    ranks: Mapping[str, Tuple[str, int, int]],
    already: Iterable[str] = (),
    per_band: int = PER_BAND,
) -> List[dict]:
    """New qualifying gainers, at most ``per_band`` per tier, biggest first.

    Bullish Tomorrow's Watchlist names that qualify are always kept (they are the point of the
    radar) and listed first in their tier; the cap applies to the rest. ``already`` = symbols
    sent earlier today, never repeated.
    """
    seen = {base_symbol(s) for s in already}
    best: Dict[str, dict] = {}
    for r in rows or []:
        sym = base_symbol(r.get("symbol"))
        if not sym or sym in seen or sym.startswith("^"):
            continue
        band = cap_band(sym, bands)
        wl = ranks.get(sym)
        on_wl = bool(wl and wl[2] > 0)
        if not qualifies(r, band, on_wl):
            continue
        item = {**dict(r), "symbol": sym, "band": band, "pct": float(r["pct"]),
                "watchlist": wl if on_wl else None}
        if sym not in best or item["pct"] > best[sym]["pct"]:
            best[sym] = item
    out: List[dict] = []
    for band in BANDS:
        items = [x for x in best.values() if x["band"] == band]
        wl_items = sorted([x for x in items if x["watchlist"]], key=lambda x: -x["pct"])
        rest = sorted([x for x in items if not x["watchlist"]], key=lambda x: -x["pct"])
        out += wl_items + rest[:max(0, per_band - len(wl_items))]
    return out


# ── "Is it worth chasing?" — how similar past moves did ────────────────────────────────────────

MOVE_BUCKETS: Tuple[Tuple[float, float], ...] = ((3, 5), (5, 8), (8, 12), (12, math.inf))
VOL_BUCKETS: Tuple[Tuple[float, float], ...] = ((0, 1.5), (1.5, 3), (3, math.inf))
HORIZON = 5
MIN_CASES = 30
ANY_VOL = "any"


def _bucket(x: float, buckets: Sequence[Tuple[float, float]]) -> Optional[int]:
    for i, (lo, hi) in enumerate(buckets):
        if lo <= x < hi:
            return i
    return None


def _key(band: str, m: int, v: Any) -> str:
    return f"{band}|{m}|{v}"


def _close_vol(df: Any) -> Optional[pd.DataFrame]:
    if df is None or len(df) == 0:
        return None
    cols = {str(c).title(): c for c in df.columns}
    if "Close" not in cols:
        return None
    out = pd.DataFrame({"Close": pd.to_numeric(df[cols["Close"]], errors="coerce")})
    out["Volume"] = (pd.to_numeric(df[cols["Volume"]], errors="coerce") if "Volume" in cols
                     else float("nan"))
    out.index = pd.to_datetime(df.index).normalize()
    out = out[~out.index.duplicated(keep="last")].sort_index()
    return out.dropna(subset=["Close"])


def move_events(df: Any, nifty_close: pd.Series, *, horizon: int = HORIZON,
                min_pct: float = 3.0) -> pd.DataFrame:
    """Every up-day of ``min_pct``% or more in one stock's history with its volume ratio (vs the
    prior 20 sessions) and its return ``horizon`` sessions later minus the Nifty's, in % points."""
    bars = _close_vol(df)
    empty = pd.DataFrame(columns=["pct", "vol_ratio", "excess"])
    if bars is None or len(bars) < 25 + horizon:
        return empty
    nifty = pd.to_numeric(nifty_close, errors="coerce")
    nifty.index = pd.to_datetime(nifty.index).normalize()
    nifty = nifty[~nifty.index.duplicated(keep="last")].sort_index()
    c = bars["Close"]
    pct = c.pct_change() * 100
    vol_ratio = bars["Volume"] / bars["Volume"].shift(1).rolling(20, min_periods=15).mean()
    fwd = (c.shift(-horizon) / c - 1) * 100
    n_al = nifty.reindex(c.index)
    nfwd = (n_al.shift(-horizon) / n_al - 1) * 100
    ev = pd.DataFrame({"pct": pct, "vol_ratio": vol_ratio, "excess": fwd - nfwd})
    ev = ev[(ev["pct"] >= min_pct) & ev["excess"].notna()]
    return ev[ev["pct"] < 40]          # splits / bad prints are not "moves"


def build_chase_table(
    history: Mapping[str, Any],
    nifty_close: pd.Series,
    band_of: Callable[[str], str],
    *,
    horizon: int = HORIZON,
) -> Dict[str, dict]:
    """Bucketed record of past up-moves: key "Band|move bucket|volume bucket" (volume bucket
    "any" pools all volumes) -> {n, median_excess, mean_excess, beat_pct, horizon}."""
    pools: Dict[str, List[float]] = {}
    for sym, df in (history or {}).items():
        band = band_of(sym)
        ev = move_events(df, nifty_close, horizon=horizon)
        for pct, vr, ex in ev[["pct", "vol_ratio", "excess"]].itertuples(index=False):
            m = _bucket(float(pct), MOVE_BUCKETS)
            if m is None:
                continue
            pools.setdefault(_key(band, m, ANY_VOL), []).append(float(ex))
            if vr == vr and vr is not None:
                v = _bucket(float(vr), VOL_BUCKETS)
                if v is not None:
                    pools.setdefault(_key(band, m, v), []).append(float(ex))
    table: Dict[str, dict] = {}
    for k, xs in pools.items():
        s = pd.Series(xs)
        table[k] = {"n": int(len(s)), "median_excess": round(float(s.median()), 2),
                    "mean_excess": round(float(s.mean()), 2),
                    "beat_pct": round(float((s > 0).mean() * 100), 1), "horizon": horizon}
    return table


def chase_lookup(table: Optional[Mapping[str, dict]], band: str, pct: float,
                 vol_ratio: Optional[float] = None, *, min_cases: int = MIN_CASES) -> Optional[dict]:
    """The closest bucket with enough cases: same tier + move size + volume, else any volume."""
    if not table or pct is None:
        return None
    m = _bucket(float(pct), MOVE_BUCKETS)
    if m is None:
        return None
    keys = []
    if vol_ratio is not None and vol_ratio == vol_ratio:
        v = _bucket(float(vol_ratio), VOL_BUCKETS)
        if v is not None:
            keys.append(_key(band, m, v))
    keys.append(_key(band, m, ANY_VOL))
    for k in keys:
        s = table.get(k)
        if isinstance(s, Mapping) and int(s.get("n") or 0) >= min_cases:
            return {**dict(s), "key": k}
    return None


def evidence_phrase(stats: Optional[Mapping[str, Any]]) -> str:
    """Plain-language record of similar past moves; never a promise."""
    if not stats:
        return "past record: too few similar moves to say"
    med = float(stats.get("median_excess") or 0)
    word = "kept going" if med > 0.5 else ("gave some back" if med < -0.5 else "went nowhere special")
    return (f"similar past moves {word}: {stats.get('horizon', HORIZON)} sessions later median "
            f"{med:+.1f} pts vs Nifty, {float(stats.get('beat_pct') or 0):.0f}% beat it "
            f"(n={int(stats.get('n') or 0)})")


# ── Holding guard ──────────────────────────────────────────────────────────────────────────────

def guard_reason(pct: Optional[float], band: str, *, negative_filings: Sequence[str] = (),
                 results_score: Optional[float] = None) -> Optional[str]:
    """Why a holding needs a look today, or None. Only real trouble counts: a sharp one-day fall
    for its tier, a negative filing (fraud, auditor exit, regulatory order, ...), or results that
    came in clearly weak (surprise score at or below -20)."""
    parts: List[str] = []
    drop = GUARD_DROP_PCT.get(band, GUARD_DROP_PCT["Micro"])
    if pct is not None and pct <= drop:
        parts.append(f"down {pct:.1f}% today (alert level {drop:.0f}% for a {BAND_LABEL[band].lower()})")
    if results_score is not None and results_score <= -20:
        parts.append("weak quarterly results")
    parts += [f"filing: {s}" for s in negative_filings if s]
    return " · ".join(parts) if parts else None
