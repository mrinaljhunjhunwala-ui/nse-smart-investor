"""
dashboard.shared.ai.client — OpenAI-compatible chat client for the co-pilot.

Default provider is Groq (`llama-3.3-70b-versatile`) because its free tier is
generous and fast. The client speaks OpenAI's `/v1/chat/completions` schema,
which means dropping OmniRoute (or any other OpenAI-compatible gateway) in
front later is a single base-URL flip — no code change.

Pure module: no Streamlit. `read_api_key()` looks in st.secrets *only* if
Streamlit is importable, and always falls back to environment variable — that
keeps this module usable from tests, scripts, and dev.py.

Graceful degradation: if no key is set, `is_available()` returns False and
`chat()` raises `CopilotUnavailable`, which the panel translates to a
"set GROQ_API_KEY in Space secrets" message rather than crashing the page.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Iterable

import requests  # already in requirements.txt; urllib fingerprint gets 403'd by Cloudflare


DEFAULT_BASE_URL = "https://api.groq.com/openai/v1"
# Groq's chat models turn over regularly. Confirmed live on this account
# 2026-09-02 by hitting /v1/models. `qwen/qwen3.8-27b` is the current chat
# default — fast, current-gen, strong at the structured-reasoning we want
# for stock analysis. Fallback candidates on the same key:
#   openai/gpt-oss-120b   (larger, slower, best reasoning)
#   openai/gpt-oss-20b    (smaller, cheapest)
#   groq/compound         (Groq's own flagship)
# Change here to swap the whole app; see analytics ideas in DEPLOY.md.
DEFAULT_MODEL = "qwen/qwen3.8-27b"
DEFAULT_TIMEOUT = 30.0


class CopilotUnavailable(RuntimeError):
    """Raised when the co-pilot cannot serve a request (missing key, provider down)."""


@dataclass
class Message:
    role: str  # "system" | "user" | "assistant"
    content: str


@dataclass
class ChatSettings:
    model: str = DEFAULT_MODEL
    base_url: str = DEFAULT_BASE_URL
    temperature: float = 0.3
    max_tokens: int = 800
    timeout: float = DEFAULT_TIMEOUT
    extra_headers: dict[str, str] = field(default_factory=dict)


def read_api_key() -> str | None:
    """Return the Groq API key or None. Prefers Streamlit secrets when available,
    falls back to the GROQ_API_KEY env var. Never raises."""
    # Env var first — cheap, no import cost.
    key = os.getenv("GROQ_API_KEY")
    if key:
        return key
    # Streamlit secrets, if streamlit is importable and secrets exist.
    try:
        import streamlit as st  # local import to keep this module pure
        try:
            return st.secrets["GROQ_API_KEY"]  # type: ignore[index]
        except (KeyError, FileNotFoundError, Exception):
            return None
    except ImportError:
        return None


def is_available() -> bool:
    """Cheap check the panel calls before rendering the chat input."""
    return bool(read_api_key())


def chat(
    messages: Iterable[Message],
    settings: ChatSettings | None = None,
    *,
    api_key: str | None = None,
) -> str:
    """Send a chat completion request and return the assistant text.

    Raises CopilotUnavailable on missing key, network failure, or non-200
    response. Callers should catch and translate to a UI-friendly message.
    """
    key = api_key or read_api_key()
    if not key:
        raise CopilotUnavailable(
            "GROQ_API_KEY is not set. Add it to .streamlit/secrets.toml locally "
            "or as a Repository secret in the Hugging Face Space settings."
        )

    settings = settings or ChatSettings()
    payload = {
        "model": settings.model,
        "temperature": settings.temperature,
        "max_tokens": settings.max_tokens,
        "messages": [{"role": m.role, "content": m.content} for m in messages],
    }
    # UA header matters: Groq is fronted by Cloudflare, which returns 403 (error
    # 1010) against Python's default urllib fingerprint. `requests` sends a
    # `python-requests/…` UA by default which also trips 1010 on some Groq
    # deployments — override with a browser-style UA for safety.
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (nse-smart-investor co-pilot)",
        "Accept": "application/json",
        **settings.extra_headers,
    }
    url = settings.base_url.rstrip("/") + "/chat/completions"

    try:
        resp = requests.post(
            url, headers=headers, data=json.dumps(payload), timeout=settings.timeout
        )
    except requests.exceptions.Timeout as e:
        raise CopilotUnavailable(f"Provider timeout after {settings.timeout}s") from e
    except requests.exceptions.ConnectionError as e:
        raise CopilotUnavailable(f"Provider unreachable: {e}") from e
    except requests.exceptions.RequestException as e:
        raise CopilotUnavailable(f"Provider error: {e}") from e

    if resp.status_code != 200:
        # Truncate to avoid leaking anything sensitive if the provider echoes
        # request context in the error body.
        body_preview = (resp.text or "")[:300]
        raise CopilotUnavailable(
            f"Provider returned HTTP {resp.status_code}: {body_preview}"
        )

    body = resp.text
    try:
        parsed: dict[str, Any] = json.loads(body)
        return parsed["choices"][0]["message"]["content"]
    except (KeyError, IndexError, json.JSONDecodeError) as e:
        raise CopilotUnavailable(
            f"Provider response was not in the expected schema: {e}. "
            f"First 200 chars of body: {body[:200]!r}"
        ) from e
