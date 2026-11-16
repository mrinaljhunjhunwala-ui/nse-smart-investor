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


def _index(closes, start="2026-09-28"):
    idx = pd.bdate_range(start=start, periods=len(closes))
    return pd.DataFrame({"Close": closes}, index=idx)


def test_bench_returns_close_to_close_h_sessions_later():
    ix = _index([100, 101, 102, 103, 104, 105, 110, 111])               # 28 Sep (Mon) ... 7 Oct
    r = C.bench_returns(ix, ["2026-09-28", "2026-09-30", "2026-10-03", "2026-10-07"], 5)
    assert round(r["2026-09-28"], 6) == 5.0                             # 100 -> 105
    assert round(r["2026-09-30"], 6) == round((111 / 102 - 1) * 100, 6)
    assert "2026-10-03" not in r and "2026-10-07" not in r              # windows not finished
    assert round(C.bench_returns(ix, ["2026-10-03"], 3)["2026-10-03"], 6) == \
        round((111 / 104 - 1) * 100, 6)                                 # Saturday: from Friday's close
    assert C.bench_returns(None, ["2026-09-28"], 5) == {} and C.bench_returns(pd.DataFrame(), ["x"], 5) == {}
    assert C.bench_returns(ix, ["2020-01-01"], 5) == {}                 # before the history


def test_rebased_swaps_the_benchmark():
    s = C.settled(_rows(), 5)
    out = C.rebased(s, {"2026-10-01": 0.0})                             # only day 1 has a broad move
    assert set(out["logged_date"]) == {"2026-10-01"} and (out["alpha"] == out["ret"]).all()
    assert C.rebased(s, {}).empty


def test_build_report_adds_broad_market_tables():
    # broad index flat over both windows, Nifty 50 as in the rows
    broad = _index([100.0] * 12, start="2026-09-28")
    regimes = {"2026-10-01": "Falling", "2026-10-02": "Rising"}
    text = "\n".join(C.build_report(_rows(), regimes, broad=broad, nifty=broad))
    assert "against the Nifty 500" in text and "BUY / STRONG BUY calls vs the Nifty 500, all:" in text
    assert "Every scored name vs the Nifty 500, by composite score:" in text and "method check" in text
    plain = "\n".join(C.build_report(_rows(), regimes))
    assert "Nifty 500" not in plain                                     # left out when no broad history


def test_band_record_and_gate_rows():
    from analysis.calibration_summary import band_record, score_band
    from analysis.final_verdict import combine, gate_rows
    df = pd.concat([_rows()] * 1, ignore_index=True)
    assert score_band(72) == "70-79" and band_record(df, 72, 5, min_picks=2)["avg_alpha"] == 1.0
    assert band_record(df, 72, 5) is None                           # under 20 settled names: no record shown
    assert band_record(df, None, 5) is None and band_record(pd.DataFrame(), 72, 5) is None
    fv = combine(composite_score=80, composite_action="BUY", quality_flags={"severity": "red"},
                 valuation_posture="DEMANDING_VS_GROWTH")
    rows = {r["name"]: r for r in gate_rows(fv)}
    assert [r["name"] for r in gate_rows(fv)][0] == "quality"       # business first, timing last
    assert rows["quality"]["state"] == "blocks" and rows["quality"]["limiting"] is True
    assert rows["valuation"]["state"] == "weakens" and rows["thesis"]["state"] == "no data"
    assert gate_rows(None) == []


def test_grade_quality_log():
    idx = pd.bdate_range("2026-09-01", periods=80)
    flat = pd.Series(100.0, index=idx)
    up = pd.Series([100.0] * 10 + [110.0] * 70, index=idx)
    day = idx[5].date().isoformat()
    logs = {day: [{"ticker": "HI.NS", "quality_score": 82}, {"ticker": "LO.NS", "quality_score": 40},
                  {"ticker": "NOPX.NS", "quality_score": 75}]}
    text = "\n".join(C.grade_quality_log(logs, {"HI.NS": up, "LO.NS": flat}, pd.DataFrame({"Close": flat})))
    assert "70 and over" in text and "under 50" in text and "+10.0 pts" in text
    assert "no Quality Watch rankings logged yet" in "\n".join(C.grade_quality_log({}, {}, None))
    late = {idx[-3].date().isoformat(): logs[day]}
    assert "nothing has settled yet" in "\n".join(
        C.grade_quality_log(late, {"HI.NS": up, "LO.NS": flat}, pd.DataFrame({"Close": flat})))
