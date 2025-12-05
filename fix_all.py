import os

# 1. Strategies.py (With .fillna(False) Fixes)
strategies_code = """
import vectorbt as vbt
import numpy as np
import pandas as pd

def get_rsi_signals(close_price, length=14, oversold=30, overbought=70):
    \"\"\"RSI Mean Reversion Strategy\"\"\"
    rsi = vbt.RSI.run(close_price, window=length).rsi

    # FIX: Handle NaNs explicitly
    entries = rsi.vbt.crossed_below(oversold).fillna(False)
    exits = rsi.vbt.crossed_above(overbought).fillna(False)

    return entries, exits

def get_bb_signals(close_price, window=20, std=2.0):
    \"\"\"Bollinger Band Mean Reversion Strategy\"\"\"
    ma = vbt.MA.run(close_price, window=window).ma
    rolling_std = close_price.rolling(window=window).std()

    upper_band = ma + (rolling_std * std)
    lower_band = ma - (rolling_std * std)

    # FIX: Handle NaNs explicitly
    entries = close_price.vbt.crossed_below(lower_band).fillna(False)
    exits = close_price.vbt.crossed_above(ma).fillna(False)

    return entries, exits

def get_sma_signals(close_price, fast_window=50, slow_window=200):
    \"\"\"SMA Trend Following Strategy\"\"\"
    fast_ma = vbt.MA.run(close_price, window=fast_window).ma
    slow_ma = vbt.MA.run(close_price, window=slow_window).ma

    # FIX: Handle NaNs explicitly
    entries = fast_ma.vbt.crossed_above(slow_ma).fillna(False)
    exits = fast_ma.vbt.crossed_below(slow_ma).fillna(False)

    return entries, exits

def get_macd_signals(close_price, fast=12, slow=26, signal=9):
    \"\"\"MACD Momentum Strategy\"\"\"
    macd_ind = vbt.MACD.run(close_price, fast_window=fast, slow_window=slow, signal_window=signal)

    # FIX: Handle NaNs explicitly
    entries = macd_ind.macd.vbt.crossed_above(macd_ind.signal).fillna(False)
    exits = macd_ind.macd.vbt.crossed_below(macd_ind.signal).fillna(False)

    return entries, exits

def get_rsi_trend_signals(close_price, rsi_len=14, sma_len=200):
    \"\"\"RSI + Trend Filter\"\"\"
    rsi = vbt.RSI.run(close_price, window=rsi_len).rsi
    sma = vbt.MA.run(close_price, window=sma_len).ma

    cond_uptrend = (close_price > sma).fillna(False)
    rsi_cross_below = rsi.vbt.crossed_below(30).fillna(False)

    entries = rsi_cross_below & cond_uptrend
    exits = rsi.vbt.crossed_above(70).fillna(False)

    return entries, exits
"""

# 2. Main.py (Using the corrected strategies)
main_code = """
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
                continue

            print(f"🔍 Scanning {ticker}...")

            # Strategy 1: RSI
            for length in rsi_lengths:
                entries, exits = get_rsi_signals(data, length=length)
                pf = run_simple_backtest(data, entries, exits)
                metrics = calculate_robustness_metrics(pf, min_trades=settings.MIN_TRADE_COUNT)
                if metrics:
                    metrics.update({'ticker': ticker, 'strategy': f'RSI ({length})'})
                    results.append(metrics)

            # Strategy 2: BBands
            for win in bb_windows:
                entries, exits = get_bb_signals(data, window=win, std=2.0)
                pf = run_simple_backtest(data, entries, exits)
                metrics = calculate_robustness_metrics(pf, min_trades=settings.MIN_TRADE_COUNT)
                if metrics:
                    metrics.update({'ticker': ticker, 'strategy': f'BBands ({win}, 2.0)'})
                    results.append(metrics)

            # Strategy 3: SMA
            for fast, slow in sma_fast_slow:
                entries, exits = get_sma_signals(data, fast, slow)
                pf = run_simple_backtest(data, entries, exits)
                metrics = calculate_robustness_metrics(pf, min_trades=settings.MIN_TRADE_COUNT)
                if metrics:
                    metrics.update({'ticker': ticker, 'strategy': f'SMA ({fast}/{slow})'})
                    results.append(metrics)

            # Strategy 4: MACD
            entries, exits = get_macd_signals(data)
            pf = run_simple_backtest(data, entries, exits)
            metrics = calculate_robustness_metrics(pf, min_trades=settings.MIN_TRADE_COUNT)
            if metrics:
                metrics.update({'ticker': ticker, 'strategy': 'MACD (12,26,9)'})
                results.append(metrics)

            # Strategy 5: RSI + Trend
            entries, exits = get_rsi_trend_signals(data)
            pf = run_simple_backtest(data, entries, exits)
            metrics = calculate_robustness_metrics(pf, min_trades=settings.MIN_TRADE_COUNT)
            if metrics:
                metrics.update({'ticker': ticker, 'strategy': 'RSI(14) + Trend(200)'})
                results.append(metrics)

        except Exception as e:
            print(f"   ⚠️ Error processing {ticker}: {e}")

    print("\\n" + "="*75)
    print("🏆 FINAL ROBUSTNESS LEADERBOARD 🏆")
    print("="*75)

    if not results:
        print("No robust strategies found. Try lowering MIN_TRADE_COUNT.")
    else:
        df = pd.DataFrame(results)
        df = df.sort_values(by='robustness_score', ascending=False)
        cols = ['ticker', 'strategy', 'robustness_score', 'profit_factor', 'trade_count', 'total_return']
        print(df[cols].head(30).to_string(index=False, float_format=\"%.2f\"))

        os.makedirs("datasets", exist_ok=True)
        df.to_csv("datasets/scan_results.csv", index=False)
        print(f"\\n✅ Full results saved to datasets/scan_results.csv")

if __name__ == "__main__":
    main()
"""

# Write files
with open("alpha_scanner_core/strategies/strategies.py", "w") as f:
    f.write(strategies_code.strip())
print("✅ Fixed strategies.py (Added NaN handling)")

with open("alpha_scanner_core/cli/main.py", "w") as f:
    f.write(main_code.strip())
print("✅ Fixed main.py (Matched imports)")

print("\n✨ Fix Complete. Run 'python run.py' now.")
