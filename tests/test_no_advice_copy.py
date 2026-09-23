"""CLAUDE.md rule 1 guard — no buy/sell instruction copy in dashboard UI strings.

Scans string literals (not comments) in dashboard/pages and dashboard/shared.
dashboard/shared/ai/ is exempt: its safety filter and persona legitimately
contain these phrases as patterns to block.
"""
import ast
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1] / "dashboard"
BANNED = re.compile(
    r"\b(buy (the )?dips?|buy now|sell now|avoid fresh|fresh (buys|longs)|"
    r"looks like a good buy|avoid buying|consider (buying|selling|exiting|trimming)|"
    r"don't add|hold existing|full long|short-bias|long-bias|go (long|short)|"
    r"buy quality|lock in profit)\b",
    re.I,
)


def _strings(path):
    """String literals excluding docstrings (code docs aren't UI copy)."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docs = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                docs.add(id(body[0].value))
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docs:
            yield node.lineno, node.value


def test_no_instruction_copy_in_ui_strings():
    hits = []
    for p in list((ROOT / "pages").glob("*.py")) + list((ROOT / "shared").glob("*.py")):
        for ln, s in _strings(p):
            # Skip docstring-length prose explaining the rule itself.
            if "rule 1" in s.lower():
                continue
            m = BANNED.search(s)
            if m:
                hits.append(f"{p.relative_to(ROOT)}:{ln}: {m.group(0)!r}")
    assert not hits, "Advice-style UI copy (CLAUDE.md rule 1):\n" + "\n".join(hits)
