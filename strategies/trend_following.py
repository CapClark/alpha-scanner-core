import vectorbt as vbt

def get_sma_signals(close_price, fast_window=50, slow_window=200):
    """SMA Trend Following Strategy"""
    fast_ma = vbt.MA.run(close_price, window=fast_window).ma
    slow_ma = vbt.MA.run(close_price, window=slow_window).ma

    # Entry: Fast > Slow
    entries = fast_ma.vbt.crossed_above(slow_ma)
    # Exit: Fast < Slow
    exits = fast_ma.vbt.crossed_below(slow_ma)

    return entries, exits
