"""Colour tokens: single source (dashboard/shared/tokens.py) consumed everywhere."""
import os
import re
import sqlite3

from dashboard.shared import tokens
from dashboard.shared.tokens import COLORS, hex_to_rgb

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_tokens_are_hex():
    for k, v in COLORS.items():
        assert re.fullmatch(r"#[0-9a-f]{6}", v), (k, v)


def test_hex_to_rgb_and_rgba():
    assert hex_to_rgb(COLORS["bull"]) == (22, 199, 132)
    assert tokens.rgba("bear", 0.5) == "rgba(255,77,77,0.5)"


def test_css_vars_cover_every_token():
    css = tokens.css_vars()
    for k, v in COLORS.items():
        assert f"--{k}: {v};" in css


def test_plot_colors_come_from_tokens():
    from dashboard.shared.chart_helpers import PLOT_COLORS, diverging_colors
    for k, v in PLOT_COLORS.items():
        assert v == COLORS[k]
    pos, neg = diverging_colors([1.0, -1.0])
    assert pos.startswith("rgba(%d,%d,%d," % hex_to_rgb(COLORS["bull"]))
    assert neg.startswith("rgba(%d,%d,%d," % hex_to_rgb(COLORS["bear"]))


def test_table_styles_use_tokens():
    from dashboard.shared import table_styles as ts
    assert ts._BULL == COLORS["bull"] and ts._BEAR == COLORS["bear"]
    assert ts._BULL_RGB == hex_to_rgb(COLORS["bull"])


def test_design_root_is_built_from_tokens():
    src = open(os.path.join(_ROOT, "dashboard", "shared", "design.py"), encoding="utf-8").read()
    assert "/*__COLOR_TOKENS__*/" in src
    for v in COLORS.values():
        assert re.search(r"--[\w-]+:\s+%s;" % v, src) is None, v


def test_tqs_page_has_no_raw_hex():
    src = open(os.path.join(_ROOT, "dashboard", "pages", "18_tqs_scanner.py"), encoding="utf-8").read()
    assert re.search(r"#[0-9a-fA-F]{6}\b", src) is None


def test_no_deprecated_components_html_in_shared():
    d = os.path.join(_ROOT, "dashboard", "shared")
    for f in os.listdir(d):
        if f.endswith(".py"):
            src = open(os.path.join(d, f), encoding="utf-8").read()
            assert "components.v1 as" not in src, f
            assert "components.html(" not in src, f


def test_read_sql_df_matches_shape():
    from trade_store import read_sql_df
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE t (a INTEGER, b TEXT)")
    conn.executemany("INSERT INTO t VALUES (?, ?)", [(1, "x"), (2, "y")])
    df = read_sql_df("SELECT * FROM t WHERE a >= ?", conn, params=(2,))
    assert list(df.columns) == ["a", "b"] and df.to_dict("records") == [{"a": 2, "b": "y"}]
    empty = read_sql_df("SELECT * FROM t WHERE a > 99", conn)
    assert list(empty.columns) == ["a", "b"] and empty.empty
