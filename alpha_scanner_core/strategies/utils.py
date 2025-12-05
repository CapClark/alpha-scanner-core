import pandas as pd

def align_signals(entries, exits):
    """
    Ensures signals are clean and aligned.
    Forces an exit before a new entry.
    """
    return entries.vbt.signals.clean(exits)

def get_valid_parameters(strategy_type):
    """Returns default parameter ranges for optimization."""
    if strategy_type == "RSI":
        return range(10, 30, 2)
    elif strategy_type == "BB":
        return range(10, 50, 5)
    return []
