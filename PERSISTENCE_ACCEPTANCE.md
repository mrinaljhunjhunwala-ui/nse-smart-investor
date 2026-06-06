# Persistence Acceptance Check (DATABASE_URL)

Operator procedure to **prove** paper trades / watchlist survive a redeploy. No infrastructure is
provisioned here — this is the validation runbook + final operator checklist. Pairs with
`DEPLOYMENT_CHECKLIST.md` (setup) and `trade_store.validate_persistence()` (startup self-check).

## Checklist accuracy — verified against the code
The `DEPLOYMENT_CHECKLIST.md` claims were re-checked against the current implementation:

| Claim | Verified in code |
|---|---|
| `validate_persistence()` checks URL present / reachable / schema | `trade_store.validate_persistence()` (returns `{backend, db_url_present, reachable, schema_ok, ephemeral, warnings, error}`) |
| Sidebar badge 🟢/🟡/🔴 + ⚠️ save-failed | `dashboard/shared/nav.py` (reads `validate_persistence()`, cached per session) |
| `kv_set` is non-silent (returns bool + logs ERROR) | `trade_store.kv_set` |
| `kv_get` / `fetch_open` / `load_by_account` log on failure | `trade_store` (P2) |
| Paper trades → `trades` table; watchlist/settings → `user_kv` | `trade_store.ensure_schema` / `_kv_ensure` |
| Default `portfolio.csv` committed; uploads session-only | `dashboard/pages/03_my_portfolio.py` (uploads held in `st.session_state`) |
| `psycopg2-binary` present for Postgres | `requirements.txt` |

All accurate. No corrections required.

## Acceptance test — paper-trade persistence across a redeploy
**Pre-req:** a Postgres `DATABASE_URL` (or `[database].url`) set in Streamlit secrets (see
`DEPLOYMENT_CHECKLIST.md` §setup). Do this on the deployed app.

1. **Confirm the backend is cloud DB.** Open the app → sidebar must read
   **🟢 Paper trades & watchlist: cloud DB (persistent)**. If 🟡 (SQLite) or 🔴 (unreachable), STOP and
   fix the URL/SSL first — persistence cannot be proven on ephemeral storage.
2. **Create a known paper trade.** Go to **📂 Paper Trades** (or open a trade from Analyze Stock).
   Record a unique marker (ticker + quantity + timestamp), e.g. `INFY × 7 @ <time>`.
3. **Add a watchlist marker.** Add a distinctive ticker to the watchlist (e.g. `BEL`).
4. **Force a redeploy** (the event that wipes ephemeral disk):
   - push any commit to `main` (Streamlit Cloud auto-redeploys), **or**
   - App menu → **Reboot app** in Streamlit Cloud.
   Wait for the app to come back up.
5. **Verify persistence after redeploy:**
   - Sidebar still **🟢**.
   - **📂 Paper Trades** still shows `INFY × 7 @ <time>` (same id/timestamp).
   - Watchlist still contains `BEL`.
6. **Result:**
   - ✅ both markers present → **persistence PROVEN**.
   - ❌ markers gone but badge 🟢 → DB connected but writes not committing — check DB logs / table
     grants; `kv_set` will have logged an ERROR.
   - ❌ badge 🟡 after redeploy → secret not applied — re-check `DATABASE_URL` in Streamlit secrets.

## Negative control (optional, proves the test is meaningful)
On a build with **no** `DATABASE_URL` (SQLite): the badge reads 🟡 and the same redeploy **wipes** the
trade — confirming the acceptance test actually distinguishes persistent vs ephemeral.

## Final operator checklist (deploy → prove)
- [ ] `DATABASE_URL` / `[database].url` set in Streamlit secrets (with `?sslmode=require`).
- [ ] First boot shows sidebar **🟢** (not 🟡/🔴).
- [ ] `validate_persistence()` (startup) → `reachable: true, schema_ok: true, ephemeral: false`.
- [ ] Acceptance test passed: paper trade **survived** a redeploy.
- [ ] Acceptance test passed: watchlist item **survived** a redeploy.
- [ ] No ⚠️ "last settings save did not persist" warning in the sidebar.
- [ ] Angel One creds (if used) in secrets, **not** committed.
- [ ] CI green on `main` (`.github/workflows/ci.yml`) before relying on a build.

When every box is ticked, persistence is **proven**, not merely configured.
