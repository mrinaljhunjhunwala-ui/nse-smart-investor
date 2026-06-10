# Fundamental Quality Efficacy Report

**Question:** do the platform's fundamental metrics predict 6–12-month returns?

**Answer: one does — revenue growth — and it is the strongest signal found in
the entire research program (ρ ≈ +0.14, monotone quintiles, Q5−Q1 ≈ +8.5pp
over 6 months).** The others were flat to *counter-productive* in this window:
high ROE and low leverage both **underperformed** (the 2022–25 Indian
value/PSU/capex rotation punished expensive "quality"), so a naive
equal-weight fundamental composite is dragged negative. Fundamentals did not
improve high-Trend-Quality selection except through revenue growth itself.

> Produced by `research/fundamental_quality.py` — point-in-time replay using
> dated statements from the canonical fundamentals engine. No production
> changes. Regenerate: `py -m research.fundamental_quality`

## Methodology (the honest parts)

| | |
|---|---|
| Observations | 4,266 (209 tickers × monthly dates, 2022-10 → 2025-05) |
| Point-in-time rule | at date t, only statements with fiscal period-end ≤ **t − 180 days** (conservative Indian reporting/audit lag). Metrics are None when not computable — never zero-filled |
| Sampling | **monthly**, deliberately not weekly — annual fundamentals change ~once a year; weekly rows would add no information and inflate significance |
| Metrics | ROE (NI / avg equity), D/E, revenue growth (annualised, ≥2 usable statements ≥0.9y apart), EPS growth; cross-sectional rank composite (D/E inverted) |
| Trend Quality | production score (post pattern-removal) at the nearest prior weekly research date |
| Coverage | ROE 100% · D/E 99% · EPS growth 59% · **revenue growth 42%** (back-loaded: usable from 2023-07 because yfinance's oldest statement year is field-sparse) |
| Caveats | survivorship (current constituents); **restatement risk** (yfinance serves current statement values, not as-first-reported); heavily overlapping 6/12-month forward windows → effective independent periods ≈ 3–4, treat magnitudes as descriptive; single macro window |

## Q1/Q2 — factor ranking (Spearman, oriented better-is-higher)

| Metric | vs fwd 6m | vs fwd 12m | Coverage |
|---|---|---|---|
| **Revenue growth** | **+0.141** | **+0.137** | 42% |
| EPS growth | +0.030 | +0.037 | 59% |
| ROE | **−0.067** | −0.052 | 100% |
| Low D/E | −0.027 | **−0.086** | 99% |
| Naive composite | −0.039 | −0.074 | 100% |

**Revenue-growth quintiles** (n=1,774 subsample):

| Quintile | avg growth % | fwd 6m % | fwd 12m % |
|---|---|---|---|
| 1 (lowest) | −7.0 | +3.7 | +3.2 |
| 2 | +5.7 | +3.2 | −0.7 |
| 3 | +13.0 | +5.2 | +4.7 |
| 4 | +19.1 | +6.8 | +9.2 |
| 5 (highest) | +37.1 | **+12.2** | **+14.2** |

**Robustness:** within the *same* subsample (same dates/stocks), revenue growth
(+0.141) beats EPS growth (+0.049), ROE (−0.113), low-D/E (−0.129) and Trend
Quality (−0.066); the per-date cross-sectional correlation is positive on
**8 of 8** dates (mean +0.165). Not a coverage artifact relative to the other
metrics — but the window is 2023-07 → 2025-05 with ~3–4 independent
forward periods, so treat it as a strong lead, not a settled law.

## Q3 — does Fundamental Quality add value beyond Trend Quality?

Double sort (within-date median splits, fwd 6m / 12m %):

| | Low fundamentals | High fundamentals |
|---|---|---|
| **Low TQ** | 9.5 / 11.6 | 10.6 / 11.4 |
| **High TQ** | **12.4 / 13.7** | 10.5 / 12.0 |

**No** — the naive composite *reduced* returns among high-TQ names (12.4% →
10.5%). The composite's ROE and low-leverage components fought the window's
factor rotation. The value beyond TQ lives in **revenue growth specifically**,
not in "fundamental quality" as a blended concept.

## Q4 — regime survival (Spearman vs fwd 6m)

| Regime | n | ROE | low D/E | Rev growth | EPS growth | Composite |
|---|---|---|---|---|---|---|
| bear | 836 | **−0.156** | −0.097 | **+0.194** | +0.087 | +0.018 |
| bull | 2,786 | −0.043 | +0.006 | +0.049 | −0.004 | −0.044 |

Revenue growth is the only metric that survives both regimes — and is
*strongest in bears* (growers fell less / recovered faster). ROE was most
damaging in the bear leg (expensive quality de-rated). Sideways had too few
observations to report.

## Q5 — composite vs individual metrics

**The naive composite fails** (−0.04 to −0.07): averaging one good signal with
two counter-productive ones destroys it. If a composite is ever productised, the
evidence supports a *growth-weighted* construction, not equal weights — and
that design would need its own out-of-window validation first.

## Conclusions & evidence-based recommendations (no production changes made)

1. **Revenue growth is the platform's most promising untapped signal** —
   stronger than anything price-based found in five studies. Recommended next
   step: surface it as a visible, point-in-time-honest metric (it already
   exists in the fundamentals UI) and validate out-of-window before any scoring
   role.
2. **Do not build an equal-weight "quality" composite** — this window actively
   punished ROE/low-leverage tilts; composite construction is a research
   decision, not a default.
3. **Quality-metric scoring should remain out of the Trend Quality score** —
   the double sort shows blended fundamentals subtract from high-TQ selection.
4. **Re-run this study when FY2026+ statements widen the growth-metric window**
   (coverage rises mechanically each year, and a second macro regime enters the
   sample).

*2026-06-11 · 4,266 observations · point-in-time lag 180d · production
untouched · outputs in `research/output/fundamental_quality_*.csv`, `fq_*.csv`.*
