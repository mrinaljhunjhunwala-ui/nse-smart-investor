"""Offline tests for scripts/calibration_report.py (pure report on ledger rows)."""
import pandas as pd

import scripts.calibration_report as C


def _rows():
    rows = []
    # two days; higher score -> better result on both; day 2 the market rose
    for day, nifty in (("2026-10-01", -1.0), ("2026-10-02", 2.0)):
        for i, (score, verdict, ret) in enumerate([(85, "STRONG BUY", nifty + 3.0), (72, "BUY", nifty + 1.0),
                                                   (65, "WATCH", nifty + 0.0), (55, "HOLD", nifty - 1.0),
                                                   (40, "AVOID", nifty - 3.0)]):
            rows.append({"id": len(rows) + 1, "logged_date": day, "ticker": f"T{i}", "verdict": verdict,
                         "composite_score": score, "source": "top_picks",
                         "ret_5d": ret, "nifty_ret_5d": nifty, "ret_20d": None, "nifty_ret_20d": None})
    rows.append(dict(rows[0], id=99, source="analyze_page"))          # same name, same day, second list
    return pd.DataFrame(rows)


def test_score_band_edges():
    assert [C.score_band(x) for x in (49.9, 50, 59.9, 60, 70, 79.9, 80, 90)] == \
        ["under 50", "50-59", "50-59", "60-69", "70-79", "70-79", "80 and over", "80 and over"]
    assert C.score_band(None) is None and C.score_band("x") is None and C.score_band(float("nan")) is None


def test_settled_and_dedupe_and_group_stats():
    s = C.settled(_rows(), 5)
    assert len(s) == 11 and set(s["alpha"].round(6)) == {3.0, 1.0, 0.0, -1.0, -3.0}
    one = C.one_per_day_ticker(s)
    assert len(one) == 10                                             # the duplicate counts once
    assert C.settled(_rows(), 20).empty and C.settled(pd.DataFrame(), 5).empty
    g = {r["group"]: r for r in C.group_stats(one, "verdict")}
    sb = g["STRONG BUY"]
    assert sb["picks"] == 2 and sb["days"] == 2 and sb["avg_alpha"] == 3.0 and sb["pick_win_pct"] == 100.0
    assert sb["day_win_pct"] == 100.0 and 0 < sb["day_win_lower_pct"] < 100
    assert g["AVOID"]["avg_alpha"] == -3.0 and g["AVOID"]["day_win_pct"] == 0.0
    assert round(g["BUY"]["avg_ret"], 6) == 1.5 and round(g["BUY"]["avg_nifty"], 6) == 0.5


def test_score_rank_corr_is_within_day():
    one = C.one_per_day_ticker(C.settled(_rows(), 5))
    rc = C.score_rank_corr(one)
    assert rc["days"] == 2 and rc["mean_corr"] > 0.9 and rc["positive_days_pct"] == 100.0
    flipped = one.assign(alpha=-one["alpha"])
    assert C.score_rank_corr(flipped)["mean_corr"] < -0.9
    assert C.score_rank_corr(one.iloc[:3])["days"] == 0               # under 5 names a day: not scored


def test_build_report_sections():
    text = "\n".join(C.build_report(_rows(), {"2026-10-01": "Falling", "2026-10-02": "Rising"}))
    assert "CALIBRATION REPORT  ledger 2026-10-01 -> 2026-10-02" in text
    assert "=== 5 sessions after the call: 11 settled rows, 2 days ===" in text
    assert "nothing has settled at this horizon yet" in text          # 20 sessions
    for part in ("by Nifty direction", "Rising", "Falling", "by composite score", "80 and over", "under 50",
                 "Every call, by verdict", "by month of the call", "2026-10", "average rank correlation +1.00"):
        assert part in text, part
    assert C.build_report(pd.DataFrame())[1].startswith("The verdict ledger is empty")
    assert C._wilson_lower(0, 0) == 0.0 and 0.5 < C._wilson_lower(30, 40) < 0.75
