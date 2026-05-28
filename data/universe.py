"""
data/universe.py
NSE stock universe — from NIFTY50 to ~500 liquid stocks.

Universe levels:
    "nifty50"   — 50 blue-chip stocks
    "nifty100"  — NIFTY50 + NIFTY_NEXT50  (100 total)
    "nifty200"  — nifty100 + NIFTY_MIDCAP (200 total)
    "nifty500"  — nifty200 + NIFTY_SMALLCAP (≈400 total)

Helpers:
    get_universe(level)         → List[str]
    resolve_ticker(query)       → "RELIANCE.NS" (accepts partial / no-suffix names)
    get_sector(ticker)          → str
    get_tickers_by_sector(sector) → List[str]
"""

from __future__ import annotations
from typing import Dict, List

# ─────────────────────────────────────────────────────────────────────────────
# NIFTY 50  (imported + re-exported for backward compat)
# ─────────────────────────────────────────────────────────────────────────────
from data.fetcher import NIFTY50_TICKERS

# ─────────────────────────────────────────────────────────────────────────────
# NIFTY NEXT 50  (stocks ranked 51-100 by market cap)
# ─────────────────────────────────────────────────────────────────────────────
NIFTY_NEXT50: List[str] = [
    # Financial Services
    "CHOLAFIN.NS", "MUTHOOTFIN.NS", "BAJAJHLDNG.NS", "HDFCAMC.NS",
    "ICICIGI.NS", "ICICIPRULI.NS", "SBICARD.NS", "ABCAPITAL.NS",
    # IT / Technology
    "PERSISTENT.NS", "COFORGE.NS", "MPHASIS.NS", "LTTS.NS",
    # Auto / Capital Goods / Industrials
    "BOSCHLTD.NS", "TVSMOTOR.NS", "BEL.NS", "SIEMENS.NS",
    "ABB.NS", "HAVELLS.NS", "VOLTAS.NS", "CUMMINSIND.NS",
    # Pharma / Healthcare
    "TORNTPHARM.NS", "AUROPHARMA.NS", "MANKIND.NS",
    # FMCG / Consumer
    "MARICO.NS", "DABUR.NS", "GODREJCP.NS", "COLPAL.NS",
    "MCDOWELL-N.NS", "TRENT.NS", "NYKAA.NS",
    # Cement / Real Estate
    "AMBUJACEM.NS", "ACC.NS", "OBEROIRLTY.NS", "DLF.NS",
    # Energy / Power / Infra
    "ADANIGREEN.NS", "TATAPOWER.NS", "PFC.NS", "RECLTD.NS",
    "CANBK.NS", "BANKBARODA.NS",
    # Metals / Chemicals
    "VEDL.NS", "PIDILITIND.NS", "BERGEPAINT.NS",
    # Telecom
    "INDUSTOWER.NS",
    # Consumer Discretionary
    "ZYDUSLIFE.NS", "LUPIN.NS", "LODHA.NS",
    "IRCTC.NS", "NAUKRI.NS", "ZOMATO.NS",
]

