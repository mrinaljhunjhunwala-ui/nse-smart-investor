"""
.claude/hooks/block_page_hex.py — PostToolUse hex-literal linter for pages.

Ships Task 1.6 from tasks/todo.md. Enforces the "no raw hex in
dashboard/pages/**/*.py" rule established by the 2026-09-01 UI audit
(Cluster B) and re-affirmed by Sprint 1.1 (design tokens now live on :root
in dashboard/shared/design.py).

WHAT IT DOES
Runs on every Edit/Write/MultiEdit that touches a file matching
dashboard/pages/*.py. Scans line by line for CSS-style hex literals
(#RGB / #RGBA / #RRGGBB / #RRGGBBAA) — including those INSIDE strings,
which is exactly the pattern the audit flagged (pages inline hex in
f-string HTML like `f'<div style="background:#0d1526">'`).

ESCAPE HATCHES
1. Any `#` inside a Python block comment (lstrip starts with `#`) is
   ignored — that's a real code comment, not inline styling.
2. `# noqa: hex` anywhere on the line silences that line entirely.

WHY POSTTOOLUSE NOT PRECOMMIT
The Claude hook already runs on every edit; no separate git hook to
opt into. Same delivery model as lint_python.py. Non-blocking: exit 0
always, findings surface to stderr for Claude to fix on the next turn.
CI can add a mirror check later if drift ever slips past.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path, PureWindowsPath

# Match CSS hex literals only: #RGB, #RGBA, #RRGGBB, #RRGGBBAA. Length
# constraints on the hex run stop matches like `#1234567` (7 chars, not a
# valid CSS length) or `#f` (too short) from firing. Word-boundary at the
# end keeps `#abc0123def` from matching as `#abc012`.
_HEX_RE = re.compile(r"#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})\b")


def _norm(p: str) -> str:
    return PureWindowsPath(p).as_posix().lower()


def _is_page_file(path: str) -> bool:
    n = _norm(str(path))
    return n.endswith(".py") and "/dashboard/pages/" in ("/" + n)


def _find_hex_violations(path: Path) -> list[tuple[int, str, str]]:
    """Return (lineno, hex_literal, offending_snippet) triples."""
    try:
        src = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    hits: list[tuple[int, str, str]] = []
    for lineno, raw in enumerate(src.splitlines(), start=1):
        stripped = raw.lstrip()
        # Whole-line block comment — user's code intent, not inline styling.
        if stripped.startswith("#"):
            continue
        if "# noqa: hex" in raw:
            continue
        m = _HEX_RE.search(raw)
        if m:
            snippet = raw.strip()
            if len(snippet) > 80:
                # Truncate around the match for readable output.
                start = max(0, m.start() - 30)
                end   = min(len(raw), m.end() + 30)
                snippet = "…" + raw[start:end].strip() + "…"
            hits.append((lineno, m.group(0), snippet))
    return hits


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        return 0

    tool_input = payload.get("tool_input") or {}
    path = tool_input.get("file_path") or tool_input.get("path")
    if not path or not _is_page_file(path):
        return 0

    p = Path(str(path))
    if not p.exists():
        return 0

    hits = _find_hex_violations(p)
    if hits:
        rel = _norm(str(path))
        print(f"page-hex-lint: {len(hits)} raw hex literal(s) in {rel} — "
              f"use var(--token) from dashboard/shared/design.py",
              file=sys.stderr)
        # Cap the report at 10 findings; big files can have dozens.
        for ln, hex_lit, snippet in hits[:10]:
            print(f"  {rel}:{ln}  {hex_lit}  ->  {snippet}", file=sys.stderr)
        if len(hits) > 10:
            print(f"  … and {len(hits) - 10} more", file=sys.stderr)
        print(f"  (add '# noqa: hex' on a line to silence a false-positive)",
              file=sys.stderr)
    return 0   # never block — surface only, same as lint_python.py


if __name__ == "__main__":
    sys.exit(main())
