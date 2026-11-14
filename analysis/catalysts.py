"""analysis/catalysts.py — event-driven BUY / SELL reads (post-earnings drift + material filings).

PURE: pandas / numpy / stdlib only. No I/O, no network, no Streamlit. Network code lives in
``data/nse_announcements.py``; orchestration in ``alerts/catalyst_alerts.py``.

Idea: stocks with a large positive earnings surprise AND a strong, high-volume announcement
reaction tend to keep drifting (post-earnings-announcement drift); the mirror holds for
negative surprises. With no free consensus data, "surprise" is the seasonal random walk:
this quarter vs the same quarter a year ago (and vs the previous quarter), plus margin change
and loss-to-profit turnarounds. Nothing here is a sure-shot signal — every read is model
output with a stop.

Rule table (``catalyst_read``)
==============================

Liquidity floor   20-day average turnover >= ₹10 cr AND price >= ₹20, else None
                  (unknown turnover also -> None).
Catalyst          every event classified by ``classify_announcement``. Results take their direction
                  from the ``results_surprise`` score: >= +25 -> +1, <= -25 -> -1, else none.
                  net = Σ direction × weight × freshness; no net direction -> None.
Freshness         session closes (15:30 IST) between filing and now: 0 -> 1.0, 1 -> 0.6, 2 -> 0.3,
                  >= 3 -> ignored. Results keep 0.5 for 3-5 sessions (swing) when the reaction day
                  closed in the top (bottom, if negative) quarter of its range on >= 2x volume.
Price move        live day change > pre-open gap > event-day return, in that order.
Volume            live relative volume, else the event day's volume vs its prior 20-day average.
BUY               positive catalyst AND move >= +1% AND (relative volume unknown or >= 1.5x).
Contradiction     positive catalyst with move <= -1% -> WATCH "good news sold into"
                  (mirror: "bad news bought").
Weak follow-up    |move| < 1% or no price yet -> WATCH; relative volume < 1.5x -> WATCH.
Gap discipline    move above +8% (below -8%) or a circuit-locked event day -> WATCH with warning
                  "extended / not tradable at open"; +1% … +8% is the tradable zone.
Trigger           above the first-15-minute high when an opening range is given; else above
                  max(pre-open IEP, previous-day high); live: above the day's high so far; else above
                  the last bar's high. SELL: below the matching lows.
Stop              intraday: the LOWER of opening-range low and trigger − 0.5 × ATR(14) (no opening
                  range: trigger − 0.5 × ATR); swing: trigger − 1.0 × ATR. SELL mirrored (the HIGHER
                  of opening-range high and trigger + k × ATR).
Target            trigger + 2 × risk, capped at the circuit band when ``price_band_pct`` is given.
R:R gate          reward / risk < 1.5 -> WATCH, warning "reward/risk under 1.5R"; no ATR -> WATCH.
Horizon           "intraday" when the strongest event was filed since the previous close, else "swing".
SELL              mirror of BUY for negative catalysts; for a cash-market user it reads
                  "exit / avoid; short only in F&O names" (added as a warning).
Strength          50 × min(1, |net|) + 25 × volume (1x -> 0, 3x -> 1; unknown = 8 pts)
                  + 25 × move (|move| / 4%, only when confirming); WATCH × 0.6.
"""
from __future__ import annotations

import datetime as _dt
import math
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence

import numpy as np
import pandas as pd

IST = _dt.timezone(_dt.timedelta(hours=5, minutes=30))
SESSION_CLOSE = _dt.time(15, 30)

MIN_TURNOVER_CR = 10.0
MIN_PRICE = 20.0
CONFIRM_MOVE_PCT = 1.0
EXTENDED_MOVE_PCT = 8.0
MIN_REL_VOL = 1.5
MIN_RR = 1.5
TARGET_R = 2.0
RESULTS_DIRECTION_SCORE = 25.0
GROWTH_CAP = 300.0
CIRCUIT_BANDS = (5.0, 10.0, 20.0)
EXTENDED_WARNING = "extended / not tradable at open"
SELL_WARNING = "exit / avoid; short only in F&O names"


# ─────────────────────────────────────────────────────────────────────────────
# Announcement classification
# ─────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Catalyst:
    kind: str
    direction: int          # +1 / -1 / 0 (0: decided later, e.g. results)
    weight: float           # 0..1
    label: str              # short plain phrase


