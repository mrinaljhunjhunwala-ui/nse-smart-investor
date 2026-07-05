"""
strategies/rsi_macd.py
Combined RSI + MACD strategy using the `backtesting.py` library.

Logic:
  BUY  when RSI < 35 (oversold) AND MACD crosses above Signal line
  SELL when RSI > 65 (overbought) OR MACD crosses below Signal line
  Stop-Loss: 2× ATR below entry
  Take-Profit: 3× ATR above entry  (R:R = 1:1.5)

── Fix log (v2) ───────────────────────────────────────────────────────────
- `avg_loss.replace(0, np.nan)` was meant to avoid a divide-by-zero, but
  during a strong uptrend avg_loss legitimately reaches exactly 0, so the
  division produced NaN instead of the correct RSI of 100 — and `next()`
  returns early on NaN RSI, so the strategy went silent exactly during its
  strongest trends. Now avg_loss == 0 is mapped explicitly to RSI 100
  (or 50 in the degenerate flat-price case where avg_gain is also 0).
- Sizing could still submit a 1-share order the account couldn't afford
  (`max(1, min(size, 0))` resolves to 1). Now returns instead.
────────────────────────────────────────────────────────────────────────────
"""

import pandas as pd
import numpy as np
from backtesting import Strategy
from backtesting.lib import crossover


class RSIMACDStrategy(Strategy):
    # ── Tunable parameters (optimisable via bt.optimize()) ───────────────────
    rsi_period   = 14
    rsi_oversold  = 35
    rsi_overbought = 65
    macd_fast    = 12
    macd_slow    = 26
    macd_signal  = 9
    atr_period   = 14
    atr_stop_mult  = 2.0   # stop-loss = entry - atr_stop_mult × ATR
    atr_tp_mult    = 3.0   # take-profit = entry + atr_tp_mult × ATR
    risk_pct       = 0.02  # risk 2% of equity per trade

    def init(self):
        close = pd.Series(self.data.Close)
        high  = pd.Series(self.data.High)
        low   = pd.Series(self.data.Low)

        # RSI
        delta = close.diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)
        avg_gain = gain.ewm(alpha=1/self.rsi_period, min_periods=self.rsi_period, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1/self.rsi_period, min_periods=self.rsi_period, adjust=False).mean()
        rs = avg_gain / avg_loss.replace(0, np.nan)
        rsi_vals = 100 - (100 / (1 + rs))
        rsi_vals = rsi_vals.where(avg_loss != 0, 100.0)                          # no down-days → RSI 100, not NaN
        rsi_vals = rsi_vals.where(~((avg_gain == 0) & (avg_loss == 0)), 50.0)    # flat price → RSI 50
        self.rsi = self.I(lambda: rsi_vals.values, name="RSI")

        # MACD
        ema_fast = close.ewm(span=self.macd_fast, adjust=False).mean()
        ema_slow = close.ewm(span=self.macd_slow, adjust=False).mean()
        macd_line   = ema_fast - ema_slow
        signal_line = macd_line.ewm(span=self.macd_signal, adjust=False).mean()
        self.macd   = self.I(lambda: macd_line.values, name="MACD")
        self.macd_sig = self.I(lambda: signal_line.values, name="MACD_Signal")

        # ATR
        hl = high - low
        hc = (high - close.shift()).abs()
        lc = (low  - close.shift()).abs()
        tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
        self.atr = self.I(lambda: tr.rolling(self.atr_period).mean().values, name="ATR")

    def next(self):
        rsi = self.rsi[-1]
        atr = self.atr[-1]
        price = self.data.Close[-1]

        if np.isnan(rsi) or np.isnan(atr):
            return

        # ── Entry: long only ─────────────────────────────────────────────────
        if not self.position:
            macd_cross_up = crossover(self.macd, self.macd_sig)
            if rsi < self.rsi_oversold and macd_cross_up:
                stop  = price - self.atr_stop_mult * atr
                tp    = price + self.atr_tp_mult * atr
                # Size = risk_pct of equity ÷ risk per share
                risk_per_share = price - stop
                if risk_per_share <= 0:
                    return

                affordable = int(self.equity / price)
                if affordable < 1:
                    return  # can't afford even 1 share — skip instead of forcing an order

                size = int((self.equity * self.risk_pct) / risk_per_share)
                size = max(1, min(size, affordable))
                self.buy(size=size, sl=stop, tp=tp)

        # ── Exit ─────────────────────────────────────────────────────────────
        elif self.position.is_long:
            macd_cross_down = crossover(self.macd_sig, self.macd)
            if rsi > self.rsi_overbought or macd_cross_down:
                self.position.close()
