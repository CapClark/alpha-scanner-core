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