# Valuation Decision Audit — "Is valuation attractive?"

Design audit for the next investor-decision gap. NSE-focused; the overriding constraint is **avoid
misleading valuation conclusions**. **Design only — no code.**

References the stack as it stands after C1 + D1: `analysis/fundamentals/valuation.py`
(`ValuationContext`), `analysis/fundamentals/analytics.py` (ROE, ROCE, CAGR), and
`analysis/sector_classification.py` (the `SectorProfile`).

---

## PART A — Current state

| Component | State today | Gap for "attractive?" |
|---|---|---|
| **P/E** | ✅ surfaced (trailing) | A bare number; no baseline; **trailing, not forward** |
| **P/B** | ✅ surfaced | Meaningful only against ROE — not yet related to it |
| **EV/EBITDA** | ✅ surfaced; **suppressed for financials** (D1) | No baseline; no growth/quality context |
| **Sector-aware applicability** | ✅ `SectorProfile` decides which multiple is valid + `preferred_valuation` | Knows *which* metric to use, not whether the level is *attractive* |
| **Confidence** | ✅ but it is **coverage** (how many of 3 present), **not reliability** of a judgment | Says nothing about whether an attractiveness call is trustworthy |

**What's still missing to judge attractiveness — there is no *baseline* and no *context*:**
1. **A comparator.** A multiple is only "attractive" *relative to* something — its growth, its quality,
   its peers, or its history. The platform surfaces the number and stops (by design, C1).
2. **Growth context.** 22× at 30% EPS CAGR ≠ 22× at 5%. We *have* `eps_cagr`/`revenue_cagr` but never
   relate them to the multiple.
3. **Quality context.** High ROE/ROCE *earns* a higher multiple. We *have* ROE/ROCE (D1) but never
   relate them to P/B / P/E.
4. **Forward view.** All multiples are **trailing**; attractiveness is forward-looking. `forwardPE`
   exists in the Yahoo `info` we already fetch but is not mapped.
5. **Reliability signal.** Coverage-confidence ≠ "is this attractiveness call safe given the data".

**Conclusion:** the missing piece is a **decision layer** that relates the (already-surfaced)
multiple to the (already-computed) growth and quality — *not* more raw multiples.

---

## PART B — NSE-specific risks (why valuation-*history* fails in India)

Yahoo gives ~4 years of EPS, so "history" ≈ the **2020–2024 window** — an unrepresentative, re-rating
regime. India has run a structural multiple re-rating that breaks own-history baselines:

| Re-rating | What happened | Why history misleads |
|---|---|---|
| **PSU** | Decade-long governance/capital-allocation **discount removed** 2022–24 (capex, dividends) | "P/E 12 vs 5-yr avg 8" reads *expensive* but the discount is structurally gone |
| **Capital goods** | Post-2021 capex upcycle re-rated L&T/ABB/Siemens/BHEL from ~20× to 50–70× | Low-capex-decade history makes them look wildly overvalued |
| **Manufacturing (PLI / China+1)** | New growth regime re-rated manufacturers | No-growth-era history is the wrong baseline |
| **Financials** | NPA cycles crush **E**; QIPs/mergers (HDFC twins) move **book** | P/E spikes when earnings collapse (not price); P/B history distorted by capital events |

**Situations where `current multiple > historical average` does NOT imply overvaluation:**
1. **Structural re-rating** (PSU discount removed, governance fixed, deleveraged turnaround).
2. **Growth acceleration** (earnings inflection — capex upcycle, new TAM).
3. **Cyclical trough earnings** (depressed E inflates P/E — metals/cyclicals look "expensive" at the
   bottom; the mirror error also bites).
4. **Business-mix shift** (higher-margin/higher-quality segments now dominate).
5. **Sector-wide re-rating** (the whole peer set moved — own-history is the wrong frame).

**Implication:** an own-history percentile band — the originally-sketched "C2" — is the **least safe**
baseline for NSE *right now*. It would manufacture false "expensive" signals on exactly the names
where India's biggest gains came from.

---

## PART C — Possible valuation frameworks

| Framework | Data requirements | Reliability | NSE suitability | Risk of misleading |
|---|---|---|---|---|
| **1. Historical percentile bands** | Historical multiple series = price (have) ÷ **TTM EPS history** (Yahoo ~4 yr → thin) | **Low** (regime-contaminated, step-function EPS) | **Poor now** — defeated by Part B re-ratings | **High** — false "expensive" on re-rated PSU/capgoods |
| **2. Sector-relative (peer median/percentile)** | Cross-sectional peer multiples + peer universe (have `SECTOR_MAP`) + **batch fetch** (Yahoo per-ticker, slow, small-cap gaps) | **Medium** — peer-set composition sensitive; coarse buckets (the "Finance" bucket mixes NBFC/insurer/AMC/exchange) | **Medium–High** — regime-neutral (the whole sector re-rates together) | **Medium** — coarse sectors, quality spread within sector |
| **3. Growth-adjusted (PEG-style)** | P/E (have) ÷ EPS CAGR (**have** — `eps_cagr`) | **Medium** — sensitive to the growth input; breaks on ≤0 growth & cyclicals | **Medium–High** — directly addresses India's #1 re-rating cause (growth) | **Medium** — needs guards (no negative growth, cap extremes) |
| **4. Quality-adjusted (ROE/ROCE-aware)** | P/B + ROE (have), P/E + ROCE (**have**, D1) | **Medium–High** — *justified P/B ≈ ROE-driven* is theoretically grounded & regime-neutral | **High** — matches Indian quality investing; reuses D1 ROE/ROCE | **Low–Medium** — main risk is over-simplification |
| **5. Hybrid (growth + quality, sector-gated; peer as secondary)** | All of the above **except** deep history | **Higher** — triangulation cuts single-metric error | **High** | **Lower** — if shown as descriptive context + confidence, not a blunt label |

