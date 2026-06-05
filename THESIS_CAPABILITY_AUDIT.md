# Investment Thesis Capability Audit

**Question:** what's required to generate Bull Case · Bear Case · Key Risks · Investment Thesis ·
Portfolio Fit — i.e. *"Explain this stock in plain English."* Capability mapping + gap analysis
only; **no implementation, no AI integration** in this pass.

## Headline
The platform is **thesis-ready on data, but has no synthesis layer.** ~90% of the *inputs* already
exist and are unusually rich — the composite score's **per-component detail dicts** and
`_deep_confirmation`'s **9-signal agreement** (weekly trend, relative strength, earnings proximity)
are effectively *pre-computed bull/bear evidence*. The work is a **rules-based synthesizer** that
turns existing signals into structured prose, plus 3–4 small data inputs — **not** data collection,
and **not** AI (which is a later polish, grounded on the rules output).

## Input inventory (the 8 requested)

| Input | Status | Where it lives | Thesis usefulness |
|---|---|---|---|
| **Technical scores** | ✅ **Rich** | `analysis/score.py` — composite + technical/momentum/volume/pattern/sentiment, **each with a `detail` dict of reasons** + `headline` + `narrative`, entry/SL/TP/RR | Bull/Bear/Verdict — the detail dicts are ready-made bullet sources |
| **Momentum** | ✅ Present | score `momentum_score` + indicators; `_deep_confirmation` weekly trend + RS vs Nifty | Bull/Bear |
| **Fundamentals** | ✅ Present (Phase 0) | `analysis/fundamentals` — ROE, Rev/EPS CAGR, D/E (schema also has FCF, margins, **P/E, P/B** not yet surfaced as analytics) | Bull/Bear/Risks |
| **Beta** | ✅ Present | `analysis/hedging` (stock + portfolio) | Risks/Fit |
| **Sector exposure** | ✅ Present | `data.universe.get_sector` (stock); `portfolio_manager.sector_weights` (book) | Risks/Fit |
| **Concentration** | ✅ Present (book) | `portfolio_manager.concentration_risk` + Phase-1 risk-contribution | Risks/Fit |
| **Portfolio risk** | ✅ Present (Phase 1) | `analysis/portfolio_risk` — Sharpe/Sortino/Calmar/MaxDD/vol/correlation/risk-contribution | Risks/Fit |
| **Backtest results** | 🟡 **Partial** | `backtest/runner` + strategies exist, but per-stock results are **run on-demand**, not stored/wired as a thesis input | Optional evidence ("this setup won X% historically") |

**Also already present and thesis-relevant** (not on the list but valuable): `_deep_confirmation`
(weekly trend, relative strength %, **earnings proximity**, 9-check bull/total agreement, named
`signals` list); news sentiment (`utils/news` + the Analyze page); earnings dates (`data/events.py`);
VIX / market regime (sentiment score); risk-reward levels (entry/SL/TP/RR).

## What each output needs → have vs missing

| Output | Needs | Have | Missing |
|---|---|---|---|
| **Bull Case** | positive technical + momentum + fundamentals + RS + sector + cheap valuation | score detail dicts, deep-confirmation, fundamentals analytics, sector rank | **valuation-context** ("is it cheap"), **peer-relative** rank, the **synthesizer** |
| **Bear Case** | negative signals, high debt/beta/vol, expensive, RS underperformance, bearish patterns | same inputs (negatives), beta, D/E, volatility | valuation-context, the synthesizer |
| **Key Risks** | beta/vol, concentration, **liquidity**, earnings proximity, leverage, drawdown, data-quality | beta, risk-contribution, earnings days, D/E, `is_partial` flags | **liquidity/turnover** metric, the risk-aggregator |
| **Investment Thesis** | weave bull+bear+risk+verdict into a coherent summary | score verdict/action + narrative as a seed | the **thesis assembler** |
| **Portfolio Fit** | candidate's correlation to current holdings, marginal beta/sector/concentration impact, position size | Phase-1 correlation/beta, sector weights, `position_sizer` | **marginal-fit computation** (candidate vs current book) |

## Missing inputs — importance / complexity / value

| Gap | Importance | Complexity | User value |
|---|---|---|---|
| **Synthesis engine** (rules-based thesis assembler over existing signals) | **Critical — the feature itself** | **Medium** (rules, no new data; reuse score detail dicts + deep-confirmation + fundamentals) | **High** — delivers 4 of 5 outputs immediately |
| **Portfolio-fit marginal computation** (candidate's corr/beta/sector/concentration impact + size) | High (the unique 5th output; differentiator) | Medium (extends Phase 1: fetch candidate returns, corr vs holdings, marginal β, sector delta) | High |
| **Valuation context** (P/E vs own 5-yr band, or sector median) | High (valuation is central to any thesis) | Medium (own-history P/E = price ÷ historical EPS; sector median needs peers) | High |
| **Liquidity / tradability** (avg daily turnover, free float) | Medium-High (key risk for small/mid-caps; makes the thesis actionable) | **Low** (avg volume × price from existing price history) | Medium-High |
| **Peer / sector-relative rank** (ROE/growth/valuation vs sector) | High (a real thesis is relative — "best-in-sector ROE") | **High** (needs sector peer set + cross-sectional fundamentals; Yahoo small-cap gaps) | High (but gated on fundamentals depth) |
| **Per-stock backtest wiring** (cache a strategy backtest as evidence) | Medium (supporting evidence, not essential) | Medium (wire runner per-stock + cache) | Medium |

## Roadmap — "Explain this stock in plain English"

### Phase A — Rules-based Thesis Synthesizer (keystone, **no new data, no AI**)
A `thesis` module: `ticker → {bull[], bear[], risks[], thesis, verdict}`. Pulls the existing
CompositeScore (+ component detail dicts), CompanyFundamentals + analytics, sector, and
`_deep_confirmation`; applies rules (e.g. *ROE > 15% & rising → bull*; *D/E > 1.5 → risk*;
*RS underperforming + downtrend → bear*) to assemble structured, templated plain-English output.
Surface on the Analyze Stock page. **Effort: M (~3–4 d). Value: High** — delivers Bull/Bear/Risks/
Thesis from data that already exists.

### Phase B — Portfolio Fit Assessment (the 5th output)
Extend `portfolio_risk`: marginal correlation of the candidate to current holdings, its impact on
portfolio beta + sector concentration, and a `position_sizer`-based size suggestion → "diversifies /
adds concentration / raises beta." **Effort: M (~2–3 d). Value: High** (unique).

### Phase C — Data enrichment (sharpens the thesis)
Valuation context (own-history P/E band) **[M]** and a liquidity flag **[S]** — both high-leverage.
Peer-relative rank **[L, data-gated]** optional, stronger once a deeper fundamentals feed lands.

### Phase D — AI narration (LATER — explicitly out of scope now)
Wrap Phase A's **structured, factual** bull/bear/risk output with an LLM for fluent prose (the
claude-api pattern), grounded strictly on the rules-derived facts so it rephrases rather than
invents. Rules-based output remains the fallback. **Gated on an API key + cost.**

## Recommendation
**Build the rules-based synthesizer first.** "Explain this stock in plain English" is achievable
**now, without any AI**, because the hard part — the signals — already exists and is rich. Sequence:
**A (synthesizer)** → **B (fit)** → **C (valuation + liquidity)** → **D (AI polish, later)**. The only
genuinely new *data* work is small (liquidity is trivial; valuation-context and fit are medium
extensions of existing engines); the headline effort is the **synthesis layer**, not collection.

*Audit only — no features implemented, no AI integration.*
