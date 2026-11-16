"""Today's Movers view, rendered by dashboard/pages/02_markets.py via render().

Shows what the intraday movers radar (alerts/movers_alerts.py) sent today: every NSE stock that
crossed its market-cap tier's move threshold, whether it was on last evening's Tomorrow's
Watchlist and at what rank, why it moved (filings / volume only), and how similar past moves did
over the next 5 sessions vs the Nifty. Reads stored results only (KV), so it renders instantly and
with the network blocked; the radar itself runs every 15 minutes in market hours.
"""
from __future__ import annotations


def _load(day: str):
    try:
        import trade_store as store
        return store.kv_get(f"movers_radar:{day}", None, user_id="_system")
    except Exception:                                       # noqa: BLE001
        return None


def _evidence():
    try:
        import trade_store as store
        return store.kv_get("movers_evidence", None, user_id="_system")
    except Exception:                                       # noqa: BLE001
        return None


def render() -> None:
    import datetime as dt

    import pandas as pd
    import streamlit as st

    from analysis.movers import BAND_LABEL, BANDS, MOVE_BUCKETS, THRESHOLD_PCT, WATCHLIST_MIN_PCT, \
        chase_lookup, evidence_phrase

    st.markdown('<h2 class="page-title-serif">Today\'s <em>Movers</em></h2>', unsafe_allow_html=True)
    st.caption(
        "Every NSE stock that moved up past its tier's threshold today — large caps from "
        f"+{THRESHOLD_PCT['Large']:g}%, mid +{THRESHOLD_PCT['Mid']:g}%, small +{THRESHOLD_PCT['Small']:g}%, "
        f"micro / other +{THRESHOLD_PCT['Micro']:g}% — plus any Tomorrow's Watchlist name (any rank) "
        f"up {WATCHLIST_MIN_PCT:g}%+. Sent to Telegram as it happens (09:45–15:25 IST)."
    )

    ist = dt.timezone(dt.timedelta(hours=5, minutes=30))
    today = dt.datetime.now(ist).date()
    rows, shown_day = None, None
    for back in range(0, 6):
        d = today - dt.timedelta(days=back)
        got = _load(d.isoformat())
        if isinstance(got, list) and got:
            rows, shown_day = got, d
            break
    evidence = _evidence()
    table = (evidence or {}).get("table") if isinstance(evidence, dict) else None

    if not rows:
        st.info("No movers recorded yet. The radar starts at 09:45 IST on trading days; "
                "this view fills in as alerts go out.", icon="📡")
    else:
        if shown_day != today:
            st.caption(f"Showing the last trading day with movers: {shown_day:%a %d %b}.")
        for band in BANDS:
            items = [r for r in rows if r.get("band") == band]
            if not items:
                continue
            st.markdown(f"**{BAND_LABEL[band]}** · {len(items)}")
            df = pd.DataFrame([{
                "Time": r.get("time", ""),
                "Stock": r.get("symbol", ""),
                "Move %": r.get("pct"),
                "Price ₹": r.get("price"),
                "Tomorrow's Watchlist": (f"#{r['watchlist'][1]} {r['watchlist'][0]}"
                                         if r.get("watchlist") else "—"),
                "Why": "; ".join(r.get("why") or []) or "no filing found",
                "Similar past moves": evidence_phrase(chase_lookup(table, band, r.get("pct"),
                                                                   r.get("vol_ratio"))),
            } for r in sorted(items, key=lambda x: -(x.get("pct") or 0))])
            st.dataframe(df, hide_index=True, use_container_width=True,
                         column_config={"Move %": st.column_config.NumberColumn(format="%+.1f%%"),
                                        "Price ₹": st.column_config.NumberColumn(format="₹%.2f")})

    with st.expander("📊 Is it worth chasing a big up-day? (the record)", expanded=not rows):
        if not table:
            st.caption("The record is built weekly from stored price history (Movers Evidence job). "
                       "It has not run yet.")
            return
        st.caption(f"Every past up-day in the scan universe, {evidence.get('nifty_from', '?')} to "
                   f"{evidence.get('nifty_to', '?')}: the stock's return 5 sessions later minus the "
                   "Nifty's. History, not a promise.")
        recs = []
        for band in BANDS:
            for m, (lo, hi) in enumerate(MOVE_BUCKETS):
                s = table.get(f"{band}|{m}|any")
                if s:
                    recs.append({"Tier": BAND_LABEL[band],
                                 "Up-day size": f"+{lo:g}% and up" if hi == float("inf") else f"+{lo:g}–{hi:g}%",
                                 "Cases": s["n"], "Median vs Nifty (pts)": s["median_excess"],
                                 "Beat the Nifty": f"{s['beat_pct']:.0f}%"})
        if recs:
            st.dataframe(pd.DataFrame(recs), hide_index=True, use_container_width=True)
