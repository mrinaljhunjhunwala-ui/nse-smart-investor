"""``?ticker=`` deep-link parsing (no Streamlit imports)."""
from __future__ import annotations

import re

_TICKER_RE = re.compile(r"^[A-Z0-9&\-]{1,20}(\.NS|\.BO)?$")


def normalise_ticker_param(raw) -> str | None:
    """Upper-case and add .NS when no exchange suffix; None if empty/invalid."""
    if isinstance(raw, (list, tuple)):
        raw = raw[0] if raw else None
    if not isinstance(raw, str):
        return None
    sym = raw.strip().upper()
    if not sym or not _TICKER_RE.match(sym):
        return None
    return sym if sym.endswith((".NS", ".BO")) else sym + ".NS"


def parse_ticker_list(raw: str) -> list[str]:
    """Split a pasted comma/newline list into Yahoo tickers.

    Bare NSE symbols ("RELIANCE") get ``.NS`` so the scan finds them;
    symbols that already carry an exchange suffix or are indices
    (``^NSEI``) pass through unchanged. Duplicates are dropped, order kept.
    """
    out: list[str] = []
    for part in str(raw or "").replace("\n", ",").split(","):
        sym = part.strip().upper()
        if not sym:
            continue
        if not sym.startswith("^") and "." not in sym:
            sym = normalise_ticker_param(sym) or sym
        if sym not in out:
            out.append(sym)
    return out
