# alpha_scanner_core/engine/robustness_score.py

def calculate_robustness_metrics(portfolio, min_trades: int = 2) -> dict | None:
    """
    Calculate robustness metrics from a VectorBT Portfolio object.
    
    Args:
        portfolio: vectorbt Portfolio object
        min_trades: minimum number of trades to calculate metrics

    Returns:
        dict | None: {'trade_count', 'profit_factor', 'total_return'} or None if not enough trades
    """

    if portfolio is None:
        return None

    trades = getattr(portfolio, 'trades', None)
    if trades is None:
        return None

    # Get the profits/losses for all trades
    pnl = trades.pnl.values  # ExitTrades supports .pnl to get PnL per trade

    trade_count = len(pnl)
    if trade_count < min_trades:
        return None

    total_profit = pnl[pnl > 0].sum()
    total_loss = pnl[pnl < 0].sum()
    profit_factor = total_profit / abs(total_loss) if total_loss != 0 else float('inf')
    total_return = pnl.sum()

    return {
        'trade_count': trade_count,
        'profit_factor': profit_factor,
        'total_return': total_return
    }
