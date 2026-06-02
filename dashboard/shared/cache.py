"""dashboard/shared/cache.py ? shared data layer for all pages.
Display-name + validation helpers, every @st.cache_data function, the paper-trade
DB helpers (delegating to trade_store), position-sizing, and index/ticker data.
Imported by page files; cached results are shared across the multipage app.
"""
from __future__ import annotations
import os, sys, sqlite3, json, math, datetime
import numpy as np
import pandas as pd
import streamlit as st
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
import trade_store as _store
from dashboard.shared.design import _glass_metric, _section_div, _spacer, _signal_card


STOCK_SEARCH_MAP = {
    # Large-cap / Nifty 50
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
    # Nifty Next 50
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
    # Midcap / Popular stocks
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
    # User portfolio stocks
    "Balrampur Chini Mills": "BALRAMCHIN.NS",
    "Xchanging Solutions": "XCHANGING.NS",
    "Bajaj Hindusthan Sugar": "BAJAJHIND.NS",
    "Dhanlaxmi Bank": "DHANBANK.NS",
}

# Reverse lookup: ticker → display name
_TICKER_TO_NAME = {v: k for k, v in STOCK_SEARCH_MAP.items()}


def get_display_name(ticker: str) -> str:
    t = ticker if ticker.endswith(".NS") else ticker + ".NS"
    return _TICKER_TO_NAME.get(t, ticker.replace(".NS", ""))


def _validate_ticker(raw: str):
    """
    Validate a user-entered NSE symbol before any API call.
    Returns (cleaned_symbol, error_message_or_None). cleaned_symbol has no
    .NS/.BO suffix (callers add it). Allows letters, digits, '-' and '&'
    (e.g. RELIANCE, M&M, BAJAJ-AUTO).
    """
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
    """One-line 'what this means + what to do' for non-traders."""
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
    """
    Categorise a setup into a trade type from its narrative headline.
    Returns (label, emoji, color). Zero extra data needed.
    """
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


# ─────────────────────────────────────────────────────────────────────────────
# Shared helpers
# ─────────────────────────────────────────────────────────────────────────────

@st.cache_data(ttl=300)
def load_ticker_df(ticker: str, period: str = "2y") -> pd.DataFrame:
    """
    Fetch OHLCV + compute all technical indicators.

    Always fetches at least 2 years so that SMA_200, RSI(14), MACD(26) etc.
    are valid at the *most recent* row.  The UI chart period controls what
    slice is *displayed*, not how much data is loaded.
    """
    from data.fetcher import fetch_single
    from utils.indicators import add_all_indicators
    df = fetch_single(ticker, period=period)
    df = add_all_indicators(df)
    # Drop warm-up rows where core indicators are NaN so iloc[-1] is always valid
    df.dropna(subset=["RSI", "ATR", "SMA_200"], inplace=True)
    return df


def _trim_to_period(df: pd.DataFrame, period: str) -> pd.DataFrame:
    """
    Return a date-sliced copy of df matching the UI display period.
    Indicators were computed on the full dataset so they remain accurate
    at the most-recent row after slicing.
    """
    if df.empty:
        return df
    last_ts = df.index[-1]
    _DAYS = {"1d": 8, "5d": 12, "1m": 35, "6m": 185, "1y": 375, "2y": 740}
    if period in _DAYS:
        cutoff = last_ts - pd.Timedelta(days=_DAYS[period])
        return df[df.index >= cutoff]
    if period == "ytd":
        return df[df.index >= pd.Timestamp(last_ts.year, 1, 1)]
    return df  # "max" or anything else → full history


@st.cache_data(ttl=600)
def load_vix_data():
    """Load VIX + Nifty daily history via Stooq (no rate limits on cloud)."""
    from data.fetcher import fetch_single
    try:
        vix   = fetch_single("^INDIAVIX", period="1y")
    except Exception:
        vix   = pd.DataFrame()
    try:
        nifty = fetch_single("^NSEI", period="1y")
    except Exception:
        nifty = pd.DataFrame()
    return vix, nifty


@st.cache_data(ttl=600)
def get_vix_info():
    # Route through utils.vix — has 10-min TTL and proper crumb auth
    # (trading.signals had a missing urllib.request import bug)
    try:
        from utils.vix import get_india_vix_regime
        return get_india_vix_regime()
    except Exception:
        return {"vix": 18.0, "regime": "normal", "allow_buy": True, "vix_pct_chg": 0.0}


@st.cache_data(ttl=1800, show_spinner=False)   # 30-min cache — powers Command Centre
def _score_for_cc(ticker: str, vix_regime: str = "normal") -> dict:
    """Score one stock for Command Centre. Pass vix_regime so we don't re-fetch VIX 5×."""
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


@st.cache_data(ttl=1800, show_spinner=False)   # 30-min cache, whole watchlist
def _score_watchlist(tickers: tuple, vix_regime: str = "normal", sector_ranks: tuple = ()) -> dict:
    """
    Score a whole watchlist IN PARALLEL (one thread per stock) and cache the
    result for 30 min. Calls score_stock directly (not the cached single-stock
    wrapper) so it is safe to run inside worker threads. Sector strength is
    folded in via sector_ranks. Returns {ticker: score_dict}.
    """
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
    except Exception:
        for tk in tickers:
            _tk, _sc = _one(tk)
            out[_tk] = _sc
    return out


