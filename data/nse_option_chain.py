"""
data/nse_option_chain.py – NSE per-symbol options chain: PCR + max pain.

Feeds the PCR and max-pain-distance sub-scores (2 pts each, 4 pts combined)
inside Recommendation 6's Positioning pillar. See
docs/POSITIONING_INTEGRATION_2026-09.md.

Third and fourth of the four Positioning-pillar data pipelines. Biggest
by data-engineering effort because the source is a per-symbol API endpoint
(not a single daily file), rate-limited from cloud IPs.

WHY
───
PCR (Put OI / Call OI) is a contrarian sentiment gauge. Extremes matter,
not the level: PCR < 0.6 = extreme complacency (contrarian bearish);
PCR > 1.5 = extreme fear (contrarian bullish). Middle values are noise.

Max pain is the strike where option writers lose the least at expiry;
price tends to pin toward it in the last few sessions of an expiry cycle.
Distance-from-max-pain in % tells you how much room the price has before
the pin effect kicks in — > 3% is a healthy runway, < 1% is at-the-pin
(more chop risk).

WHERE THE DATA COMES FROM
─────────────────────────
NSE's public options-chain API:
  https://www.nseindia.com/api/option-chain-equities?symbol=<SYM>

Returns JSON: records[].data[] with per-strike CE and PE dicts containing
openInterest, lastPrice, strikePrice, expiryDate, and the underlying
close (records.underlyingValue).

Rate limits: cloud IPs get 403 within a burst; residential IPs handle
~10 symbols in a 2-second gap comfortably. Prime the session with a
cookie fetch to nseindia.com first, otherwise NSE returns HTML.

PIPELINE
────────
scripts/fetch_nse_option_chain.py --tickers SYM1 SYM2 ...  (or --fno-all)
  -> per-symbol GET + parse + persist
    -> trade_store nse_option_chain_daily (PK symbol,date)
      -> get_pcr(sym) / get_max_pain_pct(sym) reads latest row

MUST RUN FROM RESIDENTIAL IP - same NSE-WAF constraint as
nse_delivery / nse_fno_bhavcopy / nse_fii_deriv.
"""
from __future__ import annotations

import datetime as _dt
import json
import logging
import time
from typing import Dict, List, Optional, Tuple

import pandas as pd
import requests

import trade_store as _store

_log = logging.getLogger("data.nse_option_chain")

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/122.0 Safari/537.36")
_TIMEOUT = 15
_PRIME_URL = "https://www.nseindia.com/option-chain"
# FIX OC-V3 (2026-09-04): NSE retired /api/option-chain-equities. The current
# live option-chain page fetches /api/option-chain-v3 with an explicit
# expiry parameter; the old endpoint now returns HTTP 200 + `{}` to every
# caller regardless of cookie state (verified from real Chrome with 2166
# bytes of Akamai cookies).
_CONTRACT_INFO_TPL = "https://www.nseindia.com/api/option-chain-contract-info?symbol={sym}"
_API_TPL           = "https://www.nseindia.com/api/option-chain-v3?type=Equity&symbol={sym}&expiry={expiry}"

_schema_ready_for: Optional[str] = None


# ─────────────────────────────────────────────────────────────────────────────
# Storage
# ─────────────────────────────────────────────────────────────────────────────

def ensure_schema() -> None:
    global _schema_ready_for
    key = _store._database_url() or _store._SQLITE_PATH
    if _schema_ready_for == key:
        return
    real = "DOUBLE PRECISION" if _store._is_pg() else "REAL"
    with _store._get_conn() as conn:
        cur = conn.cursor()
        cur.execute(f"""
            CREATE TABLE IF NOT EXISTS nse_option_chain_daily (
                symbol             TEXT NOT NULL,
                date               TEXT NOT NULL,
                spot               {real},
                nearest_expiry     TEXT,
                total_ce_oi        {real},
                total_pe_oi        {real},
                pcr                {real},
                max_pain_strike    {real},
                max_pain_pct       {real},
                n_strikes          INTEGER,
                fetched_at         TEXT,
                PRIMARY KEY (symbol, date)
            )
        """)
        conn.commit()
    _schema_ready_for = key


