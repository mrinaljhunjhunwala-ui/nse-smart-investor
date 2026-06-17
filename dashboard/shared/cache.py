"""dashboard/shared/cache.py - shared cached data + display/validation helpers."""
from __future__ import annotations
import os, sys, sqlite3, warnings, io, json, math, datetime
import logging
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
import plotly.io as pio
from plotly.subplots import make_subplots
import streamlit as st
warnings.filterwarnings('ignore')
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
import trade_store as _store
_log = logging.getLogger("dashboard.cache")


# ─────────────────────────────────────────────────────────────────────────────
# Company name → ticker map  (used for search autocomplete)
# ─────────────────────────────────────────────────────────────────────────────
STOCK_SEARCH_MAP = {
    "Reliance Industries": "RELIANCE.NS",
    "Tata Consultancy Services (TCS)": "TCS.NS",
    "HDFC Bank": "HDFCBANK.NS",
    "Bharti Airtel": "BHARTIARTL.NS",
    "ICICI Bank": "ICICIBANK.NS",
    "Infosys": "INFY.NS",
    "State Bank of India (SBI)": "SBIN.NS",
    "Hindustan Unilever (HUL)": "HINDUNILVR.NS",
    "ITC": "ITC.NS",
    "Larsen & Toubro (L&T)": "LT.NS",
    "Kotak Mahindra Bank": "KOTAKBANK.NS",
    "Axis Bank": "AXISBANK.NS",
    "Bajaj Finance": "BAJFINANCE.NS",
    "Asian Paints": "ASIANPAINT.NS",
    "Maruti Suzuki": "MARUTI.NS",
    "NTPC": "NTPC.NS",
    "ONGC": "ONGC.NS",
    "Wipro": "WIPRO.NS",
    "UltraTech Cement": "ULTRACEMCO.NS",
    "Titan Company": "TITAN.NS",
    "HCL Technologies": "HCLTECH.NS",
    "Sun Pharma": "SUNPHARMA.NS",
    "Power Grid": "POWERGRID.NS",
    "Coal India": "COALINDIA.NS",
    "Nestle India": "NESTLEIND.NS",
    "Bajaj Finserv": "BAJAJFINSV.NS",
    "Tata Motors (TMPV - PV)": "TMPV.NS",
    "Adani Enterprises": "ADANIENT.NS",
    "JSW Steel": "JSWSTEEL.NS",
    "Grasim Industries": "GRASIM.NS",
    "Tech Mahindra": "TECHM.NS",
    "IndusInd Bank": "INDUSINDBK.NS",
    "Cipla": "CIPLA.NS",
    "Dr. Reddy's Laboratories": "DRREDDY.NS",
    "Eicher Motors": "EICHERMOT.NS",
    "Hindalco Industries": "HINDALCO.NS",
    "BPCL": "BPCL.NS",
    "Divi's Laboratories": "DIVISLAB.NS",
    "Tata Consumer Products": "TATACONSUM.NS",
    "Britannia Industries": "BRITANNIA.NS",
    "Hero MotoCorp": "HEROMOTOCO.NS",
    "Apollo Hospitals": "APOLLOHOSP.NS",
    "Bajaj Auto": "BAJAJ-AUTO.NS",
    "SBI Life Insurance": "SBILIFE.NS",
    "HDFC Life Insurance": "HDFCLIFE.NS",
    "Tata Power": "TATAPOWER.NS",
    "Adani Ports": "ADANIPORTS.NS",
    "Mahindra & Mahindra (M&M)": "M&M.NS",
    "LTIMindtree": "LTIM.NS",
    "Shriram Finance": "SHRIRAMFIN.NS",
    "Cholamandalam Finance": "CHOLAFIN.NS",
    "Muthoot Finance": "MUTHOOTFIN.NS",
    "HDFC AMC": "HDFCAMC.NS",
    "ICICI Lombard": "ICICIGI.NS",
    "ICICI Prudential Life": "ICICIPRULI.NS",
    "SBI Cards": "SBICARD.NS",
    "Persistent Systems": "PERSISTENT.NS",
    "Coforge": "COFORGE.NS",
    "Mphasis": "MPHASIS.NS",
    "L&T Technology Services": "LTTS.NS",
    "Bosch India": "BOSCHLTD.NS",
    "TVS Motor Company": "TVSMOTOR.NS",
    "Bharat Electronics (BEL)": "BEL.NS",
    "Siemens India": "SIEMENS.NS",
    "ABB India": "ABB.NS",
    "Havells India": "HAVELLS.NS",
    "Voltas": "VOLTAS.NS",
    "Cummins India": "CUMMINSIND.NS",
    "Torrent Pharma": "TORNTPHARM.NS",
    "Aurobindo Pharma": "AUROPHARMA.NS",
    "Mankind Pharma": "MANKIND.NS",
    "Marico": "MARICO.NS",
    "Dabur India": "DABUR.NS",
    "Godrej Consumer Products": "GODREJCP.NS",
    "Colgate Palmolive": "COLPAL.NS",
    "United Spirits (McDowell's)": "MCDOWELL-N.NS",
    "Trent": "TRENT.NS",
    "Nykaa (FSN E-Commerce)": "NYKAA.NS",
    "Ambuja Cements": "AMBUJACEM.NS",
    "ACC": "ACC.NS",
    "Oberoi Realty": "OBEROIRLTY.NS",
    "DLF": "DLF.NS",
    "Adani Green Energy": "ADANIGREEN.NS",
    "PFC (Power Finance)": "PFC.NS",
    "REC Limited": "RECLTD.NS",
    "Canara Bank": "CANBK.NS",
    "Bank of Baroda": "BANKBARODA.NS",
    "Vedanta": "VEDL.NS",
    "Pidilite Industries": "PIDILITIND.NS",
    "Berger Paints": "BERGEPAINT.NS",
    "Indus Towers": "INDUSTOWER.NS",
    "Zydus Lifesciences": "ZYDUSLIFE.NS",
    "Lupin": "LUPIN.NS",
    "Lodha (Macrotech)": "LODHA.NS",
    "IRCTC": "IRCTC.NS",
    "Info Edge (Naukri)": "NAUKRI.NS",
    "Eternal Ltd (Zomato)": "ETERNAL.NS",
    "IDFC First Bank": "IDFCFIRSTB.NS",
    "Federal Bank": "FEDERALBNK.NS",
    "Bandhan Bank": "BANDHANBNK.NS",
    "AU Small Finance Bank": "AUBANK.NS",
    "Punjab National Bank (PNB)": "PNB.NS",
    "Union Bank of India": "UNIONBANK.NS",
    "IDBI Bank": "IDBI.NS",
    "RBL Bank": "RBLBANK.NS",
    "KPIT Technologies": "KPITTECH.NS",
    "Tata Elxsi": "TATAELXSI.NS",
    "Cyient": "CYIENT.NS",
    "Angel One": "ANGELONE.NS",
    "Balkrishna Industries (BKT)": "BALKRISIND.NS",
    "Exide Industries": "EXIDEIND.NS",
    "Ashok Leyland": "ASHOKLEY.NS",
    "Motherson Sumi (Samvardhana)": "MOTHERSON.NS",
    "Alkem Laboratories": "ALKEM.NS",
    "Glenmark Pharma": "GLENMARK.NS",
    "Granules India": "GRANULES.NS",
    "Laurus Labs": "LAURUSLABS.NS",
    "IPCA Laboratories": "IPCALAB.NS",
    "GlaxoSmithKline Pharma": "GLAXO.NS",
    "Natco Pharma": "NATCOPHARM.NS",
    "Varun Beverages (VBL)": "VBL.NS",
    "Radico Khaitan": "RADICO.NS",
    "Emami": "EMAMILTD.NS",
    "Avenue Supermarts (DMart)": "DMART.NS",
    "IndiaMART": "INDIAMART.NS",
    "Ramco Cements": "RAMCOCEM.NS",
    "JK Cement": "JKCEMENT.NS",
    "Astral Poly Technik": "ASTRAL.NS",
    "APL Apollo Tubes": "APLAPOLLO.NS",
    "BHEL": "BHEL.NS",
    "RVNL (Rail Vikas Nigam)": "RVNL.NS",
    "KEC International": "KEC.NS",
    "Thermax": "THERMAX.NS",
    "NBCC India": "NBCC.NS",
    "Container Corporation (CONCOR)": "CONCOR.NS",
    "IRFC": "IRFC.NS",
    "IGL (Indraprastha Gas)": "IGL.NS",
    "MGL (Mahanagar Gas)": "MGL.NS",
    "Petronet LNG": "PETRONET.NS",
    "GAIL India": "GAIL.NS",
    "NHPC": "NHPC.NS",
    "SJVN": "SJVN.NS",
    "HPCL": "HPCL.NS",
    "Indian Oil (IOC)": "IOC.NS",
    "Suzlon Energy": "SUZLON.NS",
    "Hindustan Zinc": "HINDZINC.NS",
    "NMDC": "NMDC.NS",
    "SAIL (Steel Authority)": "SAIL.NS",
    "Godrej Properties": "GODREJPROP.NS",
    "Phoenix Mills": "PHOENIXLTD.NS",
    "Prestige Estates": "PRESTIGE.NS",
    "Sobha Developers": "SOBHA.NS",
    "Aarti Industries": "AARTIIND.NS",
    "Deepak Nitrite": "DEEPAKNITR.NS",
    "SRF": "SRF.NS",
    "CDSL (Depository)": "CDSL.NS",
    "BSE": "BSE.NS",
    "MCX (Multi Commodity Exchange)": "MCX.NS",
    "CAMS": "CAMS.NS",
    "Max Healthcare": "MAXHEALTH.NS",
    "Fortis Healthcare": "FORTIS.NS",
    "Dr. Lal PathLabs": "LALPATHLAB.NS",
    "Metropolis Healthcare": "METROPOLIS.NS",
    "Indian Hotels (Taj)": "INDHOTEL.NS",
    "Polycab India": "POLYCAB.NS",
    "Dixon Technologies": "DIXON.NS",
    "Page Industries (Jockey)": "PAGEIND.NS",
    "MRF": "MRF.NS",
    "Jubilant Foodworks (Dominos)": "JUBLFOOD.NS",
    "Tata Communications": "TATACOMM.NS",
    "Sun TV Network": "SUNTV.NS",
    "Manappuram Finance": "MANAPPURAM.NS",
    "Tatasteel": "TATASTEEL.NS",
    "Balrampur Chini Mills": "BALRAMCHIN.NS",
    "Xchanging Solutions": "XCHANGING.NS",
    "Bajaj Hindusthan Sugar": "BAJAJHIND.NS",
    "Dhanlaxmi Bank": "DHANBANK.NS",
}

