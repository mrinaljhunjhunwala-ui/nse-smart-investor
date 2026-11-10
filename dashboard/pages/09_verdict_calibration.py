"""
📏 Verdict Calibration & Shadow Trades — page 18

The single most important page in the app for a long-term investor: it
answers "is the model actually right?" and "what would you have made if
you'd taken every BUY it emitted?"

Two views, one ledger:

  1. CALIBRATION — for every FinalVerdict the app has ever emitted (from
     the Analyze Stock page + every pick card on Command Centre and
     Watchlist), fetch the forward return at 1d / 5d / 20d / 60d / 250d
     and pair it with the same-day NIFTY return so we compute alpha (excess
     over the index). Then group by verdict / conviction bucket / subsystem
     labels to show a real hit-rate table with Wilson lower bounds — no
     credit for market moves, no fine-print-hiding of small samples.

  2. SHADOW TRADES — every STRONG BUY / BUY the model emitted appears here
     with the P&L you'd have realised holding to the horizon. This is the
     "winners you skipped" list. There's nothing to configure — a shadow
     trade is created automatically the moment a pick card renders or you
     open Analyze Stock. Failure modes are honest: shadow with return -8%
     is a bad call the model made; you don't get to unlog it.

Design notes
────────────
* Everything is FREE data. Forward prices come via data.fetcher.fetch_single
  (Stooq → Yahoo fallback). No new dependency, no API key.
* Backfill runs on page load, at most 200 log rows per call, so a cold
  page comes up in a second or two even after months of accumulation.
* Persistence follows the paper-trades pattern: SQLite by default (ephemeral
  on Streamlit Cloud), Postgres if DATABASE_URL is set (survives redeploys).
  The warning banner from paper trades applies here too — an ephemeral DB
  means every redeploy resets the calibration history. For this feature to
  be worth anything long-term, set DATABASE_URL. See dashboard/DB_SETUP.md.
"""
from __future__ import annotations

import os
import sys
import pathlib

import pandas as pd
import streamlit as st

# ── Path bootstrap (matches the rest of dashboard/pages/*.py) ────────────────
_ROOT = str(pathlib.Path(__file__).resolve().parents[2])
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from analysis import verdict_ledger as _vl        # noqa: E402
import trade_store as _store                       # noqa: E402
from dashboard.shared.design import apply_design   # noqa: E402
from dashboard.shared.nav import render_sidebar    # noqa: E402
from dashboard.shared.chart_helpers import render_top_bar  # noqa: E402
from dashboard.shared.tokens import COLORS as _TK  # noqa: E402
from dashboard.shared.ui_components import section_header  # noqa: E402
from analysis.action_labels import (                       # noqa: E402
    action_display_label as _act_label, verdict_display_label as _vd_label)


# FIX: this page previously called st.set_page_config, violating the
# "only dashboard/app.py may call set_page_config" rule. In practice this
# crashed the page whenever a user navigated to it after visiting any
# other page in the same session. Removed, and adding the shared
# apply_design / render_sidebar / render_top_bar so this internal-facing
# calibration page picks up the same chrome as every other page.
apply_design()
render_sidebar(current="Verdict Calibration")
render_top_bar()

st.markdown('<h1 class="page-title-serif">Verdict <em>Calibration &amp; Shadow Trades</em></h1>', unsafe_allow_html=True)

st.caption(
    "How accurate is the model, really? Every FinalVerdict this app has "
    "emitted is logged silently. This page fetches the forward return for "
    "every one that's had enough time to play out and shows the honest "
    "score — win rate, mean return, alpha vs NIFTY, Wilson lower bound."
)

# ── Stale-code guard ──────────────────────────────────────────────────────────
# Streamlit Cloud's in-place redeploy swaps page files but can keep an OLD
# analysis.verdict_ledger in memory; calling a function added by the deploy
# then crashed the page (AttributeError, 2026-09-30). Reload the module from
# disk once — what a manual reboot does — and only if that still fails, skip
# the newer sections with a notice instead of crashing.
_LEDGER_API = ("backfill_sector_returns", "evaluate_decision_rule",
               "regime_calibration", "REGIME_LOOKBACK_SESSIONS")


def _missing_ledger_api() -> list:
    return [name for name in _LEDGER_API if not hasattr(_vl, name)]


if _missing_ledger_api():
    import importlib
    try:
        _vl = importlib.reload(_vl)
    except Exception as _reload_err:            # never let the guard itself crash
        st.caption(f"Ledger module reload failed: {type(_reload_err).__name__}")
    if _missing_ledger_api():
        st.warning(
            "🔄 **The app was updated but is still running older calibration code.** "
            "The sector baseline, regime split and evidence test are hidden until the "
            "app restarts (Manage app → ⋮ → Reboot app). Everything else below is current.",
            icon="⚠️",
        )
    else:
        st.caption("🔄 Calibration code was refreshed after an app update.")
_NEW_API = not _missing_ledger_api()

