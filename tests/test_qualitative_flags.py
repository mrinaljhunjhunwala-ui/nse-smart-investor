"""
QF1 regression tests — qualitative flags (governance/regulatory/narrative
layer alongside the composite score). No network: all NSE payloads are
synthetic dicts; persistence uses an in-memory fake standing in for
trade_store.kv_get/kv_set.

Run:  py -m pytest tests/test_qualitative_flags.py -q
"""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from analysis.qualitative_flags import (              # noqa: E402
    FlagCategory, FlagSentiment, QualitativeFlag,
    build_auto_flags, load_flags, manual_flag,
    parse_announcement_flags, parse_corporate_action_flags,
    parse_shareholding_flags, refresh_all_flags, save_flags, summarize_flags,
)


# ── fake kv store (mirrors trade_store.kv_get/kv_set signatures exactly) ──
class _FakeKv:
    def __init__(self):
        self.store: dict[str, object] = {}

    def get(self, key, default=None, user_id="default"):
        return self.store.get((user_id, key), default)

    def set(self, key, value, user_id="default"):
        self.store[(user_id, key)] = value
        return True


# ── QualitativeFlag round-trip ─────────────────────────────────────────────

def test_flag_to_dict_and_back_roundtrips():
    f = manual_flag("ABDL.NS", FlagCategory.NARRATIVE, FlagSentiment.GREEN, "JV announced")
    restored = QualitativeFlag.from_dict(f.to_dict())
    assert restored.ticker == f.ticker
    assert restored.category == FlagCategory.NARRATIVE
    assert restored.sentiment == FlagSentiment.GREEN
    assert restored.headline == "JV announced"


def test_flag_expiry_inactive_after_date():
    f = manual_flag("ABDL.NS", FlagCategory.MACRO, FlagSentiment.AMBER,
                     "Budget sensitive", expiry="2020-01-01")
    assert f.is_active(as_of=__import__("datetime").date(2020, 1, 2)) is False


def test_flag_without_expiry_always_active():
    f = manual_flag("ABDL.NS", FlagCategory.NARRATIVE, FlagSentiment.GREEN, "JV")
    assert f.is_active() is True


# ── shareholding pattern parsing ────────────────────────────────────────────

def test_shareholding_pledge_increase_flags_red():
    corp_info = {
        "shareholdings_patterns": {
            "data": {
                "2026-06-30": [{"pr_and_prgrp": "45.0", "pledged_pct": "18.0"}],
                "2026-03-31": [{"pr_and_prgrp": "45.0", "pledged_pct": "12.0"}],
            }
        }
    }
    flags = parse_shareholding_flags("ABDL.NS", corp_info)
    pledge_flags = [f for f in flags if "pledge" in f.headline.lower()]
    assert len(pledge_flags) == 1
    assert pledge_flags[0].sentiment == FlagSentiment.RED
    assert pledge_flags[0].category == FlagCategory.GOVERNANCE


def test_shareholding_promoter_holding_decrease_flags_red():
    corp_info = {
        "shareholdings_patterns": {
            "data": {
                "2026-06-30": [{"pr_and_prgrp": "40.0"}],
                "2026-03-31": [{"pr_and_prgrp": "45.0"}],
            }
        }
    }
    flags = parse_shareholding_flags("ABDL.NS", corp_info)
    assert len(flags) == 1
    assert flags[0].sentiment == FlagSentiment.RED
    assert "Promoter holding" in flags[0].headline


def test_shareholding_no_relevant_fields_returns_empty():
    corp_info = {
        "shareholdings_patterns": {
            "data": {
                "2026-06-30": [{"public_val": "55.0"}],
                "2026-03-31": [{"public_val": "54.0"}],
            }
        }
    }
    assert parse_shareholding_flags("ABDL.NS", corp_info) == []


def test_shareholding_single_date_returns_empty():
    corp_info = {"shareholdings_patterns": {"data": {"2026-06-30": [{"pr_and_prgrp": "45.0"}]}}}
    assert parse_shareholding_flags("ABDL.NS", corp_info) == []


def test_shareholding_missing_key_returns_empty():
    assert parse_shareholding_flags("ABDL.NS", {}) == []


def test_shareholding_small_change_not_flagged():
    """Deltas under 0.5pp are noise, not signal — should not flag."""
    corp_info = {
        "shareholdings_patterns": {
            "data": {
                "2026-06-30": [{"pr_and_prgrp": "45.1"}],
                "2026-03-31": [{"pr_and_prgrp": "45.0"}],
            }
        }
    }
    assert parse_shareholding_flags("ABDL.NS", corp_info) == []


# ── corporate action parsing ────────────────────────────────────────────────

def test_corporate_action_buyback_flags_green():
    corp_info = {"corporate_actions": {"data": [
        {"symbol": "ABDL", "exdate": "2026-07-01", "purpose": "Buyback of Shares"}
    ]}}
    flags = parse_corporate_action_flags("ABDL.NS", corp_info)
    assert len(flags) == 1
    assert flags[0].sentiment == FlagSentiment.GREEN
    assert flags[0].category == FlagCategory.CORPORATE_ACTION


def test_corporate_action_unclassified_defaults_amber():
    corp_info = {"corporate_actions": {"data": [
        {"symbol": "ABDL", "exdate": "2026-07-01", "purpose": "Annual General Meeting"}
    ]}}
    flags = parse_corporate_action_flags("ABDL.NS", corp_info)
    assert flags[0].sentiment == FlagSentiment.AMBER


