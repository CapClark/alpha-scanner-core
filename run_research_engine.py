import os
import numpy as np
import pandas as pd
import vectorbt as vbt
from dotenv import load_dotenv
from supabase import create_client

# --- IMPORTS ---
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

def process_results(pf, windows, strategy_prefix, ticker, all_results):
    """
    Helper function to extract metrics from a Portfolio object
    and append robust findings to the results list.
    """
    # Extract Vectorized Metrics
    total_trades = pf.trades.count()
    profit_factors = pf.trades.profit_factor()
    win_rates = pf.trades.win_rate()
    returns = pf.total_return()
    portfolio_values = pf.value()

    for window in windows:
        # Vectorbt uses the parameter value as the index
        trades = total_trades[window]
        pf_value = profit_factors[window]
        
        # Filter: Minimum trades and valid Profit Factor
        if trades < 15 or np.isnan(pf_value): 
            continue

        # Robustness Score Formula
        score = pf_value * np.log(trades)
        
        if score > 3.0: # Minimum quality threshold
            
            # --- EXTRACT EQUITY CURVE ---
            equity_series = portfolio_values[window]
            
            # Downsample for database storage (max 200 points)
            if len(equity_series) > 200:
                equity_series = equity_series.iloc[::len(equity_series)//200]
            
            equity_curve = [
                {"date": str(idx.date()), "value": round(val, 2)}
                for idx, val in equity_series.items()
            ]
            
            all_results.append({
                "symbol": ticker,
                "strategy_name": f"{strategy_prefix} ({window})",
                "robustness_score": round(float(score), 2),
                "profit_factor": round(float(pf_value), 2),
                "win_rate": round(float(win_rates[window] * 100), 1),
                "total_trades": int(trades),
                "net_return_pct": round(float(returns[window] * 100), 1),
                "equity_curve": equity_curve
            })

def run_parameter_sweep():
    print(f"🚀 Starting Multi-Strategy Sweep on {len(TICKERS)} assets...")
    
    all_results = []

    for ticker in TICKERS:
        df = fetch_stock_data(ticker)
        
        if df is None or df.empty:
            continue
            
        close_price = df['Close'].squeeze() # Ensure Series format

        # =============================================
        # STRATEGY 1: RSI SWEEP (Window 5 to 40)
        # =============================================
        # Logic: Buy < 30, Sell > 70
        rsi_windows = np.arange(5, 40, 2)
        rsi = vbt.RSI.run(close_price, window=rsi_windows)
        
        entries_rsi = rsi.rsi_below(30)
        exits_rsi = rsi.rsi_above(70)
        
        pf_rsi = vbt.Portfolio.from_signals(close_price, entries_rsi, exits_rsi, fees=0.001, freq='1D')
        
        process_results(pf_rsi, rsi_windows, "RSI Reversion", ticker, all_results)

        # =============================================
        # STRATEGY 2: BOLLINGER BANDS (Window 10 to 60)
        # =============================================
        # Logic: Buy < Lower Band, Sell > Upper Band
        bb_windows = np.arange(10, 60, 5)
        bb = vbt.BBANDS.run(close_price, window=bb_windows, alpha=2.0)
        
        entries_bb = close_price < bb.lower
        exits_bb = close_price > bb.upper
        
        pf_bb = vbt.Portfolio.from_signals(close_price, entries_bb, exits_bb, fees=0.001, freq='1D')
        
        process_results(pf_bb, bb_windows, "BB Reversion", ticker, all_results)

    # --- UPLOAD ---
    if all_results:
        # Sort by Robustness
        all_results.sort(key=lambda x: x['robustness_score'], reverse=True)
        top_results = all_results[:100] # Top 100 only
        
        print(f"💾 Saving top {len(top_results)} robust strategies...")
        
        try:
            # Wipe old leaderboard and replace
            db_client.table("strategy_leaderboard").delete().neq("robustness_score", -1).execute()
            db_client.table("strategy_leaderboard").insert(top_results).execute()
            print("✅ Leaderboard Updated.")
        except Exception as e:
            print(f"❌ Database Error: {e}")
            
        # Save CSV backup (excluding equity curve for readability)
        csv_results = [{k: v for k, v in res.items() if k != 'equity_curve'} for res in top_results]
        pd.DataFrame(csv_results).to_csv("scan_results.csv", index=False)
        print("✅ Saved to scan_results.csv")
    else:
        print("No robust strategies found.")

if __name__ == "__main__":
    run_parameter_sweep()