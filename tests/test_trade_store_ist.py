"""Trade timestamps are IST wall-clock even when the server runs in UTC."""
import datetime as dt

import trade_store as ts


def test_now_ist_iso_is_utc_plus_530():
    utc = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    got = dt.datetime.fromisoformat(ts._now_ist_iso())
    assert abs((got - utc) - dt.timedelta(hours=5, minutes=30)) < dt.timedelta(seconds=5)
    assert got.tzinfo is None            # same naive format the trades table already holds
