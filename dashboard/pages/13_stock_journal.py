"""
Stock Journal — NSE Smart Investor.

Log the *reason* you took (or passed on) each stock, along with your target /
stop / review date. This is the missing piece the user asked for in PR #74:
"I don't have a system to keep a log of stocks and a way to keep an eye on
a lot of things".

The journal is a CSV at data/stock_journal.csv managed by
alerts/journal_store.py — a headless module so both this page and the alert
pipeline can read/write the same file with one schema. See the module's
docstring for schema details.

Editorial choices:
  * Simple form (no framework, no ORM) — the CSV is small and one row per
    entry stays grep-friendly if you ever want to browse it in a terminal.
  * Rows kept append-only within a status; "closing" a thesis writes a new
    entry with status='closed' rather than mutating the original, so the
    audit trail survives.
  * No composite score computation on this page — that lives on Analyze
    Stock. A journal entry is a decision record, not a re-analysis.

FIX: page-13 was previously unused (numbering ran 12, 14). Now occupies the
free slot rather than the previously-planned dashboard/pages/23_ path so
the nav order keeps journal near portfolio (3) and watchlist (14) rather
than orphaned at the end.
"""
import os
import sys
import logging
import datetime

_log = logging.getLogger("dashboard.stock_journal")
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

# sys.path bootstrap above must happen before dashboard/alerts imports — same
# pattern as every other page in dashboard/pages/. Silencing E402 here rather
# than restructuring imports so this page stays consistent with 14_my_watchlist etc.
import streamlit as st  # noqa: E402
import pandas as pd  # noqa: E402

from dashboard.shared.design import apply_design  # noqa: E402
from dashboard.shared.nav import render_sidebar  # noqa: E402
from dashboard.shared.chart_helpers import render_top_bar  # noqa: E402
from alerts.journal_store import (  # noqa: E402
    JournalEntry, VALID_STATUS, FIELDNAMES,
    append_entry, read_entries,
)

apply_design()
render_sidebar(current="Stock Journal")
render_top_bar()

st.title("📓 Stock Journal")
st.caption(
    "Your decision log — why you cared about each stock, what target and stop you "
    "had in mind, and when to review. Referenced by the alert digests so you get "
    "context (\"you flagged this for X on Y\") when a name resurfaces. "
    "Not tied to actual trades — that's what My Portfolio and Angel One are for."
)

# ─────────────────────────────────────────────────────────────────────────────
# Add / edit entry
# ─────────────────────────────────────────────────────────────────────────────

with st.expander("➕ Add a new entry", expanded=False):
    with st.form("journal_add"):
        col1, col2 = st.columns(2)
        with col1:
            _tk    = st.text_input("Ticker (NSE symbol)", value="", placeholder="e.g. RELIANCE",
                                    key="j_ticker").strip().upper()
            _thesis = st.text_area(
                "Thesis / reason (one line)",
                value="", placeholder="e.g. 55d breakout on 2x vol; target next resistance",
                key="j_thesis",
            )
            _tags  = st.text_input(
                "Tags (comma-separated)", value="",
                placeholder="delivery, breakout, momentum",
                key="j_tags",
            )
        with col2:
            _entry = st.text_input("Entry target (₹, optional)",  value="", key="j_entry")
            _stop  = st.text_input("Stop-loss (₹, optional)",     value="", key="j_stop")
            _tgt   = st.text_input("Profit target (₹, optional)", value="", key="j_tgt")
            _rev   = st.date_input(
                "Review date (when to re-evaluate)",
                value=datetime.date.today() + datetime.timedelta(days=30),
                key="j_rev",
            )
            _stat  = st.selectbox("Status", options=list(VALID_STATUS),
                                    index=list(VALID_STATUS).index("open"), key="j_stat")

        submitted = st.form_submit_button("Save entry", type="primary")
        if submitted:
            if not _tk:
                st.error("Ticker is required.")
            elif not _thesis:
                st.error("Thesis is required — a blank journal entry defeats the purpose.")
            else:
                try:
                    entry = JournalEntry(
                        ticker=_tk, thesis=_thesis.strip(),
                        entry_target=_entry.strip(), stop=_stop.strip(),
                        target=_tgt.strip(),
                        review_date=_rev.isoformat() if _rev else "",
                        tags=_tags.strip(), status=_stat,
                    )
                    append_entry(entry)
                    st.success(f"Saved: {entry.ticker} ({entry.status})")
                    # No st.rerun() here — user might want to add a related
                    # entry (e.g. same ticker, closed status to lock in a prior
                    # thesis before opening a new one). Let them see the
                    # confirmation and choose.
                except Exception as _e:
                    st.error(f"Could not save entry: {_e}")

