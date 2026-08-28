# HANDOFF — NSE Smart Investor

Cold-start guide for any developer or AI session picking this repo up fresh. If you remember
nothing about this project, **read this file first**, then the reports in §7.

---

## 1. What this is
A Streamlit dashboard for **NSE/BSE (Indian) equity analysis** — scoring, portfolio risk, paper
trading, fundamentals, and a rules-based valuation/thesis layer. Personal project, no revenue,
**no paid-API budget**. Deploys on **Streamlit Community Cloud**, auto-building from `origin/main`.

- **Entry point:** `dashboard/app.py` (thin — sets page config, theme, redirects to Command Centre).
- **17 pages:** `dashboard/pages/01_…` → `17_tomorrow_watchlist.py`.
- **Repo:** github.com/mrinaljhunjhunwala-ui/nse-smart-investor

## 2. Run it locally
```bash
pip install -r requirements.txt
streamlit run dashboard/app.py
```
**Windows note:** use the `py` launcher (not `python`). For console output with ₹ symbols set
`PYTHONUTF8=1`.

## 3. Test & CI
```bash
py -m pytest -m "not slow" -q      # default suite (275 passing) — what CI runs
py -m pytest -m slow -q            # the gated backtest end-to-end smoke (network)
py tools/validate_valuation.py --update   # refresh the valuation golden snapshot (live Yahoo)
```
- `pytest.ini` markers: **`smoke`** (page-load tests, network-blocked), **`slow`** (excluded by
  default via `addopts = -m "not slow"`), `network`.
- **CI:** `.github/workflows/ci.yml` runs `pytest -m "not slow"` on push/PR to `main`.
- **Page smoke** (`tests/test_pages_smoke.py`): loads all 17 pages headlessly with **network
  blocked** (fail-fast sockets) so they take the graceful degraded path → deterministic. Guard:
  `assert len(_PAGES) == 17` — **bump this when you add/remove a page.**
- **Valuation regression** (`tests/test_valuation_golden_snapshot.py`): replays captured
  `ValuationInputs` from `data/valuation_golden_snapshot.json` through the pure engine and fails on
  posture/confidence/guard drift (offline). After an intentional logic change, regenerate the
  snapshot with `--update` and review the diff.

## 4. Architecture (where things live)
```
dashboard/
  app.py                     entry point
  pages/01..17_*.py          one file per page (explicit imports — NO globals().update())
  shared/
    design.py                theme/CSS/Plotly template
    nav.py                   sidebar + the 4 nav maps (_NAV_GROUPS/_PAGE_EMOJI/_PAGE_FULL_NAME/_PAGE_FILE)
    cache.py                 @st.cache_data data loaders + scan helpers (_home_top_picks,
                             _tomorrow_watchlist, get_composite_score, load_ticker_df, _deep_confirmation)
    trade_utils.py           paper-trade UI helpers (_paper_trade_popover, account mgmt)
    chart_helpers.py         price chart + top bar + breadth/macro loaders
analysis/                    PURE engine (no Streamlit) — heavily unit-tested
  score.py                   CompositeScore (technical/momentum/volume/pattern/sentiment)
  hedging.py                 stock/portfolio beta vs Nifty
  portfolio_risk.py          NAV reconstruction, Sharpe/Sortino/Calmar, correlation, risk-contrib
  portfolio_manager.py       portfolio.csv → scored holdings + diversification
  liquidity.py               turnover/volume → liquidity tier (Phase C1)
  sector_classification.py   SINGLE SOURCE OF TRUTH for metric applicability (financials guard, D1)
  fundamentals/              Yahoo-backed: models, service, analytics (ROE/ROCE/CAGR/FCF),
                             valuation (P/E,P/B,EV/EBITDA), valuation_decision (E1-v2 posture engine)
  thesis/                    thesis_models/_rules/_engine (Bull/Bear/Risk/Verdict) + portfolio_fit
data/
  fetcher.py                 tiered price fetch: Angel One → Stooq → Yahoo (cached, logged)
  angel_fetcher.py           Angel One SmartAPI (optional Tier 0)
  universe.py                ticker→sector map, get_universe(), get_sector()
trade_store.py               persistence: paper trades (trades table) + settings/watchlist (user_kv);
                             SQLite by default, Postgres when DATABASE_URL is set
tools/validate_valuation.py  live valuation regression diagnostic (NOT a CI test)
```

