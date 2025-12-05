import numpy as np

def analyze_stability(param_sweep_results):
    """
    Analyzes the results from a parameter sweep to determine stability.
    """
    returns = np.array(param_sweep_results['returns'])

    if len(returns) == 0:
        return {"score": 0, "volatility": 0, "status": "No Data"}

    avg_return = np.mean(returns)
    std_dev = np.std(returns)

    # Coefficient of Variation (Risk/Reward of the parameter choice itself)
    if avg_return == 0:
        cv = 1.0
    else:
        cv = std_dev / abs(avg_return)

    # Stability Score (0-100)
    # Lower CV is better.
    # If StdDev is > 50% of Avg Return, score drops rapidly.
    raw_score = max(0, 1 - cv)
    stability_score = round(raw_score * 100, 2)

    status = "Unstable"
    if stability_score > 80: status = "Very Stable"
    elif stability_score > 50: status = "Stable"
    elif stability_score > 30: status = "Questionable"

    return {
        "score": stability_score,
        "volatility": std_dev,
        "avg_return": avg_return,
        "status": status
    }
