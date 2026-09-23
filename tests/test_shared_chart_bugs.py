"""Regression tests for shared chart / hover / nav defects (fix-shared-chart-bugs)."""
from __future__ import annotations

import json

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from dashboard.shared.ui_components import ticker_hover_wrap

import pathlib as _pl

# Absolute: AppTest resolves relative paths against the calling test file on
# some Streamlit versions (CI), not the repo root.
PAGE22 = str(_pl.Path(__file__).resolve().parents[1] / "dashboard" / "pages" / "22_fii_dii_flows.py")


def _fd_frame(nets):
    n = len(nets)
    return pd.DataFrame({
        "date": pd.date_range("2026-09-01", periods=n).astype(str),
        "fii_buy": [None] * n, "fii_sell": [None] * n, "fii_net": nets,
        "dii_buy": [None] * n, "dii_sell": [None] * n, "dii_net": list(nets),
    }, dtype=object)


def _run22(monkeypatch, df):
    import analysis.fii_dii as fd
    monkeypatch.setattr(fd, "load_history", lambda days=60: df.copy())
    return AppTest.from_file(PAGE22, default_timeout=120).run()


def test_page22_all_null_nets_does_not_crash(monkeypatch):
    at = _run22(monkeypatch, _fd_frame([None, None, None]))
    assert not at.exception, [str(e.value) for e in at.exception]


def test_page22_fii_dii_share_y_scale(monkeypatch):
    at = _run22(monkeypatch, _fd_frame(["100", "-50", 20.0]))
    assert not at.exception, [str(e.value) for e in at.exception]
    specs = [json.loads(c.proto.spec) for c in at.get("plotly_chart")]
    figs = [s for s in specs
            if any(t.get("name") == "DII net" for t in s.get("data", []))]
    assert figs, "flow subplot figure not rendered"
    lay = figs[0]["layout"]
    assert (lay.get("yaxis2", {}).get("matches") == "y"
            or lay.get("yaxis", {}).get("matches") == "y2")


def test_page22_no_advice_copy():
    with open(PAGE22, encoding="utf-8") as fh:
        assert "keep stops tight" not in fh.read().lower()


@pytest.mark.parametrize("price,chg", [(float("nan"), float("nan")),
                                       (float("nan"), 1.0),
                                       (5.0, float("inf"))])
def test_hover_skips_non_finite(price, chg):
    html = ticker_hover_wrap("X", price=price, chg_pct=chg)
    assert "nan" not in html.lower() and "inf" not in html.lower()


def test_hover_score_is_out_of_90():
    html = ticker_hover_wrap("X", score=60)
    assert "60/90" in html and "/100" not in html


def test_nav_alert_js_escapes_hostile_message():
    from dashboard.shared.nav import _alert_js_literal
    hostile = 'RELIANCE hit stop \\"; alert(1)//\n</script><script>alert(2)</script>'
    lit = _alert_js_literal(hostile)
    assert "</" not in lit
    assert "\n" not in lit
    assert json.loads(lit.replace("<\\/", "</")) == hostile[:90]
