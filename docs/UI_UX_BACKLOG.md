# UI / UX Backlog — NSE Smart Investor

Last updated: 2026-09-06 · Owner: @mrinaljhunjhunwala-ui
Living doc. Sourced from [`FEATURE_ROADMAP.md`](FEATURE_ROADMAP.md), [`PHASE1_UI_HONESTY.md`](PHASE1_UI_HONESTY.md), the `trading-dashboard-design` skill, and a walk of `dashboard/pages/` + `dashboard/shared/`.

Skills referenced below (all installed under `~/.claude/skills/`):
`trading-dashboard-design`, `taste-skill`, `apple-design`, `emil-design-eng`,
`frontend-ui-engineering`, `find-animation-opportunities`, `animate`, `dataviz`.

---

## Baseline — what we already have

The app is **not** starting from scratch. [`dashboard/shared/design.py`](../dashboard/shared/design.py) already ships an "NSE Pro v2 — Dealing Room" theme: Bloomberg-heritage black + phosphor, IBM Plex Sans / Mono, semantic-only red/green, single cyan accent (`#2fd1e0`). A shared Plotly template (`nse_pro`) is registered on every page via `apply_design()`. Sidebar nav is centralised in [`dashboard/shared/nav.py`](../dashboard/shared/nav.py). Reusable card / chip / metric primitives live in [`dashboard/shared/ui_components.py`](../dashboard/shared/ui_components.py).

So the backlog is **consistency + coverage**, not a re-skin.

---

## Rating scheme

| Symbol | Meaning |
|---|---|
| 🟥 P0 | Blocking / user-visible dishonesty / broken experience |
| 🟧 P1 | Substantive gap; ship this sprint |
| 🟨 P2 | Polish; ship when adjacent code is touched |
| 🟩 P3 | Nice-to-have |

Effort: S ≤ ½ day · M ≤ 2 days · L > 2 days

---

## 1. Cross-cutting foundations

