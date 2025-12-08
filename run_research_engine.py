import os
import requests # For Discord Notifications
import numpy as np
import pandas as pd
import vectorbt as vbt
from dotenv import load_dotenv
from supabase import create_client

# --- IMPORTS ---
from alpha_scanner_core.data.data_loader import fetch_stock_data

# --- CONFIGURATION ---
load_dotenv()
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")

# Expanded Universe (S&P 50 + High Beta Tech)
TICKERS = [
    # Mega-cap / Core Tech
    'AAPL','MSFT','GOOGL','AMZN','NVDA','META','TSLA','AMD','INTC','IBM','ORCL',
    'CSCO','ADBE','CRM','AVGO','QCOM','TXN','MU','AMAT','LRCX','ASML','NOW',
    'SNOW','PANW','NET','CRWD','SHOP','PLTR','UBER','LYFT','SQ','PYPL','ZM',
    'DDOG','OKTA','ZS','MDB','TWLO','DOCU','ROKU','FSLY','SNAP','BIDU','NTES',

    # Major ETFs
    'SPY','QQQ','DIA','IWM','VOO','VTI','VT','ARKK','SMH','SOXX','XLE','XLF',
    'XLK','XLI','XLY','XLP','XLU','XLV','XLB','XLC','XLRE','IEMG','EEM','TLT',

    # Financials
    'JPM','BAC','WFC','GS','MS','C','BLK','SCHW','AXP','USB','PNC','COF','TROW',
    'BK','STT','AIG','CB','TRV','MET','ALL','PRU','HIG','PGR','CME','ICE','NDAQ',

    # Healthcare & Pharma
    'JNJ','LLY','PFE','MRK','ABBV','BMY','TMO','ABT','DHR','AMGN','GILD','REGN',
    'CVS','CI','HUM','UNH','ZTS','SYK','BSX','ISRG','EW','VRTX','BIIB','IQV',
    'MTD','WAT','IDXX','HOLX','ALGN','NEOG',

    # Energy & Materials
    'XOM','CVX','SLB','COP','EOG','PXD','OXY','BP','SHEL','TOT','VLO','PSX','MPC',
    'KMI','ENB','EPD','WMB','LNG','AM','OKE','FCX','NEM','GOLD','CLF','AA','STLD',
    'X','APD','LIN','SHW','ECL','DD','MLM','VMC','NUE','ALB','LYB',

    # Industrials
    'BA','CAT','DE','LMT','RTX','NOC','GD','HON','GE','MMM','ETN','EMR','ITW',
    'UPS','FDX','UNP','NSC','CSX','WM','RSG','JCI','TT','IR','PCAR','MAS','PNR',
    'CMI','PH','DOV','GWW','XYL','ROK','AOS','FAST',

    # Consumer / Retail
    'WMT','HD','LOW','TGT','COST','NKE','SBUX','MCD','CMG','KO','PEP','MDLZ',
    'KHC','CL','PG','PM','MO','UL','DEO','GIS','K','KR','DG','DLTR','CVNA',
    'EBAY','ETSY','BJ','WBA','ROST','TJX','VFC','HSY','TSN','SJM','CPB',

    # Communication Services & Media
    'NFLX','DIS','CMCSA','TMUS','VZ','T','CHTR','WBD','FOX','FOXA','SPOT','TTWO',
    'EA','PARA','LBRDK','LBTYA','LBTYK',

    # Utilities
    'NEE','DUK','SO','AEP','D','EXC','SRE','PEG','ED','XEL','WEC','ES','NRG',

    # Real Estate
    'PLD','AMT','CCI','EQIX','SPG','O','PSA','VTR','WELL','DLR','EXR','AVB',
    'EQR','MAA','UDR','ARE','BXP','HST','IRM',

    # Transportation / Travel
    'DAL','AAL','UAL','LUV','ALK','JBLU','RYAAY','CCL','RCL','NCLH','MAR','HLT',
    'ABNB','BKNG','EXPE','UBER','LYFT',

    # Automotive
    'GM','F','RIVN','LCID','NIO','LI','XPEV','TM','HMC','STLA',

    # Semiconductors (Extended)
    'TSM','ON','WOLF','ADI','MCHP','NXPI','SWKS','SLAB','MRVL','KLAC','TER',
    'COHR','ACLS','UCTT','CRUS',

    # Software (Extended)
    'INTU','MSI','ADSK','ANSS','FICO','CDNS','SNPS','PAYC','APPF','BRKS',

    # Cybersecurity (Extended)
    'FTNT','CHKP','TENB','VRNS','SAIL','S','RPD','LFVN',

    # Cloud / SaaS Mid-Cap
    'BASE','ESTC','WK','FROG','HCP','PD','BOX','EGHT','RNG','APPN','AYX',

    # Biotech Extended
    'ALNY','SRPT','ICPT','EXEL','MDGL','BLUE','XLRN','IMMU','IONS','NVAX','HALO',
    'NKTR','CRSP','EDIT','NTLA',

    # Housing, Building, Industrials Extended
    'LEN','DHI','PHM','TOL','NVR','MAS','HD','LOW','CSL','AWI','OC','MLR','ALG',

    # Metals & Mining Extended
    'TECK','HMY','SBSW','BTG','FSM','AG','PAAS','HL','GPL',

    # Regional Banks (Sampling)
    'ZION','FITB','KEY','RF','HBAN','SNV','SIVB','EWBC','CFR','MTB','BANC',

    # Insurance Extended
    'GL','PRI','RGA','UNM','LNC','AFL','CINF','HIG','TRUP',

    # REIT Extended
    'STOR','NNN','KIM','FRT','REG','MAC','BRX','WPG','EPR','CUZ','HPP',

    # Industrials / Aerospace Extended
    'AIR','HEI','SPR','HXL','TDG','TXT','ERJ','AER',

    # Agriculture
    'DE','ADM','BG','MOS','NTR','CF','AGCO','TSCO','FMC',

    # Consumer Brands Extended
    'UL','KO','PEP','MNST','CELH','WDFC','HAIN','PRGO','OTLY',

    # Crypto-related Equities
    'COIN','RIOT','MARA','MSTR','HUT','BITF','BTBT','NVDS','CLSK',

    # Asset Managers / Brokers
    'HOOD','IBKR','BEN','APO','KKR','CG','ARES','BAM','BX','TPG',

    # Telecom Extended
    'USM','TDS','LUMN','SAT','VSAT',

    # Airlines / Logistics Extended
    'KNX','SNDR','ODFL','TFII','SAIA','ZTO','YELL',

    # International ADRs (Major)
    'BABA','TCEHY','TM','SONY','DEO','UL','SAP','NVO','AZN','RIO','BHP','SNY',
    'BP','SHEL','HSBC','UBS','BUD','NGG','TOT','LFC','CHL','CHU','CHN',

    # Additional ETFs (Extended)
    'SPYG','SPYV','VUG','VTV','IWF','IWD','IJH','IJR','MTUM','QUAL','USMV',
    'SCHD','JEPI','JEPQ','VHT','VNQ','VOX','VDC','VCR','VAW','VPU','VEA','VWO',
    'BND','HYG','LQD','SHY','IEF','IAU','GLD','SLV','UNG','USO'
]


