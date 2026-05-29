"""
utils/indicators.py
Computes technical indicators: MA, RSI, MACD, BB, ATR, VWAP, ADX, Stochastic,
Fibonacci retracements, Supertrend, CPR/Pivot Points,
candlestick patterns, and RSI divergence.
Uses pure pandas/numpy — no TA-Lib C library required.
"""

import pandas as pd
import numpy as np


# ─────────────────────────────────────────────────────────────────────────────
# Core call: add everything to a DataFrame
# ─────────────────────────────────────────────────────────────────────────────

def add_all_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Add all standard indicators to a single-stock OHLCV DataFrame."""
    df = add_moving_averages(df)
    df = add_rsi(df)
    df = add_macd(df)
    df = add_bollinger_bands(df)
    df = add_atr(df)
    df = add_vwap(df)
    df = add_adx(df)
    df = add_stochastic(df)
    df = add_volume_indicators(df)
    df = add_returns(df)
    df = add_fibonacci_levels(df)
    df = add_supertrend(df)
    df = add_pivot_points(df)
    df = detect_candlestick_patterns(df)
    df = detect_rsi_divergence(df)
    return df


# ─────────────────────────────────────────────────────────────────────────────
# Moving Averages
# ─────────────────────────────────────────────────────────────────────────────

def add_moving_averages(df: pd.DataFrame) -> pd.DataFrame:
    """Simple and Exponential Moving Averages."""
    for period in [5, 10, 20, 50, 200]:
        df[f"SMA_{period}"] = df["Close"].rolling(window=period).mean()
        df[f"EMA_{period}"] = df["Close"].ewm(span=period, adjust=False).mean()
    return df


# ─────────────────────────────────────────────────────────────────────────────
# RSI
# ─────────────────────────────────────────────────────────────────────────────

def add_rsi(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    """Relative Strength Index (Wilder's smoothing)."""
    delta    = df["Close"].diff()
    gain     = delta.clip(lower=0)
    loss     = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    rs       = avg_gain / avg_loss.replace(0, np.nan)
    df["RSI"] = 100 - (100 / (1 + rs))
    return df


# ─────────────────────────────────────────────────────────────────────────────
# MACD
# ─────────────────────────────────────────────────────────────────────────────

def add_macd(df: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    """MACD, Signal Line, and Histogram."""
    ema_fast          = df["Close"].ewm(span=fast,   adjust=False).mean()
    ema_slow          = df["Close"].ewm(span=slow,   adjust=False).mean()
    df["MACD"]        = ema_fast - ema_slow
    df["MACD_Signal"] = df["MACD"].ewm(span=signal, adjust=False).mean()
    df["MACD_Hist"]   = df["MACD"] - df["MACD_Signal"]
    return df


# ─────────────────────────────────────────────────────────────────────────────
# Bollinger Bands
# ─────────────────────────────────────────────────────────────────────────────

def add_bollinger_bands(df: pd.DataFrame, period: int = 20, std_dev: float = 2.0) -> pd.DataFrame:
    """Bollinger Bands: Upper, Middle (SMA), Lower, %B, and Width."""
    middle         = df["Close"].rolling(window=period).mean()
    std            = df["Close"].rolling(window=period).std()
    df["BB_Upper"] = middle + std_dev * std
    df["BB_Middle"]= middle
    df["BB_Lower"] = middle - std_dev * std
    df["BB_Width"] = (df["BB_Upper"] - df["BB_Lower"]) / df["BB_Middle"]
    df["BB_Pct"]   = (df["Close"] - df["BB_Lower"]) / (df["BB_Upper"] - df["BB_Lower"])
    return df


# ─────────────────────────────────────────────────────────────────────────────
# ATR
# ─────────────────────────────────────────────────────────────────────────────

def add_atr(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    """Average True Range — raw volatility measure."""
    high_low   = df["High"] - df["Low"]
    high_close = (df["High"] - df["Close"].shift()).abs()
    low_close  = (df["Low"]  - df["Close"].shift()).abs()
    true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    df["ATR"]     = true_range.rolling(window=period).mean()
    df["ATR_Pct"] = df["ATR"] / df["Close"] * 100   # ATR as % of price
    return df


# ─────────────────────────────────────────────────────────────────────────────
# Anchored VWAP  (intraday — resets at market open each day)
# ─────────────────────────────────────────────────────────────────────────────

def add_anchored_vwap(df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute intraday VWAP anchored from the start of each trading day.

    Designed for intraday DataFrames with a DatetimeIndex.
    Groups bars by date (ignoring time) and computes cumulative VWAP
    that resets at 09:15 each morning.

    Columns added:
        AVWAP        : anchored VWAP (resets each day)
        AVWAP_Pct    : (Close − AVWAP) / AVWAP × 100
        AVWAP_SD1_Upper : VWAP + 1σ (volume-weighted)
        AVWAP_SD1_Lower : VWAP − 1σ
        AVWAP_SD2_Upper : VWAP + 2σ
        AVWAP_SD2_Lower : VWAP − 2σ
    """
    try:
        idx = df.index
        # Works with both DatetimeIndex and date-based index
        if hasattr(idx, "date"):
            dates = pd.Series(idx.date, index=idx)
        else:
            dates = pd.Series(idx, index=idx)

        tp     = (df["High"] + df["Low"] + df["Close"]) / 3
        tp_vol = tp * df["Volume"]
        tp_sq  = tp ** 2 * df["Volume"]

        avwap_vals = np.zeros(len(df))
        sd1u = np.zeros(len(df))
        sd1l = np.zeros(len(df))
        sd2u = np.zeros(len(df))
        sd2l = np.zeros(len(df))

        cum_tp_vol = 0.0
        cum_vol    = 0.0
        cum_sq     = 0.0
        prev_date  = None

        for i, (idx_val, date) in enumerate(dates.items()):
            if date != prev_date:
                # New day — reset cumulative sums
                cum_tp_vol = 0.0
                cum_vol    = 0.0
                cum_sq     = 0.0
                prev_date  = date

            cum_tp_vol += float(tp_vol.iloc[i])
            cum_vol    += float(df["Volume"].iloc[i])
            cum_sq     += float(tp_sq.iloc[i])

            if cum_vol > 0:
                vwap_val = cum_tp_vol / cum_vol
                var_val  = max(0, cum_sq / cum_vol - vwap_val ** 2)
                sd_val   = var_val ** 0.5
                avwap_vals[i] = vwap_val
                sd1u[i]  = vwap_val + 1 * sd_val
                sd1l[i]  = vwap_val - 1 * sd_val
                sd2u[i]  = vwap_val + 2 * sd_val
                sd2l[i]  = vwap_val - 2 * sd_val

        df["AVWAP"]          = avwap_vals
        df["AVWAP_Pct"]      = (df["Close"] / df["AVWAP"].replace(0, np.nan) - 1) * 100
        df["AVWAP_SD1_Upper"] = sd1u
        df["AVWAP_SD1_Lower"] = sd1l
        df["AVWAP_SD2_Upper"] = sd2u
        df["AVWAP_SD2_Lower"] = sd2l

    except Exception:
        # Fallback: add NaN columns so downstream code doesn't break
        for col in ["AVWAP", "AVWAP_Pct", "AVWAP_SD1_Upper", "AVWAP_SD1_Lower",
                    "AVWAP_SD2_Upper", "AVWAP_SD2_Lower"]:
            df[col] = np.nan

    return df


# ─────────────────────────────────────────────────────────────────────────────
# VWAP  (rolling 20-day on daily bars — institutional fair-value reference)
# ─────────────────────────────────────────────────────────────────────────────

def add_vwap(df: pd.DataFrame, period: int = 20) -> pd.DataFrame:
    """
    Rolling VWAP on daily OHLCV bars.

    Standard VWAP resets intraday; on daily data we use a 20-day rolling window
    as the medium-term institutional benchmark price.

    Also computes VWAP_Pct = how far current close is from VWAP (in %).
    """
    tp               = (df["High"] + df["Low"] + df["Close"]) / 3
    tp_vol           = tp * df["Volume"]
    # Guard against zero-volume windows (halted stocks / holidays)
    _vol_sum = df["Volume"].rolling(period).sum().replace(0, float("nan"))
    df["VWAP_20"]    = tp_vol.rolling(period).sum() / _vol_sum
    df["VWAP_Pct"]   = (df["Close"] / df["VWAP_20"].replace(0, float("nan")) - 1) * 100
    return df


# ─────────────────────────────────────────────────────────────────────────────
# ADX — trend strength
# ─────────────────────────────────────────────────────────────────────────────

def add_adx(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    """
    Average Directional Index (ADX) with DI+ and DI-.

    ADX < 20  = no trend (range / chop)
    ADX 20-25 = weak trend
    ADX > 25  = trending market
    ADX > 40  = strong trend
    """
    high  = df["High"]
    low   = df["Low"]
    close = df["Close"]

    # True Range
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low  - close.shift()).abs()
    ], axis=1).max(axis=1)

    # +DM and -DM (mutually exclusive)
    up_move   = high - high.shift()
    down_move = low.shift() - low
    dm_plus   = np.where((up_move > down_move) & (up_move > 0), up_move,  0.0)
    dm_minus  = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    dm_plus_s  = pd.Series(dm_plus,  index=df.index)
    dm_minus_s = pd.Series(dm_minus, index=df.index)

    atr14       = tr.ewm(alpha=1/period, adjust=False).mean()
    di_plus     = 100 * dm_plus_s.ewm(alpha=1/period,  adjust=False).mean() / atr14
    di_minus    = 100 * dm_minus_s.ewm(alpha=1/period, adjust=False).mean() / atr14
    dx          = (100 * (di_plus - di_minus).abs() / (di_plus + di_minus).replace(0, np.nan))
    df["ADX"]      = dx.ewm(alpha=1/period, adjust=False).mean()
    df["DI_Plus"]  = di_plus
    df["DI_Minus"] = di_minus
    return df


# ─────────────────────────────────────────────────────────────────────────────
# Stochastic Oscillator
# ─────────────────────────────────────────────────────────────────────────────

def add_stochastic(df: pd.DataFrame, k_period: int = 14, d_period: int = 3) -> pd.DataFrame:
    """
    Stochastic %K and %D.

    < 20 = oversold   (potential buy)
    > 80 = overbought (potential sell)
    """
    low_n          = df["Low"].rolling(k_period).min()
    high_n         = df["High"].rolling(k_period).max()
    range_n        = (high_n - low_n).replace(0, np.nan)
    df["Stoch_K"]  = 100 * (df["Close"] - low_n) / range_n
    df["Stoch_D"]  = df["Stoch_K"].rolling(d_period).mean()
    return df


# ─────────────────────────────────────────────────────────────────────────────
# Volume Indicators
# ─────────────────────────────────────────────────────────────────────────────

def add_volume_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Volume SMA, Volume Ratio, and On-Balance Volume."""
    df["Volume_SMA_20"] = df["Volume"].rolling(window=20).mean()
    df["Volume_Ratio"]  = df["Volume"] / df["Volume_SMA_20"]

    # On-Balance Volume (pure-python loop — avoids float precision issues)
    obv = [0]
    closes = df["Close"].values
    vols   = df["Volume"].values
    for i in range(1, len(df)):
        if closes[i] > closes[i - 1]:
            obv.append(obv[-1] + vols[i])
        elif closes[i] < closes[i - 1]:
            obv.append(obv[-1] - vols[i])
        else:
            obv.append(obv[-1])
    df["OBV"] = obv
    return df


# ─────────────────────────────────────────────────────────────────────────────
# Relative Strength vs Index  (D-2 — delivery trader quality filter)
# ─────────────────────────────────────────────────────────────────────────────

def add_relative_strength(
    df:       pd.DataFrame,
    bench_df: pd.DataFrame,
    period:   int = 63,     # 63 trading days ≈ 3 months (IBD convention)
) -> pd.DataFrame:
    """
    Compute Relative Strength of the stock vs a benchmark (usually Nifty 50).

    RS Line  = stock_close / benchmark_close  (ratio)
    RS_Pct   = (RS now / RS_N_bars_ago − 1) × 100  → +% = outperforming
    RS_Score = percentile rank within own 52-week range [0–100]
               (similar to IBD RS Rating — higher = stronger relative performer)

    Typical usage (delivery trading rule):
        - Only buy stocks where RS_Score ≥ 70 (top 30% relative performers)
        - RS_Line making new highs before price = leading indicator

    Args:
        df       : stock daily OHLCV with Close column
        bench_df : benchmark daily OHLCV (e.g. Nifty 50 from fetch_single('^NSEI'))
        period   : lookback for RS_Pct momentum (default 63 bars = 3 months)

    Columns added:
        RS_Line   : stock / benchmark ratio
        RS_Pct    : N-period relative momentum vs benchmark  (%)
        RS_Score  : 0-100 rank within 52-week RS range
        RS_Trend  : 'outperforming' | 'underperforming' | 'inline'
    """
    try:
        # Align on common dates
        common_idx = df.index.intersection(bench_df.index)
        if len(common_idx) < period + 10:
            for col in ["RS_Line", "RS_Pct", "RS_Score", "RS_Trend"]:
                df[col] = np.nan
            return df

        stock_close = df["Close"].reindex(common_idx)
        bench_close = bench_df["Close"].reindex(common_idx)

        rs_line = stock_close / bench_close.replace(0, np.nan)

        # Reindex back to original df index
        rs_aligned = rs_line.reindex(df.index)
        df["RS_Line"] = rs_aligned

        # RS momentum: N-period change in RS ratio
        rs_pct = rs_aligned.pct_change(period) * 100
        df["RS_Pct"] = rs_pct.round(2)

        # RS Score: 0-100 percentile rank in 252-bar rolling window
        def _pct_rank(series: pd.Series, window: int = 252) -> pd.Series:
            return series.rolling(window, min_periods=window // 4).apply(
                lambda x: (x[-1] > x[:-1]).mean() * 100, raw=True
            )
        df["RS_Score"] = _pct_rank(rs_aligned, 252).round(1)

        # Trend label
        conditions = [
            rs_pct > 2,
            rs_pct < -2,
        ]
        df["RS_Trend"] = np.select(conditions, ["outperforming", "underperforming"],
                                   default="inline")

    except Exception:
        for col in ["RS_Line", "RS_Pct", "RS_Score", "RS_Trend"]:
            df[col] = np.nan

    return df


# ─────────────────────────────────────────────────────────────────────────────
# Returns / Volatility
# ─────────────────────────────────────────────────────────────────────────────

def add_returns(df: pd.DataFrame) -> pd.DataFrame:
    """Log and simple returns at various horizons."""
    df["Return_1d"]     = df["Close"].pct_change(1)
    df["Return_5d"]     = df["Close"].pct_change(5)
    df["Return_20d"]    = df["Close"].pct_change(20)
    df["Log_Return"]    = np.log(df["Close"] / df["Close"].shift(1))
    df["Volatility_20d"]= df["Log_Return"].rolling(20).std() * np.sqrt(252)
    return df


# ─────────────────────────────────────────────────────────────────────────────
# Candlestick Patterns  (from candlestick-patterns skill)
# ─────────────────────────────────────────────────────────────────────────────

def detect_candlestick_patterns(df: pd.DataFrame) -> pd.DataFrame:
    """
    Detect 8 high-reliability candlestick patterns.

    Pattern columns (int): 0 = no pattern, 1 = pattern present.
    Context checks (uptrend / downtrend / support) are done in the signal layer.

    Patterns:
        Pat_Doji          — indecision (body < 5% of range)
        Pat_Hammer        — bullish reversal at bottoms
        Pat_ShootingStar  — bearish reversal at tops
        Pat_BullMarubozu  — strong bullish bar (body ≥ 90% of range)
        Pat_BearMarubozu  — strong bearish bar
        Pat_BullEngulfing — prev red fully engulfed by curr green  ★★★★★
        Pat_BearEngulfing — prev green fully engulfed by curr red  ★★★★★
        Pat_MorningStar   — 3-candle bullish reversal              ★★★★★
        Pat_EveningStar   — 3-candle bearish reversal              ★★★★★
    """
    if "Open" not in df.columns:
        # Some data sources may lack Open; skip silently
        for col in ["Pat_Doji", "Pat_Hammer", "Pat_ShootingStar",
                    "Pat_BullMarubozu", "Pat_BearMarubozu",
                    "Pat_BullEngulfing", "Pat_BearEngulfing",
                    "Pat_MorningStar", "Pat_EveningStar"]:
            df[col] = 0
        return df

    o = df["Open"]
    h = df["High"]
    l = df["Low"]
    c = df["Close"]

    body       = (c - o).abs()
    total_rng  = (h - l).replace(0, np.nan)
    upper_wick = h - pd.concat([c, o], axis=1).max(axis=1)
    lower_wick = pd.concat([c, o], axis=1).min(axis=1) - l

    # Doji: body < 5% of total range
    df["Pat_Doji"] = (body < 0.05 * total_rng).fillna(0).astype(int)

    # Hammer: lower wick ≥ 2× body, tiny upper wick, body in upper third
    body_safe = body.replace(0, np.nan)
    df["Pat_Hammer"] = (
        (lower_wick >= 2.0 * body_safe) &
        (upper_wick <= 0.25 * body_safe)
    ).fillna(False).astype(int)

    # Shooting Star: upper wick ≥ 2× body, tiny lower wick
    df["Pat_ShootingStar"] = (
        (upper_wick >= 2.0 * body_safe) &
        (lower_wick <= 0.25 * body_safe)
    ).fillna(False).astype(int)

    # Marubozu: body ≥ 90% of total range
    marubozu = (body >= 0.90 * total_rng).fillna(False)
    df["Pat_BullMarubozu"] = (marubozu & (c >= o)).astype(int)
    df["Pat_BearMarubozu"] = (marubozu & (c <  o)).astype(int)

    # Bullish Engulfing: prev red → curr green that fully engulfs
    prev_o = o.shift(1)
    prev_c = c.shift(1)
    df["Pat_BullEngulfing"] = (
        (prev_c < prev_o) &   # prev red
        (c      > o     ) &   # curr green
        (c      > prev_o) &   # curr close above prev open
        (o      < prev_c)     # curr open below prev close
    ).fillna(False).astype(int)

    # Bearish Engulfing: prev green → curr red that fully engulfs
    df["Pat_BearEngulfing"] = (
        (prev_c > prev_o) &   # prev green
        (c      < o     ) &   # curr red
        (c      < prev_o) &   # curr close below prev open
        (o      > prev_c)     # curr open above prev close
    ).fillna(False).astype(int)

    # Morning Star (3-candle bullish reversal)
    o2, c2 = o.shift(2), c.shift(2)
    o1, c1 = o.shift(1), c.shift(1)
    body2  = (c2 - o2).abs()
    body1  = (c1 - o1).abs()
    df["Pat_MorningStar"] = (
        (c2 < o2)                &   # bar-2: red
        (body1 < 0.4 * body2)   &   # bar-1: small body (star)
        (c  > o)                &   # bar-0: green
        (c  > (o2 + c2) / 2)        # bar-0 closes above midpoint of bar-2
    ).fillna(False).astype(int)

    # Evening Star (3-candle bearish reversal)
    df["Pat_EveningStar"] = (
        (c2 > o2)                &   # bar-2: green
        (body1 < 0.4 * body2)   &   # bar-1: small body (star)
        (c  < o)                &   # bar-0: red
        (c  < (o2 + c2) / 2)        # bar-0 closes below midpoint of bar-2
    ).fillna(False).astype(int)

    return df


# ─────────────────────────────────────────────────────────────────────────────
# RSI Divergence  (from rsi-divergence skill)
# ─────────────────────────────────────────────────────────────────────────────

def detect_rsi_divergence(df: pd.DataFrame, swing_lookback: int = 20) -> pd.DataFrame:
    """
    Detect bullish and bearish RSI divergence on daily bars.

    Bullish divergence  : price makes new swing low  BUT RSI makes higher low
                          → selling pressure fading, potential reversal up
    Bearish divergence  : price makes new swing high BUT RSI makes lower high
                          → buying pressure fading, potential reversal down

    Only flags divergence when RSI is in a meaningful zone:
        Bullish  — RSI must be < 45 (oversold / approaching oversold)
        Bearish  — RSI must be > 55 (overbought / approaching overbought)
    """
    if "RSI" not in df.columns or len(df) < swing_lookback + 5:
        df["RSI_Bull_Div"] = 0
        df["RSI_Bear_Div"] = 0
        return df

    bull_div = np.zeros(len(df), dtype=int)
    bear_div = np.zeros(len(df), dtype=int)

    prices = df["Close"].values
    rsis   = df["RSI"].values

    for i in range(swing_lookback, len(df)):
        curr_p = prices[i]
        curr_r = rsis[i]
        if np.isnan(curr_r):
            continue

        window_p = prices[i - swing_lookback : i]
        window_r = rsis[i  - swing_lookback : i]

        # Bullish divergence
        if curr_r < 45:
            prev_low_val = float(np.nanmin(window_p))
            if curr_p <= prev_low_val * 1.01:       # price at/near new low
                low_idx  = int(np.nanargmin(window_p))
                rsi_then = window_r[low_idx]
                if not np.isnan(rsi_then) and curr_r > rsi_then + 2:
                    bull_div[i] = 1

        # Bearish divergence
        if curr_r > 55:
            prev_high_val = float(np.nanmax(window_p))
            if curr_p >= prev_high_val * 0.99:      # price at/near new high
                high_idx  = int(np.nanargmax(window_p))
                rsi_then  = window_r[high_idx]
                if not np.isnan(rsi_then) and curr_r < rsi_then - 2:
                    bear_div[i] = 1

    df["RSI_Bull_Div"] = bull_div
    df["RSI_Bear_Div"] = bear_div
    return df


# ─────────────────────────────────────────────────────────────────────────────
# Supertrend  (intraday + delivery — India's most-used trend indicator)
# ─────────────────────────────────────────────────────────────────────────────

def add_supertrend(df: pd.DataFrame, period: int = 10, multiplier: float = 3.0) -> pd.DataFrame:
    """
    Supertrend indicator — ATR-based dynamic support/resistance band.

    Classic settings: period=10, multiplier=3.0 (works for daily and intraday)

    How it works:
        Upper Band = (High+Low)/2 + multiplier × ATR
        Lower Band = (High+Low)/2 − multiplier × ATR
        Supertrend switches direction when price crosses a band.

    Columns added:
        ST_Upper       : raw upper band value
        ST_Lower       : raw lower band value
        Supertrend     : current active support/resistance value
        ST_Direction   : 1 = bullish (price above band), -1 = bearish
        ST_Signal      : +1 = just crossed up (buy), -1 = just crossed down (sell)
    """
    if "ATR" not in df.columns:
        df = add_atr(df, period=period)

    hl2   = (df["High"] + df["Low"]) / 2
    atr   = df["ATR"]
    upper_raw = hl2 + multiplier * atr
    lower_raw = hl2 - multiplier * atr

    # Trailing band arrays
    n           = len(df)
    upper_band  = upper_raw.values.copy()
    lower_band  = lower_raw.values.copy()
    supertrend  = np.zeros(n)
    direction   = np.ones(n, dtype=int)   # 1 = bullish
    close       = df["Close"].values

    for i in range(1, n):
        # Upper band: only move DOWN (tighten)
        if upper_raw.iloc[i] < upper_band[i - 1] or close[i - 1] > upper_band[i - 1]:
            upper_band[i] = upper_raw.iloc[i]
        else:
            upper_band[i] = upper_band[i - 1]

        # Lower band: only move UP (tighten)
        if lower_raw.iloc[i] > lower_band[i - 1] or close[i - 1] < lower_band[i - 1]:
            lower_band[i] = lower_raw.iloc[i]
        else:
            lower_band[i] = lower_band[i - 1]

        # Direction flipping
        prev_st = supertrend[i - 1] if i > 0 else upper_band[0]
        if prev_st == upper_band[i - 1]:          # was bearish
            if close[i] > upper_band[i]:
                direction[i] = 1                   # flipped bullish
                supertrend[i] = lower_band[i]
            else:
                direction[i] = -1
                supertrend[i] = upper_band[i]
        else:                                      # was bullish
            if close[i] < lower_band[i]:
                direction[i] = -1                  # flipped bearish
                supertrend[i] = upper_band[i]
            else:
                direction[i] = 1
                supertrend[i] = lower_band[i]

    # Initialize first bar
    supertrend[0] = upper_band[0]
    direction[0]  = -1

    df["ST_Upper"]     = upper_band
    df["ST_Lower"]     = lower_band
    df["Supertrend"]   = supertrend
    df["ST_Direction"] = direction

    # Signal: +1 on bar where direction flips from -1 to +1, -1 vice versa
    dir_series     = pd.Series(direction, index=df.index)
    df["ST_Signal"] = (dir_series.diff() > 0).astype(int) - (dir_series.diff() < 0).astype(int)
    return df


# ─────────────────────────────────────────────────────────────────────────────
# CPR — Central Pivot Range  (India's #1 intraday framework)
# ─────────────────────────────────────────────────────────────────────────────

def add_pivot_points(df: pd.DataFrame) -> pd.DataFrame:
    """
    Classic Pivot Points + Central Pivot Range (CPR) based on the *previous* bar.

    Works on any timeframe:
        Daily bars   → daily pivots from previous day's OHLC
        Weekly bars  → weekly pivots from previous week
        Intraday bars → pivots shift forward one BAR (approximate daily CPR)

    Levels computed:
        Pivot = (Prev_High + Prev_Low + Prev_Close) / 3
        BC    = (Prev_High + Prev_Low) / 2              ← Bottom of CPR
        TC    = Pivot + (Pivot - BC)                     ← Top of CPR
        R1    = 2 × Pivot − Prev_Low
        R2    = Pivot + (Prev_High − Prev_Low)
        R3    = Prev_High + 2 × (Pivot − Prev_Low)
        S1    = 2 × Pivot − Prev_High
        S2    = Pivot − (Prev_High − Prev_Low)
        S3    = Prev_Low  − 2 × (Prev_High − Pivot)

    Additional columns:
        CPR_Width   : TC − BC  (narrow CPR = directional day, wide = choppy)
        CPR_Width_Pct : CPR_Width / Pivot × 100
        Price_vs_CPR : 'above', 'inside', 'below'
    """
    ph = df["High"].shift(1)
    pl = df["Low"].shift(1)
    pc = df["Close"].shift(1)

    pivot = (ph + pl + pc) / 3
    bc    = (ph + pl) / 2
    tc    = pivot + (pivot - bc)

    df["Pivot"] = pivot
    df["CPR_BC"] = bc
    df["CPR_TC"] = tc
    df["R1"] = 2 * pivot - pl
    df["R2"] = pivot + (ph - pl)
    df["R3"] = ph  + 2 * (pivot - pl)
    df["S1"] = 2 * pivot - ph
    df["S2"] = pivot - (ph - pl)
    df["S3"] = pl   - 2 * (ph - pivot)

    cpr_width = (tc - bc).abs()
    df["CPR_Width"]     = cpr_width
    df["CPR_Width_Pct"] = cpr_width / pivot * 100

    # Classify current close vs CPR band
    close = df["Close"]
    cpr_upper = pd.concat([tc, bc], axis=1).max(axis=1)
    cpr_lower = pd.concat([tc, bc], axis=1).min(axis=1)

    conditions = [
        close > cpr_upper,
        (close >= cpr_lower) & (close <= cpr_upper),
        close < cpr_lower,
    ]
    df["Price_vs_CPR"] = np.select(conditions, ["above", "inside", "below"], default="unknown")
    return df


# ─────────────────────────────────────────────────────────────────────────────
# Fibonacci Retracement Levels  (from fibonacci-trading skill)
# ─────────────────────────────────────────────────────────────────────────────

def add_fibonacci_levels(df: pd.DataFrame, lookback: int = 252) -> pd.DataFrame:
    """
    Fibonacci retracement levels from rolling swing high / swing low.

    Levels are measured as retracement % from swing high toward swing low:

        Fib_23_6 = H − 0.236 × (H − L)   ← shallow pullback
        Fib_38_2 = H − 0.382 × (H − L)   ★ key support / entry zone
        Fib_50_0 = H − 0.500 × (H − L)   ← mid range
        Fib_61_8 = H − 0.618 × (H − L)   ★ golden-ratio support (deepest valid)
        Fib_78_6 = H − 0.786 × (H − L)   ← last-ditch support before new lows

    Price ordering (high → low):
        Fib_23_6 > Fib_38_2 > Fib_50_0 > Fib_61_8 > Fib_78_6

    Two lookbacks are calculated:
        Long  (default 252 bars ≈ 1 year)   → columns  Fib_High, Fib_Low, Fib_*
        Short (50 bars  ≈ 2.5 months)       → columns  Fib50_38_2, Fib50_50_0, Fib50_61_8

    Proximity signals (long-term levels, ±1.5% tolerance):
        Fib_Near_38 : 1 if Close is within 1.5 % of the 38.2 % level
        Fib_Near_62 : 1 if Close is within 1.5 % of the 61.8 % level

    Zone label (long-term):
        Fib_Zone : 'above_23' | '23_38' | '38_50' | '50_62' | '62_78' | 'below_78'
    """
    # ── Long-term swing (major levels) ──────────────────────────────────────
    min_p = max(50, lookback // 5)
    h   = df["High"].rolling(window=lookback, min_periods=min_p).max()
    l   = df["Low"].rolling(window=lookback, min_periods=min_p).min()
    rng = (h - l).replace(0, np.nan)

    df["Fib_High"] = h
    df["Fib_Low"]  = l
    df["Fib_23_6"] = h - 0.236 * rng
    df["Fib_38_2"] = h - 0.382 * rng
    df["Fib_50_0"] = h - 0.500 * rng
    df["Fib_61_8"] = h - 0.618 * rng
    df["Fib_78_6"] = h - 0.786 * rng

    # ── Short-term swing (50-bar pullback levels) ────────────────────────────
    h50  = df["High"].rolling(window=50, min_periods=20).max()
    l50  = df["Low"].rolling(window=50, min_periods=20).min()
    r50  = (h50 - l50).replace(0, np.nan)

    df["Fib50_38_2"] = h50 - 0.382 * r50
    df["Fib50_50_0"] = h50 - 0.500 * r50
    df["Fib50_61_8"] = h50 - 0.618 * r50

    # ── Proximity flags (long-term, ±1.5% band) ─────────────────────────────
    tol = 0.015
    df["Fib_Near_38"] = (
        ((df["Close"] - df["Fib_38_2"]).abs() / df["Fib_38_2"]) <= tol
    ).fillna(False).astype(int)

    df["Fib_Near_62"] = (
        ((df["Close"] - df["Fib_61_8"]).abs() / df["Fib_61_8"]) <= tol
    ).fillna(False).astype(int)

    # ── Zone the current close sits in (long-term) ───────────────────────────
    # Fib_23_6 > Fib_38_2 > Fib_50_0 > Fib_61_8 > Fib_78_6 (price level order)
    conditions = [
        df["Close"] > df["Fib_23_6"],
        (df["Close"] > df["Fib_38_2"]) & (df["Close"] <= df["Fib_23_6"]),
        (df["Close"] > df["Fib_50_0"]) & (df["Close"] <= df["Fib_38_2"]),
        (df["Close"] > df["Fib_61_8"]) & (df["Close"] <= df["Fib_50_0"]),
        (df["Close"] > df["Fib_78_6"]) & (df["Close"] <= df["Fib_61_8"]),
        df["Close"] <= df["Fib_78_6"],
    ]
    zone_labels = ["above_23", "23_38", "38_50", "50_62", "62_78", "below_78"]
    df["Fib_Zone"] = np.select(conditions, zone_labels, default="unknown")

    return df


# ─────────────────────────────────────────────────────────────────────────────
# Legacy signal generators (used by strategies)
# ─────────────────────────────────────────────────────────────────────────────

def rsi_signal(df: pd.DataFrame, oversold: float = 30, overbought: float = 70) -> pd.Series:
    """Returns +1 (buy), -1 (sell), 0 (hold) based on RSI thresholds."""
    signal = pd.Series(0, index=df.index)
    signal[df["RSI"] < oversold]  = 1
    signal[df["RSI"] > overbought] = -1
    return signal


def macd_crossover_signal(df: pd.DataFrame) -> pd.Series:
    """Returns +1 on bullish MACD crossover, -1 on bearish crossover."""
    signal  = pd.Series(0, index=df.index)
    bullish = (df["MACD"] > df["MACD_Signal"]) & (df["MACD"].shift(1) <= df["MACD_Signal"].shift(1))
    bearish = (df["MACD"] < df["MACD_Signal"]) & (df["MACD"].shift(1) >= df["MACD_Signal"].shift(1))
    signal[bullish] = 1
    signal[bearish] = -1
    return signal


def sma_crossover_signal(df: pd.DataFrame, fast: int = 20, slow: int = 50) -> pd.Series:
    """Golden/Death cross: +1 when fast SMA crosses above slow SMA."""
    fast_col, slow_col = f"SMA_{fast}", f"SMA_{slow}"
    if fast_col not in df.columns:
        df = add_moving_averages(df)
    signal = pd.Series(0, index=df.index)
    golden = (df[fast_col] > df[slow_col]) & (df[fast_col].shift(1) <= df[slow_col].shift(1))
    death  = (df[fast_col] < df[slow_col]) & (df[fast_col].shift(1) >= df[slow_col].shift(1))
    signal[golden] = 1
    signal[death]  = -1
    return signal
