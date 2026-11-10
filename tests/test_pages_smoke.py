"""tests/test_pages_smoke.py — CI page smoke coverage (Part 1).

Loads every Streamlit page headlessly via AppTest and asserts it renders with **no uncaught
exception** (which also catches unresolved imports / NameErrors — the P3 risk). Made
deterministic and CI-safe by **fail-fast network blocking**: outbound sockets raise
immediately, so each page takes its graceful degraded path (the pages already wrap their
fetches — P2) and renders quickly, with no dependence on live Yahoo/NSE.

Marked `smoke`; runs in the default suite and CI. The one slow backtest e2e is separate
(`-m slow`).
"""
from __future__ import annotations

import glob
import os
import socket
import threading
import time

import pytest
from streamlit.testing.v1 import AppTest

_PAGES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "dashboard", "pages")
_PAGES = sorted(glob.glob(os.path.join(_PAGES_DIR, "*.py")))
_IDS = [os.path.basename(p) for p in _PAGES]


@pytest.fixture(scope="module", autouse=True)
def _no_network():
    """Block outbound network so pages take the fast, deterministic degraded path.

    Module-scoped on purpose. As a per-test fixture this block was torn down at
    the end of each test, but the pages under test start their own background
    threads (utils/live_price.get_live_prices_batch runs a ThreadPoolExecutor,
    and its caller returns as soon as its wait expires — see FIX LP3 there).
    Those threads outlive the test that spawned them, so tearing the block down
    per-test let them escape into REAL network calls, with real 6–10s per-tier
    timeouts, while the NEXT test was running. That is what made this file
    non-deterministic and monstrously slow in a full-suite run — the analyze-
    stock page measured 7,754s (2h 9m) in-suite versus ~60s in isolation, and
    which page ended up carrying the blame moved around between runs.

    Holding the block for the whole module means a leaked thread still fails
    fast no matter which test is executing when it wakes up.
    """
    def _blocked(*args, **kwargs):
        raise OSError("network blocked for page smoke test")

    orig_connect = socket.socket.connect
    orig_create  = socket.create_connection
    socket.socket.connect = _blocked
    socket.create_connection = _blocked
    try:
        yield
    finally:
        socket.socket.connect = orig_connect
        socket.create_connection = orig_create


@pytest.fixture(autouse=True)
def _join_page_threads():
    """Wait for the background threads a page starts before the test ends.

    Pages start daemon threads that outlive AppTest.run() — Tomorrow's
    Watchlist's ``_tw_worker`` scan (which logs picks via log_verdict), the
    Command Centre picks scan, live-price pools. conftest.py points
    trade_store at a per-test tmp SQLite by patching a module global, so a
    thread still running when the NEXT test starts writes into THAT test's
    database (seen as an intermittent failure in test_purge_test_rows.py:
    real tickers appearing in its ledger). This fixture tears down before
    conftest's isolation does, so late writes land in this test's own DB.
    With the network blocked the threads finish within seconds; the deadline
    only guards against a genuine hang.

    ``threading.enumerate()`` also lists threads still inside ``start()``
    (not yet marked started), and ``join()`` on one of those raises
    "cannot join thread before it is started" (main run 37058272654, a
    ThreadPoolExecutor worker being spawned as the test ended). So only
    alive threads are joined, and the set is re-read until no new thread is
    left — that also catches threads spawned while we were joining.
    """
    before = set(threading.enumerate())
    yield
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        pending = set(threading.enumerate()) - before
        if not pending:
            break
        alive = [t for t in pending if t.is_alive()]
        if not alive:
            # Only threads mid-start() or mid-exit — they settle in microseconds.
            time.sleep(0.01)
            continue
        for t in alive:
            t.join(timeout=max(0.0, deadline - time.monotonic()))