# Curated liquid large/mid-cap universe for the home-page "Top Picks" scan.
# Kept ~36 names so a full scan finishes fast (Angel One: ~15-25 s) and stays cached.
_HOME_SCAN_UNIVERSE = [
    "RELIANCE.NS","TCS.NS","HDFCBANK.NS","ICICIBANK.NS","INFY.NS","SBIN.NS",
    "BHARTIARTL.NS","LT.NS","ITC.NS","AXISBANK.NS","KOTAKBANK.NS","HINDUNILVR.NS",
    "BAJFINANCE.NS","MARUTI.NS","SUNPHARMA.NS","TATAMOTORS.NS","NTPC.NS","TITAN.NS",
    "ULTRACEMCO.NS","ASIANPAINT.NS","WIPRO.NS","ADANIENT.NS","JSWSTEEL.NS","POWERGRID.NS",
    "TATASTEEL.NS","HCLTECH.NS","ONGC.NS","COALINDIA.NS","BAJAJFINSV.NS","TECHM.NS",
    "DRREDDY.NS","CIPLA.NS","HINDALCO.NS","GRASIM.NS","EICHERMOT.NS","TRENT.NS",
]


def _sector_df_from_tuple(sector_ranks: tuple):
    """Rebuild a sector-rank DataFrame (index=sector, col=Rank) from a hashable tuple."""
    if not sector_ranks:
        return None
    try:
        return pd.DataFrame(
            [{"Rank": int(r)} for _, r in sector_ranks],
            index=[str(s) for s, _ in sector_ranks],
        )
    except Exception:
        return None


@st.cache_data(ttl=1800, show_spinner=False)   # 30-min cache
def _home_top_picks(vix_regime: str = "normal", n: int = 5, sector_ranks: tuple = ()) -> dict:
    """
    Scan a curated NSE large/mid-cap universe and return the strongest
    BUY candidates and the clearest SELL/EXIT candidates for the day.

    Each stock's CompositeScore folds in trend, momentum, RSI, volume, VIX
    sentiment AND sector strength (via sector_ranks) — "self-analysis +
    volatility" in one number. Returns {"buys": [...], "sells": [...]}.
    """
    import concurrent.futures as _cf
    import sys, os as _os
    sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
    buys, sells = [], []

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
                    "entry": s.entry, "sl": s.stop_loss, "tp": s.target, "rr": s.risk_reward}
        except Exception:
            return {"ticker": tk, "price": 0, "score": 0, "grade": "?",
                    "action": "UNAVAILABLE", "headline": "", "entry": 0,
                    "sl": 0, "tp": 0, "rr": 0}

    results = []
    try:
        with _cf.ThreadPoolExecutor(max_workers=8) as ex:
            results = list(ex.map(_one, _HOME_SCAN_UNIVERSE))
    except Exception:
        results = [_one(tk) for tk in _HOME_SCAN_UNIVERSE]

    for s in results:
        act = s.get("action", "")
        if act in ("STRONG BUY", "BUY") and s.get("score", 0) > 0:
            buys.append(s)
        elif act in ("EXIT", "CAUTION") and s.get("score", 0) > 0:
            sells.append(s)

    buys.sort(key=lambda x: -x.get("score", 0))
    sells.sort(key=lambda x: x.get("score", 0))   # lowest score = weakest
    return {"buys": buys[:n], "sells": sells[:n]}


@st.cache_data(ttl=3600, show_spinner=False)   # 1-hour cache — heavy multi-fetch
def _sector_ranking():
    """
    Rank all NSE sectors by constituent momentum (cached 1 h). Returns a
    DataFrame indexed by sector with a 'Rank' column for score_stock(), or None.
    """
    try:
        from analysis.sector_strength import rank_sectors
        return rank_sectors()
    except Exception:
        return None


def _sector_ranks_tuple() -> tuple:
    """Hashable ((sector, rank), …) form of _sector_ranking() for cached scorers."""
    df = _sector_ranking()
    if df is None or df.empty:
        return ()
    try:
        return tuple((str(idx), int(row["Rank"])) for idx, row in df.iterrows())
    except Exception:
        return ()


@st.cache_data(ttl=600)
def get_composite_score(ticker: str):
    """
    Deep-dive score over a 2-YEAR lookback (was 1y). The longer window means
    every signal is computed on a full, valid history — SMA_200 (296 valid rows
    vs ~49 on 1y), RSI divergence, candlestick patterns, ADX, volume trend and
    momentum all have enough warmup, so the composite reflects real multi-signal
    analysis, not just the latest bar. Sector strength + VIX are folded in too.
    """
    from analysis.score import score_stock
    vix_info = get_vix_info()
    sectors  = _sector_ranking()
    return score_stock(ticker, period="2y", vix_info=vix_info,
                       sector_scores_df=sectors)


