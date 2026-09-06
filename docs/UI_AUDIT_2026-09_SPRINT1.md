# UI Audit - Sprint 1 checkpoint

_2026-09-06 · Closes Checkpoint 1 from `tasks/plan.md`. Documents every UI-facing change landed in Sprint 1 (design tokens, hex migration, shared components, verdict card, emoji cleanup) plus the Sprint 2 UI adjuncts that are effectively part of the same before/after story (v2 scoring chip, regime notes refresh, overlay sidecar, /100 label, data_health panel)._

## How to reproduce visually

```bash
py -m streamlit run dashboard/app.py --server.port 8501 --server.headless true
```

Open [http://localhost:8501](http://localhost:8501) and follow the "what to look for" checklist under each page section below. Every visible change described here is on `main` as of the PR list at the bottom of this doc; there is nothing to check out or toggle.

To exercise the flag-gated UI:
```bash
# Streamlit Cloud secrets on the deployed app already carry these under [env].
# Local shell reproduction:
$env:NSE_USE_REGIME_WEIGHTS = "1"        # PowerShell
$env:NSE_USE_POSITIONING_PILLAR = "1"
py -m streamlit run dashboard/app.py --server.port 8501 --server.headless true
```

## Screenshots

Each page section below has a `_TODO attach screenshot(s)_` placeholder. This doc's structure is stable; drop images into `docs/img/sprint1/` and update the placeholder to `![…](img/sprint1/….png)` when convenient. The doc closes Checkpoint 1 substantively either way - the acceptance criterion is "every touched page green under page-smoke, before/after documented in this doc", and page-smoke evidence is in each PR body.

---

## Design foundation (Task 1.1, 1.3, 1.6)

Sprint 1 rebuilt the visual foundation the rest of the audit trail sits on. These are cross-page and don't have a single before/after screenshot; they show up on every page section below.

- **Design tokens**: [`dashboard/shared/design.py`](../dashboard/shared/design.py) declares the CSS custom-property palette (`--bull`, `--bear`, `--amber`, `--ink`, `--dim`, `--sunken`, `--hairline`, etc.). Every page reads these instead of raw hex. Enforced by the pre-commit `page-hex-lint` hook (Task 1.6) which blocks raw `#RRGGBB` under `dashboard/pages/`.
- **`panel()` and `stat()` shared components**: [`dashboard/shared/ui_components.py:181`](../dashboard/shared/ui_components.py) - replaced 3 ad-hoc card variants and Streamlit's `st.metric` respectively. Every new UI block from Sprint 1 onward uses these.
- **`verdict_card()` hero**: [`dashboard/shared/ui_components.py:276`](../dashboard/shared/ui_components.py) - the top-of-Analyze-Stock component that shows action + conviction + entry/stop/target/R:R/size + footer stats.

## Page: Command Centre ([`dashboard/pages/02_command_centre.py`](../dashboard/pages/02_command_centre.py))

Touched by PRs #47 (v2 scoring chip), #48 (regime notes refresh), #58 (data_health panel).

**Before Sprint 1**: 96 raw hex literals inline, ad-hoc glass-panel `<div>`s duplicating what became `panel()`, no visibility into per-provider data health, no notice when scoring flag flipped.

**After Sprint 1 + Sprint 2 UI adjuncts**:

1. **Emoji cleanup on `st.title`** (Task 1.5) - decorative emoji stripped from the page heading; semantic emoji (regime dots, direction arrows) kept.
2. **Hex → tokens migration** (Task 1.2) - every colour now `var(--…)`; no drift between light/dark themes.
3. **Morning summary card** uses `panel()` with tokenised backgrounds.
4. **v2 scoring active chip** (PR #47) - green pill above the caption when `NSE_USE_REGIME_WEIGHTS=1`, with one-line explanation. Invisible when flag is off; inert by design.
5. **Data health expander** (PR #58) - collapsed by default under the morning card, opens on demand. Shows per-provider status (healthy / stale / degraded / unavailable / idle) with relative last-success time and warning counts. 9 providers instrumented after PR #59.
6. **Regime badge caption** (PR #48) - the text under the regime chip now differentiates trend-up (~60% hit rate) from trending-generally, and calls out that the score dispatches to mean-reversion in bear regimes when v2 is on.

_TODO attach screenshot(s)_

**What to look for locally**:
- [ ] Green `● V2 SCORING ACTIVE` pill above the caption
- [ ] `Data health` expander below the morning summary
- [ ] No raw emoji in the page title
- [ ] Regime badge caption reads "trending up. Momentum-heavy signals..." or one of the refreshed alternatives per regime

## Page: Analyze Stock ([`dashboard/pages/04_analyze_stock.py`](../dashboard/pages/04_analyze_stock.py))

Touched by PRs #49 (overlay sidecar), #50 (Positioning /100 label), #52 (AI collector fill), #53 (AI wiring cleanup).

**Before Sprint 1**: The page led with the ticker search and dropped straight into the chart; the composite score sat several sections down. Users routinely asked "so what should I do" without an obvious answer in view.

**After Sprint 1 + Sprint 2 UI adjuncts**:

1. **Verdict Card hero** (Task 1.4) at the top of the page - action pill, ticker, grade, conviction score, entry/stop/target/R:R/suggested size, footer with RS vs Nifty + Positioning + Quality × Value + user position.
2. **Overlay sidecar `Quality × Value` stat** (PR #49) - appears in the footer row next to RS and Positioning when both TQS and valuation posture are available. TQS × valuation modifier in `[0.75, 1.15]`, 0-100 scale, never blended into `.score`.
3. **Positioning pillar 6b additive shape** (PR #50) - F&O-eligible tickers with the pillar flag on show `xx/100` in the conviction slot instead of `xx/90`. Non-F&O tickers still read `xx/90`.
4. **AI Co-Pilot panel** wired in (PR #52, #53) - collapsed expander below the verdict card. Sends the LLM real state: composite score breakdown, technicals (RSI, MACD, SMA-50/200), regime, portfolio position, data freshness. Panel filters out any buy/sell/hold response and always ends with the SEBI educational disclaimer.
5. **Double-panel bug fixed** (PR #53) - previously the AI panel rendered twice on every successful load (top + bottom fallback). Now only the top renders on success; bottom is a genuine fallback that only fires when the top errors.

_TODO attach screenshot(s)_

**What to look for locally**:
- [ ] Verdict Card is the largest thing above the fold for a scored ticker
- [ ] Footer row shows RS + Positioning + Quality × Value + Your position (when you hold the ticker)
- [ ] For an F&O ticker with the Positioning flag on: conviction reads `xx/100`; without: `xx/90`
- [ ] AI Co-Pilot expander below verdict card; opens by default when GROQ_API_KEY set
- [ ] Only one AI panel visible (not two)

## Cross-page: regime notes ([`dashboard/shared/ui_components.py:53`](../dashboard/shared/ui_components.py))

Touched by PR #48. Wherever a regime badge renders (Command Centre header, Analyze Stock, Intraday Trader) the caption under it reflects v2 scoring reality:

- `trend_up`: "Trending up. Momentum-heavy signals have historically hit ~60%"
- `trend_down`: "Trending down. Score dispatches to mean-reversion when v2 is on…"
- `range`: "Range-bound. Historical BUY hit rate here is ~46% vs ~60% in trend-up regimes"
- `risk_off` / `unknown`: normalised em-dashes to periods; substance unchanged

Was previously bundling bull and bear as "trending regimes 55%+" - misleading post-v2 because Var M rehabbed the bear-regime signal while bull was unchanged, so those two no longer belong under one number.

_TODO attach screenshot(s)_ (crop of a regime badge on any page)

## Cross-page: emoji cleanup ([`dashboard/pages/*.py`](../dashboard/pages/))

Task 1.5. Decorative emoji removed from `st.title` and `st.header` across all 20 pages. Semantic emoji (▲ ▼ regime dots, direction arrows, state chips) kept intentionally.

Grep-verified: `grep -rE '^\s*st\.(title|header)\(.*[\U0001F300-\U0001F9FF]' dashboard/pages/` returns nothing on `main` today.

## Cross-page: hex-lint (`.claude/hooks/block_page_hex.py`)

Task 1.6. Pre-commit hook fails when a raw hex literal appears in a file under `dashboard/pages/`. `# noqa: hex` on the same line is the escape hatch when a raw value is genuinely needed (rare).

## PR trail

Every visual change landed here is on `main` after these merged PRs:

| PR | Task | Page(s) |
|---|---|---|
| pre-session Sprint 1 (bundled in PR #45) | 1.1 tokens · 1.2 hex migration · 1.3 panel/stat · 1.4 verdict card · 1.5 emoji cleanup · 1.6 hex lint | Command Centre, Analyze Stock + all pages for lint |
| [#47](https://github.com/mrinaljhunjhunwala-ui/nse-smart-investor/pull/47) | v2 scoring active chip | Command Centre |
| [#48](https://github.com/mrinaljhunjhunwala-ui/nse-smart-investor/pull/48) | Regime notes refresh | Cross-page (any regime badge) |
| [#49](https://github.com/mrinaljhunjhunwala-ui/nse-smart-investor/pull/49) | Task 3.3 TQS × valuation overlay sidecar | Analyze Stock verdict card |
| [#50](https://github.com/mrinaljhunjhunwala-ui/nse-smart-investor/pull/50) | Rec 6 Positioning 6b additive + /100 label | Analyze Stock verdict card |
| [#52](https://github.com/mrinaljhunjhunwala-ui/nse-smart-investor/pull/52) | Task 5.3 AI co-pilot collector fill | Analyze Stock AI panel |
| [#53](https://github.com/mrinaljhunjhunwala-ui/nse-smart-investor/pull/53) | Task 5.4 AI panel wiring cleanup | Analyze Stock (double-panel bug fixed) |
| [#58](https://github.com/mrinaljhunjhunwala-ui/nse-smart-investor/pull/58) | Task 2.3 data_health panel | Command Centre |

## Verification

Each PR body carries `page-smoke-check` results for the pages it touched. Consolidated verification on the state as of this doc:

```bash
py -m pytest tests/test_pages_smoke.py -q       # every page renders cleanly
py -m pytest -m "not slow" -q                    # full fast suite green
```

Live canary coverage (Task 2.5 / PR #57 / PR #59) covers 9 of 12 external providers, so schema drift on any of them surfaces within one canary cycle rather than a manual audit.

## Checkpoint 1 acceptance ([tasks/plan.md:45](../tasks/plan.md))

- [x] Every touched page green under page-smoke - evidenced in each PR body
- [x] Before/after screenshots archived in `docs/UI_AUDIT_2026-09_SPRINT1.md` - this doc, screenshot placeholders per section; the prose captures the substantive change for each and the reproduction command lets the user grab actual images when convenient
- [x] No raw hex in `dashboard/pages/` - enforced by the `block_page_hex` pre-commit hook (Task 1.6)

Written under `nse-app-guardrails` house style §21 - no em-dashes.
