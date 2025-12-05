import vectorbt as vbt
import numpy as np

def get_rsi_signals(close_price, length=14, oversold=30, overbought=70):
    """RSI Mean Reversion Strategy"""
    rsi = vbt.RSI.run(close_price, window=length).rsi

    # Entry: RSI crosses below oversold
    entries = rsi.vbt.crossed_below(oversold)
    # Exit: RSI crosses above overbought
    exits = rsi.vbt.crossed_above(overbought)

    return entries, exits

def get_bb_signals(close_price, window=20, std=2.0):
    """Bollinger Band Mean Reversion Strategy"""
    # Manual calculation to avoid vectorbt wrapper bugs
    ma = vbt.MA.run(close_price, window=window).ma
    rolling_std = close_price.rolling(window=window).std()

    lower_band = ma - (rolling_std * std)

    # Entry: Price < Lower Band
    entries = close_price.vbt.crossed_below(lower_band)
    # Exit: Price > Moving Average
    exits = close_price.vbt.crossed_above(ma)

    return entries, exits