# ─────────────────────────────────────────────────────────────────────────────
# NIFTY MIDCAP 100  (popular midcap stocks)
# ─────────────────────────────────────────────────────────────────────────────
NIFTY_MIDCAP: List[str] = [
    # Banking / NBFC
    "IDFCFIRSTB.NS", "FEDERALBNK.NS", "BANDHANBNK.NS", "AUBANK.NS",
    "KARURVYSYA.NS", "LICHSGFIN.NS", "SUNDARMFIN.NS", "PNB.NS",
    "UNIONBANK.NS", "IDBI.NS", "RBLBANK.NS",
    # IT / Tech Services
    "KPITTECH.NS", "TATAELXSI.NS", "CYIENT.NS", "MASTEK.NS",
    "TANLA.NS", "ANGELONE.NS", "360ONE.NS",
    # Auto Ancillaries
    "BALKRISIND.NS", "EXIDEIND.NS", "SUNDRMFAST.NS",
    "TIINDIA.NS", "MOTHERSON.NS", "ASHOKLEY.NS", "ESCORTS.NS",
    # Pharma / Healthcare
    "ALKEM.NS", "GLENMARK.NS", "GRANULES.NS", "LAURUSLABS.NS",
    "IPCALAB.NS", "GLAXO.NS", "NATCOPHARM.NS",
    # FMCG / Consumer / Retail
    "VBL.NS", "RADICO.NS", "EMAMILTD.NS", "JYOTHYLAB.NS",
    "DMART.NS", "TATACONSUM.NS", "GODREJIND.NS",
    "INDIAMART.NS", "CARTRADE.NS",
    # Cement / Building Materials
    "RAMCOCEM.NS", "JKCEMENT.NS", "ASTRAL.NS", "APLAPOLLO.NS",
    # Capital Goods / Infra / Defence
    "BHEL.NS", "RVNL.NS", "KEC.NS", "THERMAX.NS",
    "NBCC.NS", "CONCOR.NS", "IRFC.NS",
    # Energy / Oil & Gas
    "IGL.NS", "MGL.NS", "PETRONET.NS", "GAIL.NS",
    "NHPC.NS", "SJVN.NS", "NLCINDIA.NS", "HPCL.NS", "IOC.NS",
    # Metals / Mining
    "HINDZINC.NS", "NMDC.NS", "SAIL.NS", "MOIL.NS",
    # Real Estate
    "GODREJPROP.NS", "PHOENIXLTD.NS", "PRESTIGE.NS", "SOBHA.NS",
    # Chemicals / Specialty
    "AARTIIND.NS", "DEEPAKNITR.NS", "SRF.NS", "GNFC.NS",
    # Financial Services (exchanges, AMC)
    "CDSL.NS", "BSE.NS", "MCX.NS", "CAMS.NS", "HDFCAMC.NS",
    # Healthcare Services
    "LALPATHLAB.NS", "METROPOLIS.NS", "RAINBOW.NS", "FORTIS.NS",
    # Hotels / Travel
    "INDHOTEL.NS",
    # Textiles
    "TRIDENT.NS", "VARDHMAN.NS",
    # Others
    "MFSL.NS", "PIIND.NS", "POLYCAB.NS", "DIXON.NS",
]

# ─────────────────────────────────────────────────────────────────────────────
# NIFTY SMALLCAP  (selected liquid small-caps)
# ─────────────────────────────────────────────────────────────────────────────
NIFTY_SMALLCAP: List[str] = [
    # Finance
    "MANAPPURAM.NS", "UJJIVAN.NS", "JMFINANCIL.NS", "IIFL.NS",
    # IT
    "NIIT.NS", "BSOFT.NS",
    # Pharma
    "ABBOTINDIA.NS", "SOLARA.NS",
    # Consumer
    "BATAINDIA.NS", "SAFARI.NS", "WHIRLPOOL.NS", "SYMPHONY.NS",
    "HONASA.NS", "KALYANKJIL.NS",
    # Infra / Capital Goods
    "HUDCO.NS", "HFCL.NS", "RITES.NS",
    # Energy
    "RENUKA.NS", "SUZLON.NS",
    # Chemicals
    "VINATIORGA.NS", "FLUOROCHEM.NS", "NOCIL.NS",
    # Auto
    "AMARAJABAT.NS",
    # Others
    "PAGEIND.NS", "MRF.NS", "SCHAEFFLER.NS", "SOLARINDS.NS",
    "VBL.NS", "JUBLFOOD.NS", "TATACOMM.NS", "SUNTV.NS",
]

