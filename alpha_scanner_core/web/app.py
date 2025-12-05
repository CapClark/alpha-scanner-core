# alpha_scanner_core/web/app.py

import streamlit as st
import pandas as pd
import numpy as np

# --- STRATEGY SIGNALS ---
from alpha_scanner_core.strategies.strategies import (
    get_rsi_signals,
    get_bb_signals,
    get_sma_signals
)

# --- BACKTESTING & ANALYSIS ---
from alpha_scanner_core.engine.backtester import run_simple_backtest
from alpha_scanner_core.engine.robustness_score import calculate_robustness_metrics
from alpha_scanner_core.analysis.stability_analysis import analyze_stability

# --- DATA LOADER ---
from alpha_scanner_core.data.data_loader import fetch_stock_data

# --- PAGE CONFIG ---
st.set_page_config(page_title="StrategyGrade", page_icon="🎓", layout="centered")

st.title("🎓 StrategyGrade")
st.markdown("### The 'Carfax' for Trading Strategies")
st.markdown("Stop trading overfit strategies. Get a Robustness Score.")

# --- SIDEBAR INPUTS ---
st.sidebar.header("Configuration")
ticker = st.sidebar.text_input("Ticker Symbol", value="AAPL").upper()
strategy_type = st.sidebar.selectbox("Strategy", ["RSI Mean Reversion", "Bollinger Bands", "SMA Trend"])

# --- DYNAMIC PARAMETERS BASED ON STRATEGY ---
if strategy_type == "RSI Mean Reversion":
    param_name = "length"
    base_param = st.sidebar.number_input("RSI Length", value=14, min_value=2)
    func = get_rsi_signals
    other_params = {'oversold': 30, 'overbought': 70}

elif strategy_type == "Bollinger Bands":
    param_name = "window"
    base_param = st.sidebar.number_input("BB Window", value=20, min_value=5)
    func = get_bb_signals
    other_params = {'std': 2.0}

elif strategy_type == "SMA Trend":
    param_name = "fast_window"
    base_param = st.sidebar.number_input("Fast MA Window", value=50, min_value=5)
    func = get_sma_signals
    other_params = {'slow_window': 200}

# --- RUN STRATEGY & ANALYSIS ---
if st.sidebar.button("Grade Strategy", type="primary"):
    with st.spinner(f"Fetching data and crunching numbers for {ticker}..."):

        # 1. GET DATA
        data = fetch_stock_data(ticker, "2020-01-01", "2024-01-01")

        if data is None or data.empty:
            st.error("❌ No data found. Check ticker or API key.")
        else:
            # 2. RUN BASELINE BACKTEST
            entries, exits = func(data, **{param_name: base_param}, **other_params)
            pf = run_simple_backtest(data, entries, exits)
            stats = calculate_robustness_metrics(pf, min_trades=2)

            if not stats:
                st.error("❌ Not enough trades to grade.")
            else:
                # 3. RUN STABILITY ANALYSIS
                stability = analyze_stability(data, func, param_name, base_param, other_params)

                # 4. CALCULATE FINAL GRADE
                perf_score = min(100, stats['profit_factor'] * 20)
                stab_score = stability['stability_score']
                final_score = (perf_score * 0.5) + (stab_score * 0.5)

                if final_score >= 90: grade, color = "A", "green"
                elif final_score >= 80: grade, color = "B", "blue"
                elif final_score >= 70: grade, color = "C", "orange"
                elif final_score >= 60: grade, color = "D", "orange"
                else: grade, color = "F", "red"

                # --- DISPLAY DASHBOARD ---

                # Top Row: Grade
                col1, col2 = st.columns([1, 2])
                with col1:
                    st.markdown(f"<h1 style='text-align: center; color: {color}; font-size: 80px;'>{grade}</h1>", unsafe_allow_html=True)
                    st.markdown(f"<p style='text-align: center;'><b>Score: {final_score:.1f}/100</b></p>", unsafe_allow_html=True)
                with col2:
                    st.metric("Profit Factor", f"{stats['profit_factor']:.2f}")
                    st.metric("Total Return", f"{stats['total_return']:.2f}%")
                    st.metric("Trade Count", stats['trade_count'])

                st.divider()

                # Middle Row: Stability Analysis
                st.subheader("🔍 Stability Analysis")
                st.write(f"We tested {param_name} from {stability['tested_values'][0]} to {stability['tested_values'][-1]}")

                chart_data = pd.DataFrame({
                    "Parameter": stability['tested_values'],
                    "Return %": stability['returns']
                }).set_index("Parameter")

                st.bar_chart(chart_data)

                if stab_score < 50:
                    st.warning("⚠️ **Unstable Strategy:** Changing the parameter slightly causes returns to crash. This strategy is likely overfit.")
                else:
                    st.success("✅ **Stable Strategy:** Results are consistent across similar parameters.")

                # Bottom: Drill Down Raw Data
                with st.expander("See Raw Data"):
                    st.write(stats)
                    st.write(stability)
