# ==========================================================
# 📊 CRSP "ALPHA SCANNER" - VERBOSE DEBUG MODE (FIXED)
# ==========================================================
# ✅ Sets MIN_TRADE_COUNT = 5 (Easier to pass)
# ✅ Prints trade counts for EVERY test so you can see what's happening
# ✅ Fixed 'HOLD_PERIOD' NameError

import wrds
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import warnings
import sys

warnings.simplefilter(action='ignore')
plt.style.use("seaborn-v0_8-whitegrid")
pd.set_option('display.max_rows', None)
pd.set_option('display.width', 1000)

print("Libraries imported!")

# ------------------------------------------
# ⚙️ CONFIG
# ------------------------------------------
TICKERS = [
    'AAPL', 'MSFT', 'AMZN', 'GOOGL', 'META', 'NFLX', 'TSLA',
    'NVDA', 'AMD', 'JPM', 'V', 'PG', 'JNJ', 'UNH', 'XOM', 'CVX', 'KO', 'PEP'
]

START_DATE = "2018-01-01"
END_DATE = "2024-12-31"
MIN_TRADE_COUNT = 5  # Lowered to 5 to ensure we see results
HOLD_PERIOD = 5      # <-- ADDED THIS MISSING VARIABLE

RSI_LENGTHS = [14, 21]
SMA_WINDOWS = [50, 200]
BB_WINDOWS = [20]
BB_STDS = [2.0]

# ------------------------------------------
# 1️⃣ Connect to WRDS
# ------------------------------------------
db = None
data = None
try:
    print("🔗 Connecting to WRDS...")
    db = wrds.Connection()
    if not hasattr(db.connection, "cursor"):
        db.connection = db.connection.connection
    print("✅ WRDS Connection Successful.")

    # ------------------------------------------
    # 2️⃣ Fetch Data
    # ------------------------------------------
    print(f"🔍 Looking up PERMNOs...")
    ticker_tuple = tuple(TICKERS)
    lookup_query = f"""
        SELECT DISTINCT permno, ticker
        FROM crsp.stocknames
        WHERE ticker IN {ticker_tuple}
        AND ncusip IS NOT NULL
    """
    permno_df = db.raw_sql(lookup_query)
    PERMNO_TUPLE = tuple(permno_df['permno'].astype(int).unique().tolist())
    permno_to_ticker_map = pd.Series(permno_df.ticker.values, index=permno_df.permno).to_dict()

    print(f"📥 Downloading daily data...")
    query = f"""
        SELECT date, permno, prc, ret, vol
        FROM crsp.dsf
        WHERE permno IN {PERMNO_TUPLE}
          AND date >= '{START_DATE}'
          AND date <= '{END_DATE}'
        ORDER BY permno, date ASC;
    """
    data = db.raw_sql(query)
    print("✅ Data download complete!")

except Exception as e:
    print(f"Error: {e}")
    if db: db.close()
    sys.exit()

finally:
    if db: db.close()

# ------------------------------------------
# 3️⃣ Clean Data
# ------------------------------------------
if data is not None:
    data['date'] = pd.to_datetime(data['date'])
    data = data.set_index('date')
    data['prc'] = data['prc'].abs()
    data['ticker'] = data['permno'].map(permno_to_ticker_map)
    data = data.dropna(subset=['prc', 'ticker'])
else:
    sys.exit()

# ------------------------------------------
# 4️⃣ Helper Functions
# ------------------------------------------
def calculate_rsi(series, length=14):
    delta = series.diff().fillna(0)
    gain = np.where(delta > 0, delta, 0)
    loss = np.where(delta < 0, -delta, 0)
    avg_gain = pd.Series(gain, index=series.index).ewm(alpha=1/length, adjust=False).mean()
    avg_loss = pd.Series(loss, index=series.index).ewm(alpha=1/length, adjust=False).mean()
    rs = avg_gain / avg_loss
    rs[avg_loss == 0] = np.inf
    return 100 - (100 / (1 + rs))

