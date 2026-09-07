# UI / UX Design Proposal (2026-09-08)

_Companion doc to [`UI_UX_BACKLOG.md`](UI_UX_BACKLOG.md) - takes the same living
list of items and adds the information-architecture, sidebar-redesign, and
reference-implementation layers the backlog didn't cover._

Backlog owns _which pages need what work._
This doc owns _which pages exist at all, how they're grouped, and what the
whole thing should feel like when a first-time user opens it._

Skills consulted: `trading-dashboard-design`, `taste-skill`, `apple-design`,
`emil-design-eng`, `dataviz`. World references: Bloomberg Terminal, TradingView,
Zerodha Kite web, Groww web, Dhan.

> **Note on `trading-dashboard-design` (2026-09-08)** - the skill's
> `SKILL.md` still names an old target-file path (`D:\Downloads\...`) from
> before this project moved to `E:\code\nse-smart-investor`. Its
> `references/*.md` files - theme palettes, component specs, plotly
> layouts, layout patterns - are still current and are what this doc
> pulls from. Treat the skill as a **pattern library**, not a
> project-configuration source; the actual app entry is
> [`dashboard/app.py`](../dashboard/app.py) and its CSS lives in
> [`dashboard/shared/design.py`](../dashboard/shared/design.py).

---

## 1. Vision

Not "better Streamlit". A **retail-trader dealing room**: dense enough to read
five things at once, calm enough to sit on for an hour, honest enough that
a SEBI compliance officer would nod at every chip. The user is Indian, on
NSE/BSE, using this alongside their broker.

Three anchors:

- **Bloomberg-density on the surfaces that matter** (Command Centre, Analyze
  Stock, Portfolio) - grid layouts, monospaced prices, per-second cadence
  where it's real.
- **Zerodha-quietness on the surfaces that don't** (Position Sizer, Investor
  Guide, Angel One setup) - lots of whitespace, one primary action per view.
- **TradingView-restraint on charts** - one accent per plot, semantic
  colour only, no gradient-vomit.

Style rules already codified in `dashboard/shared/design.py` (NSE Pro theme:
IBM Plex, cyan `#2fd1e0` accent, semantic red/green). The design work here
is _consistency_ and _reduction_, not a re-skin.

---

## 2. Information architecture

### 2.1 The 19-page tree today

Grouped as `dashboard/shared/nav.py` currently arranges them:

| Group | Pages | Count |
|---|---|---:|
| Home | Command Centre | 1 |
| Markets | Market Live · Overview · Quality Watch · FII / DII Flows | 4 |
| Portfolio | My Portfolio · Paper Trades · My Watchlist · Tomorrow's Watchlist | 4 |
| Trading | Intraday Trader · Smart Screener | 2 |
| Analysis | Analyze Stock · Backtest · Trend Quality Score · Deep Dive Analysis · Verdict Calibration | 5 |
| Tools | Position Sizer · Angel One · Investor Guide | 3 |

**19 pages, 6 groups.** The grouping instinct is right; the placement is off
in three specific spots, and one merge is genuinely warranted.

### 2.2 Problems worth fixing

**P-IA1 · Deep Dive Analysis is a superset of Analyze Stock.**
Two per-name research pages. A user has to remember which one goes deeper.
Fix: **fold Deep Dive into Analyze Stock as a "Deep Dive" tab** inside the
existing tab strip (post-C.1 tabs already ship 7 tabs; add an 8th). Delete
[`dashboard/pages/20_deep_dive.py`](../dashboard/pages/20_deep_dive.py) once
its content is inside Analyze Stock. Sidebar count 19 → 18.

**P-IA2 · Tomorrow's Watchlist is in Portfolio; it belongs in Trading.**
"Tomorrow's Watchlist" is a next-session _scan_ output. The Portfolio group
is for _my holdings + my paper trades + names I curated_. Move it next to
Smart Screener where the other scanner lives. Related: **rename group
"Trading" → "Scanners & Signals"** to reflect what actually lives there.

**P-IA3 · Verdict Calibration is an internal analytics tool.**
It reads the `verdict_log` and shows calibration curves. Not a per-name
Analysis surface; it's a meta view of the model. Move to Tools (or a new
"Ops" group).

