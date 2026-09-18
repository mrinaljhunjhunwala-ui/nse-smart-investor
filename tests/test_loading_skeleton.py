"""tests/test_loading_skeleton.py — F6 skeleton helper contract."""
from __future__ import annotations

import pytest

from dashboard.shared.ui_components import loading_skeleton


@pytest.mark.parametrize("kind", ["card", "hero", "chart", "table", "text"])
def test_skeleton_returns_html_string(kind):
    html = loading_skeleton(kind=kind)
    assert isinstance(html, str)
    assert html.strip().startswith("<div")
    # Must use the shared shimmer class so design.py's @keyframes drive it.
    assert "cc-skel" in html


def test_skeleton_count_repeats_shape():
    one = loading_skeleton(kind="card", count=1)
    three = loading_skeleton(kind="card", count=3)
    assert three.count("cc-skel-card") == 3 * one.count("cc-skel-card")


def test_skeleton_unknown_kind_falls_back_to_card():
    """Robust to typos — an unknown kind should render *something*, not crash."""
    html = loading_skeleton(kind="does-not-exist")
    assert "cc-skel-card" in html


def test_skeleton_count_clamps_below_one():
    """count=0 or negative should still return at least one shape."""
    for c in (0, -3):
        html = loading_skeleton(kind="card", count=c)
        assert "cc-skel-card" in html


def test_skeleton_hero_has_four_tiles():
    """The hero shape mirrors the verdict-card 4-tile grid so it previews
    the real content's shape, not just a generic block."""
    html = loading_skeleton(kind="hero")
    # Four tile <div>s inside the flex row
    tile_count = html.count('style="flex:1')
    assert tile_count == 4