_TICKER_TO_NAME = {v: k for k, v in STOCK_SEARCH_MAP.items()}


def get_display_name(ticker: str) -> str:
    t = ticker if ticker.endswith(".NS") else ticker + ".NS"
    return _TICKER_TO_NAME.get(t, ticker.replace(".NS", ""))


def _validate_ticker(raw: str):
    t = (raw or "").strip().upper().replace(" ", "")
    if not t:
        return "", None
    t = t.replace(".NS", "").replace(".BO", "")
    if not all(c.isalnum() or c in "-&" for c in t):
        return t, (f"'{t}' doesn't look like a valid NSE symbol "
                   f"(letters/digits only, e.g. RELIANCE, M&M, BAJAJ-AUTO).")
    if len(t) > 20:
        return t, f"'{t[:20]}…' is too long for an NSE symbol."
    return t, None


def _plain_english(action: str, entry: float, sl: float, tp: float, rr: float) -> str:
    risk_amt = entry - sl
    rew_amt  = tp - entry
    if action in ("STRONG BUY", "BUY"):
        return (f"✅ <b>Looks like a good buy.</b> If you want in, buy near "
                f"<b>₹{entry:,.2f}</b>. Set a stop-loss at <b>₹{sl:,.2f}</b> — that's your "
                f"exit if it goes wrong (max loss ≈ ₹{risk_amt:,.2f}/share). Aim to take "
                f"profit near <b>₹{tp:,.2f}</b> (≈ ₹{rew_amt:,.2f}/share gain). "
                f"You're risking 1 to make {rr:.1f}.")
    if action == "WATCHLIST":
        return ("👀 <b>Not a buy yet.</b> It's close but not strong enough — add it to your "
                "watchlist and wait for it to firm up before committing money.")
    if action == "HOLD":
        return ("🟡 <b>Hold, don't add.</b> If you already own it, keep holding. But this isn't "
                "a good level to put fresh money in.")
    if action == "CAUTION":
        return ("⚠️ <b>Be careful.</b> Momentum is fading. If you own it, consider trimming or "
                "tightening your stop. Not a place to buy more.")
    if action == "EXIT":
        return ("🔴 <b>Weak — avoid buying.</b> If you own it, consider selling and moving the "
                "money to a stronger stock. The trend is against it right now.")
    return ("This stock is in a neutral zone — no strong edge either way. Wait for a clearer setup.")