# (kind, direction, weight, label, regex) — FIRST match wins, so severe negatives and
# tax / regulatory "orders" come before order wins, and noise comes before results.
_SEVERE: List[tuple] = [
    ("fraud", -1, 1.0, "fraud / forensic issue", r"\bfraud|forensic audit|misappropriat|siphon"),
    ("insolvency", -1, 1.0, "insolvency proceedings",
     r"insolvency|\bcirp\b|\bibc\b|nclt (?:has )?admit|admission of (?:the )?petition|liquidation"),
    ("default", -1, 0.9, "payment default",
     r"\bdefault|delay in (?:the )?(?:payment|servicing)|non[- ]payment of (?:interest|principal)"),
    ("auditor_exit", -1, 0.8, "auditor resigned", r"(?:auditor|statutory audit).{0,40}resign|resign.{0,60}auditor"),
    ("kmp_exit", -1, 0.6, "CEO / CFO resigned",
     r"(?:resign|cessation|steps? down|stepped down).{0,80}"
     r"(?:\bceo\b|\bcfo\b|chief executive|chief financial|managing director|\bmd\b)"
     r"|(?:\bceo\b|\bcfo\b|chief executive|chief financial|managing director|\bmd\b).{0,80}"
     r"(?:resign|cessation|steps? down|stepped down)"),
    ("fda_negative", -1, 0.8, "USFDA warning / import alert",
     r"warning letter|import alert|\boai\b|official action indicated"),
    ("fda_483", -1, 0.4, "USFDA Form 483 observations",
     r"form[- ]?483.{0,40}\b(?:[1-9]\d?)\b\s*observation|\b(?:[1-9]\d?)\s*observations?\b"),
    ("regulatory", -1, 0.7, "SEBI / regulatory order",
     r"\bsebi\b.{0,40}(?:order|interim|debar|restrain|ban)|debarr|restrain(?:ed|ing) from|regulatory action"
     r"|cancell?ation of licen[cs]e|suspension of licen[cs]e"),
    ("penalty", -1, 0.4, "penalty / tax demand",
     r"penalt|show[- ]cause|tax demand|demand (?:order|notice)|\bgst\b.{0,40}(?:order|demand)|fine imposed"),
    ("rating_down", -1, 0.6, "credit rating downgraded", r"downgrad"),
    ("pledge", -1, 0.5, "promoter pledge", r"creation of pledge|invocation of pledge|pledge (?:created|invoked)"
     r"|encumbrance (?:created|creation)"),
    ("promoter_sale", -1, 0.5, "promoter selling stake",
     r"promoter.{0,60}(?:\bsale\b|\bsell|\bsold\b|offload|dispos|divest)|offer for sale|\bofs\b"),
    ("disruption", -1, 0.6, "fire / plant shutdown",
     r"\bfire\b|explosion|shut ?down|lock[- ]?out|\bstrike\b|suspension of (?:operations|production)"
     r"|plant (?:closure|closed)"),
]

_NOISE = re.compile(
    r"trading window|newspaper|news paper|loss of share certificate|duplicate share certificate|"
    r"issue of duplicate|regulation 74\s*\(5\)|reg(?:ulation)?\.? 74|certificate under|compliance certificate|"
    r"board meeting intimation|prior intimation|intimation of board meeting|to consider and approve|"
    r"will consider|esop|esos|allotment of (?:equity )?shares under|employee stock|change (?:in|of) (?:registered )?"
    r"address|investor (?:meet|presentation|conference)|analyst(?:s)? (?:meet|call)|earnings call|"
    r"conference call|\bagm\b|annual general meeting|postal ballot|e-voting|scrutini[sz]er|record date for agm|"
    r"reaffirm|credit rating.{0,40}(?:assigned|withdrawn)|shareholding pattern|statement of investor complaints|"
    r"loss of certificate|transmission of shares|book closure|change in (?:rta|registrar)|secretarial|"
    r"related party transaction|integrated filing|copy of|disclosure of voting|voting results"
)

_RESULTS = re.compile(
    r"financial results?|quarterly results?|un-?audited|audited (?:standalone|consolidated|financial)|"
    r"results? for the (?:quarter|period|half)|outcome of (?:the )?board meeting.{0,120}result"
)

_POSITIVE: List[tuple] = [
    ("fda_positive", +1, 0.6, "USFDA approval / clean inspection",
     r"(?:usfda|us fda|\bfda\b).{0,60}(?:approv|\beir\b|establishment inspection|zero observation|nil observation)"
     r"|\banda\b.{0,30}approv|zero (?:483 )?observations?"),
    ("buyback", +1, 0.7, "share buyback", r"buy[- ]?back"),
    ("bonus", +1, 0.5, "bonus issue", r"\bbonus\b"),
    ("split", +1, 0.4, "stock split", r"sub-?division|stock split|split of (?:equity )?shares|\bsplit\b"),
    ("special_dividend", +1, 0.4, "special dividend", r"special dividend"),
    ("rating_up", +1, 0.5, "credit rating upgraded", r"upgrad"),
    ("promoter_buy", +1, 0.5, "promoter buying",
     r"promoter.{0,60}(?:acqui|purchase|bought|\bbuy)|creeping acquisition"),
    ("demerger", +1, 0.5, "demerger", r"demerg"),
    ("order_win", +1, 0.6, "order win",
     r"letter of (?:award|intent)|\bloa\b|\bloi\b|bagged|bags\b|receipt of (?:an? )?(?:new )?orders?|"
     r"work orders?|purchase orders?|\bl-?1 bidder|lowest bidder|(?:order|contract)s?.{0,40}"
     r"(?:receiv|win|won|secur|award|worth|valued)|(?:receiv|win|won|secur|award)\w*.{0,40}(?:order|contract)"),
    ("capacity", +1, 0.5, "capacity expansion / commissioning",
     r"commission|commercial (?:production|operation)|capacity expansion|expansion of capacity|new plant|"
     r"brownfield|greenfield|\bcapex\b"),
    ("acquisition", +1, 0.4, "acquisition", r"acqui"),
    ("merger", 0, 0.3, "merger / amalgamation", r"merger|amalgamat|scheme of arrangement"),
    ("preferential", +1, 0.4, "preferential issue", r"preferential"),
    ("dilution", -1, 0.3, "fund raise (QIP / rights)", r"\bqip\b|qualified institution|rights issue"),
]

_COMPILED_SEVERE = [(k, d, w, lbl, re.compile(p)) for k, d, w, lbl, p in _SEVERE]
_COMPILED_POSITIVE = [(k, d, w, lbl, re.compile(p)) for k, d, w, lbl, p in _POSITIVE]


def _norm_text(*parts: Any) -> str:
    return re.sub(r"\s+", " ", " | ".join(str(p or "") for p in parts)).strip().lower()


