import sys
import os
import pandas as pd
import vectorbt as vbt

# Ensure root path is visible
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(current_dir, '../../'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from alpha_scanner_core.data.data_loader import fetch_stock_data
from alpha_scanner_core.engine.backtester import run_simple_backtest
from alpha_scanner_core.engine.robustness_score import calculate_robustness_metrics
from alpha_scanner_core.config.settings import settings
from alpha_scanner_core.strategies.strategies import (
    get_rsi_signals,
    get_bb_signals,
    get_sma_signals,
    get_macd_signals,
    get_rsi_trend_signals
)

def main():
    print(f"🚀 Alpha Scanner PRO Starting...")
    print(f"📋 Target Universe: {len(settings.TICKERS)} stocks")
    print("-" * 60)

    results = []

    # Parameter Ranges
    rsi_lengths = [14, 21, 30]
    bb_windows = [20, 30]
    sma_fast_slow = [(10, 50), (20, 100), (50, 200)]

    for ticker in settings.TICKERS:
        try:
            data = fetch_stock_data(ticker)
            if data is None or data.empty:
                print(f"   ⚠️ No data found for {ticker}. Skipping.") # <-- Add this
                continue

            print(f"🔍 Scanning {ticker}...")

            # Strategy 1: RSI
            for length in rsi_lengths:
                try:
                    entries, exits = get_rsi_signals(data, length=length)
                    # FIX: Ensure boolean and fillna BEFORE checking .any()
                    entries = entries.fillna(False)
                    exits = exits.fillna(False)

                    if not entries.any() and not exits.any(): continue

                    pf = run_simple_backtest(data, entries, exits)
                    metrics = calculate_robustness_metrics(pf, min_trades=settings.MIN_TRADE_COUNT)
                    if metrics:
                        metrics.update({'ticker': ticker, 'strategy': f'RSI ({length})'})
                        results.append(metrics)
                except Exception as e:
                    # Catch strategy-specific errors without stopping the loop
                    # print(f"   Warning (RSI): {e}")
                    pass

            # Strategy 2: BBands
            for win in bb_windows:
                try:
                    entries, exits = get_bb_signals(data, window=win, std=2.0)
                    entries = entries.fillna(False)
                    exits = exits.fillna(False)

                    if not entries.any() and not exits.any(): continue

                    pf = run_simple_backtest(data, entries, exits)
                    metrics = calculate_robustness_metrics(pf, min_trades=settings.MIN_TRADE_COUNT)
                    if metrics:
                        metrics.update({'ticker': ticker, 'strategy': f'BBands ({win}, 2.0)'})
                        results.append(metrics)
                except Exception as e:
                    pass

            # Strategy 3: SMA
            for fast, slow in sma_fast_slow:
                try:
                    entries, exits = get_sma_signals(data, fast_window=fast, slow_window=slow)
                    entries = entries.fillna(False)
                    exits = exits.fillna(False)

                    if not entries.any() and not exits.any(): continue

                    pf = run_simple_backtest(data, entries, exits)
                    metrics = calculate_robustness_metrics(pf, min_trades=settings.MIN_TRADE_COUNT)
                    if metrics:
                        metrics.update({'ticker': ticker, 'strategy': f'SMA ({fast}/{slow})'})
                        results.append(metrics)
                except Exception as e:
                    pass

            # Strategy 4: MACD
            try:
                entries, exits = get_macd_signals(data)
                entries = entries.fillna(False)
                exits = exits.fillna(False)

                if entries.any() or exits.any():
                    pf = run_simple_backtest(data, entries, exits)
                    metrics = calculate_robustness_metrics(pf, min_trades=settings.MIN_TRADE_COUNT)
                    if metrics:
                        metrics.update({'ticker': ticker, 'strategy': 'MACD (12,26,9)'})
                        results.append(metrics)
            except Exception as e:
                pass

            # Strategy 5: RSI + Trend
            try:
                entries, exits = get_rsi_trend_signals(data)
                entries = entries.fillna(False)
                exits = exits.fillna(False)

                if entries.any() or exits.any():
                    pf = run_simple_backtest(data, entries, exits)
                    metrics = calculate_robustness_metrics(pf, min_trades=settings.MIN_TRADE_COUNT)
                    if metrics:
                        metrics.update({'ticker': ticker, 'strategy': 'RSI(14) + Trend(200)'})
                        results.append(metrics)
            except Exception as e:
                pass

        except Exception as e:
            print(f"   ⚠️ Error processing {ticker}: {e}")

    print("\n" + "="*75)
    print("🏆 FINAL ROBUSTNESS LEADERBOARD 🏆")
    print("="*75)

    if not results:
        print("No robust strategies found. Try lowering MIN_TRADE_COUNT.")
    else:
        df = pd.DataFrame(results)
        df = df.sort_values(by='robustness_score', ascending=False)
        cols = ['ticker', 'strategy', 'robustness_score', 'profit_factor', 'trade_count', 'total_return']
        print(df[cols].head(30).to_string(index=False, float_format="%.2f"))

        os.makedirs("datasets", exist_ok=True)
        df.to_csv("datasets/scan_results.csv", index=False)
        print(f"\n✅ Full results saved to datasets/scan_results.csv")

if __name__ == "__main__":
    main()