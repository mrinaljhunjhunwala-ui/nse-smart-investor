# Phase E1-v2 — Valuation Decision Layer — Final Implementation Specification

Supersedes `VALUATION_DECISION_E1_SPEC.md`, hardened with every mandatory guardrail from
`VALUATION_E1_STRESS_TEST.md` (G1–G4 mandatory; G5–G10 incorporated). **Design only — no code, no
architecture redesign.** This is the version to implement.

## Core principle (amended)
> A multiple is interpreted **only** by relating it to **growth** (PEG) and **quality** (ROE/ROCE), and
> only after a stack of guards confirms the inputs are *trustworthy*. **On any ambiguity, the default
> bias is toward "Reasonable" or "Insufficient evidence" — never "Supported."** Caution is cheap; a
> false "supported" on a cyclical peak or an accrual-driven grower is not.

Reuses existing inputs only: `ValuationContext` (pe/pb/ev_ebitda), `analytics.compute_all`
(roe/roce/eps_cagr/revenue_cagr/fcf + their `detail.span_years`/`start_value`), `SectorProfile` (D1),
plus `IncomeStatement.net_income` and `CashFlow.operating_cash_flow` for cash conversion. **No new
data, no provider, no network.**

---

## 1. The decision pipeline (ordered — guards run BEFORE reasoning)

```
0. Sector routing (SectorProfile)                     → financial | insurance | non-financial
1. HARD guards            → INSUFFICIENT              (neg/zero earnings, neg equity, missing
                                                       required metric, insurance, <2y history,
                                                       implausible inputs)
2. Base-effect/turnaround guard (G7)                  → growth lens OFF or INSUFFICIENT
3. Cyclical PEAK guard (G1)                           → INSUFFICIENT ("possible cyclical peak")
4. Cyclical TROUGH guard (broadened)                  → INSUFFICIENT ("possible cyclical trough")
5. Build lenses:
     growth lens (PEG) — valid only if 5% ≤ g ≤ 60% (G3) and span ≥2y
     quality lens (ROCE non-fin / ROE fin)
     cash-conversion (OCF/NI, FCF sign) (G4)
     rev-CAGR consistency (G9)
6. Non-financial → growth×quality matrix WITH quality gate (G2) + capex softening (G5)
   Financial    → P/B×ROE matrix WITH elevated-ROE caution (G6)
7. Cash-conversion veto (G4): non-capex + poor conversion → block "Supported", downgrade
8. Confidence model (G8/G9/G10) = min(availability, applicability, consistency)
9. Emit posture + phrase + justification + confidence + caveats + inputs_used
```

The order matters: **a stock can never reach the reasoning matrices if a guard has already refused it.**

---

## 2. Sector routing (unchanged from D1, one additive flag)

`SectorProfile` (D1) routes to the branch. E1-v2 adds a **`CYCLICAL_GROUPS`** set *in the valuation
module* (no D1 change): `{Metals & Mining, Chemicals, Auto, Manufacturing(cement), Energy & Power}`
(commodity/refining/cement/auto/metals). Used only by the peak/trough guards.

| Branch | Sectors | Engine |
|---|---|---|
| **Financial** | Banks, NBFC, Financial Services | P/B × ROE matrix (§5) |
| **Insurance** | Insurance | always INSUFFICIENT (P/EV unavailable) |
| **Non-financial** | Manufacturing, Capital Goods, Consumer, IT, Chemicals, Infra/Power, Other | growth × quality matrix (§4) |
| **Cyclical overlay** | any sector in `CYCLICAL_GROUPS` | peak/trough guards active (§3) |

---

## 3. Failure-mode catalogue (Part F, v2) → all return **INSUFFICIENT EVIDENCE** + reason

| ID | Condition | Trigger detail |
|---|---|---|
| H1 | Negative / zero earnings | P/E None (C1) → no growth lens; non-fin → refuse |
| H2 | Negative equity | P/B & ROE invalid → refuse |
| H3 | Missing required metric | non-fin: no multiple at all; fin: no P/B **or** no ROE |
| H4 | Insurance | embedded value unavailable |
| H5 | Newly listed / history < 2y | < 2 yrs or < 2 CAGR points |
| H6 | Implausible inputs | P/E > 200; PEG from g < 5%; multiple absurd |
| **G7** | **Base-effect / turnaround** | start-of-period EPS ≈ 0, or implied growth > 60% cap, or earnings positive < 2–3y stable |
| **G1** | **Cyclical PEAK** | cyclical group **AND** P/E < ~12 **AND** ROCE > ~18% **AND** EPS-CAGR > ~30% **AND** (EPS-CAGR − Rev-CAGR) > ~15pp |
| TR | **Cyclical TROUGH** (broadened) | cyclical group **AND** ( EPS-CAGR < 0 **OR** (P/E > ~35 **AND** ROCE < ~10%) ) |
| CN | Contradictory lenses | growth says Supported, quality says Demanding, **and** cash conversion poor → no honest single posture |

