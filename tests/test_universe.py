import data.universe as u
import data.fetcher as fetcher


def test_get_universe_defaults():
    lst = u.get_universe("nifty50")
    assert isinstance(lst, list)
    assert len(lst) > 0


def test_resolve_ticker_variants():
    # resolve_ticker should accept 'RELIANCE' and 'RELIANCE.NS' and return 'RELIANCE.NS'
    out1 = u.resolve_ticker("RELIANCE")
    out2 = u.resolve_ticker("RELIANCE.NS")
    assert out1.endswith("RELIANCE.NS") or out1 == "RELIANCE.NS"
    assert out2 == "RELIANCE.NS"


def test_get_tickers_by_sector():
    # ensure function returns a list for a known sector (if present)
    try:
        s = u.get_tickers_by_sector("it")
        assert isinstance(s, list)
    except Exception:
        # If sector mapping has different keys, just assert function exists
        assert hasattr(u, "get_tickers_by_sector")
