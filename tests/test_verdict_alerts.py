"""check_verdict_alerts — BUY/STRONG BUY verdicts from the Top Picks snapshot."""
import datetime as dt

import alerts.check_alerts as ca


def _pick(tk, score, action):
    return {"ticker": tk, "score": score, "action": action, "price": 100.0, "sl": 95.0,
            "tp": 110.0, "sector": "Pharma", "horizon": "Positional (2–4 weeks)"}


def _setup(monkeypatch, buys, verdicts, age_h=0.2):
    import trade_store
    gen = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=age_h)).isoformat()
    monkeypatch.setattr(trade_store, "kv_get",
                        lambda *a, **k: {"generated_at": gen, "data": {"buys": buys}})

    class _FV:
        def __init__(self, v):
            self.verdict, self.conviction = v, 86

    import dashboard.shared.pick_freshness as pf
    monkeypatch.setattr(pf, "compose_finalverdict_for_card",
                        lambda b, tqs=None, log_source=None: _FV(verdicts[b["ticker"]]))
    monkeypatch.setattr(ca, "_regime_note", lambda: ca._MARKET_DOWN)
    sent = []
    monkeypatch.setattr(ca, "dispatch", lambda m, **k: sent.append(m) or True)
    return sent


def test_sends_buy_and_strong_buy_once_per_day(monkeypatch):
    buys = [_pick("AAA.NS", 70, "STRONG_BUY"), _pick("BBB.NS", 72, "BUY"), _pick("CCC.NS", 55, "WATCHLIST")]
    sent = _setup(monkeypatch, buys, {"AAA.NS": "STRONG BUY", "BBB.NS": "BUY", "CCC.NS": "WATCH"})
    state = {}
    assert ca.check_verdict_alerts(state, "2026-10-02") == 2
    assert len(sent) == 1                                      # one message per run
    msg = sent[0]
    assert "2 new BUY calls</b>" in msg and "Model output, not a guarantee." in msg
    assert "STRONG BUY  <b>AAA</b>  ₹100.00 · stop ₹95.00 · target ₹110.00" in msg
    assert "BUY  <b>BBB</b>" in msg and "Market: downtrend — smaller size" in msg
    assert msg.index("AAA") < msg.index("BBB") and "CCC" not in msg   # strongest first
    assert ca.check_verdict_alerts(state, "2026-10-02") == 0   # deduped
    assert len(sent) == 1


def test_upgrade_fires_again(monkeypatch):
    state = {}
    _setup(monkeypatch, [_pick("AAA.NS", 72, "BUY")], {"AAA.NS": "BUY"})
    assert ca.check_verdict_alerts(state, "2026-10-02") == 1
    _setup(monkeypatch, [_pick("AAA.NS", 70, "STRONG_BUY")], {"AAA.NS": "STRONG BUY"})
    assert ca.check_verdict_alerts(state, "2026-10-02") == 1


def test_stale_snapshot_sends_nothing(monkeypatch):
    sent = _setup(monkeypatch, [_pick("AAA.NS", 70, "STRONG_BUY")], {"AAA.NS": "STRONG BUY"}, age_h=5)
    assert ca.check_verdict_alerts({}, "2026-10-02") == 0 and not sent


def test_verdict_alert_copy_is_descriptive(monkeypatch):
    from tests.test_alert_copy_no_advice import _assert_descriptive
    sent = _setup(monkeypatch, [_pick("AAA.NS", 70, "STRONG_BUY"), _pick("BBB.NS", 72, "BUY")],
                  {"AAA.NS": "STRONG BUY", "BBB.NS": "BUY"})
    ca.check_verdict_alerts({}, "2026-10-02")
    assert ca.check_test_verdict_alert({}, "2026-10-02") == 1
    assert len(sent) == 2                                      # combined run message + test alert
    for m in sent:
        _assert_descriptive(m)


def test_digest_lists_extra_strong_reads(monkeypatch):
    from tests.test_alert_copy_no_advice import _assert_descriptive
    buys = [_pick(f"T{i}.NS", 80 - i, "WATCHLIST") for i in range(7)]
    sent = _setup(monkeypatch, buys, {f"T{i}.NS": ("BUY" if i == 6 else "WATCH") for i in range(7)})
    monkeypatch.setattr(ca, "_verdict_of",
                        lambda b: (("BUY", 79) if b["ticker"] == "T6.NS" else ("WATCH", 60)))
    assert ca.check_delivery_digest({}, "2026-10-02", max_picks=5) == 1
    msg = sent[0]
    _assert_descriptive(msg)
    also = next(ln for ln in msg.splitlines() if ln.startswith("Also BUY"))
    assert "<b>T6</b>" in also and "T5" not in also


