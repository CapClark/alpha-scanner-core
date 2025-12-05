import numpy as np
import vectorbt as vbt
import pandas as pd

def run_monte_carlo_test(close_price, strategy_func, params, iterations=100):
    """
    Validates a strategy by shuffling the price data (detrended)
    to see if the strategy still makes money on random noise.

    If it makes money on random noise, the strategy is likely "Overfit".
    If it loses money on noise but makes money on real data, it has "Alpha".
    """
    real_entries, real_exits = strategy_func(close_price, **params)
    real_pf = vbt.Portfolio.from_signals(close_price, real_entries, real_exits, freq='D')
    real_return = real_pf.total_return()

    random_returns = []

    # Simple Monte Carlo: Shuffle the daily returns, reconstruct price
    daily_returns = close_price.pct_change().dropna()

    for _ in range(iterations):
        # 1. Shuffle returns
        shuffled_returns = np.random.permutation(daily_returns.values)

        # 2. Reconstruct a "fake" price series
        # Start at same price as real data
        start_price = close_price.iloc[0]
        # Calculate cumulative product of (1 + returns)
        fake_price_array = start_price * np.cumprod(1 + shuffled_returns)

        # Make it a Series with the same index (shifted by 1 because of pct_change drop)
        fake_price = pd.Series(fake_price_array, index=daily_returns.index)

        # 3. Run strategy on fake data
        try:
            f_entries, f_exits = strategy_func(fake_price, **params)
            f_pf = vbt.Portfolio.from_signals(fake_price, f_entries, f_exits, freq='D')
            random_returns.append(f_pf.total_return())
        except:
            random_returns.append(0.0)

    # Calculate Percentile
    # What % of random runs beat the real run?
    # Lower is better. If 0%, your strategy is unique. If 50%, it's a coin toss.
    better_than_random_count = sum(r > real_return for r in random_returns)
    p_value = better_than_random_count / iterations

    return {
        "real_return": real_return,
        "random_returns_avg": np.mean(random_returns),
        "p_value": p_value, # < 0.05 is statistically significant
        "iterations": iterations
    }