def classify_announcement(category: Any, headline: Any = "", detail: Any = "") -> Optional[Catalyst]:
    """Map one filing to a Catalyst, or None for routine / unclassifiable filings."""
    text = _norm_text(category, headline, detail)
    if not text.strip(" |"):
        return None
    zero_obs = re.search(r"\b(?:zero|nil|no)\s+(?:form[- ]?483\s+)?observations?", text)
    # Quarterly "disclosure of defaults on loans" filings usually say Nil / not applicable.
    no_default = re.search(r"\bnil\b|no default|not applicable|\bn\.?a\.?\b", text)
    for kind, d, w, lbl, rx in _COMPILED_SEVERE:
        if kind == "fda_483" and zero_obs:
            continue
        if kind == "default" and no_default:
            continue
        if rx.search(text):
            return Catalyst(kind, d, w, lbl)
    if _NOISE.search(text):
        return None
    if _RESULTS.search(text):
        return Catalyst("results", 0, 1.0, "quarterly results")
    for kind, d, w, lbl, rx in _COMPILED_POSITIVE:
        if rx.search(text):
            return Catalyst(kind, d, w, lbl)
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Results surprise
# ─────────────────────────────────────────────────────────────────────────────

def _f(x: Any) -> Optional[float]:
    if x is None:
        return None
    if isinstance(x, str):
        s = x.strip().replace(",", "")
        if s in {"", "-", "--", "NA", "N/A", "nan"}:
            return None
        if s.startswith("(") and s.endswith(")"):
            s = "-" + s[1:-1]
        x = s
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _as_date(x: Any) -> Optional[_dt.date]:
    if x is None:
        return None
    if isinstance(x, _dt.datetime):
        return x.date()
    if isinstance(x, _dt.date):
        return x
    try:
        ts = pd.Timestamp(str(x))
    except Exception:
        return None
    return None if pd.isna(ts) else ts.date()


def quarter_label(period_end: Any) -> str:
    """Indian fiscal-year quarter: Jun -> Q1, Sep -> Q2, Dec -> Q3, Mar -> Q4."""
    d = _as_date(period_end)
    if d is None:
        return "Latest quarter"
    return {6: "Q1", 9: "Q2", 12: "Q3", 3: "Q4"}.get(d.month, f"Quarter to {d:%b %Y}")


def growth_pct(cur: Optional[float], base: Optional[float], cap: float = GROWTH_CAP) -> Optional[float]:
    """Growth vs base, robust to a negative base (change over |base|) and capped at ±cap %."""
    if cur is None or base is None or base == 0:
        return None
    g = (cur / base - 1.0) * 100.0 if base > 0 else (cur - base) / abs(base) * 100.0
    return float(max(-cap, min(cap, g)))


def _find_quarter(rows: List[dict], target: _dt.date, tol_days: int = 45) -> Optional[dict]:
    best, best_gap = None, None
    for r in rows:
        d = r["_d"]
        gap = abs((d - target).days)
        if gap <= tol_days and (best_gap is None or gap < best_gap):
            best, best_gap = r, gap
    return best


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def results_surprise(quarters: Sequence[dict], is_lender: bool = False) -> Optional[dict]:
    """Seasonal-random-walk surprise from quarterly figures (newest first or any order).

    Needs the newest quarter and the year-ago quarter (±45 days), both with revenue and
    net profit. Lenders: revenue = total income and the margin test is skipped.
    Score components (sum clamped to [-100, 100]): revenue YoY ±30 (±50 % saturates),
    profit YoY ±40 (±100 %), operating-margin change ±15 (±5 pts), profit QoQ ±15 (±50 %).
    Turnaround (loss -> profit) sets the profit part to +30 (+12 if revenue fell);
    slipping to a loss sets it to -40. Profit up while revenue fell > 2 % keeps only 40 %
    of the profit part (likely one-off other income); revenue and profit disagreeing in sign
    caps |score| at 40.
    """
    rows = []
    for q in quarters or []:
        if not isinstance(q, dict):
            continue
        d = _as_date(q.get("period_end"))
        if d is None:
            continue
        rev = _f(q.get("total_income")) if is_lender and q.get("total_income") is not None else _f(q.get("revenue"))
        rows.append({**q, "_d": d, "_rev": rev, "_np": _f(q.get("net_profit")), "_eps": _f(q.get("eps")),
                     "_op": _f(q.get("operating_profit"))})
    if not rows:
        return None
    rows.sort(key=lambda r: r["_d"], reverse=True)
    cur = rows[0]
    if cur["_np"] is None or cur["_rev"] is None:
        return None
    ya = _find_quarter(rows[1:], cur["_d"] - _dt.timedelta(days=365))
    if ya is None or ya["_np"] is None or ya["_rev"] is None:
        return None
    prev = _find_quarter(rows[1:], cur["_d"] - _dt.timedelta(days=91))

    rev_yoy = growth_pct(cur["_rev"], ya["_rev"])
    np_yoy = growth_pct(cur["_np"], ya["_np"])
    eps_yoy = growth_pct(cur["_eps"], ya["_eps"])
    np_qoq = growth_pct(cur["_np"], prev["_np"]) if prev else None
    rev_qoq = growth_pct(cur["_rev"], prev["_rev"]) if prev else None
    margin_chg = None
    if not is_lender and cur["_op"] is not None and ya["_op"] is not None and cur["_rev"] and ya["_rev"]:
        margin_chg = (cur["_op"] / cur["_rev"] - ya["_op"] / ya["_rev"]) * 100.0

    turnaround = ya["_np"] <= 0 < cur["_np"]
    slipped = ya["_np"] > 0 >= cur["_np"]
    flags: List[str] = []

    rev_part = _clamp(rev_yoy or 0.0, -50, 50) / 50 * 30
    if turnaround:
        np_part = 30.0 if (rev_yoy or 0) >= 0 else 12.0
        flags.append("turnaround")
    elif slipped:
        np_part = -40.0
        flags.append("slipped_to_loss")
    else:
        np_part = _clamp(np_yoy or 0.0, -100, 100) / 100 * 40
    profit_without_revenue = (np_yoy or 0) > 0 and rev_yoy is not None and rev_yoy < -2 and not slipped
    if profit_without_revenue:
        np_part *= 0.4
        flags.append("profit_without_revenue")
    margin_part = _clamp(margin_chg, -5, 5) / 5 * 15 if margin_chg is not None else 0.0
    qoq_part = _clamp(np_qoq, -50, 50) / 50 * 15 if np_qoq is not None and prev["_np"] > 0 else 0.0
    score = rev_part + np_part + margin_part + qoq_part
    profit_dir = 1 if (turnaround or (np_yoy or 0) > 0) else (-1 if (slipped or (np_yoy or 0) < 0) else 0)
    rev_dir = 1 if (rev_yoy or 0) > 0 else (-1 if (rev_yoy or 0) < 0 else 0)
    if profit_dir and rev_dir and profit_dir != rev_dir:
        score = _clamp(score, -40, 40)
        flags.append("mixed")
    score = float(round(_clamp(score, -100, 100), 1))
    unit = str(cur.get("unit") or "cr")
    return {
        "period_end": cur["_d"], "label": quarter_label(cur["_d"]), "year_ago_period_end": ya["_d"],
        "revenue": cur["_rev"], "revenue_year_ago": ya["_rev"], "net_profit": cur["_np"],
        "net_profit_year_ago": ya["_np"], "revenue_yoy_pct": rev_yoy, "profit_yoy_pct": np_yoy,
        "eps_yoy_pct": eps_yoy, "profit_qoq_pct": np_qoq, "revenue_qoq_pct": rev_qoq,
        "margin_change_pts": None if margin_chg is None else round(margin_chg, 2),
        "turnaround": turnaround, "slipped_to_loss": slipped, "flags": flags, "score": score,
        "is_lender": is_lender, "unit": unit, "source": cur.get("source"),
    }