def test_digest_shows_sl_tp_and_escapes_html(monkeypatch):
    buys = [dict(_pick("J&KBANK.NS", 72, "BUY"), entry=140.0)]
    sent = _setup(monkeypatch, buys, {"J&KBANK.NS": "WATCH"})
    monkeypatch.setattr(ca, "_verdict_of", lambda b: ("WATCH", 60))
    assert ca.check_delivery_digest({}, "2026-10-02") == 1
    assert "J&amp;KBANK" in sent[0] and "J&KBANK" not in sent[0]
    assert "WATCH  <b>J&amp;KBANK</b>  ₹100.00 · stop ₹95.00 · target ₹110.00" in sent[0]


def test_test_digest_ignores_staleness_and_saves_nothing(monkeypatch):
    import trade_store
    sent = _setup(monkeypatch, [_pick("AAA.NS", 58, "WATCHLIST")], {"AAA.NS": "WATCH"}, age_h=40)
    saved = []
    monkeypatch.setattr(trade_store, "kv_set", lambda *a, **k: saved.append(a), raising=False)
    monkeypatch.setattr(ca, "_verdict_of", lambda b: ("WATCH", 60))
    assert ca.check_test_digest({}, "2026-10-03") == 1
    assert sent[0].startswith("🧪") and "TEST" in sent[0] and not saved


def test_digest_67_score_reads_the_app_word(monkeypatch):
    """Audit 2026-11-25 F2: a 67/90 BUY reads BUY in the digest, as on the app's pick card."""
    from tests.test_alert_copy_no_advice import _assert_descriptive
    buys = [_pick("HI.NS", 74, "BUY"), _pick("MID.NS", 67, "BUY")]
    sent = _setup(monkeypatch, buys, {"HI.NS": "BUY", "MID.NS": "BUY"})
    monkeypatch.setattr(ca, "_verdict_of", lambda b: ("BUY", 80))
    assert ca.check_delivery_digest({}, "2026-10-02") == 1
    msg = sent[0]
    _assert_descriptive(msg)
    assert "WATCH, not BUY" not in msg
    assert "BUY  <b>MID</b>  ₹100.00 · stop ₹95.00 · target ₹110.00" in msg


def test_digest_buy_without_stop_goes_out_as_watch(monkeypatch):
    """Audit F5: never a BUY without a stop; no stop at all -> WATCH + note."""
    buys = [dict(_pick("NOSL.NS", 75, "BUY"), sl=None)]
    sent = _setup(monkeypatch, buys, {"NOSL.NS": "BUY"})
    monkeypatch.setattr(ca, "_verdict_of", lambda b: ("BUY", 80))
    assert ca.check_delivery_digest({}, "2026-10-02") == 1
    head = next(ln for ln in sent[0].splitlines() if "NOSL</b>" in ln)
    assert head.startswith("WATCH  <b>NOSL</b>") and "no stop available" in head
    assert "BUY  <b>NOSL" not in sent[0] and "risk " not in sent[0]


def test_stock_line_never_prints_a_buy_without_a_stop():
    for stop in (None, "", 0, "x", -1):
        line = ca._stock_line("BUY", "AAA", 100.0, stop, 110.0)
        assert line.startswith("WATCH  <b>AAA</b>") and "no stop available" in line
    assert ca._stock_line("STRONG BUY", "AAA", 100.0, None).startswith("WATCH")
    assert ca._stock_line("BUY", "AAA", 100.0, 95.0, 110.0) == \
        "BUY  <b>AAA</b>  ₹100.00 · stop ₹95.00 · target ₹110.00"
    assert ca._stock_line("SELL", "AAA", 100.0) == "SELL  <b>AAA</b>  ₹100.00"   # non-BUY untouched


def test_verdict_alert_uses_the_app_stop_field(monkeypatch):
    """The stop comes from the same snapshot field the pick card shows (sl, else stop_loss)."""
    b = dict(_pick("ALT.NS", 75, "BUY"), sl=None, stop_loss=93.0)
    sent = _setup(monkeypatch, [b], {"ALT.NS": "BUY"})
    assert ca.check_verdict_alerts({}, "2026-10-02") == 1
    assert "BUY  <b>ALT</b>  ₹100.00 · stop ₹93.00" in sent[0]


def test_digest_uses_the_verdict_word_and_one_footer(monkeypatch):
    sent = _setup(monkeypatch, [_pick("BBB.NS", 72, "BUY")], {"BBB.NS": "BUY"})
    monkeypatch.setattr(ca, "_verdict_of", lambda b: ("STRONG BUY", 79))
    ca.check_delivery_digest({}, "2026-10-02")
    assert "STRONG BUY  <b>BBB</b>  ₹100.00 · stop ₹95.00" in sent[0]
    assert sent[0].splitlines()[-1] == ca._FOOTER and "(79)" not in sent[0]


def test_scan_label_date_only_where_asked():
    gen = "2026-10-01T17:23:13+00:00"                      # 22:53 IST, Thu 1 Oct
    assert ca._snapshot_ist_label(gen) == "22:53 IST"
    assert ca._snapshot_ist_label(gen, with_date=True) == "22:53 IST, Thu 1 Oct"
    assert ca._snapshot_ist_label("garbage", with_date=True) == "unknown time"