def test_all_pages_present():
    # Guard: the universe of pages the smoke covers (catches an accidentally-dropped page).
    # 2026-11-09: pages renumbered 01-19 to follow the sidebar order (see
    # test_page_numbers_follow_sidebar_order). File names in the history below
    # are as they were at the time, before that renumber.
    # 17 after merging Macro Dashboard + Market Breadth → Market Internals.
    # 18 after adding 18_tqs_scanner.py.
    # Still 18 after: merging Market Overview + Market Internals → Overview
    # (net -1: 09_market_internals.py deleted) and adding 19_quality_watch.py
    # (net +1) — the two changes cancel out in the page COUNT, but _IDS below
    # will differ (09_market_internals.py gone, 19_quality_watch.py present).
    # Still 18 after: merging OI & Options → Intraday Trader (net -1:
    # 10_oi_options.py deleted, its 3 tabs now live in Intraday Trader) and
    # adding 20_deep_dive.py (net +1) — same cancel-out pattern as above.
    # This assertion will read 19 (not 18) until 10_oi_options.py is manually
    # deleted from the repo — Claude cannot delete files from GitHub directly.
    #
    # 2026-08-30 sprint (calibration/FII-DII): +2 pages
    #   * 21_verdict_calibration.py (Tier 1 #1/#2/#3 — verdict ledger + calibration)
    #   * 22_fii_dii_flows.py       (Tier 2 #6 — FII/DII flow tracker)
    # Renumbered from 18/19 to avoid collision with existing 18_tqs_scanner.py
    # and 19_quality_watch.py. Both are wired into dashboard/shared/nav.py.
    #
    # 2026-08-30 sprint (Analysis-page consolidation): −1 page
    #   * 13_swing_checklist.py removed — its 8-factor go/no-go was folded
    #     into 04_analyze_stock.py via dashboard/shared/checklist_ui.py.
    #
    # 2026-09-09 (PR 3 alerts follow-through): +1 page
    #   * 13_stock_journal.py — reclaims the number vacated by the swing
    #     checklist removal. Backing store is data/stock_journal.csv +
    #     alerts/journal_store.py (already shipped in PR #74). Weekly
    #     digest reads entries added in the last 7 days and reviews due
    #     in the next 7 days.
    #
    # 2026-09-18 (Slice 2 · Deep Dive fold-in): −1 page
    #   * 20_deep_dive.py removed — its indicators / candlestick / mini-
    #     report views were folded into 04_analyze_stock.py as an 8th tab
    #     via dashboard/shared/deep_dive_tab.py. See PR #115.
    #
    # 2026-11-09 (page simplification, owner-approved layout): 19 -> 14 pages.
    #   * Markets (02) = Live Ticker + Market Breadth + FII / DII Flows (view switch)
    #   * Find Ideas (13) = Smart Screener + Trend Quality Score (view switch)
    #   * Watchlist & Journal (07) = My Watchlist + Stock Journal (tabs)
    #   * Trading Tools (12) = Intraday Trader + Position Sizer (view switch)
    #   The merged pages' bodies live in dashboard/views/; each view gets its
    #   own smoke run in test_merged_page_view_loads below.
    assert len(_PAGES) == 14, f"expected 14 pages, found {len(_PAGES)}: {_IDS}"


def test_page_numbers_follow_sidebar_order():
    """File numbers are contiguous 01..N in the order the sidebar lists the
    pages (nav._NAV_GROUPS), and every page file is routed from nav._PAGE_FILE."""
    from dashboard.shared import nav

    ordered = [p for grp in nav._NAV_GROUPS.values() for p in grp]
    files = [os.path.basename(nav._PAGE_FILE[p]) for p in ordered]
    assert files == _IDS, f"sidebar order {files} != files on disk {_IDS}"
    assert [f[:2] for f in files] == [f"{i:02d}" for i in range(1, len(files) + 1)]


@pytest.mark.smoke
@pytest.mark.parametrize("page", _PAGES, ids=_IDS)
def test_page_loads_without_exception(page):
    # Timeout bumped 120 -> 240s (2026-09-04): Streamlit's AppTest is
    # materially slower on Python 3.11 (CI runner) than on 3.12+. Command
    # Centre's ticker sweep + panel rendering routinely lands around
    # 120-130s on 3.11 even after the per-process bench / flows caches in
    # analysis/score.py cut the per-ticker DB work significantly. 240s
    # keeps a comfortable ceiling for the slowest page on the slowest
    # runner without hiding any real regression (a genuine hang is minutes,
    # not just tens of seconds over the old ceiling).
    name = os.path.basename(page)

    # Compile first. Streamlit's ScriptRunner catches compile errors (SyntaxError,
    # IndentationError, ...) itself: it logs "Script compilation error" and fires
    # SCRIPT_STOPPED_WITH_COMPILE_ERROR instead of emitting an exception element.
    # AppTest ignores that event, so ``at.exception`` stays EMPTY and the test
    # used to pass on a page that could not even parse (17_angel_one.py regression).
    with open(page, encoding="utf-8") as fh:
        source = fh.read()
    try:
        compile(source, page, "exec")
    except SyntaxError as e:
        pytest.fail(f"{name} failed to compile: {type(e).__name__}: {e}")

    at = AppTest.from_file(page, default_timeout=240).run()
    # AppTest.exception is an ElementList (falsy when empty), not None.
    assert not at.exception, (
        f"{name} raised an uncaught exception: "
        + "; ".join(str(e.value) for e in at.exception)
    )
    # Belt-and-braces for any other silent bail-out (compile error on a
    # Streamlit version whose handling differs, script never started, ...):
    # render_sidebar() always populates the sidebar, so counting it would make
    # this vacuous. Every page renders at least its top bar / title in the MAIN
    # area, so an empty main tree means the page body never ran.
    rendered = len(at.main.children)
    assert rendered > 0, f"{name} rendered no main-area elements — page body did not run"


def _merged_views():
    from dashboard.shared import nav
    out = []
    for page, (key, labels) in nav._PAGE_VIEWS.items():
        fname = os.path.basename(nav._PAGE_FILE[page])
        out += [(fname, key, label) for label in labels]
    return out


