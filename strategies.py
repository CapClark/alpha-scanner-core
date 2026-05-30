"""
Main trading strategies.
Each strategy takes a close price Series and returns (entries, exits) boolean Series.
"""
import vectorbt as vbt
import pandas as pd


# ── Individual strategies ──────────────────────────────────────────────────────

def rsi_mean_reversion(close: pd.Series, window: int = 14,
                        oversold: int = 30, overbought: int = 70):
    """Buy when RSI crosses below oversold; sell when it crosses above overbought."""
    rsi = vbt.RSI.run(close, window=window)
    entries = rsi.rsi_crossed_below(oversold)
    exits   = rsi.rsi_crossed_above(overbought)
    return entries, exits


def macd_crossover(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    """Buy when MACD line crosses above signal line; sell when it crosses below."""
    macd = vbt.MACD.run(close, fast_window=fast, slow_window=slow, signal_window=signal)
    entries = macd.macd_crossed_above(macd.signal)
    exits   = macd.macd_crossed_below(macd.signal)
    return entries, exits


def bollinger_bands(close: pd.Series, window: int = 20, alpha: float = 2.0):
    """Buy when price closes below lower band; sell when it closes above upper band."""
    bb      = vbt.BBANDS.run(close, window=window, alpha=alpha)
    entries = close < bb.lower
    exits   = close > bb.upper
    return entries, exits


def ma_crossover(close: pd.Series, fast: int = 50, slow: int = 200):
    """Buy when fast MA crosses above slow MA; sell when it crosses below."""
    fast_ma = vbt.MA.run(close, window=fast, short_name="fast")
    slow_ma = vbt.MA.run(close, window=slow, short_name="slow")
    entries = fast_ma.ma_crossed_above(slow_ma.ma)
    exits   = fast_ma.ma_crossed_below(slow_ma.ma)
    return entries, exits


def rsi_with_trend(close: pd.Series, rsi_window: int = 14, trend_window: int = 200,
                   oversold: int = 30, overbought: int = 70):
    """RSI mean reversion filtered to only trade in the direction of the 200-day trend."""
    rsi      = vbt.RSI.run(close, window=rsi_window)
    trend_ma = vbt.MA.run(close, window=trend_window)
    trend_up = close > trend_ma.ma
    entries  = rsi.rsi_crossed_below(oversold) & trend_up
    exits    = rsi.rsi_crossed_above(overbought)
    return entries, exits


def mean_reversion_bb_rsi(close: pd.Series, bb_window: int = 20, rsi_window: int = 14,
                           alpha: float = 2.0, oversold: int = 30, overbought: int = 70):
    """Combined: enter when price is below lower BB AND RSI is oversold."""
    bb      = vbt.BBANDS.run(close, window=bb_window, alpha=alpha)
    rsi     = vbt.RSI.run(close, window=rsi_window)
    entries = (close < bb.lower) & (rsi.rsi < oversold)
    exits   = (close > bb.upper) | (rsi.rsi > overbought)
    return entries, exits


# ── Strategy registry ──────────────────────────────────────────────────────────

STRATEGIES = {
    "RSI(14)":            lambda c: rsi_mean_reversion(c, window=14),
    "RSI(21)":            lambda c: rsi_mean_reversion(c, window=21),
    "MACD":               lambda c: macd_crossover(c),
    "BBands(20,2)":       lambda c: bollinger_bands(c, window=20, alpha=2.0),
    "MA Cross(50/200)":   lambda c: ma_crossover(c, fast=50, slow=200),
    "RSI(14)+Trend(200)": lambda c: rsi_with_trend(c),
    "BBands+RSI":         lambda c: mean_reversion_bb_rsi(c),
}
