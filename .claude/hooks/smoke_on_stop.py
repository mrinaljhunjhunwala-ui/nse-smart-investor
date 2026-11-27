"""
.claude/hooks/smoke_on_stop.py: Stop hook that runs the page-smoke tests for
dashboard files changed in the working tree (CLAUDE.md "Editing discipline").

- dashboard/pages/NN_x.py      -> that page's smoke case
- dashboard/views/<name>.py    -> the page(s) that import the view
- dashboard/shared/<mod>.py    -> the page(s) that import the module
- dashboard/app.py             -> the whole smoke suite

Only targeted cases run (laptop-heat rule: one heavy job). The same diff is
never smoked twice: a hash of it is kept in the git dir. On failure, exit 2
feeds the test tail back to Claude so it fixes the page before finishing.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path


def _git(*args: str, cwd: Path) -> str:
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=30)
    return r.stdout if r.returncode == 0 else ""


def stems_for(changed: list[str], root: Path) -> list[str] | None:
    """Smoke -k stems for the changed paths; None means run the full suite."""
    pages = sorted((root / "dashboard" / "pages").glob("[0-9][0-9]_*.py"))
    stems: set[str] = set()
    for c in changed:
        c = c.replace("\\", "/")
        if c == "dashboard/app.py":
            return None
        m = re.fullmatch(r"dashboard/pages/(\d\d_\w+)\.py", c)
        if m:
            stems.add(m.group(1))
            continue
        m = re.fullmatch(r"dashboard/(views|shared)/(?:\w+/)*(\w+)\.py", c)
        if not m or m.group(2) == "__init__":
            continue
        mod = re.escape(m.group(2))
        pkg = m.group(1)
        pat = re.compile(rf"\b{pkg}(?:\.\w+)*\.{mod}\b|\bfrom dashboard\.{pkg}(?:\.\w+)* import [^\n]*\b{mod}\b")
        for p in pages:
            if pat.search(p.read_text(encoding="utf-8", errors="replace")):
                stems.add(p.stem)
    return sorted(stems)


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        payload = {}
    if payload.get("stop_hook_active"):  # already continuing because of this hook
        return 0
    root = Path(_git("rev-parse", "--show-toplevel", cwd=Path.cwd()).strip() or ".")
    names = (_git("diff", "--name-only", "HEAD", "--", "dashboard", cwd=root)
             + _git("ls-files", "--others", "--exclude-standard", "--", "dashboard", cwd=root))
    changed = [ln for ln in names.splitlines() if ln.endswith(".py")]
    if not changed:
        return 0
    digest = hashlib.sha1(_git("diff", "HEAD", "--", *changed, cwd=root).encode()).hexdigest()
    mark = Path(_git("rev-parse", "--absolute-git-dir", cwd=root).strip() or root) / "smoke_last"
    if mark.exists() and mark.read_text().strip() == digest:
        return 0
    stems = stems_for(changed, root)
    if stems == []:
        mark.write_text(digest)
        return 0
    cmd = [sys.executable, "-m", "pytest", "tests/test_pages_smoke.py", "-q", "-p", "no:cacheprovider", "-x"]
    if stems:
        cmd += ["-k", " or ".join(stems)]
    tmp = Path("D:/Kashti Claude/_tmp")  # owner rule: pytest temp on D:, not C:
    if tmp.is_dir():
        cmd += ["--basetemp", str(tmp / "pytest-smoke-hook")]
    env = dict(os.environ, PYTHONUTF8="1")
    r = subprocess.run(cmd, cwd=root, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", env=env, timeout=900)
    if r.returncode == 0:
        mark.write_text(digest)
        return 0
    tail = "\n".join((r.stdout + r.stderr).strip().splitlines()[-25:])
    print(f"page-smoke failed for {', '.join(stems) if stems else 'all pages'} "
          f"({' '.join(cmd[3:])}). Fix the page before finishing:\n{tail}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
