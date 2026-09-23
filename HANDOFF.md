# Handoff — 2026-09-23 (session 2) · P2 backlog closed + tech-debt sweep

## Repo state
- **`main` includes #150 → #161** — CI green on every PR, origin/main synced.
- **Canonical checkout:** `D:\Kashti Claude\nse-smart-investor`.
- **Open PRs:** none.
- **Leftover agent worktrees** under `.claude/worktrees/agent-*` (were lock-held by the agents while running). Safe to remove: `git worktree list`, then `git worktree remove --force <path>` for each `agent-*`. `.claude/worktrees/` and `archive/` are untracked; don't commit them.

## What shipped this session — 12 merged PRs

| PR | What changed |
|---|---|
| [#150](https://github.com/mrinaljhunjhunwala-ui/nse-smart-investor/pull/150) | UX2 hover preview cards on Command Centre top picks (carried over from session 1). |
| [#151](https://github.com/mrinaljhunjhunwala-ui/nse-smart-investor/pull/151) | P&L table pattern (03 holdings, 08 backtest), signal-table summary (06 screener), Clean/Amber/Red grouping (19). New `dashboard/shared/table_styles.py`. |
| [#152](https://github.com/mrinaljhunjhunwala-ui/nse-smart-investor/pull/152) | 04 dismissible drift banner + earnings `chip_pill`; 18 four-pillar radar vs top-10 median; 22 FII/DII split panels with hue = sign only. `PLOT_COLORS` + `diverging_colors()` in `chart_helpers.py`. |
| [#153](https://github.com/mrinaljhunjhunwala-ui/nse-smart-investor/pull/153) | UX2 hover rolled out: 03 holdings cards, 14 watchlist chip strip (new UI: the watchlist itself is a dataframe), 04 hero ticker. |
| [#154](https://github.com/mrinaljhunjhunwala-ui/nse-smart-investor/pull/154) | 01 Market Live: new scrolling ticker tape, new sector heatmap, hover on movers. 02 Command Centre: single regime strip (VIX · breadth · scoring version); pick cards show 5 lines, rest behind a toggle. |
| [#155](https://github.com/mrinaljhunjhunwala-ui/nse-smart-investor/pull/155) | 11 market-closed notice · 12 input cards · 13 journal `.t-h2` + data-as-of · 15 guide typography · 16 Angel One onboarding panels · 21 `nse_pro` chart. 05 needed no change. |
| [#156](https://github.com/mrinaljhunjhunwala-ui/nse-smart-investor/pull/156) | Tech debt: `components.v1.html` → `st.html(unsafe_allow_javascript=True)` (Ctrl+K palette + alerts in `nav.py`); **`dashboard/shared/tokens.py`** is now the single colour source; R:R computed once on 06. |
| [#157](https://github.com/mrinaljhunjhunwala-ui/nse-smart-investor/pull/157) | Streamlit floor **1.52.0** (checked in the wheels: `unsafe_allow_javascript` is absent in 1.51.0 and present in 1.52.0); descriptive Market Live idea cards; screener rank column pinned. |
| [#158](https://github.com/mrinaljhunjhunwala-ui/nse-smart-investor/pull/158) | All `pd.read_sql_query` → `utils/sql.py::read_sql_df` (pure, re-exported from `trade_store`), removing the SQLAlchemy UserWarning. **Page smoke test now catches syntax errors** (see gotchas). |
| [#159](https://github.com/mrinaljhunjhunwala-ui/nse-smart-investor/pull/159) | Heatmap label contrast; screener **22-day sparkline column**; missing R:R no longer prints "None"; removed a guide H1 rule that could never apply. |
| [#160](https://github.com/mrinaljhunjhunwala-ui/nse-smart-investor/pull/160) | TQS signal/grade colours distinct again (`tokens.ordinal_ramp`, ≥4.5:1 contrast); **zero raw hex in any page**, enforced by a test. |
| #161 | Advice-copy sweep (05, 11, 15, 17, 02 paper alerts, 04 FII/DII regime text, `cache._plain_english` rewritten descriptively) + **`tests/test_no_advice_copy.py`** guard. This handoff. |

## Shared helpers / modules (new this session)

- **`dashboard/shared/tokens.py`**: `COLORS` dict (single source; `design.py` builds `:root` from it), `rgba(name, a)`, `mix(a, b, t)`, `ordinal_ramp(n)`, `css_vars()`. Plotly/Styler code must read colours from here or `PLOT_COLORS`, never hex.
- **`dashboard/shared/table_styles.py`**:
  - `pnl_styler(df, tint_col, signed_cols, formats, bold_at)`
  - `arrow_fmt(decimals, unit, prefix, indian)`
  - `row_tint_css`
  - `pinned_text_col`
  - `posture_label` (the honest label, plus a shape glyph)
- **`chart_helpers.py`**: `PLOT_COLORS`, `diverging_colors(values, full_at)` (hue = sign, opacity = magnitude).
- **`utils/sql.py::read_sql_df(sql, conn, params)`**: cursor-based, works on SQLite and Postgres (`coerce_float=True` so NUMERIC columns don't come back as `Decimal`).

## New guard tests (they fail CI, so don't work around them)

- `tests/test_tokens.py`: no raw hex in `dashboard/pages/*.py` (same exemptions as the hook); tokens are consumed by design, charts and tables; TQS ramps are distinct.
- `tests/test_no_advice_copy.py`: bans instruction phrases ("buy dips", "avoid fresh", "consider selling", "lock in profit", …) in UI string literals under `dashboard/pages` + `dashboard/shared`. `dashboard/shared/ai/` and docstrings are exempt. Add phrasings when you find new ones.
- `tests/test_pages_smoke.py`: now `compile()`s each page and fails on an empty render.

## Still open (can't be closed from here)

- **F2 real-device pass**: mobile layout checked only in Chromium emulation. It needs a real iOS Safari and Android Chrome check (pinch-zoom, keyboard reflow, momentum scroll).
- **04 drift banner live check**: it only renders during market hours (09:15–15:30 IST) with live drift ≥ 0.5%. Code and smoke test are fine, but it hasn't been seen live. Open Analyze Stock during market hours and check that dismiss (✕) works.
- **16 Angel One**: now a clean numbered 4-step panel, but not an interactive wizard (step state, validation). Only worth building if onboarding becomes a priority.
- **C/D/F grade shades on page 18**: distinct but close (orange→red). Glance at them on a real screen.

## Verified live in the browser this session
18 radar · 06 summary table + sparklines + pinned rank · 04 earnings chip · 01 tape (animating, 32 px) + heatmap + 10 hover movers · 15 guide H2/body sizes · Ctrl+K palette after the `st.html` migration · 02 regime strip.

## Gotchas learned this session

- **The page smoke test used to pass syntax-broken pages.** Streamlit 1.57 handles compile errors itself: it logs "Script compilation error" and sends a stop event, so `AppTest.exception` stays empty. Fixed in #158 with an explicit `compile()`. If you write a new AppTest-style test, don't rely on `at.exception` alone.
- **`.page-title-serif` uses `!important` on size and weight.** A page-specific H1 override without `!important` silently loses. All page titles are deliberately the same serif scale.
- **Plotly treemap auto-contrast picks near-black labels** on dark, low-alpha tiles. Set `textfont.color` explicitly.
- **Mixed `None` + float in a DataFrame column can end up object dtype**, and `st.dataframe` prints a literal "None". Run `pd.to_numeric(..., errors="coerce")` first.
- **Parallel agent PRs that all append to the end of the `design.py` CSS string conflict every time.** Resolution is always "keep both blocks". Merge them one at a time and resolve in the agent's worktree (the branch is checked out there, so `git checkout` in the main checkout fails).
- **`gh pr checks` exits non-zero while checks are pending**, so `gh pr checks N && gh pr merge N` silently skips the merge. Use `gh pr checks N --watch` first.
- **Stale Streamlit server on 8501** (from session 1) still applies. Use `preview_start` with `.claude/launch.json` (`NSE_SKIP_LIVE_TOP_PICKS=1` means Command Centre shows no picks).
- **Agent worktrees used to double the local test suite.** `test_syntax_parses.py` walks the whole repo and was parsing the ~1,100 `.py` files in `.claude/worktrees/*`, taking the count from ~1,185 to 2,302. Fixed in #161 by excluding `worktrees`. If the count jumps again, check for another repo copy inside the tree.
- **Timing:** the screener scan on NIFTY 50 takes about 2 minutes in the dev server, and a TQS scan about 30 s.

## Conventions (unchanged — don't relearn)

- **Never** `st.subheader` in a page — `.t-h2` per §9.4.
- **Never** raw hex in a page — now enforced by both the hook and `test_tokens.py`.
- **Never** `st.set_page_config` in a page.
- **Never** re-add candlestick to composite scoring.
- **No buy/sell/hold instruction copy anywhere**, now enforced by `test_no_advice_copy.py`. Posture labels come from `trade_utils._display_label` (or `table_styles.posture_label`).
- **Windows-first shell**: `py`, `PYTHONUTF8=1`.
- **Hook-blocked files:** `portfolio.csv`, `*.db`, `*.sqlite`, `.streamlit/secrets.toml`, `.env*`.
- **New research/alerts/tools/*.py with `__main__`** must be registered in `tests/test_standalone_scripts_smoke.py::_STANDALONE_SCRIPTS`.
- **Force-push** needs explicit user permission; prefer close-and-reopen.
- **Standing push permission**: auto-push after commit, and tell the user.

## Where things are

- **Repo map:** `CLAUDE.md`
- **Design doc:** `docs/UI_UX_DESIGN_2026-09.md`
- **Backlog:** `docs/UI_UX_BACKLOG.md` (everything ✅ except F2 real-device)
- **This handoff:** `HANDOFF.md`
- **Archive bundles:** `archive/*.bundle`

## What NOT to do

- Don't touch `.pulse-green` / `.pulse-red` (looping, wired to the Paper Trades glow).
- Don't add colour literals outside `dashboard/shared/tokens.py`.
- Don't reintroduce `st.components.v1.html` (deprecated); use `st.html(..., unsafe_allow_javascript=True)`.
- Don't call `pd.read_sql_query` directly; use `utils.sql.read_sql_df`.
- Don't stack PRs on the same insertion point in a shared file; sequence them.
- Don't bulk-regex-replace across pages without an `ast.parse` check.