def test_digest_and_test_header_show_scan_date(monkeypatch):
    import trade_store
    sent = _setup(monkeypatch, [_pick("AAA.NS", 72, "BUY")], {"AAA.NS": "BUY"}, age_h=40)
    monkeypatch.setattr(trade_store, "kv_set", lambda *a, **k: None, raising=False)
    monkeypatch.setattr(ca, "_verdict_of", lambda b: ("WATCH", 60))
    assert ca.check_test_digest({}, "2026-10-05") == 1
    hdr = sent[0].splitlines()[0]
    # "🧪 TEST — Morning Digest (last saved scan, may be stale) · scan at HH:MM IST, Ddd D Mon"
    import re
    assert "may be stale" in hdr
    assert re.search(r"scan at \d\d:\d\d IST, [A-Z][a-z]{2} \d{1,2} [A-Z][a-z]{2}$", hdr)


def _setup_full(monkeypatch, buys, all_scored, verdicts, *, same_scan=True):
    sent = _setup(monkeypatch, buys, verdicts)
    import trade_store
    snap = trade_store.kv_get("top_picks_snapshot")
    full = {"generated_at": snap["generated_at"] if same_scan else "2020-01-01T00:00:00+00:00",
            "data": {p["ticker"]: p for p in all_scored}}
    monkeypatch.setattr(trade_store, "kv_get",
                        lambda key, **k: full if key == "all_scored_snapshot" else snap)
    return sent


def test_reads_buy_names_beyond_the_shortlist(monkeypatch):
    buys = [_pick("AAA.NS", 70, "STRONG BUY")]
    rest = [buys[0], _pick("DDD.NS", 71, "BUY"), _pick("EEE.NS", 50, "WATCHLIST")]
    sent = _setup_full(monkeypatch, buys, rest,
                       {"AAA.NS": "STRONG BUY", "DDD.NS": "BUY", "EEE.NS": "BUY"})
    assert ca.check_verdict_alerts({}, "2026-10-02") == 2      # EEE's action is not BUY
    assert len(sent) == 1 and "AAA" in sent[0] and "DDD" in sent[0] and "EEE" not in sent[0]


def test_ignores_full_map_from_another_scan(monkeypatch):
    sent = _setup_full(monkeypatch, [], [_pick("DDD.NS", 71, "BUY")], {"DDD.NS": "BUY"},
                       same_scan=False)
    assert ca.check_verdict_alerts({}, "2026-10-02") == 0 and not sent


def test_per_run_cap_then_rest_next_run(monkeypatch):
    rest = [_pick(f"X{i}.NS", 70 + i, "BUY") for i in range(ca._VERDICT_MAX_PER_RUN + 3)]
    _setup_full(monkeypatch, [], rest, {p["ticker"]: "BUY" for p in rest})
    state = {}
    assert ca.check_verdict_alerts(state, "2026-10-02") == ca._VERDICT_MAX_PER_RUN
    assert ca.check_verdict_alerts(state, "2026-10-02") == min(3, ca._VERDICT_MAX_PER_DAY - ca._VERDICT_MAX_PER_RUN)


def test_daily_cap_across_runs(monkeypatch):
    rest = [_pick(f"Y{i}.NS", 70 + i % 15, "BUY") for i in range(30)]
    _setup_full(monkeypatch, [], rest, {p["ticker"]: "BUY" for p in rest})
    state = {}
    assert ca.check_verdict_alerts(state, "2026-11-09") == ca._VERDICT_MAX_PER_RUN
    assert ca.check_verdict_alerts(state, "2026-11-09") == ca._VERDICT_MAX_PER_DAY - ca._VERDICT_MAX_PER_RUN
    assert ca.check_verdict_alerts(state, "2026-11-09") == 0
    assert ca.check_verdict_alerts(state, "2026-11-10") == ca._VERDICT_MAX_PER_RUN   # new day


def test_combined_message_escapes_html(monkeypatch):
    sent = _setup(monkeypatch, [_pick("M&M.NS", 70, "STRONG BUY")], {"M&M.NS": "STRONG BUY"})
    assert ca.check_verdict_alerts({}, "2026-10-02") == 1
    assert "M&amp;M" in sent[0] and "1 new BUY call</b>" in sent[0]


def test_buy_verdict_under_70_is_sent_as_the_app_shows_it(monkeypatch):
    """Audit F2: no alert-only floor; a 66/90 BUY is a BUY call, as on Command Centre."""
    buys = [_pick("HI.NS", 74, "BUY"), _pick("LO.NS", 66, "BUY"), _pick("EDGE.NS", 70, "BUY")]
    sent = _setup(monkeypatch, buys, {"HI.NS": "BUY", "LO.NS": "BUY", "EDGE.NS": "BUY"})
    state = {}
    assert ca.check_verdict_alerts(state, "2026-10-02") == 3
    assert "3 new BUY calls" in sent[0] and "BUY  <b>LO</b>" in sent[0]
    assert state.get("verdict_buy_LO") == "2026-10-02"           # same dedupe key as before
    assert not hasattr(ca, "_floor_word")
