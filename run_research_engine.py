import os
import numpy as np
import pandas as pd
import vectorbt as vbt
from dotenv import load_dotenv
from supabase import create_client

# --- IMPORTS CHANGED HERE ---
# We now use your existing data loader instead of market_data.py
from alpha_scanner_core.data.data_loader import fetch_stock_data

# --- CONFIGURATION ---
load_dotenv()
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

# Expand the universe (S&P 100 subset + Tech)
TICKERS = [
    'AAPL', 'MSFT', 'GOOGL', 'AMZN', 'NVDA', 'TSLA', 'AMD', 'META', 'SPY', 'QQQ',
    'JPM', 'JNJ', 'V', 'PG', 'MA', 'HD', 'CVX', 'MRK', 'ABBV', 'PEP'
]

db_client = create_client(SUPABASE_URL, SUPABASE_KEY)

def run_parameter_sweep():
    print(f"🚀 Starting Parameter Sweep on {len(TICKERS)} assets...")
    
    all_results = []

    for ticker in TICKERS:
        # Use your existing loader
        # We use .squeeze() to convert the 1-column DataFrame to a Series for VectorBT
        df = fetch_stock_data(ticker)
        
        if df is None or df.empty:
            continue
            
        close_price = df['Close']

        # =============================================
        # STRATEGY 1: RSI SWEEP (Window 5 to 40)
        # =============================================
        
        # 1. Define Parameter Space (The "Sweep")
        windows = np.arange(5, 40, 2)  # [5, 7, 9, ... 39]
        
        # 2. Vectorized Calculation (Runs all variations instantly)
        rsi = vbt.RSI.run(close_price, window=windows)
        
        # 3. Define Logic
        entries = rsi.rsi_below(30)
        exits = rsi.rsi_above(70)
        
        # 4. Backtest All Variations
        pf = vbt.Portfolio.from_signals(close_price, entries, exits, fees=0.001, freq='1D')
        
        # 5. Extract Metrics
        total_trades = pf.trades.count()
        profit_factors = pf.trades.profit_factor()
        win_rates = pf.trades.win_rate()
        returns = pf.total_return()
        
        # Access portfolio values (Equity Curves)
        # pf.value() returns a DataFrame where columns are the windows
        portfolio_values = pf.value()

        # 6. Iterate through results to find the gems
        for window in windows:
            trades = total_trades[window]
            pf_value = profit_factors[window]
            
            # Skip bad/empty results
            if trades < 15 or np.isnan(pf_value): 
                continue

            # Robustness Formula
            score = pf_value * np.log(trades)
            
            if score > 3.0: # Minimum quality threshold
                
                # --- EXTRACT EQUITY CURVE ---
                # Get the specific column for this window
                equity_series = portfolio_values[window]
                
                # Downsample if too large (keep max 200 points for chart performance)
                if len(equity_series) > 200:
                    equity_series = equity_series.iloc[::len(equity_series)//200]
                
                # Convert to List of Dicts for JSON storage
                equity_curve = [
                    {"date": str(idx.date()), "value": round(val, 2)}
                    for idx, val in equity_series.items()
                ]
                # ---------------------------

                all_results.append({
                    "symbol": ticker,
                    "strategy_name": f"RSI Reversion ({window})",
                    "robustness_score": round(float(score), 2),
                    "profit_factor": round(float(pf_value), 2),
                    "win_rate": round(float(win_rates[window] * 100), 1),
                    "total_trades": int(trades),
                    "net_return_pct": round(float(returns[window] * 100), 1),
                    "equity_curve": equity_curve  # <--- New Data Field
                })

    # --- UPLOAD ---
    if all_results:
        # Sort by Robustness (Top 100 only)
        all_results.sort(key=lambda x: x['robustness_score'], reverse=True)
        top_results = all_results[:100]
        
        print(f"💾 Saving top {len(top_results)} robust strategies...")
        
        try:
            # Refresh Leaderboard
            db_client.table("strategy_leaderboard").delete().neq("robustness_score", -1).execute()
            db_client.table("strategy_leaderboard").insert(top_results).execute()
            print("✅ Leaderboard Updated.")
        except Exception as e:
            print(f"❌ Database Error: {e}")
            
        # Also save to local CSV for inspection
        # Drop equity_curve from CSV to keep it readable
        csv_results = [{k: v for k, v in res.items() if k != 'equity_curve'} for res in top_results]
        pd.DataFrame(csv_results).to_csv("scan_results.csv", index=False)
        print("✅ Saved to scan_results.csv")
    else:
        print("No robust strategies found.")

if __name__ == "__main__":
    run_parameter_sweep()