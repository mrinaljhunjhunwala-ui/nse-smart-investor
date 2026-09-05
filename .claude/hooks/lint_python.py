"""
.claude/hooks/lint_python.py — PostToolUse ruff check

Runs ruff (config: repo-root pyproject.toml → [tool.ruff], max-line 120,
ignores E203/W503) on every .py file just edited or written. Silent on pass; prints violations to
stderr on fail so Claude sees them and can self-correct in the same turn.

Non-blocking by design: exit 0 always. ruff output is surfaced via stderr
whether it passed or failed, but the tool call is never rejected. The point
is a fast feedback loop, not a gate — CI still enforces the bar.

Runs at most once per hook invocation even for MultiEdit (which reports a
single file_path).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import PureWindowsPath


def _norm(p: str) -> str:
    return PureWindowsPath(p).as_posix()


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        return 0

    tool_input = payload.get("tool_input") or {}
    path = tool_input.get("file_path") or tool_input.get("path")
    if not path:
        return 0

    if not str(path).endswith(".py"):
        return 0

    # Skip venvs / caches / build artefacts. Prepend "/" so a leading segment
    # like ".venv/lib/…" matches the "/.venv/" needle the same way as
    # "src/.venv/lib/…" would.
    lower = "/" + _norm(str(path)).lower()
    for skip in ("/.venv/", "/venv/", "/__pycache__/", "/build/", "/dist/", "/.mypy_cache/"):
        if skip in lower:
            return 0

    # ruff needs an explicit "check" subcommand — `ruff <path>` is a usage
    # error, unlike flake8 which was single-verb.
    ruff_args = ["-m", "ruff", "check", str(path)]
    try:
        result = subprocess.run(
            ["py"] + ruff_args,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except FileNotFoundError:
        # `py` launcher missing; try `python`.
        try:
            result = subprocess.run(
                ["python"] + ruff_args,
                capture_output=True,
                text=True,
                timeout=30,
            )
        except Exception as e:
            print(f"lint_python: could not invoke ruff ({e}).", file=sys.stderr)
            return 0
    except subprocess.TimeoutExpired:
        print("lint_python: ruff timed out after 30s.", file=sys.stderr)
        return 0

    if result.returncode != 0:
        # Print the ruff report so Claude sees it and can fix on the next turn.
        out = (result.stdout or "").strip()
        err = (result.stderr or "").strip()
        blob = "\n".join(x for x in (out, err) if x)
        print(f"ruff findings on {path}:\n{blob}", file=sys.stderr)

    return 0  # never block — surface only


if __name__ == "__main__":
    sys.exit(main())