**Key finding:** the frameworks that are **safest and use data we already have** are **quality-adjusted
(#4)** and **growth-adjusted (#3)** — both regime-neutral and reusing D1's ROE/ROCE/CAGR. **Historical
bands (#1)** — the original C2 plan — is the **weakest and most dangerous** for NSE. Sector-relative
(#2) is a good *secondary* but is data-heavy (batch fetch, coarse buckets).

---

## PART D — Financials roadmap (what's realistically achievable with current providers)

| Capability | Achievable on current providers (Yahoo)? | Notes |
|---|---|---|
| **P/B + ROE framework** | ✅ **Yes, now** | `pb` (Yahoo) + `roe` (analytics) already present; *justified P/B vs ROE* is computable today — **regime-neutral, high value (~35% of the index), low effort** |
| **NIM** (net interest margin) | ❌ No | Not in Yahoo standard fundamentals; needs interest income / earning assets from bank filings → **new feed** |
| **GNPA / NNPA** (asset quality) | ❌ No | RBI / bank disclosures or a specialised feed → **new feed** |
| **CASA** | ❌ No | Bank disclosures → **new feed** |
| **Embedded Value / VNB** (insurers) | ❌ No | Insurer disclosures → **new feed** |

**Conclusion:** of the financials wish-list, **only P/B + ROE is doable on current data** — and it is
naturally a **component of the quality-adjusted valuation layer (Part C #4)**. Everything that makes a
financials pack genuinely differentiated (**NIM/GNPA/CASA/EV**) is **data-gated** → that is a
**provider project, not a feature project**.

---

## PART E — Recommendation

### ✅ OPTION B — Build the Valuation Decision Layer next — **but reframed**

Not historical bands. A **sector-aware, growth- and quality-adjusted attractiveness layer**, built on
data we already hold, presented as **descriptive context with confidence** (e.g. *"Demanding vs growth
& quality"* / *"Fair"* / *"Undemanding"* + caveats) — **never a blunt cheap/expensive label**, and
**suppressed when data is insufficient**.

| Criterion | Why Option B wins |
|---|---|
| **Investor value** | Directly answers the stated gap ("Is valuation attractive?") — the last unanswered question in the Part-D decision test |
| **NSE relevance** | Growth- + quality-adjustment is **regime-neutral** — it *survives* the PSU/capgoods/PLI re-ratings that break history (Part B) |
| **Data quality** | Uses data **already computed** (multiples, ROE, ROCE, EPS/Rev CAGR) — no new provider, no thin 4-yr history |
| **Architecture readiness** | **D1 already delivers the prerequisites**: the `SectorProfile` gates financials → **P/B-vs-ROE**; non-financials → growth/quality-adjusted P/E/EV-EBITDA. The layer slots onto the existing `ValuationContext` |

**Why not Option A (Financials Pack):** its valuable parts (NIM/GNPA/CASA/EV) are **data-gated** with
no current provider; the only now-doable piece (**P/B + ROE**) is *delivered for free* as the
financials branch of Option B's quality-adjusted layer. Building "A" today = building a fraction of B.

**Why not Option C (provider architecture first):** it is the correct **long-term** unlock — deeper
EPS history makes #1 safe *and* a real financials pack possible — but it is a large foundation with
**no immediate investor-facing output**. Sequence it **after** the cheap, safe, high-value decision
layer ships, and scope it as the enabler for *both* historical bands and NIM/GNPA.

### Guardrails the Decision Layer must encode (to avoid misleading conclusions)
1. **Regime-neutral baselines only** (growth, quality, peers) — **no own-history verdict** until a
   deeper feed exists.
2. **Sector-gated** via the D1 `SectorProfile` (financials → P/B-ROE; cyclicals → flag trough-earnings
   distortion on P/E; never PEG a ≤0-growth name).
3. **Descriptive + confidence**, not cheap/expensive; **suppress** when growth/quality inputs are
   missing (the C1 "None, never fabricate" rule extends to judgments).
4. **Always show the justification** ("Demanding 45× **but** 30% EPS CAGR and 28% ROCE") so the user
   sees *why*, consistent with the platform's traceability standard.

### Roadmap
1. **Now — Valuation Decision Layer** (growth- + quality-adjusted, sector-gated, descriptive). Reuses
   D1; ships the P/B-ROE financials lens as a side-effect.
2. **Next — Sector-relative valuation** (peer median/percentile) once a batch-fundamentals path exists
   — a regime-neutral *secondary* baseline.
3. **Later — Provider upgrade (e.g. EODHD)** → unlocks **both** reliable historical bands **and** a
   genuine financials pack (NIM/GNPA/CASA/EV). This is the real "Option C", correctly sequenced last.

*Audit only — no code changes.*
