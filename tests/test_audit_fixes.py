"""tests/test_audit_fixes.py — regression cover for the audit fixes.

Each test here pins one specific defect that was found in the codebase and
fixed. They are deliberately written against *reference* behaviour (a
hand-computed value, or a naive re-implementation of the old loop) rather than
against the new code's own output, so they would still fail if the fix were
reverted or reworked incorrectly.

Fix IDs match the comments left at each fix site:
    IND3  utils/indicators.add_atr           — ATR was an SMA, not Wilder's
    IND4  utils/indicators.add_volume_indicators — OBV loop → vectorised
    IND5  utils/indicators.detect_rsi_divergence — per-bar loop → windowed
    SCORE-PAT  analysis/score                — patterns/divergence never computed
    SCORE-NAN  analysis/score._num           — .get() default vs NaN
    TQS-RSI    analysis/trend_quality_score  — fillna(50) hid RSI = 100
    TQS-PERIOD analysis/trend_quality_score  — "6y" silently became 1y
    SIG-52W    trading/signals               — "52-week" scanned whole frame
    CACHE1     data/fetcher                  — unlocked, unbounded price cache
    INTRA1     data/fetcher                  — intraday range map truncated
"""
from __future__ import annotations

import os
import sys
import threading

import numpy as np
import pandas as pd
import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from utils.indicators import (  # noqa: E402
    add_all_indicators,
    add_atr,
    add_rsi,
    add_volume_indicators,
    detect_rsi_divergence,
)


# ─────────────────────────── helpers ───────────────────────────

def _ohlcv(n: int = 300, seed: int = 11, drift: float = 0.4) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 100 + np.cumsum(rng.normal(drift, 1.1, n))
    close = np.maximum(close, 5.0)
    openp = np.concatenate([[close[0]], close[:-1]])
    high = np.maximum(openp, close) * (1 + rng.uniform(0.0, 0.012, n))
    low = np.minimum(openp, close) * (1 - rng.uniform(0.0, 0.012, n))
    vol = rng.integers(400_000, 3_000_000, n).astype(float)
    idx = pd.date_range("2024-01-01", periods=n, freq="B")
    return pd.DataFrame(
        {"Open": openp, "High": high, "Low": low, "Close": close, "Volume": vol},
        index=idx,
    )


def _true_range(df: pd.DataFrame) -> pd.Series:
    return pd.concat(
        [
            df["High"] - df["Low"],
            (df["High"] - df["Close"].shift()).abs(),
            (df["Low"] - df["Close"].shift()).abs(),
        ],
        axis=1,
    ).max(axis=1)


# ─────────────────────── IND3: Wilder's ATR ───────────────────────

def test_atr_uses_wilder_smoothing_not_sma():
    """ATR must follow Wilder's recursion, which is what every broker charts."""
    period = 14
    df = add_atr(_ohlcv(), period=period)
    tr = _true_range(df)

    # Independent reference: seed with the SMA of the first `period` TRs, then
    # ATR_i = (ATR_{i-1} * (period - 1) + TR_i) / period  — TradingView's rma().
    expected = np.full(len(df), np.nan)
    expected[period - 1] = tr.iloc[:period].mean()
    for i in range(period, len(df)):
        expected[i] = (expected[i - 1] * (period - 1) + tr.iloc[i]) / period

    got = df["ATR"].to_numpy()
    assert np.isnan(got[: period - 1]).all(), "warm-up rows must stay NaN"
    np.testing.assert_allclose(got[period - 1:], expected[period - 1:], rtol=1e-9)

    # And it must be genuinely different from the old simple moving average,
    # otherwise this test would pass against the buggy implementation too.
    sma_atr = tr.rolling(period).mean().to_numpy()
    assert not np.allclose(got[period:], sma_atr[period:], rtol=1e-6)


