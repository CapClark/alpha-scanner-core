import os
from dotenv import load_dotenv

load_dotenv()

class Settings:
    POLYGON_API_KEY = os.getenv("POLYGON_API_KEY", "MOCK_KEY_FOR_TESTING")

    TICKERS = [
        'AAPL', 'MSFT', 'AMZN', 'GOOGL', 'META', 'NVDA', 'ADBE', 'CRM', 'ORCL', 'IBM',
        'SAP', 'NOW', 'INTU', 'PANW', 'CSCO', 'SNOW', 'PLTR', 'DELL', 'HPQ',
        'AMD', 'QCOM', 'INTC', 'TXN', 'MU', 'AVGO', 'ASML', 'LRCX', 'AMAT', 'ADI', 'KLAC',
        'JPM', 'BAC', 'WFC', 'GS', 'MS', 'SCHW', 'BLK', 'BRK-B', 'C', 'PNC', 'USB', 'COF', 'TFC',
        'V', 'MA', 'PYPL', 'SQ', 'AXP', 'COIN', 'HOOD', 'SOFI', 'AFRM',
        'JNJ', 'LLY', 'MRK', 'PFE', 'ABBV', 'NVO', 'GILD', 'VRTX', 'REGN', 'AMGN', 'BMY', 'AZN', 'NVS',
        'UNH', 'CVS', 'ELV', 'CI', 'HCA', 'MDT', 'ISRG', 'TMO', 'DHR', 'SYK', 'BSX',
        'WMT', 'COST', 'TGT', 'HD', 'LOW', 'NKE', 'LULU', 'ETSY', 'TJX', 'ROST',
        'TSLA', 'F', 'GM', 'BKNG', 'ABNB', 'UBER', 'LYFT', 'RIVN', 'MAR', 'HLT', 'DAL', 'UAL',
        'MCD', 'SBUX', 'YUM', 'CMG', 'DPZ',
        'PG', 'KO', 'PEP', 'PM', 'MO', 'EL', 'CL', 'KMB', 'MDLZ', 'GIS', 'KHC', 'CLX',
        'CAT', 'DE', 'GE', 'HON', 'LMT', 'BA', 'UPS', 'FDX', 'WM', 'RTX', 'UNP', 'CSX', 'NSC',
        'XOM', 'CVX', 'SHEL', 'TTE', 'COP', 'SLB', 'HAL', 'EOG', 'BP', 'PXD', 'MPC', 'PSX',
        'DIS', 'NFLX', 'CMCSA', 'TMUS', 'VZ', 'T', 'SPOT', 'WBD', 'PARA',
        'LIN', 'APD', 'SHW', 'NUE', 'FCX', 'ECL', 'DOW', 'NEM',
        'IREN', 'MARA', 'RIOT', 'MSTR', 'CLSK',
        'AMT', 'PLD', 'EQIX', 'SPG', 'WELL', 'O'
    ]

    MIN_TRADE_COUNT = 5
    START_DATE = "2020-01-01"
    DATA_CACHE_DIR = "datasets/cache"

settings = Settings()
