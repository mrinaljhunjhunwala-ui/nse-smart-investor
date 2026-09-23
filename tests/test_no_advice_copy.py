"""CLAUDE.md rule 1 guard — no buy/sell instruction copy in dashboard UI strings.

Scans string literals (plain constants AND the literal parts of f-strings,
excluding docstrings and comments) in dashboard/pages and dashboard/shared.
dashboard/shared/ai/ is exempt: its safety filter and persona legitimately
contain these phrases as patterns to block.

Also asserts that FinalVerdict ``.verdict`` / CompositeScore ``.action``
values are never interpolated raw into f-strings — they must go through the
display mappers in dashboard/shared/trade_utils.py.
"""
import ast
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1] / "dashboard"
BANNED = re.compile(
    r"\b(buy (the )?dips?|buy now|sell now|avoid fresh|fresh (buys|longs)|"
    r"looks like a good buy|avoid buying|consider (buying|selling|exiting|trimming)|"
    r"don't add|hold existing|full long|short-bias|long-bias|go (long|short)|"
    r"buy quality|lock in profit|reduce (position|exposure)|consider hedg\w*|"
    r"keep stops|buy candidates|sell\s*/\s*avoid|(strong )?buy setups|enter with|"
    r"exit immediately|full position|only take trades)\b",
    re.I,
)

# TODO(advice-copy): files owned by other agents in the fix-advice-labels-scale
# sweep. Remove each entry once its owner fixes the flagged copy.
# Each entry: path relative to dashboard/ -> the phrase(s) it currently trips.
ALLOWLIST_COPY: set[str] = {
    "pages/22_fii_dii_flows.py",   # TODO(advice-copy): "keep stops tight" (~line 151)
}
ALLOWLIST_MAPPER: set[str] = {
    "shared/checklist_ui.py",      # TODO(advice-copy): raw {result.verdict} incl. "Consider entry."
}

def _files():
    return list((ROOT / "pages").glob("*.py")) + list((ROOT / "shared").glob("*.py"))


def _docstring_ids(tree):
    docs = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                docs.add(id(body[0].value))
    return docs


def _strings(path):
    """String literals (incl. f-string literal parts), excluding docstrings."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docs = _docstring_ids(tree)
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docs:
            yield node.lineno, node.value
        elif isinstance(node, ast.JoinedStr):
            # Join adjacent literal parts so phrases split across pieces still match.
            text = "".join(v.value if isinstance(v, ast.Constant) else "{}" for v in node.values)
            yield node.lineno, text


def test_no_instruction_copy_in_ui_strings():
    hits = []
    for p in _files():
        rel = str(p.relative_to(ROOT)).replace("\\", "/")
        if rel in ALLOWLIST_COPY:
            continue
        for ln, s in _strings(p):
            m = BANNED.search(s)
            if m:
                hits.append(f"{rel}:{ln}: {m.group(0)!r}")
    assert not hits, "Advice-style UI copy (CLAUDE.md rule 1):\n" + "\n".join(hits)


def _raw_label_interpolations(path):
    """f-string holes that are a bare ``<x>.verdict`` / ``<x>.action`` attribute
    or ``<x>["action"]`` subscript (i.e. not wrapped in a display mapper)."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.JoinedStr):
            continue
        for v in node.values:
            if not isinstance(v, ast.FormattedValue):
                continue
            e = v.value
            # Thesis verdicts are already descriptive (Strong Negative ..
            # Strong Positive — analysis/thesis/thesis_models.VERDICTS).
            if "thesis" in ast.unparse(e):
                continue
            if isinstance(e, ast.Attribute) and e.attr in ("verdict", "action"):
                yield node.lineno, ast.unparse(e)
            elif (isinstance(e, ast.Subscript) and isinstance(e.slice, ast.Constant)
                  and e.slice.value in ("verdict", "action")):
                yield node.lineno, ast.unparse(e)


def test_verdict_and_action_rendered_through_display_mappers():
    hits = []
    for p in _files():
        rel = str(p.relative_to(ROOT)).replace("\\", "/")
        if rel in ALLOWLIST_MAPPER:
            continue
        for ln, expr in _raw_label_interpolations(p):
            hits.append(f"{rel}:{ln}: {{{expr}}}")
    assert not hits, (
        "Raw verdict/action interpolated into UI f-string — wrap in "
        "_display_label()/verdict_display_label():\n" + "\n".join(hits))


def test_display_mappers_cover_every_engine_value():
    from analysis.final_verdict import VERDICTS
    from dashboard.shared.trade_utils import _display_label, verdict_display_label
    for v in VERDICTS:
        out = verdict_display_label(v)
        assert out != v and not re.search(r"\b(buy|sell|avoid)\b", out, re.I), (v, out)
    for a in ("STRONG BUY", "BUY", "WATCHLIST", "HOLD", "CAUTION", "EXIT", "SELL"):
        out = _display_label(a)
        assert not re.search(r"\b(buy|sell|exit|avoid)\b", out, re.I), (a, out)