def test_atr_warmup_shape_preserved_for_supertrend_seeding():
    """add_supertrend() locates the first non-NaN band row to seed its
    recursion (FIX IND2c), so ATR's NaN warm-up must keep its old shape."""
    df = add_all_indicators(_ohlcv())
    st_dir = df["ST_Direction"].to_numpy()
    assert set(np.unique(st_dir)) <= {-1, 0, 1}
    assert np.isfinite(df["Supertrend"].iloc[-1]), "Supertrend must resolve, not stay NaN"
    assert (st_dir[-50:] != 0).all(), "no undefined direction long after warm-up"


def test_atr_shorter_than_period_is_all_nan():
    df = add_atr(_ohlcv(n=5), period=14)
    assert df["ATR"].isna().all()


# ─────────────────────── IND4: vectorised OBV ───────────────────────

def test_obv_matches_the_original_loop():
    df = _ohlcv()
    closes = df["Close"].to_numpy()
    vols = df["Volume"].to_numpy()
    reference = [0.0]
    for i in range(1, len(df)):
        if closes[i] > closes[i - 1]:
            reference.append(reference[-1] + vols[i])
        elif closes[i] < closes[i - 1]:
            reference.append(reference[-1] - vols[i])
        else:
            reference.append(reference[-1])

    got = add_volume_indicators(df.copy())["OBV"].to_numpy()
    np.testing.assert_allclose(got, np.array(reference), rtol=1e-12)


def test_volume_ratio_is_nan_not_inf_on_zero_volume_window():
    df = _ohlcv(n=60)
    df.loc[df.index[:40], "Volume"] = 0.0
    out = add_volume_indicators(df)
    assert not np.isinf(out["Volume_Ratio"].to_numpy()).any()


# ─────────────────── IND5: vectorised RSI divergence ───────────────────

def _divergence_reference(df: pd.DataFrame, swing_lookback: int = 20):
    """The original per-bar loop, kept as the oracle for the vectorised form."""
    bull = np.zeros(len(df), dtype=int)
    bear = np.zeros(len(df), dtype=int)
    prices = df["Close"].to_numpy(dtype=float)
    rsis = df["RSI"].to_numpy(dtype=float)
    for i in range(swing_lookback, len(df)):
        curr_p, curr_r = prices[i], rsis[i]
        if np.isnan(curr_r):
            continue
        window_p = prices[i - swing_lookback:i]
        window_r = rsis[i - swing_lookback:i]
        if np.isnan(window_p).all():
            continue
        if curr_r < 45:
            if curr_p <= float(np.nanmin(window_p)) * 1.01:
                rsi_then = window_r[int(np.nanargmin(window_p))]
                if not np.isnan(rsi_then) and curr_r > rsi_then + 2:
                    bull[i] = 1
        if curr_r > 55:
            if curr_p >= float(np.nanmax(window_p)) * 0.99:
                rsi_then = window_r[int(np.nanargmax(window_p))]
                if not np.isnan(rsi_then) and curr_r < rsi_then - 2:
                    bear[i] = 1
    return bull, bear


@pytest.mark.parametrize("seed", [3, 17, 42])
@pytest.mark.parametrize("drift", [0.5, -0.5, 0.0])
def test_rsi_divergence_matches_the_original_loop(seed, drift):
    df = add_rsi(_ohlcv(seed=seed, drift=drift))
    exp_bull, exp_bear = _divergence_reference(df)
    out = detect_rsi_divergence(df.copy())
    np.testing.assert_array_equal(out["RSI_Bull_Div"].to_numpy(), exp_bull)
    np.testing.assert_array_equal(out["RSI_Bear_Div"].to_numpy(), exp_bear)


def test_rsi_divergence_actually_fires_somewhere():
    """Guard against the oracle and the implementation agreeing on all-zeros."""
    total = 0
    for seed in range(1, 25):
        df = add_rsi(_ohlcv(seed=seed, drift=0.0))
        out = detect_rsi_divergence(df)
        total += int(out["RSI_Bull_Div"].sum() + out["RSI_Bear_Div"].sum())
    assert total > 0, "no divergence detected across 24 series — oracle is vacuous"