# ─────────────────────────────────────────────────────────────────────────────
# List / filter existing entries
# ─────────────────────────────────────────────────────────────────────────────

entries = read_entries()

st.subheader(f"📚 Entries · {len(entries)} total")

if not entries:
    st.info(
        "No entries yet. Every time the morning digest surfaces a name you find "
        "interesting — or the alert flags a holding for EXIT_WATCH — jot it here "
        "with the thesis. Future digests will reference this log so you always "
        "have the context of why you cared."
    )
    st.stop()

# Filter chips
_all_tickers = sorted({e.ticker for e in entries})
_all_tags    = sorted({t.strip() for e in entries for t in e.tags.split(",") if t.strip()})

fc1, fc2, fc3 = st.columns(3)
with fc1:
    _flt_status = st.multiselect(
        "Status", options=list(VALID_STATUS),
        default=["open"], key="jf_status",
    )
with fc2:
    _flt_ticker = st.multiselect(
        "Ticker", options=_all_tickers, default=[], key="jf_ticker",
    )
with fc3:
    _flt_tag = st.multiselect(
        "Tag", options=_all_tags, default=[], key="jf_tag",
    )

def _match(e: JournalEntry) -> bool:
    if _flt_status and e.status not in _flt_status:
        return False
    if _flt_ticker and e.ticker not in _flt_ticker:
        return False
    if _flt_tag:
        row_tags = {t.strip() for t in e.tags.split(",") if t.strip()}
        if not (row_tags & set(_flt_tag)):
            return False
    return True

filtered = [e for e in entries if _match(e)]

if not filtered:
    st.warning("No entries match those filters.")
    st.stop()

# Render as a table, most-recent first
filtered.sort(key=lambda e: e.added_date, reverse=True)

_df = pd.DataFrame([{
    "Ticker":       e.ticker,
    "Added":        e.added_date,
    "Status":       e.status,
    "Thesis":       e.thesis,
    "Entry":        e.entry_target,
    "Stop":         e.stop,
    "Target":       e.target,
    "Review":       e.review_date,
    "Tags":         e.tags,
} for e in filtered])

# Style: colour the status chip
_status_bg = {
    "open":          "#42a5f5",   # blue
    "closed":        "#8d6e63",   # brown
    "passed":        "#78909c",   # grey
    "invalidated":   "#ef5350",   # red
}
def _colour_status(v):
    bg = _status_bg.get(v, "#42a5f5")
    return f"background-color:{bg};color:white;font-weight:600;text-align:center"

_styled = _df.style.map(_colour_status, subset=["Status"])
st.dataframe(_styled, hide_index=True, width="stretch")

# ─────────────────────────────────────────────────────────────────────────────
# Utility: review-due nudge
# ─────────────────────────────────────────────────────────────────────────────

_today = datetime.date.today()
_due = []
for e in entries:
    if e.status != "open" or not e.review_date:
        continue
    try:
        rd = datetime.date.fromisoformat(e.review_date)
    except ValueError:
        continue
    if rd <= _today:
        _due.append((e, rd))

if _due:
    st.markdown("### ⏰ Reviews due")
    for e, rd in sorted(_due, key=lambda x: x[1]):
        _overdue_by = (_today - rd).days
        _overdue_txt = "today" if _overdue_by == 0 else f"{_overdue_by} day(s) ago"
        st.markdown(
            f"- **{e.ticker}** — review was due **{_overdue_txt}** "
            f"({e.review_date}). Thesis: _{e.thesis}_"
        )
else:
    st.caption(
        "No reviews due yet. When a review_date arrives, entries surface here "
        "as a nudge — re-evaluate and add a new entry (closed / passed / open) "
        "to keep the log honest."
    )

# ─────────────────────────────────────────────────────────────────────────────
# Download
# ─────────────────────────────────────────────────────────────────────────────

_csv_bytes = _df.to_csv(index=False).encode("utf-8")
st.download_button(
    "⬇ Export filtered entries to CSV",
    _csv_bytes,
    file_name="stock_journal_export.csv",
    mime="text/csv",
)

st.caption(
    "Journal file lives at `data/stock_journal.csv` — you can edit it directly "
    "with any spreadsheet app if you prefer. Columns: " + ", ".join(FIELDNAMES) + "."
)
