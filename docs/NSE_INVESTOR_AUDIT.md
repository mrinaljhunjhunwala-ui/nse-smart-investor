# NSE Investor Audit — Highest-ROI Next Enhancement

Focused audit of the current analytics architecture against the **NSE-listed Indian equity**
universe, to choose the next enhancement before C2. **Audit only — no code.**

References are to the code as it stands after Phase C1: `analysis/thesis/thesis_rules.py`,
`analysis/fundamentals/analytics.py`, `analysis/fundamentals/valuation.py`, `analysis/liquidity.py`.

---

## PART A — NSE universe validation

**Headline:** the engine is calibrated for **non-financial, liquid, large/mid-caps**. It
**systematically misfires on financials** (the single largest slice of the NSE — financials are
~33–37% of the Nifty 50 by weight) and **degrades on small/micro-caps** (Yahoo coverage). Two root
causes: (1) generic-equity thesis rules with no sector awareness; (2) Yahoo's shallow/spotty data for
the long tail.

| Category | Thesis rules meaningful? | Valuation meaningful? | Liquidity tier meaningful? | Systematic failure (concrete) |
|---|---|---|---|---|
| **Large-cap (non-fin)** | ✅ Yes | ✅ Yes | ✅ (always *High*) | Best case — nothing systematic |
| **Mid-cap** | ✅ Mostly | ✅ Mostly | ✅ Good gradation | Coverage slightly thinner |
| **Small-cap** | ⚠️ Partial | ⚠️ Often N/A | ✅✅ Most valuable here | `revenue_cagr`/`eps_cagr` go N/A on negative/volatile base (`_growth_cagr` rejects non-positive start); Yahoo multiples often None → valuation degrades to N/A; thesis leans technical-only |
| **Micro / low-liquidity** | ❌ Weak (no fundamentals) | ❌ N/A | ✅✅✅ The key guard | Correctly flags *Illiquid* — the one place the architecture is strongest |
| **Banks** | ❌ **Misfires** | ⚠️ P/B ✅, P/E ✅, **EV/EBITDA ✗** | ✅ | `DE_ELEVATED=1.0`/`DE_HIGH=1.5` flag **every** bank "High leverage — sensitive to rates" (HDFC Bank, SBI, ICICI all run D/E ≫ 1.5 *by design* — deposits are not "debt"). EV/EBITDA meaningless (interest is operating). Missing NIM / GNPA-NNPA / CASA / provisioning |
| **NBFCs** | ❌ **Misfires** | ⚠️ P/B + P/E ✅, EV/EBITDA ✗ | ✅ | Same D/E false-positive (leverage *is* the model — Bajaj Fin, Chola). Missing GNPA / ALM / capital adequacy |
| **Insurance** | ❌ **Misfires** | ❌ P/E + EV/EBITDA both wrong | ✅ | Valued on **embedded value / VNB margin (P/EV)**, not P/E (SBI Life, HDFC Life). Current P/E "context" is actively misleading |
| **IT services** | ✅✅ Clean | ✅✅ All three valid | ✅ | None — asset-light; ROCE/FCF would *shine* (TCS, Infosys) |
| **Capital goods** | ✅ but incomplete | ✅✅ EV/EBITDA strong | ✅ | **Capital efficiency invisible** — ROCE is *the* metric (L&T, ABB, Siemens) and isn't surfaced; FCF lumpy with project cycles |
| **Consumer** | ✅ Yes | ✅ (high P/E needs context) | ✅ | Quality (high ROCE, steady FCF) invisible (HUL, Nestlé); high P/E with no baseline → future C2 judgment risk |
| **PSU** | ⚠️ Mixed | ⚠️ Low P/E ≠ cheap | ✅ | PSU banks inherit the bank misfire; "PSU discount" low P/E would be mis-read as cheap by any C2 judgment; FCF negative during capex (NTPC/power) reads as bad |

**Concrete misfire to fix first:** `key_risks()` fires *"Elevated/High leverage — sensitive to rates
and earnings shocks"* whenever `debt_to_equity > 1.0`. For the ~35% of the index that is financials,
this is a **false positive on every single name** — the most material correctness defect in the
platform today.

---

## PART B — ROCE / FCF analysis