def _trade_type(headline: str) -> tuple:
    h = (headline or "").lower()
    if any(k in h for k in ("breakout", "52-week high", "52w high", "new high", "all-time high")):
        return ("Breakout", "🚀", "#00d4aa")
    if any(k in h for k in ("oversold", "bounce", "reversal", "support")):
        return ("Oversold Bounce", "🔄", "#5b8def")
    if any(k in h for k in ("momentum", "uptrend", "above sma", "strong trend", "trending")):
        return ("Momentum", "📈", "#ff9500")
    if any(k in h for k in ("pullback", "dip")):
        return ("Pullback", "🎯", "#a78bfa")
    return ("Trend", "•", "#8899bb")


@st.cache_data(ttl=300)
def load_ticker_df(ticker: str, period: str = "2y") -> pd.DataFrame:
    from data.fetcher import fetch_single
    from utils.indicators import add_all_indicators
    df = fetch_single(ticker, period=period)
    df = add_all_indicators(df)
    df.dropna(subset=["RSI", "ATR", "SMA_200"], inplace=True)
    return df


def _trim_to_period(df: pd.DataFrame, period: str) -> pd.DataFrame:
    if df.empty:
        return df
    last_ts = df.index[-1]
    _DAYS = {"1d": 8, "5d": 12, "1m": 35, "6m": 185, "1y": 375, "2y": 740}
    if period in _DAYS:
        cutoff = last_ts - pd.Timedelta(days=_DAYS[period])
        return df[df.index >= cutoff]
    if period == "ytd":
        return df[df.index >= pd.Timestamp(last_ts.year, 1, 1)]
    return df