## 5. The analytics pipeline (read these specs to understand the "brain")
1. **Sector-aware fundamentals (D1)** — `sector_classification.py` decides which metrics are valid
   per sector. Banks/NBFCs/insurers do **not** get a leverage flag, EV/EBITDA, ROCE or FCF
   (deposits aren't debt) → assessed on P/B + ROE. Insurers refuse (no embedded value).
2. **ROCE + FCF** — derived in `fundamentals/analytics.py`; surfaced only where meaningful.
3. **Liquidity & Valuation context (C1)** — turnover tiers; P/E, P/B, EV/EBITDA surfaced factually.
4. **E1-v2 Valuation Decision Layer** — `fundamentals/valuation_decision.py`. Regime-neutral
   (growth/quality, NOT own-history). **Guards run before matrices** (cyclical peak/trough,
   quality gate, PEG band, cash-conversion veto). Output is a *descriptive posture* — never
   buy/sell/fair-value/cheap/expensive. Spec: `VALUATION_DECISION_E1_V2_SPEC.md`.
5. **Thesis + Portfolio Fit** — rules-based Bull/Bear/Risk/Verdict and "does it fit my book".

## 6. Conventions
- **Git:** commit then **push to `main` automatically** (standing preference). Streamlit Cloud
  auto-deploys. End commit messages with `Co-Authored-By: Claude …`. Never commit secrets.
- **Secrets:** Angel One creds + `DATABASE_URL` live in Streamlit secrets / `secrets.toml`
  (gitignored) — never in code.
- **PowerShell quirks:** heredocs/here-strings break on `<`/special chars → write the commit
  message to a file and `git commit -F`. `git push` prints a RemoteException wrapper but succeeds.
- **No `globals().update()`** in pages — each page uses explicit imports (P3). If you add a page,
  give it explicit imports and update the 4 nav maps + the smoke guard.

## 7. Decision docs (the "why" — read before changing the brain)
| Doc | What it decides |
|---|---|
| `PRODUCTION_HARDENING_FINAL_REPORT.md` / `OPERATIONAL_HARDENING_REPORT.md` | platform state, top-5 next steps |
| `VALUATION_DECISION_E1_V2_SPEC.md` + `VALUATION_E1_STRESS_TEST.md` | the valuation engine + why its guards exist |
| `NSE_INVESTOR_AUDIT.md` | why sector-awareness (financials) was the priority |
| `EODHD_DECISION_AUDIT.md` | **NO-GO** on a paid data provider — and why |
| `FINANCIALS_COVERAGE_SPIKE.md` | NIM/GNPA/CASA/embedded-value are not obtainable from Yahoo/EODHD |
| `VAL_LIQUIDITY_AUDIT.md` | why historical valuation bands (C2) are deferred (NSE regime risk) |
| `DEPLOYMENT_CHECKLIST.md` + `PERSISTENCE_ACCEPTANCE.md` | how to make persistence durable + prove it |

## 8. Known gaps / deferred (nothing is blocking)
- **Persistence not yet PROVEN on the live deploy** — set a free Postgres `DATABASE_URL`
  (Neon/Supabase) and run the redeploy check in `PERSISTENCE_ACCEPTANCE.md`. Until then paper
  trades/watchlist reset on redeploy (SQLite is ephemeral on Streamlit Cloud).
- **Reliability tail** — ~9 silent swallows remain in `analysis/hedging`, `portfolio_risk`,
  `portfolio_manager` (deferred; low risk).
- **NOT doing** (decided, with evidence): EODHD/paid providers, NIM/GNPA/CASA financials pack,
  historical valuation bands (C2), prediction tracking, AI-narration of the thesis.

## 9. How to resume cold (checklist)
1. `git pull` (work in the existing local clone — nothing to migrate between machines/accounts).
2. `pip install -r requirements.txt`; `py -m pytest -m "not slow" -q` → expect **275 passed**.
3. Read the relevant doc(s) in §7 for whatever you're touching.
4. Make changes → run the suite → commit → push to `main` (auto-deploys).
5. If `git push` asks for auth on a new machine: `gh auth login` or set a PAT (one-time).

*This repo was built to be resumable from docs alone — the conversation history is not needed.*
