import pandas as pd
import time
from data_loader import get_polygon_data
from strategies import (
    get_rsi_signals,
    get_bb_signals,
    get_sma_signals,
    get_macd_signals,
    get_rsi_trend_signals
)
from analyzer import run_backtest, calculate_robustness

# --- CONFIG ---
START_DATE = "2019-01-01"
END_DATE = "2024-01-01"

# Top 100+ Liquid US Stocks by Sector
TICKERS = [
    # Tech Giants
    'AAPL', 'MSFT', 'GOOGL', 'AMZN', 'META', 'TSLA', 'NVDA', 'NFLX', 'ADBE', 'CRM', 'AMD', 'INTC', 'QCOM', 'TXN', 'AVGO',
    # Financials
    'JPM', 'BAC', 'WFC', 'C', 'GS', 'MS', 'BLK', 'V', 'MA', 'AXP', 'PYPL', 'SQ', 'COIN', 'HOOD', 'SOFI',
    # Consumer
    'WMT', 'TGT', 'COST', 'HD', 'LOW', 'NKE', 'SBUX', 'MCD', 'DIS', 'CMCSA', 'TMUS', 'VZ', 'T', 'F', 'GM',
    # Healthcare
    'JNJ', 'UNH', 'PFE', 'LLY', 'MRK', 'ABBV', 'TMO', 'DHR', 'BMY', 'AMGN', 'CVS',
    # Energy & Ind
    'XOM', 'CVX', 'COP', 'SLB', 'EOG', 'CAT', 'DE', 'GE', 'HON', 'LMT', 'RTX', 'BA', 'UPS', 'FDX', 'WM',
    # ETFs (Indices)
    'SPY', 'QQQ', 'IWM', 'DIA', 'TLT', 'GLD', 'SLV', 'USO', 'XLK', 'XLF', 'XLE', 'XLV', 'XLY', 'XLP', 'XLI', 'XLB', 'XLRE', 'XLU'
]

leaderboard = []

print(f"🚀 Alpha Scanner Starting... Analyzing {len(TICKERS)} tickers.")

for ticker in TICKERS:
    print(f"\n🔍 Fetching {ticker}...")

    # 1. GET DATA
    close_price = get_polygon_data(ticker, START_DATE, END_DATE)

    if close_price is None or close_price.empty:
        continue

    # ---------------------------------------
    # STRATEGY 1: RSI (Parameter Sweep)
    # ---------------------------------------
    for length in [10, 14, 21, 30]:
        entries, exits = get_rsi_signals(close_price, length=length)
        pf = run_backtest(close_price, entries, exits)
        results = calculate_robustness(pf)
        if results:
            results.update({'ticker': ticker, 'strategy': f"RSI ({length})"})
            leaderboard.append(results)

    # ---------------------------------------
    # STRATEGY 2: Bollinger Bands
    # ---------------------------------------
    for win in [20, 30, 50]:
        for std in [2.0, 2.5]:
            entries, exits = get_bb_signals(close_price, window=win, std=std)
            pf = run_backtest(close_price, entries, exits)
            results = calculate_robustness(pf)
            if results:
                results.update({'ticker': ticker, 'strategy': f"BBands ({win}, {std})"})
                leaderboard.append(results)

    # ---------------------------------------
    # STRATEGY 3: SMA Crossover
    # ---------------------------------------
    for fast, slow in [(10, 50), (20, 100), (50, 200)]:
        entries, exits = get_sma_signals(close_price, fast, slow)
        pf = run_backtest(close_price, entries, exits)
        results = calculate_robustness(pf)
        if results:
            results.update({'ticker': ticker, 'strategy': f"SMA Cross ({fast}/{slow})"})
            leaderboard.append(results)

    # ---------------------------------------
    # STRATEGY 4: MACD (New)
    # ---------------------------------------
    # Standard 12, 26, 9 vs Slower 24, 52, 9
    for f, s in [(12, 26), (24, 52)]:
        entries, exits = get_macd_signals(close_price, fast=f, slow=s)
        pf = run_backtest(close_price, entries, exits)
        results = calculate_robustness(pf)
        if results:
            results.update({'ticker': ticker, 'strategy': f"MACD ({f}/{s})"})
            leaderboard.append(results)

    # ---------------------------------------
    # STRATEGY 5: RSI + Trend (New)
    # ---------------------------------------
    for rsi_len in [14, 21]:
        entries, exits = get_rsi_trend_signals(close_price, rsi_len=rsi_len, sma_len=200)
        pf = run_backtest(close_price, entries, exits)
        results = calculate_robustness(pf)
        if results:
            results.update({'ticker': ticker, 'strategy': f"RSI({rsi_len}) + Trend"})
            leaderboard.append(results)

# --- FINAL REPORT ---
print("\n" + "="*60)
print("🏆 FINAL ROBUSTNESS LEADERBOARD 🏆")
print("="*60)

if not leaderboard:
    print("No robust strategies found. Try expanding params or lowering min_trades.")
else:
    df = pd.DataFrame(leaderboard)
    # Sort by Robustness Score
    df = df.sort_values(by='robustness_score', ascending=False)

    cols = ['ticker', 'strategy', 'robustness_score', 'profit_factor', 'trade_count', 'total_return']
    print(df[cols].head(30).to_string(index=False, float_format="%.2f"))

    # Optional: Save to CSV for analysis
    df.to_csv("scan_results.csv", index=False)
    print("\n✅ Results saved to scan_results.csv")

print("✅ Scan Complete.")
