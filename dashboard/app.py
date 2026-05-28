"""
dashboard/app.py — NSE Smart Investor Platform
Streamlit web dashboard — 6-page non-trader friendly interface.

Pages:
    1. 🏠 My Portfolio    — Upload CSV → traffic-light health per holding
    2. 🔍 Analyze Stock   — Enter any NSE ticker → composite score + narrative
    3. 📊 Market Overview — India VIX gauge + top movers + sector heatmap
    4. 🔎 Smart Screener  — 4-screen scanner across NIFTY50/100/200/500
    5. 📂 Paper Trades    — Live paper trading log + journal export
    6. 🧪 Backtest        — Historical strategy performance

Run:
    streamlit run dashboard/app.py
"""

import os
import sys
import sqlite3
import warnings
import io

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
import streamlit as st

warnings.filterwarnings("ignore")

# ── ensure project root is on sys.path ───────────────────────────────────────
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="NSE Smart Investor",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Custom CSS — non-trader friendly cards ────────────────────────────────────
st.markdown("""
<style>
.card-green  { background:#1a3a2a; border-left:5px solid #26a69a; border-radius:8px;
               padding:14px 18px; margin:6px 0; }
.card-yellow { background:#3a3210; border-left:5px solid #f9a825; border-radius:8px;
               padding:14px 18px; margin:6px 0; }
.card-red    { background:#3a1a1a; border-left:5px solid #ef5350; border-radius:8px;
               padding:14px 18px; margin:6px 0; }
.card-blue   { background:#0d1f3c; border-left:5px solid #2196F3; border-radius:8px;
               padding:14px 18px; margin:6px 0; }
.score-big   { font-size:48px; font-weight:700; }
.signal-big  { font-size:22px; font-weight:700; }
.narrative   { font-size:15px; line-height:1.6; color:#e0e0e0; }
.ticker-label{ font-size:20px; font-weight:700; color:#fff; }
</style>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
# Sidebar
# ─────────────────────────────────────────────────────────────────────────────
st.sidebar.title("📈 NSE Smart Investor")
st.sidebar.markdown("*Your AI-powered equity companion*")
st.sidebar.markdown("---")

page = st.sidebar.radio(
    "Navigate to",
    [
        "📡 Market Live",
        "🏠 My Portfolio",
        "🔍 Analyze Stock",
        "📊 Market Overview",
        "🔎 Smart Screener",
        "📂 Paper Trades",
        "🧪 Backtest",
        "🌍 Macro Dashboard",
        "📈 Market Breadth",
        "🏦 OI & Options Setup",
        "📖 Investor Guide",
    ],
    key="nav",
)

st.sidebar.markdown("---")

# ── Sidebar live data — fetched in parallel with a hard 12-second timeout ────
@st.cache_data(ttl=600, show_spinner=False)
def _sidebar_all():
    """Fetch VIX + 4 macro instruments concurrently. Returns in <10s or gives up.

    NOTE: We deliberately do NOT use `with ThreadPoolExecutor() as pool:` because
    that context manager calls pool.shutdown(wait=True) on exit, which blocks until
    ALL threads finish — including any that are stuck/hanging.  Instead we call
    pool.shutdown(wait=False) after collecting whatever completed within the timeout.
    """
    import yfinance as yf
    from concurrent.futures import ThreadPoolExecutor, wait as _wait

    def _dl(sym):
        try:
            import requests, urllib3
            urllib3.disable_warnings()
            session = requests.Session()
            adapter = requests.adapters.HTTPAdapter(max_retries=0)
            session.mount("https://", adapter)
            df = yf.download(sym, period="2d", interval="1d",
                             auto_adjust=True, progress=False,
                             session=session)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            return sym, df
        except Exception:
            return sym, pd.DataFrame()

    symbols = {
        "^INDIAVIX": "vix",
        "^NSEI": "Nifty",
        "^NSEBANK": "BNifty",
        "GC=F": "Gold",
        "BZ=F": "Crude",
    }
    results = {}
    pool = ThreadPoolExecutor(max_workers=5)
    try:
        futs = {pool.submit(_dl, sym): (sym, name) for sym, name in symbols.items()}
        done, _ = _wait(list(futs.keys()), timeout=10)
        for fut in done:
            sym, name = futs[fut]
            try:
                _, df = fut.result(timeout=0)
                if len(df) >= 2:
                    results[name] = df
            except Exception:
                pass
    finally:
        # Don't wait for stuck threads — let them die as daemon threads
        pool.shutdown(wait=False)

    # Parse VIX
    vix_data = (None, None, "Unknown", "⚪")
    if "vix" in results:
        try:
            import math as _m
            v   = results["vix"].dropna(subset=["Close"])  # drop incomplete row
            val = float(v["Close"].iloc[-1])
            prev= float(v["Close"].iloc[-2]) if len(v) >= 2 else val
            chg = (val / prev - 1) * 100 if prev > 0 else 0.0
            if _m.isnan(val) or val <= 0:
                raise ValueError("VIX NaN")
            if val < 16:   reg, col = "Normal", "🟢"
            elif val < 22: reg, col = "Elevated", "🟡"
            elif val < 28: reg, col = "Fear", "🔴"
            else:          reg, col = "PANIC", "🔴"
            vix_data = (val, chg, reg, col)
        except Exception:
            pass

    # Parse macro pulse
    pulse = {}
    dp_map = {"Nifty": 0, "BNifty": 0, "Gold": 1, "Crude": 2}
    for name in ("Nifty", "BNifty", "Gold", "Crude"):
        if name in results:
            try:
                df = results[name].dropna(subset=["Close"])
                if len(df) < 2:
                    continue
                c, p = float(df["Close"].iloc[-1]), float(df["Close"].iloc[-2])
                pulse[name] = (c, (c / p - 1) * 100, dp_map[name])
            except Exception:
                pass

    return vix_data, pulse

try:
    _vix_data, _pulse = _sidebar_all()
    vix_val, vix_chg, vix_reg, vix_col = _vix_data
except Exception:
    vix_val, vix_chg, vix_reg, vix_col = None, None, "Unknown", "⚪"
    _pulse = {}

if vix_val:
    chg_str = f"{vix_chg:+.1f}%"
    st.sidebar.markdown(
        f"**Market Fear Gauge (VIX)**  \n"
        f"{vix_col} **{vix_val:.2f}** ({chg_str})  \n"
        f"Regime: **{vix_reg}**"
    )
else:
    st.sidebar.markdown("VIX: *—*")

for name, (price, chg, dp) in _pulse.items():
    clr   = "#26a69a" if chg >= 0 else "#ef5350"
    arrow = "▲" if chg >= 0 else "▼"
    st.sidebar.markdown(
        f'<span style="font-size:11px"><b>{name}</b> '
        f'{price:,.{dp}f} '
        f'<span style="color:{clr}">{arrow}{abs(chg):.1f}%</span></span>',
        unsafe_allow_html=True,
    )

st.sidebar.markdown("---")

# ── Market status indicator ────────────────────────────────────────────────────
try:
    from utils.market_hours import market_status as _mstatus
    _ms = _mstatus()
    st.sidebar.markdown(
        f"**NSE Market**  \n"
        f"{_ms['color']} **{_ms['status']}**  \n"
        f"<span style='font-size:11px'>{_ms['time_ist']} · {_ms['detail']}</span>",
        unsafe_allow_html=True,
    )
    if _ms["is_open"]:
        if st.sidebar.button("🔄 Refresh Prices", key="sidebar_refresh"):
            st.cache_data.clear()
            st.rerun()
except Exception:
    pass

st.sidebar.markdown("---")
st.sidebar.markdown(
    "⚠️ *For educational use only.*  \n"
    "Not SEBI registered advice.  \n"
    "Past performance ≠ future results."
)


# ─────────────────────────────────────────────────────────────────────────────
# Company name → ticker map  (used for search autocomplete)
# ─────────────────────────────────────────────────────────────────────────────
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


# ─────────────────────────────────────────────────────────────────────────────
# Shared helpers
# ─────────────────────────────────────────────────────────────────────────────

@st.cache_data(ttl=300)
def load_ticker_df(ticker: str, period: str = "1y") -> pd.DataFrame:
    from data.fetcher import fetch_single
    from utils.indicators import add_all_indicators
    df = fetch_single(ticker, period=period)
    df = add_all_indicators(df)
    return df


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
    try:
        from trading.signals import get_india_vix_regime
        return get_india_vix_regime()
    except Exception:
        return {"vix": 18.0, "regime": "NORMAL", "allow_buy": True, "vix_pct_chg": 0.0}


@st.cache_data(ttl=600)
def get_composite_score(ticker: str, period: str = "1y"):
    from analysis.score import score_stock
    vix_info = get_vix_info()
    return score_stock(ticker, period=period, vix_info=vix_info)


def load_trades_db(path: str = "trades.db") -> pd.DataFrame:
    if not os.path.exists(path):
        return pd.DataFrame()
    with sqlite3.connect(path) as conn:
        try:
            return pd.read_sql_query("SELECT * FROM trades ORDER BY id DESC", conn)
        except Exception:
            return pd.DataFrame()


def _ensure_paper_db(path: str = "trades.db"):
    """Create paper-trading SQLite tables if they don't exist."""
    with sqlite3.connect(path) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker      TEXT    NOT NULL,
                strategy    TEXT    NOT NULL DEFAULT 'Manual',
                action      TEXT    NOT NULL,
                price       REAL    NOT NULL,
                quantity    INTEGER NOT NULL,
                sl          REAL,
                tp          REAL,
                trail_stop  REAL,
                capital     REAL,
                reason      TEXT,
                timestamp   TEXT    NOT NULL,
                status      TEXT    DEFAULT 'OPEN',
                exit_price  REAL,
                exit_reason TEXT,
                exit_time   TEXT,
                pnl         REAL,
                pnl_pct     REAL
            )
        """)
        conn.commit()


def paper_open_trade(ticker: str, price: float, qty: int,
                     sl: float, tp: float, reason: str = "",
                     path: str = "trades.db") -> int:
    """Insert a new paper BUY trade. Returns new row id."""
    _ensure_paper_db(path)
    now = __import__("datetime").datetime.now().isoformat()
    with sqlite3.connect(path) as conn:
        cur = conn.execute(
            "INSERT INTO trades (ticker,strategy,action,price,quantity,sl,tp,capital,reason,timestamp) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (ticker, "Manual", "BUY", price, qty, sl, tp, price * qty, reason, now)
        )
        conn.commit()
        return cur.lastrowid


def paper_close_trade(trade_id: int, exit_price: float,
                      reason: str = "Manual close", path: str = "trades.db"):
    """Close an open paper trade by ID."""
    now = __import__("datetime").datetime.now().isoformat()
    with sqlite3.connect(path) as conn:
        row = conn.execute(
            "SELECT price, quantity FROM trades WHERE id=?", (trade_id,)
        ).fetchone()
        if not row:
            return
        entry_price, qty = row
        pnl     = (exit_price - entry_price) * qty
        pnl_pct = (exit_price / entry_price - 1) * 100 if entry_price > 0 else 0
        conn.execute(
            "UPDATE trades SET status='CLOSED', exit_price=?, exit_time=?, "
            "exit_reason=?, pnl=?, pnl_pct=? WHERE id=?",
            (exit_price, now, reason, pnl, pnl_pct, trade_id)
        )
        conn.commit()


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
        if q and q.get("price"):
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
# Macro / Breadth helpers  (for new pages 7–9)
# ─────────────────────────────────────────────────────────────────────────────

@st.cache_data(ttl=600)
def load_macro_data():
    import yfinance as yf
    symbols = {
        "Nifty 50":    "^NSEI",
        "BankNifty":   "^NSEBANK",
        "India VIX":   "^INDIAVIX",
        "Gold ($/oz)": "GC=F",
        "Brent Crude": "BZ=F",
        "USD/INR":     "USDINR=X",
        "DXY":         "DX-Y.NYB",
    }
    data = {}
    for name, sym in symbols.items():
        try:
            df = yf.download(sym, period="3mo", interval="1d",
                             auto_adjust=True, progress=False)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
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


@st.cache_data(ttl=900)  # 15-min cache — slow scan
def compute_market_breadth(tickers: tuple):
    import yfinance as yf
    adv = dec = above_20 = above_50 = above_200 = near_hi = near_lo = counted = 0
    for t in tickers:
        try:
            df = yf.download(t, period="1y", interval="1d",
                             auto_adjust=True, progress=False)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            if len(df) < 10:
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
    fig = make_subplots(
        rows=3, cols=1, shared_xaxes=True,
        row_heights=[0.6, 0.2, 0.2],
        vertical_spacing=0.02,
        subplot_titles=[f"{ticker} — Price", "RSI (14)", "MACD"],
    )
    fig.add_trace(go.Candlestick(
        x=df.index, open=df["Open"], high=df["High"],
        low=df["Low"], close=df["Close"],
        name="OHLC", increasing_line_color="#26a69a",
        decreasing_line_color="#ef5350",
    ), row=1, col=1)
    if "BB_Upper" in df.columns:
        fig.add_trace(go.Scatter(
            x=df.index, y=df["BB_Upper"],
            line=dict(color="rgba(100,160,255,0.4)", dash="dash"),
            name="BB Upper", showlegend=False,
        ), row=1, col=1)
        fig.add_trace(go.Scatter(
            x=df.index, y=df["BB_Lower"],
            fill="tonexty", fillcolor="rgba(100,160,255,0.05)",
            line=dict(color="rgba(100,160,255,0.4)", dash="dash"),
            name="BB Lower", showlegend=False,
        ), row=1, col=1)
    for sma, color in [("SMA_20", "#FF9800"), ("SMA_50", "#2196F3"), ("SMA_200", "#9C27B0")]:
        if sma in df.columns:
            fig.add_trace(go.Scatter(
                x=df.index, y=df[sma], name=sma,
                line=dict(color=color, width=1),
            ), row=1, col=1)
    if "RSI" in df.columns:
        fig.add_trace(go.Scatter(
            x=df.index, y=df["RSI"], name="RSI",
            line=dict(color="#9C27B0", width=1.5),
        ), row=2, col=1)
        for level, color in [(30, "green"), (70, "red"), (50, "gray")]:
            fig.add_hline(y=level, line_dash="dot", line_color=color, row=2, col=1)
    if "MACD" in df.columns and "MACD_Signal" in df.columns:
        fig.add_trace(go.Scatter(
            x=df.index, y=df["MACD"], name="MACD",
            line=dict(color="#2196F3"),
        ), row=3, col=1)
        fig.add_trace(go.Scatter(
            x=df.index, y=df["MACD_Signal"], name="Signal",
            line=dict(color="#FF9800"),
        ), row=3, col=1)
        if "MACD_Hist" in df.columns:
            colors = ["#26a69a" if v >= 0 else "#ef5350" for v in df["MACD_Hist"]]
            fig.add_trace(go.Bar(
                x=df.index, y=df["MACD_Hist"], name="Hist",
                marker_color=colors,
            ), row=3, col=1)
    fig.update_layout(
        height=680, template="plotly_dark",
        xaxis_rangeslider_visible=False,
        legend=dict(orientation="h", y=1.02),
        margin=dict(l=0, r=0, t=40, b=0),
    )
    return fig


# ═══════════════════════════════════════════════════════════════════════════════
# PAGE 0 — MARKET LIVE
# ═══════════════════════════════════════════════════════════════════════════════
if page == "📡 Market Live":
    from utils.market_hours import market_status as _ms_fn, refresh_interval_seconds
    from utils.news import get_market_news, get_stock_news, _quick_sentiment

    _ms = _ms_fn()
    ri  = refresh_interval_seconds()

    # ── Auto-refresh via meta tag when market is open ──────────────────────────
    if ri > 0:
        st.markdown(f'<meta http-equiv="refresh" content="{ri}">',
                    unsafe_allow_html=True)

    # ── Header ─────────────────────────────────────────────────────────────────
    col_h1, col_h2 = st.columns([3, 1])
    with col_h1:
        st.title("📡 Market Live")
        st.markdown("Real-time NSE prices · Top movers · News signals")
    with col_h2:
        st.markdown(f"""
        <div style='text-align:right;margin-top:12px'>
        <span style='font-size:22px'>{_ms['color']}</span><br>
        <b style='font-size:16px'>{_ms['status']}</b><br>
        <span style='font-size:11px;color:#aaa'>{_ms['time_ist']}</span>
        </div>""", unsafe_allow_html=True)
        if st.button("🔄 Refresh Now"):
            st.cache_data.clear()
            st.rerun()

    st.markdown(f"*{_ms['day']} — {_ms['detail']}*")
    st.markdown("---")

    # ── Fetch Nifty 50 prices — batch download (2 HTTP calls for all 50 tickers) ─
    @st.cache_data(ttl=180 if _ms["is_open"] else 3600, show_spinner=False)
    def _load_nifty_snapshot():
        """
        Batch snapshot — 2 HTTP requests total instead of 100 individual ones.
        yf.download(list_of_tickers) returns MultiIndex columns (ticker, field)
        when group_by='ticker'. We extract each ticker's slice from those DataFrames.
          - prev_close : yesterday's EOD close
          - curr_price : latest intraday bar (5 m) → falls back to EOD when market closed
          - chg_pct    : (curr / prev − 1) × 100
          - vol_ratio  : today's volume vs 20-day average
        """
        import yfinance as yf
        import pandas as pd
        from data.fetcher import NIFTY50_TICKERS

        tickers_list = list(NIFTY50_TICKERS)

        try:
            # ONE call → all 50 tickers, intraday
            intra_raw = yf.download(
                tickers_list, period="1d", interval="5m",
                auto_adjust=True, progress=False, group_by="ticker",
            )
            # ONE call → all 50 tickers, daily (prev close + avg volume)
            daily_raw = yf.download(
                tickers_list, period="30d", interval="1d",
                auto_adjust=True, progress=False, group_by="ticker",
            )
        except Exception:
            return pd.DataFrame()

        daily_multi = isinstance(daily_raw.columns, pd.MultiIndex)
        intra_multi = isinstance(intra_raw.columns, pd.MultiIndex)

        rows = []
        for t in tickers_list:
            try:
                # ── Extract daily slice ────────────────────────────────────────
                if daily_multi:
                    lvl0 = daily_raw.columns.get_level_values(0)
                    if t not in lvl0:
                        continue
                    daily = daily_raw[t].copy()
                else:
                    daily = daily_raw.copy()

                daily = daily.dropna(subset=["Close"])
                if len(daily) < 2:
                    continue

                prev_close = float(daily["Close"].iloc[-1])
                avg_vol    = float(daily["Volume"].tail(20).mean())

                # ── Extract intraday slice ─────────────────────────────────────
                if intra_multi:
                    lvl0_i = intra_raw.columns.get_level_values(0)
                    if t in lvl0_i:
                        intra = intra_raw[t].dropna(subset=["Close"])
                    else:
                        intra = pd.DataFrame()
                else:
                    intra = intra_raw.dropna(subset=["Close"]) if not intra_raw.empty else pd.DataFrame()

                if len(intra) > 0:
                    curr      = float(intra["Close"].iloc[-1])
                    today_vol = float(intra["Volume"].sum())
                else:
                    # Market closed — show yesterday's change vs the day before
                    curr       = prev_close
                    prev_close = float(daily["Close"].iloc[-2])
                    today_vol  = float(daily["Volume"].iloc[-1])

                chg   = (curr / prev_close - 1) * 100 if prev_close > 0 else 0.0
                vol_r = today_vol / avg_vol if avg_vol > 0 else 1.0

                rows.append({
                    "ticker":     t,
                    "name":       get_display_name(t),
                    "price":      curr,
                    "prev_close": prev_close,
                    "chg_pct":    chg,
                    "vol_ratio":  vol_r,
                })
            except Exception:
                continue

        if not rows:
            return pd.DataFrame()
        return pd.DataFrame(rows).sort_values("chg_pct", ascending=False)

    with st.spinner("Loading Nifty 50 snapshot…"):
        snap = _load_nifty_snapshot()

    if snap.empty:
        st.warning("Could not fetch market data. yfinance may be rate-limited — try again in 30 seconds.")
    else:
        # ── Top metrics row ────────────────────────────────────────────────────
        adv = (snap["chg_pct"] > 0).sum()
        dec = (snap["chg_pct"] < 0).sum()
        unch = len(snap) - adv - dec
        avg_chg = snap["chg_pct"].mean()

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Nifty 50 Stocks", f"{len(snap)} tracked")
        m2.metric("Advances / Declines", f"{adv} / {dec}",
                  delta=f"{adv-dec:+d} net", delta_color="normal" if adv >= dec else "inverse")
        m3.metric("Avg Change", f"{avg_chg:+.2f}%",
                  delta_color="normal" if avg_chg >= 0 else "inverse")
        m4.metric("Unchanged", str(unch))

        st.markdown("---")

        # ── Gainers and Losers ─────────────────────────────────────────────────
        top5 = snap.head(5)
        bot5 = snap.tail(5).iloc[::-1]

        col_g, col_l = st.columns(2)

        @st.cache_data(ttl=300, show_spinner=False)
        def _explain_mover(ticker: str, chg_pct: float, vol_ratio: float) -> list:
            """Generate 2-4 plain-English reasons why a stock is moving."""
            reasons = []
            try:
                import yfinance as yf
                import math
                df = yf.download(ticker, period="3mo", interval="1d",
                                 auto_adjust=True, progress=False)
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)
                df = df.dropna(subset=["Close"])
                if len(df) < 20:
                    return reasons

                last    = df.iloc[-1]
                close   = float(last["Close"])
                high52  = float(df["High"].max())
                low52   = float(df["Low"].min())
                sma20   = df["Close"].rolling(20).mean().iloc[-1]
                sma50   = df["Close"].rolling(50).mean().iloc[-1] if len(df) >= 50 else close

                # RSI
                delta   = df["Close"].diff()
                gain    = delta.clip(lower=0).rolling(14).mean()
                loss    = (-delta.clip(upper=0)).rolling(14).mean()
                rs      = gain / loss
                rsi     = float((100 - 100 / (1 + rs)).iloc[-1])

                # Volume
                if vol_ratio >= 2.5:
                    reasons.append(f"Massive volume surge ({vol_ratio:.1f}x average) — likely institutional activity")
                elif vol_ratio >= 1.5:
                    reasons.append(f"Above-average volume ({vol_ratio:.1f}x) — elevated interest")

                # RSI
                if rsi > 72:
                    reasons.append(f"RSI overbought ({rsi:.0f}) — strong momentum, watch for pullback")
                elif rsi < 30:
                    reasons.append(f"RSI oversold ({rsi:.0f}) — heavy selling, potential bounce zone")
                elif 50 < rsi < 65 and chg_pct > 0:
                    reasons.append(f"RSI healthy ({rsi:.0f}) — momentum building, not yet overbought")

                # 52-week position
                pct_from_high = (high52 - close) / high52 * 100
                pct_from_low  = (close - low52) / low52 * 100
                if pct_from_high < 2:
                    reasons.append("At 52-week high — breakout territory")
                elif pct_from_low < 3:
                    reasons.append("Near 52-week low — support zone / turnaround candidate")

                # Trend
                if not math.isnan(sma20) and not math.isnan(sma50):
                    if close > sma20 > sma50:
                        reasons.append("Above SMA20 and SMA50 — uptrend intact")
                    elif close < sma20 < sma50:
                        reasons.append("Below SMA20 and SMA50 — downtrend pressure")

                # News
                news = get_stock_news(ticker, max_articles=1)
                if news:
                    h = news[0]["title"][:90]
                    s = news[0]["sentiment"]
                    icon = "📰" if s == "neutral" else ("🟢" if s == "positive" else "🔴")
                    reasons.append(f"{icon} News: {h}…")

            except Exception:
                pass
            return reasons if reasons else ["No specific technical catalyst detected"]

        def _mover_card(row, is_gainer: bool):
            chg   = row["chg_pct"]
            price = row["price"]
            prev  = row.get("prev_close", price)
            name  = row["name"]
            tick  = row["ticker"].replace(".NS", "")
            vol_r = row["vol_ratio"]
            arrow = "▲" if is_gainer else "▼"

            with st.expander(
                f"{arrow} **{tick}** — {name}  |  ₹{price:,.2f}  |  {chg:+.2f}%",
                expanded=True,
            ):
                rc1, rc2, rc3 = st.columns(3)
                rc1.metric("Live Price", f"₹{price:,.2f}", f"{chg:+.2f}%",
                           delta_color="normal" if is_gainer else "inverse")
                rc2.metric("Prev Close", f"₹{prev:,.2f}")
                rc3.metric("Volume Ratio", f"{vol_r:.2f}x")

                reasons = _explain_mover(row["ticker"], chg, vol_r)
                for r in reasons:
                    st.markdown(f"• {r}")

        with col_g:
            st.subheader("🟢 Top Gainers (Nifty 50)")
            for _, row in top5.iterrows():
                _mover_card(row, is_gainer=True)

        with col_l:
            st.subheader("🔴 Top Losers (Nifty 50)")
            for _, row in bot5.iterrows():
                _mover_card(row, is_gainer=False)

        # ── Full Nifty 50 heatmap table ────────────────────────────────────────
        st.markdown("---")
        with st.expander("📋 Full Nifty 50 Snapshot", expanded=False):
            disp = snap[["name", "ticker", "price", "chg_pct", "vol_ratio"]].copy()
            disp.columns = ["Company", "Ticker", "Price (₹)", "Change %", "Vol Ratio"]
            disp["Ticker"]    = disp["Ticker"].str.replace(".NS", "")
            disp["Price (₹)"] = disp["Price (₹)"].map("₹{:,.2f}".format)
            disp["Change %"]  = disp["Change %"].map("{:+.2f}%".format)
            disp["Vol Ratio"] = disp["Vol Ratio"].map("{:.2f}x".format)
            st.dataframe(disp)

    # ── Market News ────────────────────────────────────────────────────────────
    st.markdown("---")
    st.subheader("📰 Latest Market News")
    with st.spinner("Loading news…"):
        mkt_news = get_market_news(max_articles=8)

    if mkt_news:
        for article in mkt_news:
            s = article["sentiment"]
            icon = "🟢" if s == "positive" else ("🔴" if s == "negative" else "⚪")
            st.markdown(
                f'{icon} **[{article["title"]}]({article["link"]})**  \n'
                f'<span style="font-size:11px;color:#aaa">'
                f'{article["publisher"]} · {article["time"]}</span>',
                unsafe_allow_html=True,
            )
    else:
        st.info("News unavailable — yfinance may be rate-limited. Try again shortly.")

    if ri > 0:
        st.caption(f"Auto-refreshes every {ri//60} minutes while market is open.")


# ═══════════════════════════════════════════════════════════════════════════════
# PAGE 1 — MY PORTFOLIO
# ═══════════════════════════════════════════════════════════════════════════════
elif page == "🏠 My Portfolio":
    st.title("🏠 My Portfolio")
    st.markdown(
        "Your holdings health check — live prices, plain English buy/hold/sell recommendations, and news for each stock."
    )

    # ── Auto-load default portfolio.csv OR let user upload ────────────────────
    import pathlib as _pl
    _DEFAULT_CSV = _pl.Path(_ROOT) / "portfolio.csv"

    col_ul, col_sample = st.columns([2, 1])

    with col_ul:
        uploaded = st.file_uploader(
            "Upload a different portfolio CSV (optional — default portfolio.csv auto-loads)",
            type=["csv"],
            help="Columns: ticker, quantity, avg_buy_price, date_bought",
        )

    with col_sample:
        sample_csv = (
            "ticker,quantity,avg_buy_price,date_bought\n"
            "RELIANCE,10,1350.00,2024-01-15\n"
            "TCS,5,3800.00,2024-03-10\n"
            "HDFCBANK,20,1600.00,2024-02-01\n"
        )
        st.download_button(
            "📥 Download sample CSV",
            data=sample_csv,
            file_name="sample_portfolio.csv",
            mime="text/csv",
        )
        st.caption("Tickers without .NS suffix are auto-resolved (e.g. RELIANCE → RELIANCE.NS)")

    # Resolve which file to analyse
    import tempfile
    if uploaded is not None:
        tmp = _pl.Path(tempfile.mktemp(suffix=".csv"))
        tmp.write_bytes(uploaded.read())
        _csv_source = tmp
        st.success("Using uploaded portfolio file.")
    elif _DEFAULT_CSV.exists():
        _csv_source = _DEFAULT_CSV
        st.info(f"Auto-loaded: **portfolio.csv** ({len(pd.read_csv(_DEFAULT_CSV))} holdings found)")
    else:
        _csv_source = None

    if _csv_source is not None:

        # ── LIVE PRICES STRIP (fast, 60-second cache) ─────────────────────────
        try:
            _port_csv = pd.read_csv(_csv_source)
            _port_tickers = tuple(
                (t if t.endswith(".NS") else t + ".NS")
                for t in _port_csv["ticker"].tolist()
            )
            _live_col, _refresh_col = st.columns([5, 1])
            with _refresh_col:
                st.write("")
                if st.button("🔄 Refresh Prices", key="port_refresh_live"):
                    st.cache_data.clear()
            with _live_col:
                st.markdown("#### 📡 Live Prices (updates every 60 s)")
            _live_prices = _portfolio_live_prices(_port_tickers)
            if _live_prices:
                _lp_rows = []
                for _row in _port_csv.itertuples():
                    _sym = _row.ticker if str(_row.ticker).endswith(".NS") else f"{_row.ticker}.NS"
                    _lp  = _live_prices.get(_sym, {})
                    _cur = _lp.get("price")
                    _chg = _lp.get("chg", 0.0)
                    _qty = getattr(_row, "quantity", 1)
                    _buy = getattr(_row, "avg_buy_price", 0)
                    if _cur:
                        _today_pnl  = (_cur - _lp.get("prev", _cur)) * _qty
                        _total_pnl  = (_cur - _buy) * _qty
                        _total_pct  = (_cur / _buy - 1) * 100 if _buy > 0 else 0
                        _lp_rows.append({
                            "Stock":        _row.ticker,
                            "Live Price":   f"₹{_cur:,.2f}",
                            "Today":        f"{_chg:+.2f}%",
                            "Today P&L":    f"₹{_today_pnl:+,.0f}",
                            "Total Return": f"{_total_pct:+.1f}%",
                            "Total P&L":    f"₹{_total_pnl:+,.0f}",
                        })
                    else:
                        _lp_rows.append({
                            "Stock":        _row.ticker,
                            "Live Price":   "—",
                            "Today":        "—",
                            "Today P&L":    "—",
                            "Total Return": "—",
                            "Total P&L":    "—",
                        })
                st.dataframe(pd.DataFrame(_lp_rows), hide_index=True, width="stretch")
            else:
                st.caption("⚠️ Live prices unavailable — yfinance rate-limited. Showing EOD data below.")
        except Exception as _e:
            st.caption(f"Live price strip skipped: {_e}")

        st.markdown("---")
        with st.spinner("Scoring your portfolio… this takes 30–60 seconds for 5–10 stocks"):
            try:
                from analysis.portfolio_manager import PortfolioManager
                pm = PortfolioManager(_csv_source)
                summary = pm.mark_to_market()

                # ── Top summary banner ─────────────────────────────────────
                pnl_sign = "+" if summary.total_pnl >= 0 else ""
                pnl_color = "#26a69a" if summary.total_pnl >= 0 else "#ef5350"

                st.markdown("---")
                c1, c2, c3, c4, c5 = st.columns(5)
                c1.metric("Portfolio Value",
                          f"₹{summary.total_current_value:,.0f}",
                          f"{pnl_sign}₹{summary.total_pnl:,.0f}")
                c2.metric("Total Return",
                          f"{pnl_sign}{summary.total_pnl_pct:.1f}%",
                          delta_color="normal" if summary.total_pnl >= 0 else "inverse")
                c3.metric("Health Score",
                          f"{summary.portfolio_score:.0f}/100",
                          f"Grade {summary.portfolio_grade}")
                c4.metric("Diversification",
                          summary.diversification.concentration_risk)
                c5.metric("VIX Regime", summary.vix_regime)

                # ── Overall narrative ──────────────────────────────────────
                st.markdown(
                    f'<div class="card-blue"><span class="narrative">'
                    f'💡 <b>Portfolio Summary:</b> {summary.summary_narrative}'
                    f'</span></div>',
                    unsafe_allow_html=True
                )

                # ── Diversification ────────────────────────────────────────
                div = summary.diversification
                if div.sector_weights:
                    with st.expander("📊 Sector Breakdown", expanded=False):
                        div_df = pd.DataFrame(
                            list(div.sector_weights.items()),
                            columns=["Sector", "Weight (%)"]
                        ).sort_values("Weight (%)", ascending=False)
                        col_pie, col_txt = st.columns([1, 1])
                        with col_pie:
                            fig_pie = px.pie(
                                div_df, names="Sector", values="Weight (%)",
                                title="Portfolio by Sector",
                                color_discrete_sequence=px.colors.qualitative.Set3,
                            )
                            fig_pie.update_layout(
                                template="plotly_dark", height=300,
                                margin=dict(l=0, r=0, t=40, b=0),
                            )
                            st.plotly_chart(fig_pie, width="stretch")
                        with col_txt:
                            risk_color = {"LOW": "card-green", "MEDIUM": "card-yellow",
                                          "HIGH": "card-red", "VERY HIGH": "card-red"}.get(
                                div.concentration_risk, "card-blue")
                            st.markdown(
                                f'<div class="{risk_color}">'
                                f'<b>Concentration Risk: {div.concentration_risk}</b><br>'
                                f'{div.advice}'
                                f'</div>',
                                unsafe_allow_html=True
                            )

                # ── Holdings cards ─────────────────────────────────────────
                st.markdown("---")
                st.subheader("📋 Your Holdings — What to Do")

                for h in summary.holdings:
                    card_class = _action_color(h.action)
                    emoji = _action_emoji(h.action)
                    pnl_str = f"{'+' if h.pnl >= 0 else ''}{h.pnl_pct:.1f}%  (₹{'+' if h.pnl >= 0 else ''}{h.pnl:,.0f})"
                    grade_color = _grade_color(h.grade)

                    with st.expander(
                        f"{emoji} {h.ticker.replace('.NS','')} — {h.signal}  |  "
                        f"P&L: {pnl_str}  |  Score: {h.score:.0f}/100 [{h.grade}]",
                        expanded=False,
                    ):
                        row1, row2, row3 = st.columns(3), st.columns(4), st.columns(1)

                        with st.container():
                            cols_info = st.columns(4)
                            cols_info[0].metric("Buy Price",    f"₹{h.avg_buy_price:,.2f}")
                            cols_info[1].metric("Current",      f"₹{h.current_price:,.2f}",
                                                f"{'+' if h.pnl_pct >= 0 else ''}{h.pnl_pct:.1f}%")
                            cols_info[2].metric("Quantity",     f"{h.quantity:.0f} shares")
                            cols_info[3].metric("Days Held",    f"{h.days_held}d")

                            cols_lvl = st.columns(4)
                            cols_lvl[0].metric("Score",         f"{h.score:.0f}/100  [{h.grade}]")
                            cols_lvl[1].metric("Stop-Loss",     f"₹{h.stop_loss:,.2f}")
                            cols_lvl[2].metric("Target",        f"₹{h.target:,.2f}")
                            cols_lvl[3].metric("Risk:Reward",   f"{h.risk_reward:.1f}:1")

                        st.markdown(
                            f'<div class="{card_class}">'
                            f'<span class="signal-big">{emoji} {h.action}</span><br>'
                            f'<b>{h.headline}</b><br><br>'
                            f'<span class="narrative">{h.narrative}</span>'
                            f'</div>',
                            unsafe_allow_html=True
                        )

                        # ── Paper Trade button ────────────────────────────
                        _pt_col, _pt_info = st.columns([1, 3])
                        with _pt_col:
                            if st.button(f"📌 Paper Trade {h.ticker.replace('.NS','')}", key=f"pt_{h.ticker}"):
                                _pt_price = h.current_price or h.avg_buy_price
                                _pt_qty   = max(1, int(10000 / _pt_price)) if _pt_price > 0 else 1
                                paper_open_trade(
                                    h.ticker, _pt_price, _pt_qty,
                                    sl=h.stop_loss, tp=h.target,
                                    reason=f"{h.action}: {h.headline}"
                                )
                                st.success(f"Paper trade opened: {_pt_qty} × {h.ticker.replace('.NS','')} @ ₹{_pt_price:,.2f} | SL ₹{h.stop_loss:,.2f} | Target ₹{h.target:,.2f}")
                        with _pt_info:
                            st.caption("Paper trades are virtual — no real money. View them in '📂 Paper Trades'.")

                        # ── News for this holding ─────────────────────────
                        with st.expander(f"📰 Latest News — {h.ticker.replace('.NS','')}", expanded=False):
                            try:
                                from utils.news import get_stock_news as _gsn2
                                _h_news = _gsn2(h.ticker, max_articles=4)
                                if _h_news:
                                    for _art in _h_news:
                                        _si = _art["sentiment"]
                                        _ic = "🟢" if _si == "positive" else ("🔴" if _si == "negative" else "⚪")
                                        _bg = "#1a3a2a" if _si == "positive" else ("#3a1a1a" if _si == "negative" else "#1a1a2a")
                                        st.markdown(
                                            f'<div style="background:{_bg};padding:8px 12px;border-radius:6px;margin:4px 0">'
                                            f'{_ic} <b><a href="{_art["link"]}" target="_blank" style="color:#ccc;text-decoration:none">'
                                            f'{_art["title"]}</a></b><br>'
                                            f'<span style="font-size:11px;color:#888">{_art["publisher"]} · {_art["time"]} · <b style="color:{"#26a69a" if _si=="positive" else "#ef5350" if _si=="negative" else "#aaa"}">{_si.upper()}</b></span>'
                                            f'</div>',
                                            unsafe_allow_html=True
                                        )
                                else:
                                    st.caption("No recent news found.")
                            except Exception:
                                st.caption("News unavailable.")

                        if h.error:
                            st.warning(f"⚠️ Data note: {h.error}")

                # ── Best / Worst ───────────────────────────────────────────
                st.markdown("---")
                bw_cols = st.columns(2)
                if summary.best_holding:
                    bh = summary.best_holding
                    with bw_cols[0]:
                        st.markdown(
                            f'<div class="card-green">'
                            f'🏆 <b>Best Performer:</b> {bh.ticker.replace(".NS","")} '
                            f'(+{bh.pnl_pct:.1f}%, ₹+{bh.pnl:,.0f})'
                            f'</div>',
                            unsafe_allow_html=True
                        )
                if summary.worst_holding:
                    wh = summary.worst_holding
                    with bw_cols[1]:
                        sign = "+" if wh.pnl_pct >= 0 else ""
                        st.markdown(
                            f'<div class="card-red">'
                            f'📉 <b>Needs Attention:</b> {wh.ticker.replace(".NS","")} '
                            f'({sign}{wh.pnl_pct:.1f}%, ₹{sign}{wh.pnl:,.0f})'
                            f'</div>',
                            unsafe_allow_html=True
                        )

                # ── Export ─────────────────────────────────────────────────
                st.markdown("---")
                export_path = pm.export_summary_csv(summary)
                export_df = pd.DataFrame([{
                    "Ticker": h.ticker.replace(".NS",""),
                    "Qty": h.quantity,
                    "Buy Price": h.avg_buy_price,
                    "Current": h.current_price,
                    "P&L (₹)": round(h.pnl, 2),
                    "P&L (%)": round(h.pnl_pct, 2),
                    "Score": h.score,
                    "Grade": h.grade,
                    "Action": h.action,
                    "Signal": h.signal.replace("🟢","G").replace("🟡","Y").replace("🔴","R"),
                    "Sector": h.sector,
                } for h in summary.holdings])

                csv_bytes = export_df.to_csv(index=False).encode()
                st.download_button(
                    "📥 Download Full Report CSV",
                    data=csv_bytes,
                    file_name="portfolio_health_report.csv",
                    mime="text/csv",
                )

            except Exception as e:
                st.error(f"Portfolio analysis failed: {e}")
                import traceback
                st.code(traceback.format_exc())
    else:
        # Empty state guidance
        st.markdown("---")
        st.warning(
            "No portfolio.csv found at the default path. "
            "Upload a CSV above to get started.  \n\n"
            "**Required columns:** `ticker, quantity, avg_buy_price, date_bought`  \n"
            "**What you'll see:**  \n"
            "- 🟢 Green = BUY MORE  |  🟡 Yellow = HOLD  |  🔴 Red = Consider Selling  \n"
            "- Composite score (0–100) for each stock — higher is better  \n"
            "- Plain English explanation and suggested stop-loss / target per holding"
        )
        col_ex1, col_ex2, col_ex3 = st.columns(3)
        with col_ex1:
            st.markdown("""
            <div class="card-green">
            <b>🟢 STRONG BUY (Score ≥ 80)</b><br>
            The stock's technicals, momentum, and volume are all aligned.
            Adding to your position here makes sense.
            </div>
            """, unsafe_allow_html=True)
        with col_ex2:
            st.markdown("""
            <div class="card-yellow">
            <b>🟡 HOLD (Score 40–65)</b><br>
            Mixed signals — some positives, some caution.
            Best to hold your current position and monitor.
            </div>
            """, unsafe_allow_html=True)
        with col_ex3:
            st.markdown("""
            <div class="card-red">
            <b>🔴 CAUTION / EXIT (Score &lt; 40)</b><br>
            Technicals are deteriorating.
            Consider reducing position size or setting a tight stop-loss.
            </div>
            """, unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════════════════════
# PAGE 2 — ANALYZE ANY STOCK
# ═══════════════════════════════════════════════════════════════════════════════
elif page == "🔍 Analyze Stock":
    st.title("🔍 Analyze Any NSE Stock")
    st.markdown("Search by company name or ticker — get a full AI score, chart, stop-loss, and plain-English recommendation.")

    # ── Stock search: name autocomplete + manual ticker ────────────────────────
    search_options = [f"{name}  ({sym.replace('.NS','')})"
                      for name, sym in STOCK_SEARCH_MAP.items()]
    search_options_sorted = sorted(search_options)

    col_search, col_manual, col_p, col_btn = st.columns([3, 2, 1, 1])
    with col_search:
        selected_option = st.selectbox(
            "Search by company name or symbol",
            options=["— type to search —"] + search_options_sorted,
            index=0,
            key="stock_search_select",
        )
    with col_manual:
        manual_ticker = st.text_input(
            "Or type ticker directly",
            value="",
            placeholder="e.g. INFY or INFY.NS",
            key="manual_ticker_input",
        ).strip().upper()
    with col_p:
        period = st.selectbox("Period", ["3mo", "6mo", "1y", "2y"], index=2,
                              key="analyze_period")
    with col_btn:
        st.write("")
        st.write("")
        analyze_btn = st.button("🔍 Analyze", type="primary", key="analyze_btn")

    # Resolve final ticker
    ticker = ""
    if manual_ticker:
        ticker = manual_ticker if manual_ticker.endswith(".NS") else manual_ticker + ".NS"
    elif selected_option != "— type to search —":
        # Extract ticker from "Company Name  (TICKER)" format
        raw_sym = selected_option.rsplit("(", 1)[-1].rstrip(")")
        ticker = raw_sym + ".NS" if not raw_sym.endswith(".NS") else raw_sym

    if not ticker:
        ticker = "RELIANCE.NS"

    if analyze_btn or ("last_analyzed" in st.session_state and st.session_state.last_analyzed == ticker):
        st.session_state.last_analyzed = ticker

        with st.spinner(f"Scoring {ticker}…"):
            try:
                cs = get_composite_score(ticker, period=period)
                df = load_ticker_df(ticker, period=period)

                # ── Score hero section ─────────────────────────────────────
                st.markdown("---")
                hero_col, detail_col = st.columns([1, 2])

                with hero_col:
                    grade_c = _grade_color(cs.grade)
                    card_c = _action_color(cs.action)
                    emoji = _action_emoji(cs.action)
                    st.markdown(
                        f'<div class="{card_c}" style="text-align:center;padding:24px">'
                        f'<div class="ticker-label">{ticker.replace(".NS","")}</div>'
                        f'<div style="font-size:14px;color:#aaa">₹{cs.price:,.2f}</div>'
                        f'<div class="score-big" style="color:{grade_c}">{cs.score:.0f}</div>'
                        f'<div style="font-size:13px;color:#aaa">out of 100</div>'
                        f'<div style="font-size:28px;font-weight:700;color:{grade_c};margin:8px 0">'
                        f'Grade: {cs.grade}</div>'
                        f'<div class="signal-big">{emoji} {cs.action}</div>'
                        f'</div>',
                        unsafe_allow_html=True
                    )
                    st.markdown("")
                    # Score breakdown mini-table
                    score_breakdown = {
                        "Technical (40)":  cs.technical_score,
                        "Momentum (25)":   cs.momentum_score,
                        "Volume (15)":     cs.volume_score,
                        "Pattern (10)":    cs.pattern_score,
                        "Sentiment (10)":  cs.sentiment_score,
                    }
                    for label, val in score_breakdown.items():
                        pct = val / {"Technical (40)": 40, "Momentum (25)": 25,
                                     "Volume (15)": 15, "Pattern (10)": 10,
                                     "Sentiment (10)": 10}[label] * 100
                        bar_color = "#26a69a" if pct >= 60 else "#f9a825" if pct >= 35 else "#ef5350"
                        st.markdown(
                            f'<div style="display:flex;align-items:center;margin:3px 0;">'
                            f'<span style="width:160px;font-size:12px;color:#ccc">{label}</span>'
                            f'<div style="flex:1;background:#333;border-radius:4px;height:10px">'
                            f'<div style="width:{pct:.0f}%;background:{bar_color};'
                            f'border-radius:4px;height:10px"></div></div>'
                            f'<span style="width:42px;text-align:right;font-size:12px;color:#ccc">'
                            f'{val:.0f}</span></div>',
                            unsafe_allow_html=True
                        )

                with detail_col:
                    # Trade levels
                    latest = df.iloc[-1]
                    prev   = df.iloc[-2]
                    day_chg = (latest["Close"] / prev["Close"] - 1) * 100

                    mc1, mc2, mc3, mc4 = st.columns(4)
                    mc1.metric("Close",      f"₹{cs.price:,.2f}", f"{day_chg:+.2f}%")
                    mc2.metric("Sector",     cs.sector)
                    mc3.metric("VIX Regime", cs.vix_regime)
                    mc4.metric("Sector Rank",f"#{cs.sector_rank}")

                    tc1, tc2, tc3, tc4 = st.columns(4)
                    tc1.metric("Entry (now)",  f"₹{cs.entry:,.2f}")
                    tc2.metric("Stop-Loss",    f"₹{cs.stop_loss:,.2f}",
                               f"-{(cs.price - cs.stop_loss)/cs.price*100:.1f}%",
                               delta_color="inverse")
                    tc3.metric("Target",       f"₹{cs.target:,.2f}",
                               f"+{(cs.target - cs.price)/cs.price*100:.1f}%")
                    tc4.metric("Risk : Reward",f"{cs.risk_reward:.1f} : 1")

                    # Headline + Narrative
                    st.markdown(
                        f'<div class="{_action_color(cs.action)}">'
                        f'<b style="font-size:16px">{cs.headline}</b><br><br>'
                        f'<span class="narrative">{cs.narrative}</span>'
                        f'</div>',
                        unsafe_allow_html=True
                    )

                # ── Technical indicators ───────────────────────────────────
                st.markdown("---")
                ti_cols = st.columns(6)
                indicators_display = [
                    ("RSI (14)",    f"{latest.get('RSI', 0):.1f}",
                     "Oversold (<30)" if latest.get("RSI", 50) < 30
                     else "Overbought (>70)" if latest.get("RSI", 50) > 70
                     else "Normal"),
                    ("ADX",         f"{latest.get('ADX', 0):.1f}",
                     "Trending (>25)" if latest.get("ADX", 0) > 25 else "Ranging"),
                    ("ATR",         f"₹{latest.get('ATR', 0):.1f}", "Daily move range"),
                    ("Vol Ratio",   f"{latest.get('Volume_Ratio', 0):.2f}x",
                     "High volume" if latest.get("Volume_Ratio", 1) > 1.5 else "Normal"),
                    ("Stoch K",     f"{latest.get('Stoch_K', 50):.1f}",
                     "Oversold" if latest.get("Stoch_K", 50) < 20
                     else "Overbought" if latest.get("Stoch_K", 50) > 80 else ""),
                    ("VWAP %",      f"{latest.get('VWAP_Pct', 0):+.1f}%",
                     "Above VWAP" if latest.get("VWAP_Pct", 0) > 0 else "Below VWAP"),
                ]
                for (label, value, note), col in zip(indicators_display, ti_cols):
                    col.metric(label, value, note)

                # ── Candlestick patterns ───────────────────────────────────
                pat_cols = [c for c in df.columns if c.startswith("Pat_")]
                active_pats = [c.replace("Pat_", "").replace("_", " ")
                               for c in pat_cols if latest.get(c, 0) == 1]
                if active_pats:
                    st.info(f"📍 **Candlestick signals today:** {', '.join(active_pats)}")

                # RSI divergence
                if latest.get("RSI_Bull_Div", 0):
                    st.success("📈 **Bullish RSI Divergence detected** — momentum improving despite lower price")
                if latest.get("RSI_Bear_Div", 0):
                    st.warning("📉 **Bearish RSI Divergence detected** — momentum fading despite higher price")

                # ── Chart ─────────────────────────────────────────────────
                st.markdown("---")
                st.subheader("📊 Price Chart")
                st.plotly_chart(build_price_chart(df, ticker), width="stretch")

                # ── News feed ─────────────────────────────────────────────
                st.markdown("---")
                st.subheader(f"📰 Latest News — {get_display_name(ticker)}")
                with st.spinner("Loading news…"):
                    from utils.news import get_stock_news as _gsn
                    articles = _gsn(ticker, max_articles=6)
                if articles:
                    for art in articles:
                        s = art["sentiment"]
                        icon = "🟢" if s == "positive" else ("🔴" if s == "negative" else "⚪")
                        impact = ("Positive catalyst" if s == "positive"
                                  else "Negative signal" if s == "negative"
                                  else "Neutral update")
                        st.markdown(
                            f'{icon} **[{art["title"]}]({art["link"]})**  \n'
                            f'<span style="font-size:11px;color:#aaa">'
                            f'{art["publisher"]} · {art["time"]} · *{impact}*</span>',
                            unsafe_allow_html=True,
                        )
                else:
                    st.info("No recent news found for this stock.")

                # ── Trading summary box ────────────────────────────────────
                st.markdown("---")
                action_c = _action_color(cs.action)
                atr = float(df["ATR"].iloc[-1]) if "ATR" in df.columns else cs.price * 0.02
                st.markdown(
                    f'<div class="{action_c}" style="padding:16px">'
                    f'<b style="font-size:16px">Trading Plan — {ticker.replace(".NS","")}</b><br><br>'
                    f'<b>Signal:</b> {_action_emoji(cs.action)} {cs.action}&nbsp;&nbsp;'
                    f'<b>Score:</b> {cs.score:.0f}/100 [{cs.grade}]<br>'
                    f'<b>Entry zone:</b> ₹{cs.entry:,.2f} — ₹{cs.entry * 1.01:,.2f}<br>'
                    f'<b>Stop-loss:</b> ₹{cs.stop_loss:,.2f} '
                    f'<span style="color:#aaa;font-size:12px">'
                    f'(~{abs(cs.entry - cs.stop_loss)/cs.entry*100:.1f}% below entry, '
                    f'~1× ATR = ₹{atr:.1f})</span><br>'
                    f'<b>Target:</b> ₹{cs.target:,.2f} '
                    f'<span style="color:#aaa;font-size:12px">'
                    f'(R:R = {cs.risk_reward:.1f}:1)</span><br><br>'
                    f'<i>{cs.headline}</i>'
                    f'</div>',
                    unsafe_allow_html=True,
                )

                # ── Paper Trade This Signal ────────────────────────────────
                st.markdown("---")
                _pbt_col, _pbt_info = st.columns([1, 3])
                with _pbt_col:
                    if st.button(f"📌 Paper Trade This Signal", type="primary", key="analyze_pt_btn"):
                        _pt_qty = max(1, int(10000 / cs.entry)) if cs.entry > 0 else 1
                        _new_trade_id = paper_open_trade(
                            ticker, cs.entry, _pt_qty,
                            sl=cs.stop_loss, tp=cs.target,
                            reason=f"{cs.action} score={cs.score:.0f}: {cs.headline}"
                        )
                        st.success(
                            f"✅ Paper trade #{_new_trade_id} opened:  "
                            f"**{_pt_qty} × {ticker.replace('.NS','')}** @ ₹{cs.entry:,.2f}  "
                            f"| SL ₹{cs.stop_loss:,.2f} | Target ₹{cs.target:,.2f}  "
                            f"| Potential gain ₹{(cs.target - cs.entry)*_pt_qty:,.0f}"
                        )
                with _pbt_info:
                    st.info(
                        "📌 **Paper Trading** lets you test this signal without real money. "
                        "Track it in the **📂 Paper Trades** page to see if the model's calls are accurate."
                    )

            except Exception as e:
                st.error(f"Analysis failed: {e}")
                import traceback
                st.code(traceback.format_exc())


# ═══════════════════════════════════════════════════════════════════════════════
# PAGE 3 — MARKET OVERVIEW
# ═══════════════════════════════════════════════════════════════════════════════
elif page == "📊 Market Overview":
    st.title("📊 Market Overview")
    st.caption("Live market snapshot — VIX, sector momentum, and top movers")

    if st.button("🔄 Refresh Data", type="primary"):
        st.cache_data.clear()

    # ── India VIX section ──────────────────────────────────────────────────
    with st.spinner("Loading VIX & Nifty…"):
        try:
            vix_df, nifty_df = load_vix_data()
            curr_vix   = float(vix_df["Close"].iloc[-1])
            prev_vix   = float(vix_df["Close"].iloc[-2])
            vix_chg    = (curr_vix / prev_vix - 1) * 100
            vix_52w_hi = float(vix_df["High"].max())
            vix_52w_lo = float(vix_df["Low"].min())
            vix_rank   = (curr_vix - vix_52w_lo) / max(vix_52w_hi - vix_52w_lo, 0.01) * 100
            curr_nifty = float(nifty_df["Close"].iloc[-1])
            nifty_chg  = float(nifty_df["Close"].pct_change().iloc[-1]) * 100

            if curr_vix < 12:    regime, reg_color = "Extreme Complacency", "#FF6B35"
            elif curr_vix < 16:  regime, reg_color = "Low Volatility",       "#4ECDC4"
            elif curr_vix < 22:  regime, reg_color = "Normal",                "#45B7D1"
            elif curr_vix < 28:  regime, reg_color = "Elevated Fear",         "#F7DC6F"
            elif curr_vix < 35:  regime, reg_color = "High Fear",             "#E74C3C"
            else:                regime, reg_color = "PANIC / Crisis",         "#8E44AD"

            if curr_vix < 15:   opt_str = "BUY options (cheap premium)"
            elif curr_vix < 22: opt_str = "SPREADS (balanced IV)"
            elif curr_vix < 28: opt_str = "SELL premium with spreads"
            else:               opt_str = "SELL wide spreads / long if conviction"

            # Divergence
            if nifty_chg > 0 and vix_chg > 0:
                div_txt = "⚠️ Warning: Nifty ↑ + VIX ↑ — fragile rally"
            elif nifty_chg < 0 and vix_chg < 0:
                div_txt = "🟢 Nifty ↓ + VIX ↓ — oversold bounce watch"
            elif nifty_chg > 0 and vix_chg < 0:
                div_txt = "✅ Healthy rally — fear leaving market"
            else:
                div_txt = "✅ Normal correction — fear rising with selling"

            st.subheader("🌡️ Fear Gauge — India VIX")
            st.markdown(
                f'<div style="background:{reg_color};padding:12px 18px;border-radius:10px;'
                f'color:#000;font-weight:700;font-size:18px;text-align:center;">'
                f'VIX {curr_vix:.2f}  ({vix_chg:+.1f}% today)  —  {regime}  |  '
                f'Options regime: {opt_str}'
                f'</div>',
                unsafe_allow_html=True
            )
            st.markdown(f"**Divergence signal:** {div_txt}")

            v_col1, v_col2, v_col3, v_col4 = st.columns(4)
            v_col1.metric("India VIX",    f"{curr_vix:.2f}", f"{vix_chg:+.1f}%")
            v_col2.metric("VIX Rank",     f"{vix_rank:.0f}%  (52w)")
            v_col3.metric("Nifty 50",     f"{curr_nifty:,.0f}", f"{nifty_chg:+.2f}%")
            v_col4.metric("52w VIX Range",f"{vix_52w_lo:.1f} – {vix_52w_hi:.1f}")

            fig_vix = go.Figure()
            fig_vix.add_trace(go.Scatter(
                x=vix_df.index, y=vix_df["Close"],
                name="India VIX", line=dict(color="#FF6B6B", width=2),
                fill="tozeroy", fillcolor="rgba(255,107,107,0.1)",
            ))
            for lo, hi, clr, lbl in [
                (0, 12, "rgba(76,175,80,.12)", "Safe"),
                (12, 22, "rgba(255,193,7,.12)", "Normal"),
                (22, 28, "rgba(255,87,34,.12)", "Caution"),
                (28, 100, "rgba(156,39,176,.12)", "Fear"),
            ]:
                fig_vix.add_hrect(y0=lo, y1=hi, fillcolor=clr,
                                  annotation_text=lbl, annotation_position="left",
                                  line_width=0)
            fig_vix.update_layout(
                title="India VIX — 1 Year",
                template="plotly_dark", height=300,
                xaxis_rangeslider_visible=False,
                margin=dict(l=0, r=0, t=40, b=0),
            )
            st.plotly_chart(fig_vix, width="stretch")

        except Exception as e:
            st.warning(f"VIX load error: {e}")

    # ── Sector Rotation ────────────────────────────────────────────────────
    st.markdown("---")
    st.subheader("🔄 Sector Momentum Heatmap")

    @st.cache_data(ttl=1800)
    def get_sector_data():
        from strategies.sector_rotation import compute_sector_scores
        return compute_sector_scores(period="1y")

    with st.spinner("Computing sector scores…"):
        try:
            scores = get_sector_data()
            if not scores.empty:
                s_col1, s_col2 = st.columns([1, 1])
                with s_col1:
                    disp = scores[["mom_20d", "mom_60d", "composite_score", "Rank"]].copy()
                    disp.columns = ["20d (%)", "60d (%)", "Score", "Rank"]
                    st.dataframe(
                        disp.style
                        .background_gradient(subset=["Score"], cmap="RdYlGn")
                        .format("{:.2f}"),
                        width="stretch",
                    )
                with s_col2:
                    fig_bar = px.bar(
                        scores.reset_index(), x="Sector", y="composite_score",
                        color="composite_score", color_continuous_scale="RdYlGn",
                        title="Sector Scores",
                        labels={"composite_score": "Score (%)"},
                    )
                    fig_bar.update_layout(
                        template="plotly_dark", height=340, showlegend=False,
                        margin=dict(l=0, r=0, t=40, b=0),
                    )
                    st.plotly_chart(fig_bar, width="stretch")
        except Exception as e:
            st.warning(f"Sector scores error: {e}")

    # ── Top movers from NIFTY50 ────────────────────────────────────────────
    st.markdown("---")
    st.subheader("🚀 NIFTY50 Top Movers")

    @st.cache_data(ttl=600)
    def get_top_movers():
        import yfinance as yf
        from data.fetcher import NIFTY50_TICKERS
        rows = []
        for t in NIFTY50_TICKERS[:50]:
            try:
                d = yf.download(t, period="5d", interval="1d",
                                auto_adjust=True, progress=False)
                if isinstance(d.columns, pd.MultiIndex):
                    d.columns = d.columns.get_level_values(0)
                if len(d) < 2:
                    continue
                close = float(d["Close"].iloc[-1])
                prev  = float(d["Close"].iloc[-2])
                chg   = (close / prev - 1) * 100
                w_chg = (close / float(d["Close"].iloc[0]) - 1) * 100
                vol_r = float(d["Volume"].iloc[-1]) / max(float(d["Volume"].mean()), 1)
                rows.append({
                    "Ticker": t.replace(".NS", ""),
                    "Price": round(close, 2),
                    "Day (%)": round(chg, 2),
                    "5d (%)": round(w_chg, 2),
                    "Vol Ratio": round(vol_r, 2),
                })
            except Exception:
                continue
        return pd.DataFrame(rows).sort_values("Day (%)", ascending=False) if rows else pd.DataFrame()

    with st.spinner("Fetching NIFTY50 movers…"):
        movers = get_top_movers()
        if not movers.empty:
            top5 = movers.head(5)
            bot5 = movers.tail(5)
            m1, m2 = st.columns(2)
            with m1:
                st.markdown("**📈 Top Gainers Today**")
                for _, row in top5.iterrows():
                    st.markdown(
                        f'<div class="card-green" style="padding:8px 14px">'
                        f'<b>{row["Ticker"]}</b>  ₹{row["Price"]:,.2f}  '
                        f'<span style="color:#26a69a">+{row["Day (%)"]:,.2f}%</span>'
                        f'</div>',
                        unsafe_allow_html=True
                    )
            with m2:
                st.markdown("**📉 Top Losers Today**")
                for _, row in bot5.iterrows():
                    st.markdown(
                        f'<div class="card-red" style="padding:8px 14px">'
                        f'<b>{row["Ticker"]}</b>  ₹{row["Price"]:,.2f}  '
                        f'<span style="color:#ef5350">{row["Day (%)"]:,.2f}%</span>'
                        f'</div>',
                        unsafe_allow_html=True
                    )


# ═══════════════════════════════════════════════════════════════════════════════
# PAGE 4 — SMART SCREENER
# ═══════════════════════════════════════════════════════════════════════════════
elif page == "🔎 Smart Screener":
    st.title("🔎 Smart Stock Screener")
    st.markdown(
        "Scan the NSE universe using 4 proven screens — oversold bounce, "
        "momentum leaders, breakouts, and pullback entries.  \n"
        "Each match is enriched with a composite score."
    )

    sc1, sc2, sc3 = st.columns(3)
    with sc1:
        universe_choice = st.selectbox(
            "Universe",
            ["NIFTY 50 (50 stocks)", "NIFTY 100 (100 stocks)",
             "NIFTY 200 (200 stocks)", "NIFTY 500 (~400 stocks)"],
        )
        universe_map = {
            "NIFTY 50 (50 stocks)":    "nifty50",
            "NIFTY 100 (100 stocks)":  "nifty100",
            "NIFTY 200 (200 stocks)":  "nifty200",
            "NIFTY 500 (~400 stocks)": "nifty500",
        }
        universe_key = universe_map[universe_choice]
    with sc2:
        screen_choice = st.selectbox(
            "Screen type",
            ["All 4 screens", "Oversold Bounce", "Momentum Leaders",
             "Breakouts", "Pullback to SMA"],
        )
        screen_map = {
            "All 4 screens": "all",
            "Oversold Bounce": "oversold",
            "Momentum Leaders": "momentum",
            "Breakouts": "breakout",
            "Pullback to SMA": "pullback_SMA20",
        }
        screen_key = screen_map[screen_choice]
    with sc3:
        enrich_scores = st.checkbox("Enrich with composite score", value=True,
                                    help="Adds 0-100 score to each result (slower)")

    scan_btn = st.button("🔍 Run Screen", type="primary")

    if scan_btn:
        from data.universe import get_universe
        from trading.signals import scan_tickers
        universe = get_universe(universe_key)

        with st.spinner(f"Scanning {len(universe)} stocks… this may take a few minutes…"):
            signals = scan_tickers(universe, strategy=screen_key, period="1y")

        if not signals:
            st.info("No signals found for the current screen. Try a broader universe or different screen.")
        else:
            st.success(f"✅ Found **{len(signals)} setups** across {len(universe)} stocks!")
            vix_info = get_vix_info()

            if enrich_scores:
                from analysis.score import score_stock
                scored_signals = []
                prog = st.progress(0)
                for i, sig in enumerate(signals):
                    try:
                        cs = score_stock(sig["ticker"], period="1y", vix_info=vix_info)
                        sig["composite_score"] = round(cs.score, 1)
                        sig["grade"]           = cs.grade
                        sig["action"]          = cs.action
                        sig["narrative"]       = cs.headline
                        sig["stop_loss"]       = round(cs.stop_loss, 2)
                        sig["target"]          = round(cs.target, 2)
                    except Exception:
                        sig["composite_score"] = 50
                        sig["grade"]           = "C"
                        sig["action"]          = sig.get("action", "WATCHLIST")
                        sig["narrative"]       = "—"
                    scored_signals.append(sig)
                    prog.progress((i + 1) / len(signals))
                signals = sorted(scored_signals, key=lambda x: x.get("composite_score", 0), reverse=True)

            # Display results as cards
            for sig in signals[:30]:  # cap at 30 for performance
                t = sig["ticker"].replace(".NS", "")
                action = sig.get("action", "WATCHLIST")
                card = _action_color(action)
                emoji = _action_emoji(action)
                score_str = (f"Score: {sig.get('composite_score','?')}/100 [{sig.get('grade','?')}]"
                             if enrich_scores else "")
                with st.expander(
                    f"{emoji} {t}  |  ₹{sig.get('price', 0):,.2f}  "
                    f"|  {sig.get('screen',''):<25}  |  {score_str}",
                    expanded=False
                ):
                    d1, d2, d3, d4 = st.columns(4)
                    d1.metric("Price",  f"₹{sig.get('price', 0):,.2f}")
                    d2.metric("Stop",   f"₹{sig.get('sl', sig.get('stop_loss', 0)):,.2f}")
                    d3.metric("Target", f"₹{sig.get('tp', sig.get('target', 0)):,.2f}" if sig.get('tp') else "Trail")
                    d4.metric("Screen", sig.get("screen", ""))
                    if enrich_scores and sig.get("narrative"):
                        st.markdown(
                            f'<div class="{card}" style="padding:10px 14px">'
                            f'<b>{sig.get("narrative","")}</b></div>',
                            unsafe_allow_html=True
                        )

            # Download results
            result_df = pd.DataFrame(signals)
            if not result_df.empty:
                st.download_button(
                    "📥 Download Watchlist CSV",
                    data=result_df.to_csv(index=False).encode(),
                    file_name="nse_watchlist.csv",
                    mime="text/csv",
                )


# ═══════════════════════════════════════════════════════════════════════════════
# PAGE 5 — PAPER TRADES  (full UI — enter, track, close, analyse)
# ═══════════════════════════════════════════════════════════════════════════════
elif page == "📂 Paper Trades":
    st.title("📂 Paper Trading Simulator")
    st.markdown(
        "Practice trading **without real money**. Open virtual trades, track live P&L, "
        "and measure your decision quality over time. All prices are from live market data."
    )

    _ensure_paper_db()

    # ── LIVE PRICE + ATR SUGGESTIONS (cached 60 s per ticker) ─────────────────
    @st.cache_data(ttl=60, show_spinner=False)
    def _paper_trade_suggestions(ticker: str) -> dict:
        """
        Live price (Yahoo JSON API) + ATR-based SL/TP + RSI + trend.
        All data sources are cloud-safe (no yfinance rate limits).
        Returns dict: price, prev, chg, atr, sl, tp, rsi, trend, qty_suggest, error
        """
        import pandas as _pd2
        from utils.live_price import get_live_quote
        from data.fetcher import fetch_single

        result = {"price": None, "prev": None, "chg": 0.0,
                  "atr": None, "sl": None, "tp": None,
                  "rsi": None, "trend": "—", "qty_suggest": 1, "error": ""}
        try:
            # ── Live price via Yahoo JSON API / NSE / Stooq ────────────────
            q = get_live_quote(ticker)
            if not q or not q.get("price"):
                result["error"] = "Price unavailable — all sources failed. Try again in 30 s."
                return result

            price = q["price"]
            prev  = q["prev_close"]
            chg   = q["chg_pct"]
            result.update({"price": price, "prev": prev, "chg": chg})

            # ── Historical data for ATR + RSI + trend via Stooq ───────────
            df = fetch_single(ticker, period="3mo")
            df = df.dropna(subset=["Close"])
            if len(df) < 15:
                # Fallback: simple % stops
                result["sl"] = round(price * 0.97, 2)   # 3% stop
                result["tp"] = round(price * 1.06, 2)   # 6% target → 2:1
                result["qty_suggest"] = max(1, int(10000 / price))
                return result

            # ATR (14)
            hi, lo, cl = df["High"], df["Low"], df["Close"]
            tr  = _pd2.concat([hi - lo,
                                (hi - cl.shift()).abs(),
                                (lo - cl.shift()).abs()], axis=1).max(axis=1)
            atr = float(tr.rolling(14).mean().dropna().iloc[-1])
            result["atr"] = atr

            # Stop = 1.5 × ATR below live price  →  tight but realistic
            # Target = 3.0 × ATR above live price  →  exactly 2:1 R:R
            sl_calc = round(price - 1.5 * atr, 2)
            tp_calc = round(price + 3.0 * atr, 2)
            result["sl"] = max(0.01, sl_calc)
            result["tp"] = tp_calc

            # RSI (14)
            delta = cl.diff()
            gain  = delta.clip(lower=0).rolling(14).mean()
            loss  = (-delta.clip(upper=0)).rolling(14).mean()
            rsi   = float((100 - 100 / (1 + gain / loss)).dropna().iloc[-1])
            result["rsi"] = rsi

            # Simple trend signal
            sma50  = float(cl.rolling(50).mean().iloc[-1]) if len(df) >= 50 else price
            sma200 = float(cl.rolling(200).mean().iloc[-1]) if len(df) >= 200 else price
            if price > sma50 > sma200:
                result["trend"] = "🟢 Uptrend (above SMA50 & SMA200)"
            elif price > sma50:
                result["trend"] = "🟡 Moderate (above SMA50)"
            elif price < sma50 < sma200:
                result["trend"] = "🔴 Downtrend (below SMA50 & SMA200)"
            else:
                result["trend"] = "🟡 Mixed — check chart"

            # Suggested qty: ~₹10,000 position (small safe default)
            result["qty_suggest"] = max(1, int(10000 / price))

        except Exception as _exc:
            result["error"] = str(_exc)
        return result

    # ── NEW TRADE FORM ─────────────────────────────────────────────────────────
    with st.expander("➕ Open a New Paper Trade", expanded=True):
        st.markdown(
            "**Select a stock** — the entry price, stop-loss, and target are auto-filled "
            "from live market data and ATR analysis. You can adjust them freely before submitting."
        )
        _search_opts = sorted([f"{n}  ({s.replace('.NS','')})" for n, s in STOCK_SEARCH_MAP.items()])
        _fc1, _fc2 = st.columns([3, 2])
        with _fc1:
            _form_sel = st.selectbox("Search by company name", ["— choose stock —"] + _search_opts, key="pt_stock_sel")
        with _fc2:
            _form_manual = st.text_input("Or type NSE ticker directly", key="pt_manual_tk",
                                         placeholder="e.g. INFY").strip().upper()

        # Resolve ticker
        _form_ticker = ""
        if _form_manual:
            _form_ticker = _form_manual if _form_manual.endswith(".NS") else _form_manual + ".NS"
        elif _form_sel != "— choose stock —":
            _raw = _form_sel.rsplit("(", 1)[-1].rstrip(")")
            _form_ticker = _raw + ".NS" if not _raw.endswith(".NS") else _raw

        # ── Fetch live data & suggestions ─────────────────────────────────
        _sugg = {"price": None, "sl": None, "tp": None, "qty_suggest": 10,
                 "atr": None, "rsi": None, "trend": "—", "chg": 0.0, "error": ""}
        if _form_ticker:
            with st.spinner(f"Fetching live price & ATR for {_form_ticker.replace('.NS','')}…"):
                _sugg = _paper_trade_suggestions(_form_ticker)

        # ── Suggestion banner ──────────────────────────────────────────────
        if _form_ticker and _sugg["price"]:
            _p    = _sugg["price"]
            _atr  = _sugg["atr"]
            _rsi  = _sugg["rsi"]
            _atr_str = f"₹{_atr:.2f}" if _atr else "—"
            _rsi_str = f"{_rsi:.0f}" if _rsi else "—"
            _rsi_label = (
                "🔴 Overbought — watch for pullback" if (_rsi and _rsi > 70)
                else "🟢 Oversold — bounce candidate"  if (_rsi and _rsi < 30)
                else "🟡 Neutral momentum"              if _rsi
                else ""
            )
            st.markdown(
                f'<div style="background:#0d1f3c;padding:12px 18px;border-radius:10px;'
                f'border-left:5px solid #2196F3;margin:8px 0">'
                f'<b style="font-size:18px">₹{_p:,.2f}</b>'
                f'<span style="color:{"#26a69a" if _sugg["chg"]>=0 else "#ef5350"};margin-left:10px">'
                f'{"▲" if _sugg["chg"]>=0 else "▼"} {abs(_sugg["chg"]):.2f}% today</span>'
                f'<br><span style="font-size:12px;color:#aaa">'
                f'ATR(14): {_atr_str} &nbsp;|&nbsp; RSI: {_rsi_str} {_rsi_label}'
                f' &nbsp;|&nbsp; Trend: {_sugg["trend"]}</span>'
                f'</div>',
                unsafe_allow_html=True
            )
        elif _form_ticker and _sugg["error"]:
            st.warning(f"⚠️ {_sugg['error']}")

        # ── Input fields — defaults from live data, keyed by ticker so they
        #    reset automatically when the user picks a different stock ────────
        _tk_key = _form_ticker or "none"      # key suffix changes → fresh widget defaults
        _def_price = _sugg["price"]  or 100.0
        _def_sl    = _sugg["sl"]     or round(_def_price * 0.97, 2)
        _def_tp    = _sugg["tp"]     or round(_def_price * 1.06, 2)
        _def_qty   = _sugg["qty_suggest"] or 10

        _pa, _pb, _pc, _pd = st.columns(4)
        _form_qty   = _pa.number_input(
            "Quantity (shares)", 1, 1000000, _def_qty,
            key=f"pt_qty_{_tk_key}"
        )
        _form_price = _pb.number_input(
            "Entry Price (₹) — live", 0.01, 1e7, float(_def_price),
            key=f"pt_price_{_tk_key}", format="%.2f"
        )
        _form_sl    = _pc.number_input(
            "Stop-Loss (₹) — ATR-based", 0.01, 1e7, float(_def_sl),
            key=f"pt_sl_{_tk_key}", format="%.2f",
            help="Default = 1.5× ATR below live price. Adjust to your preferred risk level."
        )
        _form_tp    = _pd.number_input(
            "Target (₹) — 2:1 R:R", 0.01, 1e7, float(_def_tp),
            key=f"pt_tp_{_tk_key}", format="%.2f",
            help="Default = 3× ATR above live price (gives 2:1 Risk:Reward). Adjust as needed."
        )

        # ── Live Risk:Reward summary ───────────────────────────────────────
        if _form_price > 0 and _form_sl < _form_price and _form_tp > _form_price:
            _risk_ps  = _form_price - _form_sl
            _rew_ps   = _form_tp    - _form_price
            _rr_ratio = _rew_ps / _risk_ps if _risk_ps > 0 else 0
            _cap_risk = _risk_ps * _form_qty
            _cap_rew  = _rew_ps  * _form_qty
            _rr_color = "#26a69a" if _rr_ratio >= 1.5 else "#f9a825" if _rr_ratio >= 1.0 else "#ef5350"
            st.markdown(
                f'<div style="background:#1a1a2a;padding:10px 16px;border-radius:8px;margin:8px 0">'
                f'Risk/share: <b style="color:#ef5350">₹{_risk_ps:.2f}</b> &nbsp;|&nbsp; '
                f'Reward/share: <b style="color:#26a69a">₹{_rew_ps:.2f}</b> &nbsp;|&nbsp; '
                f'<span style="color:{_rr_color}"><b>R:R = {_rr_ratio:.1f}:1</b></span> &nbsp;|&nbsp; '
                f'Max loss on trade: <b style="color:#ef5350">₹{_cap_risk:,.0f}</b> &nbsp;|&nbsp; '
                f'Max gain on trade: <b style="color:#26a69a">₹{_cap_rew:,.0f}</b>'
                f'</div>',
                unsafe_allow_html=True
            )
            if _rr_ratio < 1.0:
                st.error("⛔ R:R below 1:1 — you risk more than you can gain. Adjust your stop or target.")
            elif _rr_ratio < 1.5:
                st.warning("⚠️ R:R below 1.5:1 — minimum recommended is 1.5:1 for a consistent edge.")
            else:
                st.success(f"✅ Good R:R ({_rr_ratio:.1f}:1) — trade setup meets the minimum quality bar.")

        _form_reason = st.text_input(
            "Reason / notes (optional)", key="pt_reason",
            placeholder="e.g. RSI oversold bounce at SMA50 support — score 72"
        )

        if st.button("🟢 Open Paper Trade", type="primary", key="pt_submit"):
            if not _form_ticker:
                st.error("Please select a stock first.")
            elif _form_sl >= _form_price:
                st.error("Stop-loss must be BELOW entry price.")
            elif _form_tp <= _form_price:
                st.error("Target must be ABOVE entry price.")
            else:
                _new_id = paper_open_trade(
                    _form_ticker, _form_price, int(_form_qty),
                    sl=_form_sl, tp=_form_tp, reason=_form_reason
                )
                st.success(
                    f"✅ Paper trade #{_new_id} opened: **{int(_form_qty)} × "
                    f"{_form_ticker.replace('.NS','')}** @ ₹{_form_price:,.2f}  "
                    f"| SL ₹{_form_sl:,.2f} | Target ₹{_form_tp:,.2f}"
                )
                st.cache_data.clear()

    st.markdown("---")

    # ── LOAD ALL TRADES ────────────────────────────────────────────────────────
    _hcol, _rcol = st.columns([5, 1])
    with _rcol:
        if st.button("🔄 Refresh", key="paper_refresh"):
            st.cache_data.clear()

    trades = load_trades_db()

    if trades.empty:
        st.info("No paper trades yet. Open your first trade using the form above.")
    else:
        open_t     = trades[trades["status"] == "OPEN"]    if "status" in trades.columns else pd.DataFrame()
        closed_t   = trades[trades["status"] == "CLOSED"]  if "status" in trades.columns else pd.DataFrame()
        stopped_t  = trades[trades["status"] == "STOPPED"] if "status" in trades.columns else pd.DataFrame()
        all_closed = pd.concat([closed_t, stopped_t], ignore_index=True)

        # ── Summary metrics ────────────────────────────────────────────────
        _sm1, _sm2, _sm3, _sm4 = st.columns(4)
        _sm1.metric("Total Trades", len(trades))
        _sm2.metric("Open Positions", len(open_t))
        _sm3.metric("Closed", len(all_closed))
        if not all_closed.empty and "pnl" in all_closed.columns:
            _all_cl_pnl = pd.to_numeric(all_closed["pnl"], errors="coerce")
            _tot_pnl  = _all_cl_pnl.sum()
            _wins_cnt = (_all_cl_pnl > 0).sum()
            _sm4.metric("Realised P&L",
                        f"₹{_tot_pnl:+,.0f}",
                        f"{_wins_cnt}/{len(all_closed)} winners",
                        delta_color="normal" if _tot_pnl >= 0 else "inverse")
        st.markdown("---")

        # ── OPEN POSITIONS with live P&L + Exit button ─────────────────────
        if not open_t.empty:
            st.subheader("📌 Open Positions — Live P&L")

            # Fetch live prices for all open tickers
            _open_syms = tuple(open_t["ticker"].tolist())
            _open_lp   = _portfolio_live_prices(_open_syms)

            for _, _row in open_t.iterrows():
                _tk   = _row["ticker"]
                _ep   = float(_row["price"])
                _qty  = int(_row["quantity"])
                _sl   = float(_row["sl"]) if _row.get("sl") else None
                _tp   = float(_row["tp"]) if _row.get("tp") else None
                _tstp = _row.get("timestamp", "")
                _lp   = _open_lp.get(_tk, {})
                _cur  = _lp.get("price", _ep)
                _unr  = (_cur - _ep) * _qty
                _unr_pct = (_cur / _ep - 1) * 100 if _ep > 0 else 0
                _rr_calc = ""
                if _sl and _tp and _sl < _ep and _tp > _ep:
                    _risk = _ep - _sl
                    _rew  = _tp - _ep
                    _rr_calc = f"  |  R:R {_rew/_risk:.1f}:1"

                # Status badge
                _sl_warn = _sl and _cur <= _sl
                _tp_hit  = _tp and _cur >= _tp
                _stat_badge = ""
                if _tp_hit:
                    _stat_badge = "🎯 TARGET HIT — consider closing"
                elif _sl_warn:
                    _stat_badge = "🚨 STOP-LOSS BREACHED — consider closing"
                elif _unr >= 0:
                    _stat_badge = "🟢 In Profit"
                else:
                    _stat_badge = "🔴 In Loss"

                _pos_color = "card-green" if _unr >= 0 else "card-red"
                with st.expander(
                    f"{'🟢' if _unr >= 0 else '🔴'} {_tk.replace('.NS','')}  "
                    f"| Unrealised: ₹{_unr:+,.0f} ({_unr_pct:+.2f}%){_rr_calc}",
                    expanded=True,
                ):
                    _oc1, _oc2, _oc3, _oc4, _oc5 = st.columns(5)
                    _oc1.metric("Entry",    f"₹{_ep:,.2f}")
                    _oc2.metric("Live",     f"₹{_cur:,.2f}",  f"{_lp.get('chg',0):+.2f}% today")
                    _oc3.metric("Qty",      f"{_qty} shares")
                    _oc4.metric("Stop-Loss",f"₹{_sl:,.2f}" if _sl else "—",
                                delta=f"{(_sl/_ep-1)*100:+.1f}%" if _sl else None,
                                delta_color="inverse")
                    _oc5.metric("Target",   f"₹{_tp:,.2f}" if _tp else "—",
                                delta=f"{(_tp/_ep-1)*100:+.1f}%" if _tp else None)

                    st.markdown(
                        f'<div class="{_pos_color}" style="padding:8px 14px;margin:4px 0">'
                        f'{_stat_badge}'
                        f'</div>',
                        unsafe_allow_html=True
                    )

                    _reason_txt = str(_row.get("reason") or "")
                    if _reason_txt:
                        st.caption(f"📝 {_reason_txt}")

                    # Close buttons
                    _cl1, _cl2, _cl3 = st.columns(3)
                    _tid = int(_row["id"])
                    if _cl1.button(f"❌ Close @ Live (₹{_cur:,.2f})", key=f"close_live_{_tid}"):
                        paper_close_trade(_tid, _cur, "Closed at live price")
                        st.success(f"Closed {_tk.replace('.NS','')} @ ₹{_cur:,.2f} | P&L ₹{_unr:+,.0f}")
                        st.cache_data.clear()
                        st.rerun()
                    if _sl and _cl2.button(f"🔴 Close @ Stop (₹{_sl:,.2f})", key=f"close_sl_{_tid}"):
                        _sl_pnl = (_sl - _ep) * _qty
                        paper_close_trade(_tid, _sl, "Stop-loss triggered")
                        st.warning(f"Stop triggered on {_tk.replace('.NS','')} @ ₹{_sl:,.2f} | Loss ₹{_sl_pnl:,.0f}")
                        st.cache_data.clear()
                        st.rerun()
                    if _tp and _cl3.button(f"🎯 Close @ Target (₹{_tp:,.2f})", key=f"close_tp_{_tid}"):
                        _tp_pnl = (_tp - _ep) * _qty
                        paper_close_trade(_tid, _tp, "Target reached")
                        st.success(f"Target hit on {_tk.replace('.NS','')} @ ₹{_tp:,.2f} | Profit ₹{_tp_pnl:,.0f}")
                        st.cache_data.clear()
                        st.rerun()

            st.markdown("---")

        # ── CLOSED TRADE HISTORY ───────────────────────────────────────────
        if not all_closed.empty:
            st.subheader("📋 Closed Trade History")
            _cl_disp = all_closed[
                [c for c in ["id","ticker","price","quantity","sl","tp","exit_price",
                              "exit_reason","pnl","pnl_pct","status","timestamp"]
                 if c in all_closed.columns]
            ].copy()
            if "pnl" in _cl_disp.columns:
                _cl_disp["pnl"] = pd.to_numeric(_cl_disp["pnl"], errors="coerce")
            st.dataframe(_cl_disp, hide_index=True, width="stretch")

            # P&L Bar Chart
            _pnl_plot = all_closed.copy()
            _pnl_plot["pnl"] = pd.to_numeric(_pnl_plot["pnl"], errors="coerce")
            _pnl_plot = _pnl_plot.dropna(subset=["pnl"])
            if not _pnl_plot.empty:
                _fig_pnl = px.bar(
                    _pnl_plot, x="ticker", y="pnl",
                    color="pnl", color_continuous_scale="RdYlGn",
                    title="Realised P&L per Closed Trade (₹)",
                    labels={"pnl": "P&L (₹)", "ticker": "Stock"},
                )
                _fig_pnl.update_layout(template="plotly_dark", height=320,
                                       margin=dict(l=0, r=0, t=40, b=0))
                st.plotly_chart(_fig_pnl, width="stretch")

            # ── Performance Stats ──────────────────────────────────────────
            with st.expander("📈 Performance Statistics", expanded=False):
                _pnl_s = pd.to_numeric(all_closed["pnl"], errors="coerce").dropna()
                _n     = len(_pnl_s)
                _wins  = _pnl_s[_pnl_s > 0]
                _loss  = _pnl_s[_pnl_s < 0]
                _wr    = len(_wins) / _n * 100 if _n else 0
                _aw    = float(_wins.mean()) if not _wins.empty else 0.0
                _al    = float(_loss.mean()) if not _loss.empty else 0.0
                _pay   = abs(_aw / _al) if _al != 0 else 0
                _exp   = (_wr/100 * _aw) + ((1-_wr/100) * _al) if _n else 0

                _st1, _st2, _st3, _st4, _st5 = st.columns(5)
                _st1.metric("Win Rate",      f"{_wr:.1f}%",
                            "Good (>50%)" if _wr > 50 else "Needs work")
                _st2.metric("Avg Win",       f"₹{_aw:,.0f}")
                _st3.metric("Avg Loss",      f"₹{_al:,.0f}")
                _st4.metric("Payoff Ratio",  f"{_pay:.2f}:1",
                            "Good (>1.5)" if _pay > 1.5 else "Needs work")
                _st5.metric("Expectancy",    f"₹{_exp:,.0f}/trade",
                            "Positive edge ✓" if _exp > 0 else "Negative edge ✗",
                            delta_color="normal" if _exp >= 0 else "inverse")

                st.markdown("---")
                st.markdown(
                    "**What these numbers mean:**  \n"
                    "- **Win Rate**: % of trades that closed profitably. Aim for >45%.  \n"
                    "- **Payoff Ratio**: Avg profit on winners ÷ avg loss on losers. Aim for >1.5  \n"
                    "- **Expectancy**: Average ₹ earned per trade across all trades. Must be positive for a viable strategy."
                )

        # ── CSV export ─────────────────────────────────────────────────────
        st.markdown("---")
        if not trades.empty:
            _export_bytes = trades.to_csv(index=False).encode()
            st.download_button(
                "📥 Download Full Trade Journal (CSV)",
                data=_export_bytes,
                file_name="paper_trade_journal.csv",
                mime="text/csv",
            )


# ═══════════════════════════════════════════════════════════════════════════════
# PAGE 6 — BACKTEST
# ═══════════════════════════════════════════════════════════════════════════════
elif page == "🧪 Backtest":
    st.title("🧪 Backtest Results")
    st.caption("Historical strategy performance — how would these signals have done in the past?")

    def load_backtest_csv(path: str = "portfolio_results.csv") -> pd.DataFrame:
        if os.path.exists(path):
            return pd.read_csv(path, index_col=0)
        return pd.DataFrame()

    df = load_backtest_csv()

    if df.empty:
        st.info(
            "No backtest results found.  \n\n"
            "Run:  `python main.py --mode backtest --portfolio --index nifty50`  \n"
            "Results will appear here automatically."
        )
    else:
        r_col = next((c for c in ["Return (%)", "Return(%)"] if c in df.columns), None)
        s_col = next((c for c in ["Sharpe", "Sharpe Ratio"] if c in df.columns), None)
        t_col = next((c for c in ["# Trades", "Trades"] if c in df.columns), None)

        bt1, bt2, bt3, bt4 = st.columns(4)
        bt1.metric("Tickers Tested", len(df))
        bt2.metric("Avg Return",   f"{df[r_col].mean():.2f}%" if r_col else "—")
        bt3.metric("Avg Sharpe",   f"{df[s_col].mean():.2f}" if s_col else "—")
        bt4.metric("Total Trades", f"{df[t_col].sum():,.0f}" if t_col else "—")

        grad_cols = [r_col] if r_col else []
        st.dataframe(
            df.style.background_gradient(subset=grad_cols, cmap="RdYlGn").format("{:.2f}"),
            width="stretch",
        )

        if r_col:
            fig = px.bar(
                df.reset_index(), x=df.index, y=r_col,
                color=r_col, color_continuous_scale="RdYlGn",
                title=f"Return (%) per Ticker",
                labels={r_col: "Return (%)"},
            )
            fig.update_layout(template="plotly_dark", height=400,
                              margin=dict(l=0, r=0, t=40, b=0))
            st.plotly_chart(fig, width="stretch")

    # ── Quick backtest launcher ────────────────────────────────────────────
    st.markdown("---")
    st.subheader("⚡ Run a New Backtest")
    st.markdown(
        "Use the command line to run a full backtest:  \n"
        "```\n"
        "python main.py --mode backtest --portfolio --index nifty50\n"
        "```\n"
        "Or for a quick single stock:  \n"
        "```\n"
        "python main.py --mode backtest --tickers RELIANCE.NS TCS.NS --period 2y\n"
        "```"
    )

    st.subheader("🔍 Quick Chart Comparison")
    raw2 = st.text_input(
        "Compare tickers (space-separated)",
        value="RELIANCE.NS TCS.NS HDFCBANK.NS",
        key="backtest_tickers",
    )
    comp_period = st.selectbox("Period", ["6mo", "1y", "2y", "3y"], index=1,
                                key="comp_period")

    if st.button("📊 Show Normalised Performance", key="compare_btn"):
        tickers_list = [t.strip().upper() for t in raw2.split() if t.strip()]
        if not all(t.endswith(".NS") for t in tickers_list):
            tickers_list = [t if t.endswith(".NS") else t + ".NS" for t in tickers_list]

        fig_comp = go.Figure()
        with st.spinner("Loading price data…"):
            for t in tickers_list:
                try:
                    d = load_ticker_df(t, period=comp_period)
                    norm = d["Close"] / d["Close"].iloc[0] * 100
                    fig_comp.add_trace(go.Scatter(
                        x=d.index, y=norm, name=t.replace(".NS", ""),
                        line=dict(width=2),
                    ))
                except Exception:
                    pass
        if fig_comp.data:
            fig_comp.add_hline(y=100, line_dash="dot", line_color="gray")
            fig_comp.update_layout(
                title="Normalised Price Performance (Base = 100)",
                template="plotly_dark", height=400, yaxis_title="% of Start Price",
                margin=dict(l=0, r=0, t=40, b=0),
            )
            st.plotly_chart(fig_comp, width="stretch")


# ═══════════════════════════════════════════════════════════════════════════════
# PAGE 7 — MACRO DASHBOARD  [NEW]  (commodity-currency-correlations skill)
# ═══════════════════════════════════════════════════════════════════════════════
elif page == "🌍 Macro Dashboard":
    st.title("🌍 Macro Dashboard — Commodities, Currencies & Indices")
    st.caption(
        "Key rules: Crude ↑ → INR weakens (India imports 85%)  |  "
        "DXY ↑ → FII outflows from India  |  "
        "Gold ↑ → Risk-off globally  |  "
        "USD/INR ↑ → IT exporters benefit"
    )

    if st.button("🔄 Refresh Macro Data", type="primary"):
        st.cache_data.clear()

    with st.spinner("Fetching 7 macro instruments…"):
        try:
            macro_df = load_macro_data()
            if macro_df.empty:
                st.warning("Could not fetch macro data. Check internet connection.")
            else:
                # Metric cards
                st.subheader("Current Levels & Daily Change")
                card_cols = st.columns(min(len(macro_df.columns), 7))
                for i, col_name in enumerate(macro_df.columns):
                    series = macro_df[col_name].dropna()
                    if len(series) >= 2:
                        curr_v = float(series.iloc[-1])
                        prev_v = float(series.iloc[-2])
                        chg_v  = (curr_v / max(prev_v, 0.0001) - 1) * 100
                        fmt_v  = f"{curr_v:,.0f}" if curr_v > 500 else f"{curr_v:.2f}"
                        card_cols[i % 7].metric(col_name, fmt_v, f"{chg_v:+.2f}%")

                st.markdown("---")

                # Normalised 3-month performance
                st.subheader("3-Month Performance (Normalised to 100)")
                first_valid = macro_df.apply(
                    lambda s: s.dropna().iloc[0] if not s.dropna().empty else 1
                )
                norm_df = macro_df.div(first_valid) * 100
                _colors = ["#4CAF50","#2196F3","#FF6B6B","#FFD700","#FF8C00","#9C27B0","#00BCD4"]
                fig_norm = go.Figure()
                for i, col in enumerate(norm_df.columns):
                    fig_norm.add_trace(go.Scatter(
                        x=norm_df.index, y=norm_df[col], name=col,
                        line=dict(color=_colors[i % len(_colors)], width=2),
                    ))
                fig_norm.add_hline(y=100, line_dash="dot", line_color="white", opacity=0.3)
                fig_norm.update_layout(
                    template="plotly_dark", height=380,
                    yaxis_title="Indexed (start = 100)",
                    legend=dict(orientation="h", y=1.02),
                    margin=dict(l=0, r=0, t=40, b=0),
                )
                st.plotly_chart(fig_norm, width="stretch")

                st.markdown("---")

                # 30-day return correlation heatmap
                st.subheader("30-Day Return Correlation Matrix")
                rets_30  = macro_df.pct_change().tail(30)
                corr_m   = rets_30.corr().round(2)
                fig_corr = px.imshow(
                    corr_m, text_auto=True, aspect="auto",
                    color_continuous_scale="RdBu_r", zmin=-1, zmax=1,
                    title="30-Day Daily Return Correlation",
                )
                fig_corr.update_layout(
                    template="plotly_dark", height=420,
                    margin=dict(l=0, r=0, t=40, b=0),
                )
                st.plotly_chart(fig_corr, width="stretch")

                st.markdown("---")

                # India impact table
                st.subheader("India Market Impact Guide")
                st.dataframe(pd.DataFrame([
                    {"Move": "Brent Crude ↑", "Sector Impact": "Aviation/Paint/Tyre/FMCG ↓",
                     "INR Effect": "INR weakens (imports 85%)", "Nifty Bias": "🔴 Bearish"},
                    {"Move": "Gold ↑",        "Sector Impact": "Jewellery mixed; gold ETFs ↑",
                     "INR Effect": "USD/INR rises if risk-off", "Nifty Bias": "🟡 Risk-off"},
                    {"Move": "DXY ↑",         "Sector Impact": "FII outflows from all EM",
                     "INR Effect": "INR weakens",              "Nifty Bias": "🔴 Bearish"},
                    {"Move": "DXY ↓",         "Sector Impact": "FII inflows to EM",
                     "INR Effect": "INR strengthens",          "Nifty Bias": "🟢 Bullish"},
                    {"Move": "USD/INR ↑",     "Sector Impact": "IT exporters (TCS/Infy/HCL) ↑; Auto ↓",
                     "INR Effect": "Higher import bill",       "Nifty Bias": "🟡 Mixed"},
                    {"Move": "USD/INR ↓",     "Sector Impact": "IT exporters ↓; Importers ↑",
                     "INR Effect": "Lower import costs",       "Nifty Bias": "🟡 Mixed"},
                ]), hide_index=True)

        except Exception as e:
            st.error(f"Macro data error: {e}")


# ═══════════════════════════════════════════════════════════════════════════════
# PAGE 8 — MARKET BREADTH  [NEW]  (market-breadth skill)
# ═══════════════════════════════════════════════════════════════════════════════
elif page == "📈 Market Breadth":
    st.title("📈 Market Breadth — Nifty 50 Internal Health")
    st.caption(
        "Breadth confirms price trends. "
        "Price up + breadth expanding = sustainable rally. "
        "Price up + breadth shrinking = narrow / fragile move."
    )

    if st.button("🔄 Refresh Breadth Data", type="primary"):
        st.cache_data.clear()

    st.info("⏱️ Scanning all 50 Nifty stocks takes ~3 minutes. Results are cached for 15 minutes.")
    run_breadth = st.button("🔍 Compute Breadth Now", type="primary", key="breadth_btn")

    if run_breadth:
        with st.spinner("Scanning Nifty 50 breadth (~3 min)…"):
            breadth = compute_market_breadth(_NIFTY50_TICKERS)

        st.markdown("---")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Advancing",           breadth["advance"])
        c2.metric("Declining",           breadth["decline"])
        c3.metric("A/D Ratio",           f"{breadth['ad_ratio']:.2f}",
                  help="> 1.5 = strong; < 0.7 = weak")
        c4.metric("Near 52W High / Low", f"{breadth['near_52w_high']} / {breadth['near_52w_low']}")

        # % above key MAs bar chart
        st.markdown("---")
        st.subheader("% of Nifty 50 Stocks Above Key Moving Averages")
        bvals = {
            "Above SMA20":  breadth["pct_above_20"],
            "Above SMA50":  breadth["pct_above_50"],
            "Above SMA200": breadth["pct_above_200"],
        }
        bar_fig = go.Figure()
        for label, val in bvals.items():
            bclr = "#4CAF50" if val > 60 else ("#FF9800" if val > 40 else "#F44336")
            bar_fig.add_trace(go.Bar(
                x=[label], y=[val], name=label,
                marker_color=bclr,
                text=[f"{val:.0f}%"], textposition="auto",
            ))
        bar_fig.add_hline(y=70, line_dash="dot", line_color="#4CAF50",
                          annotation_text="Strong (70%)", annotation_position="right")
        bar_fig.add_hline(y=40, line_dash="dot", line_color="#F44336",
                          annotation_text="Weak (40%)", annotation_position="right")
        bar_fig.update_layout(
            template="plotly_dark", height=340,
            yaxis_title="% of stocks", yaxis_range=[0, 100],
            showlegend=False,
            margin=dict(l=0, r=0, t=20, b=0),
        )
        st.plotly_chart(bar_fig, width="stretch")

        # Signal interpretation
        pct200 = breadth["pct_above_200"]
        if pct200 >= 70:
            sig_txt, sig_clr = "🟢 **Strong Bull Market breadth** — Majority above SMA200. Buy dips with confidence.", "#4CAF50"
        elif pct200 >= 50:
            sig_txt, sig_clr = "🟡 **Moderate breadth** — More than half in uptrend. Stock-selective long approach.", "#FF9800"
        elif pct200 >= 30:
            sig_txt, sig_clr = "🟠 **Weakening breadth** — Over half below SMA200. Reduce position sizes.", "#FF5722"
        else:
            sig_txt, sig_clr = "🔴 **Bear market breadth** — Most below SMA200. Defensive posture; consider hedges.", "#F44336"
        st.markdown(
            f'<div style="background:{sig_clr}22;padding:12px;border-radius:8px;'
            f'border-left:4px solid {sig_clr};font-size:15px;margin:10px 0">'
            f'{sig_txt}</div>', unsafe_allow_html=True
        )

        # A/D pie + reference table side by side
        st.markdown("---")
        col_pie, col_tbl = st.columns([1, 1])
        with col_pie:
            st.subheader("Today's Advance / Decline")
            pie_fig = go.Figure(data=go.Pie(
                labels=["Advancing", "Declining"],
                values=[breadth["advance"], breadth["decline"]],
                marker_colors=["#4CAF50", "#F44336"], hole=0.4,
            ))
            pie_fig.update_layout(
                template="plotly_dark", height=260,
                margin=dict(l=0, r=0, t=20, b=0),
            )
            st.plotly_chart(pie_fig, width="stretch")
        with col_tbl:
            st.subheader("Breadth Interpretation Guide")
            st.dataframe(pd.DataFrame([
                {"% Above SMA200": "> 70%",  "Signal": "Strong Bull",    "Action": "Full long — buy dips"},
                {"% Above SMA200": "50–70%", "Signal": "Healthy uptrend","Action": "Long bias, trail stops"},
                {"% Above SMA200": "30–50%", "Signal": "Sector chop",    "Action": "Stock-selective only"},
                {"% Above SMA200": "< 30%",  "Signal": "Bear market",    "Action": "Reduce exposure, hedge"},
            ]), hide_index=True)

        # 52W high / low bars
        st.markdown("---")
        st.subheader("52-Week High / Low Distribution")
        hl_fig = go.Figure(go.Bar(
            x=["Near 52W High (within 5%)", "Near 52W Low (within 5%)"],
            y=[breadth["near_52w_high"], breadth["near_52w_low"]],
            marker_color=["#4CAF50", "#F44336"],
            text=[breadth["near_52w_high"], breadth["near_52w_low"]],
            textposition="auto",
        ))
        hl_fig.update_layout(
            template="plotly_dark", height=260,
            yaxis_title="Number of Nifty 50 stocks",
            margin=dict(l=0, r=0, t=20, b=0),
        )
        st.plotly_chart(hl_fig, width="stretch")


# ═══════════════════════════════════════════════════════════════════════════════
# PAGE 9 — OI & OPTIONS SETUP  [NEW]  (oi-pcr-analysis + options-fno skills)
# ═══════════════════════════════════════════════════════════════════════════════
elif page == "🏦 OI & Options Setup":
    st.title("🏦 OI & Options Setup")
    st.caption(
        "IV regime (VIX-based) + directional bias → right strategy.  "
        "Max Pain calculator + PCR zone reference for expiry planning."
    )

    tab1, tab2, tab3 = st.tabs([
        "📊 Strategy Selector",
        "🔢 Max Pain Calculator",
        "📈 PCR Zone Reference",
    ])

    # ── TAB 1: Strategy Selector ───────────────────────────────────────────────
    with tab1:
        st.subheader("Options Strategy Selector")
        c1, c2 = st.columns(2)
        with c1:
            direction = st.selectbox(
                "Your Directional Bias",
                ["Strongly Bullish", "Mildly Bullish", "Neutral / Range-bound",
                 "Mildly Bearish", "Strongly Bearish"],
                key="opts_dir",
            )
        with c2:
            curr_vix_opt = st.number_input(
                "India VIX (current)", min_value=5.0, max_value=80.0,
                value=float(vix_val) if vix_val else 18.0, step=0.5, key="opts_vix",
            )

        ivr_proxy = min(100, max(0, (curr_vix_opt - 10) / (35 - 10) * 100))
        iv_regime = "Low" if ivr_proxy < 40 else ("Normal" if ivr_proxy < 65 else "High")

        _smap = {
            ("Strongly Bullish",      "Low"):    ("Long Call (ATM)",        "Buy 1 ATM CE, 20–45 DTE",                  "Low IVR = cheap premium — buy directional"),
            ("Strongly Bullish",      "Normal"): ("Bull Call Spread",       "Buy ATM CE + Sell OTM CE (1–2 strikes above)", "Spread cuts cost at normal IV"),
            ("Strongly Bullish",      "High"):   ("Bull Call Spread",       "Buy ATM CE + Sell OTM CE",                  "High IVR: spread essential — naked buy overpriced"),
            ("Mildly Bullish",        "Low"):    ("Bull Call Spread",       "Buy ATM CE + Sell OTM CE",                  "Defined risk for moderate bullish view"),
            ("Mildly Bullish",        "Normal"): ("Bull Call Spread",       "Buy ATM CE + Sell OTM CE",                  "Balanced IV — spread preferred"),
            ("Mildly Bullish",        "High"):   ("Cash-Secured Put (CSP)", "Sell OTM PE at key support strike",         "Collect rich premium; happy to own stock lower"),
            ("Neutral / Range-bound", "Low"):    ("Long Straddle",          "Buy ATM CE + ATM PE, same expiry",          "Expect big move but unsure of direction (event play)"),
            ("Neutral / Range-bound", "Normal"): ("Iron Condor",            "Sell OTM CE+PE + buy further OTM wings",    "Range-bound + normal IV = classic condor setup"),
            ("Neutral / Range-bound", "High"):   ("Iron Condor",            "Sell OTM CE+PE + buy further OTM wings",    "High IVR: sell rich premium in sideways market"),
            ("Mildly Bearish",        "Low"):    ("Bear Put Spread",        "Buy ATM PE + Sell OTM PE",                  "Defined-risk bearish at low IV"),
            ("Mildly Bearish",        "Normal"): ("Bear Put Spread",        "Buy ATM PE + Sell OTM PE",                  "Spread reduces debit"),
            ("Mildly Bearish",        "High"):   ("Bear Put Spread",        "Buy ATM PE + Sell deeper OTM PE",           "High IV: spread essential — naked put costly"),
            ("Strongly Bearish",      "Low"):    ("Long Put (ATM)",         "Buy 1 ATM PE, 20–45 DTE",                  "Strong conviction + cheap premium"),
            ("Strongly Bearish",      "Normal"): ("Bear Put Spread",        "Buy ATM PE + Sell OTM PE",                  "Spread for cost management"),
            ("Strongly Bearish",      "High"):   ("Bear Put Spread",        "Buy ATM PE + Sell OTM PE",                  "High IV: never buy naked options — use spreads"),
        }
        strat, setup, reason = _smap.get(
            (direction, iv_regime),
            ("Review setup", "Use defined-risk spreads", "Unclear IV regime"),
        )

        vbc = "#4CAF50" if curr_vix_opt < 16 else ("#FF9800" if curr_vix_opt < 25 else "#F44336")
        st.markdown(
            f'<div style="background:#1a1a2e;padding:18px;border-radius:10px;'
            f'border-left:5px solid {vbc};margin:12px 0">'
            f'<h3 style="margin:0;color:#fff">Recommended: {strat}</h3>'
            f'<p style="margin:6px 0;color:#ccc"><b>Setup:</b> {setup}</p>'
            f'<p style="margin:6px 0;color:#aaa"><b>Why:</b> {reason}</p>'
            f'<hr style="border-color:#333;margin:10px 0">'
            f'VIX: <b style="color:#fff">{curr_vix_opt:.1f}</b>  |  '
            f'IV Rank (proxy): <b style="color:#fff">{ivr_proxy:.0f}%</b>  |  '
            f'Regime: <b style="color:{vbc}">{iv_regime} IV</b>'
            f'</div>', unsafe_allow_html=True
        )

        st.markdown("---")
        st.subheader("Greeks Quick Reference")
        st.dataframe(pd.DataFrame([
            {"Greek": "Delta (Δ)", "Measures": "₹ change per ₹1 underlying move",   "Rule of Thumb": "ATM ≈ 0.50. OTM 2 strikes ≈ 0.30"},
            {"Greek": "Gamma (Γ)", "Measures": "Rate delta changes",                 "Rule of Thumb": "Highest near ATM + near expiry — P&L swings fast"},
            {"Greek": "Theta (Θ)", "Measures": "Daily time decay (₹)",              "Rule of Thumb": "ATM 30 DTE: ~0.3–0.5%/day. 7 DTE: ~1.5–2%/day"},
            {"Greek": "Vega (V)",  "Measures": "P&L change per 1% IV move",         "Rule of Thumb": "Long options lose value if IV collapses post-event"},
        ]), hide_index=True)

        st.markdown("---")
        st.subheader("NSE Lot Sizes *(verify quarterly)*")
        st.dataframe(pd.DataFrame([
            {"Contract": "Nifty 50",  "Lot Size": 75,  "Approx Margin": "₹1.0–1.5L"},
            {"Contract": "BankNifty", "Lot Size": 30,  "Approx Margin": "₹0.8–1.2L"},
            {"Contract": "FinNifty",  "Lot Size": 65,  "Approx Margin": "₹0.5–0.8L"},
            {"Contract": "RELIANCE",  "Lot Size": 250, "Approx Margin": "₹3–4L"},
            {"Contract": "HDFC Bank", "Lot Size": 550, "Approx Margin": "₹6–8L"},
            {"Contract": "TCS",       "Lot Size": 175, "Approx Margin": "₹6–8L"},
            {"Contract": "Infosys",   "Lot Size": 400, "Approx Margin": "₹5–6L"},
        ]), hide_index=True)

    # ── TAB 2: Max Pain Calculator ─────────────────────────────────────────────
    with tab2:
        st.subheader("Max Pain Calculator")
        st.caption(
            "Max Pain = strike where option buyers lose the most (writers profit most).  "
            "Price gravitates toward Max Pain near expiry — strongest in the last hour."
        )

        strikes_inp = st.text_area("Strike prices (comma-separated)",
                                    "24000,24100,24200,24300,24400,24500,24600", height=60)
        calls_inp   = st.text_area("Call OI at each strike (lots, comma-separated)",
                                    "45000,75000,120000,95000,65000,42000,30000", height=60)
        puts_inp    = st.text_area("Put OI at each strike (lots, comma-separated)",
                                    "35000,55000,100000,88000,58000,40000,22000", height=60)

        if st.button("🎯 Calculate Max Pain", type="primary", key="maxpain_btn"):
            try:
                sl = [float(x.strip()) for x in strikes_inp.split(",") if x.strip()]
                cl = [float(x.strip()) for x in calls_inp.split(",")   if x.strip()]
                pl = [float(x.strip()) for x in puts_inp.split(",")    if x.strip()]

                if len(sl) == len(cl) == len(pl) >= 2:
                    oi_df = pd.DataFrame({"strike": sl, "call_oi": cl, "put_oi": pl})
                    pain_vals = []
                    for k in oi_df["strike"]:
                        cp = ((oi_df["strike"] - k).clip(lower=0) * oi_df["call_oi"]).sum()
                        pp = ((k - oi_df["strike"]).clip(lower=0) * oi_df["put_oi"]).sum()
                        pain_vals.append(cp + pp)
                    oi_df["total_pain"] = pain_vals
                    mp = float(oi_df.loc[oi_df["total_pain"].idxmin(), "strike"])

                    st.success(f"🎯 **Max Pain Strike: {mp:,.0f}**")

                    mp_fig = go.Figure()
                    mp_fig.add_trace(go.Bar(x=oi_df["strike"].astype(str), y=oi_df["call_oi"],
                                            name="Call OI", marker_color="#ef5350"))
                    mp_fig.add_trace(go.Bar(x=oi_df["strike"].astype(str), y=oi_df["put_oi"],
                                            name="Put OI", marker_color="#26a69a"))
                    mp_fig.add_vline(x=str(int(mp)), line_dash="dash",
                                     line_color="#FFD700", line_width=2,
                                     annotation_text=f"Max Pain: {mp:,.0f}",
                                     annotation_font_color="#FFD700")
                    mp_fig.update_layout(
                        template="plotly_dark", barmode="group", height=340,
                        title="Call vs Put OI by Strike",
                        margin=dict(l=0, r=0, t=40, b=0),
                    )
                    st.plotly_chart(mp_fig, width="stretch")

                    pcr_auto = sum(pl) / max(sum(cl), 1)
                    st.metric("PCR (from your input)", f"{pcr_auto:.2f}",
                              help="Total Put OI / Total Call OI")
                else:
                    st.error("All three lists must have the same length (>= 2 strikes).")
            except Exception as e:
                st.error(f"Calculation error: {e}")

    # ── TAB 3: PCR Zone Reference ──────────────────────────────────────────────
    with tab3:
        st.subheader("Put-Call Ratio (PCR) Zone Reference")
        st.caption("PCR = Total Put OI / Total Call OI. Contrarian indicator — extremes signal reversals.")

        pcr_input = st.slider("Current PCR (OI-based)", 0.3, 2.5, 1.0, 0.05, key="pcr_slider")

        if pcr_input < 0.6:
            pcr_sig, pcr_hex = "🔴 Extreme Complacency — too many call buyers. Contrarian BEARISH. Correction likely.", "#F44336"
        elif pcr_input < 0.8:
            pcr_sig, pcr_hex = "🟡 Mildly Bullish sentiment — neutral with slight upward tilt.", "#FF9800"
        elif pcr_input < 1.2:
            pcr_sig, pcr_hex = "🟢 Healthy range — no extreme reading, normal conditions.", "#4CAF50"
        elif pcr_input < 1.5:
            pcr_sig, pcr_hex = "🟡 Mildly Bearish — fear building. Caution on fresh longs.", "#FF9800"
        else:
            pcr_sig, pcr_hex = "🟢 Extreme Fear — too many put buyers. Contrarian BULLISH. Bounce setup.", "#4CAF50"

        st.markdown(
            f'<div style="background:{pcr_hex}22;padding:14px;border-radius:8px;'
            f'border-left:5px solid {pcr_hex};font-size:16px;margin:10px 0">'
            f'PCR = <b>{pcr_input:.2f}</b> → {pcr_sig}'
            f'</div>', unsafe_allow_html=True
        )

        st.markdown("---")
        st.dataframe(pd.DataFrame([
            {"PCR Value": "< 0.6",    "Sentiment": "Extreme complacency",  "Signal": "🔴 Contrarian bearish"},
            {"PCR Value": "0.6–0.8",  "Sentiment": "Mildly bullish",       "Signal": "🟡 Neutral/bullish tilt"},
            {"PCR Value": "0.8–1.2",  "Sentiment": "Healthy (normal)",     "Signal": "🟢 No extreme"},
            {"PCR Value": "1.2–1.5",  "Sentiment": "Mildly bearish",       "Signal": "🟡 Caution"},
            {"PCR Value": "> 1.5",    "Sentiment": "Extreme fear",         "Signal": "🟢 Contrarian bullish"},
        ]), hide_index=True)

        st.markdown("---")
        st.subheader("OI Price Interpretation Framework")
        st.dataframe(pd.DataFrame([
            {"Price": "↑ Rising", "OI": "↑ Rising",  "Meaning": "Long Buildup — fresh bulls entering",  "Signal": "🟢 Strongly Bullish"},
            {"Price": "↓ Falling","OI": "↑ Rising",  "Meaning": "Short Buildup — fresh bears entering", "Signal": "🔴 Strongly Bearish"},
            {"Price": "↑ Rising", "OI": "↓ Falling", "Meaning": "Short Covering — shorts buying back",  "Signal": "🟡 Bullish but weak"},
            {"Price": "↓ Falling","OI": "↓ Falling", "Meaning": "Long Unwinding — longs exiting",       "Signal": "🟡 Bearish but weak"},
        ]), hide_index=True)
        st.caption(
            "Key: Long Buildup (Price ↑ + OI ↑) is the strongest bullish signal. "
            "Short Covering (Price ↑ + OI ↓) is weaker — shorts exiting, not fresh bulls."
        )


# ═══════════════════════════════════════════════════════════════════════════════
# PAGE 11 — INVESTOR GUIDE (SOP)
# ═══════════════════════════════════════════════════════════════════════════════
elif page == "📖 Investor Guide":
    st.title("📖 Investor Guide — How to Read This Dashboard")
    st.markdown(
        "This guide explains every signal, score, and term used in the NSE Smart Investor platform.  \n"
        "Read this once and you will understand exactly what every number means and when to act."
    )

    tab_g1, tab_g2, tab_g3, tab_g4, tab_g5 = st.tabs([
        "🎯 Scores & Signals", "📊 Indicators", "🔴 Stop-Loss & Risk",
        "📰 News Signals", "📌 Paper Trading SOP"
    ])

    # ── TAB 1: SCORES & SIGNALS ───────────────────────────────────────────────
    with tab_g1:
        st.subheader("Composite Score (0 – 100)")
        st.markdown(
            "Every stock gets a **Composite Score from 0 to 100**. "
            "This combines five factors: Technical (40 pts) + Momentum (25 pts) + "
            "Volume (15 pts) + Candlestick Pattern (10 pts) + News Sentiment (10 pts)."
        )
        st.dataframe(pd.DataFrame([
            {"Score Range": "80 – 100", "Grade": "A+", "Signal": "STRONG BUY 🚀",   "What It Means": "Everything aligned — strong trend, good momentum, high volume. Ideal entry."},
            {"Score Range": "65 – 79",  "Grade": "A",  "Signal": "BUY 🟢",           "What It Means": "Positive trend with good momentum. Entry is favourable."},
            {"Score Range": "50 – 64",  "Grade": "B",  "Signal": "WATCHLIST 👀",     "What It Means": "Mixed signals. Worth watching but wait for clearer confirmation."},
            {"Score Range": "40 – 49",  "Grade": "C",  "Signal": "HOLD 🟡",          "What It Means": "Balanced picture — neither buy nor sell. Hold your existing position."},
            {"Score Range": "25 – 39",  "Grade": "D",  "Signal": "CAUTION ⚠️",       "What It Means": "Deteriorating momentum. Tighten stop-loss, don't add more."},
            {"Score Range": "0 – 24",   "Grade": "F",  "Signal": "EXIT 🔴",          "What It Means": "Technicals broken. Consider exiting to protect capital."},
        ]), hide_index=True)

        st.markdown("---")
        st.subheader("Score Sub-Components")
        st.dataframe(pd.DataFrame([
            {"Component":    "Technical (40 pts)",  "What It Measures": "RSI, MACD, Bollinger Bands, SMA trends — is the stock in a healthy uptrend?"},
            {"Component":    "Momentum (25 pts)",   "What It Measures": "Recent price performance vs moving averages. Is the stock accelerating?"},
            {"Component":    "Volume (15 pts)",     "What It Measures": "Is trading volume higher than normal? Big moves on high volume are more reliable."},
            {"Component":    "Candlestick (10 pts)","What It Measures": "Bullish/bearish candle patterns in last 3 days (Hammer, Engulfing, Doji, etc.)"},
            {"Component":    "Sentiment (10 pts)",  "What It Measures": "News tone: positive articles boost score, negative articles reduce it."},
        ]), hide_index=True)

        st.markdown("---")
        st.subheader("VIX Regime — Market Fear Gauge")
        st.markdown(
            "**India VIX** measures how much volatility the market expects over the next 30 days. "
            "High VIX = fear = caution. Low VIX = complacency = also caution (different reason)."
        )
        st.dataframe(pd.DataFrame([
            {"VIX Level": "< 12",   "Regime": "Complacency", "Meaning": "Market too relaxed — be careful, corrections start here"},
            {"VIX Level": "12–16",  "Regime": "Normal 🟢",   "Meaning": "Healthy range — good conditions for long trades"},
            {"VIX Level": "16–22",  "Regime": "Elevated 🟡", "Meaning": "Some fear — be selective, reduce position sizes"},
            {"VIX Level": "22–28",  "Regime": "Fear 🔴",     "Meaning": "Significant fear — prioritise stop-losses, be defensive"},
            {"VIX Level": "> 28",   "Regime": "PANIC 🔴",    "Meaning": "Market panic — avoid new long positions; can be contrarian buy at extremes"},
        ]), hide_index=True)

    # ── TAB 2: INDICATORS ─────────────────────────────────────────────────────
    with tab_g2:
        st.subheader("Technical Indicators — Plain English")
        st.dataframe(pd.DataFrame([
            {"Indicator": "RSI (14)",          "Range": "0 – 100",    "Normal": "30–70",     "Meaning": "Relative Strength Index. Below 30 = oversold (potential bounce). Above 70 = overbought (potential pullback). Not a standalone signal."},
            {"Indicator": "MACD",              "Range": "Positive/Neg","Normal": "Near zero", "Meaning": "Moving Average Convergence Divergence. MACD crossing above its signal line = bullish. Below = bearish."},
            {"Indicator": "Bollinger Bands",   "Range": "Price levels","Normal": "Within band","Meaning": "Upper/lower bands = 2 standard deviations from 20-day average. Price near upper = overbought. Near lower = oversold."},
            {"Indicator": "SMA 20 / 50 / 200","Range": "Price level", "Normal": "Price > SMA","Meaning": "Simple Moving Average. Price above SMA200 = in long-term uptrend. SMA20 > SMA50 > SMA200 = strong bull alignment."},
            {"Indicator": "ADX",               "Range": "0 – 100",    "Normal": "20–40",     "Meaning": "Average Directional Index. Above 25 = trending (directional trade OK). Below 20 = ranging (avoid breakout trades)."},
            {"Indicator": "ATR",               "Range": "₹ value",    "Normal": "Varies",    "Meaning": "Average True Range. Average daily price movement in rupees. Used to set stop-losses (typically 1.5–2× ATR below entry)."},
            {"Indicator": "Volume Ratio",      "Range": "> 0",        "Normal": "0.8–1.2",   "Meaning": "Today's volume ÷ 20-day average volume. Above 1.5 = above-average interest. Above 2.5 = institutional activity."},
            {"Indicator": "Stochastic K",      "Range": "0 – 100",    "Normal": "20–80",     "Meaning": "Momentum oscillator. Below 20 = oversold, above 80 = overbought. Best used with other signals."},
            {"Indicator": "VWAP %",            "Range": "% value",    "Normal": "±1%",       "Meaning": "Price vs Volume-Weighted Average Price. Positive = stock is above where most volume traded today (bullish intraday). Negative = below (bearish intraday)."},
        ]), hide_index=True)

        st.markdown("---")
        st.subheader("Candlestick Patterns")
        st.dataframe(pd.DataFrame([
            {"Pattern": "Hammer 🔨",          "Type": "Bullish Reversal", "Reliability": "★★★★", "What It Means": "Long lower wick at a low. Sellers tried to push lower but buyers stepped in. Bullish at support."},
            {"Pattern": "Shooting Star ⭐",   "Type": "Bearish Reversal", "Reliability": "★★★★", "What It Means": "Long upper wick at a high. Buyers tried to push higher but sellers overwhelmed them. Bearish at resistance."},
            {"Pattern": "Doji",               "Type": "Indecision",       "Reliability": "★★★",  "What It Means": "Open = Close. Neither buyers nor sellers in control. Watch for next candle's direction."},
            {"Pattern": "Bullish Engulfing",  "Type": "Bullish Reversal", "Reliability": "★★★★★","What It Means": "Large green candle engulfs prior red candle. Powerful reversal after a downtrend. High-probability on volume."},
            {"Pattern": "Bearish Engulfing",  "Type": "Bearish Reversal", "Reliability": "★★★★★","What It Means": "Large red candle engulfs prior green candle. Strong reversal signal after an uptrend."},
            {"Pattern": "Morning Star ☀️",   "Type": "Bullish Reversal", "Reliability": "★★★★★","What It Means": "3-candle: big red → small candle → big green. Classic bottom formation at support."},
            {"Pattern": "Evening Star 🌙",    "Type": "Bearish Reversal", "Reliability": "★★★★★","What It Means": "3-candle: big green → small candle → big red. Classic top formation at resistance."},
            {"Pattern": "Three White Soldiers","Type": "Bullish Continuation","Reliability": "★★★★","What It Means": "3 consecutive bullish candles. Signals strong uptrend resumption after a base."},
        ]), hide_index=True)

    # ── TAB 3: STOP-LOSS & RISK ───────────────────────────────────────────────
    with tab_g3:
        st.subheader("Stop-Loss — Protecting Your Capital")
        st.markdown(
            "A **stop-loss** is the price at which you exit a losing trade to prevent further losses.  \n"
            "**Never trade without a stop-loss.** It is not optional — it is your safety net."
        )
        st.dataframe(pd.DataFrame([
            {"Term": "Stop-Loss (SL)",    "Meaning": "The price at which you will exit if wrong. Set BEFORE you enter the trade."},
            {"Term": "ATR Stop",          "Meaning": "Stop set 1.5–2× the Average True Range (ATR) below entry. Adjusts for each stock's typical daily movement."},
            {"Term": "Structure Stop",    "Meaning": "Stop placed just below a key support level (previous swing low, major moving average)."},
            {"Term": "Trailing Stop",     "Meaning": "Stop that moves UP as the price rises — locks in profits while letting winners run."},
            {"Term": "Breakeven Stop",    "Meaning": "Once a trade gains 1R profit, move stop to entry price. You can no longer lose money on this trade."},
        ]), hide_index=True)

        st.markdown("---")
        st.subheader("Risk : Reward (R:R) — The Most Important Concept")
        st.markdown(
            "**Risk:Reward ratio** compares how much you could lose (risk) vs how much you could gain (reward).  \n"
            "**Always aim for at least 1.5:1**. This means for every ₹100 you risk, you aim to gain ₹150."
        )
        st.dataframe(pd.DataFrame([
            {"R:R Ratio": "3:1 or higher", "Meaning": "Excellent — even with only 35% win rate, you will be profitable long-term"},
            {"R:R Ratio": "2:1",           "Meaning": "Good — standard target. With 45% win rate you profit consistently"},
            {"R:R Ratio": "1.5:1",         "Meaning": "Minimum acceptable. Need >55% win rate to be consistently profitable"},
            {"R:R Ratio": "1:1",           "Meaning": "Break-even at best. Not recommended unless win rate is very high (>65%)"},
            {"R:R Ratio": "< 1:1",         "Meaning": "Avoid — risking more than potential reward. Mathematically losing strategy"},
        ]), hide_index=True)

        st.markdown("---")
        st.subheader("Position Sizing — How Much to Buy")
        st.markdown(
            "**Never risk more than 1–2% of your total capital on a single trade.**  \n\n"
            "**Formula:** Shares to buy = (Capital × Risk%) ÷ (Entry Price − Stop-Loss Price)  \n\n"
            "**Example:** ₹5,00,000 portfolio × 2% risk = ₹10,000 max loss.  \n"
            "If entry = ₹1,000 and stop = ₹950 → risk per share = ₹50  \n"
            "→ Buy 10,000 ÷ 50 = **200 shares** (₹2,00,000 invested, but max loss is ₹10,000)."
        )

        st.markdown("---")
        st.subheader("Common Mistakes — What to Avoid")
        st.dataframe(pd.DataFrame([
            {"Mistake": "No stop-loss",              "Consequence": "One bad trade can wipe out months of gains", "Fix": "Always set a stop before entering"},
            {"Mistake": "Moving stop-loss down",     "Consequence": "Turns a small loss into a disaster",         "Fix": "Only move stops UP (in the trade's favour), never down"},
            {"Mistake": "Averaging down losers",     "Consequence": "More capital trapped in a losing position",  "Fix": "If stop is hit, exit. Never add to a loser."},
            {"Mistake": "Holding losers, selling winners","Consequence": "Loss portfolio of bad trades",         "Fix": "Let winners run. Cut losers quickly at stop."},
            {"Mistake": "Trading on tips/news alone","Consequence": "No edge, random outcomes",                  "Fix": "Use the composite score + chart for confirmation"},
            {"Mistake": "Overtrading",               "Consequence": "Brokerage + taxes eat all profits",         "Fix": "Only trade high-conviction setups (score ≥ 65)"},
        ]), hide_index=True)

    # ── TAB 4: NEWS SIGNALS ───────────────────────────────────────────────────
    with tab_g4:
        st.subheader("How News Affects Stock Prices")
        st.markdown(
            "News is one of the **fastest-moving market catalysts**. The dashboard fetches "
            "real-time news for each stock and tags it with a sentiment: Positive, Negative, or Neutral."
        )
        st.dataframe(pd.DataFrame([
            {"News Type": "🟢 POSITIVE",              "Examples": "Strong quarterly results, big order wins, government policy support, rating upgrades, new product launches"},
            {"News Type": "🔴 NEGATIVE",              "Examples": "Profit warning, regulatory fine, management exit, debt downgrade, sector headwinds, fraud allegations"},
            {"News Type": "⚪ NEUTRAL",               "Examples": "AGM dates, routine management changes, product announcements without financials"},
        ]), hide_index=True)

        st.markdown("---")
        st.subheader("How to Use News Alongside Scores")
        st.dataframe(pd.DataFrame([
            {"Score Signal": "BUY 🟢", "News Sentiment": "Positive 🟢", "Combined Signal": "Strong BUY — fundamentals + technicals aligned",       "Action": "Enter with full position size"},
            {"Score Signal": "BUY 🟢", "News Sentiment": "Negative 🔴", "Combined Signal": "Conflict — technical buy but fundamental headwind",    "Action": "Wait or use half position"},
            {"Score Signal": "HOLD 🟡","News Sentiment": "Positive 🟢", "Combined Signal": "Potential upgrade — watch for score improvement",       "Action": "Set alert, review next day"},
            {"Score Signal": "HOLD 🟡","News Sentiment": "Negative 🔴", "Combined Signal": "Risk of breakdown — tighten stop-loss",                "Action": "Move stop to breakeven or exit"},
            {"Score Signal": "EXIT 🔴","News Sentiment": "Positive 🟢", "Combined Signal": "Technical bearish despite good news — mixed",          "Action": "If score < 30, exit anyway"},
            {"Score Signal": "EXIT 🔴","News Sentiment": "Negative 🔴", "Combined Signal": "Full sell signal — both technicals and news bearish",   "Action": "Exit immediately at stop"},
        ]), hide_index=True)

        st.markdown("---")
        st.subheader("Key News Events Calendar (Indian Markets)")
        st.dataframe(pd.DataFrame([
            {"Event": "Quarterly Results (Q1, Q2, Q3, Q4)", "When": "Apr/Jul/Oct/Jan", "Impact": "HIGH — stock can move 5–20% in one day. Avoid holding through results unless you understand the company well."},
            {"Event": "RBI Monetary Policy Committee (MPC)", "When": "Every 2 months",  "Impact": "HIGH — affects banking stocks, rate-sensitive sectors (real estate, auto, NBFCs)"},
            {"Event": "Union Budget",                        "When": "1 Feb each year", "Impact": "VERY HIGH — sector-specific impacts. VIX spikes before budget, often reverses same day."},
            {"Event": "FII/DII Buy/Sell Data",               "When": "Daily",            "Impact": "MEDIUM — sustained FII selling is bearish for Nifty. FII buying supports rally."},
            {"Event": "SEBI Circulars / Regulatory Actions", "When": "As they occur",   "Impact": "MEDIUM–HIGH — affects specific sectors (fintech, brokers, insurance)"},
        ]), hide_index=True)

    # ── TAB 5: PAPER TRADING SOP ──────────────────────────────────────────────
    with tab_g5:
        st.subheader("📌 How to Use Paper Trading — Step by Step")
        st.markdown(
            "**Paper trading** lets you practice decision-making with zero financial risk.  \n"
            "Think of it as a flight simulator before flying a real plane."
        )

        st.markdown("""
