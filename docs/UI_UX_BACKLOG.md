# UI / UX Backlog — NSE Smart Investor

Last updated: 2026-09-21 · Owner: @mrinaljhunjhunwala-ui
Living doc. Sourced from [`FEATURE_ROADMAP.md`](FEATURE_ROADMAP.md), [`PHASE1_UI_HONESTY.md`](PHASE1_UI_HONESTY.md), the `trading-dashboard-design` skill, and a walk of `dashboard/pages/` + `dashboard/shared/`.

Skills referenced below (all installed under `~/.claude/skills/`):
`trading-dashboard-design`, `taste-skill`, `apple-design`, `emil-design-eng`,
`frontend-ui-engineering`, `find-animation-opportunities`, `animate`, `dataviz`.

---

## Baseline — what we already have

The app is **not** starting from scratch. [`dashboard/shared/design.py`](../dashboard/shared/design.py) ships an "NSE Pro v2 — Dealing Room" theme built on the §9 visual-language foundation (#103): pure-black ground with a `--card-lift` overlay, three-width hairline system, saffron `--accent` (`#ff9500`) as the single interactive hue, semantic-only `--bull` / `--bear`, IBM Plex Sans / Mono, and a typography scale utility set (`.t-display / .t-h1 / .t-h2 / .t-body / .t-label / .t-value / .t-value-sm / .t-caption`). A shared Plotly template (`nse_pro`) is registered on every page via `apply_design()`. Sidebar nav is centralised in [`dashboard/shared/nav.py`](../dashboard/shared/nav.py). Reusable card / chip / metric primitives live in [`dashboard/shared/ui_components.py`](../dashboard/shared/ui_components.py).

So the backlog is **consistency + coverage**, not a re-skin.

> **Sept 2026 design sprint — what shipped:** #102–#139. Foundation (#103 §9), IR family (#116–#122 IR1–IR6), DT helpers (#114) wired across 9 surfaces (#124–#127), F1/F3/F4/F5/F6/F7 all closed, SH2 shipped, DT3 degraded-banner, chip vocabulary (#89–#91), Slice 2 Deep Dive fold into Analyze Stock (#115 — 22 → 20 pages), §9.4 typography sweep across every `st.subheader()` (#128–#133), sidebar command bar (#135, #137). Details below.

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

| # | Item | Pri | Effort | Skill / status |
|---|---|---|---|---|
| F1 | ✅ **Design-token audit** — hex routed through `design.py` tokens across all pages. Shipped in #92 (Quality Watch + Deep Dive), #94 (Market Live / My Portfolio / Paper Trades / Intraday), #100 (FII/DII Plotly). F1 hook in `.claude/hooks/block_page_hex.py` prevents regressions. | ✅ Done | — | `trading-dashboard-design` |
| F2 | **Mobile / narrow-viewport pass (<900 px)**. Streamlit's default column stacking gets ugly. Add media queries in `design.py`, collapse the top-bar to a compact strip, force single-column card grids under 768 px. | 🟧 P1 | M | `apple-design` + `trading-dashboard-design` |
| F3 | ✅ **Dark-mode parity** — default Streamlit widget chrome (light borders, wrong hover) that was bleeding through on Paper Trades / Intraday / Angel One. Shipped in #139 (widget-parity block in `design.py` for `text_area`, `slider`, `radio`, `checkbox`, `toggle`, `download_button`). | ✅ Done | — | — |
| F4 | ✅ **Motion policy** — `prefers-reduced-motion` guard + shared tokens wired on `hero_verdict`. Shipped in #97. | ✅ Done | — | — |
| F5 | ✅ **Empty-state kit** — `empty_state(icon, title, hint)` helper in `ui_components.py` (#95) + rollout across 6 pages including Watchlist and Paper Trades (#96). | ✅ Done | — | — |
| F6 | ✅ **Loading skeletons** on Analyze Stock's four slow spinners. Shipped in #120. Extending to Command Centre / TQS Scanner / Tomorrow's Watchlist stays opportunistic. | ✅ Done (Analyze Stock) | — | — |
| F7 | ✅ **Focus rings** on buttons + tabs via `:focus-visible` saffron halo. Shipped in #136. `aria-label` on ticker-tape spans + colour-blind check for red/green metrics — **still open** (see F7b below). | ✅ Focus rings done | — | `frontend-ui-engineering` |
| F7b | ✅ `aria-label` on top-bar chips + `aria-hidden` on ticker tape + `.delta-pos`/`.delta-neg` shape classes (#141). ✅ Styler dataframes on Intraday Trader + Angel One now carry ▲/▼ prefix + bold-weight cue (#147). | ✅ Shipped | — | — |

---

## 2. Score-honesty rollout (per `PHASE1_UI_HONESTY.md`)

Phase 1 shipped 2026-06-11.

| # | Item | Pri | Effort | Skill / status |
|---|---|---|---|---|
| SH1 | ✅ **Phase 2 — action-label display mapping** rolled across score surfaces via the chip-vocabulary sweep: chip_pill + chip_tag wired on Tomorrow's Watchlist (#89), Analyze Stock (#90), Command Centre + My Portfolio (#91). Chips now read as *posture* (Bullish/Neutral/Bearish), never as instruction. | ✅ Done | — | — |
| SH2 | ✅ **Phase 3 — evidence-gated candlestick + oversold-RSI display**. Shipped in #109 (display-only — do NOT reintroduce to composite scoring, per `PATTERN_REMOVAL_MIGRATION.md`). | ✅ Done | — | — |

---

## 3. Investor-reporting surfaces — SHIPPED

All six IR items shipped in the Sept 2026 sprint. Left here for provenance.

| # | Item | Status |
|---|---|---|
| IR1 | ✅ Structured Bull / Bear / Risk hero card on Analyze Stock — #116 |
| IR2 | ✅ Beta Exposure hero + β Contrib column on My Portfolio — #119 |
| IR3 | ✅ Portfolio Risk & Performance hero cards + NAV drawdown chart (Sharpe / Sortino / Calmar / Max DD) — #117 |
| IR4 | ✅ Holdings correlation heatmap dressing on My Portfolio — #121 |
| IR5 | ✅ Concentration & Diversification hero + Best/Worst polish — #118 |
| IR6 | ✅ Contribution-to-return + risk-contribution bar — #122 |

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
- ✅ IR2 + IR3 + IR4 + IR5 + IR6 all landed here (see §3).
- ✅ Holdings table → P&L table pattern: rows tinted by P&L %, ▲/▼ + bold on big moves, Indian ₹ grouping, pinned Ticker column (shared `table_styles.py`).

### [`04_analyze_stock.py`](../dashboard/pages/04_analyze_stock.py) — Analyze Stock
- ✅ SH1/SH2 chips (SH1: chip vocabulary #90; SH2: evidence-gated #109).
- ✅ IR1 Bull/Bear/Risk card (#116).
- ✅ Deep Dive absorbed as a tab (Slice 2, #115).
- ✅ F6 loading skeletons on the four slow spinners (#120).
- ✅ Live drift → dismissible amber `degraded_banner` (dismissal per ticker + drift bucket, re-surfaces on a bigger move).
- ✅ Conviction section (FIX A3) — "confirmation unavailable" branch now carries a `⏸` prefix so it's distinguishable from actual `⚠` warnings.
- ✅ Earnings status → shared `chip_pill` with ⚠/◆/●/✓ glyphs; "avoid fresh buys" copy replaced with "event risk" (no-instruction rule).

### [`05_market_overview.py`](../dashboard/pages/05_market_overview.py) — Market Overview
- 🟨 Two-column layout collapses badly on mobile (F2).

### [`06_smart_screener.py`](../dashboard/pages/06_smart_screener.py) — Smart Screener
- ✅ Signal-table summary above setup cards: rank, shape-coded posture, sector, score bar, R:R, rev growth. (Sparkline column deferred — screener doesn't carry a price series per signal.)

### [`07_paper_trades.py`](../dashboard/pages/07_paper_trades.py) — Paper Trades
- ✅ F3 widget chrome (#139).
- ✅ F5 empty state (#96).
- ✅ P&L block now uses Indian lakh/crore comma grouping via the shared `fmt_inr()` helper — `12,34,567` not `1,234,567`. Sign remains carried by the leading ▲/▼ arrow.

### [`08_backtest.py`](../dashboard/pages/08_backtest.py) — Backtest
- 🟨 Equity curve: default Plotly axes; migrate to `nse_pro` template (should already inherit, verify).
- ✅ Results tables: RdYlGn gradient replaced with the P&L pattern (row tint + ▲/▼ + bold beyond ±10%).

### [`11_intraday_trader.py`](../dashboard/pages/11_intraday_trader.py) — Intraday Trader
- ✅ F3 widget chrome (#139).
- 🟧 No "market is closed" state — page just returns empty widgets outside RTH. Use F5 empty-state kit + `dashboard/shared/market_hours.py`.

### [`12_position_sizer.py`](../dashboard/pages/12_position_sizer.py) — Position Sizer
- 🟨 Form-heavy; sliders + numeric inputs need the same restyle F1 applies elsewhere.

### [`14_my_watchlist.py`](../dashboard/pages/14_my_watchlist.py) — Watchlist
- ✅ SH1 posture chips (chip vocabulary sweep).
- ✅ F5 empty state (#95/#96).
- ✅ DT1/DT2 source pill + data-as-of (#127).

### [`15_investor_guide.py`](../dashboard/pages/15_investor_guide.py) — Investor Guide
- 🟨 Long-form document; typography scale is default (14px everywhere). Apply hierarchy from skill (H1 32/700, H2 22/700, body 15/1.6).

### [`16_angel_one.py`](../dashboard/pages/16_angel_one.py) — Angel One
- ✅ F3 widget chrome (#139).
- 🟨 "Not connected" state currently uses `st.warning` + `st.expander` markdown. Consider migrating to the F5 `empty_state()` helper so the wire-up steps read consistently with other stub states.

### [`13_stock_journal.py`](../dashboard/pages/13_stock_journal.py) — Stock Journal
- New page shipped since last backlog write. No specific UI action items filed yet — audit against §9.4 typography + DT1/DT2 next pass.

### [`17_tomorrow_watchlist.py`](../dashboard/pages/17_tomorrow_watchlist.py) — Tomorrow's Watchlist
- ✅ SH1 chips (#89).
- ✅ DT1/DT2 source pill + data-as-of (#127).
- ✅ Freshness badge via `dashboard/shared/pick_freshness.py`.

### [`18_tqs_scanner.py`](../dashboard/pages/18_tqs_scanner.py) — TQS Scanner
- ✅ SH1 chips.
- ✅ §9.4 typography sweep (#128).
- ✅ 4-pillar radar (per ticker, % of 22.5 max) vs top-10 median; stacked-bar colours moved to `PLOT_COLORS` tokens.

### [`19_quality_watch.py`](../dashboard/pages/19_quality_watch.py) — Quality Watch
- ✅ §9.4 typography sweep (#128).
- ✅ Ranked list grouped into Clean / Amber / Red bands; flag counts are `chip_pill`s with ●/◆/✓ glyphs.

### `20_deep_dive.py` — Deep Dive
- ✅ Removed. Folded into Analyze Stock as a tab in Slice 2 (#115). Page count went 22 → 20.

### [`21_verdict_calibration.py`](../dashboard/pages/21_verdict_calibration.py) — Verdict Calibration
- ✅ §9.4 typography sweep (#131).
- 🟨 Internal-facing tool; low visual priority but the summary chart should adopt `nse_pro` template.

### [`22_fii_dii_flows.py`](../dashboard/pages/22_fii_dii_flows.py) — FII/DII Flows
- ✅ Regime card (#101), F1 Plotly hex → tokens (#100), DT1/DT2 wired (#126), §9.4 typography (#128).
- ✅ Daily flows split into FII / DII panels, hue = sign only (bull/bear), opacity = magnitude via `diverging_colors()`; cumulative lines no longer use bull green for identity.

---

## 5. Data-transparency micro-UX — SHIPPED

| # | Item | Status |
|---|---|---|
| DT1 | ✅ Source pill helper (#114) wired on verdict card + Command Centre (#124), My Portfolio + Smart Screener + Backtest (#125), Market Live + FII/DII (#126), Tomorrow's + My Watchlist (#127). |
| DT2 | ✅ `data_as_of` freshness stamp — same batches as DT1. |
| DT3 | ✅ Degraded-mode banner shared helper wired on Command Centre + My Portfolio (#99). |

---

## 6. What's next — Sept 2026 sprint backlog

Everything above under a ✅ has shipped. Remaining active work:

1. ✅ **F2 mobile pass** (`<768 px`) — shipped in #146. `st.columns` collapse below 768, `.mobile-stack` utility for raw flex grids, top-bar chip shrink, hero-text scale-down, tight block-container padding. Real device pass still open.
2. **§10 UX ideas** (see below) — Ctrl+K palette + UX3 live-tick shipped; hover previews (UX2) shipped on Command Centre, My Portfolio holdings cards, My Watchlist (chip strip above table) and Analyze Stock hero.
3. ✅ **F7b a11y follow-up** — shipped in #141 + #147.
4. ✅ **Copy polish sweep** — shipped in #143 (Deep-Dive fallback removed, cyan-in-comment fixed).
5. Per-page P2 residuals — most flagged with 🟨 above; opportunistic.

---

## 7. §10 — UX ideas from the design foundation

Follow-ups seeded during the Sept 2026 sprint but not yet shipped:

| # | Item | Pri | Effort | Notes |
|---|---|---|---|---|
| UX1 | ✅ **Ctrl+K command palette modal** — shipped in #145. `st.dialog`-based modal, JS keybind via `components.v1.html`, sidebar `⌘ K` trigger button, sidebar bar retained as AppTest fallback. | ✅ Shipped | — | — |
| UX2 | **Hover preview cards on tickers** — show a mini-chart + score chip on hover. | 🟨 P2 | M | ✅ Shipped — `ticker_hover_wrap` (pure-CSS). Live on 02 top picks, 03 holdings cards, 14 watchlist chip strip, 04 hero kicker. Not possible inside st.dataframe cells. |
| UX3 | ✅ **Live-tick pulse** — `.tick-pulse-{up,down}` one-shot classes shipped in #142 (top-bar chips) and extended in #144 to Market Live movers + Command Centre top picks + My Portfolio holdings. Shared helper `tick_pulse_tracker(key)` in `chart_helpers.py`. | ✅ Shipped | — | — |
| UX4 | ~~Ticker drag-and-drop~~ | ❌ Deferred | — | Streamlit doesn't support natively; needs full custom component. |

---

## 8. How to invoke the skills against a specific page

Every page-level item above pairs with a concrete skill call. Example runbook for Analyze Stock:

```
1. Skill: trading-dashboard-design      → pull component + layout patterns
2. Skill: taste-skill                   → critique spacing / density
3. Skill: dataviz                       → validate chart palette + hover rules
4. Skill: apple-design                  → gesture / hover / transition polish
5. Skill: page-smoke-check              → auto-runs on save (project hook)
```

Every page edit under `dashboard/pages/` triggers `page-smoke-check` from `.claude/hooks/` automatically — no need to invoke by hand. `verdict-regression-reviewer` is only needed if scoring/thesis output changes shape (label rewrites don't count).