@st.cache_data(ttl=600)
def load_vix_data():
    from data.fetcher import fetch_single
    try:
        vix   = fetch_single("^INDIAVIX", period="1y")
    except Exception as _e:
        _log.debug("cache.%s degraded: %s", "load_vix_data", _e)
        vix   = pd.DataFrame()
    try:
        nifty = fetch_single("^NSEI", period="1y")
    except Exception as _e:
        _log.debug("cache.%s degraded: %s", "load_vix_data", _e)
        nifty = pd.DataFrame()
    return vix, nifty


@st.cache_data(ttl=600)
def get_vix_info():
    try:
        from utils.vix import get_india_vix_regime
        return get_india_vix_regime()
    except Exception as _e:
        _log.debug("cache.%s degraded: %s", "get_vix_info", _e)
        return {"vix": 18.0, "regime": "normal", "allow_buy": True, "vix_pct_chg": 0.0}


@st.cache_data(ttl=300, show_spinner=False)
def _score_for_cc(ticker: str, vix_regime: str = "normal") -> dict:
    try:
        import sys, os as _os
        sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
        from analysis.score import score_stock
        _vix_info = {
            "regime": vix_regime, "vix": None,
            "allow_buy": vix_regime not in ("fear", "panic"),
        }
        s = score_stock(ticker, vix_info=_vix_info)
        return {
            "ticker": ticker, "price": s.price,
            "score": s.score, "grade": s.grade, "action": s.action,
            "headline": s.headline, "entry": s.entry,
            "sl": s.stop_loss, "tp": s.target, "rr": s.risk_reward,
        }
    except Exception as _e:
        return {
            "ticker": ticker, "price": 0, "score": 0, "grade": "?",
            "action": "UNAVAILABLE",
            "headline": f"Data unavailable ({type(_e).__name__}: {str(_e)[:70]})",
            "entry": 0, "sl": 0, "tp": 0, "rr": 0,
        }


