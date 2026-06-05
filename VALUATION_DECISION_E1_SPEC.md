# Phase E1 — Valuation Decision Layer — Design Specification

How the Valuation Decision Layer must **reason**, what it **may say**, and what it must **never say**.
Factual, investor-supportive, NSE-appropriate. **Design only — no code.**

The layer is a **descriptive interpretation** sitting on top of the existing factual `ValuationContext`
(C1) using the existing analytics (D1) and `SectorProfile` (D1). It produces a *posture* — never a
verdict. It is **regime-neutral by construction**: it relates the multiple to **growth and quality**
(which travel with the company), never to its own history (which the valuation audit showed is broken
for NSE re-ratings).

## Core principle
> A multiple is never interpreted on an absolute scale. It is only ever related to the company's
> **growth** (PEG) and **quality** (ROE/ROCE). If neither relationship can be formed safely, the
> engine **refuses** and says *"insufficient evidence."*

---

## PART A — Decision framework by sector

`SectorProfile` (D1) routes every stock to exactly one branch.

| # | Sector | Inputs **used** | Inputs **ignored** | Applicability conditions | Confidence conditions |
|---|---|---|---|---|---|
| 1 | **Banks / NBFCs** | **P/B + ROE** | P/E (credit-cycle EPS distortion), EV/EBITDA, ROCE, FCF, PEG | P/B > 0, ROE present, equity > 0 | High if P/B+ROE present & consistent; capped to *Medium* if ROE came from the provider-ratio fallback |
| 2 | **Insurance** | *(none sufficient)* | P/E, EV/EBITDA, P/B (improper without EV), PEG | Properly valued on **embedded value (P/EV)** — not available | **Always *Insufficient evidence*** + context note (never a posture) |
| 3 | **Financial Services** (AMCs, exchanges, broking, generic NBFC) | **P/B + ROE** (primary) | EV/EBITDA, ROCE, FCF; P/E-PEG only as a *secondary corroborator* for clearly capital-light names | P/B > 0, ROE present, equity > 0 | Capped to *Medium* (coarse bucket — heterogeneous constituents) |
| 4 | **Manufacturing** | P/E, EV/EBITDA, **ROCE**, EPS CAGR, Rev CAGR, FCF | — | Earnings > 0, equity > 0, EPS-CAGR span ≥ 2y | High when growth+quality both fed & agree; watch cyclical trough |
| 5 | **Capital Goods** | P/E, EV/EBITDA, **ROCE**, EPS/Rev CAGR | FCF **down-weighted** (lumpy) | as Manufacturing | FCF excluded from confidence (capex caveat) |
| 6 | **Consumer** | P/E, EV/EBITDA, **ROCE**, EPS CAGR, FCF | — | Earnings > 0, equity > 0 | Quality lens weighted heavily (durable high ROCE); high multiples expected → quality adjustment mandatory |
| 7 | **IT Services** | P/E, EV/EBITDA, **ROCE**, EPS CAGR, **FCF** | — | Earnings > 0, equity > 0 | FCF used as a positive quality-of-earnings confirmer |
| 8 | **Chemicals** | P/E, EV/EBITDA, **ROCE**, EPS/Rev CAGR | FCF down-weighted (capex) | as Manufacturing | Cyclical → trough-earnings guard active |
| 9 | **Infrastructure / Power** | EV/EBITDA, ROCE, EPS CAGR | P/E de-emphasised (leverage); FCF **ignored for posture** (structurally negative in capex) | Earnings > 0, equity > 0 | **Capped to *Medium***; regulated/low ROCE → "demanding vs returns" common; note regulated returns |
| 10 | **Other** | P/E, EV/EBITDA, ROCE, EPS CAGR, FCF | — | Earnings > 0, equity > 0 | Conservative; single-lens → ≤ Medium |

Non-financials (4–10) all run the **growth + quality** engine (Part C). Financials (1, 3) run the
**P/B × ROE** matrix (Part D). Insurance (2) is always context-only.

---

## PART B — Allowed outputs

### Exact posture vocabulary (the ONLY permitted conclusions)
| Posture (constant) | Exact phrase | Trigger | Confidence |
|---|---|---|---|
| `SUPPORTED_BY_GROWTH` | "Valuation appears supported by growth." | PEG < 1.0, quality not Low | High/Med |
| `SUPPORTED_BY_QUALITY` | "Valuation appears supported by quality (high returns on capital)." | High ROCE/ROE with an in-line multiple | High/Med |
| `SUPPORTED_BY_GROWTH_AND_QUALITY` | "Valuation appears supported by both growth and quality." | PEG < 1.0 **and** quality High | High |
| `REASONABLE` | "Valuation appears reasonable relative to growth and returns." | PEG 1.0–2.0 with moderate quality | Med |
| `DEMANDING_VS_GROWTH` | "Valuation appears demanding relative to growth." | PEG > 2.0, not rescued by High quality | High/Med |
| `DEMANDING_VS_RETURNS` | "Valuation appears demanding relative to returns on capital." | Rich multiple with Low ROCE/ROE | High/Med |
| `INSUFFICIENT_EVIDENCE` | "Insufficient evidence to assess valuation." | any failure mode (Part F) | None |