def _money(v: float) -> str:
    return f"₹{v:,.1f}" if abs(v) < 10 else f"₹{v:,.0f}"


def surprise_phrase(s: dict, *, numbers: bool = False) -> str:
    """'Q2 profit +86% YoY, revenue +38%' (numbers=True adds the actual figures)."""
    q, unit = s.get("label") or "Latest quarter", s.get("unit") or "cr"
    np_, base = s.get("net_profit"), s.get("net_profit_year_ago")
    rev = s.get("revenue_yoy_pct")
    rev_txt = f"revenue {rev:+.0f}%" if rev is not None else ""
    if s.get("turnaround") and np_ is not None and base is not None:
        head = f"{q} swung to a profit of {_money(np_)} {unit} from {'a loss of ' + _money(-base) if base < 0 else _money(base)} {unit} a year ago"  # noqa: E501
    elif s.get("slipped_to_loss") and np_ is not None and base is not None:
        head = f"{q} slipped to a loss of {_money(-np_)} {unit} from a {_money(base)} {unit} profit a year ago"
    elif numbers and np_ is not None and base is not None and s.get("profit_yoy_pct") is not None:
        head = f"{q} profit {_money(np_)} {unit} vs {_money(base)} {unit} a year ago, {s['profit_yoy_pct']:+.0f}%"
    elif s.get("profit_yoy_pct") is not None:
        head = f"{q} profit {s['profit_yoy_pct']:+.0f}% YoY"
    else:
        head = f"{q} results"
    if "profit_without_revenue" in (s.get("flags") or []):
        rev_txt += " (profit up on falling revenue - check other income)"
    return f"{head}; {rev_txt}" if numbers and rev_txt else (f"{head}, {rev_txt}" if rev_txt else head)


# ─────────────────────────────────────────────────────────────────────────────
# Price / volume reaction
# ─────────────────────────────────────────────────────────────────────────────

def _ohlcv(df: Any) -> Optional[pd.DataFrame]:
    if not isinstance(df, pd.DataFrame) or df.empty:
        return None
    cols = {str(c).lower(): c for c in df.columns}
    need = ["open", "high", "low", "close"]
    if not all(n in cols for n in need):
        return None
    out = pd.DataFrame({n.capitalize(): pd.to_numeric(df[cols[n]], errors="coerce") for n in need})
    out["Volume"] = pd.to_numeric(df[cols["volume"]], errors="coerce") if "volume" in cols else np.nan
    try:
        idx = pd.to_datetime(df.index)
        if getattr(idx, "tz", None) is not None:
            idx = idx.tz_convert(IST).tz_localize(None)
    except Exception:
        return None
    out.index = idx.normalize()
    out = out[~out.index.duplicated(keep="last")].sort_index()
    return out.dropna(subset=["Close"])


def _to_ist(when: Any) -> Optional[_dt.datetime]:
    if when is None:
        return None
    if isinstance(when, _dt.datetime):
        t = when
    elif isinstance(when, _dt.date):
        t = _dt.datetime.combine(when, _dt.time(0, 0))
    else:
        try:
            ts = pd.Timestamp(str(when))
        except Exception:
            return None
        if pd.isna(ts):
            return None
        t = ts.to_pydatetime()
    return t.replace(tzinfo=IST) if t.tzinfo is None else t.astimezone(IST)


def reaction_date(event_when: Any) -> Optional[_dt.date]:
    """Session date that first trades on the event: same day if filed before 15:30 IST, else the next day.
    A bare date counts as that day's session."""
    if isinstance(event_when, _dt.date) and not isinstance(event_when, _dt.datetime):
        return event_when
    t = _to_ist(event_when)
    if t is None:
        return None
    return t.date() if t.time() < SESSION_CLOSE else t.date() + _dt.timedelta(days=1)