Refusal is a **first-class, expected output**. Partial peak signals (some but not all G1 conditions)
do **not** refuse — they **cap confidence to Medium and add a caveat** (never bless).

---

## 4. Non-financial engine — growth × quality, with the **quality gate (G2)**

**Tiers**
- Quality (ROCE; ROE fallback): **High ≥ 20%** · **Moderate 12–20%** · **Low < 12% (gate floor)**.
- Growth lens (only if **5% ≤ EPS-CAGR ≤ 60%**, G3): **PEG<1.0** · **1.0–2.0** · **>2.0**.

**Matrix (growth lens valid).** The **Low-quality column can never output "Supported"** (G2):

| PEG ↓ \ Quality → | **High (≥20%)** | **Moderate (12–20%)** | **Low (<12%) — gated** |
|---|---|---|---|
| **< 1.0** | Supported by growth **and** quality | Supported by growth | **Reasonable — growth on low returns (unproven)** |
| **1.0–2.0** | Supported by quality | Reasonable | **Demanding vs returns** |
| **> 2.0** | Demanding vs growth *(quality-supported note)* | Demanding vs growth | **Demanding vs returns** |

**Capex-phase softening (G5):** if `SectorProfile.fcf_capex_caveat` is true, the **Low-quality**
"Demanding vs returns" cells are **softened to "Reasonable"** with the caveat *"returns on capital may
be temporarily depressed by an ongoing capex cycle"* + confidence ≤ Medium (don't penalise a building
franchise on not-yet-earning capital).

**Growth lens OFF (EPS-CAGR < 5%, > 60%, or invalid)** → no growth-relative posture is permitted:
| Quality | Posture | Note |
|---|---|---|
| High (≥20%) | **Reasonable** (low confidence) | "High returns on capital but minimal/unmeasurable growth — valuation not assessed against growth." |
| Moderate / Low | **Insufficient evidence** | cannot relate a flat-growth multiple on non-exceptional quality |

This is the **G3 fix for #9**: a no-growth high-ROCE cash-cow is never run through an unstable PEG; it
gets an honest quality-context "Reasonable," never a noisy "Demanding" nor a false "Supported."

---

## 5. Financials branch — P/B × ROE, with **elevated-ROE caution (G6)**

Uses **only** `pb` + `roe` (no NIM/CASA/GNPA/EV). P/E ignored (credit-cycle distortion); EV/EBITDA
already suppressed (D1). **Prefer a 2–3yr average ROE** when ≥2 periods of net income exist; else use
latest ROE and **cap confidence to Medium**.

**Tiers:** ROE **High ≥ 16%** · **Moderate 10–16%** · **Low < 10%**. P/B **Low < 1.5×** · **Mod
1.5–3×** · **High > 3×**.

| ROE ↓ \ P/B → | **Low (<1.5)** | **Moderate (1.5–3)** | **High (>3)** |
|---|---|---|---|
| **High (≥16%)** | Supported by ROE | Supported by ROE | Reasonable (premium matched by ROE) |
| **Moderate (10–16%)** | Reasonable | Reasonable | Demanding vs ROE |
| **Low (<10%)** | Reasonable *(low-ROE caveat)* | Demanding vs ROE | Demanding vs ROE |

**Elevated-ROE caution (G6):** if ROE ≥ ~20% (cyclically high for a lender) **and** P/B is High, the
"Reasonable (premium matched)" cell is **downgraded to "Demanding vs ROE"** with *"ROE may be
cyclically elevated (benign credit cycle); the premium assumes it persists,"* confidence capped Medium.
This is the **#7 fix.**

---

## 6. Output vocabulary (Part B, v2)

### Allowed postures (the only permitted conclusions)
| Posture constant | Exact phrase |
|---|---|
| `SUPPORTED_BY_GROWTH_AND_QUALITY` | "Valuation appears supported by both growth and quality." |
| `SUPPORTED_BY_GROWTH` | "Valuation appears supported by growth." |
| `SUPPORTED_BY_QUALITY` | "Valuation appears supported by quality (high returns on capital)." |
| `SUPPORTED_BY_ROE` *(financials)* | "Valuation appears supported by ROE." |
| `REASONABLE` | "Valuation appears reasonable relative to growth and returns." |
| `DEMANDING_VS_GROWTH` | "Valuation appears demanding relative to growth." |
| `DEMANDING_VS_RETURNS` | "Valuation appears demanding relative to returns on capital." |
| `DEMANDING_VS_ROE` *(financials)* | "Valuation appears demanding relative to ROE." |
| `INSUFFICIENT_EVIDENCE` | "Insufficient evidence to assess valuation." |