| # | Item | Pri | Effort | Skill to invoke |
|---|---|---|---|---|
| F1 | **Design-token audit** — walk every `dashboard/pages/*.py` for hard-coded hex (`#26a69a`, `#ef5350`, inline `background:`) and route through `design.py` tokens. `ripgrep '#[0-9a-fA-F]{6}' dashboard/pages` returns a lot. | 🟧 P1 | M | `trading-dashboard-design` (references/css-themes.md) + `taste-skill` |
| F2 | **Mobile / narrow-viewport pass (<900 px)**. Streamlit's default column stacking gets ugly. Add media queries in `design.py`, collapse the top-bar to a compact strip, force single-column card grids under 768 px. | 🟧 P1 | M | `apple-design` (feedback + restraint) + `trading-dashboard-design` (references/layout-patterns.md) |
| F3 | **Dark-mode parity** — Portfolio, Command Centre, Analyze Stock are terminal-grade; Paper Trades, Intraday, Angel One still show default Streamlit widget chrome (light borders, wrong hover). | 🟧 P1 | M | `trading-dashboard-design` |
| F4 | **Motion policy** — no consistent stance on hover / tape scroll / loading skeletons. Define one (`prefers-reduced-motion` honoured, ≤180 ms, ease-out only for enter). | 🟨 P2 | S | `animate` + `find-animation-opportunities` |
| F5 | **Empty-state kit** — every page currently degrades differently when the network is stubbed (per `test_pages_smoke.py`). Add a shared `empty_state(icon, title, hint)` helper in `ui_components.py`. | 🟨 P2 | S | `taste-skill` |
| F6 | **Loading skeletons** replacing `st.spinner()` on the top 4 slow pages (Analyze Stock, Command Centre, TQS Scanner, Tomorrow's Watchlist). | 🟨 P2 | M | `animate` |
| F7 | **Focus / a11y sweep** — visible focus rings on custom buttons, `aria-label` on ticker-tape spans, colour-blind check for red/green metrics. | 🟨 P2 | M | `frontend-ui-engineering` |

---

## 2. Score-honesty rollout (per `PHASE1_UI_HONESTY.md`)

Phase 1 shipped 2026-06-11. Two open:

| # | Item | Pri | Effort | Skill |
|---|---|---|---|---|
| SH1 | **Phase 2 — action-label display mapping** on every score surface (Analyze Stock, Command Centre, Smart Screener, TQS Scanner, Tomorrow's Watchlist, Watchlist). Chips must read as *posture* (Bullish/Neutral/Bearish), never as instruction. | 🟥 P0 | M | project rule per [`CLAUDE.md`](../CLAUDE.md) + [`PATTERN_REMOVAL_MIGRATION.md`](PATTERN_REMOVAL_MIGRATION.md) |
| SH2 | **Phase 3 — evidence-gated component changes** for pattern & oversold-RSI display (only surface when the underlying signal has evidence weight). | 🟥 P0 | M | same |

---

## 3. Investor-reporting surfaces still missing UI

Engine code exists; the pages don't render it.

| # | Item | Pri | Effort | Skill |
|---|---|---|---|---|
| IR1 | **Structured Bull / Bear / Risk card** on Analyze Stock. `analysis/thesis/` produces the payload; no dedicated block on the page. | 🟧 P1 | M | `trading-dashboard-design` (references/components.md — signal-badge, section card) |
| IR2 | **Beta surfacing** on My Portfolio. Already computed in `analysis/hedging.py`; no UI. Show stock β, portfolio β vs Nifty, and per-holding contribution. | 🟧 P1 | S | `dataviz` (bar with reference line) |
| IR3 | **NAV curve + Sharpe / Sortino / Calmar / Max DD tiles** on My Portfolio. Roadmap item B — highest single-lever build. | 🟧 P1 | M | `dataviz` + `trading-dashboard-design` |
| IR4 | **Holdings correlation heatmap** on My Portfolio (component exists on Macro page; reuse on real returns). | 🟨 P2 | S | `dataviz` |
| IR5 | **HHI + stock-level concentration widget** — upgrade the qualitative sector label. | 🟨 P2 | S | `dataviz` |
| IR6 | **Contribution-to-return table** and **risk-contribution bar** — Phase 2 of the finance roadmap. | 🟨 P2 | M | `dataviz` |

---

## 4. Per-page issues (page-walk notes)

Every entry links to the page it fixes. Numbers reference the current top-of-file "FIX" comments where relevant.

### [`01_market_live.py`](../dashboard/pages/01_market_live.py) — Market Live
- 🟨 Ticker tape uses generic Streamlit container border; wrap in the terminal-grade "tape" component from `references/components.md` (fixed-height, monospaced, subtle gradient mask on edges).
- 🟨 Sector heatmap: reads as flat blocks — apply diverging palette from `dataviz` skill; add small % labels on hover only.

### [`02_command_centre.py`](../dashboard/pages/02_command_centre.py) — Command Centre
- 🟧 The v2 scoring active chip added in #47 works but sits alone above the cards; move it into a "regime strip" alongside VIX zone and market breadth so status lives in one place.
- 🟨 Top-picks cards: 6 metrics per card is > "5 above the fold" rule. Demote 2 to expander per `references/layout-patterns.md`.

### [`03_my_portfolio.py`](../dashboard/pages/03_my_portfolio.py) — My Portfolio
- 🟧 IR2 + IR3 + IR4 + IR5 + IR6 all land here — biggest single-page upgrade in the app.
- 🟨 Holdings table: default Streamlit df; convert to the "P&L table" pattern (row background tinted by return, monospaced ₹ column, sticky first column).

### [`04_analyze_stock.py`](../dashboard/pages/04_analyze_stock.py) — Analyze Stock
- 🟥 SH1/SH2 chips.
- 🟧 IR1 Bull/Bear/Risk card.
- 🟧 Live drift caption (FIX A2) is a plain `st.caption`; promote to a small dismissible amber banner so it doesn't get lost in the top-bar noise.
- 🟨 Conviction section (FIX A3) — "confirmation unavailable" branch renders as neutral grey text; distinguish with an iconography convention (⏸ = insufficient data ≠ ⚠ = adverse).
- 🟨 Earnings-date pill (FIX A4) needs the shared "signal-badge" component so "Results 3d ago" reads consistently with every other status chip.

### [`05_market_overview.py`](../dashboard/pages/05_market_overview.py) — Market Overview
- 🟨 Two-column layout collapses badly on mobile (F2).

### [`06_smart_screener.py`](../dashboard/pages/06_smart_screener.py) — Smart Screener
- 🟧 Result df has no colour semantics; adopt "signal table" pattern (rank chip, posture chip, sector chip, sparkline column).

### [`07_paper_trades.py`](../dashboard/pages/07_paper_trades.py) — Paper Trades
- 🟧 F3 — default Streamlit widget chrome still visible (light input borders on dark).
- 🟨 P&L column: needs Indian-comma + explicit sign per skill's number rules.

### [`08_backtest.py`](../dashboard/pages/08_backtest.py) — Backtest
- 🟨 Equity curve: default Plotly axes; migrate to `nse_pro` template (should already inherit, verify).
- 🟨 Trade-log table: same table upgrade as Smart Screener.

### [`11_intraday_trader.py`](../dashboard/pages/11_intraday_trader.py) — Intraday Trader
- 🟧 F3 — one of the worst offenders. Full Streamlit-default look.
- 🟧 No "market is closed" state — page just returns empty widgets outside RTH. Use F5 empty-state kit + `dashboard/shared/market_hours.py`.

### [`12_position_sizer.py`](../dashboard/pages/12_position_sizer.py) — Position Sizer
- 🟨 Form-heavy; sliders + numeric inputs need the same restyle F1 applies elsewhere.

### [`14_my_watchlist.py`](../dashboard/pages/14_my_watchlist.py) — Watchlist
- 🟧 15-min piggyback scan (commit 5594fd1) added scoring; the *badges* now on the table need SH1 posture-mapping.
- 🟨 Empty state before first symbol added is a plain paragraph — use F5.

### [`15_investor_guide.py`](../dashboard/pages/15_investor_guide.py) — Investor Guide
- 🟨 Long-form document; typography scale is default (14px everywhere). Apply hierarchy from skill (H1 32/700, H2 22/700, body 15/1.6).

### [`16_angel_one.py`](../dashboard/pages/16_angel_one.py) — Angel One
- 🟧 Broker-integration page; F3 fully applies. Also needs a clear "not connected" empty state with wire-up steps.

### [`17_tomorrow_watchlist.py`](../dashboard/pages/17_tomorrow_watchlist.py) — Tomorrow's Watchlist
- 🟧 SH1 chips.
- 🟨 Refresh timestamp isn't visible — add a "freshness" badge (last-updated pill) from `dashboard/shared/pick_freshness.py`.

### [`18_tqs_scanner.py`](../dashboard/pages/18_tqs_scanner.py) — TQS Scanner
- 🟧 SH1 chips (score is 0–90; label must be descriptive).
- 🟨 4-pillar breakdown: currently 4 numbers side-by-side. Convert to a compact radar or 4-segment bar for one-glance read.

### [`19_quality_watch.py`](../dashboard/pages/19_quality_watch.py) — Quality Watch
- 🟨 List view lacks visual grouping by flag colour (RAG); apply the RAG chip pattern from `references/components.md`.

### [`20_deep_dive.py`](../dashboard/pages/20_deep_dive.py) — Deep Dive
- 🟨 Long scroll — introduce anchored TOC on the right (position:sticky) for the section headers.

### [`21_verdict_calibration.py`](../dashboard/pages/21_verdict_calibration.py) — Verdict Calibration
- 🟨 Internal-facing tool; low visual priority but the summary chart should adopt `nse_pro` template.

### [`22_fii_dii_flows.py`](../dashboard/pages/22_fii_dii_flows.py) — FII/DII Flows
- 🟨 Bars + tables layout; time-series chart needs the diverging colour rule from `dataviz` skill.

---

## 5. Data-transparency micro-UX

Not "pretty" work but user-trust work:

| # | Item | Pri | Effort |
|---|---|---|---|
| DT1 | **Source pill** on every data-heavy card ("via NSE" / "via Screener" / "via Angel One" — cache TTL on hover). | 🟨 P2 | S |
| DT2 | **"Data as of ..." freshness stamp** consistent across pages (currently varies). | 🟨 P2 | S |
| DT3 | **Degraded-mode banner** — one shared component when a provider fails (per `data-provenance-auditor` subagent output). | 🟨 P2 | S |

---

## 6. Suggested execution order

1. **F3 dark-mode parity** on Paper Trades, Intraday, Angel One — biggest visible inconsistency, ~1 day.
2. **SH1 + SH2** score-honesty rollout — compliance and tone are project non-negotiables.
3. **IR1 Bull/Bear/Risk card** on Analyze Stock — engine is done, purely UI wiring.
4. **IR2 + IR3 Portfolio Beta + NAV/Sharpe stack** — highest-value single build.
5. **F1 design-token audit** — do it while you're already in every page from #1–4.
6. **F2 mobile pass** — after tokens are unified, media queries are cheap.
7. **F5/F6 empty-states + skeletons** — polish sweep.
8. IR4–IR6 + per-page P2 items — opportunistic.

---

## 7. How to invoke the skills against a specific page

Every page-level item above pairs with a concrete skill call. Example runbook for Analyze Stock:

```
1. Skill: trading-dashboard-design      → pull component + layout patterns
2. Skill: taste-skill                   → critique spacing / density
3. Skill: dataviz                       → validate chart palette + hover rules
4. Skill: apple-design                  → gesture / hover / transition polish
5. Skill: page-smoke-check              → auto-runs on save (project hook)
```

Every page edit under `dashboard/pages/` triggers `page-smoke-check` from `.claude/hooks/` automatically — no need to invoke by hand. `verdict-regression-reviewer` is only needed if scoring/thesis output changes shape (label rewrites don't count).
