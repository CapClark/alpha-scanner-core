import os
import requests # For Discord Notifications
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
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")

# Expanded Universe (S&P 50 + High Beta Tech)
# You can expand this list to 500+ if you have the data
TICKERS = [
    'AAPL', 'MSFT', 'GOOGL', 'AMZN', 'NVDA', 'TSLA', 'META', 'BRK.B', 'TSM', 'UNH',
    'JNJ', 'JPM', 'XOM', 'V', 'PG', 'MA', 'AVGO', 'HD', 'CVX', 'MRK',
    'ABBV', 'PEP', 'KO', 'LLY', 'BAC', 'COST', 'TMO', 'DIS', 'MCD', 'CSCO',
    'ABT', 'DHR', 'ACN', 'VZ', 'NEE', 'WMT', 'BA', 'LIN', 'TXN', 'ADBE',
    'PM', 'NKE', 'RTX', 'UNP', 'UPS', 'PFE', 'LOW', 'INTC', 'HON', 'AMD',
    'QCOM', 'IBM', 'SPGI', 'CAT', 'GS', 'GE', 'DE', 'MS', 'INTU', 'BKNG',
    'BLK', 'AMAT', 'NOW', 'PYPL', 'ADP', 'MDLZ', 'GILD', 'CVS', 'ISRG', 'LMT'
]

db_client = create_client(SUPABASE_URL, SUPABASE_KEY)

# --- NOTIFICATION SYSTEM ---
def send_discord_log(message, color=0x00ff00):
    if not DISCORD_WEBHOOK_URL: return
    try:
        payload = {
            "embeds": [{
                "description": message,
                "color": color,
                "footer": {"text": "Strategy Grade Engine V2"}
            }]
        }
        requests.post(DISCORD_WEBHOOK_URL, json=payload)
    except: pass

# --- MONTE CARLO SIMULATION ---
def run_monte_carlo(close_price, entries, exits, real_return, simulations=50):
    returns = close_price.pct_change()
    better_than_random_count = 0
    
    for _ in range(simulations):
        shuffled_returns = np.random.permutation(returns)
        sim_price = pd.Series(shuffled_returns).add(1).cumprod() * close_price.iloc[0]
        
        # Use simple signals for speed in MC
        pf_sim = vbt.Portfolio.from_signals(sim_price, entries, exits, fees=0.001, freq='1D')
        sim_return = pf_sim.total_return()
        
        if real_return > sim_return:
            better_than_random_count += 1
            
    return better_than_random_count / simulations

def sanitize_float(val):
    """Ensures a value is JSON compliant (no inf or nan)"""
    if val is None or np.isnan(val) or np.isinf(val):
        return 0.0
    return float(val)