| Sector | ROCE incremental value | FCF incremental value | Improves thesis? | Improves scoring? |
|---|---|---|---|---|
| **Manufacturing** | **High** — capital efficiency is the core question | **High** — cash conversion vs reported profit | Yes | Yes |
| **Capital goods** | **Very High** — *the* metric (order-book → returns on capital) | Medium — useful but **lumpy** (WC swings); needs multi-year view | Yes | Yes (ROCE), partial (FCF) |
| **Chemicals** | **High** — capex cycles, return on incremental capacity | **High** — capex-heavy, cyclical cash | Yes | Yes |
| **Infrastructure** | Medium — meaningful but often structurally low/levered | ⚠️ **Caution** — negative FCF during build-out is normal, not "bad" | Partial | Partial (needs caveat) |
| **Power** | Medium — regulated RoCE caps make it informative | ⚠️ **Caution** — negative FCF during capex (NTPC) misleads | Partial | Partial (needs caveat) |
| **PSU** | Medium–High for operating PSUs | ⚠️ Caveat for capex-heavy PSUs | Partial | Partial |
| **Financials** | ❌ **Not applicable** — no "capital employed" concept | ❌ **Not applicable** — FCF undefined for lenders | **No — must be suppressed** | No |

**Verdict:** ROCE is broadly decisive for the **real economy** (manufacturing, capital goods,
chemicals, consumer, IT) — exactly where Indian quality investors anchor ("high ROCE compounder").
FCF adds cash-quality signal but **must carry a capex-heavy caveat** (infra/power/some PSU) and
**both must be suppressed for financials**.

**Data availability — the decisive finding:**
- **FCF is already populated.** `CashFlow.free_cash_flow` exists and is derived (`OCF − capex`) when
  absent. It is in the schema today, simply **not surfaced** as an analytic or thesis factor.
- **ROCE is derivable from existing statements.** `RatioSnapshot.roce` exists but Yahoo leaves it
  `None` (the provider comment literally says *"Yahoo has no ROCE — derived later"*). ROCE =
  `operating_income (EBIT)` ÷ `(total_assets − current_liabilities)` — **all three already in the
  schema** (`IncomeStatement.operating_income`, `BalanceSheet.total_assets`, `current_liabilities`).

**Implementation effort: LOW.** No new data provider.
- **Required files:** `analysis/fundamentals/analytics.py` (add `roce()`, `fcf` analytic, both
  returning `None`/unavailable when inputs missing — same pattern as `roe()`/`debt_to_equity()`);
  `analysis/thesis/thesis_models.py` + `thesis_rules.py` (fields + bull/bear factors, **gated by a
  financial-vs-non-financial flag**); `thesis_engine.build_inputs`; the Analyze-Stock UI; tests.
- **Existing data availability:** ✅ FCF present; ✅ ROCE inputs present. The only genuinely new
  ingredient is the **sector gate** (financial / capex-heavy / other) — and `get_sector` already
  exists to drive it.

---

## PART C — C2 valuation-history analysis

| Dimension | Assessment |
|---|---|
| **Data availability** | ❌ **Constrained.** Bands need a historical P/E (and P/B) series = price history (✅ daily, deep) ÷ historical EPS/BVPS. But Yahoo gives only **~4 annual** statements and ~4–5 quarters → a percentile built on **3–4 years** of EPS is statistically thin. |
| **Reliability** | ❌ **Low at current depth.** 3–4 annual points → a noisy, regime-dependent band. Annual EPS is a step-function misaligned with daily prices (approximation). |
| **Impact on decisions** | High *in principle* — "cheap vs its own history" is what investors want — but the impact comes from the **judgment**, which is exactly what's unsafe with shallow data. |
| **NSE-specific usefulness** | ❌ **Currently dangerous.** Indian multiples **re-rated massively 2020–2024** (small/mid-cap + PSU re-rating). "Below your 3-yr median P/E" would tag a *structurally re-rated* PSU or capex name as "cheap." The recent regime break is the worst case for short-history bands. |

**Assumptions required (most fail today):** ≥5–7 yr of consistent EPS; stable/adjusted share count
(splits, bonus, QIP dilution); no business-model or regime break; reliable TTM reconstruction from
quarterlies; the stock's *own* past as a valid baseline. With Yahoo's ~4-yr depth and NSE's recent
re-rating, several of these do **not** hold.

**Can C2 avoid misleading outputs?** Only in a **heavily defanged** form: a *descriptive* percentile
with an explicit "based on N years" confidence, **suppressed when history < 5 yr**, and with **no
cheap/expensive verdict**. But the verdict is the value — so a safe C2 is also a low-value C2 *until a
deeper fundamentals feed exists*. C2 is the **least safe** next step.

---

## PART D — Indian investor decision test