@st.cache_data(ttl=600, show_spinner=False)
def _deep_confirmation(ticker: str) -> dict:
    """
    Confirmation layer on top of the composite score:
      • Multi-timeframe — weekly trend (filters daily false signals)
      • Relative strength — 1-month return vs Nifty (is it a leader?)
      • Earnings proximity — days to next result (avoid buying into a gap)
      • Signal agreement — how many of 9 checks are bullish (conviction)
    """
    out = {"weekly": None, "rel_strength": None, "rs_pct": None,
           "earnings_days": None, "bull": 0, "total": 0, "signals": []}
    try:
        from data.fetcher import fetch_single
        from utils.indicators import add_all_indicators
        df  = add_all_indicators(fetch_single(ticker, period="2y")).dropna(axis=1, how="all")
        cur = df.iloc[-1]
        price = float(cur["Close"])

        # Weekly trend
        wk = df["Close"].resample("W").last().dropna()
        if len(wk) >= 11:
            _wma10 = float(wk.rolling(10).mean().iloc[-1])
            _wkchg = (wk.iloc[-1] / wk.iloc[-5] - 1) * 100 if len(wk) >= 5 else 0
            out["weekly"] = ("uptrend" if wk.iloc[-1] > _wma10 and _wkchg > 0
                             else "downtrend" if wk.iloc[-1] < _wma10 and _wkchg < 0
                             else "sideways")

        # Relative strength vs Nifty (1 month ≈ 22 sessions)
        try:
            nf = fetch_single("^NSEI", period="6mo")["Close"].dropna()
            if len(nf) >= 22 and len(df) >= 22:
                _s1 = (price / float(df["Close"].iloc[-22]) - 1) * 100
                _n1 = (float(nf.iloc[-1]) / float(nf.iloc[-22]) - 1) * 100
                out["rs_pct"] = round(_s1 - _n1, 1)
                out["rel_strength"] = "outperforming" if out["rs_pct"] > 0 else "underperforming"
        except Exception:
            pass

        # Earnings proximity
        try:
            from data.events import get_earnings_date
            import datetime as _ed_dt
            ed = get_earnings_date(ticker)
            if ed:
                out["earnings_days"] = (ed - _ed_dt.datetime.now()).days
        except Exception:
            pass

        # Signal agreement (9 checks)
        rsi = float(cur.get("RSI", 50))
        sigs = [
            ("RSI not overbought (<70)",  rsi < 70),
            ("MACD above signal",         float(cur.get("MACD", 0)) > float(cur.get("MACD_Signal", 0))),
            ("Above 20-day avg",          price > float(cur.get("SMA_20", price * 1.1))),
            ("Above 50-day avg",          price > float(cur.get("SMA_50", price * 1.1))),
            ("Above 200-day avg",         price > float(cur.get("SMA_200", price * 1.1))),
            ("Trend has strength (ADX>20)", float(cur.get("ADX", 0)) > 20),
            ("Volume supportive",         float(cur.get("Volume_Ratio", 1)) >= 1.0),
            ("No bearish divergence",     not bool(cur.get("RSI_Bear_Div", 0))),
            ("Weekly trend not down",     out["weekly"] != "downtrend"),
        ]
        out["signals"] = sigs
        out["bull"]    = sum(1 for _, ok in sigs if ok)
        out["total"]   = len(sigs)
    except Exception:
        pass
    return out


@st.cache_data(ttl=1800, show_spinner=False)
def _sparkline_closes(ticker: str, n: int = 22) -> list:
    """Last `n` daily closes for a mini sparkline (cached 30 min)."""
    try:
        from data.fetcher import fetch_single
        c = fetch_single(ticker, period="3mo")["Close"].dropna().tolist()
        return [round(float(x), 2) for x in c[-n:]]
    except Exception:
        return []


def _sparkline_svg(prices: list, w: int = 120, h: int = 28) -> str:
    """Inline SVG sparkline from a price list — green if up over the window, else red."""
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


def load_trades_db(path: str = "trades.db") -> pd.DataFrame:
    if not os.path.exists(path):
        return pd.DataFrame()
    with sqlite3.connect(path) as conn:
        try:
            return pd.read_sql_query("SELECT * FROM trades ORDER BY id DESC", conn)
        except Exception:
            return pd.DataFrame()


# ── Paper-trade storage — delegates to trade_store (SQLite default, Postgres
#    if DATABASE_URL/secrets configured). `path` kept for signature compat. ────
import trade_store as _store


def load_trades_by_account(account: str, path: str = "trades.db") -> pd.DataFrame:
    """Load trades filtered to a specific paper trading account."""
    return _store.load_by_account(account)


def _ensure_paper_db(path: str = "trades.db"):
    """Ensure the trades schema exists on the active backend."""
    _store.ensure_schema()


def paper_list_accounts(path: str = "trades.db") -> list:
    """Return sorted list of distinct account names."""
    return _store.list_accounts()


def paper_rename_account(old_name: str, new_name: str, path: str = "trades.db"):
    """Rename an account across all its trades."""
    _store.rename_account(old_name, new_name)


def paper_delete_account(name: str, path: str = "trades.db"):
    """Delete all trades in an account."""
    _store.delete_account(name)


