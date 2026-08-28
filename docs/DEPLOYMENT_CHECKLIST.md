# Streamlit Cloud Deployment Checklist (P1 — Production Persistence)

The app runs without any database, but **Streamlit Cloud's disk is ephemeral** — without a
Postgres `DATABASE_URL`, paper trades, watchlist and saved sizing settings **reset on every
redeploy**. This checklist makes persistence durable and validated.

## What persists, and how
| Data | Store | Survives redeploy? |
|---|---|---|
| **Paper trades** | `trades` table (`trade_store.py`) | ✅ with Postgres · ❌ on SQLite (ephemeral) |
| **Watchlist + sizing settings** | `user_kv` table (`kv_get`/`kv_set`) | ✅ with Postgres · ❌ on SQLite |
| **Default portfolio** | `portfolio.csv` (committed to the repo) | ✅ always (it ships with the build) |
| **User-uploaded portfolio** | `st.session_state` only | ❌ by design — transient per session |
| **Angel One credentials** | `secrets.toml` / Streamlit secrets | ✅ (never in git) |

## One-time setup (≈5 min) — make trades & watchlist durable
1. **Create a free Postgres** — [neon.tech](https://neon.tech) or [supabase.com](https://supabase.com). Copy the connection string (`postgresql://user:pass@host/dbname`).
2. **Add it as a Streamlit secret** (App → ⚙️ Settings → Secrets):
   ```toml
   [database]
   url = "postgresql://user:pass@host/dbname?sslmode=require"
   ```
   *(or set an env var `DATABASE_URL` — both are read by `trade_store._database_url()`.)*
3. **Redeploy.** The app calls `ensure_schema()` automatically (creates `trades` + `user_kv`).
4. **Verify in the sidebar** — the badge must read **🟢 Paper trades & watchlist: cloud DB (persistent)**. 🟡 = still ephemeral; 🔴 = unreachable (fix the URL/SSL).

## Startup validation (automatic — P1)
On first render each session, `trade_store.validate_persistence()` runs and the sidebar shows:
- **🟢 persistent** — Postgres reachable, schema valid.
- **🟡 ephemeral** — SQLite; data resets on redeploy (set `DATABASE_URL`).
- **🔴 unreachable** — DB configured but not reachable / schema invalid (shows the error). **Do not rely on persistence until this is green.**
- **⚠️ last save did not persist** — a `kv_set` write failed (now logged, never silent).

`validate_persistence()` returns `{backend, db_url_present, reachable, schema_ok, ephemeral,
warnings[], error}` and never raises.

## Pre-deploy checklist
- [ ] `DATABASE_URL` (or `[database].url`) set in Streamlit secrets — **required for persistence**.
- [ ] Connection string includes `?sslmode=require` (Neon/Supabase need SSL).
- [ ] `psycopg2-binary` present in `requirements.txt` (Postgres driver).
- [ ] First boot shows **🟢** in the sidebar (not 🟡/🔴).
- [ ] Open a paper trade → redeploy → trade still present.
- [ ] Add a watchlist item → redeploy → item still present.
- [ ] Angel One creds (if used) are in secrets, **not** committed.

## Failure modes now surfaced (no longer silent — P1/P2)
- `kv_set` returns `False` + logs an **error** on write failure (was a silent no-op that could lose the watchlist).
- `kv_get` / `fetch_open` / `load_by_account` **log a warning** on read failure (was an empty result indistinguishable from "no data").
- The sidebar shows 🔴/⚠️ when storage is unreachable or a save failed.
