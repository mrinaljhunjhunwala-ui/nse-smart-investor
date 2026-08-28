# EODHD Provider Decision Audit

**Scope:** decision document only — no code, no provider, no file changes. Synthesised from
`FUNDAMENTALS_DATA_MEMO.md`, `FUNDAMENTALS_COVERAGE_REPORT.md`, `V1_NSE_VALIDATION_REPORT.md`,
`FUNDAMENTALS_ARCHITECTURE.md`, `PRODUCTION_HARDENING_FINAL_REPORT.md` and the E1-v2 valuation specs.
No EODHD API key is available in this environment, so **every EODHD unlock claim is `[PROJECTED]`**
from the documented schema in the memo, cross-referenced with Part A. Personal project, no revenue,
no paid-API budget — but per instructions the decision is argued on **effort / value / risk**, with
cost as a reinforcing factor only.

---

## Part A — Yahoo limitations: what is actually blocked

The established headline (do not re-derive): Yahoo's coverage is ~94–99% per metric with **0% total
failures**; its **sole material weakness is shallow annual history (~4–5y)**. Classifying the
*downstream* consequences:

```
LIMITATION: Shallow annual history (~4–5y)
BLOCKS: credible 5/10-year CAGR — forces a 3-year window universe-wide; caps the CAGR analytic's
        confidence; feeds the "data availability" axis of E1-v2's valuation-confidence model
FAILURE MODE: confidence downgrade  (value still returned, labelled "medium" + a reason)
ROOT FIX: deeper history
SEVERITY: medium
```
```
LIMITATION: No historical multiple time-series (P/E / P/B history)
BLOCKS: C2 historical valuation bands ("cheap vs its own history")
FAILURE MODE: honest refusal  (C2 not built; E1-v2 answers "is valuation attractive?" regime-neutrally)
ROOT FIX: other (methodology) — depth is necessary but NOT sufficient; NSE's 2020–2024 re-rating
          makes own-history bands mislead regardless of depth
SEVERITY: low
```
```
LIMITATION: No bank/NBFC operational metrics (NIM, GNPA/NNPA, CASA)
BLOCKS: a financials metric pack beyond P/B–ROE
FAILURE MODE: honest refusal / not-built  (financials use P/B–ROE; V1 shows this differentiates sensibly)
ROOT FIX: different provider — and NOT EODHD (its generic global schema has no India bank disclosures)
SEVERITY: medium  (financials ~35% of the index, but the current answer is sound, not wrong)
```
```
LIMITATION: No insurer embedded-value data (P/EV, VNB margin)
BLOCKS: insurance valuation analytics
FAILURE MODE: honest refusal  (guard H4 correctly refuses all insurers — confirmed in V1)
ROOT FIX: different provider — but NO evaluated provider supplies Indian-insurer embedded value
          (it lives in actuarial disclosures, not standardized statements)
SEVERITY: low
```
```
LIMITATION: Stale / renamed tickers (~8, 3.7%)
BLOCKS: every analytic for those symbols (0/4)
FAILURE MODE: honest refusal  (H3/H5), but reads like a gap
ROOT FIX: universe hygiene (fix data/universe.py) — provider-independent, zero cost
SEVERITY: low–medium
```
```
LIMITATION: Yahoo endpoint fragility (cookie/crumb auth, throttling at scale)
BLOCKS: operational reliability of the fetch — not any specific analytic
FAILURE MODE: transient honest refusal / empty (now logged after P2) — not a wrong answer
ROOT FIX: different provider OR caching/hardening (the app already has tiered fallback + caching)
SEVERITY: medium
```
```
LIMITATION: Mathematically-undefined CAGR (negative starting base, ~5–6 names)
BLOCKS: CAGR for loss-making-at-window-start stocks
FAILURE MODE: honest refusal  (None + reason — correct; any provider faces it)
ROOT FIX: other (irreducible); deeper history only helps if it provides a positive earlier base
SEVERITY: low
```

**Pattern:** every Yahoo limitation is an **honest refusal or a confidence downgrade — never a wrong
answer.** Exactly one (shallow history) has "deeper history" as its root fix, and even that only
moves a *label*. The rest are methodology (C2), provider-mismatch EODHD can't solve (NIM/GNPA/EV), or
universe hygiene.

---

## Part B — Analytics unlock analysis  *(all EODHD claims `[PROJECTED]`)*