def _atr(df: pd.DataFrame, n: int = 14) -> Optional[float]:
    if len(df) < 2:
        return None
    prev_close = df["Close"].shift(1)
    tr = pd.concat([df["High"] - df["Low"], (df["High"] - prev_close).abs(),
                    (df["Low"] - prev_close).abs()], axis=1).max(axis=1).iloc[1:]
    tr = tr.dropna().tail(n)
    if tr.empty:
        return None
    v = float(tr.mean())
    return v if v > 0 and math.isfinite(v) else None


def reaction(df: Any, event_date: Any, nifty_df: Any = None) -> Optional[dict]:
    """Event-day reaction from daily OHLCV.

    The event day is the first bar on/after ``reaction_date(event_date)``. When no such bar exists
    yet (pre-open, or the stock has not traded since the filing) the dict still carries the base
    stats (ATR, last bar high/low/close, turnover) with ``is_event_day=False`` and the return
    fields None. Needs >= 5 bars before the event day."""
    d = _ohlcv(df)
    rdate = reaction_date(event_date)
    if d is None or rdate is None:
        return None
    ts = pd.Timestamp(rdate)
    after = d[d.index >= ts]
    is_event = not after.empty
    if is_event:
        ev_i = d.index.get_loc(after.index[0])
        prior = d.iloc[:ev_i]
        upto = d.iloc[: ev_i + 1]
    else:
        prior, upto = d, d
    if len(prior) < 5:
        return None
    p20 = prior.tail(20)
    avg_vol = float(p20["Volume"].mean()) if p20["Volume"].notna().any() else None
    turnover = p20["Close"] * p20["Volume"]
    avg_turnover_cr = float(turnover.mean()) / 1e7 if turnover.notna().any() else None
    last = upto.iloc[-1]
    out: Dict[str, Any] = {
        "is_event_day": is_event, "event_date": (upto.index[-1].date() if is_event else rdate),
        "atr14": _atr(upto.tail(15)), "avg_turnover_cr": avg_turnover_cr, "avg_volume_20d": avg_vol,
        "last_high": float(last["High"]), "last_low": float(last["Low"]), "last_close": float(last["Close"]),
        "prior_20d_high": float(p20["High"].max()), "prior_20d_low": float(p20["Low"].min()),
        "ret_pct": None, "ret_vs_nifty_pct": None, "gap_pct": None, "rel_vol": None, "close_pos": None,
        "above_20d_high": False, "below_20d_low": False, "circuit_locked": False, "circuit_band_pct": None,
        "band_distance_pct": None, "sessions_since": 0,
    }
    if not is_event:
        return out
    ev = after.iloc[0]
    prev_close = float(prior["Close"].iloc[-1])
    o, h, lo, c, v = (float(ev[k]) for k in ("Open", "High", "Low", "Close", "Volume"))
    if prev_close <= 0:
        return out
    ret = (c / prev_close - 1) * 100
    out.update({
        "prev_close": prev_close, "open": o, "high": h, "low": lo, "close": c,
        "ret_pct": round(ret, 2), "gap_pct": round((o / prev_close - 1) * 100, 2),
        "rel_vol": (round(v / avg_vol, 2) if avg_vol and avg_vol > 0 and math.isfinite(v) else None),
        "above_20d_high": c > out["prior_20d_high"], "below_20d_low": c < out["prior_20d_low"],
        "sessions_since": int(len(d) - ev_i - 1),
    })
    rng = h - lo
    out["close_pos"] = round((c - lo) / rng, 3) if rng > 0 else (1.0 if ret > 0 else 0.0 if ret < 0 else 0.5)
    band = next((b for b in CIRCUIT_BANDS if abs(ret) <= b + 0.25), None)
    if band is not None:
        out["circuit_band_pct"] = band
        out["band_distance_pct"] = round(band - abs(ret), 2)
        at_extreme = (c >= h - 1e-9) if ret > 0 else (c <= lo + 1e-9)
        out["circuit_locked"] = abs(abs(ret) - band) <= 0.25 and at_extreme
    n = _ohlcv(nifty_df)
    if n is not None:
        nb = n[n.index <= after.index[0]]
        if len(nb) >= 2 and nb.index[-1] == after.index[0]:
            nret = (float(nb["Close"].iloc[-1]) / float(nb["Close"].iloc[-2]) - 1) * 100
            out["nifty_ret_pct"] = round(nret, 2)
            out["ret_vs_nifty_pct"] = round(ret - nret, 2)
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Freshness
# ─────────────────────────────────────────────────────────────────────────────

def _is_session(d: _dt.date, holidays: Optional[Iterable[str]]) -> bool:
    return d.weekday() < 5 and (holidays is None or d.isoformat() not in holidays)


def sessions_between(t0: Any, t1: Any, holidays: Optional[Iterable[str]] = None) -> Optional[int]:
    """Number of session closes (15:30 IST) in (t0, t1]."""
    a, b = _to_ist(t0), _to_ist(t1)
    if a is None or b is None:
        return None
    if b <= a:
        return 0
    hol = frozenset(holidays) if holidays is not None else None
    n, d = 0, a.date()
    while d <= b.date() and n < 60:
        close = _dt.datetime.combine(d, SESSION_CLOSE, tzinfo=IST)
        if a < close <= b and _is_session(d, hol):
            n += 1
        d += _dt.timedelta(days=1)
    return n


def freshness(elapsed: Optional[int], *, kind: str = "", strong_reaction: bool = False) -> float:
    if elapsed is None:
        return 0.0
    if elapsed <= 0:
        return 1.0
    if elapsed == 1:
        return 0.6
    if elapsed == 2:
        return 0.3
    if kind == "results" and strong_reaction and elapsed <= 5:
        return 0.5
    return 0.0


