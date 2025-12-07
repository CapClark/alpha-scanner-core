import sys
import os
import streamlit as st
import pandas as pd
import numpy as np
import vectorbt as vbt

# --- PATH SETUP ---
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(current_dir, '../../'))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from alpha_scanner_core.data.data_loader import fetch_stock_data
from alpha_scanner_core.engine.robustness_score import calculate_robustness_metrics
from alpha_scanner_core.engine.monte_carlo import run_monte_carlo_test
from alpha_scanner_core.strategies.strategies import (
    get_rsi_signals, get_bb_signals, get_sma_signals, get_rsi_trend_signals
)

# --- APP CONFIG ---
st.set_page_config(page_title="StrategyGrade", page_icon="🎓", layout="wide")

# --- CACHING ---
@st.cache_data(ttl=3600)
def get_data_cached(ticker):
    data = fetch_stock_data(ticker)
    if data is not None:
        if isinstance(data, pd.DataFrame):
            if 'Close' in data.columns: data = data['Close']
            elif 'close' in data.columns: data = data['close']
            else: data = data.iloc[:, 0]
        
        # CLEANING: Remove timezone and index name to prevent join errors
        data.index = pd.to_datetime(data.index).tz_localize(None)
        data.index.name = None 
    return data

@st.cache_data
def run_monte_carlo_cached(data, strat_name, params, iterations=50):
    if strat_name == "RSI Mean Reversion": func = get_rsi_signals
    elif strat_name == "Bollinger Bands": func = get_bb_signals
    elif strat_name == "SMA Trend": func = get_sma_signals
    elif strat_name == "RSI + Trend Filter": func = get_rsi_trend_signals
    else: return None
    
    return run_monte_carlo_test(data, func, params, iterations)

# --- UI ---
st.title("🎓 StrategyGrade")
st.markdown("### The Truth Engine for Trading Strategies")

st.sidebar.header("Configuration")
ticker = st.sidebar.text_input("Ticker Symbol", value="AAPL").upper()
strategy_type = st.sidebar.selectbox("Strategy Type", 
    ["RSI Mean Reversion", "Bollinger Bands", "SMA Trend", "RSI + Trend Filter"]
)

if strategy_type == "RSI Mean Reversion":
    length = st.sidebar.slider("RSI Length", 2, 30, 14)
    func = get_rsi_signals
    params = {'length': length, 'oversold': 30, 'overbought': 70}
elif strategy_type == "Bollinger Bands":
    window = st.sidebar.slider("Window", 10, 50, 20)
    std = st.sidebar.slider("Std Dev", 1.0, 3.0, 2.0, 0.1)
    func = get_bb_signals
    params = {'window': window, 'std': std}
elif strategy_type == "SMA Trend":
    fast = st.sidebar.slider("Fast MA", 10, 100, 50)
    slow = st.sidebar.slider("Slow MA", 50, 200, 200)
    func = get_sma_signals
    params = {'fast_window': fast, 'slow_window': slow}
elif strategy_type == "RSI + Trend Filter":
    rsi_len = st.sidebar.slider("RSI Length", 2, 30, 14)
    sma_len = st.sidebar.slider("Trend SMA", 50, 300, 200)
    func = get_rsi_trend_signals
    params = {'rsi_len': rsi_len, 'sma_len': sma_len}

if st.sidebar.button("Grade Strategy", type="primary"):
    with st.spinner(f"Fetching data for {ticker}..."):
        data = get_data_cached(ticker)
    
    if data is None or data.empty:
        st.error(f"❌ No data found for {ticker}.")
    else:
        try:
            # 1. Run Logic
            entries, exits = func(data, **params)
            
            # --- FINAL SANITIZATION FIX ---
            # Force signals to match data index exactly
            # Extract values if they are Series, fill NaNs, and re-wrap with clean index
            
            # Convert to numpy array to strip bad index metadata
            entry_vals = entries.values if isinstance(entries, (pd.Series, pd.DataFrame)) else np.array(entries)
            exit_vals = exits.values if isinstance(exits, (pd.Series, pd.DataFrame)) else np.array(exits)
            
            # Re-wrap with the CLEAN data index
            entries_clean = pd.Series(entry_vals, index=data.index).fillna(False).astype(bool)
            exits_clean = pd.Series(exit_vals, index=data.index).fillna(False).astype(bool)
            # ------------------------------
            
            # 2. Run Backtest
            pf = vbt.Portfolio.from_signals(
                data, entries_clean, exits_clean, fees=0.001, freq='D'
            )
            
            # 3. Metrics
            metrics = calculate_robustness_metrics(pf, min_trades=2)
            
            if not metrics:
                st.warning("⚠️ Strategy generated 0 or 1 trade. Cannot grade robustness.")
            else:
                # 4. Monte Carlo
                with st.spinner("Running Monte Carlo Simulation..."):
                    mc_results = run_monte_carlo_cached(data, strategy_type, params, iterations=50)
                
                score = metrics['robustness_score']
                p_value = mc_results.get('p_value', 1.0) if mc_results else 1.0
                
                if p_value > 0.05: grade, color, verdict = "D", "red", "Luck Likely"
                elif score > 20: grade, color, verdict = "A", "green", "Excellent"
                elif score > 10: grade, color, verdict = "B", "blue", "Good"
                elif score > 5: grade, color, verdict = "C", "orange", "Average"
                else: grade, color, verdict = "F", "red", "Weak"

                if p_value <= 0.05 and score > 5: verdict = "Robust"

                col_grade, col_stats = st.columns([1, 2])
                with col_grade:
                    st.markdown(f"<h1 style='font-size: 90px; color: {color}; text-align: center;'>{grade}</h1>", unsafe_allow_html=True)
                    st.markdown(f"<h3 style='text-align: center;'>Score: {score:.1f} ({verdict})</h3>", unsafe_allow_html=True)
                
                with col_stats:
                    c1, c2, c3 = st.columns(3)
                    c1.metric("Profit Factor", f"{metrics['profit_factor']:.2f}")
                    c2.metric("Total Return", f"{metrics['total_return']:.2f}%")
                    c3.metric("Trade Count", int(metrics['trade_count']))
                    st.metric("Luck Probability (p-value)", f"{p_value:.2%}", delta_color="inverse")

                st.divider()
                st.subheader("Equity Curve")
                st.line_chart(pf.value())

        except Exception as e:
            st.error(f"An error occurred: {e}")
            import traceback
            st.code(traceback.format_exc())
# ... inside app.py ...

# Create Tabs
tab1, tab2 = st.tabs(["Strategy Grader", "Market Leaderboard"])

with tab1:
    # ... (Move your existing "Grade Strategy" UI code here) ...
    pass

with tab2:
    st.header("🏆 Weekly Robustness Leaderboard")
    st.markdown("The top strategies across the S&P 500, pre-calculated for robustness.")
    
    try:
        # Load the CSV generated by your CLI scanner
        # Ensure 'datasets/scan_results.csv' exists in your repo
        df = pd.read_csv(os.path.join(project_root, "datasets", "scan_results.csv"))
        
        # Format for display
        st.dataframe(
            df[['ticker', 'strategy', 'robustness_score', 'profit_factor', 'trade_count']],
            hide_index=True,
            use_container_width=True
        )
    except FileNotFoundError:
        st.warning("Leaderboard data not found. Please run the CLI scanner first.")