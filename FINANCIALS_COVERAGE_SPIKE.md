# Financials Coverage Spike — what Yahoo actually returns for bank/NBFC/insurer metrics

**Purpose:** evidence only. Empirically determine whether Yahoo Finance supplies the
financial-sector-specific metrics a future NIM/GNPA pack would need. **No analytics built, no
module modified.** Probe: live `yf.Ticker(...).info` + `.income_stmt` / `.balance_sheet` / `.cashflow`
for 10 tickers (4 banks, 3 NBFCs, 3 insurers), fetched once.

Legend: ✅ present & usable · ⚠️ present but unreliable/wrong-metric · ❌ absent / None · n/a not applicable to sector

| Metric | HDFCBANK | ICICIBANK | SBIN | KOTAKBANK | BAJFINANCE | SHRIRAMFIN | CHOLAFIN | HDFCLIFE | SBILIFE | ICICIGI |
|---|---|---|---|---|---|---|---|---|---|---|
| NIM | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | n/a | n/a | n/a |
| Net Interest Income | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | n/a | n/a | n/a |
| GNPA / NPA ratio | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | n/a | n/a | n/a |
| CASA ratio | ❌ | ❌ | ❌ | ❌ | n/a | n/a | n/a | n/a | n/a | n/a |
| Capital Adequacy (CAR/CRAR) | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | ❌ | n/a | n/a | n/a |
| Loan book / advances | ⚠️ | ⚠️ | ⚠️ | ⚠️ | ⚠️ | ⚠️ | ⚠️ | n/a | n/a | n/a |
| Provisions | ⚠️ | ⚠️ | ⚠️ | ⚠️ | ⚠️ | ⚠️ | ⚠️ | n/a | n/a | n/a |
| Embedded Value | n/a | n/a | n/a | n/a | n/a | n/a | n/a | ❌ | ❌ | ❌ |
| VNB / Value of New Business | n/a | n/a | n/a | n/a | n/a | n/a | n/a | ❌ | ❌ | ❌ |
| Premium income | n/a | n/a | n/a | n/a | n/a | n/a | n/a | ❌ | ❌ | ❌ |
| Claims / Combined ratio | n/a | n/a | n/a | n/a | n/a | n/a | n/a | ⚠️ | ⚠️ | ⚠️ |
| Solvency ratio | n/a | n/a | n/a | n/a | n/a | n/a | n/a | ❌ | ❌ | ❌ |

*(Result is uniform across every ticker in each sector — no per-name variation.)*

## Findings

### What IS available for a future NIM/GNPA pack
- **Net Interest Income** — present as an income-statement **row** for all 7 banks/NBFCs, alongside
  **`interest income`** and **`interest expense`** rows. The *numerator* of NIM exists.
- That is essentially **all** the usable raw material. No ratio that matters is provided directly.

### What is NOT available from Yahoo regardless of effort
- **Every India-bank-specific ratio is absent:** **NIM, GNPA/NPA, CASA, CAR/CRAR** — none appear in
  `info` (the only margin keys are the generic `profitMargins / grossMargins / ebitdaMargins /
  operatingMargins`, which are not bank metrics) and none appear as statement rows.
- **Every insurer-specific metric is absent:** **Embedded Value, VNB, Premium income, Solvency** — no
  `info` key, no statement row. (Confirms the E1-v2 **H4** insurance refusal is the only honest output.)
- These are India regulatory/actuarial disclosures (RBI returns, insurer EV reports); a generic global
  vendor's standardized schema does not model them.

### Present-but-unreliable (flagged specifically) — ⚠️
- **"Provisions" is a false positive.** The only matching row is **`tax provision`** (corporate tax),
  **not credit/loan-loss provisioning**. Using it as "provisions" would be **wrong data** — worse than
  missing. Loan-loss provisions are **absent**.
- **"Loan book / advances" is combined.** The only matching row is **`investments and advances`** —
  loans bundled with investments, so it is **not a clean advances figure** and is an unreliable
  denominator for any NIM/advances-growth derivation.
- **Insurer "claims" is an expense, not a ratio.** The only row is **`net policyholder benefits and
  claims`** (the benefits/claims *expense*) — there is **no combined ratio and no claims ratio**.

### Could a crude pack be derived?
NIM ≈ Net Interest Income ÷ earning assets is **not safely derivable**: NII exists, but Yahoo has **no
clean earning-assets / advances figure** (only combined `investments and advances`). GNPA, CASA, CAR,
EV, VNB and solvency have **no inputs at all** — they cannot be derived from anything Yahoo returns.

## Recommended next step: **NEITHER** (build nor wait for EODHD)
- **Do not build from Yahoo:** the four ratios that define bank/NBFC analysis (NIM, GNPA, CASA, CAR)
  are absent; the only "derivable" one (NIM) would rest on an unreliable combined-advances denominator,
  and the one provisioning row is the *tax* provision — a build would produce confidently-wrong numbers.
- **Do not wait for EODHD:** the EODHD audit already established that EODHD's generic global schema does
  **not** carry India-bank disclosures either — this spike independently confirms the data simply isn't
  in standardized financial statements; it lives in RBI/insurer regulatory filings.
- **Therefore:** the realistic ceiling on current/affordable data is the **P/B-vs-ROE financials lens
  already shipped** (D1 + E1-v2), which V1 showed differentiates banks/NBFCs sensibly. A genuine
  NIM/GNPA/CASA pack requires a **specialist India banking feed** (Screener/Trendlyne — disqualified
  for production in `FUNDAMENTALS_DATA_MEMO.md`) and is out of scope for a personal project.

**This spike closes the "financials pack" question empirically: the data is not obtainable from Yahoo
or EODHD. No build trigger.**
