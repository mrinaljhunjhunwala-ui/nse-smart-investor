# Multipage Refactor — Plan & Progress (branch: refactor/multipage)

The 7.2k-line `dashboard/app.py` is being split into Streamlit multipage architecture.
This file captures the verified analysis so the remaining work is precise and lossless.

## Status

| Stage | Module | State |
|---|---|---|
| 1 | `shared/design.py` | ✅ **Done & import-verified** — `apply_design()`, `nse_pro` Plotly template, `_glass_metric/_section_div/_spacer/_signal_card` |
| 2 | `shared/cache.py` | ✅ **Done & import-verified** (66 names) — `STOCK_SEARCH_MAP`, display/validation helpers, ALL `@st.cache_data` fns, paper-trade DB helpers, position sizing, `build_price_chart`, index/ticker data. (Consolidates spec's cache.py + trade_utils.py — safer than 4 modules.) |
| 3 | `shared/nav.py` | ⏳ **Next — manual** (see below) |
| 4 | `pages/01..17_*.py` | ⏳ mechanical once nav.py exists |
| 5 | `app.py` (entry) | ⏳ |
| 6 | Verify all 17 pages route | ⏳ needs interactive testing |

`app.py` is still the working monolith (with the main-branch safe fixes), so the
branch app runs today. Nothing is broken.

## Real page boundaries (line numbers drifted from the original spec)
Find them by the `^(if|elif) page ==` markers, NOT fixed line numbers. As of this
branch: Market Live 2210, Command Centre 2569, My Portfolio 3041, Analyze 3568,
Market Overview 4007, Smart Screener 4219, Paper Trades 4354, Backtest 5140,
Macro 5322, Breadth 5419, OI&Options 5534, Intraday 5732, Position Sizer 6257,
Swing Checklist 6374, My Watchlist 6563, Investor Guide 6694, Angel One 6939.

## Stage 3 — shared/nav.py (the hard one)
Source: app.py sidebar region **lines ~306–829** + live-top-bar/index-explorer
region **~1990–2209**. These INTERLEAVE module-level defs with inline rendering:
- Module-level (keep at module scope, importable): `_NAV_GROUPS`, `_PAGE_EMOJI`,
  `_PAGE_FULL_NAME`, `_group_icons`, `_PAGE_FILE` (new), `_qv_prices`, `_sidebar_all`,
  `_persist_user_state`, `_index_strip_data`, `_ticker_tape_data`.
- Wrap inline rendering into functions:
  - `render_sidebar()` — title, `_goto_page` resolution, Section selectbox + Page
    radio, portfolio quick-view, VIX gauge, market status, Angel One badge,
    watchlist, notification bell, position-sizing settings, storage badge.
  - `render_top_bar()` — live indices strip + ticker (the `@st.fragment(run_every="5s")`
    `_live_top_bar`) + the index-constituent explorer expander.

### Navigation architecture (decided)
Keep the existing custom selectbox+radio nav (users know it). In `render_sidebar()`,
after resolving the selected page, map via `_PAGE_FILE` and `st.switch_page(target)`
ONLY when the selection differs from the current page (avoid loops). Hide Streamlit's
auto-generated `pages/` nav with CSS in `apply_design()`:
```css
[data-testid="stSidebarNav"] { display: none; }
```
Preserve `_goto_page`: buttons set `st.session_state["_goto_page"]`; render_sidebar
resolves it to the page file and `st.switch_page`es there (before widgets, as today).

`_PAGE_FILE = {"Market Live":"pages/01_market_live.py", ... }` (full 17-entry map).

## Stage 4 — pages/*.py
Each file = this prologue + the page's `elif` body (verbatim, `elif page == "...":`
header removed and body de-indented by 4):
```python
import os, sys
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path: sys.path.insert(0, _ROOT)
import streamlit as st
from dashboard.shared.design import apply_design
from dashboard.shared.nav import render_sidebar, render_top_bar
from dashboard.shared.cache import (  # only what the page uses
    ...,
)
apply_design(); render_sidebar(); render_top_bar()
# <page body>
```
Page-local `@st.cache_data` fns defined inside an elif block stay local to that page.

## Stage 5 — app.py entry (≤40 lines)
`set_page_config` (ONCE, here only) → `apply_design()` → `render_sidebar()` →
`st.switch_page("pages/02_command_centre.py")` for default landing.

## Stage 6 — verification (interactive, required)
Launch; click every one of the 17 pages; confirm: routing, `_goto_page` quick-action
buttons (Command Centre / Portfolio / Analyze), paper trades persist, portfolio
quick-view shows prices, no `set_page_config` in any page file, charts use nse_pro.

## Remaining Task-2 fixes to fold in during the split
- Cache-TTL: add `_live_ttl()` (30s open / 1h closed) in cache.py; apply to live-price fns.
- Surface silent excepts: per page, replace UI-block `except: pass` with a visible
  `st.caption("⚠️ …")`. Skip data-fetch fallbacks in trade_store/data/ (intentional).
