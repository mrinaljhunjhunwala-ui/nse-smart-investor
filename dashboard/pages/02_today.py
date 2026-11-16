"""Today - NSE Smart Investor.

Everything moving today and everything the app sent you, in one place (added 2026-11-17, owner
request). Command Centre stays "market + picks"; this page is "what is moving and what did the
alerts say":

  🚀 Movers           sector moves and the biggest gainers / losers per market-cap tier (from the
                      latest scan), then the movers radar's all-NSE list (the Telegram feed)
  📋 My lists         Tomorrow's Watchlist, My Portfolio, Angel One holdings and open paper trades
                      that moved ±1.5%+
  🔥 Picks            today's Top Picks (all 20) with their move today; ±3% or stop / target flagged
  🔔 Changes & alerts posture changes from the verdict ledger, and every alert sent today

Reads stored scans (KV) first and live quotes second, so it renders with the network blocked.
My Portfolio and Angel One holdings appear only after their PIN is unlocked this session.
"""
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import datetime as _dt  # noqa: E402

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from dashboard.shared.design import apply_design  # noqa: E402
from dashboard.shared.nav import render_sidebar  # noqa: E402
from dashboard.shared.chart_helpers import render_top_bar  # noqa: E402

apply_design()
render_sidebar(current="Today")
render_top_bar()

_IST = _dt.timezone(_dt.timedelta(hours=5, minutes=30))
_TODAY = _dt.datetime.now(_IST).date()

st.markdown('<h1 class="page-title-serif">Today</h1>', unsafe_allow_html=True)
st.caption("What is moving, which of your names moved, how today's picks are doing, and every "
           "alert the app sent you today.")


def _kv(key, user="_system"):
    try:
        import trade_store as store
        return store.kv_get(key, None, user_id=user) if user else store.kv_get(key, None)
    except Exception:
        return None


@st.cache_data(ttl=60, show_spinner=False)
def _quotes(symbols: tuple) -> dict:
    if not symbols:
        return {}
    try:
        from utils.live_price import get_live_prices_batch
        raw = get_live_prices_batch([f"{s}.NS" for s in symbols], max_workers=12) or {}
    except Exception:
        return {}
    return {k.replace(".NS", ""): v for k, v in raw.items() if isinstance(v, dict)}


@st.cache_data(ttl=300, show_spinner=False)
def _angel_holdings() -> list:
    try:
        from data.angel_fetcher import get_holdings
        return get_holdings() or []
    except Exception:
        return []


def _pct(v):
    return st.column_config.NumberColumn(v, format="%+.2f%%")


_RUPEE = st.column_config.NumberColumn("Price ₹", format="₹%.2f")

tab_mv, tab_lists, tab_picks, tab_log = st.tabs(
    ["🚀 Movers", "📋 My lists", "🔥 Picks", "🔔 Changes & alerts"])

# ── 🚀 Movers ──────────────────────────────────────────────────────────────────────────────────
with tab_mv:
    from analysis.movers import BAND_LABEL, BANDS, band_gainers_losers, band_map, sector_moves
    try:
        from dashboard.shared.cache import _persisted_all_scores_snapshot
        scored = _persisted_all_scores_snapshot() or {}
    except Exception:
        scored = {}
    if not scored:
        st.info("No recent scan to read sector and cap-size moves from. The scan refreshes every "
                "45 minutes in market hours.", icon="📡")
    else:
        sec = sector_moves(scored)
        if sec:
            st.markdown("**Sectors** · median move of the scanned names")
            import plotly.graph_objects as go
            from dashboard.shared.chart_helpers import diverging_colors
            show = sec[:6] + [r for r in sec[-6:] if r not in sec[:6]]
            fig = go.Figure(go.Bar(
                x=[r["median_pct"] for r in show], y=[r["sector"] for r in show], orientation="h",
                marker_color=diverging_colors([r["median_pct"] for r in show]),
                text=[f"{r['median_pct']:+.2f}% · {r['up']}/{r['names']} up" for r in show],
                textposition="auto"))
            fig.update_layout(height=34 * len(show) + 40, margin=dict(l=0, r=0, t=10, b=10),
                              yaxis=dict(autorange="reversed"), paper_bgcolor="rgba(0,0,0,0)",
                              plot_bgcolor="rgba(0,0,0,0)", font=dict(size=13))
            st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
        try:
            from data.universe import _CONSTITUENTS
            bands = band_map(_CONSTITUENTS)
        except Exception:
            bands = {}
        st.markdown("**By market cap** · biggest gainers and losers in the scan")
        gl = band_gainers_losers(scored, bands, n=5)
        cols = st.columns(len(BANDS))
        for col, band in zip(cols, BANDS):
            up, down = gl.get(band, ([], []))
            with col:
                st.markdown(f"**{BAND_LABEL[band]}**")
                rows = ([{"Stock": r["symbol"], "Move": r["pct"]} for r in up]
                        + [{"Stock": r["symbol"], "Move": r["pct"]} for r in down])
                if rows:
                    st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True,
                                 column_config={"Move": _pct("Move")})
                else:
                    st.caption("—")
    st.divider()
    st.markdown("**Movers radar** · all NSE stocks, as sent to Telegram")
    try:
        from dashboard.views import todays_movers
        todays_movers.render(show_title=False)
    except Exception as _e:
        st.caption(f"Movers radar unavailable ({type(_e).__name__}).")