**P-IA4 · Icon collision on 📊.**
`Overview` and `Trend Quality Score` both use 📊 in `_PAGE_EMOJI`. Two pages
with the same sidebar glyph are impossible to scan past. Reassign TQS to a
non-colliding glyph (proposal: 🌊 to match the "quality" pillar concept, or
📶 for signal-strength).

**P-IA5 · "Market Live" and "Overview" are close.**
Not identical (Overview is macro/breadth, Market Live is live ticker) but a
first-time user opening the sidebar can't tell from names alone which is which.
Do NOT merge; do rename `Market Live` → `Live Ticker` and `Overview` →
`Market Breadth` so the noun is the clue.

**P-IA6 · "Trading" group of 2 with a 5-count group next to it.**
After IA1 (drop Deep Dive) + IA2 (move Tomorrow's Watchlist) + IA3 (move
Verdict Calibration), the group balance becomes:

| Group | Pages | Count |
|---|---|---:|
| Home | Command Centre | 1 |
| Markets | Live Ticker · Market Breadth · Quality Watch · FII / DII Flows | 4 |
| Portfolio | My Portfolio · Paper Trades · My Watchlist | 3 |
| Scanners & Signals | Smart Screener · Tomorrow's Watchlist · Trend Quality Score | 3 |
| Analysis | Analyze Stock (with Deep Dive tab) · Backtest | 2 |
| Tools & Ops | Intraday Trader · Position Sizer · Angel One · Verdict Calibration · Investor Guide | 5 |

**17 pages, 6 groups. Balance is more even, semantic homes are honest.**

### 2.3 Optional further reductions (not proposing yet, need your call)

- **Merge `Quality Watch` into `My Watchlist`.** Both are per-name watch
  surfaces; Quality Watch is the RAG-flag lens on the same set. Could ship
  as a "Quality" tab inside My Watchlist. Blocks: unknown whether the two
  serve different user intents that would confuse users if collapsed. Ask
  first.
- **Merge `Backtest` into `Analyze Stock` as a "Backtest" tab.** Same-scope
  ("this ticker's history + performance"). Blocks: multi-ticker backtests
  might not fit; would need to check Backtest's actual scope.

Do these only if you agree after re-reading the pages.

---

## 3. Sidebar visual redesign

Current sidebar renders group headers as plain text, page names with a
leading emoji, and no active-state affordance beyond the underlying
Streamlit page-nav highlight. Three visible improvements:

### 3.1 Group header treatment

```
BEFORE                          AFTER
Home                            HOME ─────────────────
🎯 Command Centre               🎯 Command Centre
                                MARKETS ──────────────
Markets                         📡 Live Ticker
📡 Market Live                  📊 Market Breadth
```

- Uppercase, 10 px, letter-spacing 1.4 px, colour `var(--dim)`.
- A 1 px hairline `var(--hairline)` runs to the right of the label to fill
  the row - the group header IS the divider.
- 6 px above, 4 px below.

Pattern: `frontend-ui-engineering` §sidebar-typography +
`trading-dashboard-design` `references/layout-patterns.md` §nav-hierarchy.

### 3.2 Active-page pill

Instead of Streamlit's default full-width highlight, use a 3 px cyan bar on
the leading edge + `var(--surface-elevated)` fill:

```css
[data-testid="stSidebar"] a[aria-current="page"] {
  border-left: 3px solid var(--accent);
  background: var(--surface-elevated);
  padding-left: 9px;    /* 12 - 3 to keep text alignment */
}
```

This matches the treatment on Bloomberg's own nav and every recent
TradingView redesign - a scannable "you are here" without a heavy fill.

### 3.3 Emoji-to-icon path

Emoji are quick to ship but inconsistent across OS renderers (Windows
segoe-emoji vs macOS apple-color vs Chrome-android noto). For pages users
hit daily (Command Centre, Analyze Stock, My Portfolio, Live Ticker,
Screener) - swap to inline SVG at 16×16 with `currentColor`. Keeps the
active-state cyan bar working automatically. Emoji stay for lower-traffic
pages (Investor Guide, Angel One, Verdict Calibration) where the
inconsistency is a rounding error.

Deferred to a follow-up PR - visible win is not proportional to the code
for it. Note but do not ship in the first slice.

---

## 4. Cross-cutting design rules (extends `UI_UX_BACKLOG.md` §1)

Rules the existing backlog doesn't fully cover:

### 4.1 The five-metric ceiling