def _persist(rows: List[Dict]) -> int:
    if not rows:
        return 0
    ensure_schema()
    now = _dt.datetime.now().isoformat(timespec="seconds")
    n = 0
    with _store._get_conn() as conn:
        cur = conn.cursor()
        for r in rows:
            try:
                params = (r["symbol"], r["date"], r.get("spot"),
                          r.get("nearest_expiry"), r.get("total_ce_oi"),
                          r.get("total_pe_oi"), r.get("pcr"),
                          r.get("max_pain_strike"), r.get("max_pain_pct"),
                          r.get("n_strikes"), now)
                if _store._is_pg():
                    cur.execute(_store._q("""
                        INSERT INTO nse_option_chain_daily
                          (symbol,date,spot,nearest_expiry,total_ce_oi,
                           total_pe_oi,pcr,max_pain_strike,max_pain_pct,
                           n_strikes,fetched_at)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?)
                        ON CONFLICT (symbol,date) DO UPDATE SET
                          spot=EXCLUDED.spot,
                          nearest_expiry=EXCLUDED.nearest_expiry,
                          total_ce_oi=EXCLUDED.total_ce_oi,
                          total_pe_oi=EXCLUDED.total_pe_oi,
                          pcr=EXCLUDED.pcr,
                          max_pain_strike=EXCLUDED.max_pain_strike,
                          max_pain_pct=EXCLUDED.max_pain_pct,
                          n_strikes=EXCLUDED.n_strikes,
                          fetched_at=EXCLUDED.fetched_at
                    """), params)
                else:
                    cur.execute("""
                        INSERT INTO nse_option_chain_daily
                          (symbol,date,spot,nearest_expiry,total_ce_oi,
                           total_pe_oi,pcr,max_pain_strike,max_pain_pct,
                           n_strikes,fetched_at)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?)
                        ON CONFLICT(symbol,date) DO UPDATE SET
                          spot=excluded.spot,
                          nearest_expiry=excluded.nearest_expiry,
                          total_ce_oi=excluded.total_ce_oi,
                          total_pe_oi=excluded.total_pe_oi,
                          pcr=excluded.pcr,
                          max_pain_strike=excluded.max_pain_strike,
                          max_pain_pct=excluded.max_pain_pct,
                          n_strikes=excluded.n_strikes,
                          fetched_at=excluded.fetched_at
                    """, params)
                n += 1
            except Exception as e:
                _log.debug("_persist row failed for %s %s: %s",
                           r.get("symbol"), r.get("date"), e)
        conn.commit()
    return n


# ─────────────────────────────────────────────────────────────────────────────
# Parser  +  math helpers  (pure — canary-testable offline)
# ─────────────────────────────────────────────────────────────────────────────

def compute_pcr(total_ce_oi: float, total_pe_oi: float) -> Optional[float]:
    """Put-Call Ratio. Returns None when total_ce_oi is zero (undefined)."""
    if total_ce_oi is None or total_pe_oi is None or total_ce_oi <= 0:
        return None
    return round(float(total_pe_oi) / float(total_ce_oi), 3)


def compute_max_pain(strikes_with_oi: List[Tuple[float, float, float]]) -> Optional[float]:
    """
    Given a list of (strike, ce_oi, pe_oi), return the strike at which
    option writers lose the LEAST if expiry closed there.

    Payoff-to-writers at candidate strike K, summed across every strike S:
        loss_at_K = sum(ce_oi[S] * max(K - S, 0)) + sum(pe_oi[S] * max(S - K, 0))
    Max pain = argmin(loss_at_K).

    Returns the candidate strike with minimum writer loss. None when we
    have fewer than 3 strikes (too thin to be meaningful).
    """
    if not strikes_with_oi or len(strikes_with_oi) < 3:
        return None
    strikes = sorted({s for s, _, _ in strikes_with_oi})
    ce_by_s = {s: ce for s, ce, _ in strikes_with_oi}
    pe_by_s = {s: pe for s, _, pe in strikes_with_oi}
    best_strike = None
    best_loss   = None
    for K in strikes:
        loss = 0.0
        for S in strikes:
            ce = ce_by_s.get(S, 0.0) or 0.0
            pe = pe_by_s.get(S, 0.0) or 0.0
            if K > S:
                loss += ce * (K - S)   # ITM calls hurt writers
            elif K < S:
                loss += pe * (S - K)   # ITM puts hurt writers
        if best_loss is None or loss < best_loss:
            best_loss   = loss
            best_strike = K
    return best_strike


def compute_max_pain_distance_pct(spot: float, max_pain_strike: float) -> Optional[float]:
    """Signed % from max pain to spot: +ve = spot above max pain (bullish
    bias if pin is likely to pull down); -ve = below (bearish bias)."""
    if spot is None or max_pain_strike is None or max_pain_strike <= 0:
        return None
    return round((spot - max_pain_strike) / max_pain_strike * 100, 2)


def _nearest_expiry(expiries: List[str]) -> Optional[str]:
    """Return the earliest expiry date on/after today, from NSE's
    'DD-MMM-YYYY' format. None if all expiries are past."""
    today = _dt.date.today()
    parsed: List[Tuple[_dt.date, str]] = []
    for e in expiries:
        if not e:
            continue
        try:
            d = _dt.datetime.strptime(e, "%d-%b-%Y").date()
        except ValueError:
            continue
        if d >= today:
            parsed.append((d, e))
    if not parsed:
        return None
    parsed.sort()
    return parsed[0][1]


def parse_option_chain(payload: Dict, symbol: str,
                       target_date: Optional[_dt.date] = None) -> Optional[Dict]:
    """
    Parse the raw NSE option-chain JSON payload for one symbol.

    Extracts:
      - spot (records.underlyingValue)
      - nearest expiry
      - PCR + total CE/PE OI across THAT expiry
      - max pain strike + distance %

    Named ValueError on structural drift (Guardrail §14).
    """
    if not payload:
        raise ValueError(f"option chain: empty payload for {symbol}")
    records = (payload or {}).get("records") or {}
    if not records:
        raise ValueError(
            f"option chain: 'records' missing for {symbol} — schema drift?"
        )
    data = records.get("data") or []
    if not data:
        raise ValueError(
            f"option chain: 'records.data' empty for {symbol} — probable "
            f"schema drift or a non-F&O symbol was requested"
        )

    spot = records.get("underlyingValue")
    try:
        spot = float(spot) if spot is not None else None
    except (TypeError, ValueError):
        spot = None

    expiries = records.get("expiryDates") or []
    nearest = _nearest_expiry(expiries)
    if not nearest:
        _log.warning("option chain: no future expiry for %s (got %s)",
                     symbol, expiries[:3])
        return None

    # Aggregate CE/PE OI across the nearest expiry only.
    # FIX OC-V3 (2026-09-04): the v3 endpoint server-side filters by the
    # expiry we passed in the URL, so every row is already for `nearest`.
    # The old v2 filter compared row.get("expiryDate") but v3 uses
    # "expiryDates" (plural) with a different date format ("29-09-2026"
    # inside CE/PE dicts vs "29-Sep-2026" at the top level). Rather than
    # match on either shape, trust the server filter: accept any row that
    # matches EITHER key, OR matches nothing (v3 mode).
    strikes_for_pain: List[Tuple[float, float, float]] = []
    total_ce = 0.0
    total_pe = 0.0
    for row in data:
        if not isinstance(row, dict):
            continue
        # Legacy v2 filter — kept for backwards-compat with test fixtures
        # that still emit `expiryDate` per row. v3 rows lack that key, so
        # this comparison short-circuits to True and the row is included.
        _row_expiry = row.get("expiryDate")
        if _row_expiry is not None and _row_expiry != nearest:
            continue
        strike = row.get("strikePrice")
        try:
            strike = float(strike) if strike is not None else None
        except (TypeError, ValueError):
            continue
        if strike is None:
            continue
        ce_oi = 0.0
        pe_oi = 0.0
        ce = row.get("CE") or {}
        pe = row.get("PE") or {}
        if isinstance(ce, dict):
            try:
                ce_oi = float(ce.get("openInterest") or 0)
            except (TypeError, ValueError):
                ce_oi = 0.0
        if isinstance(pe, dict):
            try:
                pe_oi = float(pe.get("openInterest") or 0)
            except (TypeError, ValueError):
                pe_oi = 0.0
        total_ce += ce_oi
        total_pe += pe_oi
        strikes_for_pain.append((strike, ce_oi, pe_oi))

    if not strikes_for_pain:
        # Guardrail §15: silent-empty is worse than a crash.
        _log.warning(
            "option chain: no rows matched nearest expiry %s for %s "
            "(strikes seen: %d total). Possible schema drift.",
            nearest, symbol, len(data),
        )
        return None

    pcr             = compute_pcr(total_ce, total_pe)
    max_pain_strike = compute_max_pain(strikes_for_pain)
    max_pain_pct    = (compute_max_pain_distance_pct(spot, max_pain_strike)
                       if spot is not None and max_pain_strike is not None
                       else None)

    return {
        "symbol":          symbol.upper(),
        "date":            (target_date or _dt.date.today()).isoformat(),
        "spot":            spot,
        "nearest_expiry":  nearest,
        "total_ce_oi":     total_ce,
        "total_pe_oi":     total_pe,
        "pcr":             pcr,
        "max_pain_strike": max_pain_strike,
        "max_pain_pct":    max_pain_pct,
        "n_strikes":       len(strikes_for_pain),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Fetcher — with session priming
# ─────────────────────────────────────────────────────────────────────────────

# FIX OC-WAF (2026-09-04): NSE's /api/option-chain-equities endpoint now
# actively returns `{}` (2 bytes, HTTP 200) to plain-requests callers even
# after Referer + cookie priming. Confirmed via multi-approach probing:
#   * python-requests with all Chrome headers            -> {}
#   * curl_cffi impersonate=chrome124 with full cookies  -> {}
#   * nsepython (community library with workarounds)     -> {}
# NSE has fully locked this endpoint from scripted access. Working paths:
#   1. curl_cffi + browser TLS fingerprint + AJAX headers may occasionally
#      work when the session first fetches option-chain landing HTML and
#      then hits the API within seconds. We try this path first.
#   2. Manual cookie paste: user opens option-chain page in Chrome, copies
#      the `nseappid` cookie value, saves to .streamlit/secrets.toml under
#      [nse] cookie = "..." — the session then uses it verbatim. Cookies
#      typically last 24-48h before needing a re-paste.
#   3. Playwright (heavy dep) — a real headless browser that solves the
#      Akamai challenge. Not shipped here to avoid the ~150MB dependency;
#      queue as follow-up work if the two paths above prove insufficient.
#
# On {} response we now log a clear DIAGNOSTIC (not a bare "empty payload")
# telling the operator which of the escape hatches to try.

_HAS_CURL_CFFI = False
try:
    from curl_cffi import requests as _cf_requests  # type: ignore
    _HAS_CURL_CFFI = True
except ImportError:
    pass


def _read_manual_cookie() -> Optional[str]:
    """Return a Cookie: header string set by the operator in
    .streamlit/secrets.toml under `[nse] cookie = "..."`. None when absent.
    """
    try:
        import streamlit as st  # local import — module stays streamlit-free
        nse = st.secrets.get("nse")
        if isinstance(nse, dict):
            v = nse.get("cookie")
            if v:
                return str(v)
    except Exception:
        pass
    return None


def _make_session():
    """Build the best session available for the option-chain API.

    Prefers curl_cffi (browser TLS fingerprint mimicry) when installed;
    falls back to plain requests otherwise. Primes with a multi-page GET
    sequence so Akamai sets its full cookie set (AKA_A2 + _abck + ak_bmsc +
    bm_sz + bm_mi + bm_sv). Manually-pasted `nseappid` cookie is merged in
    when present in secrets.toml.
    """
    if _HAS_CURL_CFFI:
        s = _cf_requests.Session(impersonate="chrome124")
    else:
        s = requests.Session()
    s.headers.update({
        "User-Agent":               _UA,
        "Accept":                   "application/json,text/plain,*/*",
        "Accept-Language":          "en-US,en;q=0.9",
        "Referer":                  "https://www.nseindia.com/option-chain",
        "sec-ch-ua":                '"Chromium";v="124", "Not-A.Brand";v="99"',
        "sec-ch-ua-mobile":         "?0",
        "sec-ch-ua-platform":       '"Windows"',
        "sec-fetch-dest":           "empty",
        "sec-fetch-mode":           "cors",
        "sec-fetch-site":           "same-origin",
        "x-requested-with":         "XMLHttpRequest",
    })
    # Multi-step cookie prime — hit homepage + option-chain page, brief pause
    # in between so Akamai's JS-set cookies land.
    try:
        s.get("https://www.nseindia.com/", timeout=_TIMEOUT)
    except Exception as e:
        _log.debug("prime homepage failed: %s", e)
    try:
        s.get(_PRIME_URL, timeout=_TIMEOUT)
    except Exception as e:
        _log.debug("prime option-chain failed: %s", e)

    # Merge any operator-supplied cookie header
    manual = _read_manual_cookie()
    if manual:
        s.headers["Cookie"] = manual
    return s


def _http_get_json(session, url: str) -> Dict:
    """Common GET + parse + WAF-block detection. Raises named ValueError."""
    r = session.get(url, timeout=_TIMEOUT)
    if r.status_code == 404:
        raise ValueError(f"NSE: 404 for {url}")
    r.raise_for_status()
    body = r.content if hasattr(r, "content") else (r.text or "").encode("utf-8")
    if not body.strip():
        raise ValueError(f"NSE: empty response body for {url}")
    if body.lstrip().startswith(b"<"):
        raise ValueError(
            f"NSE returned HTML (not JSON) for {url} — probable rate-limit "
            f"or WAF challenge. Body: {body[:120]!r}"
        )
    if body.strip() in {b"{}", b"[]"}:
        raise ValueError(
            f"NSE returned {body.strip().decode()!r} for {url} — WAF-blocked. "
            f"Install curl_cffi (`pip install curl_cffi`) or paste a browser "
            f"Cookie header into .streamlit/secrets.toml under [nse] cookie."
        )
    try:
        return json.loads(body)
    except json.JSONDecodeError as e:
        raise ValueError(f"NSE: JSON decode failed for {url}: {e}")


def fetch_chain(symbol: str, session=None) -> Dict:
    """Fetch the option chain for one symbol via the v3 endpoint.

    Two-step (FIX OC-V3, 2026-09-04):
      1) GET /api/option-chain-contract-info?symbol=X -> list of expiries
      2) GET /api/option-chain-v3?type=Equity&symbol=X&expiry=<nearest>
    The v3 payload has the same records/data/underlyingValue/expiryDates
    shape as the retired v2 endpoint, so parse_option_chain() is unchanged.

    Raises named ValueError on any failure mode _http_get_json can raise,
    or when contract-info returns no future expiries.
    """
    sess = session or _make_session()
    sym = symbol.upper().replace(".NS", "")

    # Step 1: expiries. NSE 2026-09-04 returns
    # {"expiryDates": [...], "strikePrice": [...]}
    ci = _http_get_json(sess, _CONTRACT_INFO_TPL.format(sym=sym))
    ex_dates = ci.get("expiryDates") or []
    nearest = _nearest_expiry(ex_dates)
    if not nearest:
        raise ValueError(
            f"option chain: no future expiry for {sym} "
            f"(contract-info returned {ex_dates[:3]})"
        )

    # Step 2: chain data for that expiry.
    return _http_get_json(sess, _API_TPL.format(
        sym=sym, expiry=nearest.replace(" ", "%20"),
    ))


def fetch_and_persist(symbols: List[str],
                      pause_seconds: float = 2.0,
                      as_of: Optional[_dt.date] = None) -> int:
    """
    Fetch each symbol, persist. Between-call pause defaults to 2s so
    residential IPs don't trip NSE's rate limiter.

    Returns total rows written.
    """
    ensure_schema()
    session = _make_session()
    written = 0
    date = as_of or _dt.date.today()
    for i, sym in enumerate(symbols):
        try:
            payload = fetch_chain(sym, session=session)
            row = parse_option_chain(payload, sym, target_date=date)
            if row is not None:
                written += _persist([row])
        except ValueError as e:
            _log.warning("%s: %s", sym, e)
        except Exception as e:
            _log.warning("%s: unexpected error: %s", sym, e)
        if i < len(symbols) - 1:
            time.sleep(pause_seconds)
    _log.info("nse_option_chain: %d row(s) persisted across %d symbol(s)",
              written, len(symbols))
    return written


# ─────────────────────────────────────────────────────────────────────────────
# Read API used by analysis.score
# ─────────────────────────────────────────────────────────────────────────────

def load_symbol_latest(symbol: str) -> pd.DataFrame:
    """Return the most-recent row for the symbol (may be empty)."""
    ensure_schema()
    sym = (symbol or "").upper().replace(".NS", "")
    try:
        with _store._get_conn() as conn:
            return pd.read_sql_query(_store._q("""
                SELECT * FROM nse_option_chain_daily
                WHERE symbol = ?
                ORDER BY date DESC LIMIT 1
            """), conn, params=(sym,))
    except Exception as e:
        _log.warning("nse_option_chain.load_symbol_latest failed for %s: %s",
                     sym, e)
        return pd.DataFrame()


def get_pcr(symbol: str) -> Optional[float]:
    """Return latest PCR for symbol, or None when we lack a row."""
    df = load_symbol_latest(symbol)
    if df is None or df.empty:
        return None
    v = df["pcr"].iloc[0]
    if v is None or pd.isna(v):
        return None
    return float(v)


def get_max_pain_pct(symbol: str) -> Optional[float]:
    """Return latest max-pain distance %, or None when we lack a row."""
    df = load_symbol_latest(symbol)
    if df is None or df.empty:
        return None
    v = df["max_pain_pct"].iloc[0]
    if v is None or pd.isna(v):
        return None
    return float(v)