# ─────────────────────────────────────────────────────────────────────────────
# Combined read
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class CatalystRead:
    symbol: str
    action: str                         # BUY | SELL | WATCH
    strength: int
    horizon: str                        # intraday | swing
    reasons: List[str] = field(default_factory=list)
    trigger: Optional[float] = None
    stop: Optional[float] = None
    target: Optional[float] = None
    risk_reward: Optional[float] = None
    warnings: List[str] = field(default_factory=list)
    direction: int = 0
    catalyst: str = ""
    ref_price: Optional[float] = None

    def as_dict(self) -> dict:
        return asdict(self)

    def __getitem__(self, k: str) -> Any:
        return getattr(self, k)


def _event_catalyst(ev: dict, surprise: Optional[dict]) -> Optional[Catalyst]:
    cat = ev.get("catalyst")
    if not isinstance(cat, Catalyst):
        cat = classify_announcement(ev.get("category"), ev.get("headline"), ev.get("detail"))
    if cat is None:
        return None
    if cat.kind == "results":
        if not surprise:
            return Catalyst("results", 0, 0.0, "results (numbers unavailable)")
        sc = float(surprise.get("score") or 0)
        d = 1 if sc >= RESULTS_DIRECTION_SCORE else (-1 if sc <= -RESULTS_DIRECTION_SCORE else 0)
        return Catalyst("results", d, min(1.0, abs(sc) / 60.0), surprise_phrase(surprise))
    return cat


def _r2(x: Optional[float]) -> Optional[float]:
    return None if x is None else round(float(x), 2)


def catalyst_read(symbol: str, events: Sequence[dict], surprise: Optional[dict], reaction: Optional[dict], *,
                  preopen: Optional[dict] = None, avg_turnover_cr: Optional[float] = None,
                  now: Any = None, live: Optional[dict] = None, opening_range: Optional[dict] = None,
                  price_band_pct: Optional[float] = None,
                  holidays: Optional[Iterable[str]] = None) -> Optional[CatalystRead]:
    """Combine fresh events + results surprise + price/volume into one BUY / SELL / WATCH read.

    ``live``: {"price", "chg_pct", "rel_vol"?, "high"?, "low"?, "prev_close"?} for market-hours runs.
    ``opening_range``: {"high", "low"} of the first 15 minutes. See the module docstring table."""
    try:
        return _catalyst_read(symbol, events, surprise, reaction, preopen=preopen, avg_turnover_cr=avg_turnover_cr,
                              now=now, live=live, opening_range=opening_range, price_band_pct=price_band_pct,
                              holidays=holidays)
    except (TypeError, ValueError, KeyError, ZeroDivisionError, AttributeError):
        return None


