"""Audit 2026-11: alert jobs."""
import datetime as dt

import analysis.movers as AM
from alerts import movers_alerts as MA


def _movers(n=15):
    bands = (["Large"] * 5 + ["Mid"] * 5 + ["Small"] * 5)[:n]
    return [{"symbol": f"STOCK{i:02d}", "band": b, "pct": 5.0 + i * 0.3, "price": 1234.5, "vol_ratio": 2.5,
             "watchlist": ("Bullish breakout", 3, None)} for i, b in enumerate(bands)]


def test_only_movers_that_fit_the_message_are_marked_sent(monkeypatch):
    monkeypatch.setattr(AM, "chase_lookup",
                        lambda *a, **k: {"median_excess": 1.2, "beat_pct": 55, "n": 123, "horizon": 5})
    mv = _movers()
    reasons = {m["symbol"]: ["Order win: Company bags order worth Rs 450 crore from a state utility for "
                             "supply of", "2.5x normal volume"] for m in mv}
    scan = {"data": {f"{m['symbol']}.NS": {"score": 72, "action": "BUY", "sl": 1100} for m in mv}}
    lines, kept = MA.build_radar(mv, now=dt.datetime(2026, 11, 17, 11, 0), reasons=reasons,
                                 evidence={"table": None}, scan=scan, source="NSE")
    shown = [ln for ln in lines if ln.startswith("▲")]
    assert len(shown) == len(kept) < len(mv)          # the caller used to mark all 15 as sent
    assert len("\n".join(lines)) <= MA.MSG_CHAR_BUDGET
    assert not lines[-2].startswith("<b>")             # no orphan tier header before the footer


def test_check_movers_radar_marks_only_the_kept_movers(monkeypatch):
    import alerts.check_alerts as CA
    import analysis.catalysts as C
    import data.nse_movers as NM
    mv = _movers()
    monkeypatch.setattr(CA, "dispatch", lambda text, subject=None: True)
    monkeypatch.setattr(NM, "fetch_gainers", lambda scan: [{"source": "NSE"}])
    monkeypatch.setattr(AM, "select_movers", lambda rows, **k: mv)
    monkeypatch.setattr(AM, "watchlist_ranks", lambda d: {})
    monkeypatch.setattr(C, "explain_move", lambda *a, **k: ["x" * 300])
    monkeypatch.setattr(MA, "_kv", lambda *a, **k: None)
    monkeypatch.setattr(MA, "_kv_set", lambda *a, **k: True)
    monkeypatch.setattr(MA, "_events_by_symbol", lambda n: {})
    state = {}
    assert MA.check_movers_radar(state, "2026-11-17", now=dt.datetime(2026, 11, 17, 11, 0)) == 1
    marked = [k for k in state if k.startswith("mover_")]
    assert 0 < len(marked) < len(mv)


def test_workflow_pins_match_requirements():
    """market-alerts.yml installed pyotp <3.0; requirements.txt holds it under 2.12 because 2.12
    rejects TOTP secrets under 112 bits, which would stop the Angel One login in every alert run."""
    import pathlib
    import re
    req = {}
    for line in pathlib.Path("requirements.txt").read_text(encoding="utf-8").splitlines():
        m = re.match(r"^([A-Za-z0-9_.-]+)\s*([<>=!~][^#\s]*)", line.strip())
        if m:
            req[m.group(1).lower()] = m.group(2).replace(" ", "")
    bad = []
    for wf in pathlib.Path(".github/workflows").glob("*.yml"):
        for pkg, spec in re.findall(r'"([A-Za-z0-9_.-]+)([<>=!~][^"]*)"', wf.read_text(encoding="utf-8")):
            want = req.get(pkg.lower())
            if want and not spec.startswith("==") and spec.replace(" ", "") != want:   # exact pins are deliberate
                bad.append(f"{wf.name}: {pkg}{spec} vs requirements {pkg}{want}")
    assert not bad, bad


