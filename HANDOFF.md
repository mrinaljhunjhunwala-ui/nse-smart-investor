# Handoff — 2026-09-23 · UI/UX polish + UX2 hover previews

## Repo state
- **`main` at `f3e62ad`** — CI green, working tree clean, origin/main synced.
- **Canonical checkout:** `D:\Kashti Claude\nse-smart-investor` (per memory).
- **Open PRs:** none from this session.

## What shipped this session — 6 merged PRs

| Ref | Title | User-visible effect |
|---|---|---|
| [#144](https://github.com/mrinaljhunjhunwala-ui/nse-smart-investor/pull/144) `bfdb569` | design · UX3 extension | `.tick-pulse-{up,down}` one-shot halo now fires on Market Live movers, Command Centre top-picks buy + sell cards, My Portfolio holdings cards. New shared helper `tick_pulse_tracker(key)` in `chart_helpers.py` — `(pulse_cls, commit)` pair, auto-prunes stale prev-values. |
| [#145](https://github.com/mrinaljhunjhunwala-ui/nse-smart-investor/pull/145) `982f335` | feat · UX1 Ctrl+K command palette | Modal upgrade of the sidebar command bar. `@st.dialog` modal, JS keydown listener via `components.v1.html`, visible sidebar `⌘ K` trigger button (also click-tappable). Sidebar bar retained as AppTest-safe fallback. Shared `_cmdbar_navigate()` factored out so both surfaces route identically. |
| [#146](https://github.com/mrinaljhunjhunwala-ui/nse-smart-investor/pull/146) `265a3aa` | design · F2 mobile responsive pass | Below 768 px: `st.columns()` rows collapse via `[data-testid="stHorizontalBlock"]` override, new `.mobile-stack` utility for raw flex-row card grids (Command Centre Market Pulse, Portfolio stat tiles), `.topbar-chip` min-width shrunk, `.t-display`/`.t-h1`/`.page-title-serif`/`.score-big` scaled down, block-container padding tightened. Second `@media (max-width: 480px)` tightens phone-only. |
| [#147](https://github.com/mrinaljhunjhunwala-ui/nse-smart-investor/pull/147) `769e7b0` | design · F7b colour-blind Styler migration | Intraday Trader (Gap %, Day Chg %) and Angel One (P&L Rs, P&L %, Positions P&L) pandas Styler dataframes now get **▲/▼ arrow prefix via `Styler.format`** + **`font-weight: 700`** on high-magnitude cells. Direction survives red-green colour-vision deficiency. Categorical status columns untouched. |
| [#148](https://github.com/mrinaljhunjhunwala-ui/nse-smart-investor/pull/148) `50d9e3b` | polish · P2 sweep + backlog refresh | New shared `fmt_inr()` helper in `ui_components.py` — Indian lakh/crore comma grouping (`12,34,567` not `1,234,567`). Wired into Paper Trades P&L block. Analyze Stock "confirmation unavailable" branch got a `⏸` prefix so it's iconographically distinct from `⚠` warnings. `docs/UI_UX_BACKLOG.md` refreshed to mark F7b/F2/UX1/UX3/copy-polish/P&L-format/conviction-icon all ✅. |
| [#150](https://github.com/mrinaljhunjhunwala-ui/nse-smart-investor/pull/150) `f3e62ad` | feat · UX2 hover preview cards on tickers | Pure-CSS `:hover` tooltip on Command Centre top-picks (buy + sell) ticker labels. Shows mini sparkline (~22-day polyline SVG) + live price + delta + score chip toned by the pick's composite. New public helper `ticker_hover_wrap()` in `ui_components.py` — other surfaces (Market Live, Portfolio, Analyze Stock) can adopt. Hidden below 768 px so F2 mobile layout wins. Rebased replacement of #149 which conflicted with #148 on shared-helper insertion. |

## Shared helpers available (new this session)

All in `dashboard/shared/`:

- **`chart_helpers.py::tick_pulse_tracker(key)`** → `(pulse_cls, commit)` pair for one-shot `.tick-pulse-{up,down}` halos. Usage: `_cls, _commit = tick_pulse_tracker("_my_key")`, call `_cls(symbol, value)` per row, `_commit()` after the loop. Auto-prunes stale prev-values.
- **`ui_components.py::fmt_inr(value, decimals=0)`** — Indian lakh/crore digit grouping. Unsigned magnitude (`abs()` yourself if you carry the sign via arrow/color).
- **`ui_components.py::ticker_hover_wrap(display_label, sparkline_svg, price, chg_pct, score, sector)`** — pure-CSS `:hover` tooltip wrapper. All fields optional.
- **`nav.py::_cmdbar_navigate(kind, target, q_state_key)`** — shared post-click routing for both the sidebar command bar and the Ctrl+K modal palette.

## CSS classes added this session (in `design.py`)

- `.mobile-stack` — opt-in utility that flips inline `display:flex` to `flex-direction:column` below 768 px, for hand-rolled card-row grids that can't reach `data-testid`.
- `.ticker-hover` / `.ticker-hover-card` — pure-CSS hover-preview tooltip system with arrow indicator, transitions, tab-focus support. Hidden below 768 px.

## Backlog remaining

**From `docs/UI_UX_BACKLOG.md`:**

Real work:
- **UX2 wider adoption** — the helper is public; only Command Centre top-picks is wired (from #150). Natural next surfaces: Market Live movers, My Portfolio holdings, watchlist rows, Analyze Stock ticker.
- **F2 real-device pass** — verified in Chromium 375×812 but not on iOS Safari / real Android Chrome. Pinch-zoom, virtual-keyboard reflow, iOS momentum scroll are open.
- **Page 04 Analyze Stock — Live drift caption → amber banner** — needs banner component design.
- **Page 04 Analyze Stock — Earnings-date pill → signal-badge component** — component refactor.
- **Page 16 Angel One "Not connected" → empty_state()** — deferred; it's a full 4-step onboarding wizard, not a bare "nothing here yet" state.
- **Page 03 Holdings table → P&L table pattern** (row tinting, sticky first col).
- **Page 06 Smart Screener → signal-table pattern** (rank chip, posture chip, sector chip, sparkline col).
- **Page 08 Backtest trade-log** → same table upgrade.
- **Page 18 TQS Scanner** → 4-pillar radar or bar.
- **Page 19 Quality Watch** → RAG chip pattern grouping.
- **Page 22 FII/DII Flows** → diverging-colour rule from `dataviz` skill.
- **Page 05 Market Overview** — 🟨 F2 mobile note flagged (probably already covered by column-collapse, but hasn't been re-verified after #146).

Housekeeping:
- **Empty `E:\code\nse-smart-investor` directory shell** — `rmdir` when nothing's holding it. Prior session flagged this; I retried and got "Device or resource busy" again.

## Session-specific gotchas learned this session

- **PR conflicts on shared helper files** — #148 (added `fmt_inr`) and #149 (added `ticker_hover_wrap`) both patched `ui_components.py` at the same insertion point (right before `chip_delta`). Since both branched off the same base, they conflicted at merge time. Fix: rebased #149 on the merged main and opened as #150. Lesson: when stacking multiple PRs that touch shared helpers, either sequence them (base each new one off the prior) or use different insertion points.
- **`gh pr merge` on a stacked branch fails with "cannot be cleanly created"** — that's a conflict, not a CI failure. Local rebase + fresh branch + new PR is the recovery path since force-push to the old branch is auto-blocked.
- **Old Streamlit dev server can bind port 8501 from a previous session's cwd** — even after moving the repo. If you see "No such file or directory" pointing at an old path in the Streamlit error card, `netstat -ano | grep :8501` to find stale PIDs and `taskkill //PID <n> //F` them. Then start fresh with an absolute path to `app.py` (Streamlit tries to resolve `dashboard/app.py` against process cwd, not command-line cwd).
- **`NSE_SKIP_LIVE_TOP_PICKS=1` on the dev server means Command Centre shows no picks** — useful for fast-loading pages but breaks any test that needs actual pick cards on screen.

## Conventions (unchanged — don't relearn)

- **Never** call `st.subheader` in a page — use `.t-h2` class per §9.4.
- **Never** write raw hex in a page file — F1 hook at `.claude/hooks/block_page_hex.py` blocks it.
- **Never** call `st.set_page_config` in a page — happens once in `dashboard/app.py`.
- **Never** re-add candlestick to composite scoring.
- **No buy/sell/hold** recommendation copy anywhere — verdict is posture, not instruction.
- **Windows-first shell** — `py` not `python`, `PYTHONUTF8=1` for ₹.
- **Hook-blocked files:** `portfolio.csv`, `*.db`, `*.sqlite`, `.streamlit/secrets.toml`, `.env*`.
- **New research/alerts/tools/*.py with `__main__`** — MUST register in `tests/test_standalone_scripts_smoke.py::_STANDALONE_SCRIPTS` or CI breaks.
- **Force-push** requires explicit user permission (auto mode blocks it). Prefer close-and-reopen when rebasing.
- **User has standing push permission** — auto-push to remote right after committing (memory note from 2026-05-31). Still confirm before force-push / history rewrite.

## Where things are

- **Repo map:** `CLAUDE.md` at repo root
- **Design doc:** `docs/UI_UX_DESIGN_2026-09.md`
- **Backlog:** `docs/UI_UX_BACKLOG.md` (freshly swept in #148)
- **This handoff:** `HANDOFF.md`
- **Archive bundles:** `D:\Kashti Claude\nse-smart-investor\archive\*.bundle`

## What NOT to do

- Don't touch `.pulse-green`/`.pulse-red` (looping, wired to Paper Trades card-state glow).
- Don't reintroduce candlestick to scoring.
- Don't `st.set_page_config` in a page.
- Don't force-push without asking (or use close-and-reopen).
- Don't stack PRs that both add to the same insertion point in a shared helper file.
- Don't bulk-regex-replace across many pages without an `ast.parse` sanity check.
- Don't `--delete-branch` a squash-merge on a branch that has PRs stacked on it.

Working tree clean, CI green, all session PRs merged. Good starting point for the next chat.