def _catalyst_read(symbol, events, surprise, reaction, *, preopen, avg_turnover_cr, now, live, opening_range,
                   price_band_pct, holidays) -> Optional[CatalystRead]:
    rx = reaction if isinstance(reaction, dict) else {}
    pre = preopen if isinstance(preopen, dict) else {}
    lv = live if isinstance(live, dict) else {}
    now_t = _to_ist(now) or _dt.datetime.now(IST)

    price = _f(lv.get("price")) or _f(pre.get("iep")) or _f(rx.get("close")) or _f(rx.get("last_close"))
    turnover = _f(avg_turnover_cr) if avg_turnover_cr is not None else _f(rx.get("avg_turnover_cr"))
    if turnover is None or turnover < MIN_TURNOVER_CR or price is None or price < MIN_PRICE:
        return None

    strong_up = (rx.get("is_event_day") and (rx.get("close_pos") or 0) >= 0.75 and (rx.get("rel_vol") or 0) >= 2)
    strong_dn = (rx.get("is_event_day") and rx.get("close_pos") is not None and rx["close_pos"] <= 0.25
                 and (rx.get("rel_vol") or 0) >= 2)
    scored = []
    for ev in events or []:
        if not isinstance(ev, dict):
            continue
        cat = _event_catalyst(ev, surprise)
        if cat is None or cat.direction == 0 or cat.weight <= 0:
            continue
        when = _to_ist(ev.get("when"))
        if when is None:
            continue
        elapsed = sessions_between(when, now_t, holidays)
        strong = strong_up if cat.direction > 0 else strong_dn
        fr = freshness(elapsed, kind=cat.kind, strong_reaction=bool(strong))
        if fr <= 0:
            continue
        scored.append((cat.direction * cat.weight * fr, cat, elapsed))
    if not scored:
        return None
    net = sum(s for s, _, _ in scored)
    if abs(net) < 1e-9:
        return None
    d = 1 if net > 0 else -1
    same = sorted([x for x in scored if x[0] * d > 0], key=lambda x: -abs(x[0]))
    lead_cat, lead_elapsed = same[0][1], same[0][2]
    horizon = "intraday" if lead_elapsed == 0 else "swing"

    # Price confirmation
    if lv.get("chg_pct") is not None:
        move, move_txt = _f(lv.get("chg_pct")), "today"
    elif pre.get("gap_pct") is not None:
        move, move_txt = _f(pre.get("gap_pct")), "gap"
    elif rx.get("is_event_day"):
        move, move_txt = _f(rx.get("ret_pct")), "reaction day"
    else:
        move, move_txt = None, ""
    rel_vol = _f(lv.get("rel_vol")) if lv.get("rel_vol") is not None else (
        _f(rx.get("rel_vol")) if rx.get("is_event_day") else None)

    reasons = [c.label for _, c, _ in same[:2]]
    if move is not None:
        reasons.append(f"gap {move:+.1f}%" if move_txt == "gap" else f"{move_txt} {move:+.1f}%")
    if rel_vol is not None:
        reasons.append(f"{rel_vol:.1f}x volume")
    if d > 0 and rx.get("above_20d_high"):
        reasons.append("broke 20-day high")
    elif d < 0 and rx.get("below_20d_low"):
        reasons.append("broke 20-day low")
    warnings: List[str] = []
    action = "BUY" if d > 0 else "SELL"
    sd = move * d if move is not None else None          # signed in the catalyst's direction
    if sd is None:
        action = "WATCH"
        warnings.append("waiting for price confirmation")
    elif sd <= -CONFIRM_MOVE_PCT:
        action = "WATCH"
        reasons.insert(1, "good news sold into" if d > 0 else "bad news bought")
    elif sd < CONFIRM_MOVE_PCT:
        action = "WATCH"
        warnings.append("no price follow-through yet")
    elif sd > EXTENDED_MOVE_PCT or (rx.get("circuit_locked") and (rx.get("ret_pct") or 0) * d > 0):
        action = "WATCH"
        warnings.append(EXTENDED_WARNING)
    elif rel_vol is not None and rel_vol < MIN_REL_VOL:
        action = "WATCH"
        warnings.append(f"volume not confirming ({rel_vol:.1f}x)")

    # Plan
    atr = _f(rx.get("atr14"))
    orr = opening_range if isinstance(opening_range, dict) else {}
    or_hi, or_lo = _f(orr.get("high")), _f(orr.get("low"))
    last_hi = _f(rx.get("high")) if rx.get("is_event_day") else _f(rx.get("last_high"))
    last_lo = _f(rx.get("low")) if rx.get("is_event_day") else _f(rx.get("last_low"))
    if d > 0:
        if or_hi:
            trig = or_hi
        elif lv.get("price") is not None:
            trig = _f(lv.get("high")) or price
        elif pre.get("iep") is not None:
            trig = max(_f(pre.get("iep")) or 0, last_hi or 0)
        else:
            trig = last_hi
    else:
        if or_lo:
            trig = or_lo
        elif lv.get("price") is not None:
            trig = _f(lv.get("low")) or price
        elif pre.get("iep") is not None:
            cands = [x for x in (_f(pre.get("iep")), last_lo) if x]
            trig = min(cands) if cands else None
        else:
            trig = last_lo
    stop = target = rr = None
    if not atr or not trig:
        if action != "WATCH":
            warnings.append("no ATR / reference level — no plan")
        action = "WATCH"
    else:
        k = 0.5 if horizon == "intraday" else 1.0
        stop = trig - d * k * atr
        if horizon == "intraday":
            if d > 0 and or_lo is not None:
                stop = min(stop, or_lo)
            if d < 0 and or_hi is not None:
                stop = max(stop, or_hi)
        risk = (trig - stop) * d
        if risk <= 0:
            stop = target = None
            action = "WATCH"
        else:
            target = trig + d * TARGET_R * risk
            ref_close = _f(lv.get("prev_close")) or _f(pre.get("prev_close")) or _f(rx.get("last_close"))
            if price_band_pct and ref_close:
                cap = ref_close * (1 + d * float(price_band_pct) / 100.0)
                target = min(target, cap) if d > 0 else max(target, cap)
            rr = (target - trig) * d / risk
            if rr < MIN_RR:
                if action != "WATCH":
                    warnings.append(f"reward/risk under {MIN_RR:g}R ({rr:.1f}R)")
                action = "WATCH"
    if d < 0:
        warnings.append(SELL_WARNING)

    cat_c = min(1.0, abs(net))
    vol_c = _clamp((rel_vol - 1) / 2, 0, 1) * 25 if rel_vol is not None else 8.0
    move_c = _clamp(abs(move) / 4, 0, 1) * 25 if (sd is not None and sd >= CONFIRM_MOVE_PCT) else 0.0
    strength = 50 * cat_c + vol_c + move_c
    if action == "WATCH":
        strength *= 0.6
    return CatalystRead(
        symbol=str(symbol).upper(), action=action, strength=int(round(_clamp(strength, 0, 100))), horizon=horizon,
        reasons=reasons[:4], trigger=_r2(trig), stop=_r2(stop), target=_r2(target),
        risk_reward=None if rr is None else round(rr, 2), warnings=warnings, direction=d,
        catalyst=lead_cat.kind, ref_price=_r2(price),
    )


def rank_reads(reads: Iterable[Any]) -> List[Any]:
    """Strength desc, BUY/SELL ahead of WATCH on ties, one read per symbol (the strongest)."""
    def _get(r, k, default=None):
        return r.get(k, default) if isinstance(r, dict) else getattr(r, k, default)
    valid = [r for r in reads or [] if r is not None and _get(r, "symbol")]
    valid.sort(key=lambda r: (-(_get(r, "strength") or 0), _get(r, "action") == "WATCH"))
    seen, out = set(), []
    for r in valid:
        s = str(_get(r, "symbol")).upper()
        if s not in seen:
            seen.add(s)
            out.append(r)
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Why did it move?
# ─────────────────────────────────────────────────────────────────────────────

NO_EVIDENCE = "no filing or news found — move not explained by public data"


