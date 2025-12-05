import vectorbt as vbt

def run_simple_backtest(close_price, entries, exits):
    """Runs a standard vectorbt backtest."""
    pf = vbt.Portfolio.from_signals(
        close_price,
        entries=entries,
        exits=exits,
        fees=0.001, # 0.1% fees
        freq='D'
    )
    return pf
