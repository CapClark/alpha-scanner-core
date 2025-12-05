import os

# Define the correct content for the critical files
files_to_fix = {
    "alpha_scanner_core/config/settings.py": """
import os
from dotenv import load_dotenv

load_dotenv()

class Settings:
    POLYGON_API_KEY = os.getenv("POLYGON_API_KEY", "MOCK_KEY_FOR_TESTING")
    TICKERS = ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "TSLA"]
    MIN_TRADE_COUNT = 10
    START_DATE = "2022-01-01"
    WEIGHT_PROFIT_FACTOR = 0.4
    WEIGHT_TOTAL_RETURN = 0.3
    WEIGHT_DRAWDOWN = 0.3
    DATA_CACHE_DIR = "datasets/cache"

settings = Settings()
""",

    "alpha_scanner_core/data/caching.py": """
import os
import pandas as pd
from datetime import datetime
from alpha_scanner_core.config.settings import settings

def get_cache_filepath(ticker: str) -> str:
    if not os.path.exists(settings.DATA_CACHE_DIR):
        os.makedirs(settings.DATA_CACHE_DIR)
    return os.path.join(settings.DATA_CACHE_DIR, f"{ticker}_prices.csv")

def save_to_cache(ticker: str, df: pd.DataFrame):
    filepath = get_cache_filepath(ticker)
    df.to_csv(filepath, index=True)

def load_from_cache(ticker: str):
    filepath = get_cache_filepath(ticker)
    if os.path.exists(filepath):
        if (datetime.now() - datetime.fromtimestamp(os.path.getmtime(filepath))).total_seconds() < 86400:
            return pd.read_csv(filepath, index_col=0, parse_dates=True)
    return None
""",

    "alpha_scanner_core/data/data_loader.py": """
import os
import pandas as pd
from polygon import RESTClient
from dotenv import load_dotenv
from alpha_scanner_core.config.settings import settings
from alpha_scanner_core.data.caching import save_to_cache, load_from_cache

load_dotenv()
api_key = os.getenv("POLYGON_API_KEY")

if api_key:
    client = RESTClient(api_key)
else:
    client = None
    print("⚠️ Warning: POLYGON_API_KEY not found. Real data fetch will fail.")

def fetch_stock_data(ticker: str):
    cached_data = load_from_cache(ticker)
    if cached_data is not None:
        return cached_data

    if not client:
        return None

    try:
        start_date = settings.START_DATE
        end_date = "2024-12-31"

        aggs = []
        for a in client.list_aggs(ticker, 1, 'day', start_date, end_date, limit=50000):
            aggs.append(a)

        if not aggs:
            print(f"  ⚠️ No data found for {ticker}")
            return None

        df = pd.DataFrame(aggs)
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df.set_index('timestamp', inplace=True)

        df.rename(columns={
            'open': 'Open', 'high': 'High', 'low': 'Low', 'close': 'Close', 'volume': 'Volume'
        }, inplace=True)

        data = df['Close']
        save_to_cache(ticker, data)
        return data

    except Exception as e:
        print(f"  ❌ Error fetching {ticker}: {e}")
        return None
""",

    "alpha_scanner_core/strategies/__init__.py": """
from .strategies import (
    get_rsi_signals,
    get_bb_signals,
    get_sma_signals,
    get_macd_signals,
    get_rsi_trend_signals
)
""",

    "alpha_scanner_core/strategies/strategies.py": """
import vectorbt as vbt
import numpy as np
import pandas as pd

def get_rsi_signals(close_price, length=14, oversold=30, overbought=70):
    \"\"\"RSI Mean Reversion Strategy\"\"\"
    rsi = vbt.RSI.run(close_price, window=length).rsi
    entries = rsi.vbt.crossed_below(oversold)
    exits = rsi.vbt.crossed_above(overbought)
    return entries, exits

def get_bb_signals(close_price, window=20, std=2.0):
    \"\"\"Bollinger Band Mean Reversion\"\"\"
    ma = vbt.MA.run(close_price, window=window).ma
    rolling_std = close_price.rolling(window=window).std()
    upper_band = ma + (rolling_std * std)
    lower_band = ma - (rolling_std * std)

    entries = close_price.vbt.crossed_below(lower_band)
    exits = close_price.vbt.crossed_above(ma)
    return entries, exits

def get_sma_signals(close_price, fast_window=50, slow_window=200):
    \"\"\"SMA Trend Following\"\"\"
    fast_ma = vbt.MA.run(close_price, window=fast_window).ma
    slow_ma = vbt.MA.run(close_price, window=slow_window).ma

    entries = fast_ma.vbt.crossed_above(slow_ma)
    exits = fast_ma.vbt.crossed_below(slow_ma)
    return entries, exits

def get_macd_signals(close_price, fast=12, slow=26, signal=9):
    \"\"\"MACD Momentum Strategy\"\"\"
    macd = vbt.MACD.run(close_price, fast_window=fast, slow_window=slow, signal_window=signal)
    entries = macd.macd_crossed_above(macd.signal)
    exits = macd.macd_crossed_below(macd.signal)
    return entries, exits

def get_rsi_trend_signals(close_price, rsi_len=14, sma_len=200):
    \"\"\"RSI + Trend Filter (Regime Detection)\"\"\"
    rsi = vbt.RSI.run(close_price, window=rsi_len).rsi
    sma = vbt.MA.run(close_price, window=sma_len).ma

    cond_oversold = rsi < 30
    cond_uptrend = close_price > sma

    # Entry: RSI crossed below 30 AND Price > SMA
    entries = rsi.vbt.crossed_below(30) & cond_uptrend
    exits = rsi.vbt.crossed_above(70)

    return entries, exits
"""
}

print("🔧 REPAIRING FILES...")
for path, content in files_to_fix.items():
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(content.strip())
    print(f"  ✅ Fixed: {path}")

print("\n✨ Repair Complete. Try running 'python run.py' now.")