def paper_open_trade(ticker: str, price: float, qty: int,
                     sl: float, tp: float, reason: str = "",
                     account: str = "My Account",
                     path: str = "trades.db") -> int:
    """Insert a new paper BUY trade. Returns new row id."""
    return _store.open_trade(ticker, price, qty, sl, tp, reason=reason, account=account)


def paper_close_trade(trade_id: int, exit_price: float,
                      reason: str = "Manual close", path: str = "trades.db"):
    """Close an open paper trade by ID."""
    _store.close_trade(trade_id, exit_price, reason=reason)


def paper_edit_trade(trade_id: int, sl: float = None, tp: float = None,
                     reason: str = None, path: str = "trades.db"):
    """Edit stop-loss, target, or reason of an open trade."""
    _store.edit_trade(trade_id, sl=sl, tp=tp, reason=reason)


# ── Account product type (CNC = delivery, MIS = intraday) ─────────────────────
def paper_account_type(name: str) -> str:
    """Return 'MIS' (intraday) or 'CNC' (delivery) for an account; default CNC."""
    try:
        return _store.kv_get(f"acct_type:{name}", "CNC") or "CNC"
    except Exception:
        return "CNC"


def set_paper_account_type(name: str, atype: str) -> None:
    try:
        _store.kv_set(f"acct_type:{name}", "MIS" if str(atype).upper().startswith("MIS")
                      or "INTRA" in str(atype).upper() else "CNC")
    except Exception:
        pass


@st.cache_data(ttl=60, show_spinner=False)
def _portfolio_live_prices(tickers: tuple) -> dict:
    """
    Live prices for portfolio holdings via Yahoo Finance JSON API (cloud-safe).
    Falls back to Stooq EOD if Yahoo is unavailable.
    """
    from utils.live_price import get_live_prices_batch
    raw = get_live_prices_batch(list(tickers))
    results = {}
    for t in tickers:
        q = raw.get(t)
        if isinstance(q, dict) and q.get("price"):
            results[t] = {
                "price": q["price"],
                "prev":  q["prev_close"],
                "chg":   q["chg_pct"],
            }
    return results


def _action_color(action: str) -> str:
    if action in ("STRONG BUY", "BUY"):
        return "card-green"
    elif action in ("WATCHLIST", "HOLD"):
        return "card-yellow"
    else:
        return "card-red"


def _action_emoji(action: str) -> str:
    return {
        "STRONG BUY": "🚀", "BUY": "🟢", "WATCHLIST": "👀",
        "HOLD": "🟡", "CAUTION": "⚠️", "EXIT": "🔴",
    }.get(action, "")


def _grade_color(grade: str) -> str:
    return {"A+": "#26a69a", "A": "#4CAF50", "B": "#8BC34A",
            "C": "#FFC107", "D": "#FF5722", "F": "#f44336"}.get(grade, "#9E9E9E")


# ─────────────────────────────────────────────────────────────────────────────
# Position sizing — risk-based qty suggestion (used by auto-open paper trades)
# ─────────────────────────────────────────────────────────────────────────────

def _suggest_position(entry: float, sl: float,
                      capital: float = None,
                      risk_pct: float = None,
                      max_alloc_pct: float = 20.0) -> dict:
    """
    Suggest share quantity for a trade using fixed-fractional risk sizing.

    Sizes so that (entry - sl) × qty ≈ risk_pct% of capital, then caps the
    position at max_alloc_pct% of capital so a single name can't dominate.

    capital / risk_pct default to the user's settings in session_state
    (set in the sidebar), falling back to ₹5,00,000 and 1%.

    Returns: {qty, price, risk_per_share, capital_at_risk, position_value, basis}
    """
    if capital is None:
        capital = float(st.session_state.get("trade_capital", 500_000.0))
    if risk_pct is None:
        risk_pct = float(st.session_state.get("risk_pct", 1.0))
    entry = float(entry or 0)
    sl    = float(sl or 0)
    if entry <= 0:
        return {"qty": 1, "price": entry, "risk_per_share": 0,
                "capital_at_risk": 0, "position_value": entry, "basis": "fallback"}

    risk_amount = capital * (risk_pct / 100.0)
    rps = abs(entry - sl)
    if rps > 0.01:
        qty_risk = int(risk_amount / rps)
        basis = f"{risk_pct:.0f}% risk (₹{risk_amount:,.0f}) ÷ ₹{rps:.2f}/share"
    else:
        qty_risk = int(risk_amount / entry)   # no valid stop → notional sizing
        basis = "notional (no valid stop)"

    # Cap at max allocation
    qty_cap = int((capital * max_alloc_pct / 100.0) / entry)
    qty = max(1, min(qty_risk, qty_cap))
    if qty == qty_cap < qty_risk:
        basis += f" · capped at {max_alloc_pct:.0f}% allocation"

    return {
        "qty":             qty,
        "price":           round(entry, 2),
        "risk_per_share":  round(rps, 2),
        "capital_at_risk": round(rps * qty, 0),
        "position_value":  round(entry * qty, 0),
        "basis":           basis,
    }


