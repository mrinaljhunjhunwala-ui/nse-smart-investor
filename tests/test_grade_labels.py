"""Command Centre's pick-card grade badge must use analysis.score's grade bands."""
import ast
import pathlib

from analysis.score import GRADE_BANDS, _grade

_PAGE = pathlib.Path(__file__).resolve().parent.parent / "dashboard" / "pages" / "01_command_centre.py"


def _page_card_grade_tag():
    # The page runs Streamlit at import time, so pull out just the helper.
    tree = ast.parse(_PAGE.read_text(encoding="utf-8"))
    keep = [n for n in tree.body
            if (isinstance(n, ast.FunctionDef) and n.name == "_card_grade_tag")
            or (isinstance(n, ast.Assign) and any(getattr(t, "id", "") == "_CARD_GRADES" for t in n.targets))]
    ns = {"_grade_label": _grade}
    exec(compile(ast.Module(body=keep, type_ignores=[]), str(_PAGE), "exec"), ns)
    return ns["_card_grade_tag"]


def test_command_centre_grade_badge_matches_score_grade_at_band_edges():
    tag = _page_card_grade_tag()
    edges = [s for cut, _ in GRADE_BANDS for s in (cut - 0.01, cut, cut + 0.01)] + [0, 90]
    assert all(tag(s) == (_grade(s) if _grade(s) in ("A+", "A", "B") else "") for s in edges)