Above-the-fold density cap: **≤ 5 KPI tiles / status chips in any single
horizontal strip.** Command Centre's regime strip currently violates this
(v2-scoring chip + VIX zone + Nifty trend + market breadth + regime
verdict is already at 5; adding a warmer-health indicator from PR #64
would break it). Rule: sixth item lives in an expander or a second row.

Reference: `trading-dashboard-design` `references/layout-patterns.md` +
Bloomberg's own "no more than 5 tiles per widget" panel guidance.

### 4.2 Chip vocabulary

Every posture / status chip in the app must draw from **one** of these
four visual shapes:

| Shape | Use for | Example |
|---|---|---|
| **Solid pill** (filled) | Live state, currently true | `● BUY`, `● PANIC` |
| **Outline pill** (border only) | Descriptive posture, not a live event | `Bullish`, `Neutral` |
| **Text badge** (no shape, just colour) | Meta info, no urgency | `sc 82/100` |
| **Icon-only** | Freshness / provenance | `⟳ 5m ago`, `via NSE` |

Rule: never mix two shapes in the same chip row. Analyze Stock's Verdict
Card currently mixes solid (score-band) + outline (action) + text (RR) in
one row - it reads as three "loud" affordances competing for attention.
Fix pattern in `taste-skill` §restraint-in-affordance.

### 4.3 Indian number formatting - one helper, everywhere

Existing pages inconsistently use `Rs.1,234.56` / `₹1,234.56` /
`₹1234.56` / `1.23 Cr`. Ship a shared `format_inr(value, style)` in
[`dashboard/shared/ui_components.py`](../dashboard/shared/ui_components.py)
with three styles (`"lakh"`, `"crore"`, `"compact"`) and force-migrate
every `f"₹{x:,.2f}"` call site. About 40-50 call sites across the
project; one-day mechanical PR.

### 4.4 Motion policy (F4 from backlog, formalised)

- Enter: 180 ms ease-out
- Exit: 120 ms ease-in
- Hover: 60 ms tone-only, no scale
- Respect `prefers-reduced-motion: reduce` - hard-disable all durations
- No motion on **numbers** except when they change (flash-on-update ok;
  entry/exit slide never)

Source: `apple-design` §motion + `animate` skill's decision framework.

### 4.5 Empty states (F5 from backlog, formalised)

One helper `empty_state(icon, title, hint, cta=None)` in
`ui_components.py`. Every "no data yet" branch across the 20 pages calls it.

Design: 48 px icon (muted), 15 px title, 12 px hint, optional
`st.button` CTA below. Background `var(--surface)` at 60 % opacity. Never
show empty placeholders as bare `st.info(...)` again.

---

## 5. Execution roadmap (revised from backlog §6)

The backlog's suggested order was sound but had two miscalculations:

