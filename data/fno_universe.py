"""
data/fno_universe.py – NSE F&O-eligible universe.

Recommendation 6 (design 6a) of docs/COMPOSITE_SCORE_SHAPE_REVIEW.md
adds a Positioning pillar to the composite score. The pillar only
applies to F&O-eligible names — non-F&O names keep the legacy 4-pillar
40+25+15+10=90 shape because their positioning inputs (options OI,
PCR, max pain, FII index-futures) do not exist by construction.

This module is the source of truth for that eligibility check.

DATA
────
NSE publishes the F&O eligibility list in monthly circulars. This starter
list is the Nifty-50 + Bank-Nifty + top mid-caps that have been F&O-eligible
continuously through 2025-26. It intentionally errs SMALL (~60 names) so
Recommendation 6 activates on the tickers where the data quality is best.

FOLLOW-UP: refresh from the most recent NSE circular (typically monthly).
See docs/POSITIONING_INTEGRATION_2026-09.md for the process.
"""
from __future__ import annotations

from typing import Iterable, Set

# ── F&O-eligible starter list (Nifty-50 + high-volume mid-caps) ─────────────
# Tickers stored WITHOUT the .NS suffix; the checker normalises both forms.
_FNO_TICKERS: Set[str] = frozenset({
    # Nifty 50 (core)
    "ADANIENT", "ADANIPORTS", "APOLLOHOSP", "ASIANPAINT", "AXISBANK",
    "BAJAJ-AUTO", "BAJAJFINSV", "BAJFINANCE", "BEL", "BHARTIARTL",
    "BPCL", "BRITANNIA", "CIPLA", "COALINDIA", "DIVISLAB",
    "DRREDDY", "EICHERMOT", "GRASIM", "HCLTECH", "HDFCBANK",
    "HDFCLIFE", "HEROMOTOCO", "HINDALCO", "HINDUNILVR", "ICICIBANK",
    "INDUSINDBK", "INFY", "ITC", "JIOFIN", "JSWSTEEL",
    "KOTAKBANK", "LT", "LTIM", "M&M", "MARUTI",
    "NESTLEIND", "NTPC", "ONGC", "POWERGRID", "RELIANCE",
    "SBILIFE", "SBIN", "SHRIRAMFIN", "SUNPHARMA", "TATACONSUM",
    "TATAMOTORS", "TATASTEEL", "TCS", "TECHM", "TITAN",
    "TRENT", "ULTRACEMCO", "UPL", "WIPRO",
    # Bank Nifty additions
    "BANDHANBNK", "FEDERALBNK", "IDFCFIRSTB", "PNB", "RBLBANK",
    # High-conviction mid-caps continuously F&O since 2023
    "ABB", "ABFRL", "ACC", "AMBUJACEM", "ASHOKLEY",
    "AUROPHARMA", "BALKRISIND", "BANKBARODA", "BHEL", "BIOCON",
    "BOSCHLTD", "CANBK", "CHOLAFIN", "COLPAL", "CONCOR",
    "CUMMINSIND", "DABUR", "DALBHARAT", "DEEPAKNTR", "DIXON",
    "GAIL", "GODREJCP", "GODREJPROP", "HAVELLS", "HDFCAMC",
    "ICICIGI", "ICICIPRULI", "IDEA", "IEX", "IGL",
    "INDHOTEL", "INDIGO", "IOC", "IPCALAB", "IRCTC",
    "JINDALSTEL", "JUBLFOOD", "LAURUSLABS", "LICHSGFIN", "LICI",
    "LTTS", "LUPIN", "MANAPPURAM", "MARICO", "MFSL",
    "MOTHERSON", "MPHASIS", "NAM-INDIA", "NAUKRI", "NAVINFLUOR",
    "NMDC", "OBEROIRLTY", "OFSS", "PAGEIND", "PEL",
    "PERSISTENT", "PETRONET", "PFC", "PIDILITIND", "PIIND",
    "PNBHOUSING", "POLYCAB", "RECLTD", "SAIL", "SBICARD",
    "SIEMENS", "SRF", "SUNTV", "SYNGENE", "TATACHEM",
    "TATACOMM", "TATAPOWER", "TIINDIA", "TORNTPHARM", "TORNTPOWER",
    "TVSMOTOR", "UBL", "VBL", "VEDL", "VOLTAS", "ZYDUSLIFE",
})


def _normalize(ticker: str) -> str:
    """Strip .NS suffix and uppercase. Handles either shape safely."""
    if not ticker:
        return ""
    t = str(ticker).upper().strip()
    if t.endswith(".NS"):
        t = t[:-3]
    return t


def is_fno_eligible(ticker: str) -> bool:
    """True when the ticker is F&O-eligible per the starter universe.

    Non-F&O names skip Recommendation 6's Positioning pillar entirely
    and keep the legacy 4-pillar 40+25+15+10=90 shape.
    """
    return _normalize(ticker) in _FNO_TICKERS


def list_fno_tickers() -> Set[str]:
    """Return the full F&O-eligible set (without .NS suffix)."""
    return set(_FNO_TICKERS)


def add_fno_tickers(extra: Iterable[str]) -> None:
    """Extend the in-process F&O set — for tests and one-off overrides.

    Persistent additions should edit _FNO_TICKERS above and land as a
    commit with the source NSE circular referenced in the message.
    """
    global _FNO_TICKERS
    _FNO_TICKERS = frozenset(_FNO_TICKERS | {_normalize(t) for t in extra if t})
