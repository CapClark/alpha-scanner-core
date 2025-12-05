import numpy as np
from alpha_scanner_core.engine.backtester import run_simple_backtest

def analyze_stability(data, func, param_name, base_param, other_params, window: int = 5):
    """
    Analyze strategy stability by sweeping the main parameter around base_param.

    Args:
        data: Price series (e.g., pandas Series)
        func: Strategy signal function (returns entries, exits)
        param_name: Name of the main strategy parameter to sweep
        base_param: The current/base value of the parameter
        other_params: Dict of other fixed strategy parameters
        window: Number of steps to sweep around base_param (default +/-5)

    Returns:
        dict: {
            'stability_score': float (0-100),
            'volatility': float,
            'avg_return': float,
            'tested_values': list of parameter values tested,
            'returns': list of returns for each parameter,
            'status': str
        }
    """

    tested_values = []
    returns = []

    # Sweep around base_param
    for delta in range(-window, window + 1):
        param_value = max(1, base_param + delta)
        tested_values.append(param_value)

        # Generate signals
        entries, exits = func(data, **{param_name: param_value}, **other_params)

        # Run backtest
        pf = run_simple_backtest(data, entries, exits)

        # VectorBT-compatible PnL extraction
        pnl = pf.trades.pnl.values if pf and pf.trades else np.array([])
        total_return = pnl.sum() if pnl.size > 0 else 0
        returns.append(total_return)

    returns_array = np.array(returns)
    avg_return = np.mean(returns_array)
    std_dev = np.std(returns_array)
    cv = std_dev / abs(avg_return) if avg_return != 0 else 1.0

    # Stability score 0-100
    stability_score = round(max(0, 1 - cv) * 100, 2)

    # Status description
    if stability_score > 80:
        status = "Very Stable"
    elif stability_score > 50:
        status = "Stable"
    elif stability_score > 30:
        status = "Questionable"
    else:
        status = "Unstable"

    return {
        "stability_score": stability_score,
        "volatility": std_dev,
        "avg_return": avg_return,
        "tested_values": tested_values,
        "returns": returns,
        "status": status
    }
