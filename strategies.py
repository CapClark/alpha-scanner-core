import vectorbt as vbt
import numpy as np
import pandas as pd

def get_rsi_signals(close_price, length=14, oversold=30, overbought=70):
    """RSI Mean Reversion Strategy"""
    rsi = vbt.RSI.run(close_price, window=length).rsi

    # Entry: RSI crosses below oversold
    entries = rsi.vbt.crossed_below(oversold)

    # Exit: RSI crosses above overbought
    exits = rsi.vbt.crossed_above(overbought)

    return entries, exits

def get_bb_signals(close_price, window=20, std=2.0):
    """
    Bollinger Band Mean Reversion Strategy.
    MANUAL CALCULATION FIX: This calculates bands using raw pandas math
    to avoid the 'TypeError: expected 6, got 7' bug in vectorbt's wrapper.
    """
    # 1. Calculate Simple Moving Average (Middle Band)
    # We use vbt.MA because it handles caching efficiently
    ma = vbt.MA.run(close_price, window=window).ma

    # 2. Calculate Standard Deviation manually using Pandas
    # (VectorBT series are Pandas objects, so this works natively)
    rolling_std = close_price.rolling(window=window).std()

    # 3. Calculate Upper and Lower Bands
    upper_band = ma + (rolling_std * std)
    lower_band = ma - (rolling_std * std)

    # Entry: Price crosses below Lower Band
    entries = close_price.vbt.crossed_below(lower_band)

    # Exit: Price crosses above Middle Band (Mean Reversion)
    exits = close_price.vbt.crossed_above(ma)

    return entries, exits

def get_sma_signals(close_price, fast_window=50, slow_window=200):
    """SMA Trend Following Strategy"""
    fast_ma = vbt.MA.run(close_price, window=fast_window).ma
    slow_ma = vbt.MA.run(close_price, window=slow_window).ma

    # Entry: Fast crosses above Slow
    entries = fast_ma.vbt.crossed_above(slow_ma)

    # Exit: Fast crosses below Slow
    exits = fast_ma.vbt.crossed_below(slow_ma)

    return entries, exits
