"""Index symbols skip the Angel One tier (no EQ token; failures tripped its breaker)."""
import pandas as pd

import data.angel_fetcher as af
import data.fetcher as f


def test_index_symbol_never_calls_angel(monkeypatch):
    calls = []
    monkeypatch.setattr(af, "is_configured", lambda: True)
    monkeypatch.setattr(af, "fetch_historical", lambda t, **k: calls.append(t) or pd.DataFrame())
    monkeypatch.setattr(f, "_stooq_enabled", lambda: False)
    monkeypatch.setattr(f, "_cache_get", lambda *a: None)
    try:
        f.fetch_single("^NSEI", period="1mo")
    except Exception:
        pass                     # later tiers are offline in tests; only Angel matters here
    assert calls == []
