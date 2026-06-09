# 📈 NSE Smart Investor

An AI-powered **Streamlit dashboard for NSE/BSE (Indian) equity analysis** — composite scoring,
portfolio risk, paper trading, sector-aware fundamentals, a rules-based valuation/thesis engine,
intraday tools, and optional live broker integration via Angel One SmartAPI.

> **Educational use only.** Not SEBI-registered investment advice. Past performance ≠ future results.

🔗 **Live app:** auto-deployed on Streamlit Community Cloud from `main`
📦 **Repo:** [github.com/mrinaljhunjhunwala-ui/nse-smart-investor](https://github.com/mrinaljhunjhunwala-ui/nse-smart-investor)

---

## ✨ Features

A 17-page platform, grouped into five workspaces:

| Workspace | Pages |
|---|---|
| **Markets** | Market Live · Market Overview · Market Internals (breadth + macro) |
| **Trading** | Intraday Trader (CPR / ORB / Supertrend / VWAP) · Smart Screener · OI & Options |
| **Portfolio** | My Portfolio · Paper Trades · My Watchlist · Tomorrow's Watchlist |
| **Analysis** | Analyze Stock · Backtest · Swing Checklist |
| **Tools** | Position Sizer · Angel One · Investor Guide · Command Centre (home) |

**Highlights**
- **Composite Score (0–100):** technical · momentum · volume · candlestick pattern · news sentiment.
- **Sector-aware fundamentals:** banks/NBFCs/insurers are assessed on the right metrics (P/B + ROE),
  not penalised for "leverage" that is really deposits.
- **Valuation Decision Layer (E1-v2):** regime-neutral, guard-first engine that outputs a *descriptive
  posture* — never a buy/sell call.
- **Portfolio risk:** beta vs Nifty, NAV reconstruction, Sharpe/Sortino/Calmar, correlation, HHI
  concentration, and hedge sizing.
- **Intraday toolkit:** Opening-Range Breakout, Central Pivot Range, Supertrend, anchored VWAP, gap scanner.
- **Angel One SmartAPI (optional):** live quotes, holdings, positions, funds, order placement & GTT.
- **Paper trading:** journal with persistence (SQLite locally, Postgres in production).

---

## 🚀 Quick start

```bash
pip install -r requirements.txt
streamlit run dashboard/app.py
```

**Windows:** use the `py` launcher (not `python`). For ₹-symbol console output, set `PYTHONUTF8=1`.

---

## 🔑 Configuration (optional)

Live broker data and durable persistence are optional. Add secrets to `.streamlit/secrets.toml`
(gitignored) or as environment variables — never commit them:

```toml
# Angel One SmartAPI (Tier-0 live data + order placement)
[angel_one]
api_key     = "..."
client_id   = "..."
password    = "..."
totp_secret = "..."   # base32 seed from authenticator setup

# Durable persistence (paper trades + watchlist survive redeploys)
# DATABASE_URL = "postgresql://..."   # e.g. a free Neon/Supabase instance
```

Without these the app still runs fully — it falls back to Stooq/Yahoo for data and ephemeral
SQLite for storage.

---

## 🧱 Architecture

```
dashboard/
  app.py                 thin entry point (page config + theme + redirect to Command Centre)
  pages/01..17_*.py      one file per page (explicit imports — no global injection)
  shared/                design.py (NSE Pro theme) · nav.py · cache.py · chart_helpers.py · trade_utils.py
analysis/                PURE engine, no Streamlit — heavily unit-tested
  score.py · hedging.py · portfolio_risk.py · portfolio_manager.py · liquidity.py
  sector_classification.py   single source of truth for metric applicability
  fundamentals/          Yahoo-backed models, analytics (ROE/ROCE/CAGR/FCF), valuation engine
  thesis/                rules-based Bull/Bear/Risk/Verdict + portfolio fit
data/
  fetcher.py             tiered price fetch: Angel One → Stooq → Yahoo (cached)
  angel_fetcher.py       Angel One SmartAPI client
  universe.py            ticker → sector map
trade_store.py           persistence: SQLite by default, Postgres when DATABASE_URL is set
```

The data engine in `analysis/` is intentionally Streamlit-free so it can be unit-tested and reused.

---

## 🧪 Tests & CI

```bash
py -m pytest -m "not slow" -q      # default suite (what CI runs)
py -m pytest -m slow -q            # gated end-to-end backtest smoke (needs network)
```

- **Page smoke** (`tests/test_pages_smoke.py`) loads all 17 pages headlessly with network blocked,
  so they take the graceful degraded path → deterministic.
- **Valuation regression** (`tests/test_valuation_golden_snapshot.py`) replays captured inputs through
  the pure engine and fails on posture/confidence drift.
- **CI** (`.github/workflows/ci.yml`) runs `pytest -m "not slow"` on every push/PR to `main`.

---

## 🌐 Deployment

Pushes to `main` auto-deploy on **Streamlit Community Cloud**. For durable paper-trade/watchlist
persistence across redeploys, set a `DATABASE_URL` (see Configuration) — SQLite is ephemeral on Cloud.

---

## 📚 Further reading

New to the codebase? Start with **[`HANDOFF.md`](HANDOFF.md)** — a cold-start guide covering the
architecture, test/CI commands, deploy/persistence steps, and a "how to resume" checklist. Deeper
decision docs (valuation spec, sector-awareness audit, data-provider decisions) are listed there.

---

*Built as a personal, no-budget project. No paid data APIs.*
