# Handoff — 2026-09-25 · Audit fixes, efficacy re-run, bear-regime scoring

## Repo state
- **`main` at `1150886`**: CI passing. Local `main` is synced, and the only untracked item is `archive/`.
- **Canonical checkout:** `D:\Kashti Claude\nse-smart-investor`.
- **Open PRs:** none from this work.
- **Remote branches:** `main`, `alerts/consolidate-fresh-workflow` (has an open PR, not ours), and `ux2-ticker-hover-preview`.
  - `ux2-ticker-hover-preview` is the closed #149. Its code shipped in #150, but it was never merged, so it's safe to delete once the user OKs it.
- **Cleaned up:** all agent worktrees and 61 merged remote branches.

## What shipped (#150 → #168)

**UI/P2 backlog (#150–#161):**
- Tables: `dashboard/shared/table_styles.py`.
- Charts: diverging colours, radar, FII/DII panels.
- UX2 hover.
- Market Live tape and heatmap; Command Centre regime strip.
- Colour tokens: `dashboard/shared/tokens.py`, the single source of truth, with no raw hex allowed in pages.
- `st.html` migration (Streamlit ≥ 1.52).
- `utils/sql.py::read_sql_df`.
- The smoke test now catches pages that don't compile.

**Audit fixes (#162–#166):**
- **Relative-strength fix:** RS no longer zeroes when Nifty lags a bar, and the Nifty and FII/DII caches now expire (1 h; failures retried after 5 min).
- **Missing moving averages:** they score neutral (`sma_available` flag), and the narrative says when the 200-day average isn't available yet.
- **TQS:** the volume ratio is capped instead of falling to NaN.
- **Backtest:** trading costs are charged per side (they were counted twice).
- **Verdict ledger:** horizons in trading days, plus alpha and a separate "win vs Nifty" rate.
- **Quality Watch:** moved into `analysis/quality_watch.py`, with sector-aware ratios via `sector_classification.quality_ratio_keys()`.
- **Buy/sell language removed everywhere:**
  - verdict labels via `trade_utils.verdict_display_label()` and actions via `_display_label()`
  - the `analysis/` narratives, portfolio signals and MTF/hedging/regime notes
  - checklist `.verdict` renamed to `.summary`
- **Score scale:** shown as /90 everywhere.
- **Quality input:** the FinalVerdict now gets a real quality score.
- **Bug fixes:** page 22 NaN crash, FII/DII shared y-axis, Command Centre sparkline prefetch, and alert JS now uses `json.dumps`.

**Efficacy re-run (#167):** full report in `docs/SCORE_EFFICACY_2026-09-24.md`; the old report is marked superseded.
- **What the study now replays:** RS, the VIX part of sentiment, and the live regime label (`--regime-weights`, `--no-rs`).
- **Result:** the per-date rank correlation (IC) is **+0.020 at 20 days (t ≈ 2.6) and +0.029 at 60 days**. The top decile beats the bottom by +2.2 points at 20 days and +5.5 at 60, and the labels now run in the right order.
- **By regime:** trend_up +0.047, range about 0, trend_down −0.02, risk_off −0.12. 2025 was negative.
- **Why the old report said "inverted":** it pooled across dates (market-wide swings between dates swamp the within-date ranking) and it had no RS.

**Scoring change (#168):**
- **Bear option on by default:** `NSE_USE_REGIME_WEIGHTS` now defaults ON (`=0` disables it). In trend_down and risk_off markets, the momentum pillar's absolute-returns half becomes a 5-day reversal percentile.
- **Regime cache:** the live regime label is cached for 30 min (5 min after a failure) by `score._live_regime_label()`.
- **VIX sentiment neutral:** VIX points are fixed at the "normal" value (6.0 legacy / 5.0 in flows mode). VIX still drives stop width and horizon.
- **Regression review:** safe to merge. **Today's regime is trend_down, so bear mode is live**; in the reviewer's 19-stock sample, 17 rose by 7–14 points and two fell slightly (HDFCBANK −4.0, ULTRACEMCO −0.9).

## Guard tests (they fail CI, so don't work around them)
- **`test_no_advice_copy.py`:**
  - bans instruction phrases in UI and `analysis/` string literals, including f-strings
  - flags a raw `.verdict` / `.action` interpolated into an f-string
  - checks the display mappers cover every engine value
  - exempts `dashboard/shared/ai/` and docstrings
- **`test_tokens.py`:** no raw hex in pages.
- **`test_pages_smoke.py`:** compiles each page and checks the main area renders.
- **Scoring behaviour:** `test_bear_regime_vix_neutral.py` and `test_engine_audit_fixes.py`.

## Open / next
1. **Composite golden snapshot:** add `data/composite_golden_snapshot.json`. The regression reviewer recommended it twice; for now, scoring changes are checked by hand-sampling stocks.
2. **Three scoring inputs may be stale:** FII/DII derivatives, option-chain PCR and F&O OI.
   - They are read from database snapshots, and no GitHub workflow runs `scripts/fetch_nse_{option_chain,fii_deriv,fno_bhavcopy}.py`.
   - `data_health.py` has no freshness probe for them.
   - Ask the user whether an external scheduler runs them.
3. **Validation gaps:** sector rank, flows, delivery % and positioning can't be replayed historically; survivorship bias is not corrected.
4. **Still to check by hand:**
   - mobile layout on real phones (F2)
   - the page 04 drift banner, which only appears during market hours
   - page 18 C/D/F grade shades on a real screen
5. **Data sources:** Stooq has been dead since 2026-09-06, costing timeouts on every fetch; consider a "known dead" switch. NSE corp-info times out intermittently.
6. **Page 02 is slow:** about 200 s locally (limit 240) even with the bear option off.

## Gotchas
- **Don't switch branches in the main checkout while tests or agents are running.** It caused spurious failures twice. Use worktrees.
- **Research runs** (`py -m research.score_efficacy --period 5y`) take about 11 minutes. They write into `research/output/` (untracked) and overwrite each other, so copy each run to `run_*/` before starting the next.
- **Watch the working directory.** Commands that `cd` into a subfolder can leave the session there. The repo hooks use relative paths, so Write then fails. `cd` back to the repo root.
- **`gh pr checks N && gh pr merge N`** skips the merge while checks are still pending. Run `gh pr checks N --watch` first.
- **Parallel agent PRs** that append CSS to the end of `design.py` always conflict; resolve by keeping both blocks.
- **AppTest in tests:** use absolute paths, because CI resolves relative paths against the test file.
- **Force-push:** ask first. Instead, push the rebased branch under a new name and open a new PR (as done for #168).

## Conventions
- **No buy/sell/hold instruction copy, ever** (CLAUDE.md rule 1).
- **Composite is 0–90, as four pillars (40+25+15+10).** No candlestick component.
- **`analysis/` stays pure:** no Streamlit imports.
- **Scoring changes:** run the `verdict-regression-reviewer` agent before merging.
- **Windows shell:** use `py`, with `PYTHONUTF8=1`.
- **Push permission:** the user has standing permission to push after committing; always report the push.
