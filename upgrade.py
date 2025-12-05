import os

# 1. THE FULL TICKER UNIVERSE
FULL_SETTINGS = """
import os
from dotenv import load_dotenv

load_dotenv()

class Settings:
    # --- API Keys ---
    POLYGON_API_KEY = os.getenv("POLYGON_API_KEY", "MOCK_KEY_FOR_TESTING")

    # --- Scanner Configuration ---
    # The complete list of 100+ liquid stocks across all major sectors
    TICKERS = [
        # Tech - Giants & Software
        'AAPL', 'MSFT', 'AMZN', 'GOOGL', 'META', 'NVDA', 'ADBE',
        'CRM', 'ORCL', 'IBM', 'SAP', 'NOW', 'INTU', 'PANW', 'CSCO',
        'SNOW', 'PLTR', 'DELL', 'HPQ',

        # Tech - Semiconductors
        'AMD', 'QCOM', 'INTC', 'TXN', 'MU', 'AVGO', 'ASML', 'LRCX',
        'AMAT', 'ADI', 'KLAC',

        # Financials
        'JPM', 'BAC', 'WFC', 'GS', 'MS', 'SCHW', 'BLK', 'BRK-B', 'C',
        'V', 'MA', 'PYPL', 'SQ', 'AXP', 'COIN', 'HOOD', 'SOFI', 'AFRM',

        # Healthcare
        'JNJ', 'LLY', 'MRK', 'PFE', 'ABBV', 'NVO', 'GILD', 'VRTX',
        'UNH', 'CVS', 'ELV', 'CI', 'HCA', 'MDT', 'ISRG', 'TMO',

        # Consumer
        'WMT', 'COST', 'TGT', 'HD', 'LOW', 'NKE', 'LULU', 'ETSY',
        'TSLA', 'F', 'GM', 'BKNG', 'ABNB', 'UBER', 'LYFT', 'RIVN',
        'MCD', 'SBUX', 'YUM', 'CMG', 'DPZ',
        'PG', 'KO', 'PEP', 'PM', 'MO', 'EL', 'CL', 'KMB',

        # Energy & Industrials
        'XOM', 'CVX', 'SHEL', 'TTE', 'COP', 'SLB', 'HAL', 'EOG', 'BP',
        'CAT', 'DE', 'GE', 'HON', 'LMT', 'BA', 'UPS', 'FDX', 'WM',

        # Media & Telecom
        'DIS', 'NFLX', 'CMCSA', 'TMUS', 'VZ', 'T', 'SPOT',

        # Crypto-Related (High Volatility)
        'MARA', 'RIOT', 'CLSK', 'IREN', 'MSTR'
    ]

    MIN_TRADE_COUNT = 15  # Lowered slightly for daily timeframe
    START_DATE = "2020-01-01"
    DATA_CACHE_DIR = "datasets/cache"

settings = Settings()
"""

# 2. THE ADVANCED SCANNER LOGIC
FULL_SCANNER = """
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
from alpha_scanner_core.strategies import (
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

    # --- PARAMETER RANGES ---
    # We will loop through these to find the best settings per stock
    rsi_lengths = [14, 21, 30]
    bb_windows = [20, 30]
    sma_fast_slow = [(10, 50), (20, 100), (50, 200)]

    # Loop through every ticker in the universe
    for ticker in settings.TICKERS:
        try:
            # 1. Get Data
            data = fetch_stock_data(ticker)
            if data is None or data.empty:
                continue

            print(f"🔍 Scanning {ticker}...", end="\\r") # Update line in place

            # --- STRATEGY 1: RSI ---
            for length in rsi_lengths:
                entries, exits = get_rsi_signals(data, length=length)
                pf = run_simple_backtest(data, entries, exits)
                metrics = calculate_robustness_metrics(pf, min_trades=settings.MIN_TRADE_COUNT)
                if metrics:
                    metrics.update({'ticker': ticker, 'strategy': f'RSI ({length})'})
                    results.append(metrics)

            # --- STRATEGY 2: Bollinger Bands ---
            for win in bb_windows:
                entries, exits = get_bb_signals(data, window=win, std=2.0)
                pf = run_simple_backtest(data, entries, exits)
                metrics = calculate_robustness_metrics(pf, min_trades=settings.MIN_TRADE_COUNT)
                if metrics:
                    metrics.update({'ticker': ticker, 'strategy': f'BBands ({win}, 2.0)'})
                    results.append(metrics)

            # --- STRATEGY 3: SMA Crossover ---
            for fast, slow in sma_fast_slow:
                entries, exits = get_sma_signals(data, fast, slow)
                pf = run_simple_backtest(data, entries, exits)
                metrics = calculate_robustness_metrics(pf, min_trades=settings.MIN_TRADE_COUNT)
                if metrics:
                    metrics.update({'ticker': ticker, 'strategy': f'SMA ({fast}/{slow})'})
                    results.append(metrics)

            # --- STRATEGY 4: MACD ---
            entries, exits = get_macd_signals(data)
            pf = run_simple_backtest(data, entries, exits)
            metrics = calculate_robustness_metrics(pf, min_trades=settings.MIN_TRADE_COUNT)
            if metrics:
                metrics.update({'ticker': ticker, 'strategy': 'MACD (12,26,9)'})
                results.append(metrics)

            # --- STRATEGY 5: RSI + Trend ---
            entries, exits = get_rsi_trend_signals(data)
            pf = run_simple_backtest(data, entries, exits)
            metrics = calculate_robustness_metrics(pf, min_trades=settings.MIN_TRADE_COUNT)
            if metrics:
                metrics.update({'ticker': ticker, 'strategy': 'RSI(14) + Trend(200)'})
                results.append(metrics)

        except Exception as e:
            print(f"\\n   ⚠️ Error processing {ticker}: {e}")

    # --- FINAL REPORT ---
    print("\\n" + "="*75)
    print("🏆 FINAL ROBUSTNESS LEADERBOARD 🏆")
    print("="*75)

    if not results:
        print("No robust strategies found. Try lowering MIN_TRADE_COUNT.")
    else:
        df = pd.DataFrame(results)
        # Sort by Robustness Score
        df = df.sort_values(by='robustness_score', ascending=False)

        # Clean columns
        cols = ['ticker', 'strategy', 'robustness_score', 'profit_factor', 'trade_count', 'total_return']

        # Print Top 30 with CORRECT formatting
        # We use %.2f to ensure pandas formats it as a number
        print(df[cols].head(30).to_string(index=False, float_format=\"%.2f\"))

        # Save to CSV
        os.makedirs("datasets", exist_ok=True)
        df.to_csv("datasets/scan_results.csv", index=False)
        print(f"\\n✅ Full results saved to datasets/scan_results.csv")

if __name__ == "__main__":
    main()
"""

# Write the files
print("🚀 Upgrading Alpha Scanner to PRO version...")

with open("alpha_scanner_core/config/settings.py", "w") as f:
    f.write(FULL_SETTINGS)
print("  ✅ Upgraded Settings (100+ Tickers)")

with open("alpha_scanner_core/cli/main.py", "w") as f:
    f.write(FULL_SCANNER)
print("  ✅ Upgraded Scanner Logic (Fixed Formatting)")

print("\n✨ Upgrade Complete. Run 'python run.py' to start the Mega-Scan.")