_MERGED_VIEWS = _merged_views()


def test_every_merged_page_has_views():
    pages = {f for f, _, _ in _MERGED_VIEWS}
    assert pages == {"02_markets.py", "12_trading_tools.py", "13_find_ideas.py"}, pages
    assert len(_MERGED_VIEWS) == 7


@pytest.mark.smoke
@pytest.mark.parametrize("fname,key,label", _MERGED_VIEWS,
                         ids=[f"{f}::{lbl}" for f, _, lbl in _MERGED_VIEWS])
def test_merged_page_view_loads(fname, key, label):
    """Each view of a merged page renders with the network blocked, and the
    switch really shows the requested view."""
    at = AppTest.from_file(os.path.join(_PAGES_DIR, fname), default_timeout=240)
    at.session_state[key] = label
    at.run()
    assert not at.exception, (
        f"{fname} [{label}] raised: " + "; ".join(str(e.value) for e in at.exception))
    assert at.session_state[key] == label
    assert len(at.main.children) > 0


@pytest.mark.smoke
def test_watchlist_journal_renders_both_tabs():
    at = AppTest.from_file(os.path.join(_PAGES_DIR, "07_watchlist_journal.py"),
                           default_timeout=240).run()
    assert not at.exception, at.exception
    assert [t.label for t in at.tabs][:2] == ["⭐ My Watchlist", "📓 Stock Journal"]


@pytest.mark.smoke
def test_open_view_flag_selects_view():
    """nav.request_view's one-shot flag (used by legacy _goto_page names and
    the command bar) opens the requested view and is consumed."""
    at = AppTest.from_file(os.path.join(_PAGES_DIR, "02_markets.py"), default_timeout=240)
    at.session_state["_open_mk_view"] = "🏦 FII / DII Flows"
    at.run()
    assert not at.exception, at.exception
    assert at.session_state["mk_view"] == "🏦 FII / DII Flows"
    assert "_open_mk_view" not in at.session_state


@pytest.mark.smoke
def test_sizer_prefill_opens_position_sizer():
    """Analyze Stock's "Size Position" button sets ps_entry/ps_sl/ps_tp and
    switches to Trading Tools; new prefill values open the Position Sizer."""
    at = AppTest.from_file(os.path.join(_PAGES_DIR, "12_trading_tools.py"), default_timeout=240)
    at.session_state["ps_entry"] = 101.5
    at.session_state["ps_sl"] = 97.0
    at.session_state["ps_tp"] = 110.0
    at.run()
    assert not at.exception, at.exception
    assert at.session_state["tt_view"] == "📐 Position Sizer"
    # Without a prefill the page opens on the first view.
    at2 = AppTest.from_file(os.path.join(_PAGES_DIR, "12_trading_tools.py"), default_timeout=240).run()
    assert not at2.exception, at2.exception
    assert at2.session_state["tt_view"] == "⚡ Intraday Trader"


def test_legacy_page_names_resolve():
    from dashboard.shared import nav
    assert nav.resolve_page("📐 Position Sizer") == ("Trading Tools", "📐 Position Sizer")
    assert nav.resolve_page("Market Breadth") == ("Markets", "📊 Breadth & Macro")
    assert nav.resolve_page("🔍 Analyze Stock") == ("Analyze Stock", None)
    assert nav.resolve_page("Quality Watch") == ("Long-Term Quality", None)
    assert nav.resolve_page("nope") == (None, None)
    for old, (new, view) in nav._LEGACY_PAGES.items():
        assert new in nav._PAGE_FILE and nav._PAGE_FILE[old] == nav._PAGE_FILE[new]
        if view:
            assert view in nav._PAGE_VIEWS[new][1], (old, view)
    # Slugs the owner asked to keep (URL = file name minus the number prefix).
    slugs = {os.path.basename(f)[3:-3] for f in nav._PAGE_FILE.values()}
    for keep in ("command_centre", "analyze_stock", "tomorrow_watchlist", "my_portfolio", "paper_trades"):
        assert keep in slugs, keep


def test_command_centre_hero_says_no_read_when_feeds_are_down():
    """replica-test S3 (2026-10-04): with every feed blocked the hero used to
    read "Mixed · no clear trend" under a "range regime" kicker — a market call
    made from no data. It must say the feeds are unavailable instead."""
    at = AppTest.from_file(os.path.join(_PAGES_DIR, "01_command_centre.py"),
                           default_timeout=240).run()
    assert not at.exception, at.exception
    html = "\n".join(str(m.value) for m in at.markdown)
    assert "No read" in html and "market feeds unavailable" in html
    assert "range regime" not in html and "regime unavailable" in html
    # 2026-11-09: the full breadth panel and sector heatmap moved to Markets;
    # Command Centre keeps one summary line plus a link.
    assert "cc-market-line" in html and "NSE breadth unavailable" in html
    assert 'class="heat-grid"' not in html and "Sector heatmap" not in html
    assert any(b.label == "📊 Open Markets" for b in at.button)