1. It put the **F3 dark-mode parity** first ("biggest visible inconsistency,
   ~1 day"). But dark-mode parity fixes are cheap to do in-flight alongside
   any page-level edit. Doing it as a dedicated sweep wastes context.
2. It put **information architecture** nowhere. IA changes cascade into every
   later change - if we're going to move Tomorrow's Watchlist and rename
   Market Live, do that first so subsequent PR bodies land against the new
   names.

Proposed re-ordered execution:

### Slice 1 - IA + sidebar structure  (this doc → then one code PR)

Ships:
- [ ] Rename `Market Live` → `Live Ticker`, `Overview` → `Market Breadth`
- [ ] Reassign TQS emoji off `📊`
- [ ] Move Tomorrow's Watchlist → Scanners & Signals group
- [ ] Move Verdict Calibration → Tools & Ops group
- [ ] Rename group `Trading` → `Scanners & Signals`
- [ ] Rename group `Tools` → `Tools & Ops`
- [ ] Sidebar group-header hairline treatment (§3.1)
- [ ] Sidebar active-page pill (§3.2)

Pure `dashboard/shared/nav.py` + `dashboard/shared/design.py` edits. No page
renames needed - Streamlit's page-nav is hidden and we control the sidebar
labels. Page files stay at their current `pages/NN_*.py` paths; only nav
labels change.

Effort: 1 PR, half-day. Zero page-smoke risk (nav changes, not page bodies).

### Slice 2 - Deep Dive fold-in (P-IA1)

Move `dashboard/pages/20_deep_dive.py`'s body into a new "Deep Dive" tab
inside Analyze Stock's existing tab strip (from PR #68). Delete the old
file. Update nav. Effort: 1 PR, 1 day, needs page-smoke.

### Slice 3 - `format_inr` shared helper (§4.3)

New helper + mechanical migration of all `₹` call sites. Big diff, low risk
(display only). Effort: 1 PR, 1 day, needs page-smoke on every touched page.

### Slice 4 - Empty-state kit (§4.5, backlog F5)

Ship the helper + convert Intraday Trader (biggest offender, empty
outside market hours). Effort: 1 PR, half-day.

### Slice 5 - Chip vocabulary sweep (§4.2)

Ship a documented set of chip primitives in `ui_components.py`. Migrate
Analyze Stock's Verdict Card first (highest-visibility). Effort: 1 PR,
1 day.

### Slice 6 - Backlog SH1 + SH2 (score honesty on remaining surfaces)

Ship the remaining P0 items from the backlog. Effort: 1 PR, 1 day.

### Slice 7 - Backlog IR1 (Bull/Bear/Risk card on Analyze Stock)

Highest per-page value from the backlog. Effort: 1 PR, 1 day.

### Slice 8+ - Backlog IR2/IR3/IR4 portfolio surfaces, F1 token audit, F2 mobile pass, F6 skeletons

In whatever order fits. All are opportunistic once the foundation slices
are in.

### What we're intentionally NOT doing yet

- **Emoji → SVG icon migration** (§3.3): out of proportion for user-visible
  win vs code churn. Defer.
- **Merge Quality Watch into My Watchlist / Backtest into Analyze Stock**
  (§2.3): needs your call before I touch either.
- **F7 accessibility sweep** from backlog: defer to a dedicated focused PR;
  mixing focus rings + aria labels + colour-blind checks with layout work
  guarantees one gets skimped.

---

## 6. World-class references (what to compare against)

Not to clone. To calibrate against when a design call is close.

| Reference | What to steal | What NOT to steal |
|---|---|---|
| **Bloomberg Terminal** | 5-metric-per-panel density, monospaced everything, `<TAB>` chording | Amber-on-black default (feels dated on web) |
| **TradingView** | Chart-first surfaces, `Ctrl+K` command palette, drawer-based settings | 15-chip toolbar cluttered above the chart |
| **Zerodha Kite (web)** | Restraint on the order pad, Nifty/Sensex sticky strip, three-column NORMAL/COVER/MIS radio | Cluttered right rail with too many analyses |
| **Groww (web)** | Progressive disclosure on stock pages (tabs + "See more"), soft educational language | Mobile-first shortcuts that don't work on desktop |
| **Dhan** | The "watchlist as first-class citizen" approach; multi-account nav | Overdone hover-lift animations |

Reference each when a specific slice ships. Don't try to be all five at
once - that's the "designed by committee" look.

---

## 7. How to run this against a slice

Each slice above should:

1. Load `trading-dashboard-design` skill first (references + patterns).
2. Compose the change.
3. Run `page-smoke-check` on every touched page (auto-triggered by hook).
4. If a scoring surface's shape changed, spawn `verdict-regression-reviewer`.
5. If a fetcher was touched, spawn `data-provenance-auditor`.
6. Pass the guardrail check: §5 composite-score shape unchanged, §11 module
   purity, §21 no em-dashes.

Every slice ships as its own PR. This doc + [`UI_UX_BACKLOG.md`](UI_UX_BACKLOG.md)
stay updated together as work lands - never let them drift.

---

## 8. See also

- [`UI_UX_BACKLOG.md`](UI_UX_BACKLOG.md) - the living per-page task list
  (partner doc; keeps the P0/P1/P2/P3 tagging + effort estimates).
- [`UI_AUDIT_2026-09_SPRINT1.md`](UI_AUDIT_2026-09_SPRINT1.md) - the audit
  that produced Sprint 1's design foundation work.
- [`../dashboard/shared/design.py`](../dashboard/shared/design.py) - CSS
  tokens + Plotly template; every token change goes here.
- [`../dashboard/shared/ui_components.py`](../dashboard/shared/ui_components.py)
  - shared `panel()` / `stat()` primitives; new helpers land here.
- [`../dashboard/shared/nav.py`](../dashboard/shared/nav.py) - sidebar + group
  map; Slice 1 edits this.
- `~/.claude/skills/trading-dashboard-design/` - reference material for
  themes, components, plotly, layout patterns.