def test_rsi_divergence_handles_short_and_nan_input():
    short = add_rsi(_ohlcv(n=15))
    out = detect_rsi_divergence(short)
    assert (out["RSI_Bull_Div"] == 0).all() and (out["RSI_Bear_Div"] == 0).all()

    allnan = _ohlcv(n=80)
    allnan["RSI"] = np.nan
    out2 = detect_rsi_divergence(allnan)
    assert (out2["RSI_Bull_Div"] == 0).all() and (out2["RSI_Bear_Div"] == 0).all()


# ─────────────── SCORE-PAT: patterns reach the composite score ───────────────

def test_score_indicator_subset_covers_every_column_the_scorer_reads():
    """The screening subset must produce every column score_dataframe() reads —
    this is the invariant FIX LAZY1 broke when it dropped patterns/divergence."""
    from analysis.score import _SCORE_INDICATOR_GROUPS

    subset = add_all_indicators(_ohlcv(), groups=_SCORE_INDICATOR_GROUPS)
    required = [
        "SMA_20", "SMA_50", "SMA_200", "RSI", "MACD", "MACD_Signal", "MACD_Hist",
        "ADX", "Volume_Ratio", "OBV", "ATR",
        # read by _detect_patterns() — the ones that were silently absent
        "Pat_Doji", "Pat_Hammer", "Pat_ShootingStar", "Pat_BullMarubozu",
        "Pat_BearMarubozu", "Pat_BullEngulfing", "Pat_BearEngulfing",
        "Pat_MorningStar", "Pat_EveningStar", "RSI_Bull_Div", "RSI_Bear_Div",
    ]
    missing = [c for c in required if c not in subset.columns]
    assert not missing, f"screening subset is missing columns the scorer reads: {missing}"


def test_patterns_are_detected_through_the_screening_subset():
    """A frame with a planted bullish engulfing must surface it in the score."""
    from analysis.score import score_dataframe, _SCORE_INDICATOR_GROUPS

    df = _ohlcv()
    # Plant an unambiguous bullish engulfing on the final bar: previous bar red,
    # current bar green and fully engulfing it.
    prev_i, cur_i = df.index[-2], df.index[-1]
    df.loc[prev_i, ["Open", "Close"]] = [110.0, 100.0]
    df.loc[prev_i, ["High", "Low"]] = [111.0, 99.0]
    df.loc[cur_i, ["Open", "Close"]] = [99.0, 112.0]
    df.loc[cur_i, ["High", "Low"]] = [113.0, 98.0]

    enriched = add_all_indicators(df, groups=_SCORE_INDICATOR_GROUPS)
    result = score_dataframe(enriched, ticker="TEST.NS", sector="Other")
    assert "BullEngulfing" in result.patterns_detected, (
        f"planted pattern not surfaced; got {result.patterns_detected}"
    )


# ─────────────────── SCORE-NAN: NaN vs missing in .get() ───────────────────

def test_num_helper_falls_back_on_nan_as_well_as_missing():
    from analysis.score import _num

    row = pd.Series({"present": 5.0, "nan_valued": np.nan, "texty": "abc"})
    assert _num(row, "present", 1.0) == 5.0
    assert _num(row, "absent", 1.0) == 1.0
    assert _num(row, "nan_valued", 1.0) == 1.0, "NaN must use the default, not propagate"
    assert _num(row, "texty", 1.0) == 1.0


def test_sma_stack_not_penalised_when_sma200_is_still_warming_up():
    """A short-history stock in a clean uptrend must not be scored the same as
    one genuinely trading below its 200-day average."""
    from analysis.score import _score_technical

    df = add_all_indicators(_ohlcv(n=120, drift=0.9))   # < 200 bars → SMA_200 NaN
    assert df["SMA_200"].isna().all(), "precondition: SMA_200 has no valid value yet"

    _, detail = _score_technical(df)
    assert detail["sma"] > 0.0, (
        "SMA stack scored 0/10 purely because SMA_200 was NaN — the documented "
        "price*0.80 fallback never applied"
    )