@st.cache_data(ttl=300, show_spinner=False)
def _score_watchlist(tickers: tuple, vix_regime: str = "normal", sector_ranks: tuple = ()) -> dict:
    import concurrent.futures as _cf
    import sys, os as _os
    sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))

    _vix = {"regime": vix_regime, "vix": None,
            "allow_buy": vix_regime not in ("fear", "panic")}
    _sec_df = _sector_df_from_tuple(sector_ranks)

    def _one(tk):
        try:
            from analysis.score import score_stock
            s = score_stock(tk, vix_info=_vix, sector_scores_df=_sec_df)
            return tk, {"ticker": tk, "price": s.price, "score": s.score,
                        "grade": s.grade, "action": s.action, "headline": s.headline,
                        "entry": s.entry, "sl": s.stop_loss, "tp": s.target, "rr": s.risk_reward}
        except Exception as e:
            return tk, {"ticker": tk, "price": 0, "score": 0, "grade": "?",
                        "action": "UNAVAILABLE",
                        "headline": f"Data unavailable ({type(e).__name__})",
                        "entry": 0, "sl": 0, "tp": 0, "rr": 0}

    out: dict = {}
    if not tickers:
        return out
    try:
        with _cf.ThreadPoolExecutor(max_workers=min(8, max(1, len(tickers)))) as ex:
            for tk, sc in ex.map(_one, tickers):
                out[tk] = sc
    except Exception as _e:
        _log.debug("cache.%s degraded: %s", "_score_watchlist", _e)
        for tk in tickers:
            _tk, _sc = _one(tk)
            out[_tk] = _sc
    return out


_HOME_SCAN_UNIVERSE = [
    "RELIANCE.NS","TCS.NS","HDFCBANK.NS","ICICIBANK.NS","INFY.NS","SBIN.NS",
    "BHARTIARTL.NS","LT.NS","ITC.NS","AXISBANK.NS","KOTAKBANK.NS","HINDUNILVR.NS",
    "BAJFINANCE.NS","MARUTI.NS","SUNPHARMA.NS","TATAMOTORS.NS","NTPC.NS","TITAN.NS",
    "ULTRACEMCO.NS","ASIANPAINT.NS","WIPRO.NS","ADANIENT.NS","JSWSTEEL.NS","POWERGRID.NS",
    "TATASTEEL.NS","HCLTECH.NS","ONGC.NS","COALINDIA.NS","BAJAJFINSV.NS","TECHM.NS",
    "DRREDDY.NS","CIPLA.NS","HINDALCO.NS","GRASIM.NS","EICHERMOT.NS","TRENT.NS",
]


def _sector_df_from_tuple(sector_ranks: tuple):
    if not sector_ranks:
        return None
    try:
        return pd.DataFrame(
            [{"Rank": int(r)} for _, r in sector_ranks],
            index=[str(s) for s, _ in sector_ranks],
        )
    except Exception as _e:
        _log.debug("cache.%s degraded: %s", "_sector_df_from_tuple", _e)
        return None


