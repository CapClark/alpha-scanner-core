import numpy as np
import pandas as pd

def calculate_robustness_metrics(pf, min_trades=5):
    """
    Calculates Profit Factor, Trade Count, and the custom Robustness Score.
    """
    trade_count = pf.trades.count()
    
    if trade_count < min_trades:
        return None
    
    stats = pf.stats()
    # Safe .get() to avoid KeyErrors
    # Note: vectorbt stat names can vary slightly by version, we try standard ones
    total_return = stats.get('Total Return [%]', stats.get('Total Return', 0.0))
    profit_factor = stats.get('Profit Factor', 0.0)
    
    # Handle infinite profit factor (100% win rate cases)
    # We cap it to prevent math errors in scoring
    if np.isinf(profit_factor) or np.isnan(profit_factor):
        profit_factor = 100.0 if total_return > 0 else 0.0
        
    # --- THE ROBUSTNESS FORMULA ---
    # Score = Profit Factor * log(Trade Count)
    # We use log to reward frequency but with diminishing returns
    robustness_score = profit_factor * np.log(trade_count)
    
    return {
        "trade_count": int(trade_count),
        "profit_factor": float(profit_factor),
        "total_return": float(total_return),
        "robustness_score": float(robustness_score)
    }