import os
import time
import pandas as pd
from datetime import datetime, timedelta
from polygon import RESTClient
from dotenv import load_dotenv
from alpha_scanner_core.data.database import post_signal

# 1. Load Secrets
load_dotenv()
API_KEY = os.environ.get("POLYGON_API_KEY")

if not API_KEY:
    raise ValueError("❌ Missing POLYGON_API_KEY in .env file")

# 2. Initialize Polygon Client
client = RESTClient(API_KEY)

# 3. Define Universe
TICKERS = ['AAPL', 'MSFT', 'GOOGL', 'AMZN', 'NVDA', 'TSLA', 'AMD', 'INTC', 'NFLX', 'META']

def get_polygon_data(ticker):
    """
    Fetches the last 5 days of hourly data from Polygon.
    """
    # We need enough data for MACD (26 periods + buffer)
    end_date = datetime.now()
    start_date = end_date - timedelta(days=7)

    aggs = []
    try:
        for a in client.list_aggs(
            ticker=ticker,
            multiplier=1,
            timespan='hour',
            from_=start_date.strftime('%Y-%m-%d'),
            to=end_date.strftime('%Y-%m-%d'),
            limit=50000
        ):
            aggs.append(a)
    except Exception as e:
        print(f"⚠️ Polygon Error for {ticker}: {e}")
        return None

    if not aggs:
        return None

    df = pd.DataFrame(aggs)
    df['Close'] = df['close']
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')

    return df

def calculate_rsi(data, window=14):
    """Standard RSI Formula"""
    delta = data['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=window).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=window).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def calculate_macd(data):
    """
    MACD Calculation:
    - Fast EMA: 12 periods
    - Slow EMA: 26 periods
    - MACD Line: Fast - Slow
    - Signal Line: 9 period EMA of MACD Line
    """
    fast_ema = data['Close'].ewm(span=12, adjust=False).mean()
    slow_ema = data['Close'].ewm(span=26, adjust=False).mean()

    data['MACD'] = fast_ema - slow_ema
    data['Signal_Line'] = data['MACD'].ewm(span=9, adjust=False).mean()
    return data

def scan_market():
    print(f"🔍 Scanning {len(TICKERS)} tickers via Polygon.io...")

    for ticker in TICKERS:
        try:
            df = get_polygon_data(ticker)

            # Need at least 26 candles for MACD
            if df is None or len(df) < 30:
                continue

            current_price = df['Close'].iloc[-1]

            # --- CALCULATE INDICATORS ---
            # 1. RSI
            rsi_series = calculate_rsi(df)
            current_rsi = rsi_series.iloc[-1]

            # 2. MACD
            df = calculate_macd(df)
            current_macd = df['MACD'].iloc[-1]
            current_sig = df['Signal_Line'].iloc[-1]
            prev_macd = df['MACD'].iloc[-2]
            prev_sig = df['Signal_Line'].iloc[-2]

            # --- STRATEGY LOGIC ---

            # A) RSI Strategy
            if current_rsi < 40:
                print(f"🚀 RSI BUY: {ticker} (RSI: {current_rsi:.2f})")
                post_signal(ticker, "RSI_Dip_Buy", "BUY", float(current_price), int(100 - current_rsi))
            elif current_rsi > 60:
                print(f"🔻 RSI SELL: {ticker} (RSI: {current_rsi:.2f})")
                post_signal(ticker, "RSI_Peak_Sell", "SELL", float(current_price), int(current_rsi))

            # B) MACD Strategy (Crossover)
            # Bullish Cross: MACD crossed ABOVE Signal line recently
            if prev_macd < prev_sig and current_macd > current_sig:
                print(f"⚡ MACD CROSS: {ticker} Bullish")
                post_signal(ticker, "MACD_Golden_Cross", "BUY", float(current_price), 80)

            # Bearish Cross: MACD crossed BELOW Signal line recently
            elif prev_macd > prev_sig and current_macd < current_sig:
                print(f"📉 MACD CROSS: {ticker} Bearish")
                post_signal(ticker, "MACD_Death_Cross", "SELL", float(current_price), 80)

            # Sleep briefly to avoid rate limits
            time.sleep(0.1)

        except Exception as e:
            print(f"⚠️ Error scanning {ticker}: {e}")

if __name__ == "__main__":
    print(f"--- Alpha Scanner Initialized (RSI + MACD) ---")
    while True:
        scan_market()
        print("zzz Sleeping for 30 seconds...")
        time.sleep(30)