db_client = create_client(SUPABASE_URL, SUPABASE_KEY)

# --- NOTIFICATION SYSTEM ---
def send_discord_log(message, color=0x00ff00):
    """Sends a rich embed message to Discord with Error Handling"""
    if not DISCORD_WEBHOOK_URL:
        print("⚠️ Discord Notification SKIPPED: DISCORD_WEBHOOK_URL not found in environment.")
        return

    try:
        payload = {
            "embeds": [{
                "description": message,
                "color": color,
                "footer": {"text": "Strategy Grade Engine"}
            }]
        }
        response = requests.post(DISCORD_WEBHOOK_URL, json=payload)
        
        # Check for HTTP errors (e.g. 401 Unauthorized, 404 Not Found)
        if response.status_code not in [200, 204]:
            print(f"⚠️ Discord API Error {response.status_code}: {response.text}")
            
    except Exception as e:
        print(f"⚠️ Discord Connection Error: {e}")

def process_results(pf, windows, strategy_prefix, ticker, all_results):
    """
    Extracts metrics from VectorBT Portfolio, calculates Robustness Score,
    and formats data for Supabase.
    """
    # Extract Vectorized Metrics
    # These return Series indexed by the parameter window
    total_trades = pf.trades.count()
    profit_factors = pf.trades.profit_factor()
    win_rates = pf.trades.win_rate()
    returns = pf.total_return()
    portfolio_values = pf.value()

    for window in windows:
        try:
            # Access metric for specific window
            # Note: VectorBT might return a Scalar or a Series depending on dimensions
            trades = total_trades[window]
            pf_value = profit_factors[window]
            current_win_rate = win_rates[window]
            current_return = returns[window]
            equity_series = portfolio_values[window]
        except KeyError:
            continue

        # --- FIX: Handle MultiIndex return (Series) vs Scalar ---
        # If VBT returns a Series (due to multiple parameters), take the first item
        if isinstance(trades, (pd.Series, np.ndarray)): trades = trades.iloc[0]
        if isinstance(pf_value, (pd.Series, np.ndarray)): pf_value = pf_value.iloc[0]
        if isinstance(current_win_rate, (pd.Series, np.ndarray)): current_win_rate = current_win_rate.iloc[0]
        if isinstance(current_return, (pd.Series, np.ndarray)): current_return = current_return.iloc[0]
        
        # Handle Equity Series (if MultiIndex column, it returns a DataFrame)
        if isinstance(equity_series, pd.DataFrame):
            equity_series = equity_series.iloc[:, 0]

        # --- FILTERING LOGIC ---
        # 1. Minimum Trades: Need statistical significance (>= 15)
        # 2. Valid PF: Must not be NaN or Inf
        if trades < 15 or np.isnan(pf_value) or np.isinf(pf_value): 
            continue

        # --- ROBUSTNESS FORMULA ---
        # Score = Profit Factor * ln(Total Trades)
        score = pf_value * np.log(trades)
        
        # Threshold: Only keep strategies with Score > 3.0
        if score > 3.0: 
            
            # --- DATA REDUCTION (Equity Curve) ---
            # We don't want to upload 1000 points per strategy to DB.
            # Downsample to max 200 points for the frontend chart.
            if len(equity_series) > 200:
                equity_series = equity_series.iloc[::len(equity_series)//200]
            
            equity_curve = [
                {"date": str(idx.date()), "value": round(val, 2)}
                for idx, val in equity_series.items()
            ]
            
            all_results.append({
                "symbol": ticker,
                "strategy_name": f"{strategy_prefix} ({window})",
                "robustness_score": round(float(score), 2),
                "profit_factor": round(float(pf_value), 2),
                "win_rate": round(float(current_win_rate * 100), 1),
                "total_trades": int(trades),
                "net_return_pct": round(float(current_return * 100), 1),
                "equity_curve": equity_curve
            })

def run_parameter_sweep():
    # 1. Notify Start
    if not DISCORD_WEBHOOK_URL:
        print("ℹ️ Info: DISCORD_WEBHOOK_URL is missing. No notifications will be sent.")
    
    start_msg = f"🚀 **Strategy Grade Engine Started**\nScanning {len(TICKERS)} assets..."
    print(start_msg)
    send_discord_log(start_msg, 0x3498db) # Blue Color
    
    all_results = []

    for ticker in TICKERS:
        try:
            # 2. Fetch Data (Cached)
            df = fetch_stock_data(ticker)
            if df is None or df.empty: continue
            
            # Convert to Series for VectorBT
            close_price = df['Close'].squeeze()

            # ============================================================
            # SECTION 1: RSI STRATEGY SWEEP
            # ============================================================
            # Logic: Buy < 30, Sell > 70
            # Sweep: Windows 3 to 60 (Step 1)
            # print(f"   [{ticker}] Running RSI Sweep...")
            rsi_windows = np.arange(3, 60, 1)
            rsi = vbt.RSI.run(close_price, window=rsi_windows)
            
            entries_rsi = rsi.rsi_below(30)
            exits_rsi = rsi.rsi_above(70)
            
            pf_rsi = vbt.Portfolio.from_signals(close_price, entries_rsi, exits_rsi, fees=0.001, freq='1D')
            process_results(pf_rsi, rsi_windows, "RSI Reversion", ticker, all_results)

            # ============================================================
            # SECTION 2: BOLLINGER BANDS SWEEP
            # ============================================================
            # Logic: Buy < Lower Band, Sell > Upper Band
            # Sweep: Windows 5 to 60 (Step 1)
            # print(f"   [{ticker}] Running BB Sweep...")
            bb_windows = np.arange(5, 60, 1)
            bb = vbt.BBANDS.run(close_price, window=bb_windows, alpha=2.0)
            
            entries_bb = bb.lower.gt(close_price, axis=0) # Lower Band > Price
            exits_bb = bb.upper.lt(close_price, axis=0)   # Upper Band < Price
            
            pf_bb = vbt.Portfolio.from_signals(close_price, entries_bb, exits_bb, fees=0.001, freq='1D')
            process_results(pf_bb, bb_windows, "BB Reversion", ticker, all_results)
            
        except Exception as e:
            print(f"⚠️ Error on {ticker}: {e}")

    # --- UPLOAD ---
    if all_results:
        # Sort by Robustness
        all_results.sort(key=lambda x: x['robustness_score'], reverse=True)
        top_results = all_results[:500] # Cap at Top 500
        
        try:
            # Atomic Update: Delete old high-scores, Insert new ones
            db_client.table("strategy_leaderboard").delete().neq("robustness_score", -1).execute()
            db_client.table("strategy_leaderboard").insert(top_results).execute()
            
            success_msg = f"✅ **Scan Complete**\nFound {len(all_results)} valid strategies.\nTop {len(top_results)} uploaded to Leaderboard."
            print(success_msg)
            send_discord_log(success_msg, 0x2ecc71) # Green Color
            
        except Exception as e:
            error_msg = f"❌ Database Upload Error: {e}"
            print(error_msg)
            send_discord_log(error_msg, 0xe74c3c) # Red Color
            
        # Local Backup
        csv_results = [{k: v for k, v in res.items() if k != 'equity_curve'} for res in top_results]
        pd.DataFrame(csv_results).to_csv("scan_results.csv", index=False)
    else:
        msg = "⚠️ Scan Complete but NO robust strategies found."
        print(msg)
        send_discord_log(msg, 0xf1c40f) # Yellow Color

if __name__ == "__main__":
    run_parameter_sweep()