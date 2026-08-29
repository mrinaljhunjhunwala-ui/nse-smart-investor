"""tests/test_syntax_parses.py — belt-and-braces guard against SyntaxErrors.

Why this file exists
────────────────────
Commit 4abaf90 shipped a dangling `@st.fragment(run_every=20)` decorator above
an `import` block in dashboard/pages/02_command_centre.py. That is invalid
Python — ast.parse rejects it — and it crashed the deployed Streamlit Cloud
app with "SyntaxError: invalid syntax" the moment the page tried to load.

The local page-smoke test still passed the whole time. streamlit-testing's
AppTest.from_file() swallowed the startup SyntaxError as a silent
"no-exception-on-the-AppTest.exception-list" — the same failure mode as
loading a file at the ast.parse layer being invisible to the compile layer
above it. That gap is why the bug shipped.

This test closes the gap directly: iterate every .py file in the repo,
ast.parse each one, fail if ANY file doesn't parse. Runs in ~0.5s, needs
zero network, zero Streamlit, zero anything. If a future commit introduces
a syntax error the deployed app can't survive, CI catches it BEFORE it
reaches Streamlit Cloud.

Also catches the specific U+FEFF (UTF-8 BOM) at start of a .py file case
that Python's import machinery tolerates but ast.parse rejects — the
research/__init__.py hotfix was for exactly this.
"""
from __future__ import annotations

import ast
import os

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_EXCLUDE_DIRS = {".venv", ".git", "__pycache__", ".pytest_cache",
                 ".mypy_cache", ".ruff_cache", "build", "dist"}


def _iter_py_files():
    for dirpath, dirnames, files in os.walk(_ROOT):
        # Skip well-known non-source directories in-place so os.walk doesn't
        # descend into them (huge speedup on repos with a checked-in venv).
        dirnames[:] = [d for d in dirnames if d not in _EXCLUDE_DIRS]
        for f in files:
            if f.endswith(".py"):
                yield os.path.join(dirpath, f)


def _relative(path: str) -> str:
    return os.path.relpath(path, _ROOT).replace(os.sep, "/")


_PY_FILES = sorted(_iter_py_files())


@pytest.mark.parametrize("path", _PY_FILES, ids=[_relative(p) for p in _PY_FILES])
def test_file_parses_with_ast(path: str):
    """Every tracked .py file must be ast.parse-able. Catches: dangling
    decorators, unclosed brackets, invalid syntax, top-of-file BOMs."""
    with open(path, encoding="utf-8") as f:
        src = f.read()
    try:
        ast.parse(src, filename=path)
    except SyntaxError as e:
        pytest.fail(
            f"{_relative(path)}:{e.lineno}:{e.offset} — {e.msg}\n"
            f"    (This exact failure mode — a dangling @st.fragment decorator "
            f"above an import block — crashed the Streamlit Cloud deploy of "
            f"commit 4abaf90 while the page smoke test silently passed. This "
            f"test exists to make sure that class of bug fails HERE and not "
            f"in production.)"
        )