```
CAPABILITY: Higher-confidence CAGR (medium → high)
EODHD UNLOCKS: partially
REASON: [PROJECTED] If EODHD's NSE depth reaches 8–10y, CAGR computes over a longer window → "high"
        confidence. BUT (a) the memo flags NSE depth as the UNVERIFIED risk — non-US "minor"
        exchanges are documented at ~6y, only marginally deeper than Yahoo's 4–5y, so the upgrade may
        not even materialise for NSE without the pilot; (b) the platform already discloses "medium"
        honestly; (c) E1-v2's postures (PEG, P/B–ROE) are regime-neutral and do NOT need deep history
        — only the confidence annotation would change. Net: upgrades a label, does not change a
        decision or unlock a new analytic.
ALTERNATIVE PATH: honest "medium" disclosure (already shipped) — Option A.
```
```
CAPABILITY: Historical valuation bands (C2)
EODHD UNLOCKS: not unlocked
REASON: Depth is necessary but not sufficient. Per VAL_LIQUIDITY_AUDIT and the E1-v2 stress test, the
        binding constraint is NSE's 2020–2024 structural re-rating (PSU/capital-goods/manufacturing):
        own-history bands flag re-rated winners as "expensive" — a wrong signal — regardless of how
        many years are available. 21y of history spans multiple regimes and makes this worse, not
        better. EODHD depth does not make C2 safe.
ALTERNATIVE PATH: E1-v2's regime-neutral growth-/quality-adjusted layer (already shipped) is the
        correct substitute; C2 only becomes safe with regime-segmentation — methodology, not data.
```
```
CAPABILITY: Financials metric pack (NIM, GNPA, CASA)
EODHD UNLOCKS: not unlocked
REASON: [PROJECTED] EODHD provides standardized income/balance/cash-flow + Highlights (EPS, ROE,
        margins). It does NOT model India-specific bank disclosures (net interest margin, gross/net
        NPA, CASA ratio) — those come from RBI filings / specialist India feeds (Screener, Trendlyne,
        Tijori expose some; all disqualified for production in the memo). A generic global vendor
        cannot supply them.
ALTERNATIVE PATH: a specialist India banking feed (or manual review) — out of scope for a personal
        project; P/B–ROE (already shipped) is the realistic ceiling.
```
```
CAPABILITY: Insurance analytics (P/EV, VNB margin)
EODHD UNLOCKS: not unlocked
REASON: [PROJECTED] Embedded value and VNB come from insurers' actuarial disclosures, not financial
        statements. NO provider in the FUNDAMENTALS_DATA_MEMO matrix supplies Indian-insurer EV.
        EODHD has no EV field.
ALTERNATIVE PATH: none automated — the H4 refusal is the correct, honest output and should stay.
```
```
CAPABILITY: Sector-relative valuation (multiples vs sector peers)
EODHD UNLOCKS: not unlocked (not needed)
REASON: The peer multiples (P/E, P/B, EV/EBITDA) are ALREADY available from Yahoo — V1 fetched 62
        stocks' multiples successfully, and SECTOR_MAP + the universe already exist. Sector-relative
        valuation is an ENGINEERING task (a peer-aggregation + caching pass over data we already
        pull), not a data-provider gap. EODHD would only marginally improve peer-multiple consistency.
ALTERNATIVE PATH: build it on the existing Yahoo data — no EODHD required.
```

**Part B verdict:** EODHD **fully unlocks nothing new.** It *partially* upgrades exactly one thing —
the CAGR confidence label — and even that is NSE-depth-unverified. The four genuinely-valuable
deferred capabilities are methodologically blocked (C2), absent from EODHD's schema (NIM/GNPA, EV),
or already achievable on free Yahoo data (sector-relative).

---

## Part C — Effort / value / risk

### Effort (baseline: a new provider = one `FundamentalProvider` subclass)
| Option | Integration | Maintenance | If provider unavailable |
|---|---|---|---|
| **A — Yahoo-only + better disclosure** | **~2–4 h** (confidence copy/UI; labelling already exists) | none | n/a (no new dependency) |
| **B — Yahoo primary + EODHD optional enrichment** | ~8–16 h (1 adapter + service order + the mandatory 217-stock pilot) — **but needs a paid key just to test** | low (1 adapter) | **platform = today** (graceful) |
| **C — EODHD primary + Yahoo fallback** | ~16–24 h (adapter + pilot + re-tier + re-validate) | medium (key always-on, billing) | **degrades to Yahoo** on key lapse (so why pay) |

