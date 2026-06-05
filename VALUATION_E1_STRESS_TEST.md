# Phase E1 — Valuation Framework Stress Test

Red-team of the E1 spec (`VALUATION_DECISION_E1_SPEC.md`) **before** implementation. Where could the
growth- + quality-adjusted framework still mislead an NSE investor? **Analysis only — no code.**

Framework under test: non-financials → PEG (P/E ÷ EPS-CAGR) × ROCE 3×3 matrix; financials → P/B × ROE
matrix; FCF = confidence modifier; Rev-CAGR = consistency check; one **trough-only** guard (metals/
chemicals, high P/E + low ROCE).

**Top-line finding:** the framework is sound in its *intent* (regime-neutral) but has **three
structural blind spots**: (1) it guards the cyclical *trough* but **not the cyclical peak**; (2) PEG
can manufacture a "supported by growth" posture from **low-quality or accrual-driven** growth; (3) the
**denominator is unstable** at very low growth. Quality must become a *gate*, not a co-equal axis, and
FCF must be allowed to *veto*, not just dim confidence.

---

## Scenario-by-scenario

| # | Example company type | Current E1 interpretation | Failure mode | Recommended guardrail | Refuse? |
|---|---|---|---|---|---|
| **1** | High-growth, low-quality (cash-burn retailer / roll-up: EPS CAGR 55%, ROCE 9%, P/E 50) | PEG ≈ 0.9 → cell (PEG<1.0 × Low) = **"Supported by growth (caveat: modest returns)"** | Endorses growth that **isn't earning its capital** — often unsustainable/value-destructive. The caveat is buried under a supportive headline | **Quality floor (gate):** no "supported" posture when ROCE < ~12%. Low-quality high-growth caps at "Reasonable — growth on low returns (unproven)" | Cap, not refuse |
| **2** | **Cyclical peak** (metals/auto/cement at peak margins: P/E 8, ROCE 24%, EPS CAGR 45%) | PEG ≈ 0.18 × High ROCE → **"Supported by growth AND quality"** (the strongest endorsement) | **Most dangerous.** Peak earnings + peak ROCE + low optical P/E = classic value trap; earnings about to mean-revert down. Framework gives its top rating right at the top | **Add a cyclical-PEAK guard** (mirror the trough guard): cyclical sector + low P/E + **high** ROCE + very high EPS-CAGR + EPS-CAGR ≫ Rev-CAGR → refuse/caveat "earnings may be at a cyclical peak" | **Yes** |
| **3** | Cyclical trough (metals at bottom: P/E 40, ROCE 6%, EPS CAGR < 0) | Negative growth → PEG off; trough guard → **Insufficient (possible trough)** | Mostly handled — **but guard sector list is too narrow** (only metals/chemicals named) | Broaden cyclical set (metals, chemicals, auto, cement, energy/commodity, sugar, paper); rely on neg-growth + low-ROCE + high-P/E combo regardless of label | Yes (already) |
| **4** | Capital-intensive growth phase (capgoods/power mid-capex: EPS CAGR 30%, ROCE 10%, FCF −, P/E 35) | PEG ≈ 1.2 × Low ROCE → **"Demanding vs returns"** | **Penalises depressed ROCE** that is low *because* capacity isn't earning yet — understates a building franchise | In `fcf_capex_caveat` sectors, **don't issue "demanding vs returns" on low ROCE alone**; caveat "returns may be temporarily depressed by an ongoing capex cycle" + lower confidence | No — caveat |
| **5** | Turnaround (loss→profit: EPS just positive, CAGR explosive off a tiny base, ROCE rising, P/E huge) | Tiny-base EPS-CAGR (capped 60%) → PEG may look favourable → false **"supported by growth"** | **Base-effect distortion** — % growth off a depressed base is meaningless; ROCE not yet stable | **Base-effect guard:** if earnings recently crossed zero or implied growth exceeds the cap, growth lens off; require ≥2–3y of *stable positive* earnings | **Yes**, usually |
| **6** | PSU rerating candidate (defence/power-financier/railways: moderate ROCE, P/B risen, strong order-book growth) | PEG reasonable × Moderate ROCE → **"Reasonable"** (regime-neutral → handles re-rating well) | Low risk on the *posture*, but PSU ROE/ROCE may carry one-offs / not reflect minority-holder returns (capital-allocation, cross-subsidy) | **PSU caveat:** cap confidence to Medium + "returns may reflect government priorities / one-offs" | No |
| **7** | Financial with **temporarily elevated ROE** (NBFC in benign credit cycle: ROE 22%, P/B 3) | High ROE × High P/B → **"Reasonable (premium matched by ROE)"** | **Financial cyclical-peak trap** — ROE is at a credit-cycle high; on normalised ROE the premium is *demanding*. Framework blesses it | **Elevated-ROE caution:** High ROE + High P/B → cap confidence Medium + "ROE may be cyclically elevated"; prefer **multi-year average ROE** over latest | No — cap |
| **8** | EPS growth, weak cash conversion (EPC/real-estate/aggressive-accounting: EPS CAGR 25%, FCF persistently −, non-capex) | PEG ≈ 1.2 × Moderate → **"Reasonable/Supported"**; FCF only dims confidence | **Accrual-driven growth** survives as a supportive posture because FCF can't change the verdict, only the confidence | **Cash-conversion veto:** persistent negative FCF (or OCF ≪ NI) in a **non-capex** sector **downgrades the posture** (blocks "supported by growth"), not just confidence | No — downgrade |
| **9** | High ROCE, no growth (mature cash-cow: ROCE 35%, EPS CAGR 2%, P/E 45) | PEG = 45/2 = 22 → **"Demanding vs growth (quality note)"** | **Denominator instability** — at ~2% growth PEG swings wildly (45/2 vs 45/0.5); posture driven by a noisy denominator; also over-penalises a durable franchise that can hold a premium without growth | **PEG validity band:** valid only for growth in **[~5%, 60%]**. Below 5% → growth lens **off**, switch to a **quality-led** read ("high-quality, low-growth franchise; appears demanding relative to growth" — stated, not PEG-derived) | No — quality-led |
| **10** | Recently listed (2023–24 IPO/SME: < 2y statements, extreme multiples, thin/again profit) | Spec already lists newly-listed → **Insufficient** | Residual risk: with ~2y data it may emit a posture on a noisy 2-point CAGR | **Min growth history:** ≥3 points / ≥3y for any growth posture (High conf); 2y → Low conf only; < 2y → refuse | **Yes** (< 2–3y) |

