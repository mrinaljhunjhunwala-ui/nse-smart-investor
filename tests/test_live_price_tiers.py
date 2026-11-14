"""Live-quote tiers: a NaN / zero / null "price" from one tier must not stop
the next tier, and the dead Stooq tier costs no request unless switched on."""
from __future__ import annotations

import datetime

import pytest

import utils.live_price as lp


@pytest.fixture
def no_angel(monkeypatch):
    import data.angel_fetcher as af
    monkeypatch.setattr(af, "is_configured", lambda: False)


@pytest.mark.parametrize("bad", [
    {"price": float("nan"), "prev_close": 99.0}, {"price": 0, "prev_close": 99.0},
    {"price": None}, {"price": "n/a"}, {},
])
def test_unusable_price_falls_through_to_next_tier(monkeypatch, no_angel, bad):
    monkeypatch.setattr(lp, "_yahoo_json_quote", lambda t: dict(bad))
    monkeypatch.setattr(lp, "_nse_live_price", lambda s: {"price": 101.0, "prev_close": 100.0})
    monkeypatch.setattr(lp, "_stooq_eod_price", lambda t: None)
    q = lp.get_live_quote("VEDL")
    assert q["price"] == 101.0 and q["chg_pct"] == pytest.approx(1.0)
    assert lp.get_live_prices_batch(["VEDL"])["VEDL"]["price"] == 101.0


def test_nan_angel_quote_falls_through(monkeypatch):
    import data.angel_fetcher as af
    monkeypatch.setattr(af, "is_configured", lambda: True)
    monkeypatch.setattr(af, "get_full_quote",
                        lambda t: {"price": float("nan"), "prev_close": 1.0, "chg_pct": 0.0})
    monkeypatch.setattr(lp, "_yahoo_json_quote", lambda t: {"price": 55.0, "prev_close": 50.0})
    assert lp.get_live_quote("PFC.NS")["price"] == 55.0


def test_all_tiers_unusable_returns_none(monkeypatch, no_angel):
    for name in ("_yahoo_json_quote", "_nse_live_price", "_stooq_eod_price"):
        monkeypatch.setattr(lp, name, lambda a: {"price": float("nan")})
    assert lp.get_live_quote("X") is None


@pytest.mark.parametrize("prev", [float("nan"), 0, None, "bad"])
def test_normalise_bad_prev_close_gives_zero_change(prev):
    out = lp._normalise({"price": 100.0, "prev_close": prev})
    assert out["prev_close"] == 100.0 and out["chg_pct"] == 0.0


def test_stooq_tier_makes_no_request_when_switched_off(monkeypatch):
    monkeypatch.delenv("NSE_ENABLE_STOOQ", raising=False)
    monkeypatch.setattr(lp.urllib.request, "urlopen",
                        lambda *a, **k: pytest.fail("Stooq request made while the tier is off"))
    assert lp._stooq_eod_price("RELIANCE.NS") is None


def test_alert_timestamp_is_real_ist(monkeypatch):
    """The alert jobs run on UTC runners; the "IST" label must be IST."""
    import utils.snapshot_time as st_mod
    import utils.telegram as tg

    sent = []
    alerter = tg.TelegramAlerter(token="t", chat_id="c")
    monkeypatch.setattr(alerter, "_send", lambda text, *a, **k: sent.append(text) or True)
    alerter.send_signal("RELIANCE.NS", "BUY", 100.0)
    expected = st_mod.ist_now()
    stamps = {(expected - datetime.timedelta(minutes=m)).strftime("%d %b %Y  %H:%M IST") for m in (0, 1)}
    assert any(s in sent[0] for s in stamps)
    assert st_mod.ist_now().utcoffset() == datetime.timedelta(hours=5, minutes=30)


def test_telegram_alerter_strips_token_and_chat_id(monkeypatch):
    """A secret saved with a trailing newline must not end up in the request URL (Telegram 404)."""
    from utils.telegram import TelegramAlerter
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc\n")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", " 42 \n")
    a = TelegramAlerter()
    assert a.token == "123:abc" and a.chat_id == "42" and not a._console_only