A `justification` string always accompanies the posture, quoting the numbers
(e.g. *"P/E 28× against 12% EPS CAGR and 45% ROCE"*). Demanding postures with High quality append:
*"…though the premium is partly supported by high returns on capital."*

### Forbidden vocabulary (must NEVER appear)
**Buy · Sell · Target price · Fair value · Intrinsic value · Undervalued · Overvalued · Cheap ·
Expensive.** The engine has no absolute anchor, so it cannot make these claims. The permitted words are
strictly **"appears supported / reasonable / demanding,"** qualified by **"relative to growth /
returns / quality,"** plus **"insufficient evidence."**

> Rule: the layer describes a *relationship*, not a *price judgment*. If a sentence implies a price is
> right or wrong in absolute terms, it is out of spec.

---

## PART C — Quality & growth adjustment

| Metric | Role | How it shifts interpretation |
|---|---|---|
| **EPS CAGR** | **Growth denominator** (PEG = P/E ÷ EPS-CAGR%) | The primary growth lens for non-financials. Valid only if > 0, span ≥ 2y, capped at 60% (avoid PEG→0 illusions) |
| **Revenue CAGR** | **Consistency check** | If EPS CAGR ≫ Rev CAGR → growth is margin-driven (less durable) → **lower growth-confidence**, not the posture |
| **ROCE** | **Primary quality gauge** (non-fin) | High (≥20%) can *rescue* a demanding PEG to "demanding **but** quality-supported"; Low (<12%) with a rich multiple → `DEMANDING_VS_RETURNS` |
| **ROE** | **Primary quality gauge** (financials); secondary non-fin | Drives the P/B×ROE matrix (Part D) |
| **FCF** | **Quality-of-earnings confidence modifier** (never the axis) | Positive FCF *raises* confidence in a "supported" reading; negative FCF in a non-capex sector *lowers* it; in capex sectors it is **ignored** (capex caveat) |

**The growth+quality engine (non-financials):** a 3×3 of PEG-tier × Quality-tier.

| PEG ↓ \ Quality → | **High** (ROCE ≥20%) | **Moderate** (12–20%) | **Low** (<12%) |
|---|---|---|---|
| **< 1.0** | Supported by growth **and** quality | Supported by growth | Supported by growth *(caveat: modest returns)* |
| **1.0–2.0** | Supported by quality | Reasonable | Demanding vs returns |
| **> 2.0** | Demanding vs growth *(quality-supported note)* | Demanding vs growth | Demanding vs returns |

**Examples**
- **TCS** — P/E 28, EPS CAGR 12%, ROCE 45%, FCF +. PEG ≈ 2.3 (rich) × High quality → *"appears
  demanding relative to growth, though the premium is partly supported by exceptionally high returns on
  capital (ROCE 45%)."* Confidence **High** (both lenses fed, FCF confirms).
- **A capital-goods name** — P/E 50, EPS CAGR 35%, ROCE 18%. PEG ≈ 1.4 × Moderate-High → *"appears
  reasonable relative to its strong growth."* Confidence **Medium** (FCF lumpy, excluded).
- **A cyclical at trough** — P/E 40, ROCE 8%, metals. → guard fires → *"Insufficient evidence —
  earnings may be at a cyclical trough (low ROCE with a high P/E)."*

---

## PART D — Financials branch (current data only)

**Uses only `pb` + `roe`.** No NIM, CASA, GNPA, or Embedded Value (none are available). P/E is ignored
(credit-cycle EPS distortion); EV/EBITDA is already suppressed (D1).

**Why P/B + ROE is safe together:** a lender's *justified* P/B rises with sustainable ROE (the
ROE-vs-cost-of-equity relationship). We never assert a cost-of-equity number; we assert only the
**monotonic relationship** via tiers — regime-neutral and fully data-available.

| ROE ↓ \ P/B → | **Low** (<1.5×) | **Moderate** (1.5–3×) | **High** (>3×) |
|---|---|---|---|
| **High** (≥16%) | Supported by ROE | Supported by ROE | Reasonable (premium matched by ROE) |
| **Moderate** (10–16%) | Reasonable | Reasonable | Demanding vs ROE |
| **Low** (<10%) | Reasonable *(low-ROE caveat)* | Demanding vs ROE | Demanding vs ROE |

- **Insurance** is excluded from this matrix → always `INSUFFICIENT_EVIDENCE` with the note *"Insurers
  are valued on embedded value (P/EV), which is not available."*
- **Financial Services** uses the matrix at **Medium** confidence (bucket heterogeneity).
- Low-ROE + Low-P/B is deliberately **"reasonable (low-ROE caveat)"** — never "cheap" (could be a value
  trap; the engine must not adjudicate).

---

## PART E — Confidence model (distinct from coverage)

