from alpha_scanner_core.data.data_loader import fetch_stock_data
from alpha_scanner_core.strategies import get_rsi_signals
from alpha_scanner_core.engine.backtester import run_simple_backtest
from alpha_scanner_core.engine.robustness_score import calculate_robustness_metrics
from alpha_scanner_core.config.settings import settings

def main():
    print("🚀 Starting Batch Scan...")
    results = []

    for ticker in settings.TICKERS:
        print(f"Scanning {ticker}...")
        data = fetch_stock_data(ticker)

        if data is None: continue

        # Just testing RSI as an example for CLI
        entries, exits = get_rsi_signals(data, length=14)
        pf = run_simple_backtest(data, entries, exits)
        metrics = calculate_robustness_metrics(pf)

        if metrics:
            metrics['ticker'] = ticker
            results.append(metrics)

    # Print Leaderboard
    import pandas as pd
    df = pd.DataFrame(results)
    if not df.empty:
        df = df.sort_values(by='robustness_score', ascending=False)
        print(df[['ticker', 'robustness_score', 'profit_factor', 'trade_count']].head(10))
    else:
        print("No robust strategies found.")

if __name__ == "__main__":
    main()