def explain_move(symbol: str, day_return_pct: float, *, events: Sequence[dict] = (), surprise: Optional[dict] = None,
                 reaction: Optional[dict] = None, sector_return_pct: Optional[float] = None,
                 nifty_return_pct: Optional[float] = None) -> List[str]:
    """Ordered plain-language reasons for a big move, from evidence only (never invents one)."""
    out: List[str] = []
    ret = _f(day_return_pct) or 0.0
    sign = 1 if ret > 0 else -1
    evidence = False
    if surprise:
        out.append(surprise_phrase(surprise, numbers=True))
        evidence = True
    seen_kinds = set()
    for ev in events or []:
        if not isinstance(ev, dict):
            continue
        cat = ev.get("catalyst") if isinstance(ev.get("catalyst"), Catalyst) else classify_announcement(
            ev.get("category"), ev.get("headline"), ev.get("detail"))
        if cat is None or cat.kind in seen_kinds:
            continue
        if cat.kind == "results":
            if not surprise:
                out.append("quarterly results filed (numbers not available)")
                evidence = True
            seen_kinds.add(cat.kind)
            continue
        seen_kinds.add(cat.kind)
        head = re.sub(r"\s+", " ", str(ev.get("headline") or ev.get("detail") or "")).strip()
        out.append(f"{cat.label}: {head[:70]}" if head and head.lower() != cat.label.lower() else cat.label)
        evidence = True
        if len(seen_kinds) >= 3:
            break
    sec = _f(sector_return_pct)
    if sec is not None and abs(sec) >= 1.0 and sec * sign > 0:
        out.append(f"whole sector {sec:+.1f}%")
        evidence = True
    nif = _f(nifty_return_pct)
    if nif is not None and abs(nif) >= 0.8 and nif * sign > 0:
        out.append(f"market-wide move: Nifty {nif:+.1f}%")
        evidence = True
    if not evidence:
        out.append(NO_EVIDENCE)
    rx = reaction if isinstance(reaction, dict) else {}
    rv = _f(rx.get("rel_vol"))
    if rv is not None and rv >= 1.5:
        out.append(f"{rv:.1f}x normal volume")
    if rx.get("circuit_locked") and rx.get("circuit_band_pct"):
        out.append(f"locked at the {rx['circuit_band_pct']:g}% {'upper' if sign > 0 else 'lower'} circuit")
    elif sign > 0 and rx.get("above_20d_high"):
        out.append("broke its 20-day high")
    elif sign < 0 and rx.get("below_20d_low"):
        out.append("broke below its 20-day low")
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Grading the feature's own record
# ─────────────────────────────────────────────────────────────────────────────

def _bars(x: Any) -> List[tuple]:
    """-> [(date, high, low, close)] ascending, from a DataFrame, Series or list of dicts."""
    out: List[tuple] = []
    if isinstance(x, pd.DataFrame):
        cols = {str(c).lower(): c for c in x.columns}
        if "close" not in cols:
            return []
        for idx, row in x.iterrows():
            c = _f(row[cols["close"]])
            if c is None:
                continue
            h = _f(row[cols["high"]]) if "high" in cols else c
            lo = _f(row[cols["low"]]) if "low" in cols else c
            out.append((_as_date(idx), h if h is not None else c, lo if lo is not None else c, c))
    elif isinstance(x, pd.Series):
        for idx, v in x.items():
            c = _f(v)
            if c is not None:
                out.append((_as_date(idx), c, c, c))
    elif isinstance(x, (list, tuple)):
        for r in x:
            if isinstance(r, dict):
                c = _f(r.get("close"))
                if c is None:
                    continue
                out.append((_as_date(r.get("date")), _f(r.get("high")) or c, _f(r.get("low")) or c, c))
    return sorted([b for b in out if b[0] is not None], key=lambda b: b[0])


def grade_picks(picks: Sequence[dict], closes: Dict[str, Any]) -> dict:
    """Grade persisted picks against later bars (from the pick date on).

    Per pick: "not_triggered" (price never crossed the trigger), "stop" (-1R), "hit" (target R) or
    "open" (marked to the last close). A bar touching both stop and target counts as a stop."""
    graded: List[dict] = []
    for p in picks or []:
        if not isinstance(p, dict):
            continue
        sym = str(p.get("symbol") or "").upper()
        act = str(p.get("action") or "").upper()
        trig, stop, tgt = _f(p.get("trigger")), _f(p.get("stop")), _f(p.get("target"))
        start = _as_date(p.get("date"))
        if act not in ("BUY", "SELL") or not trig or stop is None or tgt is None or start is None:
            continue
        d = 1 if act == "BUY" else -1
        risk = (trig - stop) * d
        if risk <= 0:
            continue
        bars = [b for b in _bars((closes or {}).get(sym)) if b[0] >= start]
        status, r_mult, entered_on, exit_on = "not_triggered", None, None, None
        for dt_, h, lo, c in bars:
            if entered_on is None:
                if (h >= trig) if d > 0 else (lo <= trig):
                    entered_on = dt_
                else:
                    continue
            hit_stop = (lo <= stop) if d > 0 else (h >= stop)
            hit_tgt = (h >= tgt) if d > 0 else (lo <= tgt)
            if hit_stop:
                status, r_mult, exit_on = "stop", -1.0, dt_
                break
            if hit_tgt:
                status, r_mult, exit_on = "hit", round((tgt - trig) * d / risk, 2), dt_
                break
            status, r_mult = "open", round((c - trig) * d / risk, 2)
        graded.append({**{k: p.get(k) for k in ("symbol", "action", "date", "trigger", "stop", "target")},
                       "status": status, "r": r_mult, "entered_on": entered_on, "exit_on": exit_on})
    closed = [g for g in graded if g["status"] in ("hit", "stop")]
    entered = [g for g in graded if g["r"] is not None]
    summary = {
        "n": len(graded), "hit": sum(g["status"] == "hit" for g in graded),
        "stop": sum(g["status"] == "stop" for g in graded), "open": sum(g["status"] == "open" for g in graded),
        "not_triggered": sum(g["status"] == "not_triggered" for g in graded),
        "avg_r": round(float(np.mean([g["r"] for g in entered])), 2) if entered else None,
        "win_rate": round(sum(g["status"] == "hit" for g in closed) / len(closed), 3) if closed else None,
    }
    return {"picks": graded, "summary": summary}