@st.cache_data(ttl=300, show_spinner=False)
def _home_top_picks(vix_regime: str = "normal", n: int = 10, sector_ranks: tuple = ()) -> dict:
    """
    Scan the FULL NSE universe (~200+ liquid large/mid/small-caps) and return the
    strongest long candidates and the clearest SELL/EXIT candidates for the day.

    Each stock's CompositeScore folds in trend, momentum, RSI, volume, VIX
    sentiment AND sector strength (via sector_ranks) — "self-analysis +
    volatility" in one number.

    FIX TP1: previously this function surfaced any stock with action in
    (STRONG BUY, BUY, WATCHLIST) sorted purely by score — with no minimum
    score floor. On weak-breadth days the "best" stock in the universe might
    only be a 53/90 WATCHLIST-grade name, but it still got displayed as if
    it were a genuine Top Pick (indistinguishable from a real 85/90 STRONG
    BUY in the UI). That's why Top Picks could look like it was full of
    losers — they were never strong setups to begin with.

    Now: `buys` only contains STRONG BUY / BUY entries that also clear
    MIN_BUY_SCORE (65 — matches the BUY action threshold in analysis/score.py
    so we're never showing a "pick" weaker than the engine's own action
    label). If there are fewer than `n` genuine strong picks, we backfill
    with WATCHLIST-tier names — each entry carries a `tier` field
    ("strong" | "watch") so the UI can render backfilled names with a
    visibly different, less-confident style instead of pretending they're
    equally strong.

    `meta.no_strong_picks` is True when there are zero genuine STRONG BUY/BUY
    candidates anywhere in the scanned universe — use this to show an honest
    "no clean setups today" message instead of padding the list.

    Returns {
        "buys": [...],   # tier="strong" first, then tier="watch" backfill
        "sells": [...],
        "meta": {"n_strong_buys": int, "no_strong_picks": bool},
    }

    Cached 5 min: the first scan takes ~2 min (parallelised), every rerun
    within 5 min is instant. Cache auto-expires so picks stay live during
    market hours without needing a manual "Scan Now" click.
    """
    import concurrent.futures as _cf
    import sys, os as _os
    sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
    from data.universe import get_universe
    _UNIV = get_universe("nifty500")        # the repo's full liquid NSE universe

    # FIX TP1: floor matches the BUY action threshold (analysis/score.py
    # _action(): score >= 65 -> BUY). Keeps "Top Pick" and "BUY" in sync.
    MIN_BUY_SCORE = 65

    strong_buys, watch_buys, sells = [], [], []

    _vix = {"regime": vix_regime, "vix": None,
            "allow_buy": vix_regime not in ("fear", "panic")}
    _sec_df = _sector_df_from_tuple(sector_ranks)

    def _one(tk):
        """Score directly via score_stock (not the cached wrapper) — safe in threads."""
        try:
            from analysis.score import score_stock
            s = score_stock(tk, vix_info=_vix, sector_scores_df=_sec_df)
            return {"ticker": tk, "price": s.price, "score": s.score,
                    "grade": s.grade, "action": s.action, "headline": s.headline,
                    "entry": s.entry, "sl": s.stop_loss, "tp": s.target, "rr": s.risk_reward,
                    "narrative": s.narrative, "sector": s.sector,
                    "technical": s.technical_score, "momentum": s.momentum_score,
                    "volume": s.volume_score,
                    "sentiment": s.sentiment_score}
        except Exception as _e:
            _log.debug("cache._home_top_picks._one degraded for %s: %s", tk, _e)
            return {"ticker": tk, "price": 0, "score": 0, "grade": "?",
                    "action": "UNAVAILABLE", "headline": "", "entry": 0,
                    "sl": 0, "tp": 0, "rr": 0, "narrative": "", "sector": "",
                    "technical": 0, "momentum": 0, "volume": 0,
                    "sentiment": 0}

    results = []
    try:
        with _cf.ThreadPoolExecutor(max_workers=10) as ex:
            results = list(ex.map(_one, _UNIV))
    except Exception as _e:
        _log.debug("cache.%s degraded: %s", "_home_top_picks", _e)
        results = [_one(tk) for tk in _UNIV]

    for s in results:
        act = s.get("action", "")
        sc  = s.get("score", 0)
        if sc <= 0 or act in ("UNAVAILABLE", "DATA_UNAVAILABLE"):
            continue
        if act in ("STRONG BUY", "BUY") and sc >= MIN_BUY_SCORE:
            s["tier"] = "strong"
            strong_buys.append(s)
        elif act == "WATCHLIST":
            s["tier"] = "watch"
            watch_buys.append(s)
        elif act in ("EXIT", "CAUTION"):
            sells.append(s)

    strong_buys.sort(key=lambda x: -x.get("score", 0))
    watch_buys.sort(key=lambda x: -x.get("score", 0))
    sells.sort(key=lambda x: x.get("score", 0))   # lowest score = weakest first

    n_strong = len(strong_buys)

    # Backfill with WATCHLIST-tier names only if there aren't enough strong
    # picks — backfilled entries keep tier="watch" for the UI to style.
    buys = strong_buys[:n]
    if len(buys) < n:
        buys += watch_buys[: n - len(buys)]

    return {
        "buys": buys,
        "sells": sells[:n],
        "meta": {
            "n_strong_buys": n_strong,
            "no_strong_picks": n_strong == 0,
        },
    }


