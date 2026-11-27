"""
.claude/hooks/check_raw_html.py: PostToolUse guard for unescaped values in raw HTML.

The 2026-11 security audit found the same bug four times: an f-string puts a
stored or feed value into markup that is rendered with unsafe_allow_html=True,
with no html.escape. This hook looks only at lines the edit ADDED (compared with
git HEAD) in dashboard/ files that render raw HTML, and flags f-string fields
inside markup that are not escaped or plainly numeric.

Exit 2 so Claude sees the warning (the edit has already happened; nothing is
blocked). Silence a reviewed line with `# noqa: html`.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path, PureWindowsPath

# A {field} inside an f-string; the field's expression is group 1.
_FIELD_RE = re.compile(r"(?<!\{)\{([^{}]+)\}(?!\})")
# Values that are safe without escaping: escaped calls, numbers, CSS tokens.
_SAFE_RE = re.compile(
    r"escape\(|_h\(|_esc\(|esc\(|:[<>^]?[,.+\-0-9]|:%|int\(|float\(|len\(|round\(|"
    r"_col\b|_bg\b|color|_cls\b|_tone\b|_pct\b|_fmt\(|fmt_|_TK\[|COLORS|var\(--|\b_?(n|i|pct|score|qty)\b"
)


# Values that can carry user/store/feed text: lookups, attributes and these names.
_RISKY_RE = re.compile(
    r"\[|\.get\(|\.\w+\s*$|\b\w*(ticker|sym|symbol|name|label|account|title|headline|note|notes|text|"
    r"reason|source|publisher|link|url|msg|message|desc|question|answer|query)\w*\b", re.I
)


def _rel(path: str) -> str:
    return PureWindowsPath(path).as_posix()


def _in_scope(path: str) -> bool:
    n = "/" + _rel(path).lower()
    return n.endswith(".py") and "/dashboard/" in n


def _head_lines(path: Path) -> set[str]:
    try:
        root = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=path.parent,
                              capture_output=True, text=True, timeout=10).stdout.strip()
        rel = path.resolve().relative_to(Path(root).resolve()).as_posix()
        old = subprocess.run(["git", "show", f"HEAD:{rel}"], cwd=root,
                             capture_output=True, text=True, encoding="utf-8", timeout=10)
        return set(old.stdout.splitlines()) if old.returncode == 0 else set()
    except Exception:
        return set()


def find_issues(src: str, old: set[str]) -> list[tuple[int, str]]:
    """(lineno, line) for added lines that interpolate an unescaped value into markup."""
    if "unsafe_allow_html" not in src and "st.html(" not in src:
        return []
    hits = []
    for no, line in enumerate(src.splitlines(), start=1):
        if line in old or "# noqa: html" in line:
            continue
        s = line.strip()
        if s.startswith("#") or "<" not in s or not re.search(r"\bf['\"]", s):
            continue
        bad = [e for e in _FIELD_RE.findall(s) if _RISKY_RE.search(e) and not _SAFE_RE.search(e)]
        if bad:
            hits.append((no, s if len(s) <= 110 else s[:107] + "..."))
    return hits


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        return 0
    ti = payload.get("tool_input") or {}
    path = ti.get("file_path") or ti.get("path")
    if not path or not _in_scope(path):
        return 0
    p = Path(str(path))
    if not p.exists():
        return 0
    hits = find_issues(p.read_text(encoding="utf-8", errors="replace"), _head_lines(p))
    if not hits:
        return 0
    rel = _rel(str(path))
    print(f"raw-html-check: {len(hits)} new line(s) in {rel} put an f-string value into HTML "
          "without html.escape. If it reaches unsafe_allow_html and the value can come from a "
          "user, the store or a feed, escape it:", file=sys.stderr)
    for no, s in hits[:8]:
        print(f"  {rel}:{no}  {s}", file=sys.stderr)
    print("  (numbers and CSS tokens are fine; add '# noqa: html' after review)", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