# ─────────────────────────────────────────────────────────────────────────────
# SECTOR MAP  (ticker → sector string)
# ─────────────────────────────────────────────────────────────────────────────
_SECTOR_ASSIGNMENTS: Dict[str, List[str]] = {
    "IT": [
        "TCS.NS", "INFY.NS", "WIPRO.NS", "HCLTECH.NS", "TECHM.NS",
        "LTIM.NS", "PERSISTENT.NS", "COFORGE.NS", "MPHASIS.NS", "LTTS.NS",
        "KPITTECH.NS", "TATAELXSI.NS", "CYIENT.NS", "MASTEK.NS",
        "NIIT.NS", "BSOFT.NS", "TANLA.NS",
    ],
    "Banking": [
        "HDFCBANK.NS", "ICICIBANK.NS", "SBIN.NS", "KOTAKBANK.NS", "AXISBANK.NS",
        "INDUSINDBK.NS", "IDFCFIRSTB.NS", "FEDERALBNK.NS", "BANDHANBNK.NS",
        "AUBANK.NS", "KARURVYSYA.NS", "PNB.NS", "UNIONBANK.NS",
        "IDBI.NS", "CANBK.NS", "BANKBARODA.NS", "RBLBANK.NS",
    ],
    "Finance": [
        "BAJFINANCE.NS", "BAJAJFINSV.NS", "SHRIRAMFIN.NS", "CHOLAFIN.NS",
        "MUTHOOTFIN.NS", "BAJAJHLDNG.NS", "HDFCAMC.NS", "ICICIGI.NS",
        "ICICIPRULI.NS", "SBICARD.NS", "ABCAPITAL.NS", "SUNDARMFIN.NS",
        "LICHSGFIN.NS", "MANAPPURAM.NS", "UJJIVAN.NS", "MFSL.NS",
        "JMFINANCIL.NS", "IIFL.NS", "ANGELONE.NS", "360ONE.NS",
        "CDSL.NS", "BSE.NS", "MCX.NS", "CAMS.NS",
    ],
    "Pharma": [
        "SUNPHARMA.NS", "DRREDDY.NS", "CIPLA.NS", "DIVISLAB.NS",
        "TORNTPHARM.NS", "AUROPHARMA.NS", "MANKIND.NS", "LUPIN.NS",
        "ALKEM.NS", "GLENMARK.NS", "GRANULES.NS", "LAURUSLABS.NS",
        "IPCALAB.NS", "GLAXO.NS", "NATCOPHARM.NS", "ABBOTINDIA.NS",
        "ZYDUSLIFE.NS",
    ],
    "Healthcare": [
        "APOLLOHOSP.NS", "MAXHEALTH.NS", "FORTIS.NS",
        "LALPATHLAB.NS", "METROPOLIS.NS", "RAINBOW.NS",
    ],
    "Auto": [
        "MARUTI.NS", "TATAMOTORS.NS", "BAJAJ-AUTO.NS", "EICHERMOT.NS",
        "HEROMOTOCO.NS", "TVSMOTOR.NS", "ASHOKLEY.NS", "ESCORTS.NS",
        "BALKRISIND.NS", "EXIDEIND.NS", "SUNDRMFAST.NS", "TIINDIA.NS",
        "MOTHERSON.NS", "BOSCHLTD.NS", "AMARAJABAT.NS", "SCHAEFFLER.NS",
    ],
    "FMCG": [
        "HINDUNILVR.NS", "ITC.NS", "NESTLEIND.NS", "BRITANNIA.NS",
        "TATACONSUM.NS", "MARICO.NS", "DABUR.NS", "GODREJCP.NS",
        "COLPAL.NS", "MCDOWELL-N.NS", "EMAMILTD.NS", "JYOTHYLAB.NS",
        "BIKAJI.NS", "RADICO.NS", "VBL.NS", "JUBLFOOD.NS",
        "BATAINDIA.NS",
    ],
    "Energy": [
        "RELIANCE.NS", "ONGC.NS", "BPCL.NS", "NTPC.NS", "POWERGRID.NS",
        "TATAPOWER.NS", "ADANIGREEN.NS", "ADANITRANS.NS", "PFC.NS",
        "RECLTD.NS", "NHPC.NS", "SJVN.NS", "NLCINDIA.NS",
        "IGL.NS", "MGL.NS", "PETRONET.NS", "GAIL.NS",
        "HPCL.NS", "IOC.NS", "SUZLON.NS",
    ],
    "Metal": [
        "TATASTEEL.NS", "JSWSTEEL.NS", "HINDALCO.NS",
        "HINDZINC.NS", "NMDC.NS", "SAIL.NS", "MOIL.NS",
        "VEDL.NS",
    ],
    "Chemicals": [
        "PIDILITIND.NS", "AARTIIND.NS", "DEEPAKNITR.NS",
        "SRF.NS", "GNFC.NS", "VINATIORGA.NS", "FLUOROCHEM.NS", "NOCIL.NS",
        "SOLARINDS.NS",
    ],
    "CapitalGoods": [
        "LT.NS", "BEL.NS", "SIEMENS.NS", "ABB.NS", "HAVELLS.NS",
        "VOLTAS.NS", "CUMMINSIND.NS", "BHEL.NS", "RVNL.NS",
        "KEC.NS", "THERMAX.NS", "NBCC.NS", "CONCOR.NS",
        "IRFC.NS", "HUDCO.NS", "RITES.NS", "POLYCAB.NS",
        "DIXON.NS", "HFCL.NS",
    ],
    "Cement": [
        "ULTRACEMCO.NS", "SHREECEM.NS", "AMBUJACEM.NS", "ACC.NS",
        "RAMCOCEM.NS", "JKCEMENT.NS",
    ],
    "RealEstate": [
        "DLF.NS", "GODREJPROP.NS", "OBEROIRLTY.NS", "PHOENIXLTD.NS",
        "PRESTIGE.NS", "SOBHA.NS", "LODHA.NS",
    ],
    "Telecom": [
        "BHARTIARTL.NS", "INDUSTOWER.NS", "TATACOMM.NS",
    ],
    "Retail": [
        "TRENT.NS", "DMART.NS", "NYKAA.NS", "INDIAMART.NS",
        "KALYANKJIL.NS", "CARTRADE.NS", "SAFARI.NS", "WHIRLPOOL.NS",
    ],
    "Conglomerate": [
        "ADANIENT.NS", "ADANIPORTS.NS", "GRASIM.NS",
        "TITAN.NS", "ASIANPAINT.NS", "BERGEPAINT.NS", "M&M.NS",
        "GODREJIND.NS",
    ],
}

