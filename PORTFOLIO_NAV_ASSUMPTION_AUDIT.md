# Portfolio NAV Assumption Audit — "Constant Holdings Through History"

**Audit only — no code changed.** Assesses the impact of reconstructing the NAV curve as
`NAV_t = Σ_i quantity_i(today) × close_i,t` — i.e. **today's exact share counts held constant
backward** over the lookback.

## What the assumption does and doesn't model
- ✅ **Correctly** models a buy-and-hold book's *drifting weights* (constant **quantity**, not
  constant weight) — this is the right model for an unrebalanced portfolio.
- ❌ Projects **today's composition** backward: names added recently are shown "held all along";
  names the investor **sold** (often losers) are absent. Pre-purchase returns are **imputed**.
- ❌ Ignores interim **cash flows** (deposits/withdrawals) and **dividends** (price-return only).

## Core finding (the whole audit in one sentence)
**The assumption is the *correct input* for risk-shape metrics and an *optimistically biased*
input for reward metrics.** Risk metrics describe the *current book's character* (exactly what
constant-holdings provides); reward metrics depend on the *return path*, which is inflated by
projecting today's winners/survivors backward.

The bias lives **entirely in the reward numerator**. The volatility/risk machinery is unaffected:
- Daily NAV return = weighted blend of the holdings' day-*t* returns at today's composition →
  **volatility, beta, correlation, risk-contribution all reflect the current book correctly.**
- The **mean return** is biased upward because imputed pre-purchase periods carry the full run-up
  of names you only recently bought (and exclude names you sold at a loss).

## Per-metric assessment

| Metric | Materially affected? | Direction | Valid for… |
|---|---|---|---|
| **Correlation Matrix** | **No (negligible)** | — | Composition- and weight-independent; pure return-series relationship. Fully valid. |
| **Risk Contribution** | **No (low)** | — | Inherently a *current-snapshot* metric (today's weights × window covariance). Measuring exactly what it should. |
| **Portfolio Beta** | **No (low)** | — | Current weights × per-stock betas. A current-book snapshot; assumption irrelevant. |
| **Max Drawdown** | **Partly (medium)** | ambiguous | Valid as *drawdown susceptibility of the current book*; **distorted** as *realised experience* (imputed names add/remove path drawdowns). |
| **Sharpe** | **Yes (high)** | optimistic ↑ | Denominator (vol) valid; **numerator (return) inflated** by survivorship-of-own-winners. |
| **Sortino** | **Yes (high)** | optimistic ↑ | Same as Sharpe; downside-dev is path-sensitive so slightly more fragile. |
| **Calmar** | **Yes (highest)** | optimistic ↑ | **Both** terms biased (inflated return ÷ distorted MaxDD) — ratio compounds the error. |

**Directionally valid (keep trusting):** Correlation, Risk Contribution, Beta, Volatility.
**Materially affected (caveat heavily):** Sharpe, Sortino, Calmar, and MaxDD-as-realised.

## Error bounds under common scenarios (heuristic)

| Scenario | Reward-metric error (Sharpe/Sortino/Calmar, return) | Risk-metric error |
|---|---|---|
| **Stable buy-and-hold**, no changes in the window (e.g. the sample portfolio — all bought 2016) | **≈ 0** (reconstruction = reality) | ≈ 0 |
| **Moderate turnover** (a few names added/trimmed in-window) | return ±2–5%; Sharpe ±0.2–0.5; Calmar ±30–80% | negligible |
| **Recent winner added / loser sold** | return **+5–15%**; Sharpe **+0.5–1.0** (optimistic); Calmar up to ~2× | negligible |
| **Recently rebuilt / high turnover** | reward metrics ~meaningless as *realised*; still valid as *"if I held this book"* hypothetical | valid (snapshot) |

**Secondary, opposite-sign effect:** dividends are excluded (price-return), which *understates* reward
metrics by ~1–3%/yr for dividend payers — a partial offset to the optimistic composition bias.

> **For the bundled sample portfolio specifically**, every holding's `date_bought` (2016-05-28)
> predates all lookbacks, so its bias is **zero** — the reconstruction is a faithful buy-and-hold
> curve. The risk above applies to *real users with turnover*.

## Severity ranking (most → least affected)
1. **Calmar** — HIGH (both numerator and denominator biased)
2. **Sharpe** — HIGH (return inflation)
3. **Sortino** — HIGH (return inflation; path-sensitive)
4. **Max Drawdown** — MEDIUM (valid as susceptibility, distorted as realised)
5. **Portfolio Beta** — LOW (current snapshot)
6. **Risk Contribution** — LOW (current snapshot)
7. **Correlation Matrix** — NEGLIGIBLE (weight/composition-independent)

## User-facing disclosure recommendations
1. **Relabel the reward ratios** as *hypothetical on the current book* — e.g. group Sharpe/Sortino/
   Calmar/Total-return under *"If you'd held today's exact holdings over the period"*, distinct from
   the risk panel. They answer that question, **not** "your realised return".
2. **Flag recent additions.** `date_bought` is already in the data — when any holding was bought
   *within* the lookback, show: *"N holding(s) bought during this window — reward ratios are
   optimistically biased; risk metrics remain valid."*
3. **Lead with the robust metrics.** Present Correlation, Risk Contribution, Beta and Volatility as
   the primary outputs (they're trustworthy); keep the reward ratios clearly-asterisked secondary.
4. Show **% of book held for the full lookback** (computable from `date_bought`) as a one-glance
   reliability indicator, plus an explicit **"dividends excluded"** note.

## Recommendation: **IMPROVE**

- **KEEP — rejected.** The reward-ratio optimistic bias is *material* (HIGH severity for 3 of 7
  metrics), and the current methodology note — while honest — does not distinguish the **robust
  risk metrics** from the **biased reward metrics**, so users may over-trust Sharpe/Calmar.
- **REBUILD — not now.** A faithful realised NAV needs **full transaction history** (every buy/sell
  with date + quantity) to compute true time-weighted / money-weighted returns. The app stores only
  *current* quantity + a single `date_bought` per lot — **not** interim trades — so a faithful
  rebuild is *gated on capturing transaction events* (a separate data-model change).
- **IMPROVE — recommended.** Disclosure + a bounded engine tweak, no rebuild:
  1. Sharpen the disclosure and relabel reward ratios as hypothetical (items 1–4 above).
  2. Use the **existing `date_bought`** to flag/clamp recently-added names (eliminates most of the
     imputation bias at the source, with the data already on hand).
  3. Add the dividends-excluded note.

**Net:** the engine is sound and the *risk* analytics — the more decision-useful half — are valid as
built. The fix is to stop the *reward* ratios from being read as realised performance, which is a
disclosure/UX change plus a small, data-available refinement, not a rebuild.

*Audit only — no application code changed.*
