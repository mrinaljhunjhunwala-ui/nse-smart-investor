"""tests/test_ui_components.py — pin the shared UI palette + component API.

These are pure string builders so unit tests are cheap and definitive. What
they lock in:

  * Palette has a color for every verdict / action label the app uses,
    including the exact label spellings the pages depend on ("WATCH" and
    "WATCHLIST" both keyed, since old and new code mix them).
  * Verdict pills carry the label AND a hover tooltip carrying horizon +
    confidence — the "why this verdict" info can't be lost by future edits.
  * Regime badge includes the historical hit-rate context (the tooltip
    that helps a user calibrate their confidence in any BUY signal).
  * rr_line surfaces BOTH the gross and cost-adjusted R:R so gross is
    never shown alone (the original bug this whole R:R work exists to fix).
"""
from __future__ import annotations

import os
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from dashboard.shared.ui_components import (  # noqa: E402
    COLORS, REGIME_COLORS, REGIME_EMOJI, REGIME_NOTES,
    action_color, verdict_pill, freshness_stamp, rr_line, regime_badge,
)


def test_palette_covers_every_label_the_app_actually_uses():
    """Anti-regression: the app pages emit these strings verbatim, so a
    missing key would silently render as the neutral grey fallback."""
    from analysis.final_verdict import VERDICTS
    for v in VERDICTS:
        assert v in COLORS, f"verdict {v!r} missing from COLORS"

    # analysis/score.py action-band labels too
    for action in ("STRONG BUY", "BUY", "WATCHLIST", "HOLD",
                   "CAUTION", "EXIT", "UNAVAILABLE"):
        assert action in COLORS, f"action {action!r} missing from COLORS"


def test_action_color_never_raises_and_falls_back_to_hold_grey():
    assert action_color("STRONG BUY") == COLORS["STRONG BUY"]
    assert action_color("strong buy") == COLORS["STRONG BUY"]  # case-insensitive
    assert action_color("nonsense")   == COLORS["HOLD"]
    assert action_color(None)         == COLORS["HOLD"]
    assert action_color("")           == COLORS["HOLD"]


def test_verdict_pill_carries_hover_tooltip_with_horizon_and_confidence():
    """The tooltip is where the "why this verdict" info lives on cards
    where there's no room for a full expander."""
    html = verdict_pill("BUY", horizon="long", confidence="high",
                        conviction=78, primary_reason="Trend + valuation aligned")
    assert "VERDICT: BUY" in html
    assert "long-term lens"  in html
    assert "high confidence" in html
    assert "conviction 78/100" in html
    assert "Trend + valuation aligned" in html
    # Uses the palette green for BUY
    assert COLORS["BUY"] in html


def test_verdict_pill_veto_uses_avoid_deeper_red():
    """AVOID should look distinct from EXIT — deeper red so the "final-
    verdict veto" is visually stronger than "technical exit today"."""
    html_avoid = verdict_pill("AVOID")
    html_exit  = verdict_pill("EXIT")
    assert COLORS["AVOID"] in html_avoid
    assert COLORS["EXIT"]  in html_exit
    assert COLORS["AVOID"] != COLORS["EXIT"]


def test_rr_line_shows_both_gross_and_net():
    """The whole point — never show gross alone."""
    html = rr_line(rr_gross=3.0, rr_net=2.48, cost_pct=0.30)
    assert "3.0:1" in html and "gross" in html
    assert "2.5:1" in html and "net" in html
    assert "0.30" in html
    # Net must appear AFTER gross so a scanning reader sees the honest one last
    assert html.index("net") > html.index("gross")


def test_regime_badge_carries_historical_hit_rate_context():
    """The value of the regime badge is the tooltip that tells a user
    what to expect from a BUY signal IN THIS REGIME."""
    for label in ("trend_up", "trend_down", "range", "risk_off"):
        html = regime_badge(label, confidence="medium", compact=False)
        assert REGIME_EMOJI[label] in html
        assert label.replace("_", " ").title() in html
        # The educational note must be in there — that's the whole point
        assert any(word in html.lower()
                   for word in ("historical", "regime", "hit rate", "fear",
                                "trending", "outperformed"))


def test_regime_badge_compact_form_fits_in_a_title_row():
    """Compact form should be a single span, not a divisive full-width div,
    so it can sit next to a page title without breaking the layout."""
    html = regime_badge("trend_up", confidence="high", compact=True)
    assert html.startswith("<span")
    assert "border-left" not in html   # no full-width banner styling


def test_freshness_stamp_flags_live_price_unavailable_honestly():
    html_ok = freshness_stamp("09:32", live_ok=True)
    html_no = freshness_stamp("09:32", live_ok=False)
    assert "09:32" in html_ok and "09:32" in html_no
    assert "last close" in html_no.lower(), \
        "must say last-close explicitly when live is unavailable — no silent staleness"
    assert "last close" not in html_ok.lower()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