# ── What this page was meant to do, and what it does now ─────────────────────
# Dated record of how the measurement changed, so a reader can tell which
# numbers were produced under which rules. Append; never rewrite history.
_PAGE_CHANGES = [
    ("2026-09-24", "Forward horizons counted calendar days, so “20 days” was ~14 sessions.",
     "Horizons are trading sessions after the verdict date."),
    ("2026-09-24", "Missing NIFTY returns fell back to the raw return, crediting market moves as skill.",
     "α is blank (not guessed) when NIFTY's return is unavailable."),
    ("2026-09-27", "Verdicts were dated by the server's UTC clock; early-morning and pre-open scans "
                   "landed on the wrong day.",
     "Each verdict is dated to the NSE session its price came from (IST, weekends and holidays skipped)."),
    ("2026-09-28", "Backfill always took the 200 newest verdicts — too recent to score — so it updated "
                   "0 rows per visit; only 41 of 487 old verdicts ever got a 1-session return.",
     "Backfill picks verdicts whose horizon has actually arrived; the backlog cleared in three visits."),
    ("2026-09-28", "Verdicts whose price history never loads (delisted tickers) were re-fetched forever.",
     "They are retired after 5 confirmed misses; outages and late data never count as misses."),
    ("2026-09-29", "Picks from the same day were treated as independent trials, overstating certainty.",
     "Every table also counts days; the day-based Wilson bound is the honest number."),
    ("2026-09-29", "No view of market conditions — results from one falling month looked general.",
     "“By market regime” splits calls by NIFTY's trend before each call."),
    ("2026-09-29", "No agreed bar for “the model works”, so any number could be read as success.",
     "A pre-registered evidence test (fixed before the data matured; 30-day floor)."),
    ("2026-09-30", "Beating NIFTY couldn't be told apart from the pick's sector simply holding up.",
     "α vs own sector: each pick against a peer basket of its sector's stocks."),
    ("2026-10-02", "One evidence test pooled every market condition, though history shows the "
                   "score's edge only in rising markets.",
     "A second pre-registered test counts only verdicts logged while NIFTY was rising; the first is "
     "unchanged."),
    ("2026-10-05", "A failed ledger read (busy database right after a restart) looked like an empty "
                   "ledger: the evidence test showed “0 verdicts over 0 days”.",
     "A failed read is retried once, then shown as “couldn't read the ledger” — never as zero."),
    ("2026-11-09", "Every list's picks were pooled, so a weak list could hide behind a strong one and "
                   "down-setups were scored as if they were up-calls.",
     "“Results by list” grades each list on its own, after costs, with down-setups as down-calls, "
     "plus a separate pre-registered Tomorrow's Watchlist test."),
]

with st.expander("🛠 What this page was meant to do — and what it does now", expanded=False):
    st.markdown(
        "**Meant to do:** show, honestly, whether the model's past calls were right — "
        "without crediting market moves, hiding small samples or letting anyone pick the "
        "flattering number after the fact.\n\n"
        "**How it has changed:**"
    )
    st.dataframe(
        pd.DataFrame(_PAGE_CHANGES, columns=["Date", "Before", "Now"]),
        hide_index=True, width="stretch",
    )
    st.caption(
        "Still true today: samples are small and come mostly from one falling market; "
        "20-session windows from nearby days overlap; nothing here is investment advice."
    )

# ── Backend + freshness banner ────────────────────────────────────────────────
_backend = _store.backend_name()
if _backend == "sqlite":
    st.warning(
        "🗄 Storage is **SQLite** (ephemeral on Streamlit Cloud). Every redeploy "
        "resets the verdict ledger — a 20-day calibration needs 20 days of "
        "uninterrupted deploy. For durable calibration set **DATABASE_URL** "
        "(Neon/Supabase free tier). See `dashboard/DB_SETUP.md`.",
        icon="⚠️",
    )

# ── Backfill (lazy, capped, silent) ───────────────────────────────────────────
with st.spinner("Fetching forward returns for eligible verdicts…"):
    _stats = _vl.backfill_returns(max_rows=200)
    if _NEW_API:
        _vl.backfill_sector_returns()      # stored bhavcopy closes only — no network

_col1, _col2, _col3, _col4 = st.columns(4)
_col1.metric("Backend", _backend.upper())
_col2.metric("Rows scanned this load", _stats.get("scanned", 0))
_col3.metric("Rows updated", _stats.get("updated", 0))
_col4.metric("Tickers fetched", _stats.get("tickers_fetched", 0))

def _ledger_read_error(df) -> "str | None":
    """Error type if `df` is empty because the ledger read failed. getattr: an
    in-memory module from before a redeploy has no ledger_error()."""
    fn = getattr(_vl, "ledger_error", None)
    return fn(df) if fn else None


def _ledger_unavailable(err: str, what: str) -> None:
    st.warning(
        f"**Couldn't read the verdict ledger right now** ({err}), so {what} is unknown — "
        "not zero. This usually means the database is busy, e.g. just after an app restart; "
        "reload in a minute.",
        icon="⏳",
    )


_ledger = _vl.load_ledger(limit=1_000_000)   # FIX CAL-LIMIT (#26): 5000 dropped the oldest rows
if _ledger_read_error(_ledger):
    _ledger_unavailable(_ledger_read_error(_ledger), "every number on this page")
    st.stop()
if _ledger.empty:
    st.info(
        "No verdicts logged yet. Open the **🔍 Analyze Stock** page for any "
        "ticker, or visit **🎯 Command Centre** / **⭐ My Watchlist** — every "
        "verdict rendered there is captured here automatically. Come back in "
        "a few days once the first 5-day forward returns have played out."
    )
    st.stop()

