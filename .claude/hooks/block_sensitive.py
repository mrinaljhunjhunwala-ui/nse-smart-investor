"""
.claude/hooks/block_sensitive.py — PreToolUse guard

Blocks Edit/Write/MultiEdit on files that must not be touched by an agent:

  * portfolio.csv                    — real holdings; risk of accidental commit
  * trades.db, *.db, *.sqlite        — user paper-trade / persistence data
  * .streamlit/secrets.toml          — API keys, DB URL, tokens
  * .env, .env.*                     — environment secrets
  * .credentials, .credentials.*     — OAuth / broker credentials

Exit code 2 blocks the tool call and prints the reason to Claude.
Exit code 0 lets the call proceed.

The hook is intentionally strict: if you *want* to edit one of these files,
temporarily disable the hook in .claude/settings.json rather than loosening
the deny list here. That way the guard rail is never quietly weakened.
"""
from __future__ import annotations

import json
import sys
from pathlib import PurePosixPath, PureWindowsPath


DENY_EXACT = {
    "portfolio.csv",
    "trades.db",
    "dashboard/paper_trades.db",
    ".streamlit/secrets.toml",
    ".env",
    ".credentials",
}
DENY_SUFFIX = (".db", ".sqlite", ".sqlite3")
DENY_PREFIX = (".env.", ".credentials.")


def _normalise(path: str) -> str:
    """Return a forward-slash, project-relative-ish string for matching."""
    if not path:
        return ""
    # PureWindowsPath handles both slash styles; convert to posix form.
    p = PureWindowsPath(path).as_posix()
    # Strip a leading "./" as a token — never with lstrip, which would eat the
    # leading dot of a name like ".env.production" and defeat the deny-prefix.
    if p.startswith("./"):
        p = p[2:]
    return p


def _tail(path: str, n: int) -> str:
    """Return the last n path segments of `path`, for suffix-match on absolute paths."""
    parts = PurePosixPath(path).parts
    return "/".join(parts[-n:]) if parts else path


def _matches(path: str) -> str | None:
    if not path:
        return None
    p = _normalise(path)
    basename = PurePosixPath(p).name
    # exact matches (compare basename AND last-two segments so both
    # "trades.db" and "some/nested/trades.db" hit)
    for deny in DENY_EXACT:
        if p.endswith(deny) or basename == PurePosixPath(deny).name:
            return deny
    for suf in DENY_SUFFIX:
        if p.endswith(suf):
            return f"*{suf}"
    for pre in DENY_PREFIX:
        if basename.startswith(pre):
            return f"{pre}*"
    return None


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        # Malformed payload — do not block, but note it so Claude can surface it.
        print("block_sensitive: could not parse hook payload; allowing.", file=sys.stderr)
        return 0

    tool_input = payload.get("tool_input") or {}
    # Edit/Write use `file_path`; MultiEdit uses `file_path` with a `edits` list.
    candidates: list[str] = []
    if "file_path" in tool_input:
        candidates.append(str(tool_input["file_path"]))
    # Defensive: some MCP wrappers might pass `path` instead.
    if "path" in tool_input:
        candidates.append(str(tool_input["path"]))

    for cand in candidates:
        hit = _matches(cand)
        if hit:
            print(
                f"BLOCKED: '{cand}' matches deny rule '{hit}'.\n"
                "This file is protected by .claude/hooks/block_sensitive.py "
                "(real holdings / user data / secrets). "
                "Edit it yourself in your editor, or temporarily disable the hook "
                "in .claude/settings.json if this edit is intentional.",
                file=sys.stderr,
            )
            return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
