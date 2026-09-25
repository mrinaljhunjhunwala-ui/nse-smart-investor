"""tests/test_composite_golden_snapshot.py — OFFLINE composite-score regression.

NO network. Replays every case in data/composite_golden_snapshot.json through
`score_dataframe()` (seeded synthetic OHLCV + benchmark, fixed context) and fails
on ANY drift in score / grade / action / pillar points / entry levels.

Intentional scoring change? Regenerate and review the diff in the PR:
    python tools/composite_golden.py --update
"""
from __future__ import annotations

import json
import math

import pytest

from tools import composite_golden as cg

_TOL = 1e-4


@pytest.fixture(scope="module")
def snap():
    with open(cg.SNAPSHOT_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def replayed():
    return {c["name"]: cg.run_case(c) for c in cg.CASES}


def _same(a, b) -> bool:
    if isinstance(a, float) or isinstance(b, float):
        return a is not None and b is not None and math.isclose(a, b, abs_tol=_TOL)
    return a == b


def test_schema(snap):
    assert snap["schema_version"] == cg.SCHEMA_VERSION
    assert set(snap["cases"]) == {c["name"] for c in cg.CASES}, (
        "case list changed — run `python tools/composite_golden.py --update`")


def test_replay_no_drift(snap, replayed):
    drift = []
    for name, want in snap["cases"].items():
        got = replayed[name]
        for field, w in want.items():
            if not _same(got.get(field), w):
                drift.append(f"{name}.{field}: snapshot={w!r} now={got.get(field)!r}")
    assert not drift, (
        "Composite score drift (if intentional: python tools/composite_golden.py --update)\n  "
        + "\n  ".join(drift))


# ── Invariants the snapshot is meant to protect (readable failure messages) ─────
def _pts(row):
    return (row["technical_score"], row["momentum_score"],
            row["volume_score"], row["sentiment_score"])


def test_vix_regime_does_not_move_points(replayed):
    assert _pts(replayed["steady_uptrend__vix_high"]) == _pts(replayed["steady_uptrend__neutral"])


def test_bear_regime_momentum_on_by_default(replayed):
    on, off = replayed["steady_downtrend__bear"], replayed["steady_downtrend__bear_flag_off"]
    assert on["momentum_score"] != off["momentum_score"]
    assert off == replayed["steady_downtrend__neutral"]


def test_non_bear_regime_label_is_noop(replayed):
    assert replayed["sideways__uptrend_regime"] == replayed["sideways__neutral"]


def test_score_caps(replayed):
    for name, row in replayed.items():
        cap = 100.0 if row["positioning_score"] is not None else 90.0
        assert 0.0 <= row["score"] <= cap, name
    assert replayed["steady_uptrend__positioning_flag_off"]["positioning_score"] is None
    assert replayed["steady_uptrend__positioning_on"]["positioning_score"] is not None


def test_no_benchmark_leaves_rs_empty(replayed):
    assert replayed["steady_uptrend__no_rs"]["rs_score"] is None
