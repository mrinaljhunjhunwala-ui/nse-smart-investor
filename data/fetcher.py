"""
data/fetcher.py

Single-entry fetcher that tries multiple providers in order. On complete
failure it raises ValueError with aggregated provider diagnostics (tests
expect a ValueError when all providers fail).
"""

from __future__ import annotations
import logging
from typing import Optional
import pandas as pd

_log = logging.getLogger("data.fetcher")


def fetch_single(ticker: str, period: Optional[str] = None, interval: Optional[str] = None) -> pd.DataFrame:
    """
    Try multiple providers for historical OHLCV data in preferred order.

    Providers attempted (if available in the repo / environment):
      1. data.angel_fetcher.fetch_historical
      2. data.stooq_fetcher.fetch_historical
      3. data.yahoo_fetcher.fetch_historical

    Collects errors from each provider and, if none succeed, raises ValueError
    with the aggregated messages so callers/tests can assert the failure reason.
    """
    errors = []

    # Provider 1: Angel (repo may or may not have it)
    try:
        from data.angel_fetcher import fetch_historical as _angel_fetch  # type: ignore
        try:
            res = _angel_fetch(ticker, period=period, interval=interval)
            if isinstance(res, pd.DataFrame) and not res.empty:
                return res
            # If the provider returns an empty DataFrame treat as failure here
            if res is None or (isinstance(res, pd.DataFrame) and res.empty):
                errors.append("Angel: returned no data")
            else:
                # Accept non-empty non-DataFrame (rare) — try to coerce
                try:
                    df = pd.DataFrame(res)
                    if not df.empty:
                        return df
                    errors.append("Angel: returned non-tabular data")
                except Exception as e:
                    errors.append(f"Angel: returned unexpected type: {type(res).__name__}: {e}")
        except Exception as e:
            errors.append(f"Angel: {type(e).__name__}: {e}")
    except Exception:
        errors.append("Angel: not available")

    # Provider 2: stooq
    try:
        from data.stooq_fetcher import fetch_historical as _stooq_fetch  # type: ignore
        try:
            res = _stooq_fetch(ticker, period=period)
            if isinstance(res, pd.DataFrame) and not res.empty:
                return res
            if res is None or (isinstance(res, pd.DataFrame) and res.empty):
                errors.append("Stooq: returned no data")
            else:
                try:
                    df = pd.DataFrame(res)
                    if not df.empty:
                        return df
                    errors.append("Stooq: returned non-tabular data")
                except Exception as e:
                    errors.append(f"Stooq: returned unexpected type: {type(res).__name__}: {e}")
        except Exception as e:
            errors.append(f"Stooq: {type(e).__name__}: {e}")
    except Exception:
        errors.append("Stooq: not available")

    # Provider 3: yahoo
    try:
        from data.yahoo_fetcher import fetch_historical as _yahoo_fetch  # type: ignore
        try:
            res = _yahoo_fetch(ticker, period=period, interval=interval)
            if isinstance(res, pd.DataFrame) and not res.empty:
                return res
            if res is None or (isinstance(res, pd.DataFrame) and res.empty):
                errors.append("Yahoo: returned no data")
            else:
                try:
                    df = pd.DataFrame(res)
                    if not df.empty:
                        return df
                    errors.append("Yahoo: returned non-tabular data")
                except Exception as e:
                    errors.append(f"Yahoo: returned unexpected type: {type(res).__name__}: {e}")
        except Exception as e:
            errors.append(f"Yahoo: {type(e).__name__}: {e}")
    except Exception:
        errors.append("Yahoo: not available")

    # If a repo-specific consolidated provider exists, try it
    try:
        from data._fetcher_impl import fetch_single as _impl  # type: ignore
        try:
            res = _impl(ticker, period=period, interval=interval)
            if isinstance(res, pd.DataFrame) and not res.empty:
                return res
            if res is None or (isinstance(res, pd.DataFrame) and res.empty):
                errors.append("_impl: returned no data")
            else:
                try:
                    df = pd.DataFrame(res)
                    if not df.empty:
                        return df
                    errors.append("_impl: returned non-tabular data")
                except Exception as e:
                    errors.append(f"_impl: returned unexpected type: {type(res).__name__}: {e}")
        except Exception as e:
            errors.append(f"_impl: {type(e).__name__}: {e}")
    except Exception:
        # not present is fine; ignore
        pass

    # All providers failed — raise ValueError with aggregated reasons
    msg = "All providers failed for ticker '{}': {}".format(ticker, "; ".join(errors) if errors else "no providers attempted")
    _log.debug("fetch_single failure: %s", msg)
    raise ValueError(msg )