**The three that must change the spec:** #2 (no peak guard), #8 (FCF can't veto), #9 (PEG unstable at
low growth). #1 and #5 are close behind (quality gate, base-effect).

---

## The four design questions

### 1. Should ROCE *always* outweigh PEG?
**No — but it should be an asymmetric *gate*, not a co-equal axis.** Quality must be a **necessary
condition for any *supportive* posture** (a floor: no "supported" below ~12% ROCE — fixes #1), and a
**mitigant** for a demanding one (softens, never erases — already in spec). It must **not** dominate in
the other direction: a high-ROCE name at an absurd multiple is still demanding (#9). So quality gates
*support* and tempers *demand* — it never manufactures support and never cancels an extreme premium.

### 2. Should PEG *ever* outweigh ROCE?
**Yes — but only in the *demanding* direction.** An extreme PEG (multiple far ahead of growth) must be
able to produce "demanding vs growth" even on a high-ROCE franchise (the TCS case; #9) — quality only
appends a softening note. PEG must **never** outweigh ROCE in the *supportive* direction: a low PEG
built on low-quality growth (#1) must **not** yield "supported." **Asymmetric: PEG drives caution,
quality gates support.**

### 3. Should FCF remain *only* a confidence modifier?
**No.** Keep it a confidence modifier in **capex-caveat sectors** (negative FCF is structural there —
#4). But in **non-capex sectors**, persistent negative FCF / poor cash conversion (OCF ≪ NI) signals
**low-quality, accrual-driven earnings** and must be able to **cap/downgrade the posture** (a soft veto
on "supported by growth" — #8), not merely lower confidence. FCF = modifier by default, **veto on poor
conversion in non-capex names.**

### 4. Should revenue growth be used as a consistency check?
**Yes — keep it a consistency check, but strengthen its diagnostic role.** EPS-CAGR ≫ Revenue-CAGR
means growth is **margin-driven** (possibly peak-margin or one-off) → (a) reduce growth *durability* →
cap confidence, and (b) **feed the cyclical-peak guard** (#2/#7). It stays a check, not a primary axis,
but it becomes a key input to peak detection rather than a passive footnote.

---

## Returns

### 1. Failure modes (net-new, beyond the spec's existing list)
- **F1 — Cyclical earnings PEAK** falsely rated "supported by growth and quality" (low P/E + high ROCE
  + high recent growth). *Highest severity.*
- **F2 — Low-quality high growth** falsely rated "supported by growth" (PEG ignores that the growth
  doesn't earn its capital).
- **F3 — Accrual-driven growth** (EPS up, cash not) survives as a supportive posture because FCF only
  touches confidence.
- **F4 — PEG denominator instability** at very low (but positive) growth → noisy posture for high-ROCE
  no-growth franchises.
- **F5 — Turnaround base-effect** growth distortion → false "supported."
- **F6 — Capex-phase depressed ROCE** mislabelled "demanding vs returns."
- **F7 — Financials with cyclically elevated ROE** → premium falsely "matched by ROE."

### 2. Required guardrails
- **G1 — Cyclical-PEAK guard** (mirror the trough guard): cyclical sector + low P/E + high ROCE + very
  high EPS-CAGR + EPS-CAGR ≫ Rev-CAGR → **refuse** with "possible cyclical peak." Broaden the cyclical
  sector set.
- **G2 — Quality floor (gate):** no "supported" posture when ROCE < ~12%; low-quality high-growth caps
  at "Reasonable — growth on low returns."
- **G3 — PEG validity band [~5%, 60%]:** below 5% growth, disable PEG and use a **quality-led** read;
  above 60%, treat as base-effect/unreliable.
- **G4 — Cash-conversion veto:** persistent negative FCF / OCF ≪ NI in a **non-capex** sector
  downgrades the posture (blocks "supported"), not just confidence.
- **G5 — Capex-phase ROCE softening:** in `fcf_capex_caveat` sectors, don't issue "demanding vs
  returns" on low ROCE alone; caveat + lower confidence.
- **G6 — Elevated-ROE financial caution:** High ROE + High P/B → cap confidence Medium + "ROE may be
  cyclically elevated"; prefer **multi-year average ROE**.
- **G7 — Base-effect / turnaround guard:** earnings recently crossed zero or growth above cap →
  growth lens off; refuse without ≥2–3y stable positive earnings.
- **G8 — Min growth history:** ≥3 points / ≥3y for a High-confidence growth posture; tighten the
  newly-listed refusal.
- **G9 — Rev-CAGR divergence:** large |EPS-CAGR − Rev-CAGR| caps confidence and feeds G1.
- **G10 — PSU caveat:** cap confidence Medium + capital-allocation/one-off caveat.

### 3. Changes to the E1 specification
1. **Part F (failure modes):** add the **cyclical-PEAK** refusal (G1) and broaden the cyclical sector
   set; add the **base-effect/turnaround** guard (G7).
2. **Part C (quality & growth):**
   - Change PEG validity from "> 0, ≤ 60%" to a **band [~5%, 60%]** (G3); below the floor, growth lens
     off → quality-led posture.
   - Recast **quality as a gate**, not a co-equal axis: revise the matrix so the **Low-ROCE row can
     never output "supported by growth"** (G2). The `PEG<1.0 × Low` cell becomes "Reasonable — growth
     on low returns (unproven)."
   - Add **capex-phase ROCE softening** (G5).
3. **Part C / E (FCF):** promote FCF from pure confidence modifier to a **posture-capping veto** in
   non-capex sectors with poor cash conversion (G4); document OCF/NI as the conversion proxy.
4. **Part D (financials):** add the **elevated-ROE caution** + prefer **averaged ROE** (G6).
5. **Part E (confidence):** strengthen **Rev-CAGR divergence** into both confidence and peak detection
   (G9); raise the High-confidence growth-history threshold to **≥3y / ≥3 points** (G8); add the **PSU
   confidence cap** (G10).
6. **Net rule added to the core principle:** *the framework's default bias on ambiguity is toward
   "reasonable / insufficient," never toward "supported."* Supportive postures require the quality gate
   **and** clean cash conversion **and** a stable growth base — caution is cheap, false support is not.

**Bottom line:** ship E1, but **only with G1 (peak guard), G2 (quality gate), G3 (PEG band), and G4
(FCF veto) folded into the spec first** — without them the framework's most confident outputs land
exactly on its most dangerous cases (cyclical peaks, low-quality growth, accrual growth, no-growth
compounders).

*Stress test only — no code implemented.*
