import vectorbt as vbt
import numpy as np
import pandas as pd

def get_rsi_signals(close_price, length=14, oversold=30, overbought=70):
    """RSI Mean Reversion Strategy"""
    rsi = vbt.RSI.run(close_price, window=length).rsi
    entries = rsi.vbt.crossed_below(oversold)
    exits = rsi.vbt.crossed_above(overbought)
    return entries, exits

def get_bb_signals(close_price, window=20, std=2.0):
    """Bollinger Band Mean Reversion"""
    # Manual calculation to avoid factory bugs
    ma = vbt.MA.run(close_price, window=window).ma
    rolling_std = close_price.rolling(window=window).std()
    upper_band = ma + (rolling_std * std)
    lower_band = ma - (rolling_std * std)

    entries = close_price.vbt.crossed_below(lower_band)
    exits = close_price.vbt.crossed_above(ma)
    return entries, exits

def get_sma_signals(close_price, fast_window=50, slow_window=200):
    """SMA Trend Following"""
    fast_ma = vbt.MA.run(close_price, window=fast_window).ma
    slow_ma = vbt.MA.run(close_price, window=slow_window).ma

    entries = fast_ma.vbt.crossed_above(slow_ma)
    exits = fast_ma.vbt.crossed_below(slow_ma)
    return entries, exits

def get_macd_signals(close_price, fast=12, slow=26, signal=9):
    """MACD Momentum Strategy"""
    macd = vbt.MACD.run(close_price, fast_window=fast, slow_window=slow, signal_window=signal)

    # Entry: MACD line crosses above Signal line
    entries = macd.macd_crossed_above(macd.signal)

    # Exit: MACD line crosses below Signal line
    exits = macd.macd_crossed_below(macd.signal)
    return entries, exits

def get_rsi_trend_signals(close_price, rsi_len=14, sma_len=200):
    """
    RSI + Trend Filter (Regime Detection).
    Only buy oversold RSI if price is ABOVE the long-term SMA.
    """
    rsi = vbt.RSI.run(close_price, window=rsi_len).rsi
    sma = vbt.MA.run(close_price, window=sma_len).ma

    # Condition 1: RSI is oversold (< 30)
    cond_oversold = rsi < 30

    # Condition 2: Trend is Up (Price > SMA)
    cond_uptrend = close_price > sma

    # Entry: Both must be true. We use crossed_below on the threshold to trigger the event
    # but filter it by the trend.
    entries = rsi.vbt.crossed_below(30) & cond_uptrend

    # Exit: RSI crosses back above 70
    exits = rsi.vbt.crossed_above(70)

    return entries, exits