**Coverage** (existing C1) = *how many of the 3 multiples are present*. **Valuation-confidence** (new)
= *how trustworthy the posture is*, from three independent axes:

| Axis | High | Medium | Low |
|---|---|---|---|
| **Data availability** | both lens inputs present (e.g. P/E **and** EPS-CAGR span ≥4y; or P/B **and** ROE) | one lens fully fed; CAGR span 2–4y | single metric; CAGR span < 2y; provider-ratio fallback |
| **Metric applicability** | sector's preferred lens is the one used | a secondary lens used | lens partially valid (e.g. Infra/Power, Financial-Services bucket) |
| **Consistency of evidence** | growth & quality agree; Rev-CAGR corroborates EPS-CAGR; FCF confirms | minor divergence | growth & quality **conflict**, or EPS-CAGR ≫ Rev-CAGR, or FCF contradicts |

**Resolution:** `confidence = min(axis ratings)` (the weakest axis governs). If consistency is **Low**
(lenses materially conflict), the engine **must not** emit a single directional posture — it returns
`REASONABLE`/`INSUFFICIENT_EVIDENCE` with a "mixed signals" note. Confidence is reported separately
from, and never inflated by, coverage.

---

## PART F — Failure modes (engine must refuse → `INSUFFICIENT_EVIDENCE`)

| Condition | Why refuse |
|---|---|
| **Negative / zero earnings** | P/E and PEG meaningless (already None in C1); no growth lens |
| **Negative equity** | P/B and ROE meaningless → financials branch & quality lens both invalid |
| **Missing / negative growth history** | no PEG; if quality also absent → no basis |
| **Newly listed / CAGR span < ~1–2y** | growth lens unreliable; cap or refuse |
| **Contradictory signals** | growth says supported, quality says demanding, FCF negative → no single honest posture |
| **Sector's required metric missing** | financials with no P/B *or* no ROE; non-fin with no multiple at all |
| **Implausible inputs** | PEG from < 1% growth; P/E > ~200; multiple absurd → distortion, not signal |
| **Cyclical trough suspicion** | metals/chemicals with high P/E + low ROCE → earnings likely depressed → refuse P/E posture, note distortion |
| **Insurance (always)** | embedded value not available |

Refusal is a **first-class, expected output**, consistent with the platform's "None, never fabricate"
rule extended to *judgments*. A refusal always carries a short reason.

---

## PART G — Implementation readiness

### 1. Exact inputs required
`pe`, `pb`, `ev_ebitda` (from `ValuationContext`); `roe`, `roce`, `eps_cagr`, `revenue_cagr`, `fcf`
(from `analytics.compute_all`); `SectorProfile` (D1). Plus the **CAGR span** already carried in
`AnalyticResult.detail` (`span_years`, `points`) for the confidence model.

### 2. Existing inputs already available
**All of the above already exist** — C1 surfaced the multiples, D1 added ROCE/FCF + the sector profile,
and the CAGR analytics already attach span/points detail. **No new data, no new provider, no network.**

### 3. New fields required
- A new **`ValuationAssessment`** dataclass: `posture` (one of the Part-B constants), `phrase`,
  `justification`, `confidence` (high/med/low/none), `caveats: List[str]`, `inputs_used: List[str]`,
  `sector_branch`.
- A new pure module (suggested `analysis/fundamentals/valuation_decision.py`) — `assess_valuation(
  valuation_context, analytics, sector_profile)` → `ValuationAssessment`. Pure, deterministic.
- **No change** to data schema or providers. (`forwardPE` mapping is *optional, future* — not required
  for E1; trailing inputs suffice for a relationship-based posture.)

### 4. Recommended implementation order
1. **`ValuationAssessment` dataclass + posture constants** (the fixed vocabulary, Part B).
2. **Failure-mode guards first** (Part F) — refuse before reasoning; this is the safety spine.
3. **Financials branch** (P/B×ROE matrix, Part D) — smallest, highest-relevance, data-trivial.
4. **Non-financial growth+quality engine** (PEG×Quality matrix, Part C).
5. **Valuation-confidence model** (Part E) — `min` of the three axes.
6. **Insurance / Infra-Power special handling** (context-only / capped confidence).
7. **Integration**: surface as a **descriptive** "Valuation Assessment" section on Analyze Stock and a
   single optional **thesis note** (context, **not** a bull/bear that moves the verdict — keep
   attractiveness descriptive to avoid double-judging). Add to provenance.
8. **Deterministic tests**: the full sector matrix, each posture's triggers, every failure mode,
   confidence resolution, and financials P/B-ROE cells. Target ≥ 25 tests; maintain the suite green.

### Guarantees this design preserves
- **Regime-neutral** (growth/quality, never own-history) → survives PSU/capgoods/PLI re-ratings.
- **Sector-correct** (reuses D1) → no P/E verdict on banks, no posture on insurers.
- **Never fabricates a judgment** → refusal is a designed output.
- **No forbidden language** → only "appears supported/reasonable/demanding" + "insufficient evidence."

*Specification only — no code implemented.*
