# Persistent Paper Trades (optional, ~5 min)

By default your paper trades are stored in a local SQLite file (`trades.db`).
That works great locally, **but Streamlit Cloud's disk is wiped on every
redeploy**, so on the hosted app your trades reset whenever the code is pushed.

To make paper trades **survive redeploys**, point the app at a free cloud
Postgres database. The app auto-detects it — no code changes needed.

The sidebar shows which backend is active:
- 🟡 *local (resets on redeploy)* — SQLite (default)
- 🟢 *cloud DB (persistent)* — Postgres connected ✅

---

## Option A — Neon (recommended, simplest)

1. Go to **https://neon.tech** and sign up (free tier, no card).
2. Create a project. Neon shows a **connection string** like:
   ```
   postgresql://user:password@ep-xxx.aws.neon.tech/neondb?sslmode=require
   ```
   Copy it.
3. Add it to the app's secrets:
   - **Streamlit Cloud:** App → **Settings → Secrets**, paste:
     ```toml
     [database]
     url = "postgresql://user:password@ep-xxx.aws.neon.tech/neondb?sslmode=require"
     ```
   - **Locally:** put the same block in `.streamlit/secrets.toml`
     (this file is gitignored — never commit it).
4. Reboot the app. The sidebar should now read **🟢 cloud DB (persistent)**.
   The `trades` table is created automatically on first use.

## Option B — Supabase

1. Go to **https://supabase.com**, create a project (free tier).
2. **Project Settings → Database → Connection string → URI**. Copy it and
   replace `[YOUR-PASSWORD]` with your database password.
3. Add it under `[database]` `url = "..."` exactly as in Option A, step 3.

## Option C — Environment variable

Instead of secrets you can set an env var (useful for the GitHub Actions
alert job too):
```
DATABASE_URL=postgresql://user:password@host/dbname?sslmode=require
```

---

## Notes

- `psycopg2-binary` is already in `requirements.txt`, so enabling Postgres needs
  **no redeploy** — just add the secret and reboot.
- Switching backends does **not** migrate existing rows. If you have local
  SQLite trades you want to keep, re-enter them after switching (paper trades
  are usually short-lived, so this is rarely an issue).
- The same `DATABASE_URL` can later power background paper-trade alerts, since
  the GitHub Actions job could then read your open positions directly.
- Credentials live only in secrets / env — never in git.