### Value (delta to the 5 investor questions)
| Question | EODHD delta | Decision or label? |
|---|---|---|
| Good business? | CAGR confidence *label* medium→high (if NSE depth verifies); ROE/ROCE/growth **values unchanged** | label |
| Why? | none (thesis factors don't depend on depth) | — |
| Portfolio fit? | none (beta/correlation/sector) | — |
| Liquidity? | none (price-derived) | — |
| Valuation attractive? | E1-v2 regime-neutral; a confidence tick for some; **postures unchanged**; C2 stays blocked | label |

**The entire value delta is "upgrade confidence labels," not "change decisions."**

### Risk
- **Provider dependency:** B low (graceful), C **high** (key lapse → silent degrade to Yahoo).
- **Data quality:** EODHD's **Indian small-cap depth is unverified** — the memo makes a 2-day pilot
  *mandatory* precisely because this is where every vendor under-delivers. A new provider adds a new
  data-quality surface to validate, and **wrong data is worse than missing data**.
- **Yahoo fragility vs EODHD dependency:** Yahoo's cookie/crumb fragility is **operational and already
  mitigated** (tiered fallback Angel→Stooq→Yahoo, caching, P2 logging) and is **free**. EODHD adds a
  **paid, key-gated** failure mode (billing lapse) on top — for output that doesn't change decisions.
  For a no-revenue project, **Yahoo's known fragility is the lower-risk position.**

---

## Part D — Opportunity cost vs the top-5 next steps

EODHD integration is ~8–24 h (Option B/C) plus a paid pilot, for a label-only value delta.

| Task | Effort (hrs) | Platform impact | ROI vs EODHD |
|---|---|---|---|
| 3. Financials coverage spike (what Yahoo returns for NIM/GNPA/CASA) | 2–3 | **High** — empirically confirms whether *any* feed (incl. EODHD) could supply a financials pack; directly informs this very decision | **Higher** |
| 4. Utilities/commodity cyclical split (V1 finding) | 2–3 | **High** — removes the one observed over-refusal; sharpens valuation accuracy on real names | **Higher** |
| 1. CI page smoke test (17 pages headless AppTest) | 3–4 | **High** — locks in the P3 win; catches page regressions automatically | **Higher** |
| 2. Valuation regression harness (golden snapshot) | 3–4 | **High** — catches valuation drift; leverages the V1 run already done | **Higher** |
| 5. Backtest end-to-end smoke test | 3–4 | Medium–High — reliability of a core feature | **Higher** |
| — EODHD integration (Option B) | 8–16 + pilot + $ | Low (label upgrade only) | baseline |

Every one of the five is **smaller effort, higher platform impact, and adds no paid dependency.**
EODHD is lower ROI than all of them.

---

## Part E — Decision: **NO-GO**

The value EODHD adds does not justify the effort and dependency risk for a personal project. **Yahoo
with better confidence disclosure (Option A) is the correct path.**

- **Single most important finding:** EODHD **fully unlocks nothing new** — its only effect is to move
  the CAGR confidence label from "medium" to "high" (and even that is NSE-depth-unverified), while
  every genuinely-valuable deferred capability (C2, NIM/GNPA, embedded value, sector-relative) is
  *independently* blocked by methodology, schema mismatch, or is already achievable on free Yahoo
  data. The delta is **labels, not decisions.**

- **Strongest counter-argument:** Deep history (8–21y) is the one thing Yahoo *structurally cannot*
  provide; it is foundational, and paying ~$50–60/mo future-proofs the data layer for any later
  history-dependent analytic.

- **Why it does not change the decision:** The single history-dependent analytic that depth would
  enable — C2 historical bands — is **independently unsafe on NSE** because of the 2020–2024 regime
  break (more history makes it worse, not better). E1-v2 was *deliberately designed* to be
  regime-neutral so it would **not** depend on deep history. The platform already handles shallow
  history correctly (honest "medium" disclosure). So the "future-proofing" buys depth for an analytic
  that stays blocked regardless — a payment for optionality the audit shows won't be exercised. (The
  no-budget reality of a no-revenue project is a reinforcing tiebreaker, not the primary reason.)

**Therefore: NO-GO.** Re-open only if a *future* requirement appears that is (a) genuinely
history-dependent **and** (b) regime-safe — neither of which exists today.

*(No Part F — that section applies only to a GO decision.)*

---

## Executive summary

**Decision: NO-GO on EODHD.** The audit shows EODHD fully unlocks no new investor-facing capability:
its sole effect is upgrading the CAGR confidence label from "medium" to "high" — itself unverified
for NSE — while C2 valuation bands stay blocked by NSE's regime break (a methodology problem, not a
depth problem), NIM/GNPA/CASA and insurer embedded value are absent from EODHD's schema entirely, and
sector-relative valuation is already buildable on the free Yahoo data the platform pulls today. Since
the value delta is "labels, not decisions," a paid, key-gated dependency with unverified Indian
small-cap depth is a poor trade for a no-revenue personal project whose Yahoo path is already
hardened (tiered fallback + caching + P2 logging). **Recommended immediate next action:** spend the
hours on the higher-ROI top-5 instead — start with the **financials coverage spike** (confirms no
feed can supply a bank pack, closing this question empirically) and the **utilities/commodity
cyclical split** (removes the one V1-observed over-refusal), then Option A's honest "medium"
confidence disclosure. Keep the provider-agnostic architecture in place so EODHD remains a clean
drop-in **if** a future regime-safe, history-dependent requirement ever justifies it.
