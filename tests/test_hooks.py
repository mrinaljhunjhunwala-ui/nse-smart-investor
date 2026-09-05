"""
tests/test_hooks.py — safety tests for .claude/hooks/*

The hooks are part of the repo's safety net: block_sensitive.py guards
real-holdings / secrets from being edited by an agent, and lint_python.py
runs ruff on every Python edit. A future refactor could silently break
either one. These tests keep both honest.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
BLOCK_HOOK = REPO_ROOT / ".claude" / "hooks" / "block_sensitive.py"
LINT_HOOK = REPO_ROOT / ".claude" / "hooks" / "lint_python.py"


def _ruff_available_for_hook() -> bool:
    """The hook first tries `py -m ruff`, then falls back to `python -m ruff`.
    Mirror that here so the test skips only when neither resolver has ruff."""
    for interpreter in (["py"], ["python"]):
        try:
            result = subprocess.run(
                interpreter + ["-m", "ruff", "--version"],
                capture_output=True,
                text=True,
                timeout=15,
            )
            if result.returncode == 0:
                return True
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
    return False


_RUFF_OK = _ruff_available_for_hook()
_ruff_skip = pytest.mark.skipif(
    not _RUFF_OK,
    reason="ruff not installed for py/python launcher; skipping runtime lint tests",
)


def _run_hook(hook: Path, payload: dict) -> subprocess.CompletedProcess:
    """Invoke a hook script with a JSON payload on stdin. Returns the completed process."""
    return subprocess.run(
        [sys.executable, str(hook)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=30,
    )


# ── block_sensitive.py ────────────────────────────────────────────────────────

BLOCKED_PATHS = [
    "portfolio.csv",
    "trades.db",
    "dashboard/paper_trades.db",
    ".streamlit/secrets.toml",
    ".env",
    ".env.production",
    ".env.local",
    ".credentials",
    ".credentials.angel",
    "some/nested/paper_trades.db",
    "some/nested/data.sqlite",
    "any.sqlite3",
    "./portfolio.csv",
    "./.streamlit/secrets.toml",
]

ALLOWED_PATHS = [
    "dashboard/pages/04_analyze_stock.py",
    "dashboard/app.py",
    "analysis/score.py",
    "utils/telegram.py",
    "README.md",
    "requirements.txt",
    ".ruff",
    ".streamlit/config.toml",         # config, not secrets
    ".streamlit/secrets.toml.example", # example, not the real thing
    "portfolio.csv.example",           # example, not the real thing
    "docs/DEPLOYMENT.md",
]


@pytest.mark.parametrize("path", BLOCKED_PATHS)
def test_block_hook_denies_sensitive_paths(path):
    """Every entry in BLOCKED_PATHS must trigger exit code 2."""
    result = _run_hook(BLOCK_HOOK, {"tool_input": {"file_path": path}})
    assert result.returncode == 2, (
        f"'{path}' should be blocked but wasn't.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert "BLOCKED" in (result.stderr or ""), (
        f"Block message missing on stderr for '{path}'. Got: {result.stderr!r}"
    )


@pytest.mark.parametrize("path", ALLOWED_PATHS)
def test_block_hook_allows_safe_paths(path):
    """Every entry in ALLOWED_PATHS must pass through with exit code 0."""
    result = _run_hook(BLOCK_HOOK, {"tool_input": {"file_path": path}})
    assert result.returncode == 0, (
        f"'{path}' should be allowed but was blocked.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )


def test_block_hook_handles_malformed_payload():
    """A malformed payload should NOT block (fail-open) but should log to stderr."""
    result = subprocess.run(
        [sys.executable, str(BLOCK_HOOK)],
        input="not valid json",
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0
    assert "could not parse" in (result.stderr or "")


def test_block_hook_handles_empty_payload():
    """An empty payload should allow (nothing to check)."""
    result = _run_hook(BLOCK_HOOK, {})
    assert result.returncode == 0


def test_block_hook_handles_missing_file_path_key():
    """Payload with no file_path — nothing to check, allow."""
    result = _run_hook(BLOCK_HOOK, {"tool_input": {}})
    assert result.returncode == 0


# ── lint_python.py ────────────────────────────────────────────────────────────

def test_lint_hook_skips_non_python():
    """Non-.py files should exit 0 without invoking ruff."""
    result = _run_hook(LINT_HOOK, {"tool_input": {"file_path": "README.md"}})
    assert result.returncode == 0
    # Nothing about ruff should show up on stderr for a skipped file.
    assert "ruff findings" not in (result.stderr or "")


@_ruff_skip
def test_lint_hook_skips_venv_paths():
    """venv/cache paths should be skipped even if they end in .py."""
    for path in [
        ".venv/lib/site-packages/foo.py",
        "venv/lib/pkg.py",
        "src/__pycache__/mod.py",
        "build/lib/mod.py",
    ]:
        result = _run_hook(LINT_HOOK, {"tool_input": {"file_path": path}})
        assert result.returncode == 0, f"skip failed for {path}"
        assert "ruff findings" not in (result.stderr or "")


@_ruff_skip
def test_lint_hook_runs_ruff_on_clean_file(tmp_path):
    """A clean .py file should exit 0 with no findings printed."""
    clean = tmp_path / "clean.py"
    clean.write_text('"""A clean module."""\n\n\ndef add(a, b):\n    return a + b\n')
    result = _run_hook(LINT_HOOK, {"tool_input": {"file_path": str(clean)}})
    assert result.returncode == 0
    assert "ruff findings" not in (result.stderr or "")


@_ruff_skip
def test_lint_hook_surfaces_violations(tmp_path):
    """A file with a real violation should exit 0 (non-blocking) but print findings."""
    dirty = tmp_path / "dirty.py"
    # Two clear violations: unused import + trailing whitespace on the def line.
    dirty.write_text("import os   \ndef  bad( ):\n    return 1\n")
    result = _run_hook(LINT_HOOK, {"tool_input": {"file_path": str(dirty)}})
    # Non-blocking by design.
    assert result.returncode == 0
    # Findings must be surfaced so the agent sees them.
    assert "ruff findings" in (result.stderr or "")


def test_lint_hook_handles_missing_file_path():
    """No file_path in payload — nothing to lint, exit 0."""
    result = _run_hook(LINT_HOOK, {"tool_input": {}})
    assert result.returncode == 0


def test_lint_hook_handles_malformed_payload():
    """Malformed JSON should exit 0 (fail-open)."""
    result = subprocess.run(
        [sys.executable, str(LINT_HOOK)],
        input="totally not json",
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0