def test_missing_60d_history_is_neutral_not_penalised():
    """Under 60 bars, the 3-month momentum component must score the neutral
    midpoint. It used to fall through to the `r60d > -10` branch (1.0/10) —
    scoring "no data" identically to "down over 3 months"."""
    from analysis.score import _score_momentum

    short = _ohlcv(n=45, drift=0.8)      # >= 25 bars, < 61 bars
    pts_short, detail_short = _score_momentum(short)
    assert detail_short["r60d_available"] is False
    assert detail_short["_r60d"] is None
    assert detail_short["r60d"] == pytest.approx(5.0), (
        "absent 3-month history must score neutral, not near-zero"
    )

    # A genuinely flat-to-down 3-month record must still be scored low, so the
    # neutral default can't be reached by real weakness.
    falling = _ohlcv(n=200, drift=-0.8)
    _, detail_fall = _score_momentum(falling)
    assert detail_fall["r60d_available"] is True
    assert detail_fall["r60d"] <= 1.0


def test_narrative_does_not_print_a_fake_zero_for_missing_60d():
    from analysis.score import score_dataframe

    df = add_all_indicators(_ohlcv(n=45, drift=1.2))
    res = score_dataframe(df, ticker="NEWLISTING.NS", sector="Other")
    assert "0.0% over 3 months" not in res.narrative
    assert isinstance(res.narrative, str) and res.narrative


# ─────────────────────── TQS-RSI / TQS-PERIOD ───────────────────────

def test_tqs_rsi_returns_100_when_there_are_no_down_days():
    from analysis.trend_quality_score import _compute_rsi

    close = pd.Series(np.arange(100, 160, dtype=float))   # strictly rising
    rsi = _compute_rsi(close, period=14)
    assert rsi.iloc[:13].isna().all(), "warm-up must be NaN, not a confident 50"
    assert rsi.iloc[-1] == pytest.approx(100.0), (
        "a series with zero down-days must read RSI 100 (maximally overbought), "
        "not the neutral 50 the old fillna produced"
    )


def test_tqs_rsi_flat_series_is_neutral_and_matches_indicators_module():
    from analysis.trend_quality_score import _compute_rsi

    flat = pd.Series([50.0] * 40)
    assert _compute_rsi(flat, period=14).iloc[-1] == pytest.approx(50.0)

    # The two RSI implementations in the repo must now agree bar for bar.
    df = _ohlcv()
    a = add_rsi(df.copy(), period=14)["RSI"]
    b = _compute_rsi(df["Close"], period=14)
    pd.testing.assert_series_equal(a, b, check_names=False, rtol=1e-9)


@pytest.mark.parametrize("requested", ["1y", "2y", "5y"])
def test_tqs_padded_period_is_one_the_fetcher_actually_understands(monkeypatch, requested):
    """Whatever period score_ticker() pads to must resolve to a real, long
    window in BOTH data sources. "6y" resolved in neither: it fell through to
    _period_to_dates()'s 370-day default and _RANGE_MAP's "1y" default, so a
    5-year TQS silently ran on one year of bars."""
    import datetime
    import inspect

    import analysis.trend_quality_score as tqs
    from data.fetcher import _period_to_dates, _fetch_yahoo_direct

    seen = {}

    def _fake_fetch(ticker, period="5y"):
        seen["period"] = period
        return _ohlcv(n=700)

    monkeypatch.setattr(tqs, "fetch_data", _fake_fetch)
    tqs.score_ticker("TEST.NS", period=requested)
    padded = seen["period"]

    # Stooq path: the date window the padded period resolves to must be long.
    d1, d2 = _period_to_dates(padded)
    span = (datetime.datetime.strptime(d2, "%Y%m%d")
            - datetime.datetime.strptime(d1, "%Y%m%d")).days
    assert span > 700, (
        f"{requested!r} padded to {padded!r}, which the Stooq path resolves to "
        f"only {span} days — the padding is being silently discarded"
    )

    # Yahoo path: the padded period must be a real key, not fall to the default.
    src = inspect.getsource(_fetch_yahoo_direct)
    body = src[src.index("_RANGE_MAP"): src.index("}", src.index("_RANGE_MAP")) + 1]
    ns: dict = {}
    exec(body, ns)
    assert padded.lower() in ns["_RANGE_MAP"], (
        f"{requested!r} padded to {padded!r}, which _RANGE_MAP has no entry for — "
        f"it silently falls back to a 1-year range"
    )