def _paper_trade_popover(ticker: str, entry: float, sl: float, tp: float,
                         reason: str, key: str, label: str = "📌 Paper Trade") -> None:
    """
    Render a popover that lets the user review & adjust quantity (pre-filled
    with the risk-based suggestion) BEFORE opening a paper trade.

    Confirmation uses st.toast so feedback survives the popover closing on rerun.
    """
    sugg  = _suggest_position(entry, sl)
    _tlbl = ticker.replace(".NS", "")
    _cap  = float(st.session_state.get("trade_capital", 500_000.0))
    _rkp  = float(st.session_state.get("risk_pct", 1.0))
    with st.popover(label, use_container_width=True):
        st.markdown(f"**{_tlbl}** — open paper trade")
        st.caption(
            f"💡 Suggested **{sugg['qty']} shares** — sizes your loss-to-stop to "
            f"≈{_rkp:.2g}% of ₹{_cap:,.0f} (₹{sugg['capital_at_risk']:,.0f} at risk). "
            f"Change capital & risk in the sidebar; adjust qty below."
        )
        qty = st.number_input(
            "Quantity (shares)", min_value=1, max_value=1_000_000,
            value=int(sugg["qty"]), step=1, key=f"{key}_qty",
        )
        _val  = qty * entry
        _risk = abs(entry - (sl or entry)) * qty
        _c1, _c2, _c3 = st.columns(3)
        _c1.metric("Entry", f"₹{entry:,.2f}")
        _c2.metric("Position", f"₹{_val:,.0f}")
        _c3.metric("At Risk", f"₹{_risk:,.0f}")
        if sl or tp:
            st.caption(f"🛑 SL ₹{(sl or 0):,.2f}  ·  🎯 Target ₹{(tp or 0):,.2f}")
        if st.button("✅ Confirm & Open", key=f"{key}_confirm",
                     type="primary", use_container_width=True):
            _id = paper_open_trade(
                ticker, float(entry), int(qty), sl=sl, tp=tp, reason=reason,
                account=st.session_state.get("pt_account", "My Account"),
            )
            st.toast(f"📌 Opened #{_id}: {int(qty)} × {_tlbl} @ ₹{entry:,.2f}", icon="✅")
            st.cache_data.clear()
            st.rerun()


def _auto_close_breached(account: str = None, path: str = "trades.db") -> list:
    """
    Auto-close any OPEN paper trade whose live price has crossed its TP or SL.
    Paper trades only — never touches real broker positions.

    Only runs during NSE market hours: outside hours the live-price feed falls
    back to EOD close, which could falsely trip a stop/target. Returns a list of
    dicts describing what was closed. Caller reruns if the list is non-empty.
    """
    closed = []
    # Guard: only auto-close on live intraday prices, never on stale EOD data
    try:
        from utils.market_hours import market_status as _msx
        if not _msx().get("is_open", False):
            return closed
    except Exception:
        pass
    try:
        rows = _store.fetch_open(account)
        if rows.empty:
            return closed

        syms = tuple(rows["ticker"].tolist())
        lp   = _portfolio_live_prices(syms)

        for _, r in rows.iterrows():
            tk  = str(r["ticker"])
            ep  = float(r.get("price", 0) or 0)
            qty = int(r.get("quantity", 0) or 0)
            sl  = float(r.get("sl", 0) or 0) or None
            tp  = float(r.get("tp", 0) or 0) or None
            cur = lp.get(tk, {}).get("price")
            if cur is None or ep <= 0:
                continue

            hit = None
            if tp and cur >= tp:
                hit, exit_px, why = "target", tp, "Auto-closed: target reached"
            elif sl and cur <= sl:
                hit, exit_px, why = "stop", sl, "Auto-closed: stop-loss hit"
            if hit:
                paper_close_trade(int(r["id"]), exit_px, why, path=path)
                closed.append({
                    "ticker": tk.replace(".NS", ""), "type": hit,
                    "exit": exit_px, "pnl": (exit_px - ep) * qty,
                    "account": str(r.get("account", "My Account")),
                })
    except Exception:
        pass
    return closed