# ── The answer, in plain words ────────────────────────────────────────────────
# One card with the registered test's state, before any table: "is the model
# working?" Uses all sources, like the test itself. Descriptive only.
if _NEW_API and hasattr(_vl, "plain_summary"):
    _ps_res = _vl.evaluate_decision_rule()
    _ps_h = int(_ps_res["rule"]["horizon_days"])
    _ps_col = f"ret_{_ps_h}d"
    _ps_pending = 0
    if _ps_col in _ledger.columns:
        _ps_wait = _ledger[_ledger["verdict"].isin(_vl.BULLISH_VERDICTS) & _ledger[_ps_col].isna()]
        _ps_pending = int(_ps_wait["logged_date"].nunique())
    _ps = _vl.plain_summary(_ps_res, pending_days=_ps_pending)
    _ps_tone = {"passing": "success", "failing": "warning", "unavailable": "warning"}.get(_ps["state"], "info")
    getattr(st, _ps_tone)(
        f"**Is the model working?** {_ps['headline']}\n\n{_ps['detail']}"
        + (f"\n\n{_ps['so_far']}" if _ps["so_far"] else ""),
        icon={"success": "✅", "warning": "⚠️", "info": "⏳"}[_ps_tone],
    )
    if _ps["state"] in ("too_early", "passing", "failing"):
        _pc1, _pc2 = st.columns(2)
        _pc1.progress(_ps["picks_progress"],
                      text=f"Scored picks: {_ps['picks']} / {_ps['picks_needed']}")
        _pc2.progress(_ps["days_progress"],
                      text=f"Separate days: {_ps['days']} / {_ps['days_needed']}")
        st.caption(
            f"The test: {_ps_h} sessions (~1 month) after each bullish read, did that day's picks "
            "beat the Nifty? It answers only once both bars are full. The tables further down are "
            "the detail behind this card."
        )

# ── Results by list ───────────────────────────────────────────────────────────
# The card above pools every surface. Here each list is graded on its own —
# Top Picks, Momentum Leaders, each Tomorrow's Watchlist bucket — with
# down-setups judged as down-calls, a round-trip cost taken off, and a separate
# pre-registered Watchlist test. Uses every source, before the filter below.
if hasattr(_vl, "results_by_list"):
    st.markdown(section_header("Results by list", "each list on its own · after costs"),
                unsafe_allow_html=True)
    _rbl_rows = _vl.with_list_buckets(_ledger)
    _rbl_h = st.radio("Window", [5, 20], index=0, horizontal=True, key="_rbl_h",
                      format_func=lambda h: f"{h} sessions" + (" (~1 week)" if h == 5 else " (~1 month)"))
    _rbl = _vl.results_by_list(_rbl_rows, horizons=(_rbl_h,))
    _cost = _rbl.attrs.get("cost_pct", _vl.ROUND_TRIP_COST_PCT)
    if _rbl.empty:
        st.info("No list picks logged yet.")
    else:
        def _rate(r, col):
            if r[f"status_{_rbl_h}"] == "no data":
                return "waiting"
            if r[f"status_{_rbl_h}"] == "too early":
                return f"too early ({int(r[f'days_{_rbl_h}'])} of {_vl.LIST_MIN_DAYS} days)"
            return f"{r[col]:.0f}%"

        def _pts(v):
            return "—" if pd.isna(v) else f"{v:+.2f}%"

        _rbl_show = pd.DataFrame({
            "List": _rbl["list"],
            "What counts as a hit": _rbl["hit_means"],
            "Picks": _rbl[f"picks_{_rbl_h}"],
            "Days": _rbl[f"days_{_rbl_h}"],
            f"Hit vs Nifty ({_rbl_h} days)": [_rate(r, f"hit_pct_{_rbl_h}") for _, r in _rbl.iterrows()],
            "Cautious estimate": [_rate(r, f"hit_lower_pct_{_rbl_h}") for _, r in _rbl.iterrows()],
            "Avg vs Nifty after costs": _rbl[f"avg_vs_nifty_net_{_rbl_h}"].map(_pts),
            "Avg vs Nifty before costs": _rbl[f"avg_vs_nifty_{_rbl_h}"].map(_pts),
        })
        st.dataframe(_rbl_show, hide_index=True, width="stretch")
        _waiting = int((_rbl["picks_logged"] - _rbl[f"picks_{_rbl_h}"]).sum())
        st.caption(
            f"**Hit** = on a given day, that list's picks went the flagged way against the Nifty over "
            f"the next {_rbl_h} sessions by more than a {_cost:.2f}% round-trip cost: up-lists (Top "
            "Picks, Momentum Leaders, breakouts, bullish reversals) by beating the Nifty, down-lists "
            "(breakdown risk, bearish reversals) by lagging it. Each **day** counts once, since "
            "same-day picks share one market move; a name repeated in a list on one day is one pick. "
            "**Cautious estimate** is the 95% lower bound of the hit rate given how few days there "
            f"are; below 50% means no better than a coin flip yet. Rates show once a list has "
            f"{_vl.LIST_MIN_DAYS} scored days. Returns run **close to close** from the close of the "
            "day each pick was logged (the ledger doesn't store next-day opens, so a Tomorrow's "
            f"Watchlist pick isn't priced at the next open). {_waiting:,} logged pick(s) are still "
            "inside their window. Past model output only, not investment advice."
        )
    if hasattr(_vl, "evaluate_watchlist_rule"):
        _wr = _vl.evaluate_watchlist_rule(_rbl_rows)
        _wrule = _wr["rule"]
        _wtone = {"pass": "success", "fail": "warning"}.get(_wr["status"], "info")
        getattr(st, _wtone)(
            f"**Tomorrow's Watchlist test** (registered {_wrule['registered_on']}): {_wr['summary']}",
            icon={"success": "✅", "warning": "⚠️", "info": "⏳"}[_wtone],
        )
        st.caption(
            f"Fixed in advance: every Watchlist bucket pooled, picks logged from "
            f"{_wrule['logged_from']}, {_wrule['horizon_days']} sessions, at least "
            f"{_wrule['min_verdicts']} scored picks over {_wrule['min_days']} separate days. "
            "Separate from the test in the card above, which it doesn't change."
        )

