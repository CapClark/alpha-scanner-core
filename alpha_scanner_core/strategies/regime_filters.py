import vectorbt as vbt

def get_trend_filter(close_price, window=200):
    """
    Returns a boolean mask:
    True = Uptrend (Price > SMA)
    False = Downtrend (Price < SMA)
    """
    sma = vbt.MA.run(close_price, window=window).ma
    is_uptrend = close_price > sma
    return is_uptrend