@st.cache_data(ttl=3600, show_spinner=False)
def _tomorrow_watchlist(n: int = 15) -> dict:
    import concurrent.futures as _cf
    import datetime as _dtm
    import sys, os as _os
    sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
    from data.universe import get_universe

    scan_time = _dtm.datetime.now().strftime("%d %b %H:%M")
    out = {"breakout_candidates": [], "breakdown_watch": [], "reversal_watch": [],
           "scan_time": scan_time}
    try:
        _UNIV = get_universe("nifty500")
    except Exception as _e:
        _log.debug("cache._tomorrow_watchlist universe failed: %s", _e)
        return out

    def _one(tk):
        try:
            from analysis.score import score_stock
            s = score_stock(tk)
            return {"ticker": tk, "price": s.price, "score": s.score, "grade": s.grade,
                    "action": s.action, "headline": s.headline, "entry": s.entry,
                    "sl": s.stop_loss, "tp": s.target, "rr": s.risk_reward,
                    "technical": s.technical_score, "momentum": s.momentum_score,
                    "volume": s.volume_score}
        except Exception as _e:
            _log.debug("cache._tomorrow_watchlist score failed for %s: %s", tk, _e)
            return None

    results = []
    try:
        with _cf.ThreadPoolExecutor(max_workers=10) as ex:
            results = [r for r in ex.map(_one, _UNIV) if r]
    except Exception as _e:
        _log.debug("cache._tomorrow_watchlist scan degraded: %s", _e)
        results = [r for r in (_one(tk) for tk in _UNIV) if r]

    def _item(s, signal_type, key_level):
        return {"ticker": s["ticker"], "score": s["score"], "headline": s["headline"],
                "signal_type": signal_type, "key_level": key_level,
                "action": s["action"], "entry": s["entry"], "sl": s["sl"], "tp": s["tp"]}

    for s in results:
        act, sc = s.get("action", ""), s.get("score", 0)
        if sc <= 0 or act in ("UNAVAILABLE", "DATA_UNAVAILABLE"):
            continue

        tech = s.get("technical", 0)
        mom  = s.get("momentum",  0)
        vol  = s.get("volume",    0)

        ent = s.get("entry", 0)
        kl  = f"₹{ent:,.0f}" if ent else "—"

        if act in ("STRONG BUY", "BUY", "WATCHLIST") and sc >= 52 and mom >= 8 and vol >= 5:
            out["breakout_candidates"].append(_item(s, "🚀 Breakout setup", kl))
        elif (act in ("EXIT", "CAUTION") or sc < 40) and tech < 22 and vol >= 4:
            out["breakdown_watch"].append(_item(s, "🔻 Breakdown risk",
                                                f"₹{s.get('sl', 0):,.0f}" if s.get("sl") else kl))
        elif 35 <= sc <= 58 and mom >= 8 and tech < 25:
            out["reversal_watch"].append(_item(s, "🔄 Bullish divergence", kl))
        elif 45 <= sc <= 68 and mom < 5 and tech >= 22:
            out["reversal_watch"].append(_item(s, "🔄 Bearish divergence", kl))

    out["breakout_candidates"].sort(key=lambda x: -x["score"])
    out["breakdown_watch"].sort(key=lambda x: x["score"])
    out["reversal_watch"].sort(key=lambda x: -x["score"])
    out["breakout_candidates"] = out["breakout_candidates"][:n]
    out["breakdown_watch"]     = out["breakdown_watch"][:n]
    out["reversal_watch"]      = out["reversal_watch"][:n]
    return out


@st.cache_data(ttl=3600, show_spinner=False)
def _sector_ranking():
    try:
        from analysis.sector_strength import rank_sectors
        return rank_sectors()
    except Exception as _e:
        _log.debug("cache.%s degraded: %s", "_sector_ranking", _e)
        return None


def _sector_ranks_tuple() -> tuple:
    df = _sector_ranking()
    if df is None or df.empty:
        return ()
    try:
        return tuple((str(idx), int(row["Rank"])) for idx, row in df.iterrows())
    except Exception as _e:
        _log.debug("cache.%s degraded: %s", "_sector_ranks_tuple", _e)
        return ()


@st.cache_data(ttl=600)
def get_composite_score(ticker: str):
    from analysis.score import score_stock
    vix_info = get_vix_info()
    sectors  = _sector_ranking()
    return score_stock(ticker, period="2y", vix_info=vix_info,
                       sector_scores_df=sectors)


