"""tests/test_dt_transparency.py — DT1 source_pill + DT2 data_as_of contract."""
from __future__ import annotations

import pytest

from dashboard.shared.ui_components import source_pill, data_as_of


# ── DT1 · source_pill ───────────────────────────────────────────────────────

def test_source_pill_known_source_renders_readable_label():
    html = source_pill("nse")
    assert "via NSE" in html
    assert "<span" in html


def test_source_pill_is_case_insensitive():
    """Callers shouldn't need to remember the exact casing of the source key."""
    assert "via NSE" in source_pill("NSE")
    assert "via NSE" in source_pill("nse")
    assert "via NSE" in source_pill("  NSE  ")


def test_source_pill_normalises_delimiters():
    """'angel one' and 'angel-one' and 'angel_one' should all map to the
    same known source — callers use the phrase, not the enum key."""
    a = source_pill("angel_one")
    b = source_pill("Angel One")
    c = source_pill("angel-one")
    for html in (a, b, c):
        assert "via Angel One" in html


def test_source_pill_unknown_source_falls_back_to_dim():
    """An unknown source must still render — the pill is a transparency
    tool, so it never fails silently or omits itself."""
    html = source_pill("some-new-provider")
    assert "via some-new-provider" in html
    assert "<span" in html


def test_source_pill_empty_source_reads_as_unknown():
    """Empty/None sources are the caller's bug — still renders 'via unknown'
    so the missing-attribution is visible, not hidden."""
    for s in ("", "   "):
        assert "via unknown" in source_pill(s)


def test_source_pill_carries_ttl_hint_on_hover_only():
    """TTL hint belongs in the title attribute, not the visible pill text —
    horizontal space is scarce on data-heavy cards."""
    html = source_pill("nse", ttl_hint="60s cache")
    assert "60s cache" in html
    # Must not leak into the visible label.
    assert "60s cache</span>" not in html


def test_source_pill_extra_title_appended():
    html = source_pill("nse", ttl_hint="60s cache",
                       extra_title="last refresh 14:32")
    assert "60s cache" in html
    assert "last refresh 14:32" in html


# ── DT2 · data_as_of ────────────────────────────────────────────────────────

def test_data_as_of_basic_stamp():
    html = data_as_of("14:32 IST")
    assert "Data as of 14:32 IST" in html
    assert "<div" in html


def test_data_as_of_missing_time_falls_back_to_unknown():
    """A caller passing an empty timestamp is a bug worth surfacing
    (missing attribution), not swallowing."""
    assert "Data as of unknown" in data_as_of("")
    assert "Data as of unknown" in data_as_of("   ")


def test_data_as_of_combines_with_source_pill():
    """The canonical stamp lets a card carry both DT1 + DT2 in one line."""
    html = data_as_of("14:32 IST", source="nse", ttl_hint="60s cache")
    assert "Data as of 14:32 IST" in html
    assert "via NSE" in html
    assert "60s cache" in html


def test_data_as_of_without_source_omits_pill():
    html = data_as_of("14:32 IST")
    assert "via " not in html


@pytest.mark.parametrize("source,expected_label", [
    ("nse", "NSE"),
    ("bse", "BSE"),
    ("angel_one", "Angel One"),
    ("yahoo", "Yahoo"),
    ("yfinance", "Yahoo"),
    ("stooq", "Stooq"),
    ("screener", "Screener"),
    ("cache", "cache"),
    ("manual", "manual entry"),
])
def test_known_sources_map_to_stable_labels(source, expected_label):
    """The label taxonomy is stable — pages using this helper get the same
    string wherever they render (DT1's whole point)."""
    assert f"via {expected_label}" in source_pill(source)
