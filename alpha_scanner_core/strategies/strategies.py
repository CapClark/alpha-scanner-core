import vectorbt as vbt
import numpy as np
import pandas as pd

def get_rsi_signals(close_price, length=14, oversold=30, overbought=70):
    """RSI Mean Reversion Strategy"""
    rsi = vbt.RSI.run(close_price, window=length).rsi

    # FIX: Handle NaNs explicitly
    entries = rsi.vbt.crossed_below(oversold).fillna(False)
    exits = rsi.vbt.crossed_above(overbought).fillna(False)

    return entries, exits

def get_bb_signals(data: pd.Series, window: int = 20, std: float = 2.0):
    """
    Returns Bollinger Bands entries/exits as boolean arrays.
    """

    if isinstance(data, pd.DataFrame):
        # Use 'Close' column if DataFrame
        close = data['Close']
    else:
        close = data

    # Moving Average
    ma = close.rolling(window=window, min_periods=1).mean()

    # Rolling Standard Deviation
    rolling_std = close.rolling(window=window, min_periods=1).std().fillna(0)

    # Upper and Lower Bands
    upper_band = ma + (rolling_std * std)
    lower_band = ma - (rolling_std * std)

    # Entry / Exit signals
    entries = close < lower_band   # Buy when price crosses below lower band
    exits = close > upper_band     # Sell when price crosses above upper band

    # Return as NumPy arrays
    return entries.values, exits.values

def get_sma_signals(close_price, fast_window=50, slow_window=200):
    """SMA Trend Following Strategy"""
    fast_ma = vbt.MA.run(close_price, window=fast_window).ma
    slow_ma = vbt.MA.run(close_price, window=slow_window).ma

    # FIX: Handle NaNs explicitly
    entries = fast_ma.vbt.crossed_above(slow_ma).fillna(False)
    exits = fast_ma.vbt.crossed_below(slow_ma).fillna(False)

    return entries, exits

def get_macd_signals(close_price, fast=12, slow=26, signal=9):
    """MACD Momentum Strategy"""
    macd_ind = vbt.MACD.run(close_price, fast_window=fast, slow_window=slow, signal_window=signal)

    # FIX: Handle NaNs explicitly
    entries = macd_ind.macd.vbt.crossed_above(macd_ind.signal).fillna(False)
    exits = macd_ind.macd.vbt.crossed_below(macd_ind.signal).fillna(False)

    return entries, exits

def get_rsi_trend_signals(close_price, rsi_len=14, sma_len=200):
    """RSI + Trend Filter"""
    rsi = vbt.RSI.run(close_price, window=rsi_len).rsi
    sma = vbt.MA.run(close_price, window=sma_len).ma

    cond_uptrend = (close_price > sma).fillna(False)
    rsi_cross_below = rsi.vbt.crossed_below(30).fillna(False)

    entries = rsi_cross_below & cond_uptrend
    exits = rsi.vbt.crossed_above(70).fillna(False)

    return entries, exits