# ── Source filter ─────────────────────────────────────────────────────────────
# Each surface logs its own verdicts. "All" keeps the pooled view; a single
# source shows how that surface's calls did on their own. The pre-registered
# evidence tests and Shadow trades keep their fixed scope regardless.
_SOURCE_LABELS = {
    "analyze_page": "Analyze Stock",
    "tomorrow_watchlist": "Tomorrow's Watchlist",
    "shadow_auto": "Shadow trades (auto)",
}
_by_source = _ledger.groupby("source").size().to_dict()
_src_choice = st.selectbox(
    "Source",
    options=[None, *sorted(_by_source, key=lambda s: -_by_source[s])],
    format_func=lambda s: (f"All sources ({len(_ledger):,})" if s is None else
                           f"{_SOURCE_LABELS.get(s, s.replace('_', ' ').title())} ({_by_source[s]:,})"),
    key="_cal_source",
    help="Which surface's verdicts to score. Evidence tests and Shadow trades are unaffected.",
)
if _src_choice:
    _ledger = _ledger[_ledger["source"] == _src_choice]


def _src_kw(fn) -> dict:
    """{'source': choice} when `fn` takes it — an in-memory ledger module from
    before a redeploy may not (same failure as the stale-code guard above)."""
    import inspect
    try:
        return {"source": _src_choice} if "source" in inspect.signature(fn).parameters else {}
    except (TypeError, ValueError):
        return {}

# ── Overview strip ────────────────────────────────────────────────────────────
_total = len(_ledger)
_by_verdict = _ledger.groupby("verdict").size().to_dict()
_played_20d = int(_ledger.get("ret_20d", pd.Series()).notna().sum())
_played_60d = int(_ledger.get("ret_60d", pd.Series()).notna().sum())

_o1, _o2, _o3, _o4 = st.columns(4)
_o1.metric("Verdicts logged", f"{_total:,}")
_o2.metric("Shadow trades", f"{int((_ledger['source'] == 'shadow_auto').sum()):,}")
_o3.metric("Played out ≥20d", f"{_played_20d:,}")
_o4.metric("Played out ≥60d", f"{_played_60d:,}")

# ── Live scorecard (out-of-sample record, audit #26) ──────────────────────────
# Each settled call's edge = direction × (return − Nifty return); AVOID calls
# count as ahead when the stock lagged. Stats run over non-overlapping periods
# of the horizon's length, so same-window picks aren't counted as independent.
if hasattr(_vl, "live_scorecard"):
    st.markdown(section_header("Live scorecard", "out-of-sample · since logging began"),
                unsafe_allow_html=True)
    _lc1, _lc2 = st.columns([1, 3])
    _lsc_h = _lc1.selectbox("Horizon", [1, 5, 20], index=1, key="_lsc_h",
                            format_func=lambda h: f"{h} session{'s' if h > 1 else ''}")
    _lsc = _vl.live_scorecard(horizon_days=_lsc_h, **_src_kw(_vl.live_scorecard))
    if _lsc.get("error"):
        st.caption(f"Live scorecard unavailable: {_lsc['error']}")
    elif _lsc["summary"].empty:
        _lc2.caption("No calls have settled at this horizon yet.")
    else:
        _lc2.caption(
            "Edge = return minus the Nifty's over the same window, sign-flipped for AVOID "
            "calls. 'Independent periods' groups calls into non-overlapping "
            f"{_lsc_h}-session blocks — the honest sample size. "
            f"{_lsc['pending']:,} call(s) are still waiting for this horizon to pass."
        )
        _show = _lsc["summary"].rename(columns={
            "side": "Calls", "picks": "Settled", "sessions": "Sessions",
            "independent_periods": "Independent periods", "mean_edge_pct": "Mean edge %",
            "picks_ahead_pct": "Calls ahead %", "periods_ahead_pct": "Periods ahead %",
            "periods_ahead_lower_pct": "Periods ahead, 95% lower %", "t_stat": "t (periods)",
            "evidence": "Read",
        })
        st.dataframe(_show, hide_index=True, width="stretch")
        if not _lsc["timeline"].empty:
            st.line_chart(_lsc["timeline"].set_index("logged_date")["mean_edge_pct"], height=160)
        st.caption("A record of past calls, not a forecast. Educational only — not investment advice.")