def process_results(pf, windows, strategy_prefix, ticker, all_results, close_price, entries_mask, exits_mask):
    total_trades = pf.trades.count()
    profit_factors = pf.trades.profit_factor()
    win_rates = pf.trades.win_rate()
    returns = pf.total_return()
    portfolio_values = pf.value()

    for window in windows:
        try:
            trades = total_trades[window]
            pf_value = profit_factors[window]
            current_win_rate = win_rates[window]
            current_return = returns[window]
            equity_series = portfolio_values[window]
            
            specific_entries = entries_mask.iloc[:, list(windows).index(window)]
            specific_exits = exits_mask.iloc[:, list(windows).index(window)]
            
        except KeyError: continue

        # Series Conversion
        if isinstance(trades, (pd.Series, np.ndarray)): trades = trades.iloc[0]
        if isinstance(pf_value, (pd.Series, np.ndarray)): pf_value = pf_value.iloc[0]
        if isinstance(current_win_rate, (pd.Series, np.ndarray)): current_win_rate = current_win_rate.iloc[0]
        if isinstance(current_return, (pd.Series, np.ndarray)): current_return = current_return.iloc[0]
        if isinstance(equity_series, pd.DataFrame): equity_series = equity_series.iloc[:, 0]

        # Sanitize Metrics immediately
        trades = int(sanitize_float(trades))
        pf_value = sanitize_float(pf_value)
        current_win_rate = sanitize_float(current_win_rate)
        current_return = sanitize_float(current_return)

        # Filtering
        if trades < 15 or pf_value <= 0: continue

        # Robustness Score
        score = pf_value * np.log(trades)
        
        if score > 2.0: # Lowered threshold to ensure data populates
            # Monte Carlo
            mc_confidence = run_monte_carlo(close_price, specific_entries, specific_exits, current_return)
            if mc_confidence < 0.90:
                score = score * 0.5 
            
            if score > 2.0: 
                # Downsample Equity Curve
                if len(equity_series) > 200: equity_series = equity_series.iloc[::len(equity_series)//200]
                
                # Sanitize Equity Curve Data
                equity_curve = []
                for idx, val in equity_series.items():
                    clean_val = sanitize_float(val)
                    equity_curve.append({"date": str(idx.date()), "value": round(clean_val, 2)})
                
                all_results.append({
                    "symbol": ticker,
                    "strategy_name": f"{strategy_prefix} ({window})",
                    "robustness_score": round(float(score), 2),
                    "profit_factor": round(pf_value, 2),
                    "win_rate": round(current_win_rate * 100, 1),
                    "total_trades": trades,
                    "net_return_pct": round(current_return * 100, 1),
                    "equity_curve": equity_curve
                })

def run_parameter_sweep():
    start_msg = f"🚀 **Strategy Grade V2 Started**\nScanning {len(TICKERS)} assets with Shorting & Monte Carlo..."
    print(start_msg)
    send_discord_log(start_msg, 0x3498db)
    
    all_results = []

    for ticker in TICKERS:
        try:
            df = fetch_stock_data(ticker)
            if df is None or df.empty: continue
            close_price = df['Close'].squeeze()

            # --- STRATEGY 1: RSI ---
            rsi_windows = np.arange(3, 60, 1)
            rsi = vbt.RSI.run(close_price, window=rsi_windows)
            
            # Long
            l_entries = rsi.rsi_below(30)
            l_exits = rsi.rsi_above(70)
            pf_long = vbt.Portfolio.from_signals(close_price, l_entries, l_exits, fees=0.001, freq='1D')
            process_results(pf_long, rsi_windows, "RSI Long", ticker, all_results, close_price, l_entries, l_exits)

            # Short
            s_entries = rsi.rsi_above(70)
            s_exits = rsi.rsi_below(30)
            pf_short = vbt.Portfolio.from_signals(close_price, short_entries=s_entries, short_exits=s_exits, fees=0.001, freq='1D')
            process_results(pf_short, rsi_windows, "RSI Short", ticker, all_results, close_price, s_entries, s_exits)

            # --- STRATEGY 2: BOLLINGER ---
            bb_windows = np.arange(5, 60, 1)
            bb = vbt.BBANDS.run(close_price, window=bb_windows, alpha=2.0)
            
            # Long
            bb_l_entries = bb.lower.gt(close_price, axis=0)
            bb_l_exits = bb.upper.lt(close_price, axis=0)
            pf_bb_long = vbt.Portfolio.from_signals(close_price, bb_l_entries, bb_l_exits, fees=0.001, freq='1D')
            process_results(pf_bb_long, bb_windows, "BB Long", ticker, all_results, close_price, bb_l_entries, bb_l_exits)

            # Short
            bb_s_entries = bb.upper.lt(close_price, axis=0)
            bb_s_exits = bb.lower.gt(close_price, axis=0)
            pf_bb_short = vbt.Portfolio.from_signals(close_price, short_entries=bb_s_entries, short_exits=bb_s_exits, fees=0.001, freq='1D')
            process_results(pf_bb_short, bb_windows, "BB Short", ticker, all_results, close_price, bb_s_entries, bb_s_exits)
            
        except Exception as e:
            print(f"⚠️ Error on {ticker}: {e}")

    # --- UPLOAD ---
    if all_results:
        # Sort by Robustness
        all_results.sort(key=lambda x: x['robustness_score'], reverse=True)
        top_results = all_results[:500]
        
        print(f"✅ Found {len(all_results)} strategies. Uploading Top {len(top_results)}...")
        
        try:
            # 1. Clear Old Data
            db_client.table("strategy_leaderboard").delete().neq("robustness_score", -1).execute()
            
            # 2. Batch Upload (Chunk size 100)
            chunk_size = 100
            for i in range(0, len(top_results), chunk_size):
                chunk = top_results[i:i + chunk_size]
                print(f"   Uploading batch {i} to {i + len(chunk)}...")
                db_client.table("strategy_leaderboard").insert(chunk).execute()
            
            success_msg = f"✅ **Scan Complete**\nTop {len(top_results)} strategies uploaded."
            print(success_msg)
            send_discord_log(success_msg, 0x2ecc71)
            
        except Exception as e:
            error_msg = f"❌ Database Upload Error: {e}"
            print(error_msg)
            send_discord_log(error_msg, 0xe74c3c)
            
        csv_results = [{k: v for k, v in res.items() if k != 'equity_curve'} for res in top_results]
        pd.DataFrame(csv_results).to_csv("scan_results.csv", index=False)
    else:
        msg = "⚠️ Scan Complete but NO robust strategies found."
        print(msg)
        send_discord_log(msg, 0xf1c40f)

if __name__ == "__main__":
    run_parameter_sweep()