# Build flat SECTOR_MAP: ticker → sector
SECTOR_MAP: Dict[str, str] = {}
for _sector, _tickers in _SECTOR_ASSIGNMENTS.items():
    for _t in _tickers:
        SECTOR_MAP[_t] = _sector

# ─────────────────────────────────────────────────────────────────────────────
# Company name lookup (upper-stripped base name → .NS ticker)
# ─────────────────────────────────────────────────────────────────────────────
def _build_name_map() -> Dict[str, str]:
    """Build lookup: "RELIANCE" → "RELIANCE.NS",  "BAJAJ-AUTO" → "BAJAJ-AUTO.NS" """
    m: Dict[str, str] = {}
    for t in get_universe("nifty500"):
        base = t.replace(".NS", "").replace(".BO", "")
        m[base.upper()] = t
    return m

_NAME_MAP: Dict[str, str] = {}   # populated lazily

# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def get_universe(level: str = "nifty50") -> List[str]:
    """
    Return the ticker list for the requested universe level.

    level:
        "nifty50"   → 50 tickers
        "nifty100"  → 100 tickers
        "nifty200"  → ~200 tickers
        "nifty500"  → ~400 tickers (best coverage without noise)
    """
    level = level.lower().strip()
    if level == "nifty50":
        return list(NIFTY50_TICKERS)
    if level == "nifty100":
        seen = set()
        result = []
        for t in list(NIFTY50_TICKERS) + NIFTY_NEXT50:
            if t not in seen:
                seen.add(t)
                result.append(t)
        return result
    if level == "nifty200":
        seen = set()
        result = []
        for t in list(NIFTY50_TICKERS) + NIFTY_NEXT50 + NIFTY_MIDCAP:
            if t not in seen:
                seen.add(t)
                result.append(t)
        return result
    # nifty500 = everything
    seen = set()
    result = []
    for t in list(NIFTY50_TICKERS) + NIFTY_NEXT50 + NIFTY_MIDCAP + NIFTY_SMALLCAP:
        if t not in seen:
            seen.add(t)
            result.append(t)
    return result


def resolve_ticker(query: str) -> str:
    """
    Resolve a user query to a canonical .NS ticker.

    Accepts:
        "RELIANCE"         → "RELIANCE.NS"
        "reliance"         → "RELIANCE.NS"
        "RELIANCE.NS"      → "RELIANCE.NS"
        "Bajaj Auto"       → "BAJAJ-AUTO.NS"
        "TCS.BO"           → "TCS.NS"   (BSE to NSE)

    Raises ValueError with suggestions if not found.
    """
    global _NAME_MAP
    if not _NAME_MAP:
        _NAME_MAP = _build_name_map()

    q = query.strip().upper().replace(".BO", "").replace(".NS", "")
    q = q.replace(" ", "").replace("&", "&")   # normalise spaces

    # 1. Exact match
    if q in _NAME_MAP:
        return _NAME_MAP[q]

    # 2. Partial match — q is substring of any key
    matches = [k for k in _NAME_MAP if q in k or k in q]
    if len(matches) == 1:
        return _NAME_MAP[matches[0]]
    if len(matches) > 1:
        # prefer exact prefix match
        prefix = [m for m in matches if m.startswith(q)]
        if prefix:
            return _NAME_MAP[prefix[0]]
        raise ValueError(
            f"'{query}' is ambiguous. Did you mean: "
            + ", ".join(_NAME_MAP[m] for m in matches[:5])
        )

    # 3. Accept as-is with .NS suffix (might be a valid ticker not in our list)
    candidate = q + ".NS"
    return candidate   # fetcher will raise if invalid


def get_sector(ticker: str) -> str:
    """Return sector for a ticker. Returns 'Other' if not in map."""
    t = ticker.upper()
    if not t.endswith(".NS"):
        t += ".NS"
    return SECTOR_MAP.get(t, "Other")


def get_tickers_by_sector(sector: str) -> List[str]:
    """Return all tickers in a given sector across the full NSE500 universe."""
    return [t for t, s in SECTOR_MAP.items() if s == sector]


def list_sectors() -> List[str]:
    """Return all unique sector names in the universe."""
    return sorted(set(SECTOR_MAP.values()))