**Step 1 — Find a trade setup**
- Go to **🔍 Analyze Stock** and search for a stock
- If the Composite Score is **≥ 65** and the action is **BUY**, that is a potential entry
- Check the news — is the sentiment positive or neutral?

**Step 2 — Open a paper trade**
- Click **"📌 Paper Trade This Signal"** on the Analyze Stock page, OR
- Go to **📂 Paper Trades** and use the "Open New Paper Trade" form
- The entry price, stop-loss, and target are pre-filled from the model's analysis
- Check the **Risk:Reward ratio** shown — it should be ≥ 1.5:1 before entering

**Step 3 — Track your open position**
- Visit **📂 Paper Trades** daily
- You will see live P&L for every open position
- Green card = in profit. Red card = in loss.
- If the stock hits your stop-loss, click **"Close @ Stop"** — discipline is everything
- If the stock hits your target, click **"Close @ Target"** to book the profit

**Step 4 — Review your performance**
- After 10–20 paper trades, check the **Performance Statistics** section
- Key metrics to watch:
  - **Win Rate > 45%** — you are picking more winners than losers
  - **Payoff Ratio > 1.5** — your winners are bigger than your losers
  - **Expectancy > 0** — your strategy has a positive edge and is worth real money

**Step 5 — Graduate to real money (carefully)**
- Only consider real money after 30+ paper trades with positive expectancy
- Start with the smallest lot size / quantity possible
- Keep risking only 1–2% of capital per trade, just like in paper trading

---
""")

        st.subheader("📊 The 3 Numbers That Define Your Edge")
        _edge_col1, _edge_col2, _edge_col3 = st.columns(3)
        with _edge_col1:
            st.markdown(
                '<div class="card-green">'
                '<b>Win Rate</b><br>'
                'Target: > 45%<br>'
                'How to improve: Only take trades with score ≥ 65 and positive news'
                '</div>', unsafe_allow_html=True
            )
        with _edge_col2:
            st.markdown(
                '<div class="card-blue">'
                '<b>Payoff Ratio</b><br>'
                'Target: > 1.5:1<br>'
                'How to improve: Never enter a trade with R:R less than 1.5:1'
                '</div>', unsafe_allow_html=True
            )
        with _edge_col3:
            st.markdown(
                '<div class="card-yellow">'
                '<b>Expectancy</b><br>'
                'Target: Positive ₹/trade<br>'
                'How to improve: Cut losses quickly; let winners reach target'
                '</div>', unsafe_allow_html=True
            )

        st.markdown("---")
        st.info(
            "📖 **Remember:** The model gives signals based on historical patterns. "
            "No model is 100% accurate. Always use stop-losses. "
            "Paper trade first to verify the signals work for you before using real money."
        )