def evaluate_strategy(df, signal_col, fwd_ret_col='fwd_return'):
    # Find crossover events (change in state)
    trade_signals = df[signal_col].diff().fillna(0)
    active_trades = df[trade_signals != 0].dropna(subset=[signal_col, fwd_ret_col])

    trade_count = len(active_trades)
    if trade_count == 0: return 0, np.nan, np.nan

    trade_returns = active_trades[signal_col] * active_trades[fwd_ret_col]
    total_gain = trade_returns[trade_returns > 0].sum()
    total_loss = np.abs(trade_returns[trade_returns < 0].sum())

    # Avoid division by zero
    if total_loss == 0:
        profit_factor = 100.0 if total_gain > 0 else 0.0
    else:
        profit_factor = total_gain / total_loss

    avg_return = trade_returns.mean() * 100

    return trade_count, avg_return, profit_factor

# ------------------------------------------
# 5️⃣ Main Loop (VERBOSE MODE)
# ------------------------------------------
print(f"\n🔬 Starting verbose analysis (Min Trades: {MIN_TRADE_COUNT})...")
results_list = []

for permno, group in data.groupby('permno'):
    ticker = group['ticker'].iloc[0]
    df = group.copy().sort_index()

    # Calculate forward returns (using HOLD_PERIOD)
    df['fwd_return'] = df['prc'].shift(-HOLD_PERIOD) / df['prc'] - 1

    print(f"  > Analyzing {ticker} ({len(df)} rows)...")

    # --- RSI ---
    for length in RSI_LENGTHS:
        df['RSI'] = calculate_rsi(df['prc'], length)
        conditions = [(df['RSI'] < 30).fillna(False), (df['RSI'] > 70).fillna(False)]
        df['sig_rsi'] = np.select(conditions, [1, -1], default=0)

        count, avg, pf = evaluate_strategy(df, 'sig_rsi')

        if count > 0:
            print(f"    - RSI({length}): {count} trades | PF: {pf:.2f}")

        if count >= MIN_TRADE_COUNT:
            results_list.append({'ticker': ticker, 'strategy': 'RSI', 'params': f'len={length}',
                                 'trade_count': count, 'profit_factor': pf, 'avg_return': avg})

    # --- SMA ---
    for win in SMA_WINDOWS:
        df['SMA'] = df['prc'].rolling(win).mean()
        conditions = [(df['prc'] > df['SMA']).fillna(False), (df['prc'] < df['SMA']).fillna(False)]
        df['sig_sma'] = np.select(conditions, [1, -1], default=0)

        count, avg, pf = evaluate_strategy(df, 'sig_sma')

        if count > 0:
            print(f"    - SMA({win}): {count} trades | PF: {pf:.2f}")

        if count >= MIN_TRADE_COUNT:
            results_list.append({'ticker': ticker, 'strategy': 'SMA', 'params': f'win={win}',
                                 'trade_count': count, 'profit_factor': pf, 'avg_return': avg})

    # --- BB ---
    for win in BB_WINDOWS:
        rm = df['prc'].rolling(win).mean()
        rstd = df['prc'].rolling(win).std()
        lower = rm - (2.0 * rstd)
        upper = rm + (2.0 * rstd)
        conditions = [(df['prc'] < lower).fillna(False), (df['prc'] > upper).fillna(False)]
        df['sig_bb'] = np.select(conditions, [1, -1], default=0)

        count, avg, pf = evaluate_strategy(df, 'sig_bb')

        if count > 0:
            print(f"    - BB({win}): {count} trades | PF: {pf:.2f}")

        if count >= MIN_TRADE_COUNT:
            results_list.append({'ticker': ticker, 'strategy': 'BB', 'params': f'win={win}',
                                 'trade_count': count, 'profit_factor': pf, 'avg_return': avg})

# ------------------------------------------
# 6️⃣ Report
# ------------------------------------------
print("\n✅ Analysis complete!")

if not results_list:
    print("❌ STILL NO RESULTS. The data might be too short, or parameters too strict.")
else:
    results_df = pd.DataFrame(results_list)
    # Log-score for robustness
    results_df['score'] = results_df['profit_factor'] * np.log(results_df['trade_count'])
    results_df = results_df.sort_values(by='score', ascending=False)

    print("\n" + "="*60)
    print(f"🏆 LEADERBOARD (Min {MIN_TRADE_COUNT} Trades) 🏆")
    print("="*60)
    print(results_df.head(20).to_string(index=False, float_format="{:.2f}".format))
