"""
strategies/momentum.py
Simple price momentum strategy.

Logic:
  BUY  when 20-day return > momentum_threshold AND price > SMA_50
  SELL when price falls below SMA_20 OR 5-day momentum turns negative
  Stop-Loss: 1.5× ATR below entry
"""

import numpy as np
import pandas as pd
from backtesting import Strategy
from backtesting.lib import crossover


class MomentumStrategy(Strategy):
    momentum_lookback = 20      # days for momentum calculation
    momentum_threshold = 0.05   # 5% gain over lookback period to trigger buy
    sma_trend_period  = 50      # must be above this SMA to buy
    sma_exit_period   = 20      # exit when price crosses below this SMA
    atr_period        = 14
    atr_stop_mult     = 1.5
    risk_pct          = 0.02

    def init(self):
        close = pd.Series(self.data.Close)
        high  = pd.Series(self.data.High)
        low   = pd.Series(self.data.Low)

        self.momentum = self.I(
            lambda: close.pct_change(self.momentum_lookback).values, name="Momentum"
        )
        self.sma_trend = self.I(
            lambda: close.rolling(self.sma_trend_period).mean().values, name=f"SMA_{self.sma_trend_period}"
        )
        self.sma_exit = self.I(
            lambda: close.rolling(self.sma_exit_period).mean().values, name=f"SMA_{self.sma_exit_period}"
        )
        hl = high - low
        hc = (high - close.shift()).abs()
        lc = (low  - close.shift()).abs()
        tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
        self.atr = self.I(lambda: tr.rolling(self.atr_period).mean().values, name="ATR")

    def next(self):
        price    = self.data.Close[-1]
        momentum = self.momentum[-1]
        sma_trend= self.sma_trend[-1]
        sma_exit = self.sma_exit[-1]
        atr      = self.atr[-1]

        if any(np.isnan(v) for v in [momentum, sma_trend, sma_exit, atr]):
            return

        if not self.position:
            if momentum > self.momentum_threshold and price > sma_trend:
                stop = price - self.atr_stop_mult * atr
                risk_per_share = price - stop
                if risk_per_share <= 0:
                    return
                size = int((self.equity * self.risk_pct) / risk_per_share)
                size = max(1, min(size, int(self.equity / price)))
                self.buy(size=size, sl=stop)

        elif self.position.is_long:
            if price < sma_exit or momentum < 0:
                self.position.close()
