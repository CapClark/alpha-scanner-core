import numpy as np

def calculate_robustness_metrics(pf, min_trades=10):
    """Calculates Profit Factor, Trade Count, and Score."""
    trade_count = pf.trades.count()

    if trade_count < min_trades:
        return None

    stats = pf.stats()
    # Safe .get() to avoid KeyErrors
    pf_value = stats.get('Profit Factor', 0.0)
    ret_value = stats.get('Total Return [%]', 0.0)

    # Handle infinite profit factor (100% win rate)
    if np.isinf(pf_value):
        pf_value = 50.0 # Cap it

    # The Secret Sauce Formula
    robustness_score = pf_value * np.log(trade_count)

    return {
        "trade_count": trade_count,
        "profit_factor": pf_value,
        "total_return": ret_value,
        "robustness_score": robustness_score
    }
