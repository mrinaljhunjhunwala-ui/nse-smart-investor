"""Concrete FundamentalProvider adapters. Phase 0 ships only Yahoo Finance."""
from .yahoo_fundamentals import YahooFundamentalProvider

__all__ = ["YahooFundamentalProvider"]