# ── Pre-registered evidence tests (fixed before each sample matured) ──────────
@st.cache_data(ttl=3600, show_spinner=False)
def _nifty_history():
    return _vl._fetch_history(_vl.NIFTY_BENCH)


if _NEW_API:
    _nifty_df = _nifty_history()
    if _nifty_df is None:
        _nifty_history.clear()          # don't pin a failed fetch for the cache TTL
    st.markdown(
        '<div class="t-h2" style="margin:14px 0 6px 0">🧾 Pre-registered evidence tests</div>',
        unsafe_allow_html=True,
    )
    _rules = [("All market conditions", None)]
    if hasattr(_vl, "DECISION_RULE_RISING"):
        _rules.append(("Rising NIFTY only", _vl.DECISION_RULE_RISING))
    for _rule_name, _rule_def in _rules:
        _rule_res = (_vl.evaluate_decision_rule(_rule_def, nifty_df=_nifty_df) if _rule_def
                     else _vl.evaluate_decision_rule())
        if _rule_res["status"] == "unavailable":
            st.caption(f"**{_rule_name}.**")
            _ledger_unavailable(_rule_res.get("error") or "unknown error",
                                "this test's progress")
            continue
        _rule = _rule_res["rule"]
        _scope = (f" logged on days when NIFTY was **{_rule['regime'].lower()}** over the prior "
                  f"{_vl.REGIME_LOOKBACK_SESSIONS} sessions" if _rule.get("regime") else "")
        _reads = " + ".join(_vd_label(v).rstrip(" ▲") for v in _rule["verdicts"])
        _rule_txt = (
            f"**{_rule_name}.** At **{_rule['horizon_days']} sessions**, pooling "
            f"**{_reads}** reads{_scope}, with at least **{_rule['min_verdicts']} "
            f"verdicts** across **{_rule['min_days']} separate days**: the day-clustered Wilson lower "
            f"bound on *the day's picks beat NIFTY* must be above **{_rule['threshold_pct']:.0f}%**. "
            f"Registered {_rule['registered_on']}; changing it after seeing results would defeat "
            "its purpose."
        )
        if _rule.get("regime"):
            _rule_txt += (" Added because the 5-year replay found the score's edge only in rising "
                          "markets, while early live verdicts were logged in a falling one.")
        _wl = _rule_res["wilson_lower_days_vs_nifty"]
        _progress = (f"Now: **{_rule_res['n_alpha']}** verdicts over **{_rule_res['alpha_days']}** "
                     "days with a NIFTY return"
                     + (f" · day-clustered Wilson lower vs NIFTY **{_wl:.1f}%**" if _wl is not None
                        else ""))
        st.caption(_rule_txt + (" Scored on **all sources**: the registered rule is not "
                                "re-cut by the source filter." if _src_choice else ""))
        if _rule_res["status"] == "insufficient":
            st.info(f"**Not enough data yet.** {_progress}. Until both floors are reached, no "
                    "conclusion either way is supported.")
        elif _rule_res["status"] == "met":
            st.success(f"**Criterion met.** {_progress}. On its own past calls, the model's picks "
                       "beat NIFTY on enough days to clear the bar. Caveat: forward windows of "
                       "nearby days overlap, so this is weaker evidence than the day count "
                       "suggests. Descriptive only — not advice.")
        else:
            st.warning(f"**Criterion not met.** {_progress}. On its own past calls, the model has "
                       "not yet shown it beats NIFTY more reliably than chance. Descriptive only.")

st.markdown("---")

# ── Section A — Calibration by verdict × horizon ─────────────────────────────
st.markdown(
    '<div class="t-h2" style="margin:14px 0 6px 0">'
    '📊 Hit rate by verdict</div>',
    unsafe_allow_html=True,
)
st.caption(
    "For each verdict, what percent of calls closed positive, and what did "
    "the average call earn vs NIFTY? **Win % (raw)** = forward return > 0; "
    "**Win vs NIFTY %** = beat the index (α > 0), counted only over rows "
    "where the NIFTY return is available (**N α**) — α is shown as blank, "
    "not the raw return, when NIFTY is missing. Wilson lower-bound is the "
    "floor on win rate given the sample size — a 100% win rate on 3 trades "
    "is a Wilson lower of ~44%, not 100%. Horizons are **trading sessions** "
    "after the verdict date."
)
st.caption(
    "⚠️ **Overlap caveat:** picks logged the same day share one market move, "
    "and a ticker viewed on consecutive days has overlapping windows, so rows "
    "are not independent — the row-level Wilson bounds are **optimistic**. "
    "**Days** counts distinct logging days; **Days beating NIFTY %** scores each "
    "day once (did that day's picks beat NIFTY on average?) and its Wilson "
    "lower bound is the more honest number."
)
st.caption(
    "🏭 **vs sector** compares each pick with its sector's peer basket (the daily "
    "median move of the sector's stocks, from stored NSE bhavcopy closes; the pick "
    "is one of them) over the same window. Beating NIFTY but not the sector means "
    "the sector did the work, not the stock selection. At 1–5 sessions it is "
    "noisier: a pick logged intraday was priced mid-session while the basket "
    "starts at that day's close. Blank until the stored closes cover the window."
)

