import vectorbt as vbt
import numpy as np
import pandas as pd

def get_rsi_signals(close_price, length=14, oversold=30, overbought=70):
    """RSI Mean Reversion Strategy"""
    rsi = vbt.RSI.run(close_price, window=length).rsi
    
    # Entry: RSI crosses below oversold
    entries = rsi.vbt.crossed_below(oversold).fillna(False)
    
    # Exit: RSI crosses above overbought
    exits = rsi.vbt.crossed_above(overbought).fillna(False)
    
    return entries, exits

def get_bb_signals(close_price, window=20, std=2.0):
    """
    Bollinger Band Mean Reversion Strategy.
    Manual calculation to avoid factory bugs.
    """
    ma = vbt.MA.run(close_price, window=window).ma
    rolling_std = close_price.rolling(window=window).std()
    
    upper_band = ma + (rolling_std * std)
    lower_band = ma - (rolling_std * std)
    
    # Entry: Price crosses below Lower Band
    entries = close_price.vbt.crossed_below(lower_band).fillna(False)
    
    # Exit: Price crosses above Middle Band
    exits = close_price.vbt.crossed_above(ma).fillna(False)
    
    return entries, exits

def get_sma_signals(close_price, fast_window=50, slow_window=200):
    """SMA Trend Following Strategy"""
    fast_ma = vbt.MA.run(close_price, window=fast_window).ma
    slow_ma = vbt.MA.run(close_price, window=slow_window).ma
    
    # Entry: Fast crosses above Slow
    entries = fast_ma.vbt.crossed_above(slow_ma).fillna(False)
    
    # Exit: Fast crosses below Slow
    exits = fast_ma.vbt.crossed_below(slow_ma).fillna(False)
    
    return entries, exits

def get_macd_signals(close_price, fast=12, slow=26, signal=9):
    """MACD Momentum Strategy"""
    macd_ind = vbt.MACD.run(close_price, fast_window=fast, slow_window=slow, signal_window=signal)
    
    # Entry: MACD line crosses above Signal line
    entries = macd_ind.macd.vbt.crossed_above(macd_ind.signal).fillna(False)
    
    # Exit: MACD line crosses below Signal line
    exits = macd_ind.macd.vbt.crossed_below(macd_ind.signal).fillna(False)
    
    return entries, exits

def get_rsi_trend_signals(close_price, rsi_len=14, sma_len=200):
    """
    RSI + Trend Filter (Regime Detection).
    Only buy oversold RSI if price is ABOVE the long-term SMA.
    """
    rsi = vbt.RSI.run(close_price, window=rsi_len).rsi
    sma = vbt.MA.run(close_price, window=sma_len).ma
    
    # Condition 1: RSI is oversold (< 30)
    # We use .fillna(False) to handle the start of the series where RSI is NaN
    cond_oversold = (rsi < 30).fillna(False)
    
    # Condition 2: Trend is Up (Price > SMA)
    # We use .fillna(False) because SMA is NaN for the first 200 days
    cond_uptrend = (close_price > sma).fillna(False)
    
    # Entry: RSI crosses below 30 AND Price is above SMA
    # We use the crossover event for RSI, but check the state for Trend
    rsi_cross_below = rsi.vbt.crossed_below(30).fillna(False)
    
    entries = rsi_cross_below & cond_uptrend
    
    # Exit: RSI crosses back above 70
    exits = rsi.vbt.crossed_above(70).fillna(False)
    
    return entries, exits