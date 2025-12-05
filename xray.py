import sys
import os
import pandas as pd
import numpy as np

# Path Fix
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

from alpha_scanner_core.data.data_loader import fetch_stock_data
from alpha_scanner_core.strategies import get_rsi_signals
from alpha_scanner_core.engine.backtester import run_simple_backtest

def run_diagnosis():
    print("\n🩺 STARTING DIAGNOSIS FOR AAPL...\n")

    # 1. CHECK DATA
    print("1️⃣ CHECKING DATA...")
    data = fetch_stock_data("AAPL")

    if data is None or data.empty:
        print("   ❌ ERROR: No data returned for AAPL.")
        print("   --> Check your POLYGON_API_KEY in .env")
        return

    # --- DATA TYPE FIX ---
    # Ensure we are working with a Series (single column), not a DataFrame
    if isinstance(data, pd.DataFrame):
        print(f"   ℹ️ Note: Received DataFrame with columns: {data.columns.tolist()}")
        if 'Close' in data.columns:
            data = data['Close']
        elif 'close' in data.columns:
            data = data['close']
        else:
            # Fallback: use the first column
            print(f"   ⚠️ Warning: 'Close' column not found. Using first column: {data.columns[0]}")
            data = data.iloc[:, 0]
    # --- END FIX ---

    print(f"   ✅ Data Loaded. Rows: {len(data)}")
    print(f"   📅 Date Range: {data.index[0].date()} to {data.index[-1].date()}")

    # Now this print statement will work because data.iloc[0] is definitely a float
    print(f"   💵 First Price: {data.iloc[0]:.2f} | Last Price: {data.iloc[-1]:.2f}")

    if len(data) < 252:
        print("   ⚠️ WARNING: Less than 1 year of data. Trade counts will be low.")

    # 2. CHECK SIGNALS (RSI 14)
    print("\n2️⃣ CHECKING SIGNALS (RSI 14)...")
    try:
        # Explicitly passing the params we use in main.py
        entries, exits = get_rsi_signals(data, length=14, oversold=30, overbought=70)

        # Count signals
        n_entries = entries.sum()
        n_exits = exits.sum()

        print(f"   ✅ Entry Signals: {n_entries}")
        print(f"   ✅ Exit Signals:  {n_exits}")

        if n_entries == 0:
            print("   ⚠️ WARNING: 0 Entry signals found. RSI might never be crossing 30.")

    except Exception as e:
        print(f"   ❌ ERROR generating signals: {e}")
        import traceback
        traceback.print_exc()
        return

    # 3. CHECK BACKTEST
    print("\n3️⃣ CHECKING BACKTEST TRADES...")
    try:
        pf = run_simple_backtest(data, entries, exits)
        trade_count = pf.trades.count()

        print(f"   ✅ Total Trades Executed: {trade_count}")

        stats = pf.stats()
        # Safe get for stats to avoid KeyErrors
        ret = stats.get('Total Return [%]', stats.get('Total Return', 0.0))
        prof = stats.get('Profit Factor', 0.0)

        print(f"   💰 Total Return: {ret:.2f}%")
        print(f"   📊 Profit Factor: {prof:.2f}")

        # 4. CHECK THE FILTER
        print("\n4️⃣ CHECKING FILTER...")
        min_trades = 10 # Use a lower threshold for debugging
        print(f"   Target Filter (MIN_TRADE_COUNT): {min_trades}")

        if trade_count >= min_trades:
            print("   🎉 RESULT: This strategy WOULD pass the filter.")
        else:
            print(f"   🚫 RESULT: This strategy FAILED the filter ({trade_count} < {min_trades}).")
            print("      --> The strategy logic works, but it doesn't trade enough.")
            print("      --> RECOMMENDATION: Lower MIN_TRADE_COUNT in settings.py to 5 or 10.")

    except Exception as e:
        print(f"   ❌ ERROR running backtest: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    run_diagnosis()