# Shared column labels: raw win vs win-vs-NIFTY are labelled distinctly.
_WIN_COLS = {
    "mean_alpha": "α vs NIFTY %",
    "n_alpha": "N α",
    "win_rate": "Win % (raw)",
    "wilson_lower_win": "Wilson lower % (raw)",
    "win_vs_nifty": "Win vs NIFTY %",
    "wilson_lower_vs_nifty": "Wilson lower vs NIFTY %",
    "wins": "Wins (raw)",
    "n_days": "Days",
    "alpha_days": "Days with α",
    "day_win_vs_nifty": "Days beating NIFTY %",
    "wilson_lower_days_vs_nifty": "Wilson lower (days) vs NIFTY %",
    "mean_alpha_sector": "α vs sector %",
    "n_alpha_sector": "N α sector",
    "win_vs_sector": "Win vs sector %",
    "wilson_lower_vs_sector": "Wilson lower vs sector %",
    "sector_days": "Days with sector α",
    "day_win_vs_sector": "Days beating sector %",
    "wilson_lower_days_vs_sector": "Wilson lower (days) vs sector %",
}

_horizon_choice = st.radio(
    "Horizon",
    options=[1, 5, 20, 60, 250],
    format_func=lambda h: {1: "1 session", 5: "5 sessions", 20: "20 sessions (~1 mo)",
                            60: "60 sessions (~1 qtr)", 250: "250 sessions (~1 yr)"}[h],
    index=2,
    horizontal=True,
    key="_cal_horizon",
)

_cal = _vl.calibration_by(group_col="verdict", horizon_days=_horizon_choice,
                          **_src_kw(_vl.calibration_by))
if _ledger_read_error(_cal):
    _ledger_unavailable(_ledger_read_error(_cal), "the hit rate by verdict")
elif _cal.empty:
    st.info(
        f"No verdicts have played out for the **{_horizon_choice}-session** horizon "
        f"yet. Try a shorter horizon (1/5 sessions), or wait a few sessions."
    )
else:
    _cal = _cal.rename(columns={
        "n": "N",
        "mean_ret": f"Mean {_horizon_choice}-session %",
        "median_ret": f"Median {_horizon_choice}-session %",
        **_WIN_COLS,
    })
    # A brief interpretation line so the user doesn't have to squint.
    _buy_row = _cal[_cal["verdict"].isin(["BUY", "STRONG BUY"])]
    # Internal verdict keys stay as-is; the reader sees descriptive labels.
    st.dataframe(_cal.assign(verdict=_cal["verdict"].map(_vd_label)), hide_index=True, width="stretch")
    if not _buy_row.empty:
        _bw = _buy_row["Wilson lower % (raw)"].max()
        _bwn = _buy_row["Wilson lower vs NIFTY %"].max()
        _ba = _buy_row["α vs NIFTY %"].max()
        _bd = _buy_row["Wilson lower (days) vs NIFTY %"].max()
        _bdays_raw = _buy_row["Days"].max()
        _bdays = 0 if pd.isna(_bdays_raw) else int(_bdays_raw)
        _ba_txt = "unavailable" if pd.isna(_ba) else f"{_ba:+.2f}%"
        _bwn_txt = "unavailable" if pd.isna(_bwn) else f"{_bwn:.1f}%"
        _bd_txt = "unavailable" if pd.isna(_bd) else f"{_bd:.1f}%"
        st.caption(
            f"👀 Uptrend / Strong Trend reads at {_horizon_choice} sessions: Wilson-lower raw win "
            f"rate **{_bw:.1f}%**, Wilson-lower win vs NIFTY **{_bwn_txt}** (rows), "
            f"**{_bd_txt}** counting each of the **{_bdays}** day(s) once; best mean α "
            f"**{_ba_txt}**. Below 50% means not yet reliably better than a coin flip."
        )

# ── Section A2 — Same calls, split by market regime ──────────────────────────
if _NEW_API:
    st.markdown(
        '<div class="t-h2" style="margin:18px 0 6px 0">🌗 By market regime</div>',
        unsafe_allow_html=True,
    )
    st.caption(
        f"Uptrend / Strong Trend reads split by whether NIFTY was rising or falling over the "
        f"{_vl.REGIME_LOOKBACK_SESSIONS} sessions **before** each call (no look-ahead). A model "
        "that only looks good in one regime has learned the market, not the stocks."
    )

    _reg = _vl.regime_calibration(horizon_days=_horizon_choice, nifty_df=_nifty_df,
                                  **_src_kw(_vl.regime_calibration))
    if _ledger_read_error(_reg):
        _ledger_unavailable(_ledger_read_error(_reg), "the regime split")
    elif _reg.empty:
        st.info(f"No Uptrend / Strong Trend reads have played out at {_horizon_choice} sessions yet.")
    else:
        _reg = _reg.rename(columns={
            "regime": "NIFTY regime",
            "n": "N",
            "mean_ret": f"Mean {_horizon_choice}-session %",
            "median_ret": f"Median {_horizon_choice}-session %",
            **_WIN_COLS,
        })
        st.dataframe(_reg, hide_index=True, width="stretch")
        if (_reg["NIFTY regime"] == "Unknown").all():
            st.caption("NIFTY history unavailable right now, so regimes can't be tagged.")