# ─────────────────────── SIG-52W: real 52-week window ───────────────────────

def _signal_frame(n: int) -> pd.DataFrame:
    df = add_all_indicators(_ohlcv(n=n, drift=0.0, seed=5))
    return df.dropna(subset=["RSI", "ATR"])


def test_breakout_52w_high_ignores_history_older_than_252_bars():
    """An all-time high 3 years back must not gate a 52-week breakout."""
    from trading.signals import check_breakout, _52W_BARS

    assert _52W_BARS == 252
    df = _signal_frame(900)
    # Spike far above everything, well outside the trailing 252-bar window.
    df.loc[df.index[100], "High"] = float(df["High"].max()) * 5

    recent_high = float(df["High"].tail(_52W_BARS).max())
    whole_frame_high = float(df["High"].max())
    assert whole_frame_high > recent_high * 2, "precondition: old spike dominates"

    # Put price right at the 252-bar high with confirming volume/trend so only
    # the window choice decides whether the screen can fire.
    last = df.index[-1]
    df.loc[last, "Close"] = recent_high
    df.loc[last, "High"] = recent_high
    df.loc[last, "Volume_Ratio"] = 2.0
    df.loc[last, "ADX"] = 30.0
    df.loc[last, "RSI"] = 60.0

    sig = check_breakout(df)
    assert sig is not None, (
        "breakout suppressed by a 3-year-old high — the window is not 52 weeks"
    )
    assert sig["pct_from_52h"] == pytest.approx(0.0, abs=0.01)


def test_oversold_bounce_52w_low_ignores_history_older_than_252_bars():
    from trading.signals import check_oversold_bounce, _52W_BARS

    df = _signal_frame(900)
    df.loc[df.index[100], "Low"] = 0.01   # ancient crash low, outside the window

    last = df.index[-1]
    window_low = float(df["Low"].tail(_52W_BARS).min())
    df.loc[last, "Close"] = window_low * 1.001   # ~0.1% above the 52-week low
    df.loc[last, "RSI"] = 25.0
    df.loc[last, "Volume_Ratio"] = 1.0

    # Measured from the real 52-week low this is only ~0.1% up, so the 3%
    # floor must reject it. Measured from the ancient 0.01 low it would look
    # like a gain of thousands of percent and sail through.
    assert check_oversold_bounce(df) is None


# ─────────────────────── CACHE1 / INTRA1: fetcher ───────────────────────

def test_fetch_cache_is_bounded_and_evicts():
    import data.fetcher as f

    f.clear_fetch_cache()
    try:
        now = 1_000_000.0
        for i in range(f._FETCH_CACHE_MAX + 250):
            f._cache_put((f"T{i}.NS", "1y", "1d"), pd.DataFrame({"Close": [1.0]}), now + i)
        assert len(f._FETCH_CACHE) <= f._FETCH_CACHE_MAX
        # Newest entries survive; the oldest are the ones evicted.
        newest = (f"T{f._FETCH_CACHE_MAX + 249}.NS", "1y", "1d")
        assert newest in f._FETCH_CACHE
        assert ("T0.NS", "1y", "1d") not in f._FETCH_CACHE
    finally:
        f.clear_fetch_cache()


