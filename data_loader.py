import os
from polygon import RESTClient
from datetime import datetime, timedelta
import pandas as pd
import time
from dotenv import load_dotenv

# Load API key from .env file
load_dotenv()
api_key = os.getenv("POLYGON_API_KEY")

if not api_key:
    raise ValueError("❌ Missing POLYGON_API_KEY in .env file")

client = RESTClient(api_key)

def get_polygon_data(ticker, start_date, end_date):
    """
    Fetches daily OHLCV data from Polygon.io and formats it for VectorBT.
    """
    try:
        # Polygon expects 'YYYY-MM-DD'
        aggs = []
        # Fetch daily bars (multiplier=1, timespan='day')
        for a in client.list_aggs(ticker, 1, 'day', start_date, end_date, limit=50000):
            aggs.append(a)

        if not aggs:
            print(f"  ⚠️ No data found for {ticker}")
            return None

        # Convert to DataFrame
        df = pd.DataFrame(aggs)

        # Polygon timestamp is in milliseconds. Convert to DateTime.
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df.set_index('timestamp', inplace=True)

        # Rename columns to standard format (lowercase for vectorbt compatibility if needed)
        # Map: o->open, h->high, l->low, c->close, v->volume
        df.rename(columns={
            'open': 'Open',
            'high': 'High',
            'low': 'Low',
            'close': 'Close',
            'volume': 'Volume'
        }, inplace=True)

        # Return just the Close price (Series) for simple backtests,
        # or the whole DF if you need more.
        return df['Close']

    except Exception as e:
        print(f"  ❌ Error fetching {ticker}: {e}")
        return None
