"""2026-09-24 scoring changes (docs/SCORE_EFFICACY_2026-09-24.md):
bear-regime momentum variant ON by default (cached live regime) and the VIX
sub-component of Sentiment held neutral."""
import analysis.score as sc


def test_regime_weights_default_on(monkeypatch):
    monkeypatch.delenv("NSE_USE_REGIME_WEIGHTS", raising=False)
    assert sc._regime_weights_enabled() is True
    for off in ("0", "false", "off", "no"):
        monkeypatch.setenv("NSE_USE_REGIME_WEIGHTS", off)
        assert sc._regime_weights_enabled() is False


def test_live_regime_label_cached(monkeypatch):
    calls = {"n": 0}

    class _Snap:
        label = "trend_down"

    def fake_snap():
        calls["n"] += 1
        return _Snap()

    import analysis.regime as rg
    monkeypatch.setattr(rg, "snapshot_live", fake_snap)
    monkeypatch.setattr(sc, "_REGIME_LABEL_CACHE", {"t": 0.0, "label": None, "ok": False})
    t = {"now": 1000.0}
    monkeypatch.setattr(sc._regime_time, "time", lambda: t["now"])

    assert sc._live_regime_label() == "trend_down"
    assert sc._live_regime_label() == "trend_down"
    assert calls["n"] == 1                      # served from cache
    t["now"] += sc._REGIME_TTL_OK + 1
    sc._live_regime_label()
    assert calls["n"] == 2                      # refreshed after TTL


def test_live_regime_failure_retries_after_short_ttl(monkeypatch):
    calls = {"n": 0}

    def boom():
        calls["n"] += 1
        raise RuntimeError("network")

    import analysis.regime as rg
    monkeypatch.setattr(rg, "snapshot_live", boom)
    monkeypatch.setattr(sc, "_REGIME_LABEL_CACHE", {"t": 0.0, "label": None, "ok": False})
    t = {"now": 1000.0}
    monkeypatch.setattr(sc._regime_time, "time", lambda: t["now"])

    assert sc._live_regime_label() is None
    sc._live_regime_label()
    assert calls["n"] == 1                      # negative-cached
    t["now"] += sc._REGIME_TTL_FAIL + 1
    sc._live_regime_label()
    assert calls["n"] == 2


def test_vix_points_identical_across_regimes():
    regimes = ["complacency", "normal", "elevated", "fear", "panic", "unknown"]
    legacy = {sc._score_sentiment({"regime": r}, 7)[1]["vix"] for r in regimes}
    flows = {sc._score_sentiment({"regime": r}, 7, flows_info={"fii_5d": 1.0, "dii_5d": 1.0})[1]["vix"]
             for r in regimes}
    assert legacy == {6.0}
    assert flows == {5.0}
    # Still reported for context.
    assert sc._score_sentiment({"regime": "fear"}, 7)[1]["vix_regime"] == "fear"
