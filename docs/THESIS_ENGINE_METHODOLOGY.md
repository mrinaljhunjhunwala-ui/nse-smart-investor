# Structured Thesis Engine — Methodology (Phase A1)

How `analysis/thesis/` turns the platform's **existing** signals into structured investment
reasoning: **Bull factors · Bear factors · Key risks · Verdict**. This is a deterministic,
rules-based synthesis layer — **no AI, no LLM, no narrative generation**. Every output point is
traceable to a source subsystem and a supporting metric.

## Design

```
existing signals ──► build_inputs() ──► ThesisInputs ──► rules ──► ThesisResult
(composite score,     (integration       (flat, typed,    (pure       (bull[], bear[],
 deep-confirmation,    seam; optional      all-Optional     functions)   risks[], verdict)
 fundamentals,         pieces, lazy
 beta, sector)         defensive loads)
```

- **`thesis_models.py`** — typed contracts. `Factor(text, source, evidence, polarity)`,
  `ThesisInputs` (normalized snapshot, every field Optional), `ThesisResult`.
- **`thesis_rules.py`** — pure functions: `bull_factors`, `bear_factors`, `key_risks`,
  `compute_verdict`. Same inputs ⇒ byte-identical output.
- **`thesis_engine.py`** — `generate_thesis(inputs)` (pure core, what the tests target) and
  `build_inputs(ticker, …)` (assembles inputs from live subsystems; each optional/wrapped).

**Two key properties:**
1. **Pure core.** `generate_thesis` touches no network and no subsystem — it is total over its
   input and fully reproducible.
2. **Graceful degradation.** Every input is Optional. A rule that needs a missing field simply
   does not fire, so a partial signal set yields a smaller (still valid) thesis rather than an error.

## Inputs consumed (existing capabilities only)
| Input | Source | Used for |
|---|---|---|
| Composite + component scores (technical/momentum/volume/pattern/sentiment) | `analysis.score.CompositeScore` | bull, bear, risks, verdict band |
| Weekly trend, relative strength, earnings proximity, 9-signal agreement | `dashboard…_deep_confirmation` | bull, bear, risks |
| Revenue CAGR, EPS CAGR, ROE, Debt/Equity (+ partial flag) | `analysis.fundamentals.analytics` | bull, bear, risks |
| Beta vs Nifty | `analysis.hedging.calculate_stock_beta` | risk |
| Sector | `data.universe.get_sector` | context |
| News sentiment (optional) | caller-supplied | bull, bear, risk |

No new data providers are introduced.

## Traceability contract
Every factor carries three fields, e.g.:
> **Bull:** "Revenue is compounding strongly" · **Source:** Fundamentals · **Evidence:** Revenue CAGR = 18.4%

The verdict carries a `verdict_rationale` string (the exact arithmetic) and `inputs_present`
(which subsystems contributed) for provenance.

## Rule thresholds (single source of truth, from `thesis_rules.py`)
**Bull** — Revenue CAGR ≥ 15% (≥ 8% = "steadily"); EPS CAGR ≥ 15%; ROE ≥ 15%; D/E < 0.5;
Technical ≥ 30/40; Momentum ≥ 18/25; Volume ≥ 10/15; Pattern ≥ 5/10; weekly uptrend;
relative strength = outperforming; ≥ 70% of deep-confirmation checks bullish; Composite ≥ 70/100;
positive news.

**Bear** — Revenue CAGR < 0; EPS CAGR < 0; ROE < 8%; Technical < 15/40; Momentum < 8/25;
weekly downtrend; relative strength = underperforming; Composite < 40/100; negative news.

**Key risks** (the required set) — Beta > 1.2; D/E > 1.0 (> 1.5 → "High leverage"); Momentum < 10/25;
earnings within 7 days; negative news **or** sentiment ≤ 3/10; Technical < 15/40; partial
fundamentals (data-quality caveat).

## Verdict (deterministic)
```
band  = composite-score lean:  ≥75 → +2 · ≥62 → +1 · ≥45 → 0 · ≥30 → −1 · else −2
nudge = +1 if (bull−bear) ≥ 3 ;  −1 if (bear−bull) ≥ 3 ;  −1 more if risks ≥ 4
final = clamp(band + nudge, −2, +2)
```
| final | Verdict |
|---|---|
| +2 | **Strong Positive** |
| +1 | **Positive** |
| 0 | **Neutral** |
| −1 | **Negative** |
| −2 | **Strong Negative** |

The composite score (the platform's existing core verdict) anchors the result; the bull/bear
balance and a heavy-risk load can nudge it by at most one notch, avoiding double-counting the same
underlying signals.

## Explicitly out of scope (Phase A1)
- **No AI / LLM / generated prose** — output is structured lists only; the UI renders them as lists,
  not paragraphs.
- **No new data** — Portfolio Fit (Phase B), valuation context and liquidity (Phase C) are separate.
- **Not advice** — descriptive synthesis of model signals.