A `justification` always quotes the numbers; demanding-with-high-quality appends the quality note.

### Forbidden vocabulary (never, no exceptions)
**Buy · Sell · Target price · Fair value · Intrinsic value · Undervalued · Overvalued · Cheap ·
Expensive.** The layer describes a *relationship*, not a *price judgment*.

### Postures that become **IMPOSSIBLE** after the v2 guardrails
| Now impossible | Prevented by |
|---|---|
| "Supported by growth" when **ROCE < 12%** | Quality gate **G2** |
| Any "Supported" posture on a **cyclical peak** | Peak guard **G1** (→ Insufficient) |
| "Supported by growth" with **poor cash conversion** (non-capex) | Cash-conversion veto **G4** |
| Any **growth-relative** posture when **EPS-CAGR < 5%** | PEG band **G3** (→ Reasonable/Insufficient) |
| "Supported by growth" from a **turnaround base effect** | **G7** (growth lens off / refuse) |
| Financials "premium matched by ROE" on **elevated ROE + high P/B** | **G6** (→ Demanding vs ROE) |
| Any **High-confidence** posture on **< 3y growth history / PSU / elevated-ROE / Rev-divergence** | **G8/G9/G10** (capped) |
| Any posture on **insurance / neg earnings / neg equity / < 2y history** | Hard guards |

### When the engine must downgrade
- **→ REASONABLE:** moderate quality with in-line PEG; high-quality but no/low growth (growth lens
  off); capex-phase low-ROCE (G5); a single mild caveat; one lens only with no red flag.
- **→ INSUFFICIENT EVIDENCE:** any hard guard (H1–H6); cyclical peak (G1) or trough (TR); base-effect
  (G7); contradictory lenses (CN); missing the branch's required metric; insurance.

---

## 7. Quality / growth / cash roles (Part C, v2)

| Metric | Role | Rule |
|---|---|---|
| **EPS CAGR** | Growth denominator (PEG) | valid **only** 5–60%, span ≥2y; <5% → lens off; >60% → base-effect (off) |
| **ROCE** | Quality **gate** (non-fin) | < 12% **blocks all "Supported" postures** (G2); ≥20% rescues a demanding PEG to a softening note |
| **ROE** | Quality gauge (financials) | drives §5; averaged where possible; ≥20%+high P/B → caution (G6) |
| **Revenue CAGR** | Consistency check (G9) | EPS-CAGR − Rev-CAGR > ~15pp → margin-driven → cap confidence + **feed peak guard** |
| **FCF / OCF-to-NI** | Confidence modifier **and posture veto** (G4) | non-capex + (FCF persistently < 0 **or** OCF/NI < ~0.6) → **block "Supported", downgrade to Reasonable** + caveat; capex sectors → FCF ignored for posture |

**Asymmetry rules (from the four design questions):**
- **Quality is an asymmetric gate**, not co-equal: a *floor* for any "Supported" posture, a *mitigant*
  for a "Demanding" one — it never manufactures support nor cancels an extreme premium.
- **PEG outweighs quality only in the demanding direction** (extreme PEG → "Demanding vs growth" even
  on high ROCE); never in the supportive direction.
- **FCF is a modifier by default, a veto on poor conversion in non-capex names.**
- **Revenue growth stays a consistency check**, elevated into peak detection.

---

## 8. Confidence model (Part E, v2) — distinct from coverage

`confidence = min(data_availability, metric_applicability, consistency)` — the weakest axis governs.

| Axis | High | Medium | Low |
|---|---|---|---|
| **Data availability** | both lens inputs present; **EPS-CAGR span ≥ 3y / ≥ 3 pts** (G8) | one lens fed; span 2–3y | single metric; span < 2y; provider-ratio fallback |
| **Metric applicability** | sector's preferred lens used | secondary lens | partial (Infra/Power, Financial-Services bucket) |
| **Consistency** | growth & quality agree; Rev-CAGR corroborates; FCF confirms | minor divergence | lenses conflict; EPS-CAGR ≫ Rev-CAGR; FCF contradicts |

**Hard caps:** PSU → Medium (G10); elevated-ROE financial → Medium (G6); capex-softened cell → Medium
(G5); partial-peak signal → Medium + caveat; any single-lens posture → Medium. **A directional
"Supported"/"Demanding" posture requires consistency ≥ Medium** — if consistency is Low, downgrade to
Reasonable or Insufficient (never a confident direction on conflicting evidence).

---

## 9. Updated worked examples