def test_fetch_cache_expiry_is_race_safe():
    """Concurrent expiry of the same key must not raise (the old check-then-del
    let the losing thread hit KeyError, dropping that ticker from the batch)."""
    import data.fetcher as f

    f.clear_fetch_cache()
    try:
        key = ("RACE.NS", "1y", "1d")
        stale = 1_000.0
        f._cache_put(key, pd.DataFrame({"Close": [1.0]}), stale)
        expired_at = stale + f._FETCH_CACHE_TTL + 1

        errors = []
        barrier = threading.Barrier(16)

        def _worker():
            try:
                barrier.wait(timeout=10)
                f._cache_get(key, expired_at)
            except Exception as e:      # pragma: no cover — the bug being pinned
                errors.append(e)

        threads = [threading.Thread(target=_worker) for _ in range(16)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15)

        assert not errors, f"concurrent expiry raised: {errors}"
        assert key not in f._FETCH_CACHE
    finally:
        f.clear_fetch_cache()


def test_fetch_cache_get_returns_live_entry_and_drops_expired():
    import data.fetcher as f

    f.clear_fetch_cache()
    try:
        key = ("LIVE.NS", "1y", "1d")
        t0 = 500.0
        f._cache_put(key, pd.DataFrame({"Close": [7.0]}), t0)
        assert f._cache_get(key, t0 + 1) is not None
        assert f._cache_get(key, t0 + f._FETCH_CACHE_TTL + 1) is None
    finally:
        f.clear_fetch_cache()


def test_intraday_range_map_covers_the_requested_span():
    """Every intraday period key must map to a Yahoo range that is real AND at
    least as long as the span the caller asked for."""
    import inspect
    import data.fetcher as f

    src = inspect.getsource(f._fetch_yahoo_direct)
    ns: dict = {}
    exec(src[src.index("_RANGE_MAP"): src.index("}", src.index("_RANGE_MAP")) + 1], ns)
    range_map = ns["_RANGE_MAP"]

    yahoo_ranges = {"1d": 1, "5d": 5, "1mo": 30, "3mo": 90, "6mo": 180,
                    "1y": 365, "2y": 730, "5y": 1825, "10y": 3650,
                    "ytd": 365, "max": 100_000}
    for key, days in {"7d": 7, "15d": 15, "30d": 30, "60d": 60}.items():
        mapped = range_map[key]
        assert mapped in yahoo_ranges, f"{key!r} maps to {mapped!r}, not a real Yahoo range"
        assert yahoo_ranges[mapped] >= days, (
            f"{key!r} maps to {mapped!r} which is shorter than the {days} days requested"
        )


# ─────────────── TU-HOL: one holiday calendar, not two divergent ones ───────────────

def test_squareoff_holiday_list_matches_the_canonical_calendar():
    """trade_utils kept its own hand-maintained NSE holiday set, which had
    drifted to miss 8 of 2026's 16 closures — including four still ahead. The
    square-off guard consults THIS set, so a gap here means auto-close can run
    against stale prices on a day the exchange is shut."""
    import datetime as _dt

    from dashboard.shared.market_hours import NSE_HOLIDAYS
    from dashboard.shared.trade_utils import _NSE_HOLIDAYS_FALLBACK

    canonical = {
        _dt.date.fromisoformat(d) if isinstance(d, str) else d
        for d in NSE_HOLIDAYS
    }
    missing = canonical - set(_NSE_HOLIDAYS_FALLBACK)
    assert not missing, f"square-off calendar is missing NSE closures: {sorted(missing)}"

    # The specific dates that were absent, spelled out so a future hand-edit
    # that reintroduces a partial copy fails loudly.
    for d in [_dt.date(2026, 3, 26), _dt.date(2026, 3, 31), _dt.date(2026, 5, 28),
              _dt.date(2026, 6, 26), _dt.date(2026, 9, 14), _dt.date(2026, 10, 20),
              _dt.date(2026, 11, 10), _dt.date(2026, 11, 24)]:
        assert d in _NSE_HOLIDAYS_FALLBACK, f"{d} missing from the square-off calendar"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