def test_corporate_action_empty_purpose_skipped():
    corp_info = {"corporate_actions": {"data": [{"symbol": "ABDL", "exdate": "2026-07-01", "purpose": ""}]}}
    assert parse_corporate_action_flags("ABDL.NS", corp_info) == []


# ── announcement parsing ────────────────────────────────────────────────────

def test_announcement_negative_keyword_flags_red():
    corp_info = {"latest_announcements": {"data": [
        {"symbol": "ABDL", "broadcastdate": "2026-07-01",
         "subject": "Resignation of Independent Director"}
    ]}}
    flags = parse_announcement_flags("ABDL.NS", corp_info)
    assert flags[0].sentiment == FlagSentiment.RED


def test_announcement_respects_max_items():
    corp_info = {"latest_announcements": {"data": [
        {"symbol": "ABDL", "broadcastdate": "2026-07-01", "subject": f"Update {i}"}
        for i in range(10)
    ]}}
    flags = parse_announcement_flags("ABDL.NS", corp_info, max_items=3)
    assert len(flags) == 3


# ── build_auto_flags orchestration ──────────────────────────────────────────

def test_build_auto_flags_empty_corp_info_returns_empty():
    assert build_auto_flags("ABDL.NS", {}) == []


def test_build_auto_flags_combines_all_sources():
    corp_info = {
        "shareholdings_patterns": {"data": {
            "2026-06-30": [{"pledged_pct": "18.0"}],
            "2026-03-31": [{"pledged_pct": "10.0"}],
        }},
        "corporate_actions": {"data": [
            {"symbol": "ABDL", "exdate": "2026-07-01", "purpose": "Buyback of Shares"}
        ]},
        "latest_announcements": {"data": [
            {"symbol": "ABDL", "broadcastdate": "2026-07-01", "subject": "Q1 results announced"}
        ]},
    }
    flags = build_auto_flags("ABDL.NS", corp_info)
    categories = {f.category for f in flags}
    assert FlagCategory.GOVERNANCE in categories
    assert FlagCategory.CORPORATE_ACTION in categories
    assert FlagCategory.ANNOUNCEMENT in categories


# ── persistence (fake kv, matching real trade_store signature) ─────────────

def test_save_and_load_flags_roundtrip():
    kv = _FakeKv()
    flags = [manual_flag("ABDL.NS", FlagCategory.NARRATIVE, FlagSentiment.GREEN, "JV")]
    assert save_flags("ABDL.NS", flags, kv.set) is True
    loaded = load_flags("ABDL.NS", kv.get)
    assert len(loaded) == 1
    assert loaded[0].headline == "JV"


def test_load_flags_missing_ticker_returns_empty():
    kv = _FakeKv()
    assert load_flags("NOPE.NS", kv.get) == []


def test_load_flags_filters_expired():
    kv = _FakeKv()
    expired = manual_flag("ABDL.NS", FlagCategory.MACRO, FlagSentiment.AMBER,
                           "Old budget flag", expiry="2020-01-01")
    active = manual_flag("ABDL.NS", FlagCategory.NARRATIVE, FlagSentiment.GREEN, "JV")
    save_flags("ABDL.NS", [expired, active], kv.set)
    loaded = load_flags("ABDL.NS", kv.get)
    assert len(loaded) == 1
    assert loaded[0].headline == "JV"


def test_refresh_all_flags_preserves_manual_and_merges_fresh():
    kv = _FakeKv()
    manual = manual_flag("ABDL.NS", FlagCategory.NARRATIVE, FlagSentiment.GREEN,
                          "Ranveer Singh JV")
    save_flags("ABDL.NS", [manual], kv.set)

    corp_info = {"corporate_actions": {"data": [
        {"symbol": "ABDL", "exdate": "2026-07-01", "purpose": "Buyback of Shares"}
    ]}}
    merged = refresh_all_flags("ABDL.NS", kv.get, kv.set, corp_info=corp_info)
    headlines = {f.headline for f in merged}
    assert "Ranveer Singh JV" in headlines
    assert any("Buyback" in h for h in headlines)


def test_refresh_all_flags_degrades_gracefully_on_fetch_failure(monkeypatch):
    """If the NSE fetcher raises, refresh should not blow up the caller —
    it should fall back to an empty auto-flag set and keep manual flags."""
    kv = _FakeKv()
    manual = manual_flag("ABDL.NS", FlagCategory.NARRATIVE, FlagSentiment.GREEN, "JV")
    save_flags("ABDL.NS", [manual], kv.set)

    def _boom(_ticker):
        raise ConnectionError("NSE unreachable")

    import data.nse_corp_info as nci
    monkeypatch.setattr(nci, "get_corp_info", _boom)

    merged = refresh_all_flags("ABDL.NS", kv.get, kv.set, corp_info=None)
    assert len(merged) == 1
    assert merged[0].headline == "JV"


# ── summarize_flags ──────────────────────────────────────────────────────

def test_summarize_flags_counts_by_sentiment():
    flags = [
        manual_flag("X.NS", FlagCategory.NARRATIVE, FlagSentiment.GREEN, "a"),
        manual_flag("X.NS", FlagCategory.GOVERNANCE, FlagSentiment.RED, "b"),
        manual_flag("X.NS", FlagCategory.MACRO, FlagSentiment.AMBER, "c"),
        manual_flag("X.NS", FlagCategory.NARRATIVE, FlagSentiment.GREEN, "d"),
    ]
    counts = summarize_flags(flags)
    assert counts == {"green": 2, "red": 1, "amber": 1}
