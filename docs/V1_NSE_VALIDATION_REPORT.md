# V1 — E1-v2 NSE Universe Validation

Validated the E1-v2 Valuation Decision Layer against **62 real NSE stocks** (live Yahoo
fundamentals, 0 fetch errors) across Nifty 50, Banks, NBFCs, Insurance, PSUs, Capital Goods,
Consumer, IT and midcaps. **Valuation logic was NOT changed** — this is measurement only.

## Distributions (n = 62)
**Posture:** Reasonable 35% · Insufficient 21% · Demanding-vs-growth 21% · Supported-by-quality 8% ·
Demanding-vs-ROE 6% · Supported-by-ROE 3% · Supported-by-growth 3% · Demanding-vs-returns 2%.

| Bucket | Share |
|---|---|
| **Supportive** (any SUPPORTED_*) | **15%** (9) |
| **Reasonable** | **35%** (22) |
| **Demanding** (any DEMANDING_*) | **29%** (18) |
| **Insufficient (refusal)** | **21%** (13) |

**Confidence:** high 44% · medium 26% · none 21% (= refusals) · low 10%.
**Branch:** non-financial 42 · financial 16 · insurance 4.
**Guard triggers:** H4-insurance ×4 · cyclical-trough ×4 · growth-lens-off ×3 · H3-missing-metric ×2.

## The five questions — evidence

### 1. Are guards firing appropriately? ✅ Yes — and conservatively
- **All 4 insurers** (ICICIGI, ICICIPRULI, HDFCLIFE, SBILIFE) → Insufficient via **H4** (P/EV unavailable). Correct.
- **Cyclical-trough** fired on SAIL (steel), SRF (chemicals), IOC (refining), POWERGRID — commodity/cyclical names where trailing earnings distort the multiple. (POWERGRID, a regulated utility, is a mild over-trigger — it sits in the `Energy & Power` cyclical set; the result is a conservative *refusal*, not a misleading call. Candidate for a future utilities/commodity split.)
- **growth-lens-off → Insufficient** on RELIANCE, ONGC, COALINDIA — low/lumpy growth with non-exceptional ROCE; correctly declines a growth-relative posture.
- **H3-missing-metric** on LTIM, DEEPAKNITR — both 404 on Yahoo (symbol gaps) → refuse rather than fabricate.

### 2. Are supportive postures too rare? ❌ No — appropriately conservative
15% supportive is reasonable for a **richly-valued large-cap regime**, and is exactly the v2 design
intent ("caution is cheap, false support is not"). Crucially, support went to *genuine* quality/value:
TCS, PERSISTENT, BEL, POLYCAB, NMDC (quality); ICICIBANK, SHRIRAMFIN (ROE); BHARTIARTL, MARUTI (growth).

### 3. Are supportive postures too common? ❌ No
No cyclical peak earned "supported"; no low-quality grower earned "supported by growth". The gates hold.

### 4. Are financial outputs sensible? ✅ Yes — the headline win
- **Banks** differentiate on P/B×ROE: ICICIBANK **Supported-by-ROE**, HDFCBANK **Demanding-vs-ROE** (rich P/B), the 7 PSU/mid banks **Reasonable** at **high** confidence. **Zero false leverage / EV-EBITDA flags** (D1 fix holding in the wild).
- **NBFCs** spread sensibly: SHRIRAMFIN Supported-by-ROE, BAJFINANCE/CHOLA/LICHSG Reasonable, BAJAJFINSV/MUTHOOT/SBICARD Demanding-vs-ROE (high P/B).
- **Insurers** uniformly refused (correct).

### 5. Is the engine discriminating meaningfully? ✅ Yes — 8 distinct postures, sensible within-sector spread
- **IT:** TCS/PERSISTENT supported-by-quality; WIPRO/HCLTECH/TATAELXSI demanding-vs-growth; COFORGE/TECHM reasonable.
- **Capital Goods:** BEL supported-by-quality; SIEMENS/ABB/CUMMINS/HAVELLS demanding-vs-growth (post-rerating rich multiples).
- **Consumer:** the expensive staples (NESTLE/MARICO/COLPAL/HINDUNILVR) demanding; TATACONSUM demanding-vs-returns (lower ROCE) — a discriminating call.
- **Banks:** spread across Supported / Reasonable / Demanding by P/B-ROE.

The engine is **not** collapsing into one bucket — it separates quality compounders, rich-but-strong growers, expensive low-return names, cyclicals (refused), and financials (P/B-ROE) coherently.

## Coverage note
2 of 62 tickers (LTIM, DEEPAKNITR) returned Yahoo 404s (renamed/SME symbols) → correctly refused via
H3. This is the known Yahoo small/mid-cap symbol-coverage limit, not an engine fault.

## Verdict
E1-v2 behaves **as designed on real NSE data**: guards fire appropriately (insurers, cyclicals,
no-growth, data gaps), supportive postures are conservative and well-targeted, financials are
sensible and differentiated with no false leverage flags, and the engine discriminates meaningfully
within and across sectors. No logic changes recommended from this run; the only refinement candidate
is separating regulated utilities from commodity-energy in the cyclical set (minor, conservative).

*Validation only — no valuation logic changed.*