| Question | Status | Why |
|---|---|---|
| **1. Is this a good business?** | ⚠️ **Partially** | ROE / growth / debt present, but **ROCE (the Indian quality anchor) and FCF (cash quality) are not surfaced**, and the read is *wrong* for financials (D/E false flag). The core "good business?" test is incomplete. |
| **2. Why?** | ⚠️ **Partially** | Thesis A1 gives traceable bull/bear/risk for non-financials (strong), but is **misleading for banks/NBFCs/insurers** and omits capital-efficiency reasoning. |
| **3. Does it fit my portfolio?** | ✅ **Fully** | Phase B: sector/beta/correlation/concentration + liquidity-aware sizing. Genuinely answered. |
| **4. Is it liquid enough?** | ✅ **Fully** | Phase C1: turnover-based tiers + volume trend. Answered, and strongest for small-caps. |
| **5. Is valuation currently attractive?** | ❌ **Not answered** | C1 shows P/E/P/B/EV-EBITDA **factually with no baseline by design** — there is *no* attractiveness verdict. (Multiples are shown; the *judgment* is absent.) |

**The two real gaps are Q1 ("good business") and Q5 ("attractive valuation").** Q1 is fixable now,
safely, with data we already hold (ROCE/FCF). Q5 (C2) is fixable only with data we don't have at
sufficient depth — and is unsafe in the current NSE regime.

---

## PART E — Priority decision

### ✅ OPTION A — Implement ROCE + FCF next (bundled with a sector-aware financials guard)

**Evidence:**
1. **Data already exists** → low effort. FCF is populated (`CashFlow.free_cash_flow`); ROCE is
   derivable from `operating_income`, `total_assets`, `current_liabilities` already in the schema.
   *No new provider.*
2. **Broadest NSE relevance** → ROCE/FCF are decisive across manufacturing, capital goods, chemicals,
   consumer and IT — the bulk of the *investable real economy*.
3. **Safe** → factual metrics, no cheap/expensive judgment, no regime assumptions (unlike C2).
4. **It carries the most material correctness fix** → applying ROCE/FCF *requires* a
   financial-vs-non-financial gate, which is the **same** gate that suppresses the D/E false-positive
   on every bank/NBFC. One change repairs Part A's worst defect **and** upgrades Q1 from Partial →
   Full.

**Why not B (C2):** data-constrained (Yahoo ~4 yr) and judgment-unsafe given NSE's 2020–2024
re-rating — it would risk *misleading* "cheap" labels on re-rated PSU/mid-caps (Part C).

**Why not C (data-quality first):** the most damaging "data-quality" defect (financials misfire) is a
**rules-calibration** problem, not a feed problem — it is *included* in Option A's sector gate.
Genuine coverage depth (small-cap fundamentals, longer EPS history) needs a **paid bulk feed
(EODHD)** — a large, separable effort better sequenced *after* the cheap, high-value wins, and it is
the enabler that makes C2 safe later.

---

## PART F — Roadmap (ranked: investor value · NSE relevance · data quality · maintainability)

### 1. Immediate — Sector-aware fundamentals + ROCE + FCF (call it Phase D1)
A `get_sector`-driven gate classifies **financial / capex-heavy / standard**, then:
- **Suppress** the D/E-leverage risk flag, EV/EBITDA, and ROCE/FCF for **financials**; emphasise
  **P/B + ROE** there (the correct lens).
- **Surface ROCE** (derived) and **FCF** (already present) as analytics + thesis factors for the real
  economy; show **FCF with a capex-heavy caveat** for infra/power/PSU.
- *Value:* fixes the largest correctness defect (financials) **and** answers "good business?".
  *NSE relevance:* highest. *Data quality:* uses data we already hold. *Maintainability:* one sector
  gate, reused everywhere. **Low effort, highest ROI.**

### 2. Next — Financials metric pack (P/B–ROE lens; NIM/GNPA where available)
Financials are the **largest index weight**, so making them *first-class* (P/B-vs-ROE framing; surface
NIM / GNPA-NNPA / CASA where the provider supplies them) is the biggest remaining value pool. Higher
effort and **partly data-gated** (NIM/GNPA likely need a new feed) → sequenced second, with a
coverage spike to decide build-vs-defer.

### 3. Third — C2 historical valuation bands, *descriptive-only and depth-gated*
Implement **only after** a deeper fundamentals feed (EODHD, ≥7–10 yr EPS) lands. Until then it stays a
descriptive percentile with explicit confidence and **no cheap/expensive verdict**, suppressed below
5 yr of history. The EODHD evaluation is the shared prerequisite that *also* unlocks #2's depth — so
the bulk-feed decision is the hinge for both.

**Net recommendation:** do **ROCE + FCF with the sector gate now** — it is the only next step that is
simultaneously high-value, broadly NSE-relevant, safe, low-effort (data already exists), and a fix for
the platform's worst current defect. Defer C2 until the data depth makes its judgment trustworthy.

*Audit only — no code implemented.*