@st.cache_data(ttl=600, show_spinner=False)
def _deep_confirmation(ticker: str) -> dict:
    out = {"weekly": None, "rel_strength": None, "rs_pct": None,
           "earnings_days": None, "bull": 0, "total": 0, "signals": []}
    try:
        from data.fetcher import fetch_single
        from utils.indicators import add_all_indicators
        df  = add_all_indicators(fetch_single(ticker, period="2y")).dropna(axis=1, how="all")
        cur = df.iloc[-1]
        price = float(cur["Close"])

        wk = df["Close"].resample("W").last().dropna()
        if len(wk) >= 11:
            _wma10 = float(wk.rolling(10).mean().iloc[-1])
            _wkchg = (wk.iloc[-1] / wk.iloc[-5] - 1) * 100 if len(wk) >= 5 else 0
            out["weekly"] = ("uptrend" if wk.iloc[-1] > _wma10 and _wkchg > 0
                             else "downtrend" if wk.iloc[-1] < _wma10 and _wkchg < 0
                             else "sideways")

        try:
            nf = fetch_single("^NSEI", period="6mo")["Close"].dropna()
            if len(nf) >= 22 and len(df) >= 22:
                _s1 = (price / float(df["Close"].iloc[-22]) - 1) * 100
                _n1 = (float(nf.iloc[-1]) / float(nf.iloc[-22]) - 1) * 100
                out["rs_pct"] = round(_s1 - _n1, 1)
                out["rel_strength"] = "outperforming" if out["rs_pct"] > 0 else "underperforming"
        except Exception as _e:
            _log.debug("cache.%s degraded: %s", "_deep_confirmation", _e)
            pass

        try:
            from data.events import get_earnings_date
            import datetime as _ed_dt
            ed = get_earnings_date(ticker)
            if ed:
                out["earnings_days"] = (ed - _ed_dt.datetime.now()).days
        except Exception as _e:
            _log.debug("cache.%s degraded: %s", "_deep_confirmation", _e)
            pass

        rsi = float(cur.get("RSI", 50))
        sigs = [
            ("RSI not overbought (<70)",    rsi < 70),
            ("MACD above signal",           float(cur.get("MACD", 0)) > float(cur.get("MACD_Signal", 0))),
            ("Above 20-day avg",            price > float(cur.get("SMA_20",  price * 1.1))),
            ("Above 50-day avg",            price > float(cur.get("SMA_50",  price * 1.1))),
            ("Above 200-day avg",           price > float(cur.get("SMA_200", price * 1.1))),
            ("Trend has strength (ADX>20)", float(cur.get("ADX", 0)) > 20),
            ("Volume supportive",           float(cur.get("Volume_Ratio", 1)) >= 1.0),
            ("No bearish divergence",       not bool(cur.get("RSI_Bear_Div", 0))),
            ("Weekly trend not down",       out["weekly"] != "downtrend"),
        ]
        out["signals"] = sigs
        out["bull"]    = sum(1 for _, ok in sigs if ok)
        out["total"]   = len(sigs)
    except Exception as _e:
        _log.debug("cache.%s degraded: %s", "_deep_confirmation", _e)
        pass
    return out


@st.cache_data(ttl=1800, show_spinner=False)
def _sparkline_closes(ticker: str, n: int = 22) -> list:
    try:
        from data.fetcher import fetch_single
        c = fetch_single(ticker, period="3mo")["Close"].dropna().tolist()
        return [round(float(x), 2) for x in c[-n:]]
    except Exception as _e:
        _log.debug("cache.%s degraded: %s", "_sparkline_closes", _e)
        return []


def _sparkline_svg(prices: list, w: int = 120, h: int = 28) -> str:
    if not prices or len(prices) < 2:
        return ""
    lo, hi = min(prices), max(prices)
    rng = (hi - lo) or 1
    pts = " ".join(
        f"{i/(len(prices)-1)*w:.1f},{h - (p-lo)/rng*(h-4) - 2:.1f}"
        for i, p in enumerate(prices)
    )
    col = "#00d4aa" if prices[-1] >= prices[0] else "#ff4757"
    return (f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}" style="display:block">'
            f'<polyline points="{pts}" fill="none" stroke="{col}" stroke-width="1.6" '
            f'stroke-linejoin="round" stroke-linecap="round"/></svg>')
