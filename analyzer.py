import vectorbt as vbt
import numpy as np
import pandas as pd

def run_backtest(close_price, entries, exits, fees=0.001):
    """
    Runs the VectorBT portfolio simulation.
    """
    pf = vbt.Portfolio.from_signals(
        close_price,
        entries=entries,
        exits=exits,
        fees=fees,
        freq='D'
    )
    return pf

# --- CHANGE HERE: Lower min_trades to 5 ---
def calculate_robustness(pf, min_trades=5):
    """
    Calculates metrics.
    LOWERED min_trades to 5 to ensure you see results during testing.
    """
    trade_count = pf.trades.count()

    if trade_count < min_trades:
        return None

    stats = pf.stats()
    # Use .get() to be safe against KeyErrors
    total_return = stats.get('Total Return [%]', 0.0)
    profit_factor = stats.get('Profit Factor', 0.0)

    if np.isinf(profit_factor):
        profit_factor = 100.0

    robustness_score = profit_factor * np.log(trade_count)

    return {
        "trade_count": trade_count,
        "profit_factor": profit_factor,
        "total_return": total_return,
        "robustness_score": robustness_score
    }