def test_overlapping_runs_union_their_dedupe_stamps(tmp_path, monkeypatch):
    """market-alerts and the momentum digest overlap at 10:00, 10:30 …; each restored the same
    state file from the Actions cache and the last save won, so alerts were re-sent."""
    import alerts.check_alerts as CA
    kv = {}
    import trade_store
    monkeypatch.setattr(trade_store, "kv_get", lambda k, d=None, user_id="default": kv.get((user_id, k), d))
    monkeypatch.setattr(trade_store, "kv_set", lambda k, v, user_id="default": kv.__setitem__((user_id, k), v) or True)
    today = "2026-11-17"
    a_file, b_file = tmp_path / "a.json", tmp_path / "b.json"
    # both runs start from the same restored 09:45 state
    monkeypatch.setattr(CA, "_STATE_JSON", str(a_file))
    run_a = CA._load_state()
    monkeypatch.setattr(CA, "_STATE_JSON", str(b_file))
    run_b = CA._load_state()
    run_a["mover_DHANBANK"] = today                 # market-alerts run
    run_b["momentum_am"] = today                    # momentum digest run
    monkeypatch.setattr(CA, "_STATE_JSON", str(a_file))
    CA._save_state(run_a)
    monkeypatch.setattr(CA, "_STATE_JSON", str(b_file))
    CA._save_state(run_b)                           # saved last: used to drop mover_DHANBANK
    nxt = CA._load_state()
    assert nxt.get("mover_DHANBANK") == today and nxt.get("momentum_am") == today
    CA._save_state({"x": "2026-11-18"})             # next day: yesterday's stamps drop out
    assert CA._load_state() == {"x": "2026-11-18"}
    CA._save_state({}, merge=False)                 # --clear-today writes exactly
    assert kv[("_system", "alert_state")] == {}


def test_radar_budget_is_paced_through_the_session():
    """17 Nov: all 6 radar messages were gone by ~11:00 IST; nothing after."""
    t = dt.time
    assert MA.radar_allowance(t(9, 45)) == 1 and MA.radar_allowance(t(10, 15)) == 1
    assert MA.radar_allowance(t(11, 0)) == 2 and MA.radar_allowance(t(14, 45)) == 6
    assert MA.radar_allowance(t(9, 30)) == 0


def test_paced_run_holds_plain_movers_but_not_watchlist_names(monkeypatch):
    import alerts.check_alerts as CA
    import analysis.catalysts as C
    import data.nse_movers as NM
    sent = []
    monkeypatch.setattr(CA, "dispatch", lambda text, subject=None: sent.append(text) or True)
    monkeypatch.setattr(NM, "fetch_gainers", lambda scan: [{"source": "NSE"}])
    monkeypatch.setattr(AM, "watchlist_ranks", lambda d: {})
    monkeypatch.setattr(C, "explain_move", lambda *a, **k: ["filing"])
    monkeypatch.setattr(MA, "_kv", lambda *a, **k: None)
    monkeypatch.setattr(MA, "_kv_set", lambda *a, **k: True)
    monkeypatch.setattr(MA, "_events_by_symbol", lambda n: {})
    plain = [{"symbol": "ABC", "band": "Large", "pct": 4.0, "price": 100.0, "vol_ratio": 2.0, "watchlist": None}]
    monkeypatch.setattr(AM, "select_movers", lambda rows, **k: [dict(m) for m in plain])
    state = {"movers_msg_1": "2026-11-17"}                    # 09:45 message already out
    assert MA.check_movers_radar(state, "2026-11-17", now=dt.datetime(2026, 11, 17, 10, 0)) == 0
    assert "mover_ABC" not in state and not sent               # held, still eligible later
    assert MA.check_movers_radar(state, "2026-11-17", now=dt.datetime(2026, 11, 17, 10, 30)) == 1
    plain[0].update(symbol="WLX", watchlist=("Bullish breakout", 3, 1))
    assert MA.check_movers_radar(state, "2026-11-17", now=dt.datetime(2026, 11, 17, 10, 45)) == 1