| Case | Inputs | E1-v2 posture | Confidence | Why |
|---|---|---|---|---|
| **IT compounder** (TCS-type) | P/E 28, EPS-CAGR 12%, ROCE 45%, FCF + | Demanding vs growth *(quality-supported note)* | High | PEG 2.3 rich, but ROCE 45% softens; FCF confirms |
| **Cyclical peak** (steel) | P/E 8, ROCE 24%, EPS-CAGR 45%, Rev-CAGR 10% | **Insufficient — possible cyclical peak** | None | G1 fires (cyclical + low P/E + high ROCE + high EPS-CAGR + EPS≫Rev) |
| **Low-quality hyper-growth** | P/E 50, EPS-CAGR 55%, ROCE 9% | **Reasonable — growth on low returns (unproven)** | Low | G2 gate blocks "Supported"; quality Low |
| **Accrual grower** (EPC) | P/E 22, EPS-CAGR 25%, ROCE 14%, FCF persistently −, non-capex | **Reasonable** + "earnings not converting to cash" | Low | G4 veto blocks "Supported by growth" |
| **No-growth cash-cow** | P/E 45, EPS-CAGR 2%, ROCE 35% | **Reasonable** (growth not assessed) | Low | G3 disables PEG (<5%); quality-context only |
| **Capex-phase capgood** | P/E 35, EPS-CAGR 30%, ROCE 10%, FCF − | **Reasonable** + capex caveat | Medium | G5 softens "Demanding vs returns"; FCF ignored |
| **Elevated-ROE NBFC** | ROE 22%, P/B 3.2 | **Demanding vs ROE** + "ROE may be cyclically elevated" | Medium | G6 downgrades "premium matched" |
| **Quality grower** (capgood) | P/E 50, EPS-CAGR 35%, ROCE 18%, Rev-CAGR 30% | Reasonable | Medium | PEG 1.4, Moderate quality, consistent |
| **Insurer** | any | **Insufficient — valued on embedded value (P/EV), unavailable** | None | H4 |

---

## 10. Why E1-v2 is safer than E1

| Failure | E1 (original) output | E1-v2 output | Guard |
|---|---|---|---|
| **Cyclical peak** (steel: P/E 8, ROCE 24%, EPS-CAGR 45%) | **"Supported by growth AND quality"** — its strongest endorsement, at the top of the cycle | **"Insufficient — possible cyclical peak"** | **G1** — refuses before the matrix; broadened cyclical set + EPS≫Rev margin check |
| **Accrual growth** (EPS up, FCF −, non-capex) | **"Reasonable/Supported"** (FCF only dimmed confidence) | **"Reasonable"** + cash-conversion caveat; "Supported" blocked | **G4** — FCF promoted from modifier to posture veto |
| **Low-quality growth** (PEG 0.9, ROCE 9%) | **"Supported by growth (caveat)"** — supportive headline | **"Reasonable — growth on low returns (unproven)"** | **G2** — quality gate; Low-ROCE column can't say "Supported" |
| **Low-growth PEG** (P/E 45, EPS-CAGR 2%, ROCE 35%) | **"Demanding vs growth"** from PEG = 22 (noisy, unstable denominator) | **"Reasonable"** (PEG disabled <5%; quality-context, growth not assessed) | **G3** — PEG validity band |

In every one of the stress test's four worst cases, **E1's most confident output landed on its most
dangerous scenario.** E1-v2 converts each into a refusal or a downgraded, caveated, low-confidence
read. The framework now fails *safe*: its default on ambiguity is **Reasonable / Insufficient**, and a
"Supported" posture is reachable only through the quality gate, a stable growth base, clean cash
conversion, and (for cyclicals) a passed peak/trough check.

---

## 11. Implementation readiness (unchanged inputs, hardened logic)
- **Inputs:** all already exist (C1 multiples, D1 ROCE/FCF/sector profile, CAGR span detail) + `net_income` and `operating_cash_flow` (already in schema) for the OCF/NI conversion check. **No new data/provider.**
- **New artefacts:** `ValuationAssessment` dataclass (posture constant, phrase, justification,
  confidence, caveats[], inputs_used[], sector_branch); a pure `assess_valuation(valuation_context,
  analytics, sector_profile, statements)` module; a `CYCLICAL_GROUPS` constant.
- **Build order:** (1) posture constants + dataclass → (2) **hard + G1/G7/trough guards first** →
  (3) financials P/B×ROE + G6 → (4) non-fin growth×quality matrix + G2 gate + G5 softening + G3 band →
  (5) G4 cash-conversion veto → (6) confidence model + G8/G9/G10 caps → (7) descriptive integration
  (a context note on Analyze Stock + provenance; **not** a verdict-moving thesis factor) →
  (8) ≥ 30 deterministic tests covering every matrix cell, each guard, and the §10 four failures.

*Final specification — no code implemented.*