def _render_autoclose_banner(closed: list) -> None:
    """Show a prominent banner listing trades that were just auto-closed."""
    if not closed:
        return
    _rows = ""
    for c in closed:
        _ic  = "🎯" if c["type"] == "target" else "🛑"
        _col = "#26a69a" if c["pnl"] >= 0 else "#ef5350"
        _rows += (
            f'<div style="display:flex;justify-content:space-between;'
            f'padding:5px 0;border-bottom:1px solid rgba(255,255,255,.06);font-size:13px">'
            f'<span style="color:#eee">{_ic} <b>{c["ticker"]}</b> '
            f'<span style="color:#888">({c["account"]})</span> — '
            f'{"target reached" if c["type"]=="target" else "stop-loss hit"} '
            f'@ ₹{c["exit"]:,.2f}</span>'
            f'<span style="color:{_col};font-weight:700">₹{c["pnl"]:+,.0f}</span></div>'
        )
    st.markdown(
        f'<div style="background:linear-gradient(135deg,#1a1200,#2d1f00);'
        f'border:1px solid #FFC107;border-radius:12px;padding:14px 18px;margin-bottom:14px">'
        f'<div style="font-size:14px;font-weight:700;color:#FFC107;margin-bottom:6px">'
        f'🔔 {len(closed)} position{"s" if len(closed)!=1 else ""} auto-closed on SL/TP</div>'
        f'{_rows}</div>',
        unsafe_allow_html=True,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Macro / Breadth helpers  (for new pages 7–9)
# ─────────────────────────────────────────────────────────────────────────────

@st.cache_data(ttl=600)
def load_macro_data():
    """
    Fetch 3-month daily history for macro instruments.
    NSE indices via fetch_single() (Stooq first).
    Commodities/FX via Yahoo Finance JSON history (cloud-safe direct HTTP).
    """
    import json, io, datetime, urllib.request
    from data.fetcher import fetch_single

    data = {}

    # Indian index series — Stooq handles these reliably
    index_map = {
        "Nifty 50":  "^NSEI",
        "BankNifty": "^NSEBANK",
        "India VIX": "^INDIAVIX",
    }
    for name, sym in index_map.items():
        try:
            df = fetch_single(sym, period="3mo")
            if not df.empty:
                data[name] = df["Close"]
        except Exception:
            pass

    # Commodities / FX — use Yahoo Finance JSON history (v8 chart API)
    commodity_map = {
        "Gold ($/oz)": "GC=F",
        "Brent Crude": "BZ=F",
        "USD/INR":     "USDINR=X",
        "DXY":         "DX-Y.NYB",
    }
    for name, sym in commodity_map.items():
        try:
            url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}"
                   "?interval=1d&range=3mo")
            req = urllib.request.Request(
                url, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=10) as r:
                raw = json.loads(r.read())
            res = raw["chart"]["result"][0]
            ts  = res["timestamp"]
            cl  = res["indicators"]["quote"][0]["close"]
            df  = pd.DataFrame({"Close": cl},
                               index=pd.to_datetime(ts, unit="s")).dropna()
            if not df.empty:
                data[name] = df["Close"]
        except Exception:
            pass

    return pd.DataFrame(data).dropna(how="all")


_NIFTY50_TICKERS = (
    "RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "ICICIBANK.NS", "BHARTIARTL.NS",
    "INFY.NS", "SBIN.NS", "HINDUNILVR.NS", "ITC.NS", "LT.NS",
    "BAJFINANCE.NS", "HCLTECH.NS", "MARUTI.NS", "SUNPHARMA.NS", "ADANIENT.NS",
    "KOTAKBANK.NS", "TITAN.NS", "ONGC.NS", "NTPC.NS", "AXISBANK.NS",
    "WIPRO.NS", "ULTRACEMCO.NS", "ASIANPAINT.NS", "BAJAJFINSV.NS", "POWERGRID.NS",
    "M&M.NS", "NESTLEIND.NS", "JSWSTEEL.NS", "TMPV.NS", "TATASTEEL.NS",
    "TECHM.NS", "GRASIM.NS", "BPCL.NS", "ADANIPORTS.NS", "CIPLA.NS",
    "BRITANNIA.NS", "EICHERMOT.NS", "DRREDDY.NS", "HINDALCO.NS", "COALINDIA.NS",
    "DIVISLAB.NS", "TATACONSUM.NS", "SBILIFE.NS", "APOLLOHOSP.NS", "HDFCLIFE.NS",
    "INDUSINDBK.NS", "HEROMOTOCO.NS", "BAJAJ-AUTO.NS", "ETERNAL.NS", "SHRIRAMFIN.NS",
)