# ── Section B — Conviction calibration ────────────────────────────────────────
st.markdown("---")
st.markdown(
    '<div class="t-h2" style="margin:14px 0 6px 0">'
    '📈 Conviction calibration</div>',
    unsafe_allow_html=True,
)
st.caption(
    "Does higher conviction actually correlate with higher forward return? "
    "A well-calibrated model shows a clear upward slope. A flat line means "
    "conviction is noise."
)

_ret_col = f"ret_{_horizon_choice}d"
if _ret_col not in _ledger.columns or _ledger[_ret_col].notna().sum() == 0:
    st.info(f"No {_horizon_choice}-day returns computed yet.")
else:
    _cal_df = _ledger[_ledger[_ret_col].notna()].copy()
    if len(_cal_df) < 5:
        st.info(f"Only {len(_cal_df)} data points at {_horizon_choice}d — need at "
                f"least 5 for a meaningful chart.")
    else:
        # Bucket conviction 0-100 in 10-point bins; show mean return per bucket.
        _cal_df["bucket"] = (_cal_df["conviction"] // 10 * 10).astype(int)
        _agg = _cal_df.groupby("bucket").agg(
            mean_ret=(_ret_col, "mean"),
            n=(_ret_col, "count"),
        ).reset_index()
        _agg["mean_ret"] = _agg["mean_ret"].round(2)
        import plotly.graph_objects as go
        from dashboard.shared.chart_helpers import PLOT_COLORS as _PC
        # P2 · adopt the shared `nse_pro` template explicitly + token colours
        _fig = go.Figure()
        _fig.add_bar(x=_agg["bucket"], y=_agg["mean_ret"],
                     text=[f"n={n}" for n in _agg["n"]], textposition="outside",
                     marker_color=[_PC["bear"] if v < 0 else _PC["bull"]
                                   for v in _agg["mean_ret"]])
        _fig.add_hline(y=0, line_dash="dash", line_color=_PC["faint"])
        _fig.update_layout(
            template="nse_pro",
            xaxis_title="Conviction bucket (0-100)",
            yaxis_title=f"Mean {_horizon_choice}-day return %",
            height=360, margin=dict(l=40, r=20, t=20, b=40),
        )
        st.plotly_chart(_fig, width="stretch")

# ── Section C — Per-subsystem hit rate ────────────────────────────────────────
st.markdown("---")
st.markdown(
    '<div class="t-h2" style="margin:14px 0 6px 0">'
    '🧪 Which subsystem is right most often?</div>',
    unsafe_allow_html=True,
)
st.caption(
    "The composite verdict is a decision tree over subsystems. If Technical "
    "Uptrend has a great hit rate but Thesis Positive has a poor one, that tells "
    "you where to lean — and where to improve."
)

_sub_choice = st.selectbox(
    "Subsystem",
    options=["composite_action", "valuation_posture", "thesis_verdict",
             "quality_flags"],
    format_func=lambda k: {
        "composite_action":  "Technical (composite_action)",
        "valuation_posture": "Valuation posture",
        "thesis_verdict":    "Thesis verdict",
        "quality_flags":     "Quality flag severity",
    }[k],
    key="_cal_subsystem",
)
_sub_tbl = _vl.calibration_by(group_col=_sub_choice, horizon_days=_horizon_choice,
                               **_src_kw(_vl.calibration_by))
if _ledger_read_error(_sub_tbl):
    _ledger_unavailable(_ledger_read_error(_sub_tbl), "the subsystem hit rate")
elif _sub_tbl.empty:
    st.info("Not enough data with this subsystem populated yet.")
else:
    _sub_tbl = _sub_tbl.rename(columns={
        "n": "N",
        "mean_ret":         f"Mean {_horizon_choice}-session %",
        "median_ret":       f"Median {_horizon_choice}-session %",
        **_WIN_COLS,
    })
    if _sub_choice == "composite_action":
        _sub_tbl[_sub_choice] = _sub_tbl[_sub_choice].map(_act_label)
    st.dataframe(_sub_tbl, hide_index=True, width="stretch")

# ── Section C-bis — Per-signal-tag hit rate (Tier 1 #3) ──────────────────────
st.markdown("---")
st.markdown(
    '<div class="t-h2" style="margin:14px 0 6px 0">'
    '🔬 Per-signal-tag calibration</div>',
    unsafe_allow_html=True,
)
st.caption(
    "Every verdict is a bundle of individual rules that fired — RSI oversold, "
    "volume surge, a BullEngulfing pattern, a valuation posture, etc. This "
    "table grades **each rule independently** by its own forward return. "
    "Tags with < 5 firings are hidden — they're statistical noise. Sort by "
    "Wilson lower to see which rules are the most reliable regardless of "
    "sample size."
)
_min_n = st.slider("Minimum firings per tag", 3, 30, 5, 1,
                    key="_cal_tag_minn")
_tag_tbl = _vl.tag_calibration(horizon_days=_horizon_choice, min_n=_min_n,
                                **_src_kw(_vl.tag_calibration))
if _ledger_read_error(_tag_tbl):
    _ledger_unavailable(_ledger_read_error(_tag_tbl), "the per-tag hit rate")
elif _tag_tbl.empty:
    st.info(
        "No signal tags with enough firings yet. Every time you open Analyze "
        "Stock, the sub-signals that contributed are recorded — after ~20-30 "
        "verdicts this table becomes meaningful."
    )
else:
    _tag_tbl = _tag_tbl.rename(columns={
        "n": "N", "tag": "Signal tag",
        "mean_ret":         f"Mean {_horizon_choice}-session %",
        "median_ret":       f"Median {_horizon_choice}-session %",
        **_WIN_COLS,
    })
    st.dataframe(_tag_tbl, hide_index=True, width="stretch")

# ── Section D — Shadow trades P&L ─────────────────────────────────────────────
st.markdown("---")
st.markdown(
    '<div class="t-h2" style="margin:14px 0 6px 0">'
    '👥 Shadow trades — the winners you skipped</div>',
    unsafe_allow_html=True,
)
st.caption(
    "Every Strong Trend / Uptrend read the model surfaced (whether or not you paper-"
    "traded it), with the actual return had you held to the horizon."
    + (" Always the auto-logged shadow source; the source filter above doesn't apply."
       if _src_choice else "")
)
_sh_horizon = st.select_slider(
    "Hold horizon",
    options=[1, 5, 20, 60, 250],
    value=20,
    format_func=lambda h: f"{h} sessions",
    key="_sh_horizon",
)
_sh = _vl.shadow_pnl(horizon_days=_sh_horizon)
if _ledger_read_error(_sh):
    _ledger_unavailable(_ledger_read_error(_sh), "the shadow-trade record")
elif _sh.empty:
    st.info(
        "No shadow trades have played out for this horizon yet. Once you "
        "visit **🎯 Command Centre** or **⭐ My Watchlist** a few times, "
        "every Uptrend / Strong Trend card will start showing up here."
    )
else:
    _c1, _c2, _c3, _c4 = st.columns(4)
    _c1.metric("Shadow trades", f"{len(_sh):,}")
    _c2.metric(f"Mean {_sh_horizon}-session return",
               f"{_sh[f'return_{_sh_horizon}d_pct'].mean():+.2f}%")
    if "alpha" in _sh.columns:
        _alpha_ok = _sh["alpha"].dropna()
        _c3.metric("Mean α vs NIFTY",
                   f"{_alpha_ok.mean():+.2f}%" if len(_alpha_ok) else "unavailable",
                   f"n={len(_alpha_ok)}" if len(_alpha_ok) else None)
    _wins = int((_sh[f'return_{_sh_horizon}d_pct'] > 0).sum())
    _c4.metric("Win rate (raw, return > 0)", f"{(_wins/len(_sh)*100):.1f}%",
               f"{_wins}/{len(_sh)}")

    # Colour-code the return column
    def _colour_ret(v):
        try:
            v = float(v)
        except (TypeError, ValueError):
            return ""
        if v > 0:
            return f"color: {_TK['bull']}; font-weight: 600;"
        if v < 0:
            return f"color: {_TK['bear']}; font-weight: 600;"
        return ""
    if "verdict" in _sh.columns:
        _sh = _sh.assign(verdict=_sh["verdict"].map(_vd_label))
    # Styler.map (pandas >= 2.1) replaced applymap, which pandas 3 removed.
    _style_map = getattr(_sh.style, "map", None) or _sh.style.applymap
    _sty = _style_map(
        _colour_ret,
        subset=[c for c in [f"return_{_sh_horizon}d_pct", "alpha"]
                if c in _sh.columns],
    ).format({
        "price_when_logged":        "{:,.2f}",
        f"exit_{_sh_horizon}d":     "{:,.2f}",
        f"return_{_sh_horizon}d_pct": "{:+.2f}%",
        f"nifty_{_sh_horizon}d_pct":  "{:+.2f}%",
        "alpha":                    "{:+.2f}%",
        "conviction":               "{:.0f}",
    }, na_rep="—")
    st.dataframe(_sty, hide_index=True, width="stretch")
    st.caption("Returns and α are close-to-close from the close of the session the "
               "call was logged in. *price_when_logged* is the price the page saw "
               "at logging time (often intraday) — shown for reference, not the "
               "base of the return.")

# ── Section E — Full ledger drilldown ─────────────────────────────────────────
st.markdown("---")
with st.expander("🗄 Full verdict ledger — last 200 entries", expanded=False):
    _keep = ["logged_date", "ticker", "verdict", "conviction", "confidence",
             "horizon", "composite_action", "tqs", "valuation_posture",
             "thesis_verdict", "quality_flags", "source",
             "ret_1d", "ret_5d", "ret_20d", "ret_60d", "ret_250d"]
    _keep = [c for c in _keep if c in _ledger.columns]
    _drill = _ledger[_keep].head(200).copy()
    for _c, _fn in (("verdict", _vd_label), ("composite_action", _act_label)):
        if _c in _drill.columns:
            _drill[_c] = _drill[_c].map(_fn)
    st.dataframe(_drill, hide_index=True, width="stretch")

st.caption(
    "**Sampling caveat:** this ledger reflects tickers you *actually looked at* "
    "or that surfaced in Top Picks / Watchlist — not a uniform sample of the "
    "NSE universe. Use it to judge whether the model was right on the calls "
    "it made to you, not as a market-wide backtest. Note the **🧪 Backtest** "
    "page is not a substitute either: it replays the separate rule-based "
    "RSI-MACD / Momentum strategies, not the composite score or these verdicts."
)
