import pandas as pd
import time
from data_loader import get_polygon_data
from strategies import get_rsi_signals, get_bb_signals, get_sma_signals
from analyzer import run_backtest, calculate_robustness

# --- CONFIG ---
# Start small to test the connection
TICKERS = ['AAPL', 'MSFT', 'TSLA', 'NVDA', 'JNJ', 'KO', 'WMT']
START_DATE = "2020-01-01"
END_DATE = "2024-01-01"

# Store results here
leaderboard = []

print(f"🚀 Alpha Scanner Starting... Analyzing {len(TICKERS)} stocks.")

for ticker in TICKERS:
    print(f"\n🔍 Fetching data for {ticker}...")

    # 1. GET DATA
    close_price = get_polygon_data(ticker, START_DATE, END_DATE)

    if close_price is None or close_price.empty:
        continue

    print(f"   Data loaded. Running strategies...")

    # ---------------------------------------
    # STRATEGY 1: RSI (Parameter Sweep)
    # ---------------------------------------
    # We test 3 variations to demonstrate the loop
    for length in [14, 21, 30]:
        entries, exits = get_rsi_signals(close_price, length=length)
        pf = run_backtest(close_price, entries, exits)
        results = calculate_robustness(pf)

        if results:
            results['ticker'] = ticker
            results['strategy'] = f"RSI ({length})"
            leaderboard.append(results)

    # ---------------------------------------
    # STRATEGY 2: Bollinger Bands
    # ---------------------------------------
    for win in [20, 30]:
        entries, exits = get_bb_signals(close_price, window=win)
        pf = run_backtest(close_price, entries, exits)
        results = calculate_robustness(pf)

        if results:
            results['ticker'] = ticker
            results['strategy'] = f"BBands ({win}, 2.0)"
            leaderboard.append(results)

# --- FINAL REPORT ---
print("\n" + "="*50)
print("🏆 FINAL ROBUSTNESS LEADERBOARD 🏆")
print("="*50)

if not leaderboard:
    print("No robust strategies found (try lowering min_trades).")
else:
    df = pd.DataFrame(leaderboard)
    # Sort by your custom score
    df = df.sort_values(by='robustness_score', ascending=False)

    # Clean up columns for display
    cols = ['ticker', 'strategy', 'robustness_score', 'profit_factor', 'trade_count', 'total_return']
    print(df[cols].head(15).to_string(index=False, float_format="%.2f"))

print("\n✅ Scan Complete.")
