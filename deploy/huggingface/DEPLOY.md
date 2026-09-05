# Deploying NSE Smart Investor to Hugging Face Spaces

**Why HF Spaces over Streamlit Community Cloud:** 16 GB RAM vs 1 GB, no idle
sleep (your 15-min scan cadence keeps ticking), private repos on the free tier.

Total setup time: ~15 minutes. Cost: ₹0.

---

## Step 1 — Create the Space (2 min, in browser)

1. Sign in / sign up at https://huggingface.co (free, email is enough).
2. Go to https://huggingface.co/new-space
3. Fill:
   - **Owner:** your username
   - **Space name:** `nse-smart-investor` (or anything)
   - **License:** MIT
   - **SDK:** **Streamlit** (this is the key choice)
   - **Streamlit template:** blank
   - **Hardware:** CPU basic (free)
   - **Visibility:** **Private** (so your portfolio, trades, and secrets stay yours)
4. Click **Create Space**.

HF gives you a git URL that looks like:
`https://huggingface.co/spaces/<your-username>/nse-smart-investor`

## Step 2 — Add the Space as a second git remote (2 min, one-time)

From this repo's directory:

```bash
git remote add hf https://huggingface.co/spaces/<your-username>/nse-smart-investor
```

Verify both remotes exist:

```bash
git remote -v
```

You should see `origin` (GitHub) and `hf` (Hugging Face).

## Step 3 — Wire the HF-specific files into the repo root (5 min)

HF Spaces reads three files from the **repo root**: `README.md`, `packages.txt`, and
`requirements.txt`. We already have `requirements.txt`. The other two live in
`deploy/huggingface/` and are copied to the root **only on the HF branch** — the GitHub
`main` branch is left untouched (so Streamlit Cloud keeps working, and the existing
GitHub README stays intact).

```bash
git checkout -b hf-deploy
cp deploy/huggingface/README.md README.md
cp deploy/huggingface/packages.txt packages.txt
git add README.md packages.txt
git commit -m "hf-deploy: HF Spaces frontmatter + apt package list"
```

## Step 4 — Push to HF (3 min)

HF asks for a **user access token** as the git password (not your account password).
Create one at https://huggingface.co/settings/tokens → **New token** → role **Write** →
copy it.

```bash
git push hf hf-deploy:main
```

When prompted:
- Username: your HF username
- Password: paste the write-token you just created

HF starts building the Space immediately. Watch the log in the browser at your Space URL
→ **Logs** tab. First build takes 4–6 minutes (installs pandas, plotly, xgboost, etc.).

## Step 5 — Add secrets in the Space UI (3 min)

In the Space page → **Settings** → **Repository secrets** → **New secret**:

| Add now | Add later when you wire it |
|---|---|
| — | `GROQ_API_KEY` (get free at https://console.groq.com — Task B) |
| `DATABASE_URL` (Supabase Postgres, free) — only if you want durable paper-trade / calibration data. Without it the app boots on SQLite and forgets on every rebuild. | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` (if you want alerts) |

**Free Postgres in 3 min if you want persistence:**
1. Sign up at https://supabase.com (free, 500 MB Postgres)
2. Create a project → wait ~1 min for provisioning
3. Project → **Settings** → **Database** → **Connection string** → **URI** → copy
4. Replace `[YOUR-PASSWORD]` in the string with the DB password you set
5. Paste as `DATABASE_URL` in the HF Space secrets

## Step 6 — Update workflow, going forward

Two branches, two purposes:
- `main` on GitHub — dev + Streamlit Community Cloud (existing)
- `hf-deploy` on HF — the deployed Space

To ship a new version to HF:

```bash
git checkout hf-deploy
git merge main            # pull in your dev changes
git push hf hf-deploy:main
```

HF rebuilds and redeploys automatically on push.

---

## Troubleshooting

- **Build fails on `psycopg2-binary`**: hasn't happened on HF (wheels exist for Python 3.10/3.11).
  If it ever does, uncomment the `libpq-dev` line in `packages.txt`.
- **Space crashes with `RuntimeError: Bad magic number`**: means Python version drift. In
  Space Settings → **Variables** → set `PYTHON_VERSION=3.11`.
- **App boots but shows "storage unreachable"**: `DATABASE_URL` is set but wrong. Re-check the
  URI (must include `?sslmode=require` for Supabase) and click **Restart** on the Space.
- **App sleeps anyway**: Only Streamlit Community Cloud sleeps. HF Spaces on the free CPU tier
  stay warm as long as your account is active. If you see slowness after long idle, the container
  is just paging back in — first request is slower, subsequent ones normal.

## When to add OmniRoute

Skip it for v1. Wire the AI panel directly to Groq (single free key). Only when you hit Groq's
daily limits (~14,400 req/day — you won't for a personal app) drop OmniRoute in front. The app
code doesn't change: both speak OpenAI-compatible API on `/v1/chat/completions`.