# ── 📋 My lists ────────────────────────────────────────────────────────────────────────────────
with tab_lists:
    from analysis.movers import list_moves, watchlist_ranks
    thr = st.slider("Show moves of at least (±%)", 0.5, 5.0, 1.5, 0.5, key="today_list_thr")
    sources = {}
    tw = _kv("tomorrow_watchlist_snapshot")
    ranks = watchlist_ranks(tw.get("data")) if isinstance(tw, dict) else {}
    if ranks:
        sources["Tomorrow's Watchlist"] = {s: f"#{r} {lbl}" for s, (lbl, r, _) in ranks.items()}
    notes = []
    try:
        from dashboard.shared.pin_gate import holdings_unlocked, is_unlocked
    except Exception:
        holdings_unlocked = is_unlocked = None
    if holdings_unlocked and holdings_unlocked():
        hold = _kv("manual_portfolio_holdings", user=None) or []
        mine = {}
        for h in hold if isinstance(hold, list) else []:
            sym = str((h or {}).get("ticker", "")).upper().replace(".NS", "").replace(".BO", "").strip()
            if sym:
                avg = (h or {}).get("avg_buy_price")
                mine[sym] = f"avg ₹{float(avg):,.2f}" if avg else ""
        if mine:
            sources["My Portfolio"] = mine
    else:
        notes.append("My Portfolio is locked — unlock it on the My Portfolio page to include your holdings.")
    try:
        import trade_store as _ts
        _open = _ts.fetch_open()
        _pt = {}
        for _r in (_open.to_dict("records") if _open is not None and len(_open) else []):
            _pt[str(_r.get("ticker", "")).replace(".NS", "")] = (
                f"qty {int(_r.get('quantity') or 0)} @ ₹{float(_r.get('price') or 0):,.2f}")
        if _pt:
            sources["Paper Trades"] = _pt
    except Exception:
        pass
    if is_unlocked and is_unlocked("angel_one"):
        ah = {str(h.get("symbol", "")).upper(): f"qty {h.get('qty')}" for h in _angel_holdings() if h.get("symbol")}
        if ah:
            sources["Angel One"] = ah
        else:
            notes.append("Angel One returned no holdings (not connected, or none held).")
    else:
        notes.append("Angel One is locked — unlock it on the Angel One page to include broker holdings.")
    syms = tuple(sorted({s for items in sources.values() for s in items}))
    moves = list_moves(sources, _quotes(syms), threshold_pct=thr)
    st.caption(f"{len(syms)} names across {', '.join(sources) or 'no lists'} · "
               f"{len(moves)} moved ±{thr:g}% or more today")
    if moves:
        st.dataframe(pd.DataFrame([{
            "Stock": m["symbol"], "Move": m["pct"], "Price ₹": m["price"],
            "From": " · ".join(m["sources"]), "Detail": " · ".join(m["details"])} for m in moves]),
            hide_index=True, use_container_width=True,
            column_config={"Move": _pct("Move"), "Price ₹": _RUPEE})
    elif syms:
        st.info(f"Nothing on your lists has moved ±{thr:g}% yet today (or live quotes are unavailable).",
                icon="📋")
    for n in notes:
        st.caption(n)

# ── 🔥 Picks ───────────────────────────────────────────────────────────────────────────────────
with tab_picks:
    try:
        from dashboard.shared.cache import _persisted_top_picks_snapshot
        tp = _persisted_top_picks_snapshot() or {}
    except Exception:
        tp = {}
    buys = [b for b in (tp.get("buys") or []) if isinstance(b, dict)][:20]
    if not buys:
        st.info("No Top Picks scan yet today. Command Centre runs one on open.", icon="🔥")
    else:
        q = _quotes(tuple(str(b.get("ticker", "")).replace(".NS", "") for b in buys))
        rows = []
        for i, b in enumerate(buys, start=1):
            sym = str(b.get("ticker", "")).replace(".NS", "")
            live = q.get(sym) or {}
            px, chg = live.get("price"), live.get("chg_pct")
            sl, tgt = float(b.get("sl") or 0), float(b.get("tp") or 0)
            flag = ""
            if px and sl and px <= sl:
                flag = "🛑 at / under stop"
            elif px and tgt and px >= tgt:
                flag = "🎯 target reached"
            elif chg is not None and abs(chg) >= 3:
                flag = "⚡ big move"
            rows.append({"#": i, "Stock": sym, "Score": b.get("score"), "Move": chg,
                         "Price ₹": px or b.get("price"), "Stop ₹": sl or None, "Target ₹": tgt or None,
                         "Flag": flag})
        df = pd.DataFrame(rows)
        df["_k"] = df["Flag"].eq("")
        df = df.sort_values(["_k", "#"]).drop(columns="_k")
        st.caption(f"Today's {len(buys)} Top Picks, flagged ones first · scan "
                   f"{str(tp.get('generated_at', ''))[11:16] or '—'}. Command Centre shows the top 10.")
        st.dataframe(df, hide_index=True, use_container_width=True,
                     column_config={"Move": _pct("Move"), "Price ₹": _RUPEE,
                                    "Stop ₹": st.column_config.NumberColumn(format="₹%.2f"),
                                    "Target ₹": st.column_config.NumberColumn(format="₹%.2f")})

