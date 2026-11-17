"""trading/paper_exits.py — replay daily bars to find where an open paper trade exited.

Why this exists
───────────────
Live auto-close (`dashboard/shared/trade_utils._auto_close_breached`) only runs while
the Paper Trades page is open, during market hours, with its toggle on, and it only
compares the *current* price with SL / TP. A trade whose stop or target was touched
while the app was asleep, or touched intraday and then pulled back, therefore stayed
OPEN forever and never reached Closed Trade History.

`find_exit` answers "did this trade's own SL / TP get hit since entry, and where?" from
daily OHLC bars. Pure: no Streamlit, no network, no DB.

Fill rules (BUY; SELL / SHORT mirrored)
───────────────────────────────────────
Bars strictly AFTER the entry date are replayed in order (the entry-day bar mixes
prices from before and after the entry time, so its high / low can't be trusted):
  • open at or below SL            → exit at the open  (gapped through the stop)
  • open at or above TP            → exit at the open  (gapped through the target)
  • low ≤ SL and high ≥ TP same day → exit at SL        (order unknown — assume the worse)
  • low ≤ SL                       → exit at SL
  • high ≥ TP                      → exit at TP
MIS (intraday) trades still open after their entry session are squared off at that
session's close; daily bars can't say whether SL / TP came first inside that day.
"""
from __future__ import annotations

import datetime as _dt
from typing import Optional

import pandas as pd

# Exit reasons — kept short; the history table shows them verbatim.
REASON_STOP = "Stop-loss hit (daily-bar catch-up)"
REASON_TARGET = "Target reached (daily-bar catch-up)"
REASON_GAP_STOP = "Gapped below stop — filled at open (daily-bar catch-up)"
REASON_GAP_TARGET = "Gapped above target — filled at open (daily-bar catch-up)"
REASON_MIS = "MIS square-off at session close (daily-bar catch-up)"


def _to_date(x) -> Optional[_dt.date]:
    try:
        ts = pd.Timestamp(x)
    except Exception:
        return None
    if pd.isna(ts):
        return None
    return ts.date()


def _num(x) -> Optional[float]:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v > 0 and v == v else None


NSE_CLOSE = _dt.time(15, 30)


def mis_session(dates, entry_time) -> Optional[_dt.date]:
    """The session an intraday (MIS) trade belongs to: the entry day if it was entered before
    the 15:30 close on a day with a bar, else the next session with a bar. A trade opened in the
    evening or at the weekend was squared off at a close earlier than its own entry (audit 2026-11)."""
    try:
        ts = pd.Timestamp(entry_time)
    except Exception:
        return None
    if pd.isna(ts):
        return None
    d = ts.date()
    after_close = ts.time() >= NSE_CLOSE
    for x in sorted(dates):
        if x > d or (x == d and not after_close):
            return x
    return None


def find_exit(
    bars: Optional[pd.DataFrame],
    entry_time,
    sl,
    tp,
    *,
    action: str = "BUY",
    product: str = "CNC",
    today: Optional[_dt.date] = None,
) -> Optional[dict]:
    """Return {"exit_price", "exit_date", "reason"} for the first exit, else None.

    bars        daily OHLC frame indexed by date (Open / High / Low / Close columns).
    entry_time  the trade's timestamp (ISO string or datetime, IST wall-clock).
    sl, tp      stop and target; a missing / zero side is ignored.
    action      "BUY" (long) or "SELL" / "SHORT" (short).
    product     "MIS" squares off at the entry session's close once that session is over.
    today       IST date "now" (for MIS: the entry session must be over); defaults to
                the last bar's date + 1 so a full history counts as finished.
    """
    if bars is None or len(bars) == 0:
        return None
    entry_date = _to_date(entry_time)
    if entry_date is None:
        return None
    need = {"Open", "High", "Low", "Close"}
    if not need.issubset(set(bars.columns)):
        return None

    df = bars[["Open", "High", "Low", "Close"]].copy()
    df.index = [_to_date(i) for i in df.index]
    df = df[[d is not None for d in df.index]]
    df = df[~pd.Index(df.index).duplicated(keep="last")].sort_index()
    if df.empty:
        return None

    short = str(action).upper() in ("SELL", "SHORT")
    sl_v, tp_v = _num(sl), _num(tp)

    if str(product).upper() == "MIS":
        if today is None:
            today = df.index[-1] + _dt.timedelta(days=1)
        session = mis_session(df.index, entry_time)
        if session is not None and session < today:
            close = _num(df.loc[session, "Close"])
            if close:
                return {"exit_price": round(close, 2), "exit_date": session,
                        "reason": REASON_MIS}
        return None

    if sl_v is None and tp_v is None:
        return None

    for d, row in df[df.index > entry_date].iterrows():
        o, h, lo = _num(row["Open"]), _num(row["High"]), _num(row["Low"])
        if o is None or h is None or lo is None:
            continue
        if short:
            # A short loses when price rises to SL, wins when it falls to TP.
            if sl_v and o >= sl_v:
                return {"exit_price": round(o, 2), "exit_date": d,
                        "reason": REASON_GAP_STOP.replace("below", "above")}
            if tp_v and o <= tp_v:
                return {"exit_price": round(o, 2), "exit_date": d,
                        "reason": REASON_GAP_TARGET.replace("above", "below")}
            hit_sl = bool(sl_v and h >= sl_v)
            hit_tp = bool(tp_v and lo <= tp_v)
        else:
            if sl_v and o <= sl_v:
                return {"exit_price": round(o, 2), "exit_date": d, "reason": REASON_GAP_STOP}
            if tp_v and o >= tp_v:
                return {"exit_price": round(o, 2), "exit_date": d, "reason": REASON_GAP_TARGET}
            hit_sl = bool(sl_v and lo <= sl_v)
            hit_tp = bool(tp_v and h >= tp_v)
        if hit_sl:   # both on one day → order unknown, take the worse fill
            return {"exit_price": round(sl_v, 2), "exit_date": d, "reason": REASON_STOP}
        if hit_tp:
            return {"exit_price": round(tp_v, 2), "exit_date": d, "reason": REASON_TARGET}
    return None