@st.cache_data(ttl=900)  # 15-min cache
def compute_market_breadth(tickers: tuple):
    """
    Fetch 1-year OHLCV for each ticker via Stooq (no rate limits) in parallel,
    then compute advance/decline, SMA positions, and 52-week extremes.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from data.fetcher import fetch_single

    tickers_list = list(tickers)

    def _fetch_one(t):
        try:
            return t, fetch_single(t, period="1y")
        except Exception:
            return t, None

    data_map = {}
    with ThreadPoolExecutor(max_workers=10) as pool:
        futs = {pool.submit(_fetch_one, t): t for t in tickers_list}
        for fut in as_completed(futs, timeout=45):
            try:
                t, df = fut.result(timeout=0)
                if df is not None and not df.empty:
                    data_map[t] = df
            except Exception:
                pass

    adv = dec = above_20 = above_50 = above_200 = near_hi = near_lo = counted = 0
    for t in tickers_list:
        try:
            df = data_map.get(t)
            if df is None or len(df) < 10:
                continue
            close = df["Close"]
            curr  = float(close.iloc[-1])
            prev  = float(close.iloc[-2])
            counted += 1
            if curr > prev:
                adv += 1
            else:
                dec += 1
            if len(df) >= 20 and curr > float(close.rolling(20).mean().iloc[-1]):
                above_20 += 1
            if len(df) >= 50 and curr > float(close.rolling(50).mean().iloc[-1]):
                above_50 += 1
            if len(df) >= 200 and curr > float(close.rolling(200).mean().iloc[-1]):
                above_200 += 1
            high52 = float(df["High"].max())
            low52  = float(df["Low"].min())
            if (high52 - curr) / max(high52, 1) * 100 < 5:
                near_hi += 1
            if (curr - low52) / max(low52, 1) * 100 < 5:
                near_lo += 1
        except Exception:
            continue

    n = max(counted, 1)
    return {
        "advance":       adv,
        "decline":       dec,
        "total":         counted,
        "ad_ratio":      round(adv / max(dec, 1), 2),
        "pct_above_20":  round(above_20  / n * 100, 1),
        "pct_above_50":  round(above_50  / n * 100, 1),
        "pct_above_200": round(above_200 / n * 100, 1),
        "near_52w_high": near_hi,
        "near_52w_low":  near_lo,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Shared chart builder
# ─────────────────────────────────────────────────────────────────────────────

def build_price_chart(df: pd.DataFrame, ticker: str) -> go.Figure:
    """
    4-panel trading chart: Price (candlestick + SMAs + BB) / Volume / RSI / MACD.
    Matches the layout of professional trading terminals.
    """
    fig = make_subplots(
        rows=4, cols=1, shared_xaxes=True,
        row_heights=[0.52, 0.14, 0.17, 0.17],
        vertical_spacing=0.02,
        subplot_titles=[f"{ticker} — Price", "Volume", "RSI (14)", "MACD"],
    )

    # ── Row 1: Candlestick ──────────────────────────────────────────────────
    fig.add_trace(go.Candlestick(
        x=df.index, open=df["Open"], high=df["High"],
        low=df["Low"], close=df["Close"],
        name="OHLC",
        increasing_line_color="#26a69a", increasing_fillcolor="#26a69a",
        decreasing_line_color="#ef5350", decreasing_fillcolor="#ef5350",
    ), row=1, col=1)

    if "BB_Upper" in df.columns:
        fig.add_trace(go.Scatter(
            x=df.index, y=df["BB_Upper"],
            line=dict(color="rgba(100,160,255,0.4)", dash="dash", width=1),
            name="BB Upper", showlegend=False,
        ), row=1, col=1)
        fig.add_trace(go.Scatter(
            x=df.index, y=df["BB_Lower"],
            fill="tonexty", fillcolor="rgba(100,160,255,0.06)",
            line=dict(color="rgba(100,160,255,0.4)", dash="dash", width=1),
            name="BB Lower", showlegend=False,
        ), row=1, col=1)

    for sma, color in [("SMA_20", "#FF9800"), ("SMA_50", "#2196F3"), ("SMA_200", "#9C27B0")]:
        if sma in df.columns:
            fig.add_trace(go.Scatter(
                x=df.index, y=df[sma], name=sma,
                line=dict(color=color, width=1.2),
            ), row=1, col=1)

    # ── Row 2: Volume bars (green = up day, red = down day) ─────────────────
    if "Volume" in df.columns:
        vol_colors = [
            "#26a69a" if c >= o else "#ef5350"
            for c, o in zip(df["Close"], df["Open"])
        ]
        fig.add_trace(go.Bar(
            x=df.index, y=df["Volume"],
            marker_color=vol_colors,
            name="Volume", showlegend=False,
            opacity=0.7,
        ), row=2, col=1)
        # 20-day avg volume line
        vol_ma = df["Volume"].rolling(20).mean()
        fig.add_trace(go.Scatter(
            x=df.index, y=vol_ma,
            line=dict(color="#FFD700", width=1.2, dash="dot"),
            name="Vol MA20", showlegend=False,
        ), row=2, col=1)

    # ── Row 3: RSI ──────────────────────────────────────────────────────────
    if "RSI" in df.columns:
        fig.add_trace(go.Scatter(
            x=df.index, y=df["RSI"], name="RSI",
            line=dict(color="#CE93D8", width=1.5),
        ), row=3, col=1)
        for level, color in [(30, "#26a69a"), (70, "#ef5350"), (50, "rgba(150,150,150,0.5)")]:
            fig.add_hline(y=level, line_dash="dot", line_color=color, row=3, col=1)
        # RSI overbought / oversold shading
        fig.add_hrect(y0=70, y1=100, fillcolor="rgba(239,83,80,0.06)",
                      line_width=0, row=3, col=1)
        fig.add_hrect(y0=0, y1=30, fillcolor="rgba(38,166,154,0.06)",
                      line_width=0, row=3, col=1)

    # ── Row 4: MACD ─────────────────────────────────────────────────────────
    if "MACD" in df.columns and "MACD_Signal" in df.columns:
        fig.add_trace(go.Scatter(
            x=df.index, y=df["MACD"], name="MACD",
            line=dict(color="#2196F3", width=1.5),
        ), row=4, col=1)
        fig.add_trace(go.Scatter(
            x=df.index, y=df["MACD_Signal"], name="Signal",
            line=dict(color="#FF9800", width=1.5),
        ), row=4, col=1)
        if "MACD_Hist" in df.columns:
            hist_colors = ["#26a69a" if v >= 0 else "#ef5350" for v in df["MACD_Hist"]]
            fig.add_trace(go.Bar(
                x=df.index, y=df["MACD_Hist"], name="Hist",
                marker_color=hist_colors, opacity=0.6,
            ), row=4, col=1)

    # ── NSE Pro Plotly layout ────────────────────────────────────────────────
    _NSE_GRID = dict(gridcolor="rgba(255,255,255,.04)", linecolor="rgba(255,255,255,.06)")
    _NSE_TICK = dict(color="#4a5568", size=10)
    fig.update_layout(
        height=720,
        paper_bgcolor="#070c18",
        plot_bgcolor="#0a1020",
        xaxis_rangeslider_visible=False,
        font=dict(family="Inter, -apple-system, sans-serif", color="#8899bb", size=11),
        legend=dict(
            orientation="h", y=1.02, x=0,
            bgcolor="rgba(7,12,24,.85)",
            bordercolor="rgba(255,255,255,.06)", borderwidth=1,
            font=dict(color="#8899bb", size=11),
        ),
        margin=dict(l=0, r=60, t=40, b=0),
        hoverlabel=dict(
            bgcolor="#0d1526", bordercolor="rgba(255,255,255,.1)",
            font=dict(color="#f0f4ff", family="Inter", size=12),
        ),
        hovermode="x unified",
    )
    # Apply grid style to all rows
    for row in range(1, 5):
        fig.update_xaxes(
            **_NSE_GRID, zeroline=False, tickfont=_NSE_TICK,
            row=row, col=1,
        )
        fig.update_yaxes(
            **_NSE_GRID, zeroline=False, tickfont=_NSE_TICK,
            side="right", row=row, col=1,
        )
    fig.update_yaxes(title_text="₹ Price",  title_font=dict(size=10,color="#4a5568"), row=1, col=1)
    fig.update_yaxes(title_text="Volume",   title_font=dict(size=10,color="#4a5568"), tickformat=".2s", row=2, col=1)
    fig.update_yaxes(title_text="RSI",      title_font=dict(size=10,color="#4a5568"), range=[0,100], row=3, col=1)
    fig.update_yaxes(title_text="MACD",     title_font=dict(size=10,color="#4a5568"), row=4, col=1)
    # Spike lines for crosshair
    fig.update_xaxes(showspikes=True, spikethickness=1, spikecolor="#5a6a8a", spikedash="dot")
    fig.update_yaxes(showspikes=True, spikethickness=1, spikecolor="#5a6a8a")
    return fig


# ── Live top bar: Nifty indices strip + scrolling ticker (auto-refresh 5 s) ───
# All Nifty indices the strip tries to show (failures are skipped gracefully).
_INDEX_STRIP = [
    ("NIFTY 50",   "^NSEI"),      ("BANK NIFTY", "^NSEBANK"),
    ("NIFTY IT",   "^CNXIT"),     ("NIFTY AUTO",  "^CNXAUTO"),
    ("NIFTY FMCG", "^CNXFMCG"),   ("NIFTY PHARMA","^CNXPHARMA"),
    ("NIFTY METAL","^CNXMETAL"),  ("NIFTY ENERGY","^CNXENERGY"),
]


@st.cache_data(ttl=5, show_spinner=False)        # 5-second freshness for live feel
def _index_strip_data():
    """Live value + day-change % for each Nifty index via Yahoo chart meta."""
    import json, urllib.parse, urllib.request
    try:
        from data.fetcher import _get_yf_crumb
        _opener, _crumb = _get_yf_crumb()
    except Exception:
        _opener, _crumb = None, ""
    _qs = f"&crumb={urllib.parse.quote(_crumb)}" if _crumb else ""
    _open = _opener.open if _opener else urllib.request.urlopen
    out = []
    for label, sym in _INDEX_STRIP:
        try:
            url = (f"https://query1.finance.yahoo.com/v8/finance/chart/"
                   f"{urllib.parse.quote(sym)}?interval=1d&range=5d{_qs}")
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0", "Accept": "application/json"})
            with _open(req, timeout=6) as r:
                meta = json.loads(r.read())["chart"]["result"][0]["meta"]
            price = meta.get("regularMarketPrice")
            prev  = meta.get("chartPreviousClose") or meta.get("previousClose")
            if price and prev:
                out.append((label, float(price), (float(price) / float(prev) - 1) * 100))
        except Exception:
            continue
    return out


@st.cache_data(ttl=30, show_spinner=False)
def _ticker_tape_data():
    _names = ["RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "ICICIBANK.NS", "INFY.NS",
              "SBIN.NS", "BHARTIARTL.NS", "ITC.NS", "LT.NS", "AXISBANK.NS",
              "MARUTI.NS", "TATAMOTORS.NS", "SUNPHARMA.NS", "TITAN.NS"]
    try:
        from utils.live_price import get_live_prices_batch
        raw = get_live_prices_batch(_names, max_workers=10)
    except Exception:
        raw = {}
    out = []
    for t in _names:
        q = raw.get(t)
        if isinstance(q, dict) and q.get("price"):
            out.append((t.replace(".NS", ""), float(q["price"]), float(q.get("chg_pct", 0.0))))
    return out