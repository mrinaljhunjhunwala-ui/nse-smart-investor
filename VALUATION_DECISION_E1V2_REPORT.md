# Phase E1-v2 — Valuation Decision Layer — Implementation Report

Implements `VALUATION_DECISION_E1_V2_SPEC.md` exactly, following the §11 build order:
**guards before matrices**, descriptive-only, with every stress-test guardrail (G1–G10).
**No code redesign; spec implemented as written.**

**Result: ✅ done.** New pure engine + descriptive UI section + **49 new tests → 245 passing**.

## 1. Files modified / added
| File | Change |
|---|---|
| `analysis/fundamentals/valuation_decision.py` | **NEW** — `ValuationInputs`, `ValuationAssessment`, `assess()` (the ordered pipeline), `assess_valuation()` integration seam, `CYCLICAL_GROUPS`, posture constants + `PHRASES` |
| `dashboard/pages/04_analyze_stock.py` | **NEW** "🧮 Valuation Assessment" sub-section (descriptive; posture + basis + reasons + caveats + confidence factors). **Not** a verdict-moving thesis factor |
| `tests/test_valuation_decision.py` | **NEW** — 49 deterministic tests |

No schema, provider, or other module changed — inputs reuse `ValuationContext` (C1), `analytics.compute_all` (D1), `SectorProfile` (D1), and existing `net_income`/`operating_cash_flow`.

## 2. Pipeline (guards first, per §1)
`sector route → HARD guards (H1–H6) → base-effect (G7) → cyclical PEAK (G1) → cyclical TROUGH →
build lenses → financial P/B×ROE (G6) | non-financial PEG×ROCE gated (G2,G5,G3) → cash-conversion
veto (G4) → confidence (G8/G9/G10) → emit`. A stock cannot reach a matrix if a guard refused it.

## 3. Explainability (all three preserved)
- **Every posture** carries `reasons[]` (the firing rules) + `justification` (the numbers).
- **Every refusal** carries `triggered_guard` (e.g. `G1-cyclical-peak`) + reason.
- **Confidence** carries `confidence_factors[]` (the contributing axes/caps).

## 4. Descriptive philosophy (enforced + tested)
The output vocabulary is fixed to 9 postures (`SUPPORTED_*`, `REASONABLE`, `DEMANDING_*`,
`INSUFFICIENT_EVIDENCE`). A dedicated test (`test_no_forbidden_vocabulary_anywhere`) asserts that
**none** of Buy/Sell/Fair value/Intrinsic/Cheap/Expensive/Under-/Over-valued/Target ever appears in
any phrase, justification, reason or caveat across representative cases.

## 5. Test counts — 49 new (target ≥ 30)
| Group | Tests |
|---|---|
| Non-financial matrix — every cell (incl. quality-unknown) | 10 |
| Financial matrix — every cell + G6 elevated-ROE + caps | 9 |
| Guards / refusals (H1,H2,H3×2,H4,H5,H6,G1,trough×2,G7×2) | 12 |
| G3 PEG band / no-growth path | 2 |
| G4 cash-conversion veto (FCF, OCF/NI, capex-exempt) | 3 |
| G5 capex softening | 1 |
| Four headline failures | 4 |
| Confidence / explainability / vocabulary / determinism | 8 |
| **Total new** | **49** |
| **Full suite** | **245 passed** (196 prior, untouched) |

## 6. Example outputs
| Case | Posture | Confidence | Note |
|---|---|---|---|
| Clean compounder (P/E 18, EPS-CAGR 20%, ROCE 25%) | **Supported by growth and quality** | high | — |
| TCS (P/E 28, EPS-CAGR 12%, ROCE 45%) | **Demanding vs growth** | high | "premium partly supported by high returns on capital" |
| Bank (P/B 2.8, ROE 17%, avg) | **Supported by ROE** | high | — |
| Mid-PEG, moderate quality | **Reasonable** | medium/high | — |
| Insurer | **Insufficient evidence** | none | guard `H4-insurance` |

## 7. Before / after — the four headline failures
| Failure | E1 (pre-v2) would say | E1-v2 actual output | Guard |
|---|---|---|---|
| **Cyclical peak** (steel: P/E 8, ROCE 24%, EPS-CAGR 45%, Rev 10%) | "Supported by growth **and** quality" | **Insufficient evidence** — *"possible cyclical peak…"* | **G1** |
| **Low-quality hyper-growth** (P/E 50, EPS-CAGR 55%, ROCE 9%) | "Supported by growth" | **Reasonable** — quality gate blocks support | **G2** |
| **Accrual growth** (P/E 22, EPS-CAGR 25%, ROCE 14%, FCF −, non-capex) | "Supported by growth" | **Reasonable** — *"earnings not converting to cash"* | **G4** |
| **Low-growth PEG** (P/E 45, EPS-CAGR 2%, ROCE 35%) | "Demanding vs growth" (PEG=22 noise) | **Reasonable** — PEG disabled <5%, quality-context | **G3** |

Each was verified by a dedicated test (`test_headline_*`) and reproduced live.

## 8. Scope honoured
Implemented the spec as written — **no framework redesign**. Did **not** add: historical bands,
cheap/expensive labels, peer comparison, new providers, DCF. The layer is **descriptive** and is
surfaced as its own section; it does **not** move the thesis verdict (per §11). PSU confidence cap
(G10) is wired as an `is_psu` hook (default off — no PSU flag exists in current data; documented).

## Net effect
An NSE investor can now read a **regime-neutral, sector-correct, guard-protected** answer to "is
valuation attractive?" — phrased only as a relationship to growth and quality, refusing on cyclical
peaks/troughs, turnarounds, accrual growth and insurers, with every posture, refusal and confidence
level fully explained.
