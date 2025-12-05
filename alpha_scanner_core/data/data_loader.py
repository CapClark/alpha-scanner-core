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