# alpha_scanner_core/data/data_loader.py

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


def fetch_stock_data(ticker: str, start_date: str = None, end_date: str = None) -> pd.DataFrame | None:
    """
    Fetches historical daily stock data for a given ticker from Polygon.io.
    Uses cache if available.

    Args:
        ticker (str): Stock symbol (e.g., "AAPL").
        start_date (str, optional): Start date in "YYYY-MM-DD". Defaults to settings.START_DATE.
        end_date (str, optional): End date in "YYYY-MM-DD". Defaults to "2024-12-31".

    Returns:
        pd.DataFrame | None: Daily Close prices with timestamp index or None if failed.
    """

    # Try cache first
    cached_data = load_from_cache(ticker)
    if cached_data is not None:
        return cached_data

    if not client:
        print(f"⚠️ No Polygon client initialized. Cannot fetch data for {ticker}.")
        return None

    start_date = start_date or settings.START_DATE
    end_date = end_date or "2024-12-31"

    try:
        aggs = []
        for agg in client.list_aggs(ticker, 1, 'day', start_date, end_date, limit=50000):
            aggs.append(agg)

        if not aggs:
            print(f"⚠️ No data found for {ticker}")
            return None

        df = pd.DataFrame(aggs)
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df.set_index('timestamp', inplace=True)
        df.rename(columns={
            'open': 'Open',
            'high': 'High',
            'low': 'Low',
            'close': 'Close',
            'volume': 'Volume'
        }, inplace=True)

        data = df[['Close']]  # return only Close column; adjust if you need OHLCV
        save_to_cache(ticker, data)
        return data

    except Exception as e:
        print(f"❌ Error fetching data for {ticker}: {e}")
        return None
