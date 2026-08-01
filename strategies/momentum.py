"""
strategies/momentum.py
Simple price momentum strategy.

Logic:
  BUY  when 20-day return > momentum_threshold AND price > SMA_50
  SELL when price falls below SMA_20 OR 5-day momentum turns negative
  Stop-Loss: 1.5× ATR below entry
  Take-Profit: optional, ATR-based (off by default — set atr_tp_mult to enable)

── Fix log (v2) ───────────────────────────────────────────────────────────
- Exit used to re-check the 20-day entry momentum instead of a genuine 5-day
  momentum, contradicting this docstring. Added a real fast momentum
  indicator (`momentum_exit_lookback`) so entry and exit use the windows
  they claim to.
- Removed unused `crossover` import.
- Sizing could still submit a 1-share order when the account couldn't
  actually afford 1 share at the current price (`max(1, min(size, 0))`
  resolves to 1). Now returns instead of submitting an unaffordable order.
- Added optional ATR-based take-profit (`atr_tp_mult`, default None = off,
  preserving the original pure trend-following exit behaviour unless
  explicitly enabled).
────────────────────────────────────────────────────────────────────────────
"""

import numpy as np
import pandas as pd
from backtesting import Strategy


class MomentumStrategy(Strategy):
    momentum_lookback      = 20     # days for entry momentum calculation
    momentum_exit_lookback = 5      # days for exit momentum calculation (matches docstring)
    momentum_threshold     = 0.05   # 5% gain over lookback period to trigger buy
    sma_trend_period  = 50          # must be above this SMA to buy
    sma_exit_period   = 20          # exit when price crosses below this SMA
    atr_period        = 14
    atr_stop_mult      = 1.5
    atr_tp_mult        = None       # e.g. 3.0 to enable an ATR take-profit; None = trend-following exit only
    risk_pct           = 0.02

    def init(self):
        close = pd.Series(self.data.Close)
        high  = pd.Series(self.data.High)
        low   = pd.Series(self.data.Low)

        self.momentum = self.I(
            lambda: close.pct_change(self.momentum_lookback).values, name="Momentum"
        )
        self.momentum_exit = self.I(
            lambda: close.pct_change(self.momentum_exit_lookback).values,
            name=f"Momentum_{self.momentum_exit_lookback}d_Exit",
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
        price         = self.data.Close[-1]
        momentum      = self.momentum[-1]
        momentum_exit = self.momentum_exit[-1]
        sma_trend     = self.sma_trend[-1]
        sma_exit      = self.sma_exit[-1]
        atr           = self.atr[-1]

        if any(np.isnan(v) for v in [momentum, momentum_exit, sma_trend, sma_exit, atr]):
            return

        if not self.position:
            if momentum > self.momentum_threshold and price > sma_trend:
                stop = price - self.atr_stop_mult * atr
                risk_per_share = price - stop
                if risk_per_share <= 0:
                    return

                affordable = int(self.equity / price)
                if affordable < 1:
                    return  # can't afford even 1 share — skip instead of forcing an order

                size = int((self.equity * self.risk_pct) / risk_per_share)
                if size < 1:
                    return  # FIX MOM2: risk-sized qty rounds to 0 — a forced 1-share
                             # trade here would risk more than risk_pct of equity
                size = min(size, affordable)

                tp = price + self.atr_tp_mult * atr if self.atr_tp_mult else None
                self.buy(size=size, sl=stop, tp=tp)

        elif self.position.is_long:
            if price < sma_exit or momentum_exit < 0:
                self.position.close()