# ── 🔔 Changes & alerts ────────────────────────────────────────────────────────────────────────
with tab_log:
    st.markdown("**Posture changes** · latest change per stock (verdict ledger)")
    try:
        from dashboard.shared.cache import get_recent_posture_changes
        from dashboard.shared.trade_utils import verdict_display_label
        changes = get_recent_posture_changes(limit=15)
    except Exception:
        changes = []
    if changes:
        st.dataframe(pd.DataFrame([{
            "Date": str(c.get("date", ""))[5:], "Stock": str(c.get("ticker", "")).replace(".NS", ""),
            "From": verdict_display_label(c.get("prev")), "To": verdict_display_label(c.get("new")),
            "Score": (f"{float(c['prev_score']):.0f} → {float(c['new_score']):.0f}"
                      if c.get("prev_score") is not None and c.get("new_score") is not None else ""),
            "Logged by": str(c.get("source", "")).replace("_", " ")} for c in changes]),
            hide_index=True, use_container_width=True)
    else:
        st.caption("No verdict has changed between logged sessions yet.")
    st.divider()
    log = None
    shown = None
    for back in range(0, 4):
        d = _TODAY - _dt.timedelta(days=back)
        got = _kv(f"alerts_sent:{d.isoformat()}")
        if isinstance(got, list) and got:
            log, shown = got, d
            break
    st.markdown("**Alerts sent** · everything that went to Telegram"
                + ("" if shown in (None, _TODAY) else f" · last on {shown:%a %d %b}"))
    if not log:
        st.caption("No alerts logged yet. Each alert is recorded here from now on.")
    else:
        for a in reversed(log):
            with st.expander(f"{a.get('time', '')} · {a.get('subject', 'Alert')}"):
                st.text(a.get("text", ""))
    st.divider()
    with st.expander("🔔 Background Alerts (Telegram) — fire even when this app is closed", expanded=False):
        st.caption(
            "A GitHub Actions job checks these every 15 min during market hours and "
            "messages you on Telegram. Edit **data/alerts.csv** in your GitHub repo to "
            "change them. Full setup: **alerts/README.md**."
        )
        try:
            import pathlib as _alp
            _alerts_path = _alp.Path(_ROOT) / "data" / "alerts.csv"
            if _alerts_path.exists():
                _al_df = pd.read_csv(_alerts_path)
                _act_df = _al_df[_al_df["enabled"].astype(str).isin(["1", "True", "true"])]
                st.markdown(f"**{len(_act_df)} active** of {len(_al_df)} configured price alerts:")
                if not _act_df.empty:
                    _al_show = _act_df[["ticker", "condition", "level", "note"]].copy()
                    _al_show.columns = ["Stock", "When price goes", "Level (₹)", "Note"]
                    st.dataframe(_al_show, hide_index=True, width="stretch")
                else:
                    from dashboard.shared.ui_components import empty_state as _empty_al
                    st.markdown(
                        _empty_al(
                            title="No active price alerts",
                            hint="All rows are examples (enabled=0). Set "
                                 "`enabled=1` on a row in `data/alerts.csv` to "
                                 "activate it.",
                            icon="🔔",
                        ),
                        unsafe_allow_html=True,
                    )
            else:
                from dashboard.shared.ui_components import empty_state as _empty_al2
                st.markdown(
                    _empty_al2(
                        title="No alerts.csv found yet",
                        hint="Create `data/alerts.csv` with your desired price "
                             "levels to start getting Telegram notifications.",
                        icon="📄",
                    ),
                    unsafe_allow_html=True,
                )
        except Exception as _ale:
            st.caption(f"Could not read alerts.csv: {_ale}")

        st.markdown(
            "**Also alerted automatically:** 📡 movers radar (09:45–15:25) · ⚠️ holdings: sharp falls or bad "
            "filings only · 🔴 VIX entering fear/panic · 📉 Nifty breaking into a downtrend.  \n"
            "**One-time setup:** create a Telegram bot via @BotFather, then add "
            "`TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` as GitHub Actions secrets "
            "(Settings → Secrets and variables → Actions)."
        )
