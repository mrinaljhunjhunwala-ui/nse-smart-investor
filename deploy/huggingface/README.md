---
title: NSE Smart Investor
emoji: 📈
colorFrom: yellow
colorTo: indigo
sdk: streamlit
sdk_version: "1.38.0"
app_file: dashboard/app.py
pinned: true
license: mit
short_description: AI-powered NSE/BSE equity dashboard — composite scoring, TQS, sector-aware fundamentals, paper trading.
---

# NSE Smart Investor — Hugging Face Space

This is the Hugging Face Spaces deployment mirror of
[github.com/mrinaljhunjhunwala-ui/nse-smart-investor](https://github.com/mrinaljhunjhunwala-ui/nse-smart-investor).

The full README (features, screenshots, methodology) lives in the GitHub repo. This file exists
only so Hugging Face Spaces has the YAML frontmatter it needs to boot the Streamlit runtime.

**Space status:** private • always-on • CPU-only.

## Secrets set in Space Settings → Repository secrets

| Key | Purpose | Required? |
|---|---|---|
| `DATABASE_URL` | Postgres URL for paper-trade / calibration persistence | Optional — app falls back to SQLite (ephemeral on Spaces) |
| `GROQ_API_KEY` | Free-tier Groq key for the in-app AI co-pilot (task B) | Optional until AI panel is wired |
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` | Alert delivery | Optional |

## App entry point

Streamlit runs `dashboard/app.py`. The `app_file` frontmatter above already points at it, so no
Procfile / Dockerfile is needed